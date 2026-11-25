# Status of the PHP edition (2026-10-26)

## What it is

A full port of the Python edition (`../elf-archive`, Flask) to PHP 8.1+, made to run on ordinary PHP hosting. Every
public page, contributor page, editorial tool, administration page, forum and moderation page, data feed (`/map/*.json`,
`/timeline/data.json`, `/explore/context.json`, `/lookup/…`), the media access rule, sign-in with two-step codes, the
three interface languages, the sample archive and the operator commands are ported. The database schema, migrations,
translations, styles, scripts and map files are the Python edition's, unchanged.

| Python edition | PHP edition |
|---|---|
| Flask blueprints `web/*.py` | `src/Web/*Controller.php` (same addresses and route names) |
| Jinja templates | Twig templates (`templates/`), converted and then checked page by page |
| `services/*.py`, `queries.py`, `atlas.py` | `src/Services/*.php`, `src/Queries.php`, `src/Atlas.php` |
| Flask signed session cookie | `src/Http/Session.php` (signed with HMAC-SHA256; same contents) |
| `flask --app elf_archive …` | `php bin/elf …` (same commands, plus `legacy-password-resets`) |
| `sampledata.py`, `devseed.py` | `src/Tools/SampleData.php`, `src/Tools/DevSeed.php` (same records) |
| Werkzeug password hashes | PHP `password_hash` (Argon2id or bcrypt); Werkzeug *pbkdf2* hashes are accepted |
| Pillow | GD (photos re-encoded, metadata removed, turned upright from EXIF) |
| smtplib | PHPMailer |

## How it was checked

1. **Page-by-page comparison with the Python edition.** Both editions rendered the same URLs from copies of the same
   sample database, and the HTML was compared after removing only whitespace and cache-busting `?v=` values:
   207 public pages and data feeds (including 4 views of the embedded map and timeline), and the signed-in pages of
   eight roles
   (contributor 92, editor 89, administrator 19, moderator 8, member 16, researcher 32, family representative 32,
   unverified newcomer 32). **All identical**, on PHP 8.3.36 and on PHP 8.1.31.
2. **The Python edition's browser test suite** (Playwright + Chromium, `tests/e2e_browser.py`) run against the PHP
   server: **16 of 16 scenarios pass**: the contributor → editor → publication workflow with revision, alias search,
   mobile layout, keyboard use, Arabic (right-to-left) and Tigrinya, photo upload with progress and editor decisions,
   the atlas (map ↔ timeline state, location picking, reviewers' layer, curated explorations, reduced motion), the forum
   with a moderator removal, a merge with redirects, and **axe-core: no WCAG A/AA violations on 44 pages**.
3. **PHPUnit**: 48 tests, 429 assertions (`tools\php\php.exe vendor\bin\phpunit`), passing on PHP 8.3 and 8.1.
4. **The sample builder** produces the same records as the Python one (same counts in every table; same entities,
   names, citations, media files and workflow states).
5. **Shared data**: a database and media folder written by the Python edition are served by the PHP edition (pages,
   photographs, two-step sign-in secrets and recovery codes, pbkdf2 passwords).
6. **Production mode** of the upload copy (`make-release.ps1`): database created with `bin/elf migrate`, templates
   compiled into the cache, HTTPS-only headers sent, development pages absent.

## Known differences from the Python edition

- **Passwords set by the Python edition with scrypt** (its default) cannot be checked by PHP's standard library.
  Those people use *Forgot your password?* once, or an administrator sends them reset links with
  `php bin/elf legacy-password-resets --send`. The current real database (`../elf-archive/instance/archive.db`) has
  9 such accounts. Passwords set by the PHP edition are stored with PHP's own methods, which the Python edition
  cannot read: moving back would need the same reset step.
- **Built-in server for local use**: `run-sample.ps1` and `run-dev.ps1` use PHP's built-in server, which answers one
  request at a time. That is fine for one person trying the site; a public site runs under Apache or nginx.
- **Not tested here**: Apache (`public/.htaccess`) and nginx (`docs/nginx.conf.example`) configurations, and sending
  real email over SMTP, because neither a web server nor a mail server is installed on this computer. The application
  itself was tested through PHP's built-in server and in-process requests. Check these on the host with the smoke test
  in DEPLOYMENT.md §8.
- **Large photographs**: GD holds a decoded picture in memory. The archive raises PHP's memory limit for a large photo
  when the host allows it, and otherwise refuses it with an explanation (instead of failing). `memory_limit = 512M`
  is recommended.

## Changes made to the Python edition during the port

The page-by-page comparison found these in the Python edition; they are fixed in both editions:

- The editor's staff page of an **archive item** or a **collection** failed with an error (it asked for a record form
  those kinds do not have). Fixed in `services/curation.py`; a regression test opens every staff record page of the
  sample archive (`tests/test_sampledata.py`, and `tests/PhotosAndToolsTest.php` here).
- The review page showed "None×None" as the size of a PDF. It now shows dimensions only for images
  (`templates/editor/review.html`).
- The browser test checked that an uploaded image had loaded as soon as the element was visible, which could fail on a
  slower server. It now waits for the image itself, and still fails if it never loads (`tests/e2e_browser.py`).

After these changes the Python edition's 241 unit tests and 16 browser scenarios pass.

## What remains

- Run the smoke test on the real host after deploying, including a real email.
- The Tigrinya and Arabic interface translations are still drafts until reviewed by native speakers (as in the
  Python edition).
- The legal pages (privacy, terms, copyright, data policy) are still drafts for a lawyer to approve (as in the Python
  edition).
