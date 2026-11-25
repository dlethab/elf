<?php
declare(strict_types=1);

namespace Elf\Services;

use chillerlan\QRCode\QRCode;
use chillerlan\QRCode\QROptions;
use Elf\Db;

/**
 * Two-step sign-in with an authenticator app (TOTP, RFC 6238: HMAC-SHA1, 6 digits, 30-second steps), plus single-use
 * recovery codes. The algorithm is the published standard, built from PHP's hash_hmac; nothing here invents
 * cryptography. A code is accepted at most once (replay protection). Secrets are compatible with the Python edition.
 */
final class Mfa
{
    public const STEP = 30;
    public const DIGITS = 6;
    public const WINDOW = 1;          // accept the previous/next step to allow for clock drift
    private const B32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

    public static function base32Encode(string $bytes): string
    {
        $bits = '';
        foreach (str_split($bytes) as $c) {
            $bits .= str_pad(decbin(ord($c)), 8, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 5) as $chunk) {
            $out .= self::B32[bindec(str_pad($chunk, 5, '0'))];
        }
        return $out;            // without '=' padding, as the Python edition stores it
    }

    public static function base32Decode(string $s): string
    {
        $s = strtoupper(rtrim($s, '='));
        $bits = '';
        foreach (str_split($s) as $c) {
            $i = strpos(self::B32, $c);
            if ($i === false) {
                throw new \InvalidArgumentException('not base32');
            }
            $bits .= str_pad(decbin($i), 5, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 8) as $byte) {
            if (strlen($byte) === 8) {
                $out .= chr(bindec($byte));
            }
        }
        return $out;
    }

    public static function newSecret(): string
    {
        return self::base32Encode(random_bytes(20));
    }

    private static function code(string $secret, int $counter): string
    {
        $key = self::base32Decode($secret);
        $digest = hash_hmac('sha1', pack('J', $counter), $key, true);
        $o = ord($digest[19]) & 0x0F;
        $v = unpack('N', substr($digest, $o, 4))[1] & 0x7FFFFFFF;
        return str_pad((string) ($v % (10 ** self::DIGITS)), self::DIGITS, '0', STR_PAD_LEFT);
    }

    public static function codeAt(string $secret, ?int $t = null): string
    {
        return self::code($secret, intdiv($t ?? time(), self::STEP));
    }

    public static function matchingStep(string $secret, ?string $code, ?int $t = null): ?int
    {
        $code = preg_replace('/\D/', '', (string) $code);
        if (strlen($code) !== self::DIGITS) {
            return null;
        }
        $now = intdiv($t ?? time(), self::STEP);
        for ($step = $now - self::WINDOW; $step <= $now + self::WINDOW; $step++) {
            if (hash_equals(self::code($secret, $step), $code)) {
                return $step;
            }
        }
        return null;
    }

    public static function otpauthUri(string $secret, string $account, string $issuer = 'ELF Archive'): string
    {
        return 'otpauth://totp/' . rawurlencode($issuer) . ':' . rawurlencode($account) . "?secret={$secret}&issuer="
            . rawurlencode($issuer) . '&digits=' . self::DIGITS . '&period=' . self::STEP;
    }

    /** An SVG QR code as a data: address (drawn here; nothing is sent elsewhere). */
    public static function qrSvgDataUri(string $text): string
    {
        $opts = new QROptions(['outputBase64' => true, 'quietzoneSize' => 2]);
        return (new QRCode($opts))->render($text);
    }

    private static function hashCode(string $code): string
    {
        return hash('sha256', strtolower(trim(str_replace('-', '', $code))));
    }

    /** @return array{0:string[],1:string} codes, and their stored (hashed) form */
    public static function newRecoveryCodes(int $n = 10): array
    {
        $codes = [];
        for ($i = 0; $i < $n; $i++) {
            $codes[] = bin2hex(random_bytes(3)) . '-' . bin2hex(random_bytes(3));
        }
        return [$codes, json_encode(array_map([self::class, 'hashCode'], $codes))];
    }

    /** Confirm the first code from the app, then switch two-step sign-in on. Returns recovery codes. */
    public static function enable(Db $db, int $userId, string $secret, ?string $code): ?array
    {
        $step = self::matchingStep($secret, $code);
        if ($step === null) {
            return null;
        }
        [$codes, $stored] = self::newRecoveryCodes();
        $db->exec('UPDATE users SET totp_secret=?, totp_enabled_at=?, totp_last_step=?, recovery_codes=?, updated_at=? WHERE id=?',
            [$secret, Util::nowIso(), $step, $stored, Util::nowIso(), $userId]);
        Audit::log($db, $userId, 'auth.mfa_enabled', 'user', $userId);
        return $codes;
    }

    public static function disable(Db $db, int $userId, ?int $actorId = null): void
    {
        $db->exec('UPDATE users SET totp_secret=NULL, totp_enabled_at=NULL, totp_last_step=NULL, recovery_codes=NULL, updated_at=? WHERE id=?',
            [Util::nowIso(), $userId]);
        Audit::log($db, $actorId ?? $userId, 'auth.mfa_disabled', 'user', $userId);
    }

    public static function regenerateCodes(Db $db, int $userId): array
    {
        [$codes, $stored] = self::newRecoveryCodes();
        $db->exec('UPDATE users SET recovery_codes=? WHERE id=?', [$stored, $userId]);
        Audit::log($db, $userId, 'auth.mfa_codes_regenerated', 'user', $userId);
        return $codes;
    }

    /** true if `code` is a fresh authenticator code or an unused recovery code; 'locked' after too many tries. */
    public static function verify(Db $db, int $userId, ?string $code, ?string $ip = null): bool|string
    {
        if (!RateLimit::allow($db, "mfa:{$userId}", 6, 900)) {
            return 'locked';
        }
        $u = $db->one('SELECT totp_secret, totp_last_step, recovery_codes FROM users WHERE id=? AND is_active=1', [$userId]);
        if (!$u || !$u['totp_secret']) {
            return false;
        }
        $step = self::matchingStep($u['totp_secret'], $code);
        if ($step !== null && $step > ($u['totp_last_step'] ?? -1)) {
            $db->exec('UPDATE users SET totp_last_step=? WHERE id=?', [$step, $userId]);
            Audit::log($db, $userId, 'auth.mfa_ok', 'user', $userId, null, $ip);
            return true;
        }
        $hashes = json_decode((string) ($u['recovery_codes'] ?: '[]'), true) ?: [];
        $h = self::hashCode((string) $code);
        foreach ($hashes as $i => $x) {
            if (hash_equals((string) $x, $h)) {
                unset($hashes[$i]);
                $hashes = array_values($hashes);
                $db->exec('UPDATE users SET recovery_codes=? WHERE id=?', [json_encode($hashes), $userId]);
                Audit::log($db, $userId, 'auth.mfa_recovery_code_used', 'user', $userId, ['remaining' => count($hashes)], $ip);
                return true;
            }
        }
        Audit::log($db, $userId, 'auth.mfa_failed', 'user', $userId, null, $ip);
        return false;
    }

    public static function remainingCodes(Db $db, int $userId): int
    {
        $r = $db->one('SELECT recovery_codes FROM users WHERE id=?', [$userId]);
        return $r ? count(json_decode((string) ($r['recovery_codes'] ?: '[]'), true) ?: []) : 0;
    }
}
