-- 0004_photos.sql — photographs attached to contributions.
--
-- A photo arrives attached to a SUBMISSION. It is not an archive record until an editor publishes
-- the submission and decides, per photo, whether to include it and who may see it. Only then does
-- it become an archive item linked to the record it illustrates.

-- media_files was schema-only (no code used it), so it is recreated: files may now belong to a
-- submission before they belong to a published entity.
DROP INDEX idx_media_owner;
DROP TABLE media_files;
CREATE TABLE media_files (
  id INTEGER PRIMARY KEY,
  owner_id INTEGER REFERENCES entities(id),            -- archive item, once published
  submission_id INTEGER REFERENCES submissions(id),    -- the contribution it arrived with (kept for provenance)
  storage_key TEXT NOT NULL UNIQUE,                    -- random; never derived from the upload name
  original_filename TEXT,                              -- shown to staff only
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
  width INTEGER, height INTEGER,
  sha256 TEXT NOT NULL,
  file_role TEXT NOT NULL CHECK (file_role IN ('original','access_derivative','thumbnail','edited_derivative')),
  derived_from_id INTEGER REFERENCES media_files(id),
  access_level TEXT NOT NULL DEFAULT 'private' CHECK (access_level IN ({{VOCAB:ACCESS_LEVELS}})),
  processing_status TEXT NOT NULL DEFAULT 'pending' CHECK (processing_status IN ('pending','processing','done','failed')),
  processing_error TEXT,
  digitization_note TEXT,
  uploaded_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (file_role = 'original' OR derived_from_id IS NOT NULL),    -- derivatives always point at their original
  CHECK (owner_id IS NOT NULL OR submission_id IS NOT NULL)         -- never an orphan
);
CREATE INDEX idx_media_owner ON media_files(owner_id);
CREATE INDEX idx_media_submission ON media_files(submission_id);

-- What the contributor told us about each photo, and what the editor decided.
CREATE TABLE submission_photos (
  id INTEGER PRIMARY KEY,
  submission_id INTEGER NOT NULL REFERENCES submissions(id),
  original_media_id INTEGER NOT NULL UNIQUE REFERENCES media_files(id),
  caption TEXT NOT NULL,
  creator_text TEXT,                         -- photographer, if known (NOT necessarily the uploader)
  {{DATE:taken}},
  place_note TEXT,                           -- proposed identifications: unverified, staff-only
  people_note TEXT,
  rights_holder TEXT,
  rights_status TEXT NOT NULL DEFAULT 'rights_unknown' CHECK (rights_status IN ({{VOCAB:RIGHTS_STATUSES}})),
  rights_declared INTEGER NOT NULL CHECK (rights_declared = 1),
  editor_decision TEXT NOT NULL DEFAULT 'pending' CHECK (editor_decision IN ('pending','accept','decline')),
  editor_access TEXT NOT NULL DEFAULT 'restricted' CHECK (editor_access IN ('public','restricted')),
  editor_rights_status TEXT CHECK (editor_rights_status IN ({{VOCAB:RIGHTS_STATUSES}})),
  published_caption TEXT,
  editor_note TEXT,                          -- confidential
  decided_by INTEGER REFERENCES users(id),
  result_item_id INTEGER,
  result_item_kind TEXT NOT NULL DEFAULT 'archive_item' CHECK (result_item_kind = 'archive_item'),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  FOREIGN KEY (result_item_id, result_item_kind) REFERENCES entities(id, kind),
  -- a public decision is only possible with rights that permit public display
  CHECK (editor_access = 'restricted' OR editor_rights_status IN ({{VOCAB:PUBLIC_RIGHTS}}))
);
CREATE INDEX idx_subphotos_sub ON submission_photos(submission_id);

-- Which records an archive item depicts or documents (a photo of a person, a family, a place…).
CREATE TABLE archive_item_subjects (
  item_id INTEGER NOT NULL,
  item_kind TEXT NOT NULL DEFAULT 'archive_item' CHECK (item_kind = 'archive_item'),
  subject_id INTEGER NOT NULL REFERENCES entities(id),
  note TEXT,
  PRIMARY KEY (item_id, subject_id),
  FOREIGN KEY (item_id, item_kind) REFERENCES entities(id, kind),
  CHECK (item_id <> subject_id)
);
CREATE INDEX idx_item_subject ON archive_item_subjects(subject_id);
