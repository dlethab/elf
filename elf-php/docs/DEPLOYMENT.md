# Deployment guide (PHP edition)

This puts the archive on ordinary PHP web hosting: the same kind of hosting that runs WordPress, including cPanel
and Plesk accounts. The archive does not need a database server; its data is one SQLite file.

The recommended set-up is the archive on its own subdomain, for example **`https://archive.elfveterans.org`**, on the
same hosting account as the WordPress site. WordPress stays exactly as it is. The archive's map and timeline can then
be shown inside WordPress pages ([section 10](#10-showing-the-map-and-timeline-in-wordpress)).

## 1. What you need

- **PHP 8.1 or newer** with the extensions `pdo_sqlite`, `gd`, `mbstring`, `intl`, `fileinfo`, `zip` and `openssl`.
  `exif` is recommended. Most hosts have all of them. In cPanel: *Select PHP Version* → *Extensions*.
- **HTTPS** for the subdomain (cPanel's *SSL/TLS Status* or *Let's Encrypt*; most hosts do this automatically).
- **SSH or a terminal** for a few one-off commands (cPanel: *Terminal*). Without one, see the note in section 5.
- About 100 MB of disk to start, plus room for uploaded photographs and recordings.

## 2. Build the upload

On the Windows computer that has this folder:

```powershell
.\make-release.ps1
```

This makes `dist\elf-php.zip` with only what belongs on a server (no local databases, tests or the Windows PHP).

## 3. Upload and point the subdomain at `public/`

1. Create the subdomain (cPanel: *Domains* → *Create A New Domain*, e.g. `archive.elfveterans.org`).
2. Upload `elf-php.zip` to your home folder (cPanel: *File Manager* → *Upload*) and extract it. You now have
   `/home/<account>/elf-php/`.
3. Set the subdomain's **document root** to `/home/<account>/elf-php/public`. Only that folder is ever published.
   The settings, database and uploaded files stay one level above it, out of reach of the web.

If your host does not let you choose the document root (the web folder is fixed as `public_html`): put the project
next to it as `/home/<account>/elf-php`, and copy the *contents* of `elf-php/public/` (including the hidden
`.htaccess`) into `public_html/`. The `index.php` there finds the project folder by itself.

The project folder's own `.htaccess` refuses all access, in case it is ever published by mistake.

## 4. Settings: `.env`

Copy `.env.example` to `.env` in `elf-php/` and set at least:

```
ELF_ENV=production
ELF_SECRET_KEY=<a random value of at least 32 characters>
ELF_BASE_URL=https://archive.elfveterans.org
ELF_CONTACT_EMAIL=<the address visitors may write to>
ELF_SMTP_HOST=<your host's mail server, e.g. mail.elfveterans.org>
ELF_SMTP_PORT=587
ELF_SMTP_USER=<a mailbox, e.g. archive@elfveterans.org>
ELF_SMTP_PASSWORD=<its password>
ELF_SMTP_FROM=archive@elfveterans.org
```

Make a secret with `php -r "echo bin2hex(random_bytes(32)), PHP_EOL;"`. The site refuses to start in production
without a strong secret and an `https://` address. Keep `.env` private: it is never served, and nobody needs a copy.

**PHP limits for uploads** (cPanel: *Select PHP Version* → *Options*, or *MultiPHP INI Editor*):

| setting | value | why |
|---|---|---|
| `upload_max_filesize` | 260M | the largest recording (`ELF_MAX_AV_MB`, 250) |
| `post_max_size` | 262M | the same plus the form |
| `memory_limit` | 512M | large photographs are processed in memory |
| `max_execution_time` | 120 | processing a large upload |

If a file is larger than PHP accepts, the visitor is told the file is too large. Nothing else breaks.

## 5. Database and first administrator

In the terminal:

```sh
cd ~/elf-php
php bin/elf migrate
php bin/elf create-admin --email you@elfveterans.org --username yourname --display-name "Your Name"
```

`create-admin` asks for the password twice without showing it. On some hosts the command is `php8.3` or
`/usr/local/bin/php` rather than `php`. The terminal's PHP must be the same version as the website's.

**Without a terminal:** add `ELF_AUTO_MIGRATE=true` to `.env`, open the site once (this creates the database), then
remove the line again. For the first administrator, ask your host's support to run the `create-admin` command once
(it needs someone at a keyboard to type the password; never put a password in a cron job or a file).

Check `instance/` was created inside `elf-php/` and that PHP can write to it (cPanel does this by default).

## 6. Scheduled jobs: email and backups

cPanel → *Cron Jobs* (adjust the path and `php`):

```
*/5 * * * *  cd ~/elf-php && php bin/elf send-email > /dev/null
15 3 * * *   cd ~/elf-php && php bin/elf backup instance/backups/archive-$(date +\%F).db --media instance/backups/media
```

The backup copy is consistent while the site is running and is checked after writing. Download the backup folder
regularly to somewhere else: a backup on the same account does not protect against losing the account. Remove old
copies now and then.

## 7. First sign-in and hardening

1. Visit the site, sign in as the administrator, and turn on **two-step sign-in** (*Dashboard* → *Two-step sign-in*).
2. Give staff their roles under *Admin* → *Users*. Ask each of them to turn on two-step sign-in, then set
   `ELF_REQUIRE_STAFF_MFA=true` in `.env` so staff tools require it.
3. Check *Admin* → *Overview*: nothing should say "failed", and the outbox should empty within five minutes.

## 8. Smoke test after every deployment

- The home page, `/people`, `/map` and `/timeline` open over HTTPS.
- Sign-in works, and the *Dashboard* opens.
- A test email arrives (*Forgot your password?* with your own address).
- `/dev/outbox` shows "Not found" (development pages never exist in production).
- `https://archive.elfveterans.org/.env`, `/instance/archive.db` and `/composer.json` show "Not found" or
  "Forbidden" (only `public/` is on the web).

## 9. Updating to a new version

1. Run a backup (`php bin/elf backup …`).
2. Build a new `elf-php.zip` and upload it. Replace everything **except** `.env` and `instance/`.
3. `php bin/elf migrate`, then repeat the smoke test.
4. If anything looks wrong: put back the previous files and the backed-up database.

Compiled templates are cached in `instance/cache/twig`. A new version clears itself (the cache notices changed
templates), but deleting that folder is always safe.

## 10. Showing the map and timeline in WordPress

The map and timeline can appear inside a WordPress page, with no WordPress plugin.

1. **Allow the site.** In `.env`:
   ```
   ELF_EMBED_ORIGINS=https://elfveterans.org https://www.elfveterans.org
   ```
   Only the public map and timeline, in their embedded layout (`?embed=1`), may then be framed, and only by these
   sites. Every other page, including sign-in, contribution forms and staff pages, still refuses framing.
2. **In WordPress**, *Pages* → *Add New*. Add a **Custom HTML** block (type `/html`) and paste one of these:
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
   Any filter can be added to the address, e.g. `&from=1961&to=1970` for one decade, or `&place=plc-…` to open on one
   place.
3. **Preview, then publish.** Inside the frame, the archive's header and footer are left out. Visitors can switch
   between map and timeline and use every filter, and "Open the full archive in a new tab" goes to the archive itself.

Notes: your WordPress account needs permission to add raw HTML (administrators of a self-hosted site have it). If the
frame stays blank, check that the WordPress address (with or without `www`) is listed in `ELF_EMBED_ORIGINS`.
Visitors are not signed in inside the frame, so contributing and editing happen on the archive's own site.

## 11. Moving from the Python edition

The two editions use the same database schema, the same settings and the same file storage, so the data moves as it is.

1. On the Python server: `flask --app elf_archive backup archive-copy.db --media media-copy`.
2. Upload `archive-copy.db` to `elf-php/instance/archive.db` and the contents of `media-copy/` to
   `elf-php/instance/media/` (or wherever `ELF_DATABASE_PATH` and `ELF_MEDIA_ROOT` point).
3. Use the same `.env` values (`ELF_SECRET_KEY` can be new: everyone simply signs in again).
4. `php bin/elf migrate` (normally "nothing"), then `php bin/elf reindex`.
5. **Passwords.** Accounts whose password was set by the Python edition with its default *scrypt* method cannot be
   checked by PHP's standard library. `php bin/elf legacy-password-resets` lists them, and
   `php bin/elf legacy-password-resets --send` queues a password-reset email to each (then `php bin/elf send-email`).
   Each link works for one hour; anyone who misses it can use *Forgot your password?*. Accounts with *pbkdf2*
   passwords sign in as before. Two-step sign-in settings and recovery codes carry over.

Records, revisions, citations, photographs, oral histories, the forum, the audit log and every permanent identifier
(`/id/per-…`) are unchanged by the move.

## 12. Other servers

- **nginx with PHP-FPM**: see [nginx.conf.example](nginx.conf.example). Serve only `public/`, send everything that is
  not a file to `index.php`, and set `client_max_body_size` to the upload limit.
- **Behind a CDN or proxy** (e.g. Cloudflare): set `ELF_TRUSTED_PROXIES=1` so rate limits and lockouts apply per visitor.
- **On your own computer** for trying things: `.\run-sample.ps1` or `.\run-dev.ps1` (PHP's built-in server; it handles
  one request at a time, which is fine for one person but not for a public site).

## 13. Optional settings

- `ELF_MAP_TILE_URL` and `ELF_MAP_TILE_ATTRIBUTION`: a street-level layer above the archive's own base map (respect
  the provider's usage policy). Empty means no third-party map service is contacted.
- `ELF_MAX_PHOTO_MB`, `ELF_MAX_DOCUMENT_MB`, `ELF_MAX_AV_MB`, `ELF_MAX_PHOTOS_PER_SUBMISSION`: upload limits (keep
  the PHP limits in section 4 at least this large).
- `ELF_REQUIRE_EMAIL_VERIFICATION`, `ELF_ALLOW_SELF_REVIEW`, `ELF_SESSION_LIFETIME_SECONDS`: account rules.

## 14. Antivirus scanning (optional)

Uploads are checked by content, images are re-encoded before visitors see them, PDFs with scripts or embedded files
are refused, and originals are given only to staff, as downloads. If your host offers a malware scanner (cPanel:
*Virus Scanner* / ImunifyAV), include `elf-php/instance/media` in its scans.
