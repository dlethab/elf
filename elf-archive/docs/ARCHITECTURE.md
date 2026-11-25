# Architecture

This document is the architecture proposal requested by the specification (§28 Rule 2, §30 A–D). It describes what is built, the reasoning, and the tradeoffs.

## 1. Environment findings

The project started from an empty workspace (no repository). The build environment has Python 3.13 with Flask 3.1, Werkzeug, Jinja2 and Pillow, SQLite 3.45 with FTS5, Node 22, ffmpeg, ImageMagick and Playwright with Chromium. It has **no PostgreSQL** and **no general internet access**, so packages beyond those installed cannot be fetched and a Next.js/Prisma/PostgreSQL stack could not be installed, run or tested here.

## 2. Stack and the main tradeoff

| Concern | Choice | Why |
| --- | --- | --- |
| Web framework | Flask 3 (Python), server-rendered Jinja templates | Available and testable here; small, stable, easy for a small team to maintain; server rendering gives crawlable pages and works without JavaScript |
| Database | SQLite (WAL mode), plain SQL migrations | One file, trivial to back up and move (spec §22.5), full-text search built in, no server to operate |
| Search | SQLite FTS5 with a public-only index | Built in; diacritic-insensitive tokenizer; enough for an archive of this size |
| Auth | Werkzeug scrypt password hashing + server-side session table | Maintained primitives, not custom crypto; sessions are revocable server-side |
| Styling | One hand-written CSS design system with tokens | No build step; strict CSP (no inline styles or scripts) |
| Tests | `unittest` + Flask test client + Playwright | All available offline |

**Tradeoff — the spec's default was Next.js + PostgreSQL.** The Flask + SQLite stack was chosen because it is the one that could actually be built, run and tested in this environment, and because a historical archive has few concurrent writers (editors and contributors), which suits SQLite well. Costs: SQLite allows one writer at a time (fine for this workload; not for thousands of simultaneous contributors), and hosting must give the app a persistent disk. **Migration path:** the schema is standard SQL with foreign keys and CHECK constraints; moving to PostgreSQL would mean translating the macros in `db.py`, replacing FTS5 with `tsvector`, and rewriting the append-only triggers in PL/pgSQL. The service layer would not change. This is the one decision flagged for the project owner in `STATUS.md`.

## 3. Project structure and layering

```
web/ (HTTP: parse request, call service, render)  →  services/ (rules, validation, transactions)  →  SQLite
queries.py (read-only public queries, always PUBLIC_WHERE)
permissions.py (role → permission matrix)   security.py (CSRF, headers, cache, route guards)
```

Templates never query the database. Historical content is data only; nothing historical is hard-coded in templates (spec Rule 6).

## 4. Data model

The full schema is in `elf_archive/migrations/`. Key design points:

### 4.1 Shared entity registry
Every canonical record (person, family, place, event, organization, source, archive item, collection, oral history) has one row in **`entities`** holding: permanent ID (`per-xxxxxxxx`), slug, publication status, visibility, merge pointer, soft-delete time, fictional-test flag. Each kind has a subtype table (`people`, `places`, …) keyed by the same id.

**Referential integrity for polymorphic links (spec §19.2):** every subtype table and every link column carries a fixed `kind` column, and foreign keys reference `entities(id, kind)`. A `birth_place_id` therefore *cannot* point at a person, and a citation's `source_id` cannot point at an event. This is enforced by SQLite, not by application code, and is tested.

### 4.2 Core tables

| Area | Tables |
| --- | --- |
| Identity | `users`, `user_roles`, `user_sessions` (hashed tokens), `auth_tokens` (hashed), `rate_events`, `outbox` |
| Registry | `entities`, `entity_slug_history` (old URLs redirect), `entity_names` (names, aliases, transliterations, original script; `normalized` search form kept separately) |
| People and families | `people`, `families`, `family_memberships`, `family_representatives` (scoped, revocable grants), `relationships` |
| Organizations | `organizations`, `affiliations` (time-ranged, evidence-rated) |
| Places and events | `places` (+ coordinate precision), `place_alt_locations`, `place_types`, `events`, `event_types`, `event_places`, `event_participants` |
| Evidence | `sources`, `citations` (one source → one claim on one record), `conflicting_accounts` |
| History | `revisions` (full snapshots, append-only), `audit_logs` (append-only), `merges` |
| Workflow | `submissions`, `submission_events` (append-only), `notifications`, `contact_messages` |
| Archive (schema only) | `archive_items`, `media_files` (checksums, derivatives, access level), `collections`, `collection_items`, `oral_histories`, `consent_records` (one row per consent type) |
| Community (schema only) | `forum_categories`, `forum_topics`, `forum_posts`, `reports`, `moderation_actions` (append-only) |

### 4.3 Uncertain dates (spec §19.3)
Each date is four columns: `*_start`, `*_end`, `*_precision` (exact, month, year, decade, approximate, range, unknown), `*_note`. Start and end hold partial ISO strings (`1952`, `1952-03`, `1952-03-14`); nothing is padded to a fake day. A CHECK constraint forbids a stored date when precision is `unknown`. Conflicting dates are recorded in `conflicting_accounts`.

### 4.4 Relationships
`relationships` holds typed person-to-person links (parent, adoptive parent, step-parent, guardian, spouse, partner, sibling, other documented) with status (current, historical, uncertain, disputed), dates, notes, publication and visibility. Symmetric types are stored once in canonical order (CHECK constraint), so A–B and B–A cannot both exist. Nothing assumes relationships are biological.

### 4.5 Integrity rules enforced by the database
Composite kind foreign keys; no half coordinates; coordinates require a precision; no date with "unknown" precision; append-only revisions, audit log, submission events and moderation log (triggers); one active family-representative grant per user and family; one active consent row per type; derivatives must point at their original file.

### 4.6 Deletion and retention
Historical records are never hard-deleted by the application: they are archived, restricted, merged (tombstone with `merged_into`) or soft-deleted. User accounts are deactivated and then anonymised (personal fields replaced) so contribution and audit history survives without personal data.

## 5. Visibility rule

One definition, `PUBLIC_WHERE` in `services/entities.py`: published **and** public **and** not deleted **and** not merged. Every public query, the search index, the sitemap, and record resolution use it. A restricted or draft record returns the same 404 as a record that never existed, and appears in no list, search result, related-record panel, relationship list, sitemap or metadata. People recorded as living are published as **restricted** unless an editor explicitly confirms consent.

## 6. Editorial workflow

```
draft ─▶ submitted ─▶ under_review ─▶ approved ─▶ published
  │          │  ▲          │              │
  │          ▼  │          ▼              ▼
  │    needs_revision ◀────┘          rejected
  └──▶ withdrawn (by submitter, any time before approval)
```

`services/workflow.py` is the only code path that creates or changes public records from contributions. It checks the transition is legal, the actor's permission, that editors are not reviewing their own work (configurable), that a reason is given for returns and rejections, and that referenced places and people are still public at publication time. Publication runs in a single transaction: either the record, its names, sources, citations, revision, audit entry and search index entry are all written, or none are.

Contributions never touch entity tables until published. Corrections store only the changed fields; names and sources added in a correction are additive, and a renamed record keeps its old name as a searchable alternate.

## 7. Search

FTS5 table `search_fts`, one row per **public** entity: normalized title, all normalized names/aliases, and body text. Normalization folds case and diacritics, drops apostrophe variants (so *Ghebre'ab* = *Ghebreab*), and keeps Ge'ez and Arabic letters. Queries use prefix matching on every token, rank title and alias matches above body text, re-check `PUBLIC_WHERE` (so a stale index row can never leak), report which alternate name matched, and offer "did you mean" suggestions from public names only.

## 8. Security summary

Server-side permission checks on every route (`security.require`) and again inside services; CSRF tokens on every POST; session token rotation on login; logout and password changes revoke sessions in the database; login rate limiting per account and per network address with timing equalisation; no account enumeration on reset; open-redirect protection; strict Content-Security-Policy with no inline code; `X-Frame-Options: DENY`; `no-store` on every personalised or private response; parameterised SQL throughout; Jinja auto-escaping; secrets never logged. Production refuses to start with the development secret or a non-https base URL.

## 9. Page and route inventory

Generated from the application's route table. Every POST needs a CSRF token; every non-public route checks its permission on the server (`security.require`) and again in the service it calls.

**Public** (`web/public.py`)
| Route | Purpose |
| --- | --- |
| `/` | Home: mission, category cards with real counts, timeline preview, contribution call |
| `/people`, `/families`, `/places`, `/events`, `/organizations`, `/sources` | Paginated lists with A–Z filter |
| `/<section>/<slug>` | Record pages; old slugs 301-redirect; merged records redirect to the kept record |
| `/people/<slug>/tree`, `/families/<slug>/tree` | Family tree (server-rendered SVG with a list alternative) |
| `/people/<slug>/connections` | Connection diagram: family, organizations, events (with a list alternative) |
| `/id/<permanent-id>` | Permanent identifier resolver (follows merges) |
| `/search?q=&type=` | Global search (names, aliases, transliterations, transcripts where consent allows) |
| `/explore` (also `/map`, `/timeline`) | One page with map, timeline and combined modes over one URL-backed exploration state (`atlas-state.js`; the server admits only public identifiers into it). `explore.js` runs the shared filter bar, chips and mode switch; `map.js` and `timeline.js` subscribe to the state and request changes through it, never keeping their own copies |
| `/timeline/data.json` | Interactive horizontal timeline (`static/js/timeline.js`) over all public events, each drawn over the span its record allows (`atlas.date_interval`); filters shared with the map through `static/js/atlas-state.js`; the server-rendered list applies the same rules without JavaScript |
| `/map`, `/map/data.json`, `/map/basemap.json` | Interactive map on the archive's own Eritrea base map (Natural Earth); place list alternative |
| `/archive`, `/archive/<slug>` | Photographs, documents, audio and video whose own access level and rights allow public display |
| `/collections`, `/collections/<slug>` | Curated collections (only their public items are shown) |
| `/oral-histories`, `/oral-histories/<slug>`, `/oral-histories/request` | Interviews, each element shown only with its consent; request-an-interview form |
| `/media/<key>` | Every stored file; the access rule in `services/photos.can_view_media` is checked on each request; supports range requests |
| `/lookup/<kind>` | Typeahead for reference fields (published public records only; rate-limited) |
| `/language/<en|ti|ar>?next=` | Sets the interface-language cookie and returns to the page |
| `/about`, `/standards`, `/how-to-contribute`, `/corrections`, `/privacy`, `/terms`, `/copyright`, `/accessibility`, `/data-policy`, `/contact` | Information pages and contact form |
| `/robots.txt`, `/sitemap.xml` | Crawling (public, non-fictional records only) |

**Authentication** (`web/auth.py`): `/auth/register`, `/auth/login`, `/auth/two-step` (second step when two-step sign-in is on), `POST /auth/logout`, `/auth/verify/<token>`, `POST /auth/resend-verification`, `/auth/forgot`, `/auth/reset/<token>`. Development only: `/dev/outbox`.

**Contributor** (`web/dashboard.py`): `/dashboard`, `/dashboard/submissions[/<id>[/edit]]`, `POST …/<id>/<submit|withdraw>`, `POST …/<id>/photos` (multipart; JSON when sent with `X-Upload-Progress: 1`), `POST …/photos/<pid>/remove`, `/contribute/<person|family|place|event|source|organization|affiliation|membership|participation|oral_history>`, `/contribute/correction/<permanent-id>`, `/contribute/relationship`, `/dashboard/profile`, `/dashboard/password`, `/dashboard/security` (two-step sign-in), `/dashboard/notifications`.

**Community** (`web/community.py`): `/community`, `/community/c/<category>[/new]`, `/community/topics/<slug>`, `POST …/reply`, `/community/posts/<id>/edit` (author, within the edit window; earlier versions kept), `POST /community/report`, `/community/rules`, `/community/search`, `/community/users/<username>`. Moderators: `/moderation` (report queue), `POST /moderation/<posts|topics|reports|users>/<id>` (every action needs a reason and is logged).

**Editorial** (`web/editor.py`): `/editor` (queue with tabs and flags), `/editor/submissions/<id>` (review, photo decisions, consent confirmation), `POST …/transition`, `POST …/note`, `POST /editor/bulk` (bulk publish of import batches), `/editor/records[/<permanent-id>]` (staff view), `…/edit` (direct edit with reason), `POST …/state`, `POST …/slug`, `POST …/citations[/<cid>]`, `POST …/accounts[/<aid>]` (differing accounts), `POST …/links/<table>/<lid>`, `POST …/rights`, `POST …/consent/<type>`, `POST …/oral-controls` (embargo, transcript review), `POST …/collection[/items]`, `/editor/duplicates`, `/editor/merge`, `/editor/import[/<id>]`, `/editor/import/template/<kind>.csv`, `/editor/quality`, `/editor/collections`, family-representative grants, `/editor/messages`.

**Administration** (`web/admin.py`): `/admin` (operational overview: editorial backlog, data quality, media, rights and consent, forum reports, staff without two-step sign-in, last backup and export), `/admin/users[/<id>]`, `POST …/roles`, `POST …/<deactivate|reactivate|anonymize|verify|reset_mfa>`, `/admin/audit`, `/admin/taxonomies`, `/admin/export` (public data export).

## 10. Components added after Milestone 1

**Map (historical atlas).** MapLibre GL JS 4.7.1 (BSD-3), vendored in `static/vendor/maplibre`; its CSP build is used, with the worker served from this server, so the strict CSP needs no `unsafe-eval` (only `blob:` images, for the browser's own tile decoding). The 3D relief comes from elevation tiles in `static/map/terrain` (zoom 5–9, about 20 MB), built once by `tools/build_terrain.py` from the open Terrain Tiles dataset (SRTM, GMTED2010, ETOPO1; AWS Open Data) and served from this server; the sea floor is flattened at −150 m for legibility and no land elevation is changed. Borders, regions, rivers and towns come from `static/map/eritrea-basemap.json`, built by `tools/build_basemap.py` from Natural Earth (public domain); regions are named by the capital each contains, because the source mislabels four. Labels are HTML (so Ge'ez and Arabic render with system fonts) with a priority-based collision check. Archive places are keyboard-reachable buttons, clustered by MapLibre; exact, approximate and region-only locations have different shapes, explained in the place panel. A period ribbon (events at mapped places per year, split into exact, range and approximate/decade) filters the map and links to the timeline; the timeline links each event to `/map?place=`. Without WebGL the page keeps the full list of places. No third-party service is contacted unless `ELF_MAP_TILE_URL` is set, in which case the CSP allows exactly that host. No historical boundaries are drawn.

**Atlas data and behaviour.** `atlas.py` holds the read side: marker categories (shape by place type: settlement circle, region or area diamond, conflict location square, other sites triangle; the outline shows precision: solid = documented, dashed with a halo = approximate, dotted ring = region only), the people, organizations and archive items linked to each mapped place (for filters), and previews. Routes: `/map/data.json` (all mapped places, small), `/map/place/<id>.json` (place panel, loaded on demand: summary, other names, events, people, organizations, photographs, location sources), `/map/record/<id>.json` (any public record and its mapped places, plus a count of linked places without coordinates), `/map/search.json?q=` (places by any recorded name, people, events, organizations, archive records; each result typed). `/map?place=`, `?event=` (from the timeline, with `from`/`to` kept), `?person=`, `?organization=` open the atlas in that state. A record reaches the map only through a public place with valid coordinates (the database also rejects out-of-range or half coordinates); places are never joined by lines. Camera: tilted overview fitted to Eritrea (gentler on phones), short eases for nearby selections and longer flights only for long moves, never zooming an approximate place as if exact; closing a preview restores the earlier view. Touch gestures pan and zoom only (rotation and tilt are buttons). Relief is raised 1.3× in 3D, stated in the legend. Fallbacks: no WebGL or a lost WebGL context → a flat SVG map of the same geography with the same place buttons; elevation tiles missing → a flat map and a notice; places data failing → the server-rendered lists. Low-memory devices start in 2D; pixel ratio is capped at 2.

**Media.** `services/storage.py` stores files under random keys outside the web folder (local disk; the interface is ready for an S3-compatible backend). `services/photos.py` sniffs the type from content (Pillow for images; signatures for PDF, MP3, M4A, OGG, WAV, FLAC, MP4, WebM), refuses PDFs with active content, re-encodes images for visitors with all metadata removed, and strips audio/video metadata with ffmpeg when it is installed. Originals are kept for staff. Rights status and access level are checked separately from the record's own visibility on every request.

**Oral histories.** `services/oral.py` is the single answer to "may this part of this interview be shown?": one consent row per use (record, store, publish recording, transcript, translation, excerpts, research access, download), embargo overriding all of them, and consent recorded only when an editor confirms evidence of it.

**Researchers.** The `researcher` role (granted by administrators) may view restricted (never private or embargoed) archive items, and oral histories whose interviewee consented to research access. With `ELF_REQUIRE_STAFF_MFA` on, this also requires two-step sign-in. Every such view writes a `restricted.viewed` audit entry and the page carries a notice.

**Curation.** `services/curation.py` (direct edits, citations, differing accounts, link management; every change keeps the previous value and a reason), `services/merging.py` (impact preview, merge with tombstone and redirect, duplicate report), `services/importer.py` (CSV preview, then submissions, then bulk publish), `services/graph.py` (trees and connection diagrams).

**Forum.** `services/forum.py`: categories, topics and posts in the database; posting needs a verified account; rate limits; edits within a time window with earlier versions kept (`forum_post_edits`, append-only); reports by category; moderation actions with reasons in `moderation_actions`; posting pauses; reply notifications. Forum posts never become archive records except through the editorial workflow.

**Two-step sign-in.** `services/mfa.py`: TOTP per RFC 6238 (verified against the RFC's test vectors), replay protection, rate-limited attempts, ten single-use recovery codes stored as hashes, QR code rendered locally as inline SVG. Administrators can reset it; `ELF_REQUIRE_STAFF_MFA=true` makes it mandatory for staff tools.

**Interface languages.** `i18n.py` with catalogues in `translations/ti.json` and `ar.json` (English text is the key). Arabic is right to left. Staff tools and the draft legal pages are English only and marked `lang="en"`.

**Data export.** `services/export.py`: a ZIP of public data as JSON and CSV. Each exported table has an explicit column list and an explicit list of excluded columns; a test fails if a new column is not classified. Transcripts and translations follow consent and embargo. Admin download and `flask export-public`; every export is audited.

**Reverse proxy.** `ELF_TRUSTED_PROXIES` enables Werkzeug's `ProxyFix` for that many hops, so rate limits and logs see the visitor's address instead of the proxy's. HSTS is sent in production.

## 11. Milestones

| # | Scope | Status |
| --- | --- | --- |
| 1 | Schema, migrations, auth, roles, editorial workflow, design system, record pages, search, admin foundation | Done |
| 2 | Duplicate merging, citation and differing-account management, organizations and affiliations, family memberships and event participants via the workflow, CSV import with preview | Done |
| 3 | Interactive map, timeline filters, family tree, connection diagrams | Done |
| 4 | Secure uploads (photos, documents, audio, video), storage, rights, collections, oral histories with consent, researcher access | Done |
| 5 | Forum, reports, moderation, notification preferences | Done |
| 6 | Exports, Tigrinya and Arabic interfaces with RTL, two-step sign-in, automated accessibility and dependency checks, deployment and handover guides | Done, except the independent accessibility and security reviews and native-speaker translation review, which need people outside the project (see `STATUS.md`) |

## 12. Testing strategy

- **Unit, service and HTTP integration tests** (`python -m unittest discover -s tests -t .`): services, schema constraints, workflow rules, publication atomicity, living-person protection, forged requests against every role boundary, leak checks across public surfaces (pages, search, sitemap, lookup, media, map data, exports), CSRF, sessions, lockout, two-step sign-in, open redirects, headers, production configuration, translations completeness.
- **Browser end-to-end** (`python tests/e2e_browser.py [screenshot_dir]`): Chromium through 14 scenarios, including the full editorial cycle, photo upload, languages and RTL on a phone, map, forum moderation, merging, and an axe-core accessibility scan (WCAG 2.0–2.2 A/AA rules) of 35 pages in English, Arabic, signed in and dark mode. axe-core 4.10.2 is vendored in `tests/vendor` (MPL-2.0) and is used only by tests.
- **Dependencies**: `pip-audit -r requirements.txt` (no known vulnerabilities at the time of writing).
