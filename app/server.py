"""Lifeboat HTTP server: JSON API, server-sent events, streaming downloads, static UI, and the scheduler."""
import ipaddress
import json
import mimetypes
import os
import secrets
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import b2 as b2mod
import engine
import notify
import store
import verify

PORT = int(os.environ.get("LIFEBOAT_PORT", "8850"))
STATIC = os.environ.get("LIFEBOAT_STATIC", os.path.join(os.path.dirname(__file__), "..", "static"))
ALLOWED_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "::1/128", "fd7a:115c:a1e0::/48")]

_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn, force=False):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not force and time.time() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (time.time(), val)
    return val


def drop_cache(*keys):
    with _cache_lock:
        for k in keys or list(_cache):
            _cache.pop(k, None)


# ---------------------------------------------------------------- scheduling

CATCH_UP = timedelta(hours=6)    # a slot missed while the container was down still runs within this window


def _today_slot(s, now):
    hh, mm = (int(x) for x in (s.get("schedule_time") or "02:30").split(":"))
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def next_scheduled(s=None, now=None):
    s = s or store.get_settings()
    if not s.get("schedule_enabled") or not engine.configured():
        return None
    now = now or datetime.now()
    slot = _today_slot(s, now)
    if s.get("_last_slot") == slot.strftime("%Y-%m-%d") or now > slot + CATCH_UP:
        slot += timedelta(days=1)
    return slot


def scheduler():
    while True:
        time.sleep(20)
        try:
            s = store.get_settings()
            now = datetime.now()
            slot = next_scheduled(s, now)
            if slot and slot <= now:
                store.set_settings({"_last_slot": slot.strftime("%Y-%m-%d")})
                last = store.last_run("backup")
                if not (last and last["started_at"] >= slot.timestamp()):
                    engine.enqueue("backup", "schedule")
        except Exception as e:
            print(f"[lifeboat] scheduler: {e!r}", flush=True)


# ---------------------------------------------------------------- views

def public_settings():
    s = store.get_settings()
    sec = store.get_secrets()
    s["secrets"] = {k: bool(sec.get(k)) for k in store.SECRET_KEYS}
    s["b2_key_id_hint"] = (sec.get("b2_key_id") or "")[:6] + "…" if sec.get("b2_key_id") else ""
    return s


def overview():
    s = store.get_settings()
    runs = store.list_runs(1, "backup")
    lv = store.last_verification()
    nxt = next_scheduled(s)
    last_ok = store.last_run("backup", "success") or store.last_run("backup", "warning")
    return {
        "configured": engine.configured(),
        "host": engine.HOST,
        "restic": cached("restic_version", 3600, engine.restic_version),
        "settings": public_settings(),
        "next_run": nxt.timestamp() if nxt else None,
        "last_backup": runs[0] if runs else None,
        "last_good_backup": last_ok,
        "verification": {"at": lv["at"], "ok": bool(lv["ok"]), "counts": lv["result"].get("counts"),
                         "issues": lv["result"].get("issues", [])[:20]} if lv else None,
        "restore_root": engine.RESTORE_ROOT if os.path.isdir(engine.RESTORE_ROOT) else None,
        "state": engine.snapshot_state(),
        "server_time": time.time(),
    }


def recovery_kit():
    s, sec = store.get_settings(), store.get_secrets()
    try:
        repo = engine.repo_url()
    except Exception:
        repo = "(not configured)"
    return f"""LIFEBOAT RECOVERY KIT — generated {datetime.now():%Y-%m-%d %H:%M}
Keep this in your password manager. Anyone with it can read your backups.
Without the repository password the backup CANNOT be decrypted by anyone, including Backblaze.

Repository   : {repo}
Bucket       : {s.get('b2_bucket')}
Prefix       : {s.get('b2_prefix')}
B2 key ID    : {sec.get('b2_key_id', '')}
B2 app key   : {sec.get('b2_app_key', '')}
Repo password: {sec.get('repo_password', '')}
Host name    : {engine.HOST}

RESTORE ON ANY MACHINE (unRAID, Linux, Mac, Windows) WITH PLAIN RESTIC
  export AWS_ACCESS_KEY_ID='{sec.get('b2_key_id', '')}'
  export AWS_SECRET_ACCESS_KEY='<B2 app key above>'
  export RESTIC_REPOSITORY='{repo}'
  export RESTIC_PASSWORD='<repo password above>'
  restic snapshots                                  # list versions
  restic restore latest --target /mnt/user/restore  # everything, newest version
  restic restore <id> --target X --include /source/photo   # one folder from one version
  restic mount /mnt/restic                          # browse every version as folders

OR RUN LIFEBOAT AGAIN (same UI, same history in B2)
  Start the lifeboat container on the new machine, open Settings, enter the
  B2 key, bucket, prefix and choose "Connect to existing repository" with the
  password above. Set LIFEBOAT_HOST={engine.HOST} to continue the same version
  lineage, and mount the new shares under /source with the same names.
"""


# ---------------------------------------------------------------- HTTP

class H(BaseHTTPRequestHandler):
    server_version = "Lifeboat"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _allowed(self):
        try:
            ip = ipaddress.ip_address(self.client_address[0].replace("::ffff:", ""))
        except ValueError:
            return False
        return any(ip in n for n in ALLOWED_NETS)

    def _send(self, code, body, ctype="application/json", headers=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, default=str).encode() if ctype == "application/json" else str(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, {"error": msg})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1 << 20:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if not self._allowed():
            return self._err(403, "LAN / tailnet only")
        u = urllib.parse.urlparse(self.path)
        qs = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            return self.route_get(u.path, qs)
        except engine.NotConfigured as e:
            return self._err(409, str(e))
        except (b2mod.B2Error, RuntimeError, ValueError) as e:
            return self._err(502 if isinstance(e, b2mod.B2Error) else 400, str(e))
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        if not self._allowed():
            return self._err(403, "LAN / tailnet only")
        if self.headers.get("X-Lifeboat") != "1":
            return self._err(403, "missing X-Lifeboat header")
        try:
            return self.route_post(urllib.parse.urlparse(self.path).path, self._body())
        except engine.NotConfigured as e:
            return self._err(409, str(e))
        except (b2mod.B2Error, RuntimeError, ValueError, KeyError) as e:
            return self._err(502 if isinstance(e, b2mod.B2Error) else 400, str(e))

    # ---- GET routes
    def route_get(self, path, qs):
        if path == "/api/overview":
            return self._send(200, overview())
        if path == "/api/events":
            return self.sse()
        if path == "/api/versions":
            res = cached("versions", 60, lambda: verify.reconcile(fresh=False), force=qs.get("refresh") == "1")
            return self._send(200, res)
        if path == "/api/storage":
            def calc():
                m = engine.b2_storage(include_versions=True)
                if m:
                    price = float(store.get_settings().get("price_per_tb") or 0)
                    m["monthly_cost"] = round((m["bytes"] + m.get("hidden_bytes", 0)) / 1e12 * price, 2)
                return m
            return self._send(200, cached("storage", 600, calc, force=qs.get("refresh") == "1"))
        if path == "/api/runs":
            runs = store.list_runs(min(int(qs.get("limit", 100)), 500), qs.get("kind") or None)
            return self._send(200, runs)
        if path.startswith("/api/runs/"):
            rid = int(path.rsplit("/", 1)[1])
            run = store.get_run(rid)
            if not run:
                return self._err(404, "no such run")
            run["log"] = store.run_log(rid)
            return self._send(200, run)
        if path == "/api/verifications":
            rows = store.q("SELECT id, at, ok, result FROM verifications ORDER BY id DESC LIMIT 60")
            out = []
            for r in rows:
                res = json.loads(r["result"])
                out.append({"id": r["id"], "at": r["at"], "ok": bool(r["ok"]), "counts": res.get("counts"),
                            "issues": len(res.get("issues", []))})
            return self._send(200, out)
        if path == "/api/browse":
            return self._send(200, engine.ls(qs["snapshot"], qs.get("path", "/")))
        if path == "/api/download":
            return self.download(qs)
        if path == "/api/folders":
            return self._send(200, {"root": engine.SOURCE_ROOT, "path": qs.get("path") or engine.SOURCE_ROOT,
                                    "folders": engine.source_tree(qs.get("path"))})
        if path == "/api/recovery-kit":
            return self._send(200, recovery_kit(), "text/plain; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="lifeboat-recovery-kit.txt"'})
        return self.static(path)

    def sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(b"retry: 3000\n\n")
        version = -1
        try:
            while True:
                st = engine.snapshot_state()
                if st["version"] != version:
                    version = st["version"]
                    self.wfile.write(f"data: {json.dumps(st)}\n\n".encode())
                else:
                    self.wfile.write(b"event: ping\ndata: {}\n\n")   # visible to JS, so the page can tell the stream is alive
                self.wfile.flush()
                engine.wait_change(version, 15)
                time.sleep(0.25)        # coalesce bursts of updates
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def download(self, qs):
        snap, p, kind = qs["snapshot"], qs.get("path") or "/", qs.get("type", "file")
        if not all(c in "0123456789abcdef" for c in snap) and snap != "latest":
            raise ValueError("bad snapshot id")
        archive = {"zip": "zip", "tar": "tar"}.get(kind)
        base = os.path.basename(p.rstrip("/")) or f"snapshot-{snap[:8]}"
        fname = base + (f".{archive}" if archive else "")
        proc = engine.dump_proc(snap, p, archive)
        first = proc.stdout.read(65536)
        if not first and proc.wait() != 0:
            return self._err(400, engine.errmsg(proc.stderr.read().decode(errors="replace"), "restic dump failed"))
        self.send_response(200)
        ctype = {"zip": "application/zip", "tar": "application/x-tar"}.get(archive) or \
            mimetypes.guess_type(fname)[0] or "application/octet-stream"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(fname))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            chunk = first
            while chunk:
                self.wfile.write(chunk)
                chunk = proc.stdout.read(1 << 20)
        except (BrokenPipeError, ConnectionResetError):
            proc.kill()
        finally:
            proc.wait()

    def static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        full = os.path.realpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(os.path.realpath(STATIC)) or not os.path.isfile(full):
            full = os.path.join(STATIC, "index.html")
        with open(full, "rb") as f:
            body = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, body, ctype, {"Cache-Control": "no-cache"})

    # ---- POST routes
    def route_post(self, path, b):
        if path == "/api/jobs":
            kind = b.get("kind")
            if kind not in engine.JOBS:
                raise ValueError("unknown job")
            params = {}
            if kind == "check":
                params["subset"] = int(b.get("subset", store.get_settings().get("check_subset_pct", 2)))
            if kind == "restore":
                params = {"snapshot": b["snapshot"], "paths": b.get("paths") or [],
                          "target_name": b.get("target_name") or ""}
            if kind != "verify" and not engine.configured():
                raise engine.NotConfigured("Connect a repository first (Settings)")
            ok = engine.enqueue(kind, "manual", **params)
            drop_cache("versions", "storage")
            return self._send(202 if ok else 409, {"queued": ok})
        if path == "/api/cancel":
            return self._send(200, {"cancelled": engine.cancel()})
        if path == "/api/settings":
            clean = {}
            for k, v in b.items():
                if k in store.DEFAULT_SETTINGS:
                    clean[k] = v
            if "schedule_time" in clean:
                hh, mm = clean["schedule_time"].split(":")
                assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
            if "sources" in clean:
                root = os.path.realpath(engine.SOURCE_ROOT)
                for sp in clean["sources"]:
                    if not os.path.realpath(sp).startswith(root + "/"):
                        raise ValueError(f"{sp} is outside {root}")
            store.set_settings(clean)
            if "b2_bucket" in clean or "b2_prefix" in clean:
                store.set_settings({"_repo_ready": False})
            drop_cache()
            engine.bump()
            return self._send(200, public_settings())
        if path == "/api/secrets":
            store.set_secrets({k: (v or "").strip() for k, v in b.items() if k in store.SECRET_KEYS})
            if {"b2_key_id", "b2_app_key", "repo_password"} & set(b):
                store.set_settings({"_repo_ready": False})
            drop_cache()
            engine.bump()
            return self._send(200, public_settings())
        if path == "/api/b2/test":
            return self._send(200, self.b2_test())
        if path == "/api/repo/connect":
            return self._send(200, self.repo_connect(b))
        if path == "/api/folders/size":
            threading.Thread(target=engine.measure_size, args=(b["path"],), daemon=True).start()
            return self._send(202, {"ok": True})
        if path == "/api/ack":
            store.ledger_acknowledge(b["snapshot"])
            drop_cache("versions")
            return self._send(200, {"ok": True})
        if path == "/api/notify/test":
            notify.test()
            return self._send(200, {"ok": True})
        if path == "/api/password/generate":
            return self._send(200, {"password": "-".join(secrets.token_urlsafe(6) for _ in range(5))})
        return self._err(404, "not found")

    def b2_test(self):
        s = store.get_settings()
        c = engine.b2()
        c.authorize(force=True)
        info = c.key_info()
        out = {"ok": True, "key": info, "bucket": None, "warnings": []}
        need = {"listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"}
        missing = sorted(need - set(info["capabilities"]))
        if missing:
            out["warnings"].append("Key is missing capabilities: " + ", ".join(missing))
        if s.get("b2_bucket"):
            bk = c.bucket(s["b2_bucket"])
            out["bucket"] = {"name": bk["bucketName"], "type": bk.get("bucketType"),
                             "lifecycle": bk.get("lifecycleRules"),
                             "encryption": (bk.get("defaultServerSideEncryption") or {}).get("value"),
                             "object_lock": None if (bk.get("fileLockConfiguration") or {}).get("isClientAuthorizedToRead") is False
                             else ((bk.get("fileLockConfiguration") or {}).get("value") or {}).get("isFileLockEnabled")}
            if bk.get("bucketType") != "allPrivate":
                out["warnings"].append("Bucket is not private")
            if verify._lifecycle_days(bk) in ("none", None):
                out["warnings"].append("Lifecycle keeps all versions forever: set 'Keep prior versions for 30 days'")
        return out

    def repo_connect(self, b):
        """Connect to an existing repository, or create one when asked to."""
        if b.get("password"):
            store.set_secrets({"repo_password": b["password"]})
        code, out, err = engine.run_restic(["cat", "config", "--no-lock"], timeout=120)
        if code == 0:
            store.set_settings({"_repo_ready": True})
            engine.invalidate()
            drop_cache()
            snaps = engine.restic_snapshots(force=True)
            engine.bump()
            return {"connected": True, "created": False, "snapshots": len(snaps)}
        low = err.lower()
        if "wrong password" in low or "no key found" in low:
            raise ValueError("A repository exists here but the password is wrong")
        if not b.get("create"):
            return {"connected": False, "exists": False, "detail": engine.errmsg(err, "")}
        code, out, err = engine.run_restic(["init"], timeout=300)
        if code != 0:
            raise RuntimeError(engine.errmsg(err, "restic init failed"))
        store.set_settings({"_repo_ready": True})
        drop_cache()
        engine.bump()
        return {"connected": True, "created": True, "snapshots": 0}


def main():
    store.conn()
    store.interrupted_runs_cleanup()
    os.makedirs(os.path.join(store.DATA_DIR, "cache"), exist_ok=True)
    threading.Thread(target=engine.worker, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    print(f"[lifeboat] listening on :{PORT} host={engine.HOST} restic={engine.restic_version()}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
