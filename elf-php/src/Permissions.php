<?php
declare(strict_types=1);

namespace Elf;

/**
 * Central permission matrix. Every server-side check goes through `can()`.
 *
 * Roles are additive. 'contributor' is implicit for any active account. Family-representative
 * power is NOT a role: it is a scoped, revocable grant (see Services\Families).
 * Moderators deliberately receive no archival-review permissions (least privilege).
 */
final class Permissions
{
    public const CONTRIBUTOR = [
        'submission.create', 'submission.view_own', 'submission.edit_own',
        'submission.withdraw_own', 'profile.edit_own',
    ];
    public const EDITOR = [
        'queue.view', 'submission.review', 'submission.request_revision', 'submission.decide',
        'submission.publish', 'record.view_any', 'record.restrict', 'duplicates.view',
        'confidential.view', 'messages.view', 'family_rep.manage', 'record.edit', 'citation.manage',
        'record.merge', 'import.run', 'restricted.view',
    ];
    /** Researchers are vetted by administrators. They can VIEW material marked for research access
     *  (restricted records and media), and every such view is logged. They cannot edit or publish. */
    public const RESEARCHER = ['restricted.view'];
    public const MODERATOR = ['reports.view', 'forum.moderate'];
    public const ADMIN_EXTRA = ['users.manage', 'roles.assign', 'audit.view', 'admin.overview', 'settings.manage'];

    public static function forRole(string $role): array
    {
        return match ($role) {
            Vocab::BASE_ROLE => self::CONTRIBUTOR,
            'editor' => self::EDITOR,
            'moderator' => self::MODERATOR,
            'administrator' => array_merge(self::EDITOR, self::MODERATOR, self::ADMIN_EXTRA),
            'researcher' => self::RESEARCHER,
            default => [],
        };
    }

    /** @return array<string,true> */
    public static function permissionsFor(iterable $roles): array
    {
        $perms = array_fill_keys(self::CONTRIBUTOR, true);
        foreach ($roles as $r) {
            foreach (self::forRole($r) as $p) {
                $perms[$p] = true;
            }
        }
        return $perms;
    }

    public static function can(iterable $roles, string $permission): bool
    {
        return isset(self::permissionsFor($roles)[$permission]);
    }
}
