-- migrate: foreign_keys=off
-- 0005_records.sql — new submission kinds (organizations, affiliations, family memberships, event
-- participation, archive items, oral histories), the researcher role, CSV import batches, and
-- provenance columns on link tables.
--
-- SQLite cannot alter a CHECK constraint, so `submissions` and `user_roles` are rebuilt following
-- SQLite's documented procedure (foreign keys suspended; the runner verifies every reference with
-- PRAGMA foreign_key_check before committing). No data is changed.

CREATE TABLE imports (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  filename TEXT,
  created_by INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'preview' CHECK (status IN ('preview','created','discarded')),
  rows_json TEXT NOT NULL,                  -- validated rows and per-row errors, kept for the preview
  total_rows INTEGER NOT NULL, valid_rows INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE submissions_new (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ({{VOCAB:SUBMISSION_KINDS}})),
  target_entity_id INTEGER REFERENCES entities(id),
  family_scope_id INTEGER,
  family_scope_kind TEXT NOT NULL DEFAULT 'family' CHECK (family_scope_kind = 'family'),
  proposed_data TEXT NOT NULL,
  contributor_note TEXT,
  rights_note TEXT,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ({{VOCAB:SUBMISSION_STATUSES}})),
  submitter_id INTEGER NOT NULL REFERENCES users(id),
  reviewer_id INTEGER REFERENCES users(id),
  decision_reason TEXT,
  editor_notes TEXT,
  base_revision INTEGER,
  result_entity_id INTEGER REFERENCES entities(id),
  consent_confirmed INTEGER NOT NULL DEFAULT 0 CHECK (consent_confirmed IN (0,1)),
  import_batch_id INTEGER REFERENCES imports(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  submitted_at TEXT, decided_at TEXT, published_at TEXT,
  FOREIGN KEY (family_scope_id, family_scope_kind) REFERENCES entities(id, kind),
  CHECK (kind <> 'correction' OR target_entity_id IS NOT NULL)
);
INSERT INTO submissions_new (id, kind, target_entity_id, family_scope_id, family_scope_kind, proposed_data, contributor_note,
  rights_note, status, submitter_id, reviewer_id, decision_reason, editor_notes, base_revision, result_entity_id,
  consent_confirmed, created_at, updated_at, submitted_at, decided_at, published_at)
SELECT id, kind, target_entity_id, family_scope_id, family_scope_kind, proposed_data, contributor_note,
  rights_note, status, submitter_id, reviewer_id, decision_reason, editor_notes, base_revision, result_entity_id,
  consent_confirmed, created_at, updated_at, submitted_at, decided_at, published_at FROM submissions;
DROP TABLE submissions;
ALTER TABLE submissions_new RENAME TO submissions;
CREATE INDEX idx_sub_status ON submissions(status, submitted_at);
CREATE INDEX idx_sub_submitter ON submissions(submitter_id);
CREATE INDEX idx_sub_batch ON submissions(import_batch_id);

CREATE TABLE user_roles_new (
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL CHECK (role IN ({{VOCAB:ROLES}})),
  granted_by INTEGER REFERENCES users(id),
  granted_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  revoked_at TEXT,
  revoked_by INTEGER REFERENCES users(id),
  PRIMARY KEY (user_id, role)
);
INSERT INTO user_roles_new SELECT user_id, role, granted_by, granted_at, revoked_at, revoked_by FROM user_roles;
DROP TABLE user_roles;
ALTER TABLE user_roles_new RENAME TO user_roles;

-- Organizations: when they were active (uncertain dates allowed).
ALTER TABLE organizations ADD COLUMN active_start TEXT;
ALTER TABLE organizations ADD COLUMN active_end TEXT;
ALTER TABLE organizations ADD COLUMN active_precision TEXT NOT NULL DEFAULT 'unknown'
  CHECK (active_precision IN ({{VOCAB:PRECISIONS}}) AND (active_precision <> 'unknown' OR active_start IS NULL));
ALTER TABLE organizations ADD COLUMN active_note TEXT;

-- Where each link came from (the contribution that proposed it) and who created it.
ALTER TABLE affiliations ADD COLUMN submission_id INTEGER REFERENCES submissions(id);
ALTER TABLE affiliations ADD COLUMN created_by INTEGER REFERENCES users(id);
ALTER TABLE family_memberships ADD COLUMN submission_id INTEGER REFERENCES submissions(id);
ALTER TABLE event_participants ADD COLUMN submission_id INTEGER REFERENCES submissions(id);
ALTER TABLE event_participants ADD COLUMN created_by INTEGER REFERENCES users(id);
CREATE INDEX idx_aff_person ON affiliations(person_id);
CREATE INDEX idx_aff_org ON affiliations(organization_id);
CREATE INDEX idx_memb_person ON family_memberships(person_id);
CREATE INDEX idx_part_person ON event_participants(person_id);
CREATE INDEX idx_part_org ON event_participants(organization_id);

-- Conflicting accounts can be revised; the previous text is kept in the audit log.
ALTER TABLE conflicting_accounts ADD COLUMN updated_at TEXT;
ALTER TABLE conflicting_accounts ADD COLUMN updated_by INTEGER REFERENCES users(id);
