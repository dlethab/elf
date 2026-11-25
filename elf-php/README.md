# ELF Digital Historical Archive — PHP edition

A searchable, connected archive of people, families, places, events, sources, photographs and oral histories
associated with the Eritrean Liberation Front, with editorial review, an interactive historical map and timeline,
a community forum, and interfaces in English, Tigrinya and Arabic.

This is a complete port of the Python (Flask) edition in `../elf-archive` to PHP, for ordinary PHP web hosting
(the kind WordPress runs on). It has the same pages, features, permissions and security rules, and it uses
**the same database schema**. A database from the Python edition can be copied over and used as it is
(see [Moving from the Python edition](docs/DEPLOYMENT.md#11-moving-from-the-python-edition)).

## Documentation

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): putting it on a web host, settings, email, backups, updates, embedding
  the map and timeline in WordPress.
- [docs/STATUS.md](docs/STATUS.md): what was ported, how it was checked, and the known differences.
- The editorial, permission and operations guides of the Python edition (`../elf-archive/docs/`) apply unchanged;
  only the commands differ (`php bin/elf …` instead of `flask --app elf_archive …`).

## Requirements

- PHP 8.1 or newer (tested with 8.1.31 and 8.3.36) with these extensions: `pdo_sqlite`, `gd`, `mbstring`, `intl`,
  `fileinfo`, `zip`, `openssl` (for email). `exif` is recommended (photos taken sideways are turned upright).
- Apache with `mod_rewrite` (the usual shared hosting), or nginx with PHP-FPM. For trying it on a computer, PHP's
  built-in server is enough.
- No database server: the archive is a single SQLite file. No Composer on the server: `vendor/` is included.

On this Windows computer a portable PHP 8.3 is included in `tools/php`, with Composer in `tools/composer.phar`.
They are for local use only and are not uploaded to a host.

## Trying it: the sample archive

```powershell
.\run-sample.ps1            # http://127.0.0.1:8001
.\run-sample.ps1 -Lan       # also phones and tablets on the same Wi-Fi
.\run-sample.ps1 -Rebuild   # start the sample over
```

(`./run-sample.sh` on macOS and Linux.) This builds a **separate, entirely fictional** sample archive in
`instance/sample.db`, with every kind of record and every step of the review workflow, then starts the site. The
sign-in names and the shared password are printed and saved in `instance/sample-accounts.txt`, one account per role
(administrator, editors, moderator, researcher, contributor, family representative, member, a new unverified account).
The real archive is never touched. Everything in the sample is labelled FICTIONAL, its dates fall in 2040–2099 and its
places carry test-only coordinates.

If a phone cannot connect with `-Lan`, allow the port through Windows Firewall once (as administrator):
`New-NetFirewallRule -DisplayName "ELF archive (PHP)" -Direction Inbound -Protocol TCP -LocalPort 8001 -Action Allow -Profile Private`.

## Development setup

```powershell
copy .env.example .env          # then edit it; development needs no changes
.\run-dev.ps1                   # http://127.0.0.1:8000, database instance\archive.db
```

In development, pending database updates are applied at start-up and queued email can be read at `/dev/outbox`.
To add a few clearly labelled fictional records to your own development database: `php bin/elf seed-test-data`.

## Tests

```powershell
tools\php\php.exe vendor\bin\phpunit
```

48 tests (429 assertions): HTTP security headers and caching, CSRF, sessions, sign-in lockout and two-step sign-in,
password hashes from the Python edition, visibility of restricted and living people, the full contribution → review →
publication cycle, corrections, merges, roles and permissions, family representatives, photo uploads and the media
access rule, translations and right-to-left layout, every template compiling, the sample builder and the command-line
tool. See [docs/STATUS.md](docs/STATUS.md) for the cross-checks against the Python edition (page-by-page comparison
and its browser test suite).

The Python edition's browser test suite (Playwright, 16 scenarios including an accessibility check of 44 pages) can be
run against this edition, with the Python edition next to this folder:

```powershell
..\elf-archive\.venv\Scripts\python.exe tests\e2e_against_php.py
```

## Operator commands

```
php bin/elf migrate                         apply pending database updates
php bin/elf create-admin --email E --username U   first administrator (asks for the password)
php bin/elf send-email                      send queued email (run from cron every few minutes)
php bin/elf backup DEST.db [--media DIR]    consistent copy of the database (+ media files)
php bin/elf export-public DEST.zip          public data export (JSON + CSV)
php bin/elf reindex                         rebuild the search index
php bin/elf legacy-password-resets [--send] accounts needing a new password after moving from the Python edition
php bin/elf sample-db                       rebuild the fictional sample archive
php bin/elf seed-test-data                  development only: a few fictional records
```

## Project layout

```
public/            the only folder the web server publishes: index.php, .htaccess, static/ (styles, scripts, map)
src/               the application
  App.php          request handling, sessions, error pages      Security.php  CSRF, headers, guards
  View.php         Twig set-up (the same helpers as the Python templates)
  Http/            request, response, router, signed session cookie
  Web/             the pages: Public, Auth, Dashboard, Editor, Admin, Community controllers
  Services/        records, workflow, photos, search, accounts, forum, merging, import, export, …
  Atlas.php, Queries.php, I18n.php, Vocab.php, Permissions.php, Config.php, Db.php
  Tools/           the sample builder, the development seed, an in-process client
templates/         Twig templates (converted from the Python edition's Jinja templates)
migrations/        SQL migrations (identical to the Python edition's)
translations/      interface catalogues: Tigrinya and Arabic (drafts until reviewed by native speakers)
bin/elf            the command-line tool
instance/          database, uploaded files, caches (created on first run; never published)
tests/             PHPUnit tests
```

## Third-party components

Included in `vendor/`: [Twig](https://twig.symfony.com/) 3.30 (BSD-3-Clause), [PHPMailer](https://github.com/PHPMailer/PHPMailer)
6.12 (LGPL-2.1), [chillerlan/php-qrcode](https://github.com/chillerlan/php-qrcode) 5.0 (MIT or Apache-2.0; QR codes for
two-step sign-in) with php-settings-container (MIT), and three small Symfony support packages (MIT). Development only:
PHPUnit 10.5 (BSD-3-Clause). In `public/static/vendor`: MapLibre GL JS (BSD-3-Clause). The base map
uses Natural Earth data (public domain).
