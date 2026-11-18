"""SQLite-backed local log: settings, job runs, run log lines, and the snapshot ledger.

The ledger is the local side of verification: every snapshot this instance
created or has ever seen in B2 gets a row, along with the B2 object identity
(file id, sha1, size, upload time) recorded the first time it was observed.
"""
import json
import os
import sqlite3
import threading
import time

DATA_DIR = os.environ.get("LIFEBOAT_DATA", "/data")
DB_PATH = os.path.join(DATA_DIR, "lifeboat.sqlite")
SECRETS_PATH = os.path.join(DATA_DIR, "secrets.json")

DEFAULT_SETTINGS = {
    "sources": [],
    "excludes": ["/source/root/Lifeboat Restores", "@eaDir", "#recycle", "#snapshot", ".DS_Store", "Thumbs.db", "._*", "*.tmp", ".@__thumb"],
    "schedule_enabled": True,
    "schedule_time": "02:30",
    "retention": {"daily": 30, "weekly": 8, "monthly": 12, "yearly": 3},
    "prune_weekday": 6,          # 0=Mon … 6=Sun
    "check_weekday": 6,
    "check_subset_pct": 2,
    "limit_upload_kib": 0,       # 0 = unlimited
    "b2_bucket": "",
    "b2_prefix": "lifeboat",
    "price_per_tb": 6.95,
    "notify_success": False,
}

SECRET_KEYS = ("b2_key_id", "b2_app_key", "repo_password", "discord_webhook")

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  trigger TEXT NOT NULL,
  started_at REAL NOT NULL,
  finished_at REAL,
  status TEXT NOT NULL,
  snapshot_id TEXT,
  tree TEXT,
  summary TEXT,
  b2_before TEXT,
  b2_after TEXT,
  error TEXT,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS runs_started ON runs(started_at);
CREATE INDEX IF NOT EXISTS runs_snapshot ON runs(snapshot_id);
CREATE TABLE IF NOT EXISTS run_log (
  run_id INTEGER NOT NULL,
  ts REAL NOT NULL,
  level TEXT NOT NULL,
  line TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_log_run ON run_log(run_id);
CREATE TABLE IF NOT EXISTS ledger (
  snapshot_id TEXT PRIMARY KEY,
  origin TEXT NOT NULL,          -- 'local' (created by a run here) or 'b2' (first seen in B2)
  run_id INTEGER,
  first_seen REAL NOT NULL,
  b2_file_id TEXT,
  b2_sha1 TEXT,
  b2_size INTEGER,
  b2_upload_ts INTEGER,
  removed_at REAL,
  removed_by_run INTEGER,
  acknowledged INTEGER DEFAULT 0,
  meta TEXT                      -- restic snapshot metadata (time, tree, paths, summary) as last decrypted
);
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL NOT NULL,
  ok INTEGER NOT NULL,
  result TEXT NOT NULL
);
"""


def conn():
    global _conn
    with _lock:
        if _conn is None:
            os.makedirs(DATA_DIR, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
        return _conn


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def x(sql, args=()):
    with _lock:
        cur = conn().execute(sql, args)
        return cur.lastrowid


# ---------- settings & secrets ----------

def get_settings():
    s = dict(DEFAULT_SETTINGS)
    for row in q("SELECT key, value FROM settings"):
        try:
            s[row["key"]] = json.loads(row["value"])
        except ValueError:
            pass
    return s


def set_settings(updates):
    for k, v in updates.items():
        if k in DEFAULT_SETTINGS or k.startswith("_"):
            x("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
              (k, json.dumps(v)))


def get_secrets():
    try:
        with open(SECRETS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def set_secrets(updates):
    with _lock:
        s = get_secrets()
        for k, v in updates.items():
            if k in SECRET_KEYS:
                if v is None or v == "":
                    s.pop(k, None)
                else:
                    s[k] = v
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SECRETS_PATH + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(s, f)
        os.replace(tmp, SECRETS_PATH)


# ---------- runs ----------

def _row_run(r):
    if not r:
        return r
    for k in ("summary", "b2_before", "b2_after", "detail"):
        if r.get(k):
            try:
                r[k] = json.loads(r[k])
            except ValueError:
                pass
    return r


def start_run(kind, trigger):
    return x("INSERT INTO runs(kind, trigger, started_at, status) VALUES(?, ?, ?, 'running')",
             (kind, trigger, time.time()))


def update_run(run_id, **fields):
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v)
        cols.append(f"{k}=?")
        vals.append(v)
    vals.append(run_id)
    x(f"UPDATE runs SET {', '.join(cols)} WHERE id=?", vals)


def get_run(run_id):
    rows = q("SELECT * FROM runs WHERE id=?", (run_id,))
    return _row_run(rows[0]) if rows else None


def list_runs(limit=100, kind=None):
    if kind:
        rows = q("SELECT * FROM runs WHERE kind=? ORDER BY started_at DESC LIMIT ?", (kind, limit))
    else:
        rows = q("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
    return [_row_run(r) for r in rows]


def last_run(kind, status=None):
    if status:
        rows = q("SELECT * FROM runs WHERE kind=? AND status=? ORDER BY started_at DESC LIMIT 1", (kind, status))
    else:
        rows = q("SELECT * FROM runs WHERE kind=? ORDER BY started_at DESC LIMIT 1", (kind,))
    return _row_run(rows[0]) if rows else None


def log(run_id, line, level="info"):
    x("INSERT INTO run_log(run_id, ts, level, line) VALUES(?, ?, ?, ?)", (run_id, time.time(), level, line[:2000]))


def run_log(run_id, limit=2000):
    return q("SELECT ts, level, line FROM run_log WHERE run_id=? ORDER BY rowid LIMIT ?", (run_id, limit))


def interrupted_runs_cleanup():
    """Runs left 'running' by a container restart can never finish."""
    x("UPDATE runs SET status='failed', finished_at=?, error='Interrupted: Lifeboat restarted during this job' "
      "WHERE status='running'", (time.time(),))


# ---------- ledger ----------

def ledger_all():
    out = {}
    for r in q("SELECT * FROM ledger"):
        r["meta"] = json.loads(r["meta"]) if r.get("meta") else None
        out[r["snapshot_id"]] = r
    return out


def ledger_add_local(snapshot_id, run_id):
    x("INSERT INTO ledger(snapshot_id, origin, run_id, first_seen) VALUES(?, 'local', ?, ?) "
      "ON CONFLICT(snapshot_id) DO UPDATE SET run_id=excluded.run_id",
      (snapshot_id, run_id, time.time()))


def ledger_record_b2(snapshot_id, file_id, sha1, size, upload_ts):
    """Record the B2 identity of a snapshot object the first time we see it. Never overwrite it later:
    a changed identity is exactly what verification looks for."""
    existing = q("SELECT b2_file_id FROM ledger WHERE snapshot_id=?", (snapshot_id,))
    if not existing:
        x("INSERT INTO ledger(snapshot_id, origin, first_seen, b2_file_id, b2_sha1, b2_size, b2_upload_ts) "
          "VALUES(?, 'b2', ?, ?, ?, ?, ?)", (snapshot_id, time.time(), file_id, sha1, size, upload_ts))
    elif not existing[0]["b2_file_id"]:
        x("UPDATE ledger SET b2_file_id=?, b2_sha1=?, b2_size=?, b2_upload_ts=? WHERE snapshot_id=?",
          (file_id, sha1, size, upload_ts, snapshot_id))


def ledger_mark_removed(snapshot_id, run_id):
    x("UPDATE ledger SET removed_at=?, removed_by_run=? WHERE snapshot_id=? AND removed_at IS NULL",
      (time.time(), run_id, snapshot_id))
    if not q("SELECT 1 FROM ledger WHERE snapshot_id=?", (snapshot_id,)):
        x("INSERT INTO ledger(snapshot_id, origin, first_seen, removed_at, removed_by_run) VALUES(?, 'b2', ?, ?, ?)",
          (snapshot_id, time.time(), time.time(), run_id))


def ledger_set_meta(snapshot_id, meta):
    x("UPDATE ledger SET meta=? WHERE snapshot_id=?", (json.dumps(meta), snapshot_id))


def ledger_acknowledge(snapshot_id):
    x("UPDATE ledger SET acknowledged=1 WHERE snapshot_id=?", (snapshot_id,))


# ---------- verifications ----------

def add_verification(ok, result):
    return x("INSERT INTO verifications(at, ok, result) VALUES(?, ?, ?)", (time.time(), 1 if ok else 0, json.dumps(result)))


def last_verification():
    rows = q("SELECT * FROM verifications ORDER BY id DESC LIMIT 1")
    if not rows:
        return None
    r = rows[0]
    r["result"] = json.loads(r["result"])
    return r


def prune_old():
    """Keep the local log bounded: run log lines for the newest 400 runs, last 200 verifications."""
    x("DELETE FROM run_log WHERE run_id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT 400)")
    x("DELETE FROM verifications WHERE id NOT IN (SELECT id FROM verifications ORDER BY id DESC LIMIT 200)")
