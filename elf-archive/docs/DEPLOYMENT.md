# Deployment guide

This guide puts the archive on a rented Linux server (a "VPS") with HTTPS, automatic restarts, scheduled email delivery and nightly backups. It assumes **Ubuntu 24.04 LTS**; other Debian-based systems work the same way. Allow about an hour.

Commands run as a user with `sudo` unless shown otherwise. Replace `archive.example.org` with your domain throughout.

## 1. What you need

| Item | Notes |
| --- | --- |
| A server | 2 GB RAM and 1–2 vCPUs are enough to start. Disk: 20 GB plus room for media (photos, documents, recordings). Any provider (Hetzner, DigitalOcean, OVH, Linode, a university server…) |
| A domain name | With an `A` record (and `AAAA` if the server has IPv6) pointing at the server |
| An email (SMTP) account | For verification and password-reset emails. Any provider that gives SMTP credentials (Postmark, Mailgun, Amazon SES, Fastmail, your organisation's mail server) |
| Off-site backup storage | Under a **different account and provider** from the server, e.g. Backblaze B2, a second VPS, or an S3-compatible bucket |

The archive keeps all records in one SQLite file and media on local disk. That suits one server with a persistent disk. Platforms without a persistent disk (Heroku-style hosting, most "serverless" platforms) are **not** suitable without first moving to PostgreSQL and object storage (see `ARCHITECTURE.md` §2).

## 2. Prepare the server

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv ffmpeg sqlite3 unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades      # automatic security updates

# firewall: SSH and web only
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable

# a dedicated system user, and folders for code, data, media and backups
sudo adduser --system --group --home /srv/elf elf
sudo mkdir -p /srv/elf/app /srv/elf/data /srv/elf/media /srv/elf/backups
sudo chown -R elf:elf /srv/elf
sudo chmod 750 /srv/elf/data /srv/elf/media /srv/elf/backups
```

`ffmpeg` is optional but recommended: with it, audio and video files have their embedded metadata (which can include locations and device details) removed before visitors can play them. Without it, recordings are served as uploaded.

## 3. Install the application

Copy the project folder to `/srv/elf/app` (with `git clone` if it is in a repository, or `scp -r` / `rsync` from your computer; leave out `.venv`, `instance` and `.env`).

```bash
sudo -u elf -H bash
cd /srv/elf/app
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt gunicorn python-dotenv
exit
```

## 4. Settings (`.env`)

Create `/srv/elf/app/.env` (owner `elf`, mode `600`). Use plain `KEY=value` lines with no quotes, because systemd reads this file.

```ini
ELF_ENV=production
# python3 -c "import secrets; print(secrets.token_urlsafe(48))"
ELF_SECRET_KEY=paste-a-long-random-value-here
ELF_BASE_URL=https://archive.example.org
ELF_SITE_NAME=ELF Digital Historical Archive
ELF_CONTACT_EMAIL=archive@example.org

ELF_DATABASE_PATH=/srv/elf/data/archive.db
ELF_MEDIA_ROOT=/srv/elf/media

# one reverse proxy (Caddy or nginx) on this server
ELF_TRUSTED_PROXIES=1
# staff must use two-step sign-in (turn on after the first administrator has set it up; see §8)
ELF_REQUIRE_STAFF_MFA=false

ELF_SMTP_HOST=smtp.your-provider.example
ELF_SMTP_PORT=587
ELF_SMTP_USER=your-smtp-user
ELF_SMTP_PASSWORD=your-smtp-password
ELF_SMTP_FROM=ELF Archive <no-reply@archive.example.org>

# upload limits in MB (the reverse proxy limit in §6 must be at least the largest of these + 2)
ELF_MAX_PHOTO_MB=15
ELF_MAX_DOCUMENT_MB=30
ELF_MAX_AV_MB=250
```

```bash
sudo chown elf:elf /srv/elf/app/.env && sudo chmod 600 /srv/elf/app/.env
```

The application refuses to start in production with a weak secret or a non-`https` address. Every setting is described in `.env.example`.

### Running management commands

Commands such as `migrate` and `backup` need the same settings. `flask` reads `.env` from the current folder by itself (that is what `python-dotenv` is for), so a small wrapper is enough:

```bash
sudo tee /usr/local/bin/elf >/dev/null <<'EOF'
#!/bin/sh
# Run an archive management command as the elf user with the production settings.
cd /srv/elf/app && exec sudo -u elf .venv/bin/flask --app elf_archive "$@"
EOF
sudo chmod 755 /usr/local/bin/elf
```

Then: `elf migrate`, `elf create-admin …`, `elf backup …` and so on.

## 5. Database and first administrator

```bash
elf migrate
elf create-admin --email you@example.org --username yourname     # prompts for the password
```

Never run `seed-test-data` on the production server (it refuses anyway).

## 6. Web server and HTTPS

### Option A: Caddy (recommended: obtains and renews HTTPS certificates automatically)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
archive.example.org {
    encode zstd gzip
    request_body {
        max_size 260MB
    }
    handle_path /static/* {
        root * /srv/elf/app/elf_archive/static
        header X-Content-Type-Options nosniff
        # the same caching the application sends when it serves these files itself:
        # versioned addresses (?v=…) never change; elevation tiles change only when rebuilt
        @versioned query v=*
        header @versioned Cache-Control "public, max-age=31536000, immutable"
        @terrain {
            path /map/terrain/*
            not query v=*
        }
        header @terrain Cache-Control "public, max-age=2592000"
        @other {
            not path /map/terrain/*
            not query v=*
        }
        header @other Cache-Control "public, max-age=3600"
        file_server
    }
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

### Option B: nginx with Let's Encrypt (certbot)

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/elf`:

```nginx
# versioned static addresses (?v=…) never change, so they can be cached for a year
map $arg_v $elf_static_cache {
    ""      "public, max-age=3600";
    default "public, max-age=31536000, immutable";
}

server {
    server_name archive.example.org;
    client_max_body_size 260m;
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;   # map and timeline data are JSON

    location /static/ {
        alias /srv/elf/app/elf_archive/static/;
        add_header X-Content-Type-Options nosniff;
        add_header Cache-Control $elf_static_cache;
    }
    location /static/map/terrain/ {
        alias /srv/elf/app/elf_archive/static/map/terrain/;
        add_header X-Content-Type-Options nosniff;
        add_header Cache-Control "public, max-age=2592000";
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 300s;
        proxy_request_buffering off;      # stream large uploads to the app
    }
    listen 80;
}
```

```bash
sudo ln -s /etc/nginx/sites-available/elf /etc/nginx/sites-enabled/elf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d archive.example.org       # adds HTTPS and renews automatically
```

Either way, `ELF_TRUSTED_PROXIES=1` must be set (§4). Without it, every visitor appears to come from the proxy, and the sign-in lockout and rate limits would apply to everyone at once.

## 7. Run the application as a service

`/etc/systemd/system/elf-archive.service`:

```ini
[Unit]
Description=ELF Digital Historical Archive
After=network.target

[Service]
User=elf
Group=elf
WorkingDirectory=/srv/elf/app
EnvironmentFile=/srv/elf/app/.env
ExecStart=/srv/elf/app/.venv/bin/gunicorn --workers 3 --threads 2 --timeout 300 --bind 127.0.0.1:8000 wsgi:app
Restart=always
RestartSec=5
# hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/srv/elf/data /srv/elf/media /srv/elf/backups

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now elf-archive
sudo systemctl status elf-archive          # should say "active (running)"
journalctl -u elf-archive -f               # live log; Ctrl+C to stop
```

## 8. Scheduled jobs: email and backups

**Email delivery every 2 minutes.** `/etc/systemd/system/elf-email.service`:

```ini
[Unit]
Description=ELF archive: send queued email
[Service]
Type=oneshot
User=elf
WorkingDirectory=/srv/elf/app
EnvironmentFile=/srv/elf/app/.env
ExecStart=/srv/elf/app/.venv/bin/flask --app elf_archive send-email
```

`/etc/systemd/system/elf-email.timer`:

```ini
[Unit]
Description=ELF archive: send queued email every 2 minutes
[Timer]
OnBootSec=1min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
```

**Nightly backup at 02:30**, keeping 14 daily database copies and an incremental media copy. `/etc/systemd/system/elf-backup.service`:

```ini
[Unit]
Description=ELF archive: nightly backup
[Service]
Type=oneshot
User=elf
WorkingDirectory=/srv/elf/app
EnvironmentFile=/srv/elf/app/.env
ExecStart=/bin/sh -c '/srv/elf/app/.venv/bin/flask --app elf_archive backup /srv/elf/backups/archive-$(date +%%Y%%m%%d-%%H%%M).db --media /srv/elf/backups/media && find /srv/elf/backups -maxdepth 1 -name "archive-*.db" -mtime +14 -delete'
```

`/etc/systemd/system/elf-backup.timer`:

```ini
[Unit]
Description=ELF archive: nightly backup
[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now elf-email.timer elf-backup.timer
sudo systemctl start elf-backup.service && ls -l /srv/elf/backups     # try one backup now
```

Each backup is recorded in the audit log, and the admin overview shows the date of the last one.

**Off-site copies.** `/srv/elf/backups` is on the same server, so it does not protect against losing the server. Copy it off-site every night with a tool such as `restic` (encrypted, deduplicated) or `rclone`, to storage under a different account. For example, with restic and Backblaze B2: install `restic`, create a repository once (`restic -r b2:bucket-name:elf init`), then add a timer that runs `restic -r b2:bucket-name:elf backup /srv/elf/backups` after the nightly backup, followed by `restic forget --keep-daily 14 --keep-weekly 12 --keep-monthly 24 --prune`. Keep the restic password somewhere other than the server. Backups contain account emails and restricted records, so they must be encrypted before they leave the server; restic does that.

## 9. First sign-in and hardening

1. Open `https://archive.example.org`, sign in as the administrator.
2. **Dashboard → Two-step sign-in**: turn it on and store the recovery codes safely.
3. Create accounts for the other staff (they register normally), then grant roles in **Admin → Users**.
4. Once every staff member has set up two-step sign-in, set `ELF_REQUIRE_STAFF_MFA=true` in `.env` and `sudo systemctl restart elf-archive`. Staff without it are then sent to set it up before they can use staff tools.
5. Check **Admin → Overview**: no fictional records, a recent backup date, emails sending.

## 10. Smoke test after every deployment

- Home page loads over HTTPS; the padlock shows a valid certificate.
- Register a test account and receive the verification email.
- Search finds a known record; the map draws.
- An editor can open the queue.
- Upload a small photo on a draft submission and see its thumbnail.
- `curl -sI https://archive.example.org | grep -i strict-transport` shows the HSTS header.
- `curl -sI -H 'Accept-Encoding: gzip' https://archive.example.org/map/data.json` shows `Content-Encoding: gzip` (or `zstd`), and `curl -sI 'https://archive.example.org/static/js/map.js?v=1'` shows `Cache-Control: public, max-age=31536000, immutable`.

## 11. Updating to a new version

```bash
elf backup /srv/elf/backups/before-update-$(date +%Y%m%d-%H%M).db --media /srv/elf/backups/media
# copy the new code into /srv/elf/app (keep .env, .venv)
sudo -u elf /srv/elf/app/.venv/bin/pip install -r /srv/elf/app/requirements.txt gunicorn python-dotenv
elf migrate
sudo systemctl restart elf-archive
```

Then run the smoke test (§10). Migrations are numbered and applied once; restoring the backup taken first undoes an update.

## 12. Optional settings

| Setting | Effect |
| --- | --- |
| `ELF_MAP_TILE_URL`, `ELF_MAP_TILE_ATTRIBUTION` | Adds a street-level layer from a tile provider above the archive's own base map. Off by default, so no visitor data goes to a third party. If you use OpenStreetMap's public tiles, respect their usage policy; heavy use needs a commercial provider or self-hosted tiles. |
| `ELF_SESSION_LIFETIME_SECONDS` | How long a sign-in lasts (default 7 days). |
| `ELF_REQUIRE_EMAIL_VERIFICATION` | Keep `true` in production. |
| `ELF_ALLOW_SELF_REVIEW` | Keep `false`: editors cannot approve their own submissions. |
| `ELF_MAX_PHOTOS_PER_SUBMISSION` | Default 10. |
| `ELF_EMBED_ORIGINS` | Sites that may show the map and timeline inside their own pages (see §13). Empty by default. |

## 13. Showing the map and timeline on the organization's website (e.g. WordPress)

The map and timeline can appear inside a page of another site, such as the organization's WordPress site, with no WordPress plugin. The archive must already be running publicly over HTTPS (for example at `https://archive.elfveterans.org`). Browsers block an `http://` page inside an `https://` site, and a computer on a home network cannot be reached by visitors.

1. **Allow the site.** In `.env` on the archive server, then restart the service:
   ```
   ELF_EMBED_ORIGINS=https://elfveterans.org https://www.elfveterans.org
   ```
   Only the public map and timeline, in their embedded layout (`?embed=1`), may then be framed, and only by these sites. Every other page, including sign-in, contribution forms and staff pages, still refuses framing.
2. **In WordPress**, go to Pages → Add New. Add a **Custom HTML** block (type `/html`) and paste one of these:
   ```html
   <!-- the map -->
   <iframe src="https://archive.elfveterans.org/explore?mode=map&embed=1"
           title="Historical map of Eritrea, from the ELF Digital Historical Archive"
           style="width:100%;height:900px;border:0" loading="lazy"></iframe>

   <!-- the timeline -->
   <iframe src="https://archive.elfveterans.org/explore?mode=timeline&embed=1"
           title="Historical timeline, from the ELF Digital Historical Archive"
           style="width:100%;height:900px;border:0" loading="lazy"></iframe>
   ```
   Any filter can be added to the address, e.g. `&from=1961&to=1970` for one decade, or `&place=plc-…` to open on one place.
3. **Preview, then publish.** Inside the frame, the archive's header and footer are left out. Visitors can switch between map and timeline and use every filter, and "Open the full archive in a new tab" goes to the archive itself. Links to records open in a new tab.

**Notes:**
- Your WordPress account needs permission to add raw HTML. Administrators on a self-hosted site have it.
- If the frame stays blank, check that the WordPress address (with or without `www`) is listed in `ELF_EMBED_ORIGINS`.
- Visitors are not signed in inside the frame (browsers keep the two sites' cookies apart), so contributing and editing happen on the archive's own site.

## 14. Antivirus scanning (optional)

Uploads are checked by content, images are re-encoded before visitors see them, PDFs with scripts or embedded files are refused, and originals are given only to staff as downloads. If you also want virus scanning, install ClamAV (`sudo apt install clamav clamav-daemon`) and schedule `clamscan -r --infected /srv/elf/media` daily, with its output emailed to an administrator. The application does not call a scanner itself.
