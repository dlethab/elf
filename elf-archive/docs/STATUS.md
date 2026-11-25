# Status (2026-10-14)

All six planned milestones are built. The software is ready to install on a server and use. Before launch, steps that need people outside the project remain: hosting, email, legal review, translation review, and independent accessibility and security reviews. They are listed in `LAUNCH_CHECKLIST.md`.

## PHP edition, and fixes found while porting (2026-10-26)

- **A PHP edition** of the whole site now exists in `../elf-php`, for ordinary PHP hosting. It shares this edition's database schema, migrations, translations, styles and scripts, so a database and media folder can move between them. Its pages were compared with this edition's, page by page, and this edition's browser test suite passes against it. See `../elf-php/docs/STATUS.md`.
- **Fixed:** the editor's staff page of an archive item or a collection failed with an error (`services/curation.py` asked for a record form those kinds do not have). A new test opens every staff record page of the sample archive (`tests/test_sampledata.py`).
- **Fixed:** the review page showed "None×None" as the size of a PDF; dimensions are now shown for images only.
- **Test made reliable:** the browser test now waits for an uploaded image to load before checking it, rather than checking as soon as the element appears.
- 241 unit tests and the 16 browser scenarios pass.

## Map and timeline fixed and restyled (2026-10-14)

- **Fixed:** the map, timeline and explore pages failed because the local database had not received the latest update (migration 0011).
  - On a development machine, pending updates are now applied when the app starts.
  - In production they are still applied deliberately (`flask --app elf_archive migrate`, after a backup). The app logs a clear error at start-up if any are pending.
- **New look, site-wide:** a minimal light design using the archive's colours, light blue (`#b4d7f4`) and green (`#239e46`).
  - Text and buttons use a deeper green (`#1b7a38`) so they keep AA contrast.
  - Dark mode follows the visitor's system setting.
  - The map and timeline now use the same theme as the rest of the site instead of their own dark one.
- **Layout:**
  - The map and timeline sit in rounded cards, aligned with the filters and header.
  - The view switch is a single segmented control, and the filters sit in one quiet card.
  - Map controls and the legend are floating white cards.
  - On the map, Eritrea is outlined in green on a light-blue sea. Blue marks uncertainty: approximate halos and date ranges.
  - Phones run the map and timeline edge to edge.
- **Tested:** 230 unit tests and 16 browser scenarios. axe-core passes on 43 pages, including dark mode. Six screen sizes were checked with no horizontal overflow.

## Choosing locations on a map, and archival depth in the atlas (2026-10-14)

- **Choosing a location on a map** (contribution forms, corrections and the editors' edit form):
  - **Place records:** click the map or drag the marker to fill in latitude and longitude. "Put the point at the centre of the map" works for keyboard users.
  - **Precision is never set automatically.** The form says how accurate a click is at the current zoom, and the contributor must still choose the precision. Places already in the archive within 3 km are listed, to avoid duplicates.
  - **Place fields** (where an event happened, birthplace, place of death, place of an affiliation): "Choose on the map" shows published places with coordinates.
  - **Clicking an empty spot** lists the nearest published places and offers "Propose a new place at this point", which opens a new place form with the coordinates filled in.
  - **Events and people are located only through place records,** never by loose coordinates.
  - Without JavaScript or WebGL, the coordinate and place fields work as before.
- **Archival images:**
  - Place panels and event previews (map and timeline) show a public archive image with its title, type, date (or "date unknown"), creator, rights holder and rights status.
  - The image opens the full archive record. Restricted or rights-unknown items never appear, and nothing stands in for a missing image.
- **Context:**
  - **Place panel:** families with a public member documented at the place (with the number of such members), archive collections, and the sources for the location. Shortcuts: explore this place's history, photographs and documents (n), read the sources (n), copy a link.
  - **Period summary:** setting a period shows counts and the places, people, families, collections and sources most often linked. "Most documented events" means most cited sources, not an editorial ranking. It is labelled as a count, not a history.
- **Evidence:**
  - Editors can mark a differing account as being about where a place is. Such places get a split-ring mark on the map, a note in the list, and the accounts in the panel.
  - Editors and reviewers can turn on a "Proposed places awaiting review" layer. Each proposal opens its review page. It is served from a separate, never-cached address and is not part of the public map data.
- **Layers:** "Places with documented events" and "Other places in the archive" can be turned on and off, each with an explanation. The menu says that historical routes and boundaries are not shown because no sourced data exists. No empty layer is offered.
- **Curated explorations** (`/explore/curated`, editors manage them under Editorial → Explorations):
  - Each is a saved list of published, public records, with a description, the editor's name, sources, and an optional period and region.
  - Only records that are public at the time are shown. A draft, or an exploration with no public record left, is not shown at all. Every change is logged in the audit log.
- **Tested:**
  - 227 unit tests, including 19 new ones in `tests/test_atlas_depth.py`.
  - 16 browser scenarios. The new one covers clicking the map, the required precision, choosing a place for an event, the proposals layer, place layers, the period summary, place shortcuts and a curated exploration.
  - axe-core passes on 43 pages, including the new ones.
- **Translations:** the 83 new interface strings have draft Arabic and Tigrinya translations. They need the same native-speaker review as the rest.

## Atlas polish, performance and verification (2026-10-14)

- **Interface:**
  - The explore page header is now one compact block: title, mode switch and a one-line description.
  - The filter bar shows search, event type and period; the other six filters sit under "More filters", with a count of active filters.
  - "Clear filters" appears only when a filter is active. The search button disappears once JavaScript is running, because filters apply immediately.
  - Clearer compass and home icons. Only Asmara is styled as the capital.
  - On phones, the timeline puts events before the toolbar and hides the long description and breadcrumbs.
- **Performance**, measured with a throwaway database of 400 places and 2,000 events (test data):

  | Measurement | Before | After |
  |---|---|---|
  | Map data | 568 KB | 334 KB |
  | Combined-mode page | 1,736 KB | 505 KB |
  | Map-mode page | — | 130 KB |
  | Cold map visit, total download | 4.3 MB | 2.9 MB |
  | Repeat visit, transferred | 1.8 MB | 335 KB (30 of 32 files from cache) |
  | Timeline-only visit | 2.7 MB | 1.4 MB |

  - The timeline-only visit is smaller because the map library (817 KB) now loads only when the map is shown.
  - Map interactive in about 1.0 s, timeline in about 0.4 s (local machine, software WebGL).
  - 30 mode switches showed no memory growth.
  - Static files carry a version in their address and can be cached for a year; elevation tiles for 30 days.
  - The combined and timeline pages list events 300 at a time.
- **Errors:**
  - Photos and thumbnails that fail to load are removed instead of showing a broken image.
  - Invalid filters in an address are ignored.
  - Missing records return a plain 404, with no technical details.
- **Geography verified by tests** (`tests/test_atlas_quality.py`):
  - The outline is Eritrea in [longitude, latitude] order (WGS 84), and the initial view frames it.
  - Each region contains its capital.
  - No historical boundaries are drawn.
  - Elevations are credible: Asmara about 2,330 m, Keren about 1,400 m, the Red Sea floor flattened at −150 m.
  - Markers use the record's coordinates exactly.
- **Tested:** 208 unit tests and 15 browser scenarios.
  - New browser scenario: keyboard-only use with reduced motion (Enter opens, Escape closes and returns focus, no panel animation).
  - axe-core passes on 38 pages.
  - Lint (ruff: pyflakes, pycodestyle, bugbear) is clean. JavaScript passes `node --check`.
  - There is no type checker or build step: the site has no TypeScript and no bundler.
- **Not verified:** the proxy configurations in `DEPLOYMENT.md` now set the same cache headers, and nginx compresses JSON. Neither Caddy nor nginx was available to test them, so check them with `curl -I` after deployment.

## Historical atlas upgrade (2026-10-14)

- **Map:** now a tilted 3D relief map of Eritrea (MapLibre GL JS with self-hosted elevation tiles from SRTM, GMTED2010 and ETOPO1, plus hillshading), replacing the flat Leaflet map.
  - Place markers are keyboard-reachable buttons, with distinct shapes for exact, approximate and region-only locations.
  - A side panel shows each place and its events, with their uncertainty.
  - There are controls for 2D/3D, facing north, resetting the view and map layers.
  - A period ribbon (events per year, split into exact, range and approximate) filters the map.
  - Each place has a shareable address (`/map?place=…`).
  - Without WebGL, visitors get the full list of places.
- **Timeline:** a time ruler (events per year by date certainty), decade sections, uncertainty marks on every event, and each event's places with links to them on the map.
- **Design:** both pages use a new dark "atlas" design system (`static/css/atlas.css`). Nothing is contacted outside this server.
- **3D atlas, second pass:**
  - Search across places (including other and historical names), people, events, organizations and archive records, with each result's record type shown.
  - Record previews list a record's places, so you choose which one to go to.
  - Place previews load on demand: summary, other names, events, people, organizations, photographs, and the sources for the location.
  - Marker shapes show the kind of place; the outline shows how precisely its location is known.
  - Filters for period, event type, place category, person, organization and archive materials, with removable chips.
  - Closing a preview restores the previous view.
  - On phones, previews open as a bottom sheet.
  - Full-screen mode, and touch gestures that only pan and zoom.
  - Timeline links open the event and its place and keep the period.
  - Fallbacks without WebGL, or when elevation data is missing.
- **Tested:** 192 unit tests and 14 browser scenarios. The atlas scenario covers search, previews, chips, the timeline link, the phone bottom sheet, the no-WebGL fallback and missing elevation data. axe-core passes on 36 pages.
- **Not yet:** historical routes and boundaries, which would need documented sources, and a per-place uncertainty radius (the data model records precision, not a radius). Map labels for modern towns and regions are in English only.

## One explore page: map and timeline together (2026-10-14)

- **One page, three addresses:** `/explore`, `/map` and `/timeline` all serve one page, starting in map, timeline or combined ("Map and timeline") mode; the combined mode is desktop only. Switching mode never reloads the page.
- **One shared state** (`static/js/atlas-state.js`) holds the mode, the filters (search, type, period, region, places of a kind, events at a place, person, organization, media) and the selection (place, event or other record).
  - The filter bar, chips, map, timeline and address all read it, so they cannot disagree.
  - Deliberate steps add a browser history entry, so back and forward work; typing and dragging only replace the current entry, and camera movement is never written.
- **Integration:**
  - A place's "Explore this place on the timeline" filters to events explicitly documented at that place, keeping the period and showing a removable chip and a context box.
  - An event's "Show on the map" centres on its single documented place or lets the visitor choose; with no documented place, nothing is drawn and the reason is given.
  - A period change applies to both views; a selection that no longer matches is closed with an explanation.
- **Shareable links are checked on the server:** only public records enter the page's state; anything else is dropped with a neutral notice that does not reveal whether the record exists. Older `/timeline?place=` links still work, read as "events at this place".
- **Tested:** 198 unit tests and 14 browser scenarios. The explore scenario covers all ten integration checks, including back and forward, a shared link, the phone layout and private records. axe-core passes on 38 pages.

## Interactive timeline (2026-10-14)

- **Horizontal timeline** (`/timeline`):
  - Zoom with buttons, Ctrl or pinch on the wheel, or + and −; move by dragging, horizontal scrolling or the earlier and later buttons.
  - An overview strip shows the whole filtered period with a window for what is in view.
  - "Use this view as the period" turns the visible years into the period filter.
  - Markers stack in rows; when there are too many to separate, they combine into "+n" buttons that zoom in.
- **Honest dates:** each event covers exactly the span its record allows (`atlas.date_interval`).
  - A day is a point. A month, year, decade or range is a bar meaning "somewhere within".
  - Approximate and decade-only dates are dashed. Undated events are listed but never placed.
  - Editors can mark a differing account as being about the date (migration 0010). The timeline, list and event page then say that sources disagree.
- **Markers:** shape shows the event category (armed conflict, political and organizational, lives and displacement, community and other), with colour repeating it.
- **Preview card:** category, date with its precision, any date disagreement, summary, an archival image, places (with location precision and map links), people and organizations. It sits beside the timeline on desktop and below it on phones.
- **Filters:** search, event type, period, region, place, person, organization, and "has photographs, documents or oral histories". All values come from the database, show as removable chips, and update the timeline, count, overview and list. The server-rendered list applies the same rules without JavaScript.
- **Linked to the map** (`static/js/atlas-state.js`), with the same address parameters and event rules on both pages:
  - "Show on the map" opens the event with its place and keeps the period and compatible filters.
  - On the map, "Events at this place on the timeline" opens the timeline focused on that place, keeping the period, with a "Back to this place on the map" link.
- **Event page:** date precision and disagreements; places with location precision and map links; oral histories; related events (same place or participant, with the reason given); links to the timeline and map.
- **Accessibility:** markers are buttons in date order with full descriptions; arrow keys move between events. The chronological list remains the alternative.
- **Tested:** 198 unit tests and 15 browser scenarios, including the full timeline-to-map workflow and the phone layout. axe-core passes on 37 pages.

## What works

**Records and connections**
- People, families, places, events, organizations and sources as shared records with permanent IDs and stable addresses (old addresses redirect).
- Names and aliases in any script, uncertain dates (approximate, decade, range, unknown), claim-level citations with evidence levels, differing accounts kept side by side.
- Links between records through the workflow: relationships, family memberships, affiliations with organizations (with role, dates, place and evidence), event participants.
- Complete revision history and an append-only audit log.

**Contributing and editing**
- Draft → submit → review → return for revision → approve → publish, plus reject and withdraw.
- Corrections to any public record, with a side-by-side diff for the editor.
- Editors can: edit directly with a reason; manage citations, differing accounts and links; merge duplicates (impact preview, permanent redirect); import CSV files (preview first, then submissions, then bulk publish); use a data-quality report; manage collections.
- Living people are protected by default. Family representatives have scoped, revocable grants.

**Files and oral histories**
- Contributors can upload photographs, PDF documents, audio and video. The type is checked from the file content, and PDFs with scripts or embedded files are refused.
- Images are re-encoded for visitors with all metadata (including GPS) removed. Audio and video metadata are stripped too when ffmpeg is installed.
- Originals are kept for staff. Every file request is checked against the item's access and rights, so a guessed address returns 404.
- Oral histories record consent per use and support embargoes, transcript and translation labelling, and timestamped transcripts that seek the recording. There is also a request-an-interview form.
- Researchers (granted by administrators) can see restricted items with research consent, and every such view is logged.

**Exploring**
- Global search across names, aliases, transliterations and permitted transcripts.
- A timeline with filters, and an interactive map on the archive's own base map of Eritrea (no third-party tile service). Places without coordinates are listed, never guessed.
- Family trees and connection diagrams, each with a list alternative.

**Community**
- Forum with categories, topics, replies, editing within a window (earlier versions kept), search and member profiles.
- Reports by category; moderation with logged reasons; posting pauses; reply notifications. Posting needs a verified email address.

**Accounts and security**
- Registration with email verification; lockout after repeated failures; password reset without revealing which accounts exist.
- Optional two-step sign-in (authenticator app, recovery codes, admin reset), which can be required for all staff.
- Server-side permission checks everywhere, CSRF protection, a strict Content-Security-Policy, HSTS in production, and correct visitor addresses behind a reverse proxy.

**Languages**
- English, Tigrinya and Arabic interfaces (Arabic right to left), switchable on every page.
- All public pages, contributor pages and information pages are translated.
- Staff tools and the draft legal pages are English only, and say so.

**Administration and operations**
- Operational overview: editorial backlog, data quality, media, rights and consent issues, forum reports, staff without two-step sign-in, last backup and export.
- User and role management, audit log, categories.
- Public data export (JSON + CSV, public fields only, audited) from the admin area or the command line.
- Backups of the database plus incremental media copies, recorded in the audit log.
- Email retried after temporary failures.

## What was tested

| Check | Result |
| --- | --- |
| `python -m unittest discover -s tests -t .` | **182 tests pass.** Covers services, schema rules, the workflow, forged requests across role boundaries, leak checks on every public surface (pages, search, sitemap, typeahead, map data, media, export), CSRF, sessions, lockout, two-step sign-in (including the RFC 6238 test vectors, replay and recovery codes), translations completeness, production settings, the reverse-proxy setting, email retries and the development seed |
| `python tests/e2e_browser.py` (Chromium) | **14 scenarios pass:** full editorial cycle, alias search, mobile menu, keyboard skip link, Arabic and Tigrinya (including Arabic on a 375 px phone), photo upload to publication, map with no third-party requests, forum report and moderation, duplicate merge with redirect, and an axe-core accessibility scan |
| Accessibility (axe-core 4.10.2, WCAG 2.0–2.2 A/AA rules) | **No violations on 35 pages:** public, signed-in and staff pages, in English, Arabic and dark mode. The scan found two problems, now fixed: map checkboxes below the 24 px target size, and dimmed text below AA contrast |
| `pip-audit` | No known vulnerabilities in the declared requirements or the installed environment (after upgrading pip) |
| Backup, then restore | Backup with integrity check and media copy run against the local database; the copy was restored, migrated forward and served pages and search correctly |
| Spec §26.3 scenarios | All 16 are covered by automated tests. For scenario 15, the mobile run opens the map and its list alternative, but touch gestures on the map itself are not automated |

**Not tested here:**
- ffmpeg is not installed on this machine, so stripping metadata from audio and video has not been run (its fallback has).
- Email has been tested with a simulated mail server, not a real provider.
- No load testing.
- The deployment guide has not been run on a real server from this machine.
- No independent accessibility audit or penetration test.

## What remains

**Needs people or accounts outside the project** (`LAUNCH_CHECKLIST.md`):
- A server, domain, SMTP account and off-site backup storage.
- Legal review of the privacy, terms, copyright and data pages, and a choice of data licence.
- Native-speaker review of the Tigrinya and Arabic translations. Both were written by an AI assistant without native-speaker review, and the site says they are drafts; marking a catalogue as reviewed removes the notice.
- An independent accessibility review with disabled users, and an independent security review.

**Known limits of the software:**
- SQLite on one server. It suits the expected scale; a PostgreSQL path is described in `ARCHITECTURE.md`.
- Media on local disk only (no S3-compatible storage yet).
- No built-in virus scanner (a scheduled ClamAV scan is described in `DEPLOYMENT.md`).
- No HEIC images (phones usually convert them when uploading through a browser).
- No captions for video.
- Files from rejected or withdrawn submissions are kept, and there is no clean-up command yet.
- Gregorian dates only (no Ethiopian calendar display).
- Staff tools are English only.
- The map shows modern borders and regions only; historical boundaries would need a sourced, licensed dataset.

## Configuration summary

Every setting is in `.env.example`. These must be set for production:
- `ELF_ENV=production`, `ELF_SECRET_KEY`, `ELF_BASE_URL` (https)
- `ELF_DATABASE_PATH`, `ELF_MEDIA_ROOT`
- `ELF_TRUSTED_PROXIES=1`
- `ELF_SMTP_*`, `ELF_CONTACT_EMAIL`

Recommended once staff are set up: `ELF_REQUIRE_STAFF_MFA=true`.
