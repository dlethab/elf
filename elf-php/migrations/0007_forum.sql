-- 0007_forum.sql — the community forum: default categories (administrators can change them),
-- edit history for posts, report categories, reply notifications.

INSERT INTO forum_categories (slug, title, description, sort_order) VALUES
 ('family-histories', 'Family histories and memories', 'Share and discuss family histories, and ask relatives and others for help.', 10),
 ('historical-events', 'Historical events', 'Discuss events, their dates and places, and differing accounts of them.', 20),
 ('photo-identification', 'Photo identification', 'Help identify people, places and dates in photographs.', 30),
 ('hometowns', 'Hometown and regional history', 'Towns, villages and regions: their names, people and history.', 40),
 ('research-questions', 'Research questions', 'Ask for sources, archives and advice on research.', 50),
 ('recollections', 'Personal recollections', 'First-hand memories. They are community conversation, not verified records.', 60),
 ('archival-discoveries', 'Archival discoveries', 'Documents, publications and collections you have found.', 70),
 ('general', 'General community discussion', 'Everything else about the archive and its community.', 80);

ALTER TABLE forum_topics ADD COLUMN last_post_at TEXT;
ALTER TABLE forum_topics ADD COLUMN archive_link TEXT;     -- a related archive record's permanent id, if any
ALTER TABLE forum_posts ADD COLUMN edit_count INTEGER NOT NULL DEFAULT 0;

-- Earlier versions of an edited post (append-only), so moderators can see what was changed.
CREATE TABLE forum_post_edits (
  id INTEGER PRIMARY KEY,
  post_id INTEGER NOT NULL REFERENCES forum_posts(id),
  previous_body TEXT NOT NULL,
  edited_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TRIGGER post_edits_no_update BEFORE UPDATE ON forum_post_edits
BEGIN SELECT RAISE(ABORT, 'post edit history is append-only'); END;
CREATE TRIGGER post_edits_no_delete BEFORE DELETE ON forum_post_edits
BEGIN SELECT RAISE(ABORT, 'post edit history is append-only'); END;

ALTER TABLE reports ADD COLUMN category TEXT NOT NULL DEFAULT 'other'
  CHECK (category IN ('spam','harassment','private_information','threat','misinformation','copyright','other'));
ALTER TABLE users ADD COLUMN notify_forum_replies INTEGER NOT NULL DEFAULT 1 CHECK (notify_forum_replies IN (0,1));

CREATE INDEX idx_topics_category ON forum_topics(category_id, is_pinned, last_post_at);
CREATE INDEX idx_reports_status ON reports(status, created_at);
