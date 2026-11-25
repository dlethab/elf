-- 0008_mfa.sql — optional two-step sign-in (TOTP authenticator apps, RFC 6238) and recovery codes.
ALTER TABLE users ADD COLUMN totp_secret TEXT;            -- base32; needed to check codes (protect the database file)
ALTER TABLE users ADD COLUMN totp_enabled_at TEXT;
ALTER TABLE users ADD COLUMN totp_last_step INTEGER;      -- a code can be used only once
ALTER TABLE users ADD COLUMN recovery_codes TEXT;         -- JSON list of SHA-256 hashes; each code works once
