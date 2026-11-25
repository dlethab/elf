-- 0011_atlas_depth.sql — editorial depth for the historical atlas.
-- 1. A differing account can be marked as being about WHERE a place is, so the map can show that sources
--    disagree about a location (instead of guessing from the topic text).
ALTER TABLE conflicting_accounts ADD COLUMN concerns_location INTEGER NOT NULL DEFAULT 0 CHECK (concerns_location IN (0,1));
UPDATE conflicting_accounts SET concerns_location = 1
 WHERE entity_id IN (SELECT id FROM entities WHERE kind = 'place')
   AND (lower(topic) LIKE '%location%' OR lower(topic) LIKE '%where%' OR lower(topic) LIKE '%coordinates%' OR lower(topic) LIKE '%site of%');

-- 2. Curated explorations: an editor's saved selection of real, reviewed records (a period, a region or a theme),
--    with a description, sources and the editor's name. Only the records that are public at the time of viewing
--    are ever shown; the exploration itself never makes a record visible.
CREATE TABLE explorations (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE CHECK (slug GLOB '[a-z0-9]*' AND slug NOT GLOB '*[^a-z0-9-]*'),
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  sources_note TEXT,                          -- the sources this selection rests on, in the editor's words
  period_from INTEGER CHECK (period_from IS NULL OR period_from BETWEEN 1000 AND 2100),
  period_to INTEGER CHECK (period_to IS NULL OR period_to BETWEEN 1000 AND 2100),
  region TEXT,
  is_published INTEGER NOT NULL DEFAULT 0 CHECK (is_published IN (0,1)),
  created_by INTEGER NOT NULL REFERENCES users(id),
  updated_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (period_from IS NULL OR period_to IS NULL OR period_from <= period_to)
);
CREATE TABLE exploration_items (
  exploration_id INTEGER NOT NULL REFERENCES explorations(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entities(id),
  position INTEGER NOT NULL DEFAULT 0,
  note TEXT,                                  -- why this record is part of the exploration (shown with it)
  PRIMARY KEY (exploration_id, entity_id)
);
CREATE INDEX idx_exploration_items_entity ON exploration_items(entity_id);
