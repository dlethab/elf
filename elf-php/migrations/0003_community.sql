-- 0003_community.sql — forum, reports, moderation. SCHEMA ONLY at this milestone (Milestone 5 UI).

CREATE TABLE forum_categories (
  id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL, description TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE forum_topics (
  id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES forum_categories(id),
  slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
  author_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','locked','archived','hidden')),
  is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE forum_posts (
  id INTEGER PRIMARY KEY,
  topic_id INTEGER NOT NULL REFERENCES forum_topics(id),
  author_id INTEGER NOT NULL REFERENCES users(id),
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','hidden','removed')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  edited_at TEXT
);
CREATE INDEX idx_posts_topic ON forum_posts(topic_id, created_at);
CREATE TABLE reports (
  id INTEGER PRIMARY KEY,
  reporter_id INTEGER NOT NULL REFERENCES users(id),
  post_id INTEGER REFERENCES forum_posts(id),
  topic_id INTEGER REFERENCES forum_topics(id),
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','actioned','dismissed','escalated')),
  handled_by INTEGER REFERENCES users(id),
  resolution_note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (post_id IS NOT NULL OR topic_id IS NOT NULL)
);
CREATE TABLE moderation_actions (
  id INTEGER PRIMARY KEY,
  moderator_id INTEGER NOT NULL REFERENCES users(id),
  action TEXT NOT NULL, target_type TEXT NOT NULL, target_id INTEGER NOT NULL, reason TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TRIGGER modactions_no_update BEFORE UPDATE ON moderation_actions
BEGIN SELECT RAISE(ABORT, 'moderation log is append-only'); END;
CREATE TRIGGER modactions_no_delete BEFORE DELETE ON moderation_actions
BEGIN SELECT RAISE(ABORT, 'moderation log is append-only'); END;
