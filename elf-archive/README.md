# ELF Digital Historical Archive

A connected, searchable historical archive for the Eritrean Liberation Front and Eritrea's independence struggle. People, families, places, events, organizations and sources are shared records linked to each other, with claim-level citations and honest handling of uncertainty. It also includes an editorial review workflow, photographs, documents, recordings and consent-based oral histories, an interactive map of Eritrea, family trees and connection diagrams, a moderated community forum, and an interface in English, Tigrinya and Arabic.

## Documentation

| Document | For |
| --- | --- |
| `docs/STATUS.md` | What works, what was tested, what remains |
| `docs/LAUNCH_CHECKLIST.md` | Steps before going live |
| `docs/DEPLOYMENT.md` | Putting it on a Linux server with HTTPS, services, email and backups |
| `docs/ADMIN_GUIDE.md` | Running the archive day to day (administrators, editors, moderators) |
| `docs/EDITORIAL.md` | Editorial guidelines: evidence, living people, rights, consent |
| `docs/OPERATIONS.md` | Backup, restore, export, upgrades, troubleshooting |
| `docs/PERMISSIONS.md` | Roles and what each can do |
| `docs/ARCHITECTURE.md` | Design, data model, routes, testing |
| `docs/SPECIFICATION.md` | The original product specification |

## Requirements

- Python 3.12 or newer (SQLite with FTS5 is included with standard Python builds)
- Nothing else for development: no database server, no Node toolchain. `ffmpeg` is optional (strips metadata from audio and video).

## Development setup

**Windows (PowerShell)**, from the project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\flask.exe --app elf_archive migrate
.\.venv\Scripts\flask.exe --app elf_archive create-admin --email you@example.org --username you   # prompts for a password
.\.venv\Scripts\flask.exe --app elf_archive run --debug
```

**macOS / Linux:**

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
flask --app elf_archive migrate
flask --app elf_archive create-admin --email you@example.org --username you
flask --app elf_archive run --debug
```

Open http://localhost:5000. Mail you trigger (verification, password reset) is queued in the database; in development read it at http://localhost:5000/dev/outbox. Copying `.env.example` to `.env` is optional in development.

### The sample archive (recommended for trying the site)

```powershell
.\run-sample.ps1            # builds instance\sample.db on first run, then opens http://127.0.0.1:5001
.\run-sample.ps1 -Rebuild   # start the sample over
.\run-sample.ps1 -Lan       # also reachable from a phone on the same Wi-Fi; prints the address to open
```

With `-Lan` the debugger is turned off, because it must never be reachable from other devices. If the phone can't connect, allow the port through Windows Firewall once. Run this in PowerShell as administrator; it applies to private networks only:

```powershell
New-NetFirewallRule -DisplayName "ELF sample archive (5001)" -Direction Inbound -Protocol TCP -LocalPort 5001 -Action Allow -Profile Private
```

Your Wi-Fi must be set to **Private** (Settings → Network & internet → Wi-Fi → your network). Remove the rule when you no longer need it: `Remove-NetFirewallRule -DisplayName "ELF sample archive (5001)"`.

A complete, separate, fictional archive for walking through every journey. It contains:

- **Places:** 12 places with test-only coordinates of every precision, plus some places with no coordinates.
- **Events:** 18 events covering every kind of date, from an exact day to unknown.
- **People and families:** 11 people (one is living, so stays private), 3 families with relationships and a family representative.
- **Organizations and sources:** 3 organizations, and 6 sources whose citations carry different evidence levels.
- **Disagreements:** one about a date and one about a location.
- **Media and curation:** 2 oral histories, 7 photographs and a document, a collection, and 2 curated explorations.
- **Workflow and community:** contributions waiting at every review stage, forum topics with a report for the moderator, and a message to the editors.

The accounts (`sample_admin`, `sample_editor`, `sample_contrib`, `sample_moderator`, `sample_family`, …) and their shared password are written to `instance\sample-accounts.txt`.

The sample lives in its own database (`instance\sample.db`, with its files in `instance\sample-media`) and never touches `instance\archive.db`. Every record is flagged and labelled fictional, dated 2040–2099, and in fictional "Test Regions". The command behind the script is `flask --app elf_archive sample-db`, and it refuses to run in production.

### Adding a few fictional records to your own database (development only)

```bash
flask --app elf_archive seed-test-data
```

This adds records named "… (FICTIONAL)", flagged in the database and labelled on every page: people, a family, a place, events, organizations, affiliations, an oral history with a transcript, and forum topics. It also creates dev accounts (`dev_admin`, `dev_editor`, `dev_editor2`, `dev_moderator`, `dev_contrib`, `dev_rep`, `dev_researcher`) with a printed random password. Fictional records carry no coordinates and use the year 2099 so they cannot be mistaken for history. Running it again on a database seeded by an older version adds only the newer sections. The command refuses to run in production. Delete `instance/archive.db` to start over.

## Tests

```bash
python -m unittest discover -s tests -t .       # unit, service and HTTP integration tests
python tests/e2e_browser.py [screenshot_dir]    # 14 real-browser scenarios incl. an axe-core accessibility scan
                                                # (first: python -m playwright install chromium)
python -m tests.i18n_keys ar                    # lists interface text missing from a translation
pip-audit -r requirements.txt                   # known vulnerabilities in dependencies
```

## Operator commands

`flask --app elf_archive <command>` (on a server, the `elf` wrapper from `docs/DEPLOYMENT.md`):

| Command | Purpose |
| --- | --- |
| `migrate` | Apply pending database migrations (safe to re-run) |
| `create-admin --email … --username …` | Create an administrator; the password is prompted, never passed on the command line |
| `send-email` | Deliver queued email via SMTP (needs `ELF_SMTP_*`) |
| `backup DEST.db [--media DIR]` | Online database copy with integrity check, plus an incremental copy of media files |
| `export-public DEST.zip` | Public data export (JSON + CSV, public fields only) |
| `reindex` | Rebuild the public search index |
| `seed-test-data` | Development only: fictional records and dev accounts |

## Project layout

```
elf_archive/
  vocab.py            controlled vocabularies (single source for DB CHECK constraints and code)
  permissions.py      the permission matrix; every server-side check uses it
  migrations/         numbered SQL migrations
  db.py               connections, transactions, migration runner
  services/           business logic: accounts, entities, records, workflow, search, curation, merging,
                      importer, photos/media, oral histories, collections, graph, forum, mfa, export
  queries.py          read-side queries for public pages (always filtered to public records)
  security.py         CSRF, headers, cache policy, route guards
  i18n.py             interface languages; catalogues in translations/
  web/                Flask blueprints: public, auth, dashboard, editor, admin, community
  templates/          Jinja templates; _macros.html holds the shared components
  static/             CSS (archive.css, atlas.css), progressive-enhancement JS, vendored MapLibre, the Eritrea base map and terrain tiles
tools/build_basemap.py  rebuilds static/map/eritrea-basemap.json from Natural Earth
tools/build_terrain.py  rebuilds static/map/terrain (elevation tiles for the 3D map)
tests/                unit, HTTP integration and browser end-to-end tests
docs/                 see the table above
```

## Third-party components

Flask, Werkzeug and Jinja (BSD-3), Pillow (MIT-CMU), qrcode (BSD), MapLibre GL JS (BSD-3) vendored in `static/vendor`, map data from Natural Earth (public domain), elevation from Terrain Tiles (SRTM, GMTED2010, ETOPO1; AWS Open Data). Tests only: Playwright (Apache-2.0), axe-core (MPL-2.0) in `tests/vendor`.
