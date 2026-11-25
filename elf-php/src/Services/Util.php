<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;

/** Small shared helpers: UTC timestamps, the audit trail, rate limits, random tokens. */
final class Util
{
    public const FMT = 'Y-m-d\TH:i:s\Z';

    public static function nowIso(): string
    {
        return gmdate(self::FMT);
    }

    public static function futureIso(int $seconds): string
    {
        return gmdate(self::FMT, time() + $seconds);
    }

    /** URL-safe random text, like Python's secrets.token_urlsafe(n) (n random bytes). */
    public static function tokenUrlsafe(int $n = 32): string
    {
        return rtrim(strtr(base64_encode(random_bytes($n)), '+/', '-_'), '=');
    }

    public static function json(mixed $v, bool $sortKeys = false): string
    {
        if ($sortKeys) {
            $v = self::sortKeys($v);
        }
        return json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION | JSON_INVALID_UTF8_SUBSTITUTE);
    }

    public static function sortKeys(mixed $v): mixed
    {
        if (is_array($v)) {
            if (!array_is_list($v)) {
                ksort($v, SORT_STRING);
            }
            foreach ($v as $k => $x) {
                $v[$k] = self::sortKeys($x);
            }
        }
        return $v;
    }

    /** Python str.split() semantics: split on runs of whitespace, no empty pieces. */
    public static function words(?string $s): array
    {
        $s = trim((string) $s);
        return $s === '' ? [] : preg_split('/\s+/u', $s);
    }

    /** " ".join(s.split()) */
    public static function squash(?string $s): string
    {
        return implode(' ', self::words($s));
    }

    public static function strlen(?string $s): int
    {
        return mb_strlen((string) $s, 'UTF-8');
    }

    public static function substr(?string $s, int $start, ?int $len = null): string
    {
        return mb_substr((string) $s, $start, $len, 'UTF-8');
    }
}
