<?php
declare(strict_types=1);

namespace Elf\Services;
use Elf\Db;

final class RateLimit
{
    public static function count(Db $db, string $bucket, int $window): int
    {
        return (int) $db->val('SELECT COUNT(*) FROM rate_events WHERE bucket=? AND at>?', [$bucket, time() - $window]);
    }

    public static function hit(Db $db, string $bucket): void
    {
        $db->exec('INSERT INTO rate_events(bucket, at) VALUES (?,?)', [$bucket, time()]);
    }

    /** Record an attempt; false when the bucket is already at its limit. */
    public static function allow(Db $db, string $bucket, int $limit, int $window): bool
    {
        if (self::count($db, $bucket, $window) >= $limit) {
            return false;
        }
        self::hit($db, $bucket);
        return true;
    }

    public static function prune(Db $db, int $olderThan = 86400): void
    {
        $db->exec('DELETE FROM rate_events WHERE at<?', [time() - $olderThan]);
    }
}
