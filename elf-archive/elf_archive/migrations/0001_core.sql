-- 0001_core.sql — identity & access, shared entity registry, historical records,
-- evidence, editorial workflow, audit. Vocabulary and date macros are expanded
-- by elf_archive/db.py from elf_archive/vocab.py.

-- ───────────── Identity and access ─────────────
CREATE TABLE users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  email_verified_at TEXT,
  is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  deactivated_at TEXT,
  anonymized_at TEXT,
  bio TEXT, languages TEXT, research_interests TEXT,
  attribution_pref TEXT NOT NULL DEFAULT 'display_name'
    CHECK (attribution_pref IN ('display_name','username','anonymous')),
  notify_submission_updates INTEGER NOT NULL DEFAULT 1 CHECK (notify_submission_updates IN (0,1)),
  forum_restricted_until TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- 'contributor' is implicit for every active account; only elevated roles are stored.
CREATE TABLE user_roles (
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL CHECK (role IN ({{VOCAB:ROLES}})),
  granted_by INTEGER REFERENCES users(id),
  granted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  revoked_at TEXT,
  revoked_by INTEGER REFERENCES users(id),
  PRIMARY KEY (user_id, role)
);

CREATE TABLE user_sessions (
  token_hash TEXT PRIMARY KEY,               -- sha256 of the cookie token; raw token is never stored
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  ip TEXT, user_agent TEXT
);
CREATE INDEX idx_sessions_user ON user_sessions(user_id);

CREATE TABLE auth_tokens (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  purpose TEXT NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE rate_events (
  id INTEGER PRIMARY KEY,
  bucket TEXT NOT NULL,
  at INTEGER NOT NULL
);
CREATE INDEX idx_rate_bucket ON rate_events(bucket, at);

-- Email is queued here. Delivery is a separate step (SMTP) so the app works without a provider.
CREATE TABLE outbox (
  id INTEGER PRIMARY KEY,
  to_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  sent_at TEXT,
  error TEXT
);

-- ───────────── Taxonomies (configurable) ─────────────
CREATE TABLE place_types (
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1
);
INSERT INTO place_types (slug,label,sort_order) VALUES
 ('town_city','Town or city',10),('village','Village',20),('region','Region',30),
 ('historical_settlement','Historical settlement',40),('geographic_feature','Geographic feature',50),
 ('displacement_location','Refugee or displacement-related location',60),
 ('organizational_location','Training or organizational location',70),
 ('historical_site','Historical site',80),('conflict_location','Conflict or battle location',90),
 ('memorial_site','Memorial or commemorative site',100),('other','Other historically relevant place',999);

CREATE TABLE event_types (
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1
);
INSERT INTO event_types (slug,label,sort_order) VALUES
 ('battle_conflict','Battle or armed conflict',10),('political_development','Political development',20),
 ('organizational_development','Organizational development',30),('meeting_conference','Meeting or conference',40),
 ('statement_publication','Public statement or publication',50),('personal_life_event','Personal life event',60),
 ('displacement_migration','Displacement or migration',70),('humanitarian_event','Humanitarian event',80),
 ('community_event','Community event',90),('commemoration','Commemoration',100),
 ('other','Other historical event',999);

-- ───────────── Shared entity registry ─────────────
-- Every canonical historical record has exactly one row here. Publication state, visibility,
-- slug, permanent id and merge/tombstone state live in ONE place, so the public-visibility rule
-- is written once. Subtype tables reference (id, kind) so a "place" column can only hold a place.
CREATE TABLE entities (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ({{VOCAB:ENTITY_KINDS}})),
  public_id TEXT NOT NULL UNIQUE,            -- permanent identifier; never changes
  slug TEXT NOT NULL,
  publication_status TEXT NOT NULL DEFAULT 'draft' CHECK (publication_status IN ({{VOCAB:PUBLICATION_STATUSES}})),
  visibility TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ({{VOCAB:VISIBILITIES}})),
  is_fictional_test INTEGER NOT NULL DEFAULT 0 CHECK (is_fictional_test IN (0,1)),
  merged_into INTEGER REFERENCES entities(id),
  deleted_at TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (id, kind),
  UNIQUE (kind, slug),
  CHECK (merged_into IS NULL OR merged_into <> id)
);
CREATE INDEX idx_entities_public ON entities(kind, publication_status, visibility);

CREATE TABLE entity_slug_history (        -- old slugs keep resolving (HTTP 301)
  kind TEXT NOT NULL,
  slug TEXT NOT NULL,
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  retired_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  PRIMARY KEY (kind, slug)
);

-- Names, aliases, transliterations for any entity. Original spelling is never overwritten;
-- `normalized` is a separate search form.
CREATE TABLE entity_names (
  id INTEGER PRIMARY KEY,
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  name TEXT NOT NULL,
  normalized TEXT NOT NULL,
  name_type TEXT NOT NULL CHECK (name_type IN ({{VOCAB:NAME_TYPES}})),
  language TEXT, script TEXT, note TEXT,
  UNIQUE (entity_id, name, name_type)
);
CREATE INDEX idx_names_norm ON entity_names(normalized);
CREATE INDEX idx_names_entity ON entity_names(entity_id);

-- ───────────── Places ─────────────
CREATE TABLE places (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'place' CHECK (kind = 'place'),
  primary_name TEXT NOT NULL,
  original_name TEXT,
  place_type_id INTEGER REFERENCES place_types(id),
  country TEXT, admin_region TEXT,
  latitude REAL CHECK (latitude BETWEEN -90 AND 90),
  longitude REAL CHECK (longitude BETWEEN -180 AND 180),
  coord_precision TEXT CHECK (coord_precision IN ({{VOCAB:COORD_PRECISIONS}})),
  coord_note TEXT,
  overview TEXT,
  {{DATE:valid}},
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind),
  CHECK ((latitude IS NULL) = (longitude IS NULL)),                  -- never a half coordinate
  CHECK (latitude IS NULL OR coord_precision IS NOT NULL)            -- coordinates always carry precision
);

CREATE TABLE place_alt_locations (         -- alternative proposed locations / location over time
  id INTEGER PRIMARY KEY,
  place_id INTEGER NOT NULL,
  place_kind TEXT NOT NULL DEFAULT 'place' CHECK (place_kind = 'place'),
  latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
  longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
  coord_precision TEXT NOT NULL CHECK (coord_precision IN ({{VOCAB:COORD_PRECISIONS}})),
  note TEXT,
  {{DATE:valid}},
  FOREIGN KEY (place_id, place_kind) REFERENCES entities(id, kind)
);

-- ───────────── People ─────────────
CREATE TABLE people (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'person' CHECK (kind = 'person'),
  preferred_name TEXT NOT NULL,
  full_name TEXT, original_name TEXT, original_name_lang TEXT,
  summary TEXT, biography TEXT, occupation TEXT,
  living_status TEXT NOT NULL DEFAULT 'unknown' CHECK (living_status IN ('living','deceased','unknown')),
  {{DATE:birth}},
  birth_place_id INTEGER,
  birth_place_kind TEXT NOT NULL DEFAULT 'place' CHECK (birth_place_kind = 'place'),
  {{DATE:death}},
  death_place_id INTEGER,
  death_place_kind TEXT NOT NULL DEFAULT 'place' CHECK (death_place_kind = 'place'),
  research_notes TEXT,                      -- confidential; never selected by public queries
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind),
  FOREIGN KEY (birth_place_id, birth_place_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (death_place_id, death_place_kind) REFERENCES entities(id, kind)
);

-- ───────────── Families ─────────────
CREATE TABLE families (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'family' CHECK (kind = 'family'),
  display_name TEXT NOT NULL,
  original_name TEXT,
  summary TEXT, narrative TEXT, region_note TEXT,
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind)
);

CREATE TABLE family_memberships (
  id INTEGER PRIMARY KEY,
  family_id INTEGER NOT NULL,
  family_kind TEXT NOT NULL DEFAULT 'family' CHECK (family_kind = 'family'),
  person_id INTEGER NOT NULL,
  person_kind TEXT NOT NULL DEFAULT 'person' CHECK (person_kind = 'person'),
  role_note TEXT,
  {{DATE:period}},
  publication_status TEXT NOT NULL DEFAULT 'draft' CHECK (publication_status IN ({{VOCAB:PUBLICATION_STATUSES}})),
  visibility TEXT NOT NULL DEFAULT 'restricted' CHECK (visibility IN ({{VOCAB:VISIBILITIES}})),
  created_by INTEGER REFERENCES users(id),
  FOREIGN KEY (family_id, family_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (person_id, person_kind) REFERENCES entities(id, kind),
  UNIQUE (family_id, person_id)
);

-- A family representative is a contributor with a SCOPED grant on one family. Revocable.
CREATE TABLE family_representatives (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  family_id INTEGER NOT NULL,
  family_kind TEXT NOT NULL DEFAULT 'family' CHECK (family_kind = 'family'),
  can_suggest_edits INTEGER NOT NULL DEFAULT 1 CHECK (can_suggest_edits IN (0,1)),
  can_propose_tree INTEGER NOT NULL DEFAULT 1 CHECK (can_propose_tree IN (0,1)),
  can_submit_media INTEGER NOT NULL DEFAULT 0 CHECK (can_submit_media IN (0,1)),
  granted_by INTEGER REFERENCES users(id),
  granted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  revoked_at TEXT,
  revoked_by INTEGER REFERENCES users(id),
  FOREIGN KEY (family_id, family_kind) REFERENCES entities(id, kind)
);
CREATE UNIQUE INDEX uq_family_rep_active ON family_representatives(user_id, family_id) WHERE revoked_at IS NULL;

-- ───────────── Person-to-person relationships ─────────────
CREATE TABLE relationships (
  id INTEGER PRIMARY KEY,
  person_a_id INTEGER NOT NULL,
  person_a_kind TEXT NOT NULL DEFAULT 'person' CHECK (person_a_kind = 'person'),
  person_b_id INTEGER NOT NULL,
  person_b_kind TEXT NOT NULL DEFAULT 'person' CHECK (person_b_kind = 'person'),
  relationship_type TEXT NOT NULL CHECK (relationship_type IN ({{VOCAB:RELATIONSHIP_TYPES}})),
  status TEXT NOT NULL DEFAULT 'current' CHECK (status IN ({{VOCAB:RELATIONSHIP_STATUSES}})),
  {{DATE:period}},
  notes TEXT,
  publication_status TEXT NOT NULL DEFAULT 'draft' CHECK (publication_status IN ({{VOCAB:PUBLICATION_STATUSES}})),
  visibility TEXT NOT NULL DEFAULT 'restricted' CHECK (visibility IN ({{VOCAB:VISIBILITIES}})),
  created_by INTEGER REFERENCES users(id),
  submission_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (person_a_id, person_a_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (person_b_id, person_b_kind) REFERENCES entities(id, kind),
  CHECK (person_a_id <> person_b_id),
  -- symmetric types are stored in canonical order so (A,B) and (B,A) cannot both exist
  CHECK (relationship_type IN ({{VOCAB:DIRECTED_RELATIONSHIPS}}) OR person_a_id < person_b_id),
  UNIQUE (person_a_id, person_b_id, relationship_type)
);
CREATE INDEX idx_rel_a ON relationships(person_a_id);
CREATE INDEX idx_rel_b ON relationships(person_b_id);

-- ───────────── Organizations and affiliations ─────────────
CREATE TABLE organizations (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'organization' CHECK (kind = 'organization'),
  name TEXT NOT NULL,
  original_name TEXT,
  description TEXT,
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind)
);

CREATE TABLE affiliations (
  id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL,
  person_kind TEXT NOT NULL DEFAULT 'person' CHECK (person_kind = 'person'),
  organization_id INTEGER NOT NULL,
  organization_kind TEXT NOT NULL DEFAULT 'organization' CHECK (organization_kind = 'organization'),
  role TEXT,
  {{DATE:period}},
  place_id INTEGER,
  place_kind TEXT NOT NULL DEFAULT 'place' CHECK (place_kind = 'place'),
  evidence_status TEXT NOT NULL DEFAULT 'unverified' CHECK (evidence_status IN ({{VOCAB:EVIDENCE}})),
  notes TEXT,
  editor_notes TEXT,
  publication_status TEXT NOT NULL DEFAULT 'draft' CHECK (publication_status IN ({{VOCAB:PUBLICATION_STATUSES}})),
  visibility TEXT NOT NULL DEFAULT 'restricted' CHECK (visibility IN ({{VOCAB:VISIBILITIES}})),
  FOREIGN KEY (person_id, person_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (organization_id, organization_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (place_id, place_kind) REFERENCES entities(id, kind)
);

-- ───────────── Events ─────────────
CREATE TABLE events (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'event' CHECK (kind = 'event'),
  title TEXT NOT NULL,
  event_type_id INTEGER REFERENCES event_types(id),
  summary TEXT, description TEXT,
  {{DATE:date}},
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind)
);

CREATE TABLE event_places (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL,
  event_kind TEXT NOT NULL DEFAULT 'event' CHECK (event_kind = 'event'),
  place_id INTEGER NOT NULL,
  place_kind TEXT NOT NULL DEFAULT 'place' CHECK (place_kind = 'place'),
  role_note TEXT,
  is_uncertain INTEGER NOT NULL DEFAULT 0 CHECK (is_uncertain IN (0,1)),
  FOREIGN KEY (event_id, event_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (place_id, place_kind) REFERENCES entities(id, kind),
  UNIQUE (event_id, place_id)
);

CREATE TABLE event_participants (
  id INTEGER PRIMARY KEY,
  event_id INTEGER NOT NULL,
  event_kind TEXT NOT NULL DEFAULT 'event' CHECK (event_kind = 'event'),
  person_id INTEGER,
  person_kind TEXT NOT NULL DEFAULT 'person' CHECK (person_kind = 'person'),
  organization_id INTEGER,
  organization_kind TEXT NOT NULL DEFAULT 'organization' CHECK (organization_kind = 'organization'),
  role TEXT,
  evidence_status TEXT NOT NULL DEFAULT 'unverified' CHECK (evidence_status IN ({{VOCAB:EVIDENCE}})),
  notes TEXT,
  publication_status TEXT NOT NULL DEFAULT 'draft' CHECK (publication_status IN ({{VOCAB:PUBLICATION_STATUSES}})),
  FOREIGN KEY (event_id, event_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (person_id, person_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (organization_id, organization_kind) REFERENCES entities(id, kind),
  CHECK ((person_id IS NOT NULL) + (organization_id IS NOT NULL) = 1)   -- exactly one participant
);
CREATE UNIQUE INDEX uq_event_person ON event_participants(event_id, person_id) WHERE person_id IS NOT NULL;
CREATE UNIQUE INDEX uq_event_org ON event_participants(event_id, organization_id) WHERE organization_id IS NOT NULL;

-- ───────────── Sources, citations, conflicting accounts ─────────────
CREATE TABLE sources (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'source' CHECK (kind = 'source'),
  title TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'other' CHECK (source_type IN ({{VOCAB:SOURCE_TYPES}})),
  creator TEXT, publisher TEXT, repository TEXT, identifier TEXT,
  pub_date_text TEXT,                       -- free text: publication dates are often partial
  url TEXT, accessed_on TEXT, language TEXT,
  provenance TEXT, rights_note TEXT, reliability_note TEXT,
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind)
);

-- A citation ties ONE source to ONE claim (field/passage) on ONE record. Not "the whole page".
CREATE TABLE citations (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'source' CHECK (source_kind = 'source'),
  target_id INTEGER NOT NULL REFERENCES entities(id),
  field_name TEXT,                          -- e.g. 'birth', 'biography'; NULL = general
  claim_text TEXT,
  locator TEXT,                             -- page, timestamp, section
  explanation TEXT,
  evidence_status TEXT NOT NULL DEFAULT 'unverified' CHECK (evidence_status IN ({{VOCAB:EVIDENCE}})),
  editor_note TEXT,                         -- confidential
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (source_id, source_kind) REFERENCES entities(id, kind)
);
CREATE INDEX idx_citations_target ON citations(target_id);
CREATE INDEX idx_citations_source ON citations(source_id);

CREATE TABLE conflicting_accounts (        -- differing accounts are preserved, never silently overwritten
  id INTEGER PRIMARY KEY,
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  topic TEXT NOT NULL,
  account_text TEXT NOT NULL,
  attributed_to TEXT,
  source_id INTEGER,
  source_kind TEXT NOT NULL DEFAULT 'source' CHECK (source_kind = 'source'),
  basis_note TEXT,
  needs_research INTEGER NOT NULL DEFAULT 0 CHECK (needs_research IN (0,1)),
  is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0,1)),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (source_id, source_kind) REFERENCES entities(id, kind)
);

-- ───────────── Revisions and audit (append-only) ─────────────
CREATE TABLE revisions (
  id INTEGER PRIMARY KEY,
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  revision_number INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  change_summary TEXT NOT NULL,
  reason TEXT,
  actor_id INTEGER REFERENCES users(id),
  submission_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  UNIQUE (entity_id, revision_number)
);
CREATE TRIGGER revisions_no_update BEFORE UPDATE ON revisions
BEGIN SELECT RAISE(ABORT, 'revisions are append-only'); END;
CREATE TRIGGER revisions_no_delete BEFORE DELETE ON revisions
BEGIN SELECT RAISE(ABORT, 'revisions are append-only'); END;

CREATE TABLE audit_logs (
  id INTEGER PRIMARY KEY,
  actor_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  detail_json TEXT,
  ip TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;

CREATE TABLE merges (
  id INTEGER PRIMARY KEY,
  canonical_id INTEGER NOT NULL REFERENCES entities(id),
  retired_id INTEGER NOT NULL REFERENCES entities(id),
  performed_by INTEGER NOT NULL REFERENCES users(id),
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (canonical_id <> retired_id)
);

-- ───────────── Editorial workflow ─────────────
CREATE TABLE submissions (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ({{VOCAB:SUBMISSION_KINDS}})),
  target_entity_id INTEGER REFERENCES entities(id),      -- corrections: the record being corrected
  family_scope_id INTEGER,                               -- relationship proposals: the family granting scope
  family_scope_kind TEXT NOT NULL DEFAULT 'family' CHECK (family_scope_kind = 'family'),
  proposed_data TEXT NOT NULL,                           -- validated JSON
  contributor_note TEXT,
  rights_note TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ({{VOCAB:SUBMISSION_STATUSES}})),
  submitter_id INTEGER NOT NULL REFERENCES users(id),
  reviewer_id INTEGER REFERENCES users(id),
  decision_reason TEXT,                                  -- shown to the submitter
  editor_notes TEXT,                                     -- confidential; never shown to submitter
  base_revision INTEGER,                                 -- target's revision number when submitted
  result_entity_id INTEGER REFERENCES entities(id),
  consent_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (consent_confirmed IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  submitted_at TEXT, decided_at TEXT, published_at TEXT,
  FOREIGN KEY (family_scope_id, family_scope_kind) REFERENCES entities(id, kind),
  CHECK (kind <> 'correction' OR target_entity_id IS NOT NULL)
);
CREATE INDEX idx_sub_status ON submissions(status, submitted_at);
CREATE INDEX idx_sub_submitter ON submissions(submitter_id);

CREATE TABLE submission_events (
  id INTEGER PRIMARY KEY,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  actor_id INTEGER REFERENCES users(id),
  from_status TEXT, to_status TEXT NOT NULL,
  message TEXT,
  visible_to_submitter INTEGER NOT NULL DEFAULT 1 CHECK (visible_to_submitter IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TRIGGER subevents_no_update BEFORE UPDATE ON submission_events
BEGIN SELECT RAISE(ABORT, 'submission events are append-only'); END;
CREATE TRIGGER subevents_no_delete BEFORE DELETE ON submission_events
BEGIN SELECT RAISE(ABORT, 'submission events are append-only'); END;

CREATE TABLE notifications (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  link TEXT,
  read_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_notifications_user ON notifications(user_id, read_at);

CREATE TABLE contact_messages (            -- public correction requests / contact (no account needed)
  id INTEGER PRIMARY KEY,
  name TEXT, email TEXT,
  message TEXT NOT NULL,
  related_public_id TEXT,
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','handled')),
  handled_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ───────────── Search index (public records only; maintained by services/search.py) ─────────────
CREATE VIRTUAL TABLE search_fts USING fts5(
  title, aliases, body,
  tokenize = 'unicode61 remove_diacritics 2'
);
