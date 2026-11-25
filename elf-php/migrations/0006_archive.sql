-- 0006_archive.sql — documents, audio and video alongside photos; collections; oral histories with
-- granular consent; links from oral histories to the records they concern.

-- An uploaded file can now be an image, a PDF document, audio or video.
ALTER TABLE submission_photos ADD COLUMN media_kind TEXT NOT NULL DEFAULT 'image'
  CHECK (media_kind IN ('image','document','audio','video'));
ALTER TABLE submission_photos ADD COLUMN item_type TEXT NOT NULL DEFAULT 'photograph' CHECK (item_type IN ({{VOCAB:ITEM_TYPES}}));
ALTER TABLE submission_photos ADD COLUMN transcript TEXT;                  -- contributor's transcript (unverified)
ALTER TABLE archive_items ADD COLUMN media_kind TEXT NOT NULL DEFAULT 'image'
  CHECK (media_kind IN ('image','document','audio','video','none'));
ALTER TABLE archive_items ADD COLUMN transcript_reviewed INTEGER NOT NULL DEFAULT 0 CHECK (transcript_reviewed IN (0,1));

-- Collections are curated by editors.
ALTER TABLE collections ADD COLUMN is_featured INTEGER NOT NULL DEFAULT 0 CHECK (is_featured IN (0,1));
ALTER TABLE collections ADD COLUMN created_by INTEGER REFERENCES users(id);

-- Oral histories: what the interview is about, translations kept separate from the original
-- transcript, and the people/places/events/families it concerns.
ALTER TABLE oral_histories ADD COLUMN interviewee_text TEXT;            -- when the interviewee has no public record
ALTER TABLE oral_histories ADD COLUMN topics TEXT;
ALTER TABLE oral_histories ADD COLUMN translation_text TEXT;
ALTER TABLE oral_histories ADD COLUMN translation_kind TEXT
  CHECK (translation_kind IN ('human_reviewed','human_unreviewed','machine_draft'));
ALTER TABLE oral_histories ADD COLUMN media_item_id INTEGER;               -- the archive item holding the recording
ALTER TABLE oral_histories ADD COLUMN media_item_kind TEXT NOT NULL DEFAULT 'archive_item' CHECK (media_item_kind = 'archive_item');

CREATE TABLE oral_history_subjects (
  oral_history_id INTEGER NOT NULL,
  oral_history_kind TEXT NOT NULL DEFAULT 'oral_history' CHECK (oral_history_kind = 'oral_history'),
  subject_id INTEGER NOT NULL REFERENCES entities(id),
  PRIMARY KEY (oral_history_id, subject_id),
  FOREIGN KEY (oral_history_id, oral_history_kind) REFERENCES entities(id, kind)
);
CREATE INDEX idx_ohs_subject ON oral_history_subjects(subject_id);
