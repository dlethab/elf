-- 0010_date_accounts.sql — a differing account can be marked as being about the DATE of the record, so the
-- timeline can show that sources disagree about when an event happened (instead of guessing from the topic text).
ALTER TABLE conflicting_accounts ADD COLUMN concerns_date INTEGER NOT NULL DEFAULT 0 CHECK (concerns_date IN (0,1));
-- accounts recorded before this existed: topics that plainly name a date or year
UPDATE conflicting_accounts SET concerns_date = 1 WHERE lower(topic) LIKE '%date%' OR lower(topic) LIKE '%year%' OR lower(topic) LIKE '%when %';
