<?php
declare(strict_types=1);

namespace Elf\Services;

/**
 * Password hashing. New hashes use PHP's maintained implementation (Argon2id where the server supports it, bcrypt
 * otherwise). Hashes written by the Python edition in Werkzeug's "pbkdf2:sha256:N$salt$hex" form are verified too.
 * Werkzeug's default "scrypt:" form cannot be checked with PHP's standard library, so those accounts use
 * "Forgot your password?" once (the reset stores a PHP hash).
 */
final class Passwords
{
    public static function hash(string $password): string
    {
        return defined('PASSWORD_ARGON2ID') ? password_hash($password, PASSWORD_ARGON2ID) : password_hash($password, PASSWORD_BCRYPT);
    }

    public static function verify(?string $hash, string $password): bool
    {
        $hash = (string) $hash;
        if (str_starts_with($hash, '$')) {
            return password_verify($password, $hash);
        }
        if (str_starts_with($hash, 'pbkdf2:')) {
            $parts = explode('$', $hash, 3);
            if (count($parts) !== 3) {
                return false;
            }
            [$method, $salt, $expected] = $parts;
            $m = explode(':', $method);
            $algo = $m[1] ?? 'sha256';
            $iterations = (int) ($m[2] ?? 600000);
            if (!in_array($algo, hash_hmac_algos(), true) || $iterations < 1) {
                return false;
            }
            return hash_equals($expected, hash_pbkdf2($algo, $password, $salt, $iterations, 0));
        }
        return false;
    }

    /** True for hashes this edition can verify; false means the account must reset its password once. */
    public static function supported(?string $hash): bool
    {
        $hash = (string) $hash;
        return str_starts_with($hash, '$') || str_starts_with($hash, 'pbkdf2:');
    }
}
