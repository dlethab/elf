<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Accounts, sessions, email verification, password reset, roles.
 * Session and reset/verification tokens are random, and only their SHA-256 hashes are stored.
 */
final class Accounts
{
    public const EMAIL_RE = '/^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$/u';
    public const USERNAME_RE = '/^[A-Za-z0-9_]{3,30}$/';
    public const COMMON_PASSWORDS = ['password', 'password1', '1234567890', 'qwertyuiop', 'letmein123', 'iloveyou12',
        'administrator', 'welcome123', 'passw0rd123'];
    public const LOGIN_FAIL_LIMIT = 5;
    public const LOGIN_WINDOW = 900;
    /** with send-email every 2 minutes, a short mail-server outage is ridden out */
    public const MAX_EMAIL_ATTEMPTS = 5;
    private static ?string $dummyHash = null;

    public static function h(string $token): string
    {
        return hash('sha256', $token);
    }

    public static function validatePassword(string $pw, string $email = '', string $username = ''): ?string
    {
        $len = mb_strlen($pw, 'UTF-8');
        if ($len < 10) {
            return 'Use at least 10 characters.';
        }
        if ($len > 128) {
            return 'Use at most 128 characters.';
        }
        $low = mb_strtolower($pw, 'UTF-8');
        if (ctype_digit($pw) || in_array($low, self::COMMON_PASSWORDS, true)) {
            return 'That password is too easy to guess.';
        }
        if ($username !== '' && strlen($username) >= 4 && str_contains($low, mb_strtolower($username, 'UTF-8'))) {
            return 'The password should not contain your username.';
        }
        $local = explode('@', $email)[0] ?? '';
        if ($email !== '' && mb_strlen($local) >= 4 && str_contains($low, mb_strtolower($local, 'UTF-8'))) {
            return 'The password should not contain your email name.';
        }
        return null;
    }

    public static function queueEmail(Db $db, string $to, string $subject, string $body): void
    {
        $db->exec('INSERT INTO outbox(to_email, subject, body) VALUES (?,?,?)', [$to, $subject, $body]);
    }

    private static function newToken(Db $db, int $userId, string $purpose, int $lifetime): string
    {
        $raw = Util::tokenUrlsafe(32);
        $db->exec('INSERT INTO auth_tokens(user_id, purpose, token_hash, expires_at) VALUES (?,?,?,?)',
            [$userId, $purpose, self::h($raw), Util::futureIso($lifetime)]);
        return $raw;
    }

    public static function register(Db $db, ?string $email, ?string $username, ?string $displayName, ?string $password, string $ip, string $baseUrl): int
    {
        $email = trim((string) $email);
        $username = trim((string) $username);
        $displayName = trim((string) $displayName);
        $errors = [];
        if (!preg_match(self::EMAIL_RE, $email)) {
            $errors['email'] = 'Enter a valid email address.';
        }
        if (!preg_match(self::USERNAME_RE, $username)) {
            $errors['username'] = '3–30 characters: letters, numbers, underscore.';
        }
        $dl = mb_strlen($displayName, 'UTF-8');
        if ($dl < 1 || $dl > 80) {
            $errors['display_name'] = 'Enter a display name (up to 80 characters).';
        }
        $perr = self::validatePassword((string) $password, $email, $username);
        if ($perr) {
            $errors['password'] = $perr;
        }
        if ($errors) {
            throw new AccountError($errors);
        }
        if (!RateLimit::allow($db, "register:{$ip}", 10, 3600)) {
            throw new AccountError(['form' => 'Too many registrations from this network. Try again later.']);
        }
        if ($db->one('SELECT 1 FROM users WHERE email=?', [$email])) {
            $errors['email'] = 'An account with this email already exists.';
        }
        if ($db->one('SELECT 1 FROM users WHERE username=?', [$username])) {
            $errors['username'] = 'That username is taken.';
        }
        if ($errors) {
            throw new AccountError($errors);
        }
        $uid = $db->insert('INSERT INTO users(email, username, display_name, password_hash) VALUES (?,?,?,?)',
            [$email, $username, $displayName, Passwords::hash((string) $password)]);
        self::sendVerification($db, $uid, $email, $baseUrl);
        Audit::log($db, $uid, 'account.registered', 'user', $uid, null, $ip);
        return $uid;
    }

    public static function sendVerification(Db $db, int $userId, string $email, string $baseUrl): void
    {
        $raw = self::newToken($db, $userId, 'verify_email', 86400);
        self::queueEmail($db, $email, 'Verify your email address',
            "Open this link to verify your email address (valid 24 hours):\n{$baseUrl}/auth/verify/{$raw}\n\n"
            . 'If you did not register, ignore this message.');
    }

    public static function verifyEmail(Db $db, string $raw): bool
    {
        $row = $db->one("SELECT * FROM auth_tokens WHERE token_hash=? AND purpose='verify_email' AND used_at IS NULL AND expires_at>?",
            [self::h($raw), Util::nowIso()]);
        if (!$row) {
            return false;
        }
        $db->exec('UPDATE auth_tokens SET used_at=? WHERE id=?', [Util::nowIso(), $row['id']]);
        $db->exec('UPDATE users SET email_verified_at=?, updated_at=? WHERE id=? AND email_verified_at IS NULL',
            [Util::nowIso(), Util::nowIso(), $row['user_id']]);
        Audit::log($db, $row['user_id'], 'account.email_verified', 'user', $row['user_id']);
        return true;
    }

    public static function lockedOut(Db $db, string $identifier, string $ip): bool
    {
        return RateLimit::count($db, 'loginfail:id:' . mb_strtolower($identifier, 'UTF-8'), self::LOGIN_WINDOW) >= self::LOGIN_FAIL_LIMIT
            || RateLimit::count($db, "loginfail:ip:{$ip}", self::LOGIN_WINDOW) >= self::LOGIN_FAIL_LIMIT * 6;
    }

    /** Return user id, 'locked', or null. Failures are rate-limited; timing is equalised for unknown users. */
    public static function authenticate(Db $db, ?string $identifier, ?string $password, string $ip): int|string|null
    {
        $identifier = trim((string) $identifier);
        if ($identifier === '') {
            return null;
        }
        if (self::lockedOut($db, $identifier, $ip)) {
            return 'locked';
        }
        $row = $db->one('SELECT id, password_hash, is_active FROM users WHERE email=? OR username=?', [$identifier, $identifier]);
        self::$dummyHash ??= Passwords::hash('dummy-password-for-timing-equalisation');
        $ok = Passwords::verify($row ? $row['password_hash'] : self::$dummyHash, (string) $password);
        if ($row && $ok && $row['is_active']) {
            Audit::log($db, $row['id'], 'auth.login', 'user', $row['id'], null, $ip);
            return (int) $row['id'];
        }
        RateLimit::hit($db, 'loginfail:id:' . mb_strtolower($identifier, 'UTF-8'));
        RateLimit::hit($db, "loginfail:ip:{$ip}");
        Audit::log($db, null, 'auth.login_failed', 'user', null, ['identifier_hash' => substr(self::h(mb_strtolower($identifier, 'UTF-8')), 0, 16)], $ip);
        return null;
    }

    // ───────────── Sessions ─────────────
    public static function createSession(Db $db, int $userId, string $ip, ?string $userAgent, int $lifetime): string
    {
        $raw = Util::tokenUrlsafe(32);
        $db->exec('INSERT INTO user_sessions(token_hash, user_id, created_at, expires_at, ip, user_agent) VALUES (?,?,?,?,?,?)',
            [self::h($raw), $userId, Util::nowIso(), Util::futureIso($lifetime), $ip, substr((string) $userAgent, 0, 200)]);
        return $raw;
    }

    /** CurrentUser for a live session, else null (expired, revoked, deactivated). */
    public static function loadSession(Db $db, ?string $raw): ?CurrentUser
    {
        if (!$raw) {
            return null;
        }
        $r = $db->one('SELECT u.* FROM user_sessions s JOIN users u ON u.id=s.user_id '
            . 'WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.is_active=1', [self::h($raw), Util::nowIso()]);
        if (!$r) {
            return null;
        }
        return new CurrentUser((int) $r['id'], $r['email'], $r['username'], $r['display_name'], self::getRoles($db, (int) $r['id']),
            $r['email_verified_at'] !== null, $r['totp_enabled_at'] !== null);
    }

    public static function revokeSession(Db $db, string $raw): void
    {
        $db->exec('UPDATE user_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL', [Util::nowIso(), self::h($raw)]);
    }

    public static function revokeAllSessions(Db $db, int $userId, ?string $exceptRaw = null): void
    {
        $keep = $exceptRaw ? self::h($exceptRaw) : '';
        $db->exec('UPDATE user_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL AND token_hash<>?', [Util::nowIso(), $userId, $keep]);
    }

    // ───────────── Password reset / change ─────────────
    /** Always behaves identically to the caller (no account enumeration). */
    public static function requestReset(Db $db, ?string $email, string $ip, string $baseUrl): void
    {
        $email = trim((string) $email);
        if (!RateLimit::allow($db, "reset:{$ip}", 10, 3600)) {
            return;
        }
        $u = $db->one('SELECT id, email FROM users WHERE email=? AND is_active=1', [$email]);
        if ($u) {
            $raw = self::newToken($db, (int) $u['id'], 'reset_password', 3600);
            self::queueEmail($db, $u['email'], 'Reset your password',
                "Open this link to choose a new password (valid 1 hour):\n{$baseUrl}/auth/reset/{$raw}\n\n"
                . 'If you did not request this, ignore this message.');
            Audit::log($db, (int) $u['id'], 'account.reset_requested', 'user', $u['id'], null, $ip);
        }
    }

    public static function resetTokenValid(Db $db, string $raw): bool
    {
        return (bool) $db->one("SELECT 1 FROM auth_tokens WHERE token_hash=? AND purpose='reset_password' AND used_at IS NULL AND expires_at>?",
            [self::h($raw), Util::nowIso()]);
    }

    public static function resetPassword(Db $db, string $raw, ?string $new): int
    {
        $row = $db->one("SELECT t.*, u.email, u.username FROM auth_tokens t JOIN users u ON u.id=t.user_id "
            . "WHERE t.token_hash=? AND t.purpose='reset_password' AND t.used_at IS NULL AND t.expires_at>?", [self::h($raw), Util::nowIso()]);
        if (!$row) {
            throw new AccountError(['form' => 'This reset link is invalid or has expired.']);
        }
        $err = self::validatePassword((string) $new, $row['email'], $row['username']);
        if ($err) {
            throw new AccountError(['password' => $err]);
        }
        $db->exec('UPDATE auth_tokens SET used_at=? WHERE id=?', [Util::nowIso(), $row['id']]);
        $db->exec('UPDATE users SET password_hash=?, updated_at=? WHERE id=?', [Passwords::hash((string) $new), Util::nowIso(), $row['user_id']]);
        self::revokeAllSessions($db, (int) $row['user_id']);
        Audit::log($db, (int) $row['user_id'], 'account.password_reset', 'user', $row['user_id']);
        return (int) $row['user_id'];
    }

    public static function changePassword(Db $db, int $userId, ?string $current, ?string $new, ?string $keepSessionRaw = null): void
    {
        $u = $db->one('SELECT * FROM users WHERE id=?', [$userId]);
        if (!Passwords::verify($u['password_hash'], (string) $current)) {
            throw new AccountError(['current_password' => 'Current password is incorrect.']);
        }
        $err = self::validatePassword((string) $new, $u['email'], $u['username']);
        if ($err) {
            throw new AccountError(['new_password' => $err]);
        }
        $db->exec('UPDATE users SET password_hash=?, updated_at=? WHERE id=?', [Passwords::hash((string) $new), Util::nowIso(), $userId]);
        self::revokeAllSessions($db, $userId, $keepSessionRaw);
        Audit::log($db, $userId, 'account.password_changed', 'user', $userId);
    }

    // ───────────── Profile ─────────────
    public static function updateProfile(Db $db, int $userId, array $form): void
    {
        $dn = trim((string) ($form['display_name'] ?? ''));
        $dl = mb_strlen($dn, 'UTF-8');
        if ($dl < 1 || $dl > 80) {
            throw new AccountError(['display_name' => 'Enter a display name (up to 80 characters).']);
        }
        $pref = $form['attribution_pref'] ?? 'display_name';
        if (!in_array($pref, ['display_name', 'username', 'anonymous'], true)) {
            throw new AccountError(['attribution_pref' => 'Choose one of the listed options.']);
        }
        $db->exec('UPDATE users SET display_name=?, bio=?, languages=?, research_interests=?, attribution_pref=?, '
            . 'notify_submission_updates=?, notify_forum_replies=?, updated_at=? WHERE id=?',
            [$dn, mb_substr((string) ($form['bio'] ?? ''), 0, 1000), mb_substr((string) ($form['languages'] ?? ''), 0, 200),
                mb_substr((string) ($form['research_interests'] ?? ''), 0, 500), $pref,
                !empty($form['notify_submission_updates']) ? 1 : 0, !empty($form['notify_forum_replies']) ? 1 : 0, Util::nowIso(), $userId]);
    }

    // ───────────── Roles ─────────────
    public static function getRoles(Db $db, int $userId): array
    {
        return $db->col('SELECT role FROM user_roles WHERE user_id=? AND revoked_at IS NULL', [$userId]);
    }

    public static function activeAdminCount(Db $db): int
    {
        return (int) $db->val("SELECT COUNT(*) FROM user_roles r JOIN users u ON u.id=r.user_id "
            . "WHERE r.role='administrator' AND r.revoked_at IS NULL AND u.is_active=1");
    }

    public static function grantRole(Db $db, ?int $actorId, int $userId, string $role, ?string $ip = null): void
    {
        if (!in_array($role, Vocab::ROLES, true)) {
            throw new AccountError(['role' => 'Unknown role.']);
        }
        if (!$db->one('SELECT 1 FROM users WHERE id=? AND is_active=1', [$userId])) {
            throw new AccountError(['user' => 'User not found or inactive.']);
        }
        $db->exec('INSERT INTO user_roles(user_id, role, granted_by, granted_at) VALUES (?,?,?,?) '
            . 'ON CONFLICT(user_id, role) DO UPDATE SET revoked_at=NULL, revoked_by=NULL, granted_by=excluded.granted_by, '
            . 'granted_at=excluded.granted_at', [$userId, $role, $actorId, Util::nowIso()]);
        Audit::log($db, $actorId, 'role.granted', 'user', $userId, ['role' => $role], $ip);
    }

    public static function revokeRole(Db $db, ?int $actorId, int $userId, string $role, ?string $ip = null): void
    {
        if ($role === 'administrator' && self::activeAdminCount($db) <= 1
            && $db->one("SELECT 1 FROM user_roles WHERE user_id=? AND role='administrator' AND revoked_at IS NULL", [$userId])) {
            throw new AccountError(['role' => 'Cannot remove the last administrator.']);
        }
        $db->exec('UPDATE user_roles SET revoked_at=?, revoked_by=? WHERE user_id=? AND role=? AND revoked_at IS NULL',
            [Util::nowIso(), $actorId, $userId, $role]);
        Audit::log($db, $actorId, 'role.revoked', 'user', $userId, ['role' => $role], $ip);
    }

    // ───────────── Deactivation / anonymisation ─────────────
    public static function deactivate(Db $db, ?int $actorId, int $userId, ?string $ip = null): void
    {
        if (in_array('administrator', self::getRoles($db, $userId), true) && self::activeAdminCount($db) <= 1) {
            throw new AccountError(['user' => 'Cannot deactivate the last administrator.']);
        }
        $db->exec('UPDATE users SET is_active=0, deactivated_at=?, updated_at=? WHERE id=?', [Util::nowIso(), Util::nowIso(), $userId]);
        self::revokeAllSessions($db, $userId);
        Audit::log($db, $actorId, 'account.deactivated', 'user', $userId, null, $ip);
    }

    public static function reactivate(Db $db, ?int $actorId, int $userId, ?string $ip = null): void
    {
        $db->exec('UPDATE users SET is_active=1, deactivated_at=NULL, updated_at=? WHERE id=? AND anonymized_at IS NULL', [Util::nowIso(), $userId]);
        Audit::log($db, $actorId, 'account.reactivated', 'user', $userId, null, $ip);
    }

    /** Scrub personal data but keep the row, so attribution links and audit history stay intact. */
    public static function anonymize(Db $db, ?int $actorId, int $userId, ?string $ip = null): void
    {
        $u = $db->one('SELECT is_active FROM users WHERE id=?', [$userId]);
        if (!$u || $u['is_active']) {
            throw new AccountError(['user' => 'Deactivate the account before anonymising it.']);
        }
        $db->exec("UPDATE users SET email=?, username=?, display_name='Former contributor', bio=NULL, languages=NULL, "
            . "research_interests=NULL, password_hash=?, attribution_pref='anonymous', anonymized_at=?, updated_at=? WHERE id=?",
            ["anon-{$userId}@anonymized.invalid", "former_{$userId}", '!' . bin2hex(random_bytes(16)), Util::nowIso(), Util::nowIso(), $userId]);
        $db->exec('DELETE FROM auth_tokens WHERE user_id=?', [$userId]);
        Audit::log($db, $actorId, 'account.anonymized', 'user', $userId, null, $ip);
    }

    /**
     * Send queued email through a mailer (injected, so it is testable and optional).
     * A failed message is retried on later runs, up to MAX_EMAIL_ATTEMPTS; `error` keeps the latest failure.
     * @param callable(string $to, string $subject, string $body): void $send
     */
    public static function deliverOutbox(Db $db, callable $send, int $limit = 50): int
    {
        $sent = 0;
        foreach ($db->all('SELECT * FROM outbox WHERE sent_at IS NULL AND attempts < ? ORDER BY id LIMIT ?', [self::MAX_EMAIL_ATTEMPTS, $limit]) as $r) {
            try {
                $send($r['to_email'], $r['subject'], $r['body']);
                $db->exec('UPDATE outbox SET sent_at=?, attempts=attempts+1 WHERE id=?', [Util::nowIso(), $r['id']]);
                $sent++;
            } catch (\Throwable $exc) {   // recorded, never logged with the message body
                $db->exec('UPDATE outbox SET error=?, attempts=attempts+1 WHERE id=?', [(new \ReflectionClass($exc))->getShortName(), $r['id']]);
            }
        }
        return $sent;
    }
}
