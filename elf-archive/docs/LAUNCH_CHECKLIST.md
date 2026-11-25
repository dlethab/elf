# Launch checklist

Everything the software can do is built and tested. These are the remaining steps that need decisions, accounts or people outside the project. Work through them in order; tick each when done.

## Decisions and accounts

- [ ] **Name and domain.** Confirm the archive's public name (`ELF_SITE_NAME`) and register the domain.
- [ ] **Governing body.** Decide who owns the archive, who appoints administrators and editors, and who decides disputed removal requests.
- [ ] **Server.** Rent a Linux server with a persistent disk and follow `DEPLOYMENT.md`.
- [ ] **Email.** Open an SMTP account and set `ELF_SMTP_*`. Send a test verification email.
- [ ] **Off-site backup storage** under a different provider and account holder from the server. Set up the nightly copy (`DEPLOYMENT.md` §8).
- [ ] **Contact address** (`ELF_CONTACT_EMAIL`) that someone reads.

## People

- [ ] At least **two administrators**, so the archive never depends on one person. Both use two-step sign-in.
- [ ] **Editors** appointed and given `EDITORIAL.md` and `ADMIN_GUIDE.md`.
- [ ] **Moderators** for the forum, with the community rules (`/community/rules`) agreed.
- [ ] Turn on `ELF_REQUIRE_STAFF_MFA=true` once every staff member has two-step sign-in.

## Content and policy

- [ ] **Legal review** of the privacy policy, terms of use, copyright and data policy pages (`elf_archive/templates/pages/`). They describe what the software does, but they are drafts and are not legal advice. Add the operator's legal name, jurisdiction and data-protection contact.
- [ ] **Data licence** for the public export decided and stated on the data policy page.
- [ ] **Editorial guidelines** (`EDITORIAL.md`) adopted by the editorial board.
- [ ] **Translation review.** Native speakers review `translations/ti.json` (Tigrinya) and `translations/ar.json` (Arabic). When each is approved, set its `"status"` to `"reviewed"`; the "draft translation" notice then disappears for that language. The legal pages are then translated once the English text is final.
- [ ] **Interview consent form** for oral histories, matching the per-use consent options the site records.
- [ ] **No test data.** The admin overview must show 0 fictional records. (Never run `seed-test-data` in production; it refuses.)

## Checks before opening to the public

- [ ] Smoke test from `DEPLOYMENT.md` §10 passes on the live server.
- [ ] A backup has run and a **restore has been tested** (`OPERATIONS.md`).
- [ ] **Independent accessibility review**, ideally including disabled users and screen-reader users of Tigrinya and Arabic. The automated scan (axe-core) passes on 35 pages, but automated tools find only part of the problems.
- [ ] **Independent security review** (penetration test) of the live site.
- [ ] `ffmpeg` installed on the server (removes metadata from audio and video).
- [ ] Optional: ClamAV scheduled scan of the media folder (`DEPLOYMENT.md` §13).
- [ ] Optional: a street-level map layer (`ELF_MAP_TILE_URL`) chosen with its provider's terms in mind. The archive's own base map works without it.

## After launch

- [ ] Weekly and monthly routines in `ADMIN_GUIDE.md` assigned to named people.
- [ ] Quarterly restore test in the calendar.
- [ ] A plan for software updates: who applies security updates to the server, and who maintains the code.
