"""restic wrapper, the single-job worker, live progress, and B2-side storage measurements."""
import json
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime

import b2 as b2mod
import notify
import store

RESTIC = os.environ.get("LIFEBOAT_RESTIC", "restic")
HOST = os.environ.get("LIFEBOAT_HOST", "phoenix")
SOURCE_ROOT = os.environ.get("LIFEBOAT_SOURCE_ROOT", "/source")
RESTORE_ROOT = os.environ.get("LIFEBOAT_RESTORE_ROOT", "/restore")
REPO_OVERRIDE = os.environ.get("LIFEBOAT_REPO_OVERRIDE")   # tests: a local repo path instead of B2/S3
TAG = "lifeboat"


class NotConfigured(Exception):
    pass


# ---------------------------------------------------------------- config

_b2_client = None
_b2_key = None


def b2():
    global _b2_client, _b2_key
    sec = store.get_secrets()
    key = (sec.get("b2_key_id"), sec.get("b2_app_key"))
    if not all(key):
        raise NotConfigured("Backblaze key not set")
    if _b2_client is None or _b2_key != key:
        _b2_client, _b2_key = b2mod.B2(*key), key
    return _b2_client


def prefix():
    p = (store.get_settings().get("b2_prefix") or "").strip("/")
    return p + "/" if p else ""


def repo_url():
    if REPO_OVERRIDE:
        return REPO_OVERRIDE
    s = store.get_settings()
    if not s.get("b2_bucket"):
        raise NotConfigured("Bucket not set")
    ep = b2().s3_endpoint().rstrip("/")
    return f"s3:{ep}/{s['b2_bucket']}/{prefix().rstrip('/')}".rstrip("/")


def restic_env():
    sec = store.get_secrets()
    if not sec.get("repo_password"):
        raise NotConfigured("Repository password not set")
    env = dict(os.environ)
    env.update({
        "RESTIC_REPOSITORY": repo_url(),
        "RESTIC_PASSWORD": sec["repo_password"],
        "RESTIC_CACHE_DIR": os.path.join(store.DATA_DIR, "cache"),
        "RESTIC_PROGRESS_FPS": "1",
    })
    if not REPO_OVERRIDE:
        env["AWS_ACCESS_KEY_ID"] = sec["b2_key_id"]
        env["AWS_SECRET_ACCESS_KEY"] = sec["b2_app_key"]
        m = re.search(r"s3\.([a-z0-9-]+)\.backblazeb2\.com", b2().s3_endpoint())
        if m:
            env["AWS_DEFAULT_REGION"] = m.group(1)
    return env


def configured():
    try:
        restic_env()
        return bool(store.get_settings().get("_repo_ready"))
    except (NotConfigured, b2mod.B2Error):
        return False


def run_restic(args, timeout=600, input_text=None):
    """Run a short restic command; returns (code, stdout, stderr)."""
    p = subprocess.run([RESTIC, *args], env=restic_env(), capture_output=True, text=True,
                       timeout=timeout, input=input_text)
    return p.returncode, p.stdout, p.stderr


def errmsg(err, fallback="restic failed"):
    """Last meaningful stderr line; restic emits JSON exit_error objects when --json is on."""
    lines = [l for l in (err or "").strip().splitlines() if l.strip()]
    if not lines:
        return fallback
    last = lines[-1]
    if last.startswith("{"):
        try:
            return json.loads(last).get("message") or last
        except ValueError:
            pass
    return last


def restic_version():
    try:
        return subprocess.run([RESTIC, "version"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:  # noqa
        return f"unavailable ({e})"


# ---------------------------------------------------------------- caches

_snap_cache = {"at": 0, "data": None}
_cache_lock = threading.Lock()


def invalidate():
    with _cache_lock:
        _snap_cache["at"] = 0


def restic_snapshots(force=False):
    """Decrypted snapshot metadata straight from the repository (reads B2)."""
    with _cache_lock:
        if not force and _snap_cache["data"] is not None and time.time() - _snap_cache["at"] < 600:
            return _snap_cache["data"]
    code, out, err = run_restic(["snapshots", "--json", "--no-lock"], timeout=300)
    if code != 0:
        raise RuntimeError(errmsg(err, f"restic exited {code}"))
    data = json.loads(out or "[]")
    with _cache_lock:
        _snap_cache.update(at=time.time(), data=data)
    for s in data:
        store.ledger_set_meta(s["id"], {k: s.get(k) for k in ("time", "tree", "paths", "hostname", "tags", "summary", "program_version")})
    return data


def b2_storage(include_versions=False):
    """Bytes and object counts in the bucket under our prefix, measured by B2 (not restic)."""
    if REPO_OVERRIDE and os.environ.get("LIFEBOAT_B2_API") is None:
        return None
    s = store.get_settings()
    c = b2()
    bucket = c.bucket(s["b2_bucket"])
    files = c.list_names(bucket["bucketId"], prefix())
    out = {"at": time.time(), "objects": len(files), "bytes": 0, "by_kind": {}}
    for f in files:
        size = f.get("contentLength") or 0
        out["bytes"] += size
        kind = f["fileName"][len(prefix()):].split("/", 1)[0] or "?"
        k = out["by_kind"].setdefault(kind, {"objects": 0, "bytes": 0})
        k["objects"] += 1
        k["bytes"] += size
    if include_versions:
        vers = c.list_versions(bucket["bucketId"], prefix())
        visible_ids = {f["fileId"] for f in files}
        hidden = [v for v in vers if v.get("action") == "upload" and v["fileId"] not in visible_ids]
        out["hidden_objects"] = len(hidden)
        out["hidden_bytes"] = sum(v.get("contentLength") or 0 for v in hidden)
    return out


# ---------------------------------------------------------------- live state

state_lock = threading.Lock()
state = {"job": None, "queue": [], "version": 0}
_tx_hist = []
_listeners = []
_jobq = queue.Queue()
_current_proc = None
_cancel = threading.Event()


def bump(**changes):
    with state_lock:
        state.update(changes)
        state["version"] += 1
        for ev in list(_listeners):
            ev.set()


def wait_change(version, timeout=15):
    ev = threading.Event()
    with state_lock:
        if state["version"] != version:
            return
        _listeners.append(ev)
    ev.wait(timeout)
    with state_lock:
        if ev in _listeners:
            _listeners.remove(ev)


def snapshot_state():
    with state_lock:
        return json.loads(json.dumps(state))


def _net_tx():
    try:
        total = 0
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                name, rest = line.split(":", 1)
                if name.strip() != "lo":
                    total += int(rest.split()[8])
        return total
    except Exception:
        return None


def _tx_sampler(stop):
    last, last_t = _net_tx(), time.time()
    while not stop.wait(1):
        now, t = _net_tx(), time.time()
        if now is None or last is None:
            continue
        rate = max(0, (now - last) / max(t - last_t, 0.001))
        last, last_t = now, t
        with state_lock:
            job = state.get("job")
            if job:
                job["tx_rate"] = rate
                job["tx_total"] = job.get("tx_total", 0) + rate * 1
                hist = job.setdefault("tx_hist", [])
                hist.append(round(rate))
                del hist[:-180]
        bump()


# ---------------------------------------------------------------- job queue

def enqueue(kind, trigger="manual", **params):
    with state_lock:
        if state["job"] and state["job"]["kind"] == kind and kind != "restore":
            return False
        if any(j["kind"] == kind for j in state["queue"]) and kind != "restore":
            return False
        state["queue"].append({"kind": kind, "trigger": trigger, "params": params})
    _jobq.put({"kind": kind, "trigger": trigger, "params": params})
    bump()
    return True


def cancel():
    _cancel.set()
    p = _current_proc
    if p and p.poll() is None:
        p.send_signal(signal.SIGINT)
        return True
    return False


def worker():
    while True:
        job = _jobq.get()
        with state_lock:
            for i, j in enumerate(state["queue"]):
                if j["kind"] == job["kind"] and j["params"] == job["params"]:
                    state["queue"].pop(i)
                    break
        _cancel.clear()
        try:
            JOBS[job["kind"]](job["trigger"], **job["params"])
        except Exception as e:  # last-resort guard; jobs record their own failures
            print(f"[lifeboat] job {job['kind']} crashed: {e!r}", flush=True)
        finally:
            bump(job=None)
            invalidate()


def _begin(kind, trigger, title):
    run_id = store.start_run(kind, trigger)
    bump(job={"kind": kind, "run_id": run_id, "title": title, "trigger": trigger,
              "started_at": time.time(), "progress": None, "tx_rate": 0, "tx_hist": [], "phase": "starting"})
    return run_id


def _phase(phase, **extra):
    with state_lock:
        if state["job"]:
            state["job"]["phase"] = phase
            state["job"].update(extra)
    bump()


def _stream(run_id, args, on_json=None, timeout=None):
    """Run a long restic command, feed JSON lines to on_json, log everything else. Returns exit code."""
    global _current_proc
    env = restic_env()
    store.log(run_id, "$ restic " + shlex.join(args), "cmd")
    p = subprocess.Popen([RESTIC, *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, bufsize=1)
    _current_proc = p
    stop = threading.Event()
    sampler = threading.Thread(target=_tx_sampler, args=(stop,), daemon=True)
    sampler.start()

    def pump_err():
        for line in p.stderr:
            line = line.rstrip()
            if line:
                store.log(run_id, line, "warn" if "error" in line.lower() or "warning" in line.lower() else "info")

    te = threading.Thread(target=pump_err, daemon=True)
    te.start()
    started = time.time()
    try:
        for line in p.stdout:
            line = line.rstrip()
            if not line:
                continue
            if on_json and line[:1] in "{[":
                try:
                    on_json(json.loads(line))
                    continue
                except ValueError:
                    pass
            store.log(run_id, line)
            if timeout and time.time() - started > timeout:
                p.send_signal(signal.SIGINT)
        p.wait()
    finally:
        stop.set()
        te.join(5)
        _current_proc = None
    return p.returncode


def _finish(run_id, status, error=None, **fields):
    store.update_run(run_id, status=status, finished_at=time.time(), error=error, **fields)
    store.prune_old()


def _measure(run_id, label):
    try:
        m = b2_storage()
        if m is not None:
            store.log(run_id, f"B2 {label}: {m['objects']} objects, {human(m['bytes'])}")
        return m
    except Exception as e:
        store.log(run_id, f"Could not measure B2 {label}: {e}", "warn")
        return None


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1000


# ---------------------------------------------------------------- jobs

def job_backup(trigger, **_):
    s = store.get_settings()
    run_id = _begin("backup", trigger, "Backing up to B2")
    try:
        if not configured():
            raise NotConfigured("Lifeboat isn't connected to a repository yet (Settings)")
        sources = [p for p in s["sources"] if os.path.exists(p)]
        missing = [p for p in s["sources"] if not os.path.exists(p)]
        for m in missing:
            store.log(run_id, f"Source folder not found, skipped: {m}", "warn")
        if not sources:
            raise NotConfigured("No source folders selected (Settings → Folders)")
        _phase("measuring B2")
        before = _measure(run_id, "before")
        store.update_run(run_id, b2_before=before)
        run_restic(["unlock"], timeout=120)

        args = ["backup", "--json", "--host", HOST, "--tag", TAG, "--exclude-caches"]
        for e in s.get("excludes") or []:
            args += ["--exclude", e]
        if s.get("limit_upload_kib"):
            args += ["--limit-upload", str(int(s["limit_upload_kib"]))]
        args += sources
        summary = {}
        errors = []

        def on_json(msg):
            t = msg.get("message_type")
            if t == "status":
                with state_lock:
                    if state["job"]:
                        state["job"]["phase"] = "uploading"
                        state["job"]["progress"] = {k: msg.get(k) for k in (
                            "percent_done", "total_files", "files_done", "total_bytes", "bytes_done",
                            "seconds_elapsed", "seconds_remaining", "current_files", "error_count")}
                bump()
            elif t == "error":
                err = msg.get("error", {}).get("message", "") if isinstance(msg.get("error"), dict) else str(msg.get("error"))
                errors.append(f"{msg.get('item', '')}: {err}")
                store.log(run_id, f"{msg.get('during', 'error')}: {msg.get('item', '')}: {err}", "warn")
            elif t == "summary":
                summary.update(msg)
            elif t == "verbose_status":
                pass

        _phase("scanning")
        code = _stream(run_id, args, on_json)
        snap = summary.get("snapshot_id")
        if _cancel.is_set():
            status, error = "cancelled", "Cancelled from the web UI (uploaded data is kept and reused next run)"
        elif code == 0 and snap:
            status, error = "success", None
        elif code == 3 and snap:
            status, error = "warning", f"{len(errors)} file(s) could not be read; the rest were backed up"
        else:
            status, error = "failed", (errors[-1] if errors else f"restic exited with code {code}")
        tree = None
        if snap:
            store.ledger_add_local(snap, run_id)
            invalidate()
            try:
                for sn in restic_snapshots(force=True):
                    if sn["id"] == snap:
                        tree = sn.get("tree")
            except Exception as e:
                store.log(run_id, f"Could not read back snapshot metadata: {e}", "warn")
        _phase("measuring B2")
        after = _measure(run_id, "after")
        detail = {"errors": errors[:200], "sources": sources}
        store.update_run(run_id, b2_after=after)
        _finish(run_id, status, error, snapshot_id=snap, tree=tree, summary=summary, detail=detail)
        store.log(run_id, f"Backup {status}" + (f": snapshot {snap[:8]}" if snap else ""), "ok" if status == "success" else "warn")
    except Exception as e:
        store.log(run_id, str(e), "error")
        _finish(run_id, "failed", str(e))
        status = "failed"

    run = store.get_run(run_id)
    if trigger == "schedule" and status in ("success", "warning"):
        job_forget(trigger)
        wd = datetime.now().weekday()
        if wd == int(s.get("prune_weekday", 6)):
            job_prune(trigger)
        if wd == int(s.get("check_weekday", 6)):
            job_check(trigger, subset=s.get("check_subset_pct", 2))
    import verify
    result = verify.run_and_store()
    notify.after_backup(run, result)


def job_forget(trigger, **_):
    s = store.get_settings()
    r = s.get("retention") or {}
    run_id = _begin("forget", trigger, "Applying retention")
    try:
        args = ["forget", "--json", "--host", HOST, "--tag", TAG, "--group-by", "host,tags"]
        for k in ("daily", "weekly", "monthly", "yearly"):
            if int(r.get(k) or 0) > 0:
                args += [f"--keep-{k}", str(int(r[k]))]
        if not any(a.startswith("--keep-") for a in args):
            raise ValueError("Retention policy keeps nothing; refusing to forget")
        groups = []
        code = _stream(run_id, args, lambda m: groups.extend(m if isinstance(m, list) else [m]))
        removed, kept = [], 0
        for grp in groups:
            if isinstance(grp, dict):
                removed += [x["id"] for x in grp.get("remove") or []]
                kept += len(grp.get("keep") or [])
        for sid in removed:
            store.ledger_mark_removed(sid, run_id)
            store.log(run_id, f"Removed by retention: {sid[:8]}")
        store.log(run_id, f"Retention kept {kept} version(s), removed {len(removed)}")
        _finish(run_id, "success" if code == 0 else "failed",
                None if code == 0 else f"restic exited with code {code}", detail={"removed": removed})
    except Exception as e:
        store.log(run_id, str(e), "error")
        _finish(run_id, "failed", str(e))


def job_prune(trigger, **_):
    run_id = _begin("prune", trigger, "Pruning unreferenced data")
    try:
        before = _measure(run_id, "before")
        code = _stream(run_id, ["prune"])
        after = _measure(run_id, "after")
        _finish(run_id, "success" if code == 0 else "failed", None if code == 0 else f"restic exited with code {code}",
                b2_before=before, b2_after=after)
    except Exception as e:
        store.log(run_id, str(e), "error")
        _finish(run_id, "failed", str(e))


def job_check(trigger, subset=2, **_):
    subset = max(0, min(100, int(subset or 0)))
    run_id = _begin("check", trigger, f"Integrity check (reading {subset}% of data)" if subset else "Integrity check")
    try:
        args = ["check"] + ([f"--read-data-subset={subset}%"] if subset else [])
        code = _stream(run_id, args)
        _finish(run_id, "success" if code == 0 else "failed",
                None if code == 0 else "restic check reported problems (see log)", detail={"subset_pct": subset})
    except Exception as e:
        store.log(run_id, str(e), "error")
        _finish(run_id, "failed", str(e))


def job_verify(trigger, **_):
    run_id = _begin("verify", trigger, "Reconciling B2 against the local log")
    try:
        import verify
        res = verify.run_and_store()
        bad = [i for i in res["issues"] if i["level"] == "error"]
        for i in res["issues"]:
            store.log(run_id, i["text"], "warn" if i["level"] != "error" else "error")
        store.log(run_id, f"{res['counts'].get('verified', 0)} versions verified, {len(res['issues'])} issue(s)")
        _finish(run_id, "failed" if bad else ("warning" if res["issues"] else "success"),
                bad[0]["text"] if bad else None, detail={"verification_id": res.get("id")})
        notify.after_verify(res)
    except Exception as e:
        store.log(run_id, str(e), "error")
        _finish(run_id, "failed", str(e))


def job_restore(trigger, snapshot, paths, target_name, **_):
    run_id = _begin("restore", trigger, f"Restoring to {target_name}")
    try:
        target = os.path.join(RESTORE_ROOT, safe_name(target_name))
        if not os.path.isdir(RESTORE_ROOT):
            raise NotConfigured(f"No restore folder is mounted at {RESTORE_ROOT}")
        os.makedirs(target, exist_ok=True)
        args = ["restore", "--json", snapshot, "--target", target]
        for p in paths or []:
            args += ["--include", p]

        def on_json(msg):
            if msg.get("message_type") == "status":
                with state_lock:
                    if state["job"]:
                        state["job"]["phase"] = "downloading"
                        state["job"]["progress"] = {k: msg.get(k) for k in (
                            "percent_done", "total_files", "files_restored", "total_bytes", "bytes_restored", "seconds_elapsed")}
                bump()
            elif msg.get("message_type") == "summary":
                store.log(run_id, f"Restored {msg.get('files_restored', '?')} files, {human(msg.get('bytes_restored'))}")
            elif msg.get("message_type") == "error":
                store.log(run_id, json.dumps(msg), "warn")

        code = _stream(run_id, args, on_json)
        _finish(run_id, "success" if code == 0 else "failed", None if code == 0 else f"restic exited with code {code}",
                snapshot_id=snapshot, detail={"target": target, "paths": paths})
    except Exception as e:
        store.log(run_id, str(e), "error")
        _finish(run_id, "failed", str(e))


JOBS = {"backup": job_backup, "forget": job_forget, "prune": job_prune, "check": job_check,
        "verify": job_verify, "restore": job_restore}


def safe_name(n):
    n = re.sub(r"[^A-Za-z0-9 ._-]+", "-", n or "").strip(" .-")
    return n or datetime.now().strftime("Lifeboat restore %Y-%m-%d %H%M")


# ---------------------------------------------------------------- browse & download

def ls(snapshot, path):
    path = "/" + path.strip("/") if path and path != "/" else "/"
    code, out, err = run_restic(["ls", "--json", "--no-lock", snapshot, path], timeout=300)
    if code != 0:
        raise RuntimeError(errmsg(err, "restic ls failed"))
    entries = []
    for line in out.splitlines():
        try:
            n = json.loads(line)
        except ValueError:
            continue
        if n.get("struct_type") != "node" or n.get("path") == path:
            continue
        entries.append({"name": n["name"], "path": n["path"], "type": n["type"],
                        "size": n.get("size"), "mtime": n.get("mtime")})
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return entries


def dump_proc(snapshot, path, archive=None):
    args = ["dump", "--no-lock", snapshot, path]
    if archive:
        args[1:1] = ["--archive", archive]
    return subprocess.Popen([RESTIC, *args], env=restic_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)


# ---------------------------------------------------------------- folders on the NAS

_size_cache = {}


def source_tree(path=None):
    base = os.path.realpath(path or SOURCE_ROOT)
    if not (base == os.path.realpath(SOURCE_ROOT) or base.startswith(os.path.realpath(SOURCE_ROOT) + "/")):
        raise ValueError("outside source root")
    out = []
    try:
        names = sorted(os.listdir(base), key=str.lower)
    except OSError as e:
        raise ValueError(str(e))
    for n in names:
        if n.startswith("@") or n in ("#recycle", "#snapshot"):
            continue
        full = os.path.join(base, n)
        if os.path.isdir(full) and not os.path.islink(full):
            out.append({"name": n, "path": full, "size": _size_cache.get(full)})
    return out


def measure_size(path):
    try:
        p = subprocess.run(["du", "-sb", path], capture_output=True, text=True, timeout=3600)
        _size_cache[path] = {"bytes": int(p.stdout.split()[0]), "at": time.time()}
    except Exception:
        _size_cache[path] = {"bytes": None, "at": time.time()}
    bump()


def disk_free(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None
