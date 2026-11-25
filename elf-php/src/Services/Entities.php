<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;

/**
 * Canonical entity registry: permanent ids, slugs (with redirect history), names, revisions, publication state.
 * Subtype data lives in per-kind tables; this class owns the shared part.
 */
final class Entities
{
    /** The ONE definition of "publicly visible". Every public query must use it. */
    public const PUBLIC_WHERE = "e.publication_status = 'published' AND e.visibility = 'public' "
        . 'AND e.deleted_at IS NULL AND e.merged_into IS NULL';

    public const KIND_TABLE = ['person' => 'people', 'family' => 'families', 'place' => 'places', 'event' => 'events',
        'organization' => 'organizations', 'source' => 'sources', 'archive_item' => 'archive_items',
        'collection' => 'collections', 'oral_history' => 'oral_histories'];
    public const TITLE_COL = ['person' => 'preferred_name', 'family' => 'display_name', 'place' => 'primary_name',
        'event' => 'title', 'organization' => 'name', 'source' => 'title', 'archive_item' => 'title',
        'collection' => 'title', 'oral_history' => 'title'];
    public const SUMMARY_COL = ['person' => 'summary', 'family' => 'summary', 'place' => 'overview', 'event' => 'summary',
        'organization' => 'description', 'source' => null, 'archive_item' => 'description',
        'collection' => 'description', 'oral_history' => 'summary'];
    public const ID_PREFIX = ['person' => 'per', 'family' => 'fam', 'place' => 'plc', 'event' => 'evt', 'organization' => 'org',
        'source' => 'src', 'archive_item' => 'itm', 'collection' => 'col', 'oral_history' => 'ora'];
    public const URL_SECTION = ['person' => 'people', 'family' => 'families', 'place' => 'places', 'event' => 'events',
        'source' => 'sources', 'archive_item' => 'archive', 'collection' => 'collections',
        'oral_history' => 'oral-histories', 'organization' => 'organizations'];
    private const ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789';

    /** PUBLIC_WHERE written against a different table alias. */
    public static function pub(string $alias): string
    {
        return str_replace('e.', $alias . '.', self::PUBLIC_WHERE);
    }

    public static function newPublicId(Db $db, string $kind): string
    {
        while (true) {
            $s = '';
            for ($i = 0; $i < 8; $i++) {
                $s .= self::ALPHABET[random_int(0, strlen(self::ALPHABET) - 1)];
            }
            $pid = self::ID_PREFIX[$kind] . '-' . $s;
            if (!$db->one('SELECT 1 FROM entities WHERE public_id=?', [$pid])) {
                return $pid;
            }
        }
    }

    public static function uniqueSlug(Db $db, string $kind, string $base, ?int $excludeId = null): string
    {
        $slug = $base;
        $n = 2;
        while (true) {
            $r = $db->one('SELECT id FROM entities WHERE kind=? AND slug=?', [$kind, $slug]);
            $h = $db->one('SELECT entity_id FROM entity_slug_history WHERE kind=? AND slug=?', [$kind, $slug]);
            $owner = $r['id'] ?? ($h['entity_id'] ?? null);
            if (!$owner || $owner === $excludeId) {
                return $slug;
            }
            $slug = "{$base}-{$n}";
            $n++;
        }
    }

    /** @return array{0:int,1:string,2:string} [id, public id, slug] */
    public static function create(Db $db, string $kind, string $title, ?int $createdBy = null, string $status = 'draft',
                                  string $visibility = 'private', bool $fictional = false): array
    {
        $pid = self::newPublicId($db, $kind);
        $slug = self::uniqueSlug($db, $kind, Names::slugify($title, $pid));
        $id = $db->insert('INSERT INTO entities(kind, public_id, slug, publication_status, visibility, is_fictional_test, created_by) '
            . 'VALUES (?,?,?,?,?,?,?)', [$kind, $pid, $slug, $status, $visibility, (int) $fictional, $createdBy]);
        return [$id, $pid, $slug];
    }

    public static function addName(Db $db, int $entityId, ?string $name, string $nameType, ?string $language = null, ?string $note = null): void
    {
        $name = trim((string) $name);
        if ($name === '') {
            return;
        }
        $db->exec('INSERT OR IGNORE INTO entity_names(entity_id, name, normalized, name_type, language, note) VALUES (?,?,?,?,?,?)',
            [$entityId, $name, Names::normalize($name), $nameType, $language, $note]);
    }

    public static function changeSlug(Db $db, int $entityId, string $newSlug, ?int $actorId = null): string
    {
        $e = self::get($db, $entityId);
        $newSlug = self::uniqueSlug($db, $e['kind'], Names::slugify($newSlug, $e['public_id']), $entityId);
        if ($newSlug === $e['slug']) {
            return $newSlug;
        }
        $db->exec('INSERT OR REPLACE INTO entity_slug_history(kind, slug, entity_id) VALUES (?,?,?)', [$e['kind'], $e['slug'], $entityId]);
        $db->exec('DELETE FROM entity_slug_history WHERE kind=? AND slug=?', [$e['kind'], $newSlug]);
        $db->exec('UPDATE entities SET slug=?, updated_at=? WHERE id=?', [$newSlug, Util::nowIso(), $entityId]);
        Audit::log($db, $actorId, 'entity.slug_changed', 'entity', $e['public_id'], ['from' => $e['slug'], 'to' => $newSlug]);
        return $newSlug;
    }

    public static function get(Db $db, ?int $entityId): ?array
    {
        return $entityId === null ? null : $db->one('SELECT * FROM entities WHERE id=?', [$entityId]);
    }

    public static function getByPublicId(Db $db, ?string $publicId): ?array
    {
        return $publicId ? $db->one('SELECT * FROM entities WHERE public_id=?', [$publicId]) : null;
    }

    public static function getPublicByPublicId(Db $db, ?string $publicId, ?string $kind = null): ?array
    {
        if (!$publicId) {
            return null;
        }
        $q = 'SELECT e.* FROM entities e WHERE e.public_id=? AND ' . self::PUBLIC_WHERE;
        $args = [$publicId];
        if ($kind) {
            $q .= ' AND e.kind=?';
            $args[] = $kind;
        }
        return $db->one($q, $args);
    }

    public static function titleOf(Db $db, ?int $entityId): ?string
    {
        $e = self::get($db, $entityId);
        if (!$e) {
            return null;
        }
        return $db->val('SELECT ' . self::TITLE_COL[$e['kind']] . ' FROM ' . self::KIND_TABLE[$e['kind']] . ' WHERE entity_id=?', [$entityId]);
    }

    public static function subtypeRow(Db $db, int $entityId): ?array
    {
        $e = self::get($db, $entityId);
        return $db->one('SELECT * FROM ' . self::KIND_TABLE[$e['kind']] . ' WHERE entity_id=?', [$entityId]);
    }

    /**
     * ['ok', entity] | ['redirect', entity] | null. Non-public records resolve to null (-> 404), so the existence
     * of private records is never revealed.
     */
    public static function resolvePublic(Db $db, string $kind, string $slug): ?array
    {
        $row = $db->one('SELECT e.* FROM entities e WHERE e.kind=? AND e.slug=? AND ' . self::PUBLIC_WHERE, [$kind, $slug]);
        if ($row) {
            return ['ok', $row];
        }
        $raw = $db->one('SELECT * FROM entities WHERE kind=? AND slug=?', [$kind, $slug]);
        if ($raw === null) {
            $h = $db->one('SELECT entity_id FROM entity_slug_history WHERE kind=? AND slug=?', [$kind, $slug]);
            $raw = $h ? self::get($db, $h['entity_id']) : null;
        }
        $seen = [];
        while ($raw !== null && $raw['merged_into'] && !isset($seen[$raw['id']])) {    // follow merge tombstones
            $seen[$raw['id']] = true;
            $raw = self::get($db, $raw['merged_into']);
        }
        if ($raw !== null) {
            $pub = $db->one('SELECT e.* FROM entities e WHERE e.id=? AND ' . self::PUBLIC_WHERE, [$raw['id']]);
            if ($pub && $pub['kind'] === $kind && $pub['slug'] !== $slug) {
                return ['redirect', $pub];
            }
        }
        return null;
    }

    // ───────────── Revisions ─────────────
    public static function snapshot(Db $db, int $entityId): array
    {
        $e = self::get($db, $entityId);
        $sub = self::subtypeRow($db, $entityId);
        $names = $db->all('SELECT name, name_type, language FROM entity_names WHERE entity_id=? ORDER BY id', [$entityId]);
        return ['entity' => $e, 'data' => $sub ?: null, 'names' => $names];
    }

    public static function latestRevisionNumber(Db $db, int $entityId): int
    {
        return (int) ($db->val('SELECT MAX(revision_number) FROM revisions WHERE entity_id=?', [$entityId]) ?? 0);
    }

    public static function addRevision(Db $db, int $entityId, ?int $actorId, string $summary, ?string $reason = null, ?int $submissionId = null): int
    {
        $n = self::latestRevisionNumber($db, $entityId) + 1;
        $db->exec('INSERT INTO revisions(entity_id, revision_number, snapshot_json, change_summary, reason, actor_id, submission_id, created_at) '
            . 'VALUES (?,?,?,?,?,?,?,?)',
            [$entityId, $n, Util::json(self::snapshot($db, $entityId)), $summary, $reason, $actorId, $submissionId, Util::nowIso()]);
        return $n;
    }

    /** Change publication state/visibility with revision + audit + search-index maintenance. */
    public static function setState(Db $db, int $entityId, ?string $status = null, ?string $visibility = null, ?int $actorId = null, ?string $reason = null): void
    {
        $e = self::get($db, $entityId);
        $status = $status ?: $e['publication_status'];
        $visibility = $visibility ?: $e['visibility'];
        $db->exec('UPDATE entities SET publication_status=?, visibility=?, updated_at=? WHERE id=?', [$status, $visibility, Util::nowIso(), $entityId]);
        self::addRevision($db, $entityId, $actorId, "State changed: {$e['publication_status']}/{$e['visibility']} → {$status}/{$visibility}", $reason);
        Audit::log($db, $actorId, 'entity.state_changed', 'entity', $e['public_id'],
            ['from' => [$e['publication_status'], $e['visibility']], 'to' => [$status, $visibility], 'reason' => $reason]);
        Search::reindex($db, $entityId);
    }
}
