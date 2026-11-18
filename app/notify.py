"""Discord webhook alerts (outbound only)."""
import json
import threading
import urllib.request

import store


def _post(content):
    url = store.get_secrets().get("discord_webhook")
    if not url:
        return

    def go():
        try:
            req = urllib.request.Request(url, data=json.dumps({"content": content[:1900], "username": "Lifeboat"}).encode(),
                                         headers={"Content-Type": "application/json", "User-Agent": "Lifeboat"})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print(f"[lifeboat] discord notify failed: {e}", flush=True)

    threading.Thread(target=go, daemon=True).start()


def _gb(n):
    return f"{(n or 0) / 1e9:.2f} GB"


def after_backup(run, verification):
    if not run:
        return
    errors = [i for i in verification["issues"] if i["level"] == "error"] if verification else []
    if run["status"] in ("failed", "cancelled"):
        _post(f"🔴 **Lifeboat backup {run['status']}** (run #{run['id']}): {run.get('error') or 'see log'}")
    elif errors:
        _post("🟠 **Lifeboat verification found problems**\n" + "\n".join(f"• {e['text']}" for e in errors[:8]))
    elif run["status"] == "warning":
        _post(f"🟡 **Lifeboat backup finished with warnings** (run #{run['id']}): {run.get('error')}")
    elif store.get_settings().get("notify_success"):
        s = run.get("summary") or {}
        _post(f"🟢 Lifeboat backup ok: snapshot `{(run.get('snapshot_id') or '')[:8]}`, "
              f"{s.get('files_new', 0)} new / {s.get('files_changed', 0)} changed files, {_gb(s.get('data_added_packed'))} uploaded; "
              f"{verification['counts'].get('verified', 0) if verification else '?'} versions verified in B2")


def after_verify(res):
    errors = [i for i in res["issues"] if i["level"] == "error"]
    if errors:
        _post("🟠 **Lifeboat verification found problems**\n" + "\n".join(f"• {e['text']}" for e in errors[:8]))


def test():
    _post("👋 Lifeboat test message: alerts are wired up.")
