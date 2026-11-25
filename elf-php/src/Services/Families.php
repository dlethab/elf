<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;

/** Family-representative grants: scoped to one family, individually revocable, never a global role. */
final class Families
{
    public static function activeGrant(Db $db, int $userId, int $familyEntityId): ?array
    {
        return $db->one('SELECT * FROM family_representatives WHERE user_id=? AND family_id=? AND revoked_at IS NULL', [$userId, $familyEntityId]);
    }

    public static function listForFamily(Db $db, int $familyEntityId): array
    {
        return $db->all('SELECT fr.*, u.username, u.display_name FROM family_representatives fr JOIN users u ON u.id=fr.user_id '
            . 'WHERE fr.family_id=? AND fr.revoked_at IS NULL ORDER BY fr.granted_at', [$familyEntityId]);
    }

    public static function familiesForUser(Db $db, int $userId): array
    {
        return $db->all('SELECT e.id, e.public_id, e.slug, f.display_name, fr.can_propose_tree, fr.can_suggest_edits, fr.can_submit_media '
            . 'FROM family_representatives fr JOIN entities e ON e.id=fr.family_id JOIN families f ON f.entity_id=e.id '
            . 'WHERE fr.user_id=? AND fr.revoked_at IS NULL AND e.deleted_at IS NULL', [$userId]);
    }

    public static function grant(Db $db, ?int $actorId, ?string $username, int $familyEntityId, bool $suggestEdits = true,
                                 bool $proposeTree = true, bool $submitMedia = false): int
    {
        $u = $db->one('SELECT id FROM users WHERE username=? AND is_active=1', [trim((string) $username)]);
        if (!$u) {
            throw new \InvalidArgumentException('No active user with that username.');
        }
        $fam = Entities::get($db, $familyEntityId);
        if (!$fam || $fam['kind'] !== 'family') {
            throw new \InvalidArgumentException('Family not found.');
        }
        if (self::activeGrant($db, (int) $u['id'], $familyEntityId)) {
            throw new \InvalidArgumentException('This user is already a representative of this family.');
        }
        $db->exec('INSERT INTO family_representatives(user_id, family_id, can_suggest_edits, can_propose_tree, can_submit_media, granted_by) '
            . 'VALUES (?,?,?,?,?,?)', [$u['id'], $familyEntityId, (int) $suggestEdits, (int) $proposeTree, (int) $submitMedia, $actorId]);
        Audit::log($db, $actorId, 'family_rep.granted', 'family', $fam['public_id'], ['user_id' => (int) $u['id']]);
        return (int) $u['id'];
    }

    public static function revoke(Db $db, ?int $actorId, int $grantId): void
    {
        $g = $db->one('SELECT * FROM family_representatives WHERE id=? AND revoked_at IS NULL', [$grantId]);
        if (!$g) {
            throw new \InvalidArgumentException('Grant not found.');
        }
        $db->exec('UPDATE family_representatives SET revoked_at=?, revoked_by=? WHERE id=?', [Util::nowIso(), $actorId, $grantId]);
        Audit::log($db, $actorId, 'family_rep.revoked', 'family', $g['family_id'], ['user_id' => (int) $g['user_id']]);
    }
}
