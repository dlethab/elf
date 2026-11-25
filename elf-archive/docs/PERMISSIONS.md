# Roles and permissions

Enforced on the server in `elf_archive/permissions.py` (role → permission matrix), in route guards (`security.require`), and again inside services. Hiding a button is never the protection. Forged-request tests in `tests/` check the boundaries.

Roles are additive. Every active account is a **contributor**. **Family representative** is not a role: it is a grant on one specific family, made and revoked by editors, with three separate switches. **Researcher** is granted by administrators to vetted researchers; it never opens private or embargoed material, or restricted records about people.

## Matrix

| Capability | Visitor | Contributor | Family rep (own family) | Researcher | Moderator | Editor | Administrator |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Browse published public records, search, map, timeline, trees, archive, oral histories (as consent allows) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Read the forum | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Send a contact / correction message, request an interview | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Save drafts (before email verification) | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Submit records, links, corrections, files and oral histories (verified email) | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Post, reply, edit own posts (within the edit window), report (verified email) | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Turn on two-step sign-in | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Propose relationships and members for a family | | | ✓ (if granted) | | | ✓ | ✓ |
| View restricted archive items, and interviews whose interviewee agreed to research access (each view logged) | | | | ✓ | | ✓ | ✓ |
| Handle forum reports; hide, remove, lock, pin; warn or pause members | | | | | ✓ | | ✓ |
| Editorial queue: review, return, approve, reject, publish | | | | | | ✓ | ✓ |
| Review own submission | | | | | | ✗ (configurable) | ✗ (configurable) |
| Edit records directly, manage citations and differing accounts, manage links (reason required) | | | | | | ✓ | ✓ |
| Restrict, unpublish, republish, change slug (reason required) | | | | | | ✓ | ✓ |
| Rights, access and consent decisions on files and oral histories | | | | | | ✓ | ✓ |
| Merge duplicates, CSV import, bulk publish, collections | | | | | | ✓ | ✓ |
| Grant / revoke family representatives | | | | | | ✓ | ✓ |
| Read contact messages | | | | | | ✓ | ✓ |
| Manage users and roles, deactivate, anonymise, reset two-step sign-in | | | | | | | ✓ |
| Audit log, categories, operational overview, data export | | | | | | | ✓ |
| Remove the last administrator | | | | | | | ✗ (refused) |

Moderators have **no** access to archive submissions, restricted records or user management (spec §3.5). Editors cannot manage users or roles. Researchers cannot edit or publish anything.

With `ELF_REQUIRE_STAFF_MFA=true`, every staff permission (everything below "Turn on two-step sign-in" in the table) additionally requires two-step sign-in to be on.

## Record-level rules

- A record is publicly visible only if it is published, public, not deleted and not merged. Anything else returns the same 404 as a record that never existed, on every surface: pages, search, sitemap, typeahead, map data, trees, media files and the public export.
- People recorded as living are published as restricted unless an editor confirms consent. A correction that marks a public person as living restricts the record automatically. Links (relationships, memberships, affiliations) to non-public people are omitted everywhere public.
- A file is shown publicly only when its item is public, its own access level is public, and its rights status allows display. Every file request is checked; a guessed or copied file address returns 404.
- Each element of an oral history (recording, transcript, translation, download) is shown only with its own recorded consent, and nothing is shown during an embargo.
- Corrections can only target public records; the error for a private record is identical to the error for a nonexistent one.
- Contributors can only read, edit, submit or withdraw their own submissions (others' return 404).
- Every role change, account action, publication, correction, access, rights and consent change, merge, import, research-access view, export, backup and family grant is written to the append-only audit log with actor, time and network address. Moderator actions are in the moderation log.
