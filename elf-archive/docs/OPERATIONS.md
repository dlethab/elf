# Operations: backup, restore, export, upgrade, troubleshooting

Server setup, including scheduled backups, is in `DEPLOYMENT.md`. On the server, `elf <command>` is the wrapper described there; elsewhere use `flask --app elf_archive <command>`.

## What holds the archive's state

| What | Where | In the database backup? |
| --- | --- | --- |
| Records, history, users, submissions, forum, audit log | One SQLite file (`ELF_DATABASE_PATH`) | Yes |
| Uploaded files: photos, documents, recordings and their derivatives | `ELF_MEDIA_ROOT` | No: copy with `--media` (below) |
| Settings and secrets | `.env` | No: keep a copy in a password manager |

## Backups

```bash
elf backup /srv/elf/backups/archive-$(date +%Y%m%d-%H%M).db --media /srv/elf/backups/media
```

- The database copy uses SQLite's online backup API (safe while the site is running) and then runs an integrity check.
- `--media DIR` copies new media files into `DIR`. Stored files never change after upload, so each run copies only what is new. The `sha256` column in `media_files` lets you verify every restored file.
- Every backup is recorded in the audit log; the admin overview shows the date of the last one and warns if there is none.

Recommended policy, to be confirmed by the archive's governing body:
- Daily backups kept 14 days, weekly kept 3 months, monthly kept indefinitely.
- Encrypt backups before they leave the server (`restic` does this), because they contain account emails and restricted records.
- Keep at least one copy with a different provider and under a different account owner from the web host, so the archive never depends on one person or one provider (spec §22.5).
- Recovery objectives (suggested): lose at most one day of data; restore within one working day.

## Test a restore (at least quarterly)

```bash
cp /srv/elf/backups/archive-YYYYMMDD-HHMM.db /tmp/restore-test.db
cd /srv/elf/app
sudo -u elf env ELF_ENV=development ELF_DATABASE_PATH=/tmp/restore-test.db ELF_MEDIA_ROOT=/srv/elf/backups/media \
     .venv/bin/flask --app elf_archive run --port 5001
```

From your computer, open an SSH tunnel (`ssh -L 5001:127.0.0.1:5001 you@server`) and browse `http://localhost:5001`: check a few known records, a photo, search and sign-in. Then stop it and delete `/tmp/restore-test.db`.

## Restore for real

1. `sudo systemctl stop elf-archive`
2. Move the damaged database aside (do not delete it).
3. Copy the backup to `ELF_DATABASE_PATH`; if media was lost, copy the media backup folder back to `ELF_MEDIA_ROOT` (`rsync -a /srv/elf/backups/media/ /srv/elf/media/`). Make sure both are owned by the `elf` user.
4. `elf migrate` then `elf reindex`.
5. `sudo systemctl start elf-archive` and run the smoke test (`DEPLOYMENT.md` §10).

## Public data export

```bash
elf export-public /srv/elf/backups/public-export-$(date +%Y%m%d).zip
```

The same file can be downloaded from **Admin → Data export**. It contains only what the public site shows (JSON and CSV, with a manifest). Confidential fields, accounts, submissions, messages, logs and media files are never included, and oral-history transcripts are included only where consent allows. Every export is recorded in the audit log. The export is for researchers, preservation and moving to other software; **it is not a backup**.

## Upgrades

1. Take a backup.
2. Deploy the new code and install requirements.
3. `elf migrate` (migrations are numbered, applied once, each in its own transaction).
4. `sudo systemctl restart elf-archive`.

## Moving to another server

Copy the database file, the media folder and `.env`; nothing else holds state. Set up the new server with `DEPLOYMENT.md`, put the files in place, `elf migrate`, start.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| App will not start in production | `journalctl -u elf-archive -n 50`. `ELF_SECRET_KEY` must be 32+ random characters and `ELF_BASE_URL` must start with `https://` |
| Users never receive email | Set `ELF_SMTP_*`; check the `elf-email.timer` is active (`systemctl list-timers`); failures are counted on the admin overview and recorded per message in the `outbox` table |
| Everyone gets "Too many attempts" at once | `ELF_TRUSTED_PROXIES=1` is missing, so every visitor appears to come from the proxy |
| "Your session expired or the form was invalid" | The form's CSRF token is older than the session; reload the page |
| A large upload fails | The proxy's limit (`request_body max_size` in Caddy, `client_max_body_size` in nginx) must be at least the largest `ELF_MAX_*_MB` + 2 |
| A record is published but not in search | `elf reindex` |
| A person was published but is not visible | They are recorded as living and were published as restricted; an editor can change access on the staff record page after confirming consent |
| A recording plays but still has metadata | `ffmpeg` is not installed on the server |
| A staff member is sent to "Two-step sign-in" | `ELF_REQUIRE_STAFF_MFA` is on and they have not set it up yet |
| "database is locked" under load | Expected only with very high write volume; consider the PostgreSQL migration path in `ARCHITECTURE.md` |
