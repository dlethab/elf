# MASTER DEVELOPMENT SPECIFICATION
# ELF Digital Historical Archive & Community Preservation Platform

**Project type:** Full-stack historical archive, research platform, genealogy and family-history system, interactive geographic history platform, and moderated community website  
**Primary subject:** Eritrean Liberation Front (ELF) and its role in Eritrea’s struggle for independence  
**Primary goal:** Preserve, organize, connect, and make accessible the historical experiences, biographies, families, places, events, documents, photographs, and oral histories associated with Eritrea’s independence struggle.  
**Primary audience:** Former ELF members, veterans, families, descendants, historians, researchers, journalists, students, Eritrean communities, and future generations.  
**Primary language at launch:** English, with the architecture prepared for Tigrinya, Arabic, and additional languages.  
**Product standard:** Production-minded, secure, accessible, responsive, maintainable, historically responsible, and fully functional.

---

# 1. YOUR ROLE AND OVERALL OBJECTIVE

Act as a senior full-stack software engineer, software architect, product designer, database designer, UX researcher, security engineer, and digital-archive specialist.

Your task is to design and develop a complete website for the Eritrean Liberation Front (ELF) that functions as a permanent, searchable, interconnected digital historical archive.

This project is not simply a memorial website, blog, forum, or collection of static pages. It is a structured historical knowledge platform in which every person, family, place, event, document, photograph, oral history, and source can connect to other relevant records.

For example:

- A person has a biography, aliases, family connections, hometown, documented roles, associated events, photographs, interviews, and citations.
- A family has a dedicated page containing its history, family tree, members, places of origin, historical contributions, photographs, documents, and oral histories.
- A town has a historical page containing its geographic context, historical names, related people, events, families, and archival material.
- A historical event connects to its date or date range, location, participants, organizations, sources, and surviving documentation.
- A document can be connected to the people, families, events, and places it references.
- A source can support claims across multiple records without having to be entered repeatedly.
- A visitor can navigate from a town to an event, from that event to a person, from that person to a family, and from the family to photographs or testimony.

All of these relationships must use shared underlying records. Do not create disconnected pages with duplicate information.

**The central product principle is that the archive should become more useful as more reliable information is added.** Each new record should enrich the existing historical network.

Build the platform in a coherent, modular way. It must be possible to add features, contributors, records, languages, and content over time without rebuilding the entire system.

Do not stop after producing a plan, design mockup, static front end, or nonfunctional prototype. First inspect the development environment, propose an appropriate architecture, and then implement and test the application.

If requirements are unclear, make sensible, conservative decisions and document them. Ask questions only when a decision genuinely blocks implementation.

---

# 2. MISSION, SCOPE, AND EDITORIAL POSITION

## 2.1 Mission

Preserve the history and human experiences associated with the ELF and Eritrea’s independence struggle in a form that is accessible, searchable, connected, and useful for future generations.

The platform should help preserve:

- Individual biographies and personal histories.
- Family histories and intergenerational memories.
- The experiences and contributions of people who participated in the struggle.
- Historical towns, villages, regions, and places of significance.
- Major and local historical events, campaigns, battles, and turning points.
- Photographs, documents, letters, publications, recordings, and maps.
- Firsthand testimony and oral histories.
- Historical research, citations, corrections, and differing accounts.
- Community knowledge that might otherwise disappear as eyewitnesses age and family archives are lost.

## 2.2 Historical scope

Keep the ELF at the center of the platform while providing contextual information about the wider Eritrean independence struggle.

Do not imply that everyone who participated in Eritrea’s independence struggle belonged to the ELF. People associated with other organizations, civilian communities, political movements, or historical events may be included when relevant, but their affiliations must be represented accurately and specifically.

Allow historical affiliations to be time-dependent. A person may have been associated with different organizations at different times. The system must support multiple affiliations, date ranges, uncertain dates, and conflicting accounts.

Do not reduce a person's life to a military or political role. Profiles should be able to include family, community, education, occupation, migration, personal recollections, and other historically relevant context.

## 2.3 Historical integrity

Never fabricate historical facts, dates, names, quotations, battles, affiliations, family relationships, locations, or biographical details.

When information is unknown, display “Unknown,” “Not yet documented,” or an appropriate equivalent rather than filling gaps with guesses.

Clearly distinguish:

- Verified or well-supported historical information.
- Information supported by a cited source but not independently corroborated.
- Firsthand testimony.
- Family recollection.
- Oral tradition.
- Research hypotheses.
- Conflicting historical accounts.
- Unverified community submissions.
- Information awaiting editorial review.

A source does not automatically make every statement in a record true. Editors must be able to assess which source supports which claim.

Preserve meaningful disagreements between accounts rather than silently choosing one version. Where appropriate, display a respectful explanation that historical accounts differ.

---

# 3. USERS AND PERMISSIONS

The website must support public access, registered contributors, family representatives, historical editors, moderators, and administrators.

Use role-based access control enforced on the server. Hiding buttons in the user interface is not sufficient security.

## 3.1 Public visitor

A visitor should be able to browse the public archive without creating an account.

Public visitors can:

- View published biographies, family records, places, events, and archive items.
- Explore the historical map and timeline.
- Search and filter public records.
- Read public oral-history transcripts.
- View publicly authorized photographs and documents.
- Browse approved public forum discussions.
- Follow links between related historical records.
- View citations, available provenance, and revision information.
- Submit a correction request or contact the archive where permitted.

Visitors must not be able to access private records, restricted media, moderation tools, drafts, or unpublished submissions.

## 3.2 Registered contributor

Registered contributors can:

- Maintain their account profile.
- Propose new historical profiles.
- Submit biographies, family information, historical events, and place records.
- Upload photographs and documents when authorized.
- Suggest corrections to published records.
- Submit citations, bibliographic references, and supporting evidence.
- Propose identifications of people or places in photographs.
- Submit oral-history materials or request an interview.
- Participate in the community forum.
- Track their submissions and review feedback.
- Withdraw a pending submission where appropriate.

Submitting content must not publish it automatically.

Contributors should be able to see the status of their submissions without seeing confidential editorial notes or other users' private information.

## 3.3 Family representative

A family representative is a contributor granted permission to help maintain a particular family record.

They may:

- Suggest edits to the family narrative.
- Propose additions to the family tree.
- Suggest relationships between family members.
- Submit family photographs, documents, and oral histories.
- Help identify people and locations.
- Propose corrections to associated individual profiles.
- Manage family-specific draft material they are authorized to manage.

They must not automatically gain unrestricted access to all information about living relatives or the ability to publish changes to shared historical records.

Changes affecting public records should go through the editorial review process. A family representative cannot delete or rewrite another person's historical profile without authorization.

Support multiple representatives for one family, clearly defined scopes of access, and the ability to revoke representative permissions.

## 3.4 Historical editor

Historical editors can:

- Review submitted records and proposed corrections.
- Request additional evidence or clarification.
- Approve, reject, or return submissions for revision.
- Edit and publish approved records.
- Link records to existing people, families, places, events, and sources.
- Merge duplicate profiles while preserving identifiers and relationships.
- Resolve conflicting spellings, aliases, and transliterations.
- Manage citations and source quality.
- Flag disputed claims and document editorial decisions.
- Correct relationships, dates, and geographic information.
- View relevant record histories and compare revisions.

Editors should not be able to permanently erase the historical audit trail.

## 3.5 Moderator

Moderators can:

- Review forum reports.
- Remove spam, harassment, and content that violates community rules.
- Hide or lock discussions when necessary.
- Issue warnings and apply temporary restrictions according to policy.
- Escalate serious issues to administrators.
- Maintain a record of moderation actions.

Moderators should not automatically receive access to private archival submissions or unrelated personal information.

## 3.6 Administrator

Administrators can manage:

- User accounts and roles.
- Editorial and moderation permissions.
- Site-wide settings.
- Archive configuration.
- Content workflows.
- Place and event taxonomies.
- Language settings.
- Media access and retention settings.
- System health and background jobs.
- Backup and restoration procedures.
- Data exports and migration tools.

Sensitive administrative actions must be logged.

## 3.7 Role design requirements

Use least-privilege permissions. A user should receive only the access needed for their role.

Provide a permission matrix in the project documentation. Test role boundaries on the server, including attempts to access protected records through direct API requests.

Support account deactivation, secure account recovery, and appropriate retention or anonymization of account data when an account is removed.

---

# 4. INFORMATION ARCHITECTURE AND NAVIGATION

Create a consistent, intuitive global navigation system.

Recommended primary navigation:

1. Home
2. People
3. Historical Map
4. Timeline
5. Families
6. Digital Archive
7. Oral Histories
8. Community
9. About the Archive

Provide a prominent global search field.

The header should support responsive desktop, tablet, and mobile layouts. On smaller screens, use an accessible compact navigation menu.

The footer should include:

- About the project.
- Historical and editorial standards.
- How to contribute.
- How to submit corrections.
- Privacy policy.
- Terms of use.
- Copyright and permissions.
- Accessibility statement.
- Contact information.
- Data and licensing policy, where applicable.

Use breadcrumbs on individual records so visitors can understand where they are and return to relevant parent sections.

Every important public record must have a stable, shareable URL.

Example URL patterns:

- `/people/person-slug`
- `/families/family-slug`
- `/places/place-slug`
- `/events/event-slug`
- `/archive/item-slug`
- `/oral-histories/interview-slug`
- `/sources/source-slug`
- `/community/topics/topic-slug`

Use stable internal identifiers independent of display names and slugs. If a name or slug changes, existing relationships and permanent identifiers must remain intact. Provide redirects where appropriate.

---

# 5. HOMEPAGE

Design the homepage as the main entry point into the historical archive.

It should explain the project's purpose and invite visitors to explore or contribute.

Recommended sections:

## 5.1 Hero section

- Clear project title and mission statement.
- Strong, dignified archival visual.
- Primary action: Explore the Archive.
- Secondary action: Explore the Historical Map.
- A visible contribution invitation.

Use authentic photographs only when their origin, rights, and context are appropriately established. Do not use invented images that appear to document real historical events.

## 5.2 Explore by category

Prominent links or cards for:

- People.
- Families.
- Places.
- Historical events.
- Photographs and documents.
- Oral histories.
- Timeline.
- Community forum.

## 5.3 Historical map preview

Show a useful preview of the interactive map with an option to open the full experience.

## 5.4 Timeline preview

Show a small number of editorially approved historical milestones, with links to the full timeline.

Do not fabricate historical milestones for demonstration purposes.

## 5.5 Featured archival collections

Display curated collections such as:

- Family photographs.
- Personal correspondence.
- Historical publications.
- Oral histories.
- Photographic collections.
- Documents associated with a specific period or place.

Only show public and authorized materials.

## 5.6 Featured stories

Support editorially curated biographies, family histories, and place histories.

## 5.7 Contribution call to action

Invite users to preserve a photograph, submit a family history, share a firsthand account, identify people in an image, or correct an existing record.

Explain that submissions undergo review before public publication.

## 5.8 Trust and transparency

Link to the archive's source standards, privacy principles, and correction process.

Avoid inventing statistics, member counts, collection sizes, or historical achievements to make the project appear established.

---

# 6. HISTORICAL PEOPLE AND BIOGRAPHICAL PROFILES

People are one of the central entities in the database.

Each person must have one canonical record, even when that person appears in several families, events, places, documents, or relationship networks.

## 6.1 Individual profile fields

Support the following fields where applicable:

- Permanent internal identifier.
- Preferred display name.
- Full name.
- Original-language name or spelling.
- Alternative spellings.
- Transliteration variants.
- Aliases, noms de guerre, and nicknames.
- Birth date or approximate birth period.
- Birthplace.
- Death date or approximate death period, if applicable and supported.
- Place of death, if known.
- Living/deceased/unknown status, where appropriate.
- Biography and life history.
- Occupation or civilian role.
- Historical roles and contributions.
- Organizational affiliations.
- Affiliation date ranges.
- Hometown and places of residence.
- Education and professional background.
- Relevant life events.
- Family relationships.
- Associated people.
- Associated families.
- Associated historical events.
- Photographs and documents.
- Oral-history recordings or transcripts.
- Sources and citations.
- Research notes, with access restrictions where necessary.
- Record status and publication status.
- Creation and update timestamps.
- Revision history.
- Contributor and editorial attribution.

Every field should be optional unless it is essential for technical integrity.

Unknown dates and locations must be represented explicitly. Do not substitute an arbitrary date, zero coordinate, or guessed hometown.

## 6.2 Profile presentation

The public profile should have:

- Name and alternative names.
- Portrait or authorized representative image.
- A concise biography summary.
- A detailed historical narrative.
- Key facts, only where known.
- Historical affiliations and roles.
- Family connections.
- Associated events.
- Associated places.
- Photographs and documents.
- Oral histories.
- Citations and source list.
- A related-people section.
- A revision or last-reviewed indicator.
- A correction suggestion link.

Avoid displaying empty fields as a long list of missing information. Use progressive disclosure and clear sections.

## 6.3 Affiliation and contribution history

Represent organizational affiliations as separate linked records where practical.

Each affiliation or role can include:

- Organization.
- Role or relationship.
- Start date or approximate date.
- End date or approximate date.
- Relevant location.
- Supporting sources.
- Confidence or evidence status.
- Editorial notes.

A person may have several affiliations or roles. Do not force the entire history into a single organization field.

## 6.4 Duplicate handling

The system must detect possible duplicate people using:

- Name similarity.
- Alternative spellings.
- Transliteration variants.
- Aliases.
- Matching dates.
- Matching family connections.
- Matching source references.

Treat this as a review aid, not automatic proof of identity.

When records are merged:

- Select a canonical record.
- Preserve the canonical identifier.
- Keep redirects from retired public URLs where applicable.
- Preserve source references.
- Preserve family and event links.
- Preserve revision history.
- Record who performed the merge and why.

Do not automatically merge people solely because they have similar names.

---

# 7. FAMILY RECORDS AND GENEALOGICAL HISTORY

Family history is a core feature, not a minor addition to biographies.

Families must have dedicated public pages and a structured relationship system.

## 7.1 Family record

Each family record should support:

- Permanent identifier.
- Family display name.
- Alternative family names and spellings.
- Original-language names.
- Geographic or regional associations.
- Historical origins, where documented.
- Family narrative.
- Generational history.
- Important historical experiences.
- Associated towns and regions.
- Associated people.
- Family tree.
- Family photographs.
- Letters and documents.
- Oral histories.
- Related events.
- Citations and sources.
- Family representatives.
- Editorial status.
- Privacy and visibility settings.
- Revision history.

A family record can exist even if not every member was involved in the independence struggle.

However, claims about an individual's participation or historical contribution must be supported by evidence.

## 7.2 Interactive family tree

Build an interactive family-tree viewer that supports:

- Multiple generations.
- Parents and children.
- Siblings.
- Spouses and partners, when appropriate and authorized.
- Adoption and stepfamily relationships, if contributors choose to record them.
- Unknown parents.
- Incomplete branches.
- Multiple spouses or partners where historically appropriate.
- Relationships with uncertain or disputed evidence.
- Approximate birth and death dates.
- Clickable person nodes.
- Navigation to canonical person profiles.
- Zoom, pan, and fit-to-screen controls.
- Mobile-friendly viewing.
- A list or table alternative for accessibility and smaller screens.

Do not assume that every relationship is biologically based.

The data model must support relationship types instead of hardcoding a single family structure.

Relationships should be stored as explicit records with evidence and optional dates. Avoid duplicating the same person's biography inside each family tree.

One person may belong to multiple family groupings, and different family records may refer to the same canonical person.

## 7.3 Family relationship data

For each relationship, support:

- Person A.
- Person B.
- Relationship type.
- Start and end dates where relevant.
- Whether the relationship is current, historical, uncertain, or disputed.
- Source references.
- Explanation or notes.
- Submission and review status.
- Visibility restrictions when necessary.

Do not publish sensitive family information about living people without appropriate authorization.

## 7.4 Family network explorer

In addition to the genealogical tree, provide a broader network view.

The network explorer may show documented connections through:

- Family relationships.
- Shared historical events.
- Shared organizations.
- Shared places.
- Shared archival documents.
- Documented collaboration.
- Other explicitly described historical connections.

Keep these relationship categories visually distinct.

Do not infer that two people knew each other simply because they lived in the same town or belonged to the same organization.

Every displayed connection should have an explanation, an underlying record, or a source where appropriate.

## 7.5 Family privacy

Support public, restricted, and unpublished family records.

For living people, allow fields or entire records to be restricted where appropriate.

Do not make the existence of a private family record, private interview, or confidential relationship visible through public search results, APIs, map data, page metadata, or related-record recommendations.

---

# 8. INTERACTIVE HISTORICAL MAP OF ERITREA

The map is a major feature and must be implemented as a genuine interactive geographic interface.

Use a maintainable mapping library and an appropriate geographic data source. Explain the choice before implementation.

Do not invent geographic coordinates, historical boundaries, or precise battle locations. Use reliable data, clearly documented estimates, or explicitly marked approximate locations.

## 8.1 Map interface

The map should support:

- Pan and zoom.
- Search for towns, villages, regions, and historical place names.
- Markers for relevant places and events.
- Different marker styles for place types and event types.
- Clustering when markers overlap.
- A legend.
- Map filters.
- Time-period filters.
- Event-type filters.
- Associated-person filters where practical.
- Place detail previews.
- Links to full place pages.
- A list-based alternative to map interaction.
- Responsive desktop and mobile layouts.
- Clear loading, empty, and error states.

Where mapping services require keys, billing, or specific licensing, document these requirements and provide environment configuration instructions.

Do not make the entire website unusable when a map tile provider is unavailable. Provide a graceful fallback to a place list or textual search.

## 8.2 Place categories

Support categories such as:

- Town or city.
- Village.
- Region.
- Historical settlement.
- Geographic feature.
- Refugee or displacement-related location.
- Training or organizational location.
- Historical site.
- Conflict or battle location.
- Memorial or commemorative site.
- Other historically relevant place.

Categories should be configurable.

## 8.3 Place records

Every place should have a dedicated automatically generated historical page.

Fields should include:

- Permanent identifier.
- Primary display name.
- Alternative spellings.
- Historical names.
- Original-language names.
- Transliteration variants.
- Place type.
- Country and regional context.
- Geographic coordinates, if known.
- Coordinate precision.
- Whether the location is approximate.
- Historical or modern administrative region, when known.
- Historical overview.
- Relevant date ranges.
- Sources.
- Associated people.
- Associated families.
- Associated events.
- Photographs and documents.
- Related places.
- Editorial status and revision history.

Support places whose boundaries, names, or administrative classifications have changed over time.

## 8.4 Place pages

A public place page should display:

1. Name and location context.
2. Short historical overview.
3. Map or location visualization.
4. Historical names and alternative spellings.
5. Events associated with the place.
6. People associated with the place.
7. Families associated with the place.
8. Photographs and archival materials.
9. Related places.
10. Relevant timeline entries.
11. Sources and citations.
12. A way to suggest corrections.

The page should be generated from the same underlying records used by the map, timeline, and other archive sections.

## 8.5 Historical geographic accuracy

Historical geography can be uncertain.

Support:

- Approximate points.
- Coordinate precision.
- Historical names.
- Former administrative divisions.
- Location date ranges.
- Uncertain locations.
- Alternative proposed locations.
- Notes explaining uncertainty.

Never display an estimated battle location as a definitively established exact point.

If historical boundary datasets are unavailable or unlicensed, do not fabricate them. Clearly distinguish modern geography from historical geography.

## 8.6 Map and timeline integration

Allow users to filter the map by historical period.

Selecting an event should show its date or date range, location, description, associated people, and sources.

Selecting a person should reveal their relevant documented places and events where appropriate.

Selecting a town should provide access to its historical timeline and related records.

All links must lead to real records rather than decorative popups.

---

# 9. HISTORICAL TIMELINE AND EVENTS

Create a dedicated interactive timeline of the ELF and the broader Eritrean independence struggle.

The timeline must use actual event records in the database.

## 9.1 Event record fields

Support:

- Permanent identifier.
- Event title.
- Alternative titles.
- Event type.
- Summary.
- Detailed description.
- Start date.
- End date.
- Approximate date or date range.
- Date precision.
- Location or multiple locations.
- Associated people.
- Associated families where historically relevant.
- Organizations and affiliations.
- Associated documents and photographs.
- Sources.
- Conflicting accounts.
- Editorial status.
- Revision history.

Do not require a precise day or month for events whose dates are uncertain.

## 9.2 Event categories

Use configurable categories such as:

- Battle or armed conflict.
- Political development.
- Organizational development.
- Meeting or conference.
- Public statement or publication.
- Personal life event.
- Displacement or migration.
- Humanitarian event.
- Community event.
- Commemoration.
- Other historical event.

## 9.3 Timeline interface

Provide:

- Chronological ordering.
- Zoomable or segmented time periods.
- Year, decade, and date-range navigation.
- Filters by event type, place, organization, and associated people.
- Search within events.
- Links to full event pages.
- Links to the historical map.
- Associated people and archival media.
- A mobile-friendly chronological list.
- Clear handling of uncertain dates.

Events with uncertain dates must be represented honestly rather than assigned false precision.

## 9.4 Event pages

Each event page should include its summary, detailed historical account, date confidence, geographic context, participants, related organizations, supporting archival materials, sources, and related events.

Where credible accounts conflict, present the differing accounts with attribution.

---

# 10. DIGITAL ARCHIVE AND MEDIA MANAGEMENT

The archive must store and organize more than ordinary web images.

Support archival material such as:

- Photographs.
- Scanned documents.
- Letters and correspondence.
- Books and publications.
- Pamphlets and newsletters.
- Newspaper clippings.
- Speeches.
- Audio recordings.
- Video interviews.
- Oral-history recordings.
- Transcripts.
- Historical maps.
- Posters.
- Certificates and personal papers.
- Other historically relevant materials.

## 10.1 Archive item data model

Every item should support:

- Permanent identifier.
- Title.
- Alternative title.
- Item type.
- Description.
- Date created, if known.
- Approximate date or date range.
- Original creator or photographer, if known.
- Donor or contributor.
- Current custodian, if appropriate to publish.
- Source or collection.
- Provenance and chain-of-custody notes where available.
- Original language.
- Translation or transcript.
- Geographic association.
- Associated people.
- Associated families.
- Associated events.
- Associated places.
- Related archive items.
- Rights holder, if known.
- Copyright or licensing status.
- Permission status.
- Access level.
- File metadata.
- Review status.
- Source citations.
- Revision history.

Distinguish the person who uploaded an item from the person who created it and the person who owns its copyright.

## 10.2 File handling

Implement secure file upload and storage.

Requirements:

- Validate file type using actual content where practical, not only the filename.
- Restrict file size and accepted formats.
- Generate safe storage filenames.
- Store files outside executable application paths.
- Prevent uploaded files from being executed.
- Scan files for malware where infrastructure supports it.
- Protect private and restricted files from public URL access.
- Use signed or otherwise access-controlled URLs for restricted media.
- Create thumbnails and previews when appropriate.
- Preserve original files where authorized.
- Store metadata separately from file binaries.
- Support retryable processing for large files.
- Show upload progress and meaningful errors.
- Log failures without exposing secrets.

Consider object storage compatible with S3 or another suitable service rather than storing every large file directly in the application database.

Document local-development storage and production storage separately.

## 10.3 Archival preservation

Preserve originals where rights and permissions allow.

Where practical, support:

- Original files.
- Access derivatives.
- Thumbnail images.
- Checksums for integrity verification.
- File format and size metadata.
- Upload timestamps.
- Digitization information.
- Metadata exports.
- Preservation and retention notes.

Never silently replace an original archival file with an edited image.

If an image is cropped, restored, annotated, or otherwise modified, preserve the original when permitted and identify the derivative as edited.

## 10.4 Rights and access control

Each item must support explicit rights and permission states, such as:

- Public domain.
- Copyrighted, permission granted.
- Copyrighted, permission pending.
- Licensed for specified uses.
- Restricted to authorized users.
- Private or embargoed.
- Rights unknown.
- Not approved for public display.

Do not assume that a contributor owns the copyright to everything they upload.

The platform must allow administrators to restrict, correct, or remove public access to material when required, while preserving an appropriate audit record.

## 10.5 Collections

Allow editors to group archive items into curated collections.

A collection may represent:

- A family collection.
- A donated photographic collection.
- A particular town.
- A historical period.
- A documented event.
- A person's papers.
- An interview series.
- A particular publication or organization.

Collections should have their own descriptions, sources, rights information, and linked items.

---

# 11. ORAL HISTORIES AND INTERVIEWS

Oral history is an essential part of the project.

Create a dedicated section for audio interviews, video interviews, transcripts, translations, and interview metadata.

## 11.1 Interview record

Support:

- Interview title.
- Interview identifier.
- Interviewee.
- Interviewer.
- Recording date.
- Recording location, if appropriate.
- Language.
- Translation language.
- Transcript.
- Audio or video file.
- Summary.
- Topics and keywords.
- Associated people.
- Associated families.
- Associated places.
- Associated events.
- Consent status.
- Public access permissions.
- Transcript publication permissions.
- Translation permissions.
- Embargo date, if applicable.
- Redaction notes.
- Source and provenance information.
- Editorial status.

## 11.2 Consent and ethical handling

Build a workflow for recording and tracking consent.

Consent must be specific enough to distinguish permission to:

- Record an interview.
- Store the recording.
- Publish the recording.
- Publish a transcript.
- Publish a translation.
- Use selected excerpts.
- Make material available for research.
- Allow downloads or reuse, if applicable.

Do not publish private interviews simply because an account has uploaded them.

Allow authorized editors to restrict sensitive sections, redact personal details, or manage an embargo according to the documented consent terms.

## 11.3 Interview presentation

Provide:

- Audio or video player.
- Transcript alongside the media where appropriate.
- Searchable transcript.
- Timestamps or chapter markers where available.
- Interview summary.
- Interviewee profile link.
- Related family, place, event, and archive links.
- Language and translation controls.
- Citation and source information.
- Clear permission and reuse information.

Do not fabricate transcripts or attribute invented quotations to real people.

Automated transcription, if introduced, must be labeled as a draft until reviewed. Preserve the distinction between a verbatim transcript, an edited transcript, a translation, and a summary.

---

# 12. GLOBAL SEARCH AND DISCOVERY

Search must work across the entire public archive.

It is one of the most important functions of the website.

## 12.1 Searchable entities

Search:

- People.
- Aliases and alternate names.
- Families.
- Places.
- Historical events.
- Archive items.
- Collections.
- Oral histories.
- Sources.
- Public forum topics, where appropriate.

## 12.2 Search behavior

Support:

- Partial matches.
- Case-insensitive matching.
- Alternative spellings.
- Transliteration variants.
- Original-language names.
- Historical place names.
- Alias matching.
- Filtering by record type.
- Filtering by historical period.
- Filtering by place.
- Filtering by archive category.
- Sorting by relevance or date where applicable.
- Pagination or incremental loading.
- Empty-result guidance.
- Useful spelling suggestions where feasible.

Design the search index so that the same record is not returned as several separate people simply because it has several aliases.

## 12.3 Search result presentation

Each result should show:

- Title or primary name.
- Record type.
- Short relevant summary.
- Available thumbnail where appropriate.
- Relevant dates or geographic context.
- Why the result matches, when useful.
- Link to the canonical record.

Never expose unpublished submissions, private living-person records, confidential research notes, or restricted media through search.

## 12.4 Related-record discovery

Provide related records based on explicit relationships and documented metadata.

For example:

- People connected to the same documented event.
- Documents mentioning a person.
- Events linked to a place.
- Family members with published profiles.
- Photographs associated with a family collection.

Clearly distinguish directly documented relationships from broad topical similarity.

Do not present algorithmic suggestions as proof of historical association.

---

# 13. COMMUNITY FORUM

Create a real, database-backed discussion forum.

The forum should support respectful historical discussion and community knowledge preservation.

## 13.1 Forum structure

Support:

- Categories.
- Topics or threads.
- Posts and replies.
- User profiles.
- Search.
- Pagination.
- Editing of a user's own posts under defined rules.
- Reporting inappropriate content.
- Moderator review.
- Locking and archiving discussions.
- Pinned announcements.
- Basic notification preferences.

Suggested categories:

- Family histories and memories.
- Historical events.
- Photo identification.
- Hometown and regional history.
- Research questions.
- Personal recollections.
- Archival discoveries.
- General community discussion.

## 13.2 Forum and archive separation

Forum discussions are community conversations, not automatically authoritative historical records.

Users may propose that a forum discussion contribute to the archive, but conversion into an official record requires editorial review, source assessment, and appropriate permissions.

Where a forum discussion informs a historical record, editors should be able to reference it internally without exposing private information or treating uncorroborated claims as established facts.

## 13.3 Moderation and abuse prevention

Implement:

- Reporting tools.
- Rate limiting.
- Spam prevention.
- Input validation.
- Protection against malicious links and scripts.
- Moderation logs.
- Account restrictions.
- Clear community rules.
- Procedures for threats, harassment, and privacy violations.

Do not allow users to post other people's private information without authorization.

Support respectful handling of disagreement about history, identity, political affiliation, and contested events.

---

# 14. USER ACCOUNTS AND ACCOUNT SETTINGS

Implement real authentication and session management using a secure, maintained solution appropriate to the chosen technology stack.

Do not build an insecure custom password system.

## 14.1 Authentication

Support:

- Account registration.
- Login and logout.
- Email verification where appropriate.
- Secure password reset.
- Session expiration and revocation.
- Protection against brute-force attempts.
- Secure password storage through a trusted authentication provider or framework.
- Optional multifactor authentication if supported by the selected solution.
- Account deactivation.
- Role assignment and revocation.

If OAuth or social login is implemented, make it optional and document its configuration.

Never expose password hashes, session tokens, reset tokens, or secret environment variables.

## 14.2 User profile

Allow users to manage appropriate profile fields, such as:

- Display name.
- Username.
- Optional profile photograph.
- Short biography.
- Languages.
- Research interests.
- Contributor attribution preferences.
- Notification preferences.

Do not require users to publicly disclose their real name, precise location, political history, or family relationships.

## 14.3 User dashboard

Create a dashboard showing:

- Submitted records.
- Pending submissions.
- Requested revisions.
- Approved contributions.
- Rejected submissions with appropriate explanations.
- Drafts.
- Uploads.
- Correction requests.
- Forum activity.
- Family records the user is authorized to help maintain.
- Account settings.

Do not display confidential internal editorial notes unless the user has the appropriate role and authorization.

---

# 15. CONTRIBUTION AND EDITORIAL REVIEW WORKFLOW

Every public contribution must be reviewed before publication.

Build a clear workflow rather than a simple publish button.

## 15.1 Submission lifecycle

Use a controlled lifecycle, for example:

1. Draft.
2. Submitted.
3. Under review.
4. Needs revision.
5. Approved.
6. Published.
7. Rejected.
8. Withdrawn.
9. Archived or superseded.

The exact implementation may use separate publication and review statuses if that provides a clearer data model.

## 15.2 Submission content

A submission should support:

- Proposed record type.
- Proposed record data.
- Supporting sources.
- Uploaded files.
- Source and rights information.
- Contributor explanation.
- Relationship to existing records.
- Suggested edits.
- Relevant consent declarations.
- Submission timestamp.

## 15.3 Editorial queue

Editors need an administrative interface showing:

- New submissions.
- Pending corrections.
- Items awaiting rights clarification.
- Items awaiting consent confirmation.
- Possible duplicates.
- Incomplete citations.
- Conflicting dates or names.
- Items needing additional research.
- Recently approved and rejected submissions.

## 15.4 Review tools

Editors should be able to:

- Compare submitted content with the current record.
- See the submitter's proposed changes.
- Inspect source metadata.
- Open related records.
- Add or correct citations.
- Ask the contributor for clarification.
- Approve, reject, or return the submission.
- Record the reason for the decision.
- Publish approved changes.
- Preserve the revision history.

## 15.5 Publication guarantees

A submission must not become public until all required approvals are complete.

This rule must be enforced by backend authorization and publication logic, not just by the user interface.

If an approved record contains restricted media, the record and the media must each respect their own access permissions.

---

# 16. SOURCES, CITATIONS, AND HISTORICAL EVIDENCE

Build source management into the core database from the beginning.

Do not rely solely on a bibliography field containing unstructured text.

## 16.1 Source types

Support sources such as:

- Books.
- Academic publications.
- Newspaper articles.
- Official records.
- Personal letters.
- Photographs with provenance.
- Oral histories.
- Interviews.
- Archival collections.
- Family documents.
- Previously published histories.
- Organizational publications.
- Maps.
- Web resources.
- Other primary or secondary sources.

## 16.2 Source metadata

A source may include:

- Title.
- Creator or author.
- Publication or creation date.
- Publisher.
- Collection or archive.
- Repository.
- Identifier or catalog number.
- Page number or page range.
- URL where appropriate.
- Access date for online sources.
- Language.
- Source type.
- Provenance.
- Rights information.
- Notes about reliability or limitations.

## 16.3 Claim-level citations

Where practical, allow sources to support specific claims or sections of a record.

A citation relationship should be able to reference:

- The source.
- The associated record.
- The relevant claim or passage.
- Page number, timestamp, or section.
- A short explanation.
- Evidence status.
- Editorial notes.

For example, a birth year, organizational affiliation, and participation in a particular event may require different sources.

Do not imply that one citation necessarily supports every statement on a biography page.

## 16.4 Revision history

For published records, maintain a revision history that records:

- Previous and current versions.
- Editor or contributor responsible.
- Date of change.
- Reason for change where provided.
- Changes to important facts.
- Publication status changes.

Where appropriate, expose a public revision summary without revealing private user information or confidential moderation notes.

## 16.5 Conflicting accounts

Support multiple claims or accounts when historical sources disagree.

Each account should be attributable to a source or witness where possible.

Editors should be able to explain the disagreement, record the basis for each version, and indicate whether further research is needed.

Do not overwrite a disputed historical account without preserving the prior record and its supporting material.

---

# 17. MULTILINGUAL SUPPORT AND HISTORICAL NAMING

Build the system to support multilingual content from the beginning, even if the initial interface is English.

Planned languages include:

- English.
- Tigrinya.
- Arabic.
- Additional languages later if needed.

Do not assume that all names, place names, and documents will be written in Latin script.

## 17.1 Language-aware records

Support:

- Original-language names.
- Alternate spellings.
- Transliteration variants.
- Language tags.
- Localized page titles.
- Translated descriptions and biographies.
- Translated interface text.
- Translated oral-history transcripts.
- Language-specific metadata.

Preserve original text when it is available. A translation should not silently replace the original.

## 17.2 Search and rendering

Ensure the database and interface support Unicode properly.

Plan for right-to-left layout and text direction for Arabic. Do not assume that right-to-left support can be added simply by changing labels.

Use proper language tags and accessible language-switching controls.

Do not machine-translate historical testimony and present it as a verified human translation. Clearly identify drafts and unreviewed translations.

## 17.3 Name normalization

Store names as entered and maintain separate normalized search forms when needed.

Never destroy original spelling during normalization.

Names with different transliterations may refer to the same person, but this must be established through evidence and editorial review.

---

# 18. ADMINISTRATION AND ARCHIVE MANAGEMENT

Build a practical administrative dashboard for day-to-day operation.

The platform must be manageable by authorized staff who are not software engineers.

## 18.1 Dashboard overview

Display useful operational information, such as:

- Pending submissions.
- Pending corrections.
- Unreviewed media.
- Incomplete records.
- Records missing citations.
- Potential duplicate records.
- Items with unresolved rights or consent.
- Recently changed records.
- Forum reports.
- Broken internal links.
- Failed media-processing jobs.
- Backup or system-health status where available.

Do not display fabricated counts.

## 18.2 Record management

Provide administrative tools for:

- Creating and editing records.
- Linking existing entities.
- Reviewing relationships.
- Merging duplicates.
- Managing categories and taxonomies.
- Managing sources.
- Restricting or unpublishing records.
- Reviewing revision history.
- Managing media rights.
- Exporting records.
- Viewing audit logs.

## 18.3 Data quality tools

Flag records that may need attention, including:

- Missing citations.
- Unclear dates.
- Missing descriptions.
- Unresolved place associations.
- Possible duplicate people.
- Conflicting aliases.
- Broken relationships.
- Media without rights information.
- Oral histories without complete consent records.
- Records that refer to deleted or merged entities.
- Missing translations where required.

Warnings should help editors investigate. They should not automatically delete or rewrite historical content.

---

# 19. RECOMMENDED DATA MODEL

Design a normalized relational database with explicit relationships.

Use database migrations, foreign keys, appropriate unique constraints, indexes, and transactions. Explain the schema before implementation.

The following entities define the minimum conceptual model. You may refine the table names and structure, but do not omit these capabilities.

## 19.1 Core entities

### People
Canonical identity and biographical data.

### PersonNames
Multiple names, aliases, original-language forms, transliterations, and spelling variants.

### Families
Family identity, narrative, geographic associations, and privacy settings.

### FamilyMemberships
Links between people and family records, including optional role and date information.

### Relationships
Explicit person-to-person relationships with type, evidence, date ranges, status, and visibility.

### Organizations
Organizations and movements relevant to the historical archive.

### Affiliations
Links between people and organizations, including roles, time ranges, and supporting sources.

### Places
Geographic entities, including current and historical names.

### PlaceNames
Alternative and historical place names, languages, and transliteration variants.

### Events
Historical events with date precision, descriptions, locations, and evidence.

### EventParticipants
Links between events and people, organizations, or other relevant entities, with roles where known.

### ArchiveItems
Metadata for documents, photographs, publications, recordings, and other archival objects.

### MediaFiles
Storage references, file metadata, derivatives, checksums, access levels, and processing status.

### Collections
Curated groups of archive items.

### CollectionItems
Links between collections and archival objects.

### OralHistories
Interview-specific metadata, participants, consent, transcripts, languages, and recording details.

### Sources
Bibliographic and archival source records.

### Citations
Relationships between sources and records or specific claims.

### Users
Authenticated user identities and account metadata.

### Roles and Permissions
Access control and authorization policies.

### Submissions
Proposed records, edits, uploads, and corrections.

### Revisions
Historical versions and change metadata.

### ForumCategories
Forum structure.

### ForumTopics
Discussion threads.

### ForumPosts
Posts and replies.

### Reports
User reports about forum content or other issues requiring moderation.

### AuditLogs
Sensitive actions and important editorial or administrative changes.

### Translations
Localized content or translated fields where a separate translation model is appropriate.

### Notifications
Submission updates and other user notifications, with preferences and delivery status as needed.

## 19.2 Relationship modeling

Avoid a database where every relationship is represented by arbitrary unvalidated strings.

Use explicit relational records and, where appropriate, constrained relationship types.

For flexible associations between historical entities, consider a typed relationship table or a set of specific join tables.

If using polymorphic relationships, ensure referential integrity is not lost. Explain how invalid references are prevented.

A source should be reusable across multiple records. An event should reference the same canonical people and places that appear elsewhere in the site.

## 19.3 Dates and uncertainty

Use appropriate date types and separate precision or uncertainty metadata.

Support:

- Exact dates.
- Month and year.
- Year only.
- Approximate dates.
- Date ranges.
- Unknown dates.
- Conflicting dates.

Do not encode uncertainty by inventing an exact date.

## 19.4 Database integrity

Use:

- Foreign keys.
- Unique constraints where appropriate.
- Transactions for multi-record operations.
- Indexes for frequently searched fields.
- Full-text or dedicated search indexing as appropriate.
- Safe cascade rules.
- Explicit handling of merges and archival records.

Avoid cascading deletion of historically important records simply because a related user or relationship is removed.

## 19.5 Auditability and deletion

Use soft deletion, archival status, or explicit tombstone records where appropriate for historical records.

Permanent deletion should be restricted to legitimate cases and governed by policy.

Personal data, private content, and user accounts require their own retention and deletion policies. Historical preservation must not be used as a justification to retain private information indefinitely without a lawful and documented reason.

---

# 20. TECHNICAL ARCHITECTURE AND STACK

Choose a maintainable modern stack that fits the development environment and can be operated by a small team.

If the environment does not already dictate a stack, a reasonable default is:

- **Frontend:** Next.js with TypeScript and React.
- **Styling:** Tailwind CSS with reusable accessible components.
- **Database:** PostgreSQL.
- **ORM and migrations:** Prisma, Drizzle, or another suitable maintained solution; choose one and use it consistently.
- **Authentication:** A reputable authentication library or managed provider with secure session handling.
- **File storage:** S3-compatible object storage or a suitable managed equivalent.
- **Mapping:** Leaflet or MapLibre, with a documented, properly licensed geographic data source.
- **Search:** PostgreSQL full-text search initially, with an option to add a dedicated search service if justified.
- **Validation:** Shared schema validation for client and server inputs.
- **Testing:** Unit, integration, and end-to-end tests.
- **Deployment:** A documented deployment process suitable for the selected stack.

These are defaults, not inflexible requirements. If the repository or environment already contains a strong architecture, inspect it and explain any proposed changes before replacing it.

Do not introduce unnecessary microservices or a complex infrastructure that a small archive team cannot maintain.

## 20.1 Architecture principles

Use:

- Clear separation of presentation, business logic, and data access.
- Reusable UI components.
- Typed interfaces and schemas.
- Server-side authorization.
- Validated input at every trust boundary.
- Database migrations.
- Consistent error handling.
- Logging that excludes secrets.
- Centralized permission checks.
- Environment-based configuration.
- Explicit media-access rules.
- Maintainable background processing for large files where needed.

## 20.2 Backend and API

Implement the backend using the chosen framework's secure, maintainable conventions.

Every mutation must validate:

- User identity.
- Role and record-level permissions.
- Input structure.
- Record state.
- Required approvals.
- File access.
- Related entity validity.

Do not rely on frontend validation alone.

Use pagination for large result sets. Prevent unbounded queries and unnecessary repeated database requests.

## 20.3 Environment configuration

Provide an `.env.example` file containing all required variable names and safe placeholder values.

Never commit actual secrets.

Document configuration for:

- Database connection.
- Authentication secrets.
- Email provider, if used.
- Object storage.
- Map tiles or mapping services.
- Optional search services.
- Background jobs.
- Monitoring and error reporting, if used.

## 20.4 Deployment and maintainability

Provide:

- Development setup instructions.
- Production build instructions.
- Database migration commands.
- Seed-data instructions.
- Storage configuration.
- Deployment steps.
- Backup and restoration instructions.
- Upgrade instructions.
- Troubleshooting documentation.

Do not assume a service is configured merely because a code integration exists. Clearly distinguish implemented functionality from features that require external credentials or infrastructure.

---

# 21. VISUAL DESIGN AND USER EXPERIENCE

The visual design should feel like a serious historical archive, research library, or museum—not a generic social network or flashy startup landing page.

## 21.1 Design direction

Use a dignified, restrained, warm, archival visual language.

Suggested direction:

- Warm off-white or paper-inspired backgrounds.
- Deep charcoal or dark neutral text.
- Restrained dark red, muted earth tones, or subtle heritage-inspired accents.
- Clean typography with excellent readability.
- Generous but purposeful whitespace.
- Strong, consistent information hierarchy.
- High-quality photography where authorized.
- Subtle borders and dividers.
- Clear cards and structured metadata.
- Minimal decorative animation.
- Consistent iconography.

The design should feel timeless and credible.

Avoid excessive gradients, neon colors, glassmorphism, unnecessary animation, and decorative UI that competes with the historical content.

Do not use the Eritrean flag or ELF insignia as decoration without considering historical context, accuracy, and appropriate rights. Any historical emblem should be authentic, correctly represented, and used respectfully.

## 21.2 Component system

Create reusable design tokens and components for:

- Typography.
- Color palette.
- Spacing.
- Buttons.
- Links.
- Form controls.
- Cards.
- Record headers.
- Biography layouts.
- Metadata lists.
- Citation blocks.
- Status indicators.
- Tabs.
- Filters.
- Pagination.
- Breadcrumbs.
- Modals and dialogs.
- Tooltips.
- Notifications.
- Loading states.
- Empty states.
- Error states.

Do not create a different visual style for every page.

## 21.3 Responsive design

Support:

- Desktop.
- Tablet.
- Mobile.

Design complex components such as family trees, map interfaces, and timelines to work on touch devices.

Provide alternative list and table presentations when complex visualizations do not work well on smaller screens.

Avoid horizontal overflow, tiny controls, unreadable metadata, and mobile navigation that blocks access to important sections.

## 21.4 Accessibility

Target WCAG 2.2 AA where practical.

Implement:

- Semantic HTML.
- Keyboard navigation.
- Visible focus indicators.
- Appropriate color contrast.
- Screen-reader labels.
- Accessible form errors.
- Proper heading hierarchy.
- Alternative text for meaningful images.
- Captions or transcripts for audiovisual material where available.
- Reduced-motion support.
- Accessible dialogs.
- Focus management.
- Keyboard alternatives to drag-based interactions.
- Nonvisual alternatives to the map and family-tree visualizations.

Do not convey historical evidence status or record privacy through color alone.

## 21.5 Interface states

Every data-driven page should handle:

- Loading.
- Empty results.
- Missing or unpublished records.
- Permission denied.
- Network or server errors.
- Failed uploads.
- Invalid form submissions.
- Unsaved changes.
- Successful saves.
- Pending editorial review.

Use helpful language. Do not expose stack traces, database errors, or internal implementation details to public users.

---

# 22. PRIVACY, SECURITY, AND DATA GOVERNANCE

Security and privacy are essential because the platform may contain family relationships, personal correspondence, interviews, political history, and information about living people.

## 22.1 Application security

Implement protections appropriate to the chosen framework, including:

- Server-side authorization.
- Secure session management.
- Protection against SQL injection.
- Protection against cross-site scripting.
- CSRF protections where applicable.
- Secure file-upload handling.
- Rate limiting.
- Input validation.
- Safe output encoding.
- Secure password-reset workflows.
- Appropriate HTTP security headers.
- Protection against unauthorized object access.
- Dependency maintenance.
- Safe error handling.
- Audit logging for sensitive actions.

## 22.2 Private records

Restrict private information at the database/API boundary, not merely by hiding it in the user interface.

Public endpoints must never expose confidential data in:

- JSON responses.
- Page source.
- HTML metadata.
- Search indexes.
- Sitemap entries.
- Public file URLs.
- Related-record APIs.
- Error messages.
- Cached pages.

Ensure that caches and search indexes respect publication and privacy status.

## 22.3 Living-person protections

Use privacy-by-default for sensitive information about living people.

Support:

- Private or restricted profiles.
- Restricted family relationships.
- Removal or correction requests.
- Consent records where appropriate.
- Limited display of birth dates and personal details.
- Restricted interview materials.
- Unpublished research notes.
- Appropriate handling of minors.
- Protection against exposing precise residential locations.

Do not publish private contact details or exact home addresses.

## 22.4 Data rights

Provide a process for rights holders and contributors to request correction, restriction, or removal of material.

Document how requests are reviewed and how decisions are recorded.

Historical importance alone does not establish permission to publish copyrighted material, private correspondence, or sensitive personal information.

## 22.5 Backups and continuity

Implement a backup strategy appropriate to the selected infrastructure.

Document:

- Database backups.
- Media backups.
- Backup encryption where appropriate.
- Backup retention.
- Independent backup copies.
- Restoration testing.
- Recovery objectives.
- Access control.
- Procedures for migrating away from a hosting provider.

The archive must not depend on one developer's laptop or a single provider account.

Design for long-term institutional continuity, maintainability, and future handover.

---

# 23. PERFORMANCE, SEO, AND DISCOVERABILITY

Historical content should be easy to discover and share.

## 23.1 Performance

Implement:

- Server-rendered or otherwise search-engine-accessible public pages where appropriate.
- Optimized images.
- Responsive image sizes.
- Lazy loading for noncritical media.
- Pagination.
- Efficient database queries.
- Indexed search fields.
- Caching for public content where safe.
- Avoidance of unnecessary client-side JavaScript.
- Reasonable map and timeline loading behavior.

Private and unpublished records must never be cached or indexed as public content.

## 23.2 SEO and sharing

Implement:

- Descriptive page titles.
- Unique meta descriptions where useful.
- Canonical URLs.
- Open Graph metadata.
- Appropriate social preview images.
- XML sitemap for eligible public records.
- Robots directives.
- Structured data where appropriate.
- Redirects after approved slug changes.

Do not expose restricted information through structured metadata or social previews.

## 23.3 Stable identifiers and exportability

Each important historical record should have a permanent identifier.

Support export of structured records and associated metadata so that the archive can be backed up, transferred, or migrated.

Where appropriate, use interoperable archival metadata conventions rather than a proprietary structure that prevents future access.

---

# 24. DATA IMPORT, INITIAL CONTENT, AND SEED DATA

The application should be useful even before a large collection has been entered, but historical accuracy must never be compromised for demonstration purposes.

## 24.1 Initial data strategy

Build a secure import mechanism that can eventually accept structured data from spreadsheets or CSV files.

Support validation, duplicate detection, previewing, error reports, and a review process before imported records become public.

Where feasible, allow batch import of:

- People.
- Families.
- Places.
- Events.
- Sources.
- Archive metadata.
- Relationships.

Do not require users to manually create every record through the interface.

## 24.2 Demonstration data

If seed data is necessary to test the application:

- Clearly mark fictional demonstration records as fictional.
- Do not mix fictional data into the public historical archive.
- Do not fabricate real people's biographies.
- Do not invent historical events or quotes.
- Do not use fictional relationships that could be mistaken for actual family connections.
- Prefer synthetic records with obvious labels for automated tests.
- Keep demonstration data separate from production data.

For real historical records, use only facts supported by reliable sources and preserve source attribution.

If no reliable source is available, leave the record unpopulated or clearly mark the information as awaiting verification.

---

# 25. PHASED DEVELOPMENT PLAN

Implement the website in phases while keeping the overall architecture coherent.

The first release should cover all major user-facing sections, with depth prioritized according to dependencies. It is better to have complete, modest versions of all core sections than several beautiful but disconnected mockups.

## Phase 1 — Foundation

Build:

- Project structure.
- Design system.
- Database schema.
- Database migrations.
- Authentication.
- Role-based authorization.
- User profiles.
- Core entities.
- Record publication statuses.
- Source and citation system.
- Audit and revision history.
- Admin dashboard foundation.
- Basic global navigation.
- Setup documentation.

**Completion condition:** A user can sign in, access the appropriate dashboard, and create or submit records subject to permissions.

## Phase 2 — Historical records and discovery

Build:

- People pages.
- Family pages.
- Place pages.
- Event pages.
- Archive-item pages.
- Relationship system.
- Citation display.
- Global search.
- Filtering and pagination.
- Related-record links.
- Editorial submission queue.

**Completion condition:** Records are connected through shared entities, and approved changes appear consistently across all related pages.

## Phase 3 — Map, timeline, and family explorer

Build:

- Interactive map.
- Place search and filters.
- Place detail pages.
- Historical event timeline.
- Time-based filtering.
- Interactive family trees.
- Broader relationship explorer.
- Mobile and accessible alternatives.

**Completion condition:** A user can navigate from the map or timeline to real records and explore documented relationships without encountering dead links or invented associations.

## Phase 4 — Digital archive and oral histories

Build:

- Secure file uploads.
- Media storage.
- Image previews and thumbnails.
- Document metadata.
- Rights and permission management.
- Collections.
- Audio and video playback.
- Transcripts and translations.
- Consent tracking.
- Media moderation and review.

**Completion condition:** Authorized contributors can submit media, editors can review it, and only appropriately approved material becomes public.

## Phase 5 — Community and contributions

Build:

- Registration and account settings.
- Contributor dashboard.
- Correction requests.
- Family representative permissions.
- Moderated forum.
- Notifications where appropriate.
- Reporting and moderation tools.
- Contributor attribution.

**Completion condition:** Public users can browse freely, registered users can contribute through the review workflow, and forum activity is moderated and separate from authoritative archive records.

## Phase 6 — Preservation, refinement, and launch readiness

Build or complete:

- Data import and export.
- Backup and restoration documentation.
- Data-quality reports.
- Accessibility audit.
- Performance improvements.
- SEO and social metadata.
- Security review.
- End-to-end tests.
- Production deployment documentation.
- Administrator handover guide.

**Completion condition:** The project can be installed, configured, tested, deployed, operated, backed up, restored, and maintained by someone other than the original developer.

---

# 26. TESTING AND QUALITY ASSURANCE

Testing must cover real behavior, not just whether pages render.

## 26.1 Unit tests

Test important business logic, including:

- Permission checks.
- Date uncertainty handling.
- Name normalization and alias search.
- Relationship validation.
- Publication-status transitions.
- Duplicate-detection helpers.
- File-access policies.
- Citation associations.

## 26.2 Integration tests

Test:

- Database persistence.
- Authentication.
- Authorization.
- Record creation and editing.
- Submission and review workflows.
- Record merging.
- Search.
- Family relationships.
- Event participation.
- Media metadata and access.
- Restricted records.
- User account operations.

## 26.3 End-to-end tests

At minimum, test the following scenarios:

1. A public visitor opens a biography, follows a family link, opens a related event, and views a public document.
2. A contributor creates a draft and submits it for review.
3. An editor reviews the submission and requests changes.
4. The contributor revises and resubmits it.
5. An editor approves and publishes it.
6. The published record becomes discoverable through search.
7. The published record appears on relevant person, family, place, and event pages.
8. A family representative proposes a relationship and cannot publish it directly.
9. An unauthorized user attempts to access a restricted record and is denied.
10. A restricted file cannot be retrieved through a guessed or copied URL.
11. An editor merges duplicate records without losing relationships or citations.
12. A forum user submits a report and a moderator can process it.
13. A user cannot elevate their own role or modify another user's account through a forged request.
14. A record with uncertain dates displays the uncertainty correctly.
15. A mobile user can navigate the map and access a list alternative.
16. A user can search alternative spellings and reach the canonical person profile.

## 26.4 Accessibility and visual QA

Check:

- Keyboard navigation.
- Focus states.
- Screen-reader labeling.
- Contrast.
- Form validation.
- Responsive layouts.
- Family-tree alternatives.
- Map alternatives.
- Timeline alternatives.
- Image alt text.
- Audio and video transcripts.

## 26.5 Operational QA

Verify:

- Fresh installation.
- Database migrations.
- Seed-data isolation.
- Production build.
- Environment configuration.
- File upload behavior.
- Backup process.
- Restoration process.
- Error handling.
- Logs without secrets.
- Dependency and security checks.

Do not claim a feature is tested if the test was not actually run.

---

# 27. DEFINITION OF DONE

The project is not complete merely because the homepage looks polished.

A feature is complete only when its data, interface, permissions, errors, and relevant tests work together.

The initial release must meet these requirements:

- Every main navigation item opens a working section.
- Public historical records have stable URLs.
- Core record types are stored in the database.
- Related records share canonical entities.
- Search returns real records and supports aliases.
- The historical map uses real place records and documented coordinates or explicitly marked approximations.
- The timeline uses real event records.
- Family trees use actual relationship records.
- Archive items include metadata and permission controls.
- Oral histories include appropriate consent and publication controls.
- Registered users can submit content.
- Submissions remain unpublished until approved.
- Editors can review and publish contributions.
- Family representatives have scoped permissions.
- Forum posts and moderation actions are persisted.
- Server-side access control prevents unauthorized actions.
- Private data and restricted media are not publicly accessible.
- Revisions and important administrative actions are recorded.
- The application has useful loading, empty, success, and error states.
- The interface works on desktop and mobile.
- Critical workflows have automated tests.
- Setup, migration, deployment, backup, and restoration instructions are documented.

Every visible button, link, filter, form, tab, and control must perform its advertised action.

Do not use placeholder buttons that do nothing. Do not hardcode fake search results. Do not display fabricated statistics. Do not simulate authentication with frontend-only state.

If a feature requires external configuration, implement the integration where possible, clearly identify what is missing, and document how to configure it.

---

# 28. IMPLEMENTATION RULES FOR CLAUDE

Follow these rules throughout development.

## Rule 1: Inspect before changing

Inspect the existing repository, package configuration, framework, database, and environment before choosing an implementation strategy.

Do not overwrite an existing working project or replace its architecture without understanding it.

## Rule 2: Plan the architecture first

Before major implementation, produce a concise architecture proposal including:

- Chosen technology stack.
- Database schema.
- Authentication and authorization approach.
- File storage approach.
- Search strategy.
- Mapping library and geographic data source.
- Main pages and routes.
- Reusable component strategy.
- Editorial workflow.
- Testing strategy.
- Deployment and backup approach.

Explain meaningful tradeoffs and any external services or credentials required.

Then proceed with implementation unless a critical decision is genuinely blocked.

## Rule 3: Build real functionality

Prioritize working end-to-end workflows over superficial breadth.

A smaller feature that correctly saves data, checks permissions, handles errors, and has tests is better than a larger feature that only looks interactive.

## Rule 4: Use shared records

Do not duplicate people, families, events, places, or sources just to populate different pages.

Use canonical entities and explicit relationships. When a record changes, all related views should reflect the change consistently.

## Rule 5: Enforce permissions on the server

Never trust the browser to enforce publication status, account roles, family-representative permissions, or access to private files.

## Rule 6: Keep historical content separate from application logic

Historical records must be stored as data. Do not hardcode biographies, family trees, or event descriptions directly into components.

The same application should support adding new content without editing source code.

## Rule 7: Preserve evidence and uncertainty

Store citations, provenance, revision history, and uncertainty as first-class data.

Do not invent missing facts to make pages appear complete.

## Rule 8: Do not silently substitute services

If a map, storage service, email provider, search engine, or authentication provider needs configuration, explain that dependency.

Provide a local development alternative where reasonable.

## Rule 9: Keep the project maintainable

Use clear naming, modular architecture, consistent formatting, type safety, reusable components, and documented conventions.

Avoid unnecessary abstraction, excessive dependencies, and infrastructure complexity.

## Rule 10: Run the application and tests

After implementing a feature:

- Run relevant tests.
- Run type checking.
- Run linting.
- Build the application where feasible.
- Test the actual user workflow.
- Fix errors before claiming completion.

Report any tests or checks that could not be run.

## Rule 11: Do not fabricate progress

Clearly distinguish between completed, partially implemented, mocked, and planned functionality.

Do not claim database persistence, real authentication, secure media access, or working map interactions unless they have actually been implemented and verified.

## Rule 12: Maintain project documentation

Keep documentation updated as the architecture evolves.

Document important design decisions, schema changes, environment variables, external dependencies, known limitations, and operational procedures.

---

# 29. REQUIRED PROJECT DELIVERABLES

Deliver the working application and the supporting files needed to operate it.

At minimum, provide:

1. Full application source code.
2. Database schema and migrations.
3. Authentication and authorization implementation.
4. Reusable frontend components and design system.
5. All major public pages.
6. Administrative dashboard.
7. Historical record management.
8. Search and filtering.
9. Interactive map.
10. Timeline.
11. Family tree and relationship explorer.
12. Archive and media-management system.
13. Oral-history system.
14. Contribution and editorial-review workflow.
15. Community forum.
16. Seed-data and import approach.
17. Automated tests for critical workflows.
18. `.env.example`.
19. README with installation and setup instructions.
20. Database migration and development commands.
21. Deployment guide.
22. Backup and restoration guide.
23. Security and permission documentation.
24. Historical editorial and contribution guidelines.
25. Known limitations and future improvements.

Also provide:

- A clear folder and file structure.
- An explanation of the database relationships.
- A summary of implemented routes and features.
- A list of required external accounts or API keys.
- Instructions for creating the first administrator account securely.
- Instructions for importing the first verified historical records.
- A launch checklist.

Do not include real secrets in the source code or documentation.

---

# 30. FIRST TASK: BEGIN DEVELOPMENT

Start by inspecting the current development environment and repository.

Then produce:

**A. Architecture proposal**

Explain the stack, project structure, database design, authentication, storage, search, map, and deployment approach.

**B. Page and route inventory**

List the public pages, authenticated pages, administrative pages, and key API or server actions.

**C. Data model**

Show the core entities, important fields, relationships, permission boundaries, and treatment of uncertain historical information.

**D. Development milestones**

Identify dependencies, implementation order, testing strategy, and what qualifies as complete for each milestone.

**E. Immediate implementation**

Once the proposal is established, begin creating the application. Do not stop at a specification or wait for me to manually approve every routine decision.

Inspect the existing repository first, preserve useful work, and implement the highest-priority foundation.

If the project is starting from an empty repository, scaffold the application, configure the database and migrations, establish the design system, implement authentication and server-side permissions, and build the shared record architecture.

Then continue through the phases in this specification.

At the end of each milestone, summarize:

- What was implemented.
- Which files or modules were created or changed.
- Which workflows work.
- Which tests and checks were run.
- What remains incomplete.
- Any external configuration I must provide.

**Final objective:** Deliver a dignified, secure, historically responsible, searchable, interconnected digital archive that can preserve the stories of the ELF and Eritrea’s independence struggle for generations—not just a website that looks finished in a screenshot.

Build it with the care appropriate to a historical institution whose records may become an important resource for families, researchers, and future generations.