"""Reconcile what Backblaze says is in the bucket (primary) against the local log (secondary).

Sources, in order of authority:
  1. B2 native API listing of <prefix>/snapshots/ (every object version, including hidden/deleted ones)
  2. restic's decrypted snapshot metadata (proves the object is a readable snapshot, not just a file)
  3. the local SQLite log: runs that created snapshots, forget runs that removed them, and the B2 identity
     (file id + sha1) recorded the first time each snapshot object was seen
"""
import time

import engine
import store

UPLOAD_SLACK = 600      # seconds a snapshot object may land in B2 after its run finished


def _b2_snapshot_objects():
    s = store.get_settings()
    c = engine.b2()
    bucket = c.bucket(s["b2_bucket"])
    pfx = engine.prefix() + "snapshots/"
    versions = c.list_versions(bucket["bucketId"], pfx)
    by_name = {}
    for v in versions:                      # B2 returns newest version first for each name
        by_name.setdefault(v["fileName"], []).append(v)
    objs = {}
    for name, vs in by_name.items():
        sid = name[len(pfx):]
        if len(sid) != 64:
            continue
        latest = vs[0]
        upload = next((v for v in vs if v.get("action") == "upload"), None)
        if not upload:
            continue
        objs[sid] = {
            "visible": latest.get("action") == "upload",
            "hidden_at": latest.get("uploadTimestamp") if latest.get("action") == "hide" else None,
            "file_id": upload["fileId"],
            "sha1": upload.get("contentSha1"),
            "size": upload.get("contentLength"),
            "upload_ts": upload.get("uploadTimestamp"),
            "versions": len([v for v in vs if v.get("action") == "upload"]),
        }
    return bucket, objs


def _lifecycle_days(bucket):
    """daysFromHidingToDeleting for the rule covering our prefix, None = keep forever, 'none' = no rule."""
    pfx = engine.prefix()
    best = "none"
    for r in bucket.get("lifecycleRules") or []:
        fp = r.get("fileNamePrefix") or ""
        if pfx.startswith(fp):
            best = r.get("daysFromHidingToDeleting")
    return best


def reconcile(fresh=True):
    """Build the full picture. Never raises for data problems; reports them as issues."""
    now = time.time()
    s = store.get_settings()
    issues, repo_checks = [], []

    def issue(level, text, sid=None):
        issues.append({"level": level, "text": text, "snapshot": sid})

    # ---- 1. B2 (primary)
    b2_ok, bucket, objs, b2_err = False, None, {}, None
    try:
        bucket, objs = _b2_snapshot_objects()
        b2_ok = True
    except Exception as e:
        b2_err = str(e)
        issue("error", f"Could not list the bucket through the B2 API: {e}")
    repo_checks.append({"id": "b2_api", "label": "B2 API listing", "ok": b2_ok,
                        "detail": f"{len(objs)} snapshot objects under {engine.prefix()}snapshots/" if b2_ok else b2_err})

    # ---- 2. restic metadata
    snaps, restic_err = {}, None
    try:
        snaps = {x["id"]: x for x in engine.restic_snapshots(force=fresh)}
        if not fresh and any(o["visible"] and sid not in snaps for sid, o in objs.items()):
            snaps = {x["id"]: x for x in engine.restic_snapshots(force=True)}   # B2 has news the cache lacks
    except Exception as e:
        restic_err = str(e)
        issue("error", f"restic could not read the repository: {e}")
    repo_checks.append({"id": "restic_read", "label": "Repository decrypts with your password", "ok": restic_err is None,
                        "detail": f"{len(snaps)} snapshots readable" if restic_err is None else restic_err})

    # ---- 3. local log
    for sid, o in objs.items():
        store.ledger_record_b2(sid, o["file_id"], o["sha1"], o["size"], o["upload_ts"])
    ledger = store.ledger_all()
    runs = {r["id"]: r for r in store.q("SELECT id, kind, trigger, started_at, finished_at, status, snapshot_id, tree, summary FROM runs "
                                       "WHERE snapshot_id IS NOT NULL OR kind='forget'")}

    rows = []
    for sid in sorted(set(objs) | set(ledger) | set(snaps)):
        o, led, sn = objs.get(sid), ledger.get(sid), snaps.get(sid)
        run = runs.get(led["run_id"]) if led and led.get("run_id") else None
        meta = sn or (led or {}).get("meta") or {}
        checks = []

        def chk(name, ok, detail=""):
            checks.append({"name": name, "ok": ok, "detail": detail})

        in_b2 = bool(o and o["visible"])
        hidden = bool(o and not o["visible"])
        removed = bool(led and led.get("removed_at"))
        local = bool(led and led.get("origin") == "local")

        if b2_ok and removed and not in_b2:
            chk("Gone from B2 after retention", True, "deleted version still held" if hidden else "purged")
        elif b2_ok:
            chk("Object present in B2", in_b2, "visible" if in_b2 else ("deleted (hidden version still held)" if hidden else "absent"))
        if in_b2 and restic_err is None:
            chk("Decrypts as a restic snapshot", sn is not None)
        if o and led and led.get("b2_file_id"):
            same = led["b2_file_id"] == o["file_id"] and (not led.get("b2_sha1") or led["b2_sha1"] == o["sha1"])
            chk("B2 identity unchanged since first seen", same,
                f"file id {o['file_id'][-12:]}, sha1 {(o['sha1'] or '?')[:12]}")
        if run:
            chk("Created by a logged backup run", True, f"run #{run['id']}")
            if o and o.get("upload_ts"):
                ts = o["upload_ts"] / 1000
                within = run["started_at"] - 120 <= ts <= (run["finished_at"] or now) + UPLOAD_SLACK
                chk("B2 upload time falls inside the run", within,
                    f"uploaded {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}")
            if sn and run.get("tree"):
                chk("Snapshot tree matches local log", sn.get("tree") == run["tree"], (sn.get("tree") or "")[:12])
        if removed:
            chk("Removed by a logged retention run", True, f"run #{led.get('removed_by_run')}")

        if b2_ok and o and led and led.get("b2_file_id") and led["b2_file_id"] != o["file_id"]:
            status = "identity_changed"
            issue("error", f"Snapshot {sid[:8]} was replaced in B2 after it was first recorded", sid)
        elif in_b2 and restic_err is None and sn is None:
            status = "unreadable"
            issue("error", f"Snapshot {sid[:8]} is in B2 but restic can't decrypt or parse it", sid)
        elif in_b2 and removed:
            status = "should_be_removed"
            issue("warning", f"Snapshot {sid[:8]} was forgotten by retention but is still visible in B2", sid)
        elif in_b2 and local:
            failed = [c for c in checks if not c["ok"]]
            status = "verified" if not failed else "mismatch"
            if failed:
                issue("error", f"Snapshot {sid[:8]}: {failed[0]['name'].lower()} check failed", sid)
        elif in_b2:
            status = "acknowledged" if led and led.get("acknowledged") else "b2_only"
            if status == "b2_only":
                issue("warning", f"Snapshot {sid[:8]} exists in B2 but no local run created it", sid)
        elif removed:
            status = "retired"
        elif not b2_ok:
            status = "unknown"
        elif local and run and run["status"] in ("success", "warning"):
            status = "deleted" if hidden else "missing"
            issue("error", f"Snapshot {sid[:8]} from run #{run['id']} is {'deleted (hidden) in' if hidden else 'missing from'} B2 "
                           "and no retention run removed it", sid)
        elif hidden:
            status = "retired"
        else:
            status = "local_only"

        rows.append({
            "id": sid, "short": sid[:8], "status": status, "checks": checks,
            "time": meta.get("time"), "paths": meta.get("paths"), "hostname": meta.get("hostname"),
            "tags": meta.get("tags"), "summary": meta.get("summary"), "tree": meta.get("tree"),
            "b2": o, "run": {k: run[k] for k in ("id", "trigger", "started_at", "finished_at", "status")} if run else None,
            "ledger": {k: led.get(k) for k in ("origin", "first_seen", "removed_at", "removed_by_run", "acknowledged")} if led else None,
        })
    rows.sort(key=lambda r: r.get("time") or "", reverse=True)

    # ---- repo-level checks
    if bucket:
        days = _lifecycle_days(bucket)
        if days == "none" or days is None:
            repo_checks.append({"id": "lifecycle", "label": "Deleted data is eventually purged", "ok": False, "warn": True,
                                "detail": "Bucket keeps every old version forever, so pruned data keeps costing money. "
                                          "Set lifecycle to keep prior versions for 30 days."})
            issue("warning", "B2 lifecycle keeps deleted versions forever (storage cost grows); set it to 30 days")
        else:
            repo_checks.append({"id": "lifecycle", "label": "Deleted data is eventually purged", "ok": True,
                                "detail": f"Hidden versions kept {days} day(s): a safety window against accidental or malicious deletes"})
        flc = bucket.get("fileLockConfiguration") or {}
        lock = flc.get("value") or {}
        repo_checks.append({"id": "object_lock", "label": "Object Lock", "ok": True, "info": True,
                            "detail": "unknown (key can't read retention settings)" if flc.get("isClientAuthorizedToRead") is False
                            else "enabled" if lock.get("isFileLockEnabled") else "off (pruning needs delete access)"})

    last_ok = store.last_run("backup", "success") or store.last_run("backup", "warning")
    if s.get("schedule_enabled"):
        age = (now - last_ok["finished_at"]) / 3600 if last_ok and last_ok.get("finished_at") else None
        fresh = age is not None and age < 36
        repo_checks.append({"id": "fresh", "label": "Backed up in the last 36 hours", "ok": fresh,
                            "detail": f"last good backup {age:.1f} h ago" if age is not None else "no successful backup yet"})
        if not fresh and age is not None:
            issue("warning", f"No successful backup for {age:.0f} hours")
    crun = store.last_run("check")
    chk_ok = bool(crun and crun["status"] == "success" and now - crun["started_at"] < 15 * 86400)
    repo_checks.append({"id": "check", "label": "restic integrity check in the last 15 days", "ok": chk_ok,
                        "detail": (f"last check {time.strftime('%b %d', time.localtime(crun['started_at']))}: {crun['status']}"
                                   f" ({(crun.get('detail') or {}).get('subset_pct', 0)}% of data read)" if crun else "never run")})
    if crun and crun["status"] == "failed":
        issue("error", "The last restic integrity check failed")

    # upload accounting for recent backup runs: B2 growth vs what restic says it added
    uploads = []
    for r in store.list_runs(20, "backup"):
        if not (r.get("b2_before") and r.get("b2_after") and isinstance(r.get("summary"), dict)):
            continue
        grew = r["b2_after"]["bytes"] - r["b2_before"]["bytes"]
        added = r["summary"].get("data_added_packed") or 0
        ok = grew >= added * 0.98 and grew <= added + max(64 << 20, added * 0.2)
        uploads.append({"run": r["id"], "b2_growth": grew, "restic_added": added, "ok": ok,
                        "new_objects": r["b2_after"]["objects"] - r["b2_before"]["objects"]})
    bad_up = [u for u in uploads if not u["ok"]]
    repo_checks.append({"id": "uploads", "label": "B2 growth matches what restic uploaded", "ok": not bad_up,
                        "detail": f"{len(uploads)} recent run(s) compared" + (f"; run #{bad_up[0]['run']} differs" if bad_up else "")})

    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    ok = b2_ok and restic_err is None and not any(i["level"] == "error" for i in issues)
    return {"at": now, "ok": ok, "counts": counts, "snapshots": rows, "repo_checks": repo_checks,
            "issues": issues, "uploads": uploads, "b2_calls": engine.b2().calls if b2_ok else None}


def run_and_store():
    res = reconcile()
    slim = dict(res)
    slim["snapshots"] = [{k: r[k] for k in ("id", "status")} for r in res["snapshots"]]
    res["id"] = store.add_verification(res["ok"], slim)
    return res
