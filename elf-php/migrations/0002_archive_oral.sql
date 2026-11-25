-- 0002_archive_oral.sql — digital archive, media, collections, oral histories, consent.
-- SCHEMA ONLY at this milestone: upload handling and UI arrive in Milestone 4.

CREATE TABLE archive_items (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'archive_item' CHECK (kind = 'archive_item'),
  title TEXT NOT NULL, alt_title TEXT,
  item_type TEXT NOT NULL CHECK (item_type IN ({{VOCAB:ITEM_TYPES}})),
  description TEXT,
  {{DATE:created}},
  creator TEXT,                              -- original creator/photographer (not the uploader)
  uploaded_by INTEGER REFERENCES users(id),  -- uploader (not necessarily creator or rights holder)
  donor TEXT, custodian TEXT, collection_note TEXT, provenance TEXT,
  original_language TEXT, transcript TEXT,
  rights_holder TEXT,
  rights_status TEXT NOT NULL DEFAULT 'rights_unknown' CHECK (rights_status IN ({{VOCAB:RIGHTS_STATUSES}})),
  access_level TEXT NOT NULL DEFAULT 'private' CHECK (access_level IN ({{VOCAB:ACCESS_LEVELS}})),
  embargo_until TEXT,
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind)
);

CREATE TABLE media_files (
  id INTEGER PRIMARY KEY,
  owner_id INTEGER NOT NULL REFERENCES entities(id),   -- archive item or oral history
  storage_key TEXT NOT NULL UNIQUE,                    -- generated; never derived from the upload name
  original_filename TEXT,
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
  sha256 TEXT NOT NULL,
  file_role TEXT NOT NULL CHECK (file_role IN ('original','access_derivative','thumbnail','edited_derivative')),
  derived_from_id INTEGER REFERENCES media_files(id),
  access_level TEXT NOT NULL DEFAULT 'private' CHECK (access_level IN ({{VOCAB:ACCESS_LEVELS}})),
  processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending','processing','done','failed')),
  processing_error TEXT,
  digitization_note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (file_role = 'original' OR derived_from_id IS NOT NULL)   -- derivatives always point at their original
);
CREATE INDEX idx_media_owner ON media_files(owner_id);

CREATE TABLE collections (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'collection' CHECK (kind = 'collection'),
  title TEXT NOT NULL, description TEXT, rights_note TEXT,
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind)
);
CREATE TABLE collection_items (
  collection_id INTEGER NOT NULL,
  collection_kind TEXT NOT NULL DEFAULT 'collection' CHECK (collection_kind = 'collection'),
  item_id INTEGER NOT NULL,
  item_kind TEXT NOT NULL DEFAULT 'archive_item' CHECK (item_kind = 'archive_item'),
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (collection_id, item_id),
  FOREIGN KEY (collection_id, collection_kind) REFERENCES entities(id, kind),
  FOREIGN KEY (item_id, item_kind) REFERENCES entities(id, kind)
);

CREATE TABLE oral_histories (
  entity_id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'oral_history' CHECK (kind = 'oral_history'),
  title TEXT NOT NULL,
  interview_code TEXT UNIQUE,
  interviewee_id INTEGER,
  interviewee_kind TEXT NOT NULL DEFAULT 'person' CHECK (interviewee_kind = 'person'),
  interviewer_text TEXT,
  {{DATE:recorded}},
  recording_location_note TEXT,
  language TEXT, translation_language TEXT,
  summary TEXT, transcript_text TEXT,
  transcript_kind TEXT CHECK (transcript_kind IN ({{VOCAB:TRANSCRIPT_KINDS}})),
  transcript_reviewed INTEGER NOT NULL DEFAULT 0 CHECK (transcript_reviewed IN (0,1)),
  embargo_until TEXT, redaction_notes TEXT,
  FOREIGN KEY (entity_id, kind) REFERENCES entities(id, kind),
  FOREIGN KEY (interviewee_id, interviewee_kind) REFERENCES entities(id, kind)
);

-- Consent is granular: each permission is its own row so "recorded" never implies "published".
CREATE TABLE consent_records (
  id INTEGER PRIMARY KEY,
  oral_history_id INTEGER NOT NULL,
  oral_history_kind TEXT NOT NULL DEFAULT 'oral_history' CHECK (oral_history_kind = 'oral_history'),
  consent_type TEXT NOT NULL CHECK (consent_type IN ({{VOCAB:CONSENT_TYPES}})),
  granted INTEGER NOT NULL CHECK (granted IN (0,1)),
  granted_on TEXT, granted_by_text TEXT, evidence_note TEXT,
  recorded_by INTEGER REFERENCES users(id),
  revoked_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (oral_history_id, oral_history_kind) REFERENCES entities(id, kind)
);
CREATE UNIQUE INDEX uq_consent_active ON consent_records(oral_history_id, consent_type) WHERE revoked_at IS NULL;
