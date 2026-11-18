# Lifeboat

Encrypted, automated offsite backups of selected NAS folders to Backblaze B2, with a web UI for monitoring uploads, browsing and downloading any version, and verifying the backups.

- **Engine:** [restic](https://restic.net) 0.19.1 (checksum-pinned in the Dockerfile). Data is encrypted on the NAS before upload. restic talks to B2 through its S3-compatible endpoint.
- **Source of truth:** the B2 native API (v3). Versions are listed from `<prefix>/snapshots/` in the bucket, including hidden (deleted) versions while the bucket lifecycle keeps them.
- **Cross-check:** a local SQLite log of every job (start/finish, restic output, the B2 file id and sha1 first seen for each snapshot, retention removals, and B2 byte counts before/after each backup).
- **Portable:** the repository is plain restic, so it can be restored on any machine (e.g. unRAID) with the restic CLI or by running this container there. Settings → Encryption → *Download recovery kit* has the exact commands.

## Features

- Nightly schedule → retention (`forget`) → weekly `prune` and `check --read-data-subset` → verification → Discord webhook alerts
- Live upload monitor (restic progress plus the container's real network transmit rate)
- Versions view: per-snapshot checks (present in B2, decrypts, B2 identity unchanged, upload time inside the logged run, tree hash matches the log)
- Browse any version; download a file, a folder as .zip, or a whole version as .tar; or restore into a folder on the NAS
- Activity log with the full output of every job
- Repository checks: B2 lifecycle, Object Lock, backup freshness, integrity-check age, B2 growth vs restic's reported upload

Verification statuses: `verified`, `retired` (removed by logged retention), `acknowledged`, `b2_only`, `should_be_removed`, `mismatch`, `missing`, `deleted`, `identity_changed` (replaced in B2), `unreadable`.

## Deploy (Synology DSM 7 / Container Manager)

```sh
./deploy.sh        # tars the sources to phoenix and runs `docker compose up -d --build`
```

`docker-compose.yml` mounts the shares read-only under `/source/*` and `/volume1/root/Lifeboat Restores` as `/restore`. App state lives in `./data` (SQLite log, restic cache, `secrets.json` with mode 0600).

Then open `http://<nas>:8850` and go through Settings:

1. **Backblaze B2:** a private bucket with lifecycle *Keep prior versions for 30 days*, and an application key restricted to that bucket (listBuckets, listFiles, readFiles, writeFiles, deleteFiles).
2. **Encryption password:** generate one, save it, create the repository, download the recovery kit.
3. **Folders**, 4. **Schedule & retention**, 5. **Alerts** (Discord webhook).

| Env var | Default | |
|---|---|---|
| `LIFEBOAT_HOST` | `phoenix` | restic host name; keep it the same on a new machine to continue the version lineage |
| `LIFEBOAT_PORT` | `8850` | |
| `LIFEBOAT_SOURCE_ROOT` | `/source` | folder picker root |
| `LIFEBOAT_RESTORE_ROOT` | `/restore` | restore target |
| `TZ` | `America/New_York` | schedule time zone |

The UI only answers private-network and Tailscale addresses; POSTs require the `X-Lifeboat: 1` header.

## Tests

`tests/mock_b2.py` is a fake B2 v3 API over a local restic repository (objects that disappear stay listed as hidden versions; `POST /_tamper` swaps an object's file id). Run the app against it with:

```sh
LIFEBOAT_DATA=/tmp/lb/data LIFEBOAT_REPO_OVERRIDE=/tmp/lb/repo LIFEBOAT_B2_API=http://127.0.0.1:18901 \
LIFEBOAT_SOURCE_ROOT=/tmp/lb/source LIFEBOAT_RESTORE_ROOT=/tmp/lb/restore python3 app/server.py
python3 tests/mock_b2.py /tmp/lb/repo lifeboat 18901
python3 tests/seed.py http://127.0.0.1:8850   # set up + a few backups (expects the source root env var)
```
