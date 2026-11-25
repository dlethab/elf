-- 0009_outbox_retry.sql — queued email is retried after a temporary failure (up to MAX_ATTEMPTS in
-- services/accounts.py); `error` now holds the most recent failure.
ALTER TABLE outbox ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
UPDATE outbox SET attempts = 1 WHERE error IS NOT NULL;
