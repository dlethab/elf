<?php
declare(strict_types=1);

namespace Elf\Services;
use Elf\Db;

final class Audit
{
    /** Append to the audit trail. Never pass secrets in `detail`. */
    public static function log(Db $db, ?int $actorId, string $action, ?string $targetType = null, mixed $targetId = null,
                               mixed $detail = null, ?string $ip = null): void
    {
        $db->exec(
            'INSERT INTO audit_logs(actor_id, action, target_type, target_id, detail_json, ip, created_at) VALUES (?,?,?,?,?,?,?)',
            [$actorId, $action, $targetType, $targetId === null ? null : (string) $targetId,
                $detail !== null ? Util::json($detail, true) : null, $ip, Util::nowIso()]
        );
    }
}
