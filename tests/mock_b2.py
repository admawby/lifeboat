"""Fake B2 native API over a local restic repository directory (for tests only).

Objects = files under REPO, named PREFIX/<relpath>. Files that disappear from disk stay listed as hidden
versions (like a bucket with 'keep prior versions'). POST /_tamper?name=… swaps an object's file id.
"""
import hashlib
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO, PREFIX, PORT = sys.argv[1], sys.argv[2].strip("/") + "/", int(sys.argv[3])
seen = {}        # name -> {fileId, sha1, size, ts}
hidden = {}      # name -> (upload record, hide ts)
tamper = set()
lock = threading.Lock()


def scan():
    with lock:
        current = {}
        for root, _, files in os.walk(REPO):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, REPO)
                name = PREFIX + rel
                st = os.stat(full)
                rec = seen.get(name)
                if not rec or rec["mtime"] != st.st_mtime_ns:
                    with open(full, "rb") as fh:
                        sha1 = hashlib.sha1(fh.read()).hexdigest()
                    rec = {"fileId": "4_z" + hashlib.md5(f"{name}{st.st_mtime_ns}".encode()).hexdigest(),
                           "sha1": sha1, "size": st.st_size, "ts": st.st_mtime_ns // 1_000_000, "mtime": st.st_mtime_ns}
                    seen[name] = rec
                if name in tamper:
                    rec = dict(rec, fileId=rec["fileId"] + "x")
                current[name] = rec
        for name, rec in list(seen.items()):
            if name not in current and name not in hidden:
                hidden[name] = (rec, max(rec["ts"], 0) + 1000)
        return current


def entry(name, rec, action="upload", ts=None):
    return {"fileName": name, "fileId": rec["fileId"] if action == "upload" else rec["fileId"] + "h",
            "contentSha1": rec["sha1"], "contentLength": rec["size"] if action == "upload" else 0,
            "uploadTimestamp": ts or rec["ts"], "action": action}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/b2api/v3/b2_authorize_account"):
            return self.send({"accountId": "acct", "authorizationToken": "tok", "apiInfo": {"storageApi": {
                # real v3 shape (verified against Backblaze 2026-11-18): restriction fields sit directly on storageApi
                "apiUrl": f"http://127.0.0.1:{PORT}", "s3ApiUrl": "https://s3.us-west-004.backblazeb2.com",
                "capabilities": ["listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles"],
                "bucketId": "bkt", "bucketName": "test-bucket", "namePrefix": None, "infoType": "storageApi"}}})
        self.send({"code": "not_found", "message": "nope"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/_tamper"):
            tamper.add(body["name"])
            seen.pop(body["name"], None)
            return self.send({})
        name = self.path.rsplit("/", 1)[-1]
        if name == "b2_list_buckets":
            return self.send({"buckets": [{"bucketId": "bkt", "bucketName": "test-bucket", "bucketType": "allPrivate",
                                           "lifecycleRules": [{"fileNamePrefix": "", "daysFromHidingToDeleting": 30,
                                                               "daysFromUploadingToHiding": None}],
                                           "fileLockConfiguration": {"value": {"isFileLockEnabled": False}}}]})
        cur = scan()
        pfx = body.get("prefix", "")
        if name == "b2_list_file_names":
            files = [entry(k, v) for k, v in sorted(cur.items()) if k.startswith(pfx)]
            return self.send({"files": files, "nextFileName": None})
        if name == "b2_list_file_versions":
            out = []
            names = sorted(set(cur) | set(hidden))
            for k in names:
                if not k.startswith(pfx):
                    continue
                if k in hidden and k not in cur:
                    rec, hts = hidden[k]
                    out += [entry(k, rec, "hide", hts), entry(k, rec)]
                else:
                    out.append(entry(k, cur[k]))
            return self.send({"files": out, "nextFileName": None, "nextFileId": None})
        self.send({"code": "bad", "message": name}, 400)


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
