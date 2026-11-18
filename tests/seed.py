"""Drive a test Lifeboat through setup + a few backups (run inside the test container)."""
import json, os, random, sys, time, urllib.request
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8850"
SRC = os.environ.get("LIFEBOAT_SOURCE_ROOT", "/source")

def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Lifeboat": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"null")

def wait_idle():
    for _ in range(600):
        if not call("/api/overview")["state"]["job"] and not call("/api/overview")["state"]["queue"]:
            return
        time.sleep(1)

def write(p, n):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(os.urandom(n))

for i in range(40):
    write(f"{SRC}/photo/2024/IMG_{4000+i}.HEIC", random.randint(800_000, 3_000_000))
for name in ("Insurance policy.pdf", "Taxes 2025.pdf", "Passport scan.jpg"):
    write(f"{SRC}/root/GDrive/Home/{name}", random.randint(50_000, 600_000))
for name in ("strap-5mm-Ava.3mf", "strap-6mm-Liam.3mf"):
    write(f"{SRC}/root/GDrive/3D Printing/!Etsy/{name}", 400_000)
write(f"{SRC}/root/Multimedia/Movies/big.mkv", 5_000_000)
os.makedirs(f"{SRC}/root/Gaming/OpenRCT2", exist_ok=True)

call("/api/secrets", {"b2_key_id": "0041a2b3c4d5e6f0000000007", "b2_app_key": "K004testtesttesttesttest"})
call("/api/settings", {"b2_bucket": "test-bucket", "b2_prefix": "lifeboat",
                       "sources": [f"{SRC}/photo", f"{SRC}/root/GDrive/Home", f"{SRC}/root/GDrive/3D Printing"]})
print(call("/api/b2/test", {}))
print(call("/api/repo/connect", {"password": "correct-horse-battery", "create": True}))
for round_ in range(3):
    call("/api/jobs", {"kind": "backup"}); time.sleep(1); wait_idle()
    for i in range(6):
        write(f"{SRC}/photo/2024/IMG_{5000+round_*10+i}.HEIC", random.randint(800_000, 2_500_000))
    time.sleep(2)
call("/api/jobs", {"kind": "check", "subset": 10}); time.sleep(1); wait_idle()
call("/api/jobs", {"kind": "verify"}); time.sleep(1); wait_idle()
print("seeded")
