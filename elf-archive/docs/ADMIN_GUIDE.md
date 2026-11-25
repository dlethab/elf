# Running the archive: administrator and editor handbook

This is the handover guide for the people who run the archive day to day. It needs no programming knowledge. Server setup is in `DEPLOYMENT.md`; editorial judgement (what to publish and how) is in `EDITORIAL.md`.

## Roles at a glance

| Role | Who | Can |
| --- | --- | --- |
| Contributor | Anyone who registers and verifies their email | Propose records, corrections, photos, documents, recordings and oral histories; post in the forum |
| Family representative | A contributor given a grant on one family by an editor | Propose relationships and members for that family, suggest edits to it |
| Editor | Trusted archive staff | Review and publish submissions, edit records directly, cite sources, merge duplicates, import CSV files, set rights and consent, manage collections |
| Moderator | Forum volunteers | Handle forum reports, hide or remove posts, lock topics, warn or pause members. No access to archive submissions or restricted records |
| Researcher | Vetted researchers | View restricted archive items, and interviews whose interviewee agreed to research access. Every view is logged |
| Administrator | One or two people | Everything an editor and moderator can do, plus users and roles, audit log, categories, data export |

Full matrix: `PERMISSIONS.md`. Roles are added in **Admin → Users → (person) → Roles**. Give each person the least they need.

## Routine

**Daily (editors)**
- **Editor → Queue.** Work through *New* and *Under review*. Flags show living people, missing sources, possible duplicates, a record changed since the submission was made, and rights notes.
- **Editor → Messages.** Contact-form messages, including corrections and removal requests from people without accounts. Mark each handled.

**Daily (moderators)**
- **Moderation.** Open reports, oldest first. Every action needs a reason, which is kept in the moderation log.

**Weekly (administrator)**
- **Admin → Overview.** Check: the last backup date is recent; no emails failed; open and escalated forum reports; staff without two-step sign-in (should be 0); archive items with unknown rights; oral histories without publication consent.
- **Editor → Data quality** and **Editor → Duplicates.** Prompts for research, not errors.

**Monthly (administrator)**
- Skim **Admin → Audit log** for anything unexpected (role grants, access changes, research-access views).
- Download a **public data export** (Admin → Data export) and keep it with the off-site backups.

**Quarterly (administrator)**
- **Test a restore** (`OPERATIONS.md`). An untested backup is not a backup.
- Review who holds staff roles and researcher access; revoke what is no longer needed.

## Common tasks

### Give someone a role
Ask them to register and verify their email. Then **Admin → Users**, search for them, open their page, choose the role and **Grant**. Revoking works the same way and takes effect immediately. The system will not let you remove the last administrator.

### Grant researcher access
Agree the terms first (purpose, period, no redistribution). Then grant the *researcher* role. They can now see restricted (not private or embargoed) photographs, documents and recordings, and oral histories whose interviewee agreed to research access, with a notice on every such page. Restricted records about people stay closed to them. Each view is written to the audit log (`restricted.viewed`). Revoke the role when the research ends.

### Make someone a family representative
Open the family's staff page (**Editor → Records**, find the family). Under *Family representatives*, choose the user and the three permissions (propose relationships, suggest edits, submit media). Their proposals still go through review.

### Someone lost their phone (two-step sign-in)
They should first try one of their recovery codes. If they have none left: confirm who they are by a means other than email (a call, or in person), then **Admin → Users → (person) → Reset two-step sign-in**. This also signs them out everywhere. They sign in with their password and set it up again.

### A staff account may be compromised
**Admin → Users → (person) → Deactivate.** All their sessions end immediately. Then check the audit log for their recent actions, reverse anything wrong through the normal record tools (every change kept its previous value), and reset their two-step sign-in before reactivating.

### Someone asks for their account to be deleted
**Anonymise** the account. Their personal details are removed; their contribution history stays without their name, so the archive's provenance trail is not broken.

### Removal or restriction request about a record
Requests come through the contact form or by email. Do not delete records. On the record's staff page, use **Access → Restrict** (or *Unpublish*) with a reason; the reason is kept in the audit log, and the public address then returns "not found". For a photo or document, change its access or rights on the item's staff page. Reply to the person saying what was done. If the request is disputed, restrict first and decide afterwards.

### An interviewee changes their consent
Open the oral history's staff page. Under *Consent*, change the specific permission (for example *Publishing the transcript*) and record the evidence (who, when, how). Earlier consent records are kept, marked as withdrawn, not deleted. What visitors see updates immediately. To pause everything, set an **embargo** date.

### A published photo turns out to have the wrong rights
On the item's staff page, change the rights status. Anything other than *public domain*, *permission granted* or *licensed* stops public display at once, including direct links to the file.

### Merge two records for the same person
**Editor → Duplicates** lists likely pairs; or open **Editor → Merge** with both permanent IDs. The preview shows exactly what moves. Give the reason (it is kept). The retired record's address redirects to the kept one forever. Merging cannot be undone with a button, so be sure first.

### Bulk import from a spreadsheet
**Editor → Import**: download the CSV template for the record type, fill it in, upload. You see a preview with every row's problems before anything is created. Confirmed rows become ordinary submissions in the queue, which can be published together with **Bulk publish**.

### Add a place or event category
**Admin → Categories.** Categories can be renamed or hidden but not deleted while records use them.

### Fix or improve a translation
The Tigrinya and Arabic interface text is in `elf_archive/translations/ti.json` and `ar.json`, one line per phrase: `"English text": "translation"`. Change only the right-hand side, keep any `{name}`-style placeholders exactly, save as UTF-8, then restart the site (`sudo systemctl restart elf-archive`). When a native-speaker review is complete, change `"status": "draft"` at the top of the file to `"reviewed"` to remove the "draft translation" notice. Historical content (names, biographies, transcripts) is never machine-translated.

### Export the archive's public data
**Admin → Data export → Download.** The ZIP contains only what the public site shows, as JSON and spreadsheet-friendly CSV, with a manifest. It is not a backup: confidential fields and media files are left out on purpose. For a full copy, see backups below.

## Backups and restore

The server takes a backup every night (database plus an incremental copy of media files) and keeps 14 days. An off-site copy must also exist (see `DEPLOYMENT.md` §8). How to test and perform a restore: `OPERATIONS.md`.

If the admin overview says "No backup has been recorded" or the date is old, tell whoever looks after the server the same day.

## Where things are recorded

| Log | What | Where |
| --- | --- | --- |
| Revision history | Every change to a published record, with its previous values | Record page (public summary) and staff record page (full) |
| Audit log | Sign-ins, role and account changes, publications, access and rights changes, consent changes, merges, imports, research-access views, exports, backups | Admin → Audit log |
| Moderation log | Every moderator action and its reason | Moderation pages |
| Submission history | Every step of a submission, with editors' messages | Submission page |

None of these can be edited or deleted through the website.

## Getting help

Technical problems: whoever administers the server, with `journalctl -u elf-archive --since "1 hour ago"` output if possible. The application never shows error details to visitors; it logs them.
