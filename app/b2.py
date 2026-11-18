"""Minimal Backblaze B2 native API (v3) client: the independent source of truth for what is in the bucket.

restic itself talks to B2 through the S3-compatible endpoint; this module only lists and inspects.
"""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = os.environ.get("LIFEBOAT_B2_API", "https://api.backblazeb2.com")


class B2Error(Exception):
    def __init__(self, msg, status=None, code=None):
        super().__init__(msg)
        self.status = status
        self.code = code


class B2:
    def __init__(self, key_id, app_key):
        self.key_id = key_id
        self.app_key = app_key
        self.auth = None
        self.auth_at = 0
        self.lock = threading.Lock()
        self.calls = 0

    # -- plumbing --
    def _req(self, url, data=None, headers=None, timeout=60):
        req = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read())
            except Exception:
                body = {}
            raise B2Error(body.get("message") or f"HTTP {e.code}", e.code, body.get("code")) from None
        except urllib.error.URLError as e:
            raise B2Error(f"Cannot reach Backblaze: {e.reason}") from None

    def authorize(self, force=False):
        with self.lock:
            if self.auth and not force and time.time() - self.auth_at < 12 * 3600:
                return self.auth
            token = base64.b64encode(f"{self.key_id}:{self.app_key}".encode()).decode()
            self.auth = self._req(f"{API_BASE}/b2api/v3/b2_authorize_account",
                                  headers={"Authorization": f"Basic {token}"})
            self.auth_at = time.time()
            return self.auth

    @property
    def storage(self):
        return self.authorize()["apiInfo"]["storageApi"]

    def call(self, name, params):
        self.authorize()
        url = f"{self.storage['apiUrl']}/b2api/v3/{name}"
        body = json.dumps(params).encode()
        for attempt in range(2):
            self.calls += 1
            try:
                return self._req(url, data=body, headers={
                    "Authorization": self.auth["authorizationToken"], "Content-Type": "application/json"})
            except B2Error as e:
                if e.status == 401 and attempt == 0:
                    self.authorize(force=True)
                    continue
                raise

    # -- queries --
    def s3_endpoint(self):
        return self.storage.get("s3ApiUrl", "")

    def key_info(self):
        # API v3 puts capabilities/bucket restriction directly on storageApi; older shapes nest them under "allowed"
        st = self.storage
        allowed = st.get("allowed") or {}
        caps = st.get("capabilities") or allowed.get("capabilities") or []
        buckets = [b.get("name") for b in (st.get("buckets") or allowed.get("buckets") or []) if b.get("name")]
        if not buckets and (st.get("bucketName") or allowed.get("bucketName")):
            buckets = [st.get("bucketName") or allowed.get("bucketName")]
        return {
            "capabilities": caps,
            "buckets": buckets,
            "name_prefix": st.get("namePrefix", allowed.get("namePrefix")),
            "s3_endpoint": st.get("s3ApiUrl"),
        }

    def bucket(self, name):
        res = self.call("b2_list_buckets", {"accountId": self.authorize()["accountId"], "bucketName": name})
        for b in res.get("buckets", []):
            if b.get("bucketName") == name:
                return b
        raise B2Error(f"Bucket '{name}' not found or this key can't see it", code="no_bucket")

    def list_versions(self, bucket_id, prefix, max_total=500000):
        """All object versions (uploads + hide markers) under a prefix, newest version first per name."""
        out, start_name, start_id = [], None, None
        while True:
            params = {"bucketId": bucket_id, "prefix": prefix, "maxFileCount": 10000}
            if start_name:
                params["startFileName"] = start_name
                if start_id:
                    params["startFileId"] = start_id
            res = self.call("b2_list_file_versions", params)
            out.extend(res.get("files", []))
            start_name, start_id = res.get("nextFileName"), res.get("nextFileId")
            if not start_name or len(out) >= max_total:
                return out

    def list_names(self, bucket_id, prefix, max_total=2000000):
        """Current (visible) objects only."""
        out, start = [], None
        while True:
            params = {"bucketId": bucket_id, "prefix": prefix, "maxFileCount": 10000}
            if start:
                params["startFileName"] = start
            res = self.call("b2_list_file_names", params)
            out.extend(res.get("files", []))
            start = res.get("nextFileName")
            if not start or len(out) >= max_total:
                return out
