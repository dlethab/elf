<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Merging duplicate records.
 *
 * A merge is always an editor's decision with a recorded reason; similarity scores only suggest candidates. The
 * record that is kept ("canonical") keeps its permanent id and address. The retired record is NOT deleted: it becomes
 * a tombstone pointing at the canonical record, so its old address and permanent id keep working (they redirect).
 * Every name, citation, account, link and photo is moved to the canonical record in one transaction; links that would
 * become duplicates or self-links are dropped and listed in the merge log. Both records get a revision, and the full
 * before-state of the retired record stays in its (append-only) revision history.
 */
final class Merging
{
    public const MERGEABLE = ['person', 'family', 'place', 'event', 'organization', 'source'];
    /** (table, column) pairs that can point at an entity. */
    private const SIMPLE_REFS = [
        ['citations', 'target_id'], ['citations', 'source_id'], ['conflicting_accounts', 'entity_id'],
        ['conflicting_accounts', 'source_id'], ['people', 'birth_place_id'], ['people', 'death_place_id'],
        ['affiliations', 'person_id'], ['affiliations', 'organization_id'], ['affiliations', 'place_id'],
        ['place_alt_locations', 'place_id'], ['oral_histories', 'interviewee_id'], ['media_files', 'owner_id'],
        ['submissions', 'family_scope_id'],
    ];
    /** Link tables with a uniqueness rule: if the canonical record already has the same link, the retired copy is dropped (and logged). */
    private const UNIQUE_LINKS = [
        ['family_memberships', 'family_id', 'person_id'], ['family_memberships', 'person_id', 'family_id'],
        ['event_places', 'event_id', 'place_id'], ['event_places', 'place_id', 'event_id'],
        ['event_participants', 'event_id', 'person_id'], ['event_participants', 'event_id', 'organization_id'],
        ['event_participants', 'person_id', 'event_id'], ['event_participants', 'organization_id', 'event_id'],
        ['archive_item_subjects', 'subject_id', 'item_id'],
        ['collection_items', 'collection_id', 'item_id'],
    ];

    private static function check(Db $db, ?string $keepPid, ?string $retirePid): array
    {
        $keep = Entities::getByPublicId($db, $keepPid ?: '');
        $retire = Entities::getByPublicId($db, $retirePid ?: '');
        if (!$keep || !$retire) {
            throw new MergeError('Both records must exist.');
        }
        if ($keep['id'] === $retire['id']) {
            throw new MergeError('Choose two different records.');
        }
        if ($keep['kind'] !== $retire['kind'] || !in_array($keep['kind'], self::MERGEABLE, true)) {
            throw new MergeError('Only two records of the same kind can be merged.');
        }
        foreach ([$keep, $retire] as $e) {
            if ($e['merged_into'] || $e['deleted_at']) {
                throw new MergeError('One of these records has already been merged or removed.');
            }
        }
        return [$keep, $retire];
    }

    /** What a merge would move: counts per kind of link (shown on the preview page). */
    public static function impact(Db $db, ?string $keepPid, ?string $retirePid): array
    {
        [$keep, $retire] = self::check($db, $keepPid, $retirePid);
        $rid = $retire['id'];
        $out = [];
        foreach (self::SIMPLE_REFS as [$table, $col]) {
            $n = (int) $db->val("SELECT COUNT(*) FROM {$table} WHERE {$col}=?", [$rid]);
            if ($n) {
                $out["{$table}.{$col}"] = $n;
            }
        }
        foreach (self::UNIQUE_LINKS as [$table, $col]) {
            $n = (int) $db->val("SELECT COUNT(*) FROM {$table} WHERE {$col}=?", [$rid]);
            if ($n) {
                $out["{$table}.{$col}"] = $n;
            }
        }
        $n = (int) $db->val('SELECT COUNT(*) FROM relationships WHERE person_a_id=? OR person_b_id=?', [$rid, $rid]);
        if ($n) {
            $out['relationships'] = $n;
        }
        $out['names'] = (int) $db->val('SELECT COUNT(*) FROM entity_names WHERE entity_id=?', [$rid]);
        $pending = (int) $db->val("SELECT COUNT(*) FROM submissions WHERE target_entity_id=? AND status IN "
            . "('draft','submitted','under_review','needs_revision','approved')", [$rid]);
        if ($pending) {
            $out['pending corrections'] = $pending;
        }
        return [$keep, $retire, $out];
    }

    /** Copy values the kept record lacks from the retired one (dates as a whole group). Returns fields filled. */
    private static function fillGaps(Db $db, array $keep, array $retire): array
    {
        $table = Entities::KIND_TABLE[$keep['kind']];
        $k = Entities::subtypeRow($db, (int) $keep['id']);
        $r = Entities::subtypeRow($db, (int) $retire['id']);
        $cols = [];
        $filled = [];
        $prefixes = [];
        foreach (array_keys($k) as $c) {
            if (str_ends_with($c, '_precision') && $c !== 'coord_precision') {
                $prefixes[] = substr($c, 0, -strlen('_precision'));
            }
        }
        foreach ($prefixes as $p) {
            if ($k["{$p}_precision"] === 'unknown' && $r["{$p}_precision"] !== 'unknown') {
                foreach (['start', 'end', 'precision', 'note'] as $s) {
                    $cols["{$p}_{$s}"] = $r["{$p}_{$s}"];
                }
                $filled[] = $p;
            }
        }
        $skip = ['entity_id' => 1, 'kind' => 1, 'latitude' => 1, 'longitude' => 1, 'coord_precision' => 1];
        foreach ($prefixes as $p) {
            foreach (['start', 'end', 'precision', 'note'] as $s) {
                $skip["{$p}_{$s}"] = 1;
            }
        }
        if (array_key_exists('latitude', $k) && $k['latitude'] === null && $r['latitude'] !== null) {   // coordinates move as a set
            $cols += ['latitude' => $r['latitude'], 'longitude' => $r['longitude'], 'coord_precision' => $r['coord_precision']];
            $filled[] = 'coordinates';
        }
        foreach (array_keys($k) as $c) {
            if (isset($skip[$c]) || str_ends_with($c, '_kind')) {
                continue;
            }
            if (in_array($k[$c], [null, ''], true) && !in_array($r[$c], [null, ''], true)) {
                if ($c === 'living_status') {
                    continue;
                }
                $cols[$c] = $r[$c];
                $filled[] = $c;
            }
        }
        if ($keep['kind'] === 'person' && $k['living_status'] === 'unknown' && $r['living_status'] !== 'unknown') {
            $cols['living_status'] = $r['living_status'];
            $filled[] = 'living_status';
        }
        if ($cols) {
            $db->exec("UPDATE {$table} SET " . implode(', ', array_map(fn ($c) => "{$c}=?", array_keys($cols))) . ' WHERE entity_id=?',
                [...array_values($cols), $keep['id']]);
        }
        return $filled;
    }

    public static function merge(Db $db, CurrentUser $editor, ?string $keepPid, ?string $retirePid, ?string $reason, bool $fillGaps = true): array
    {
        $reason = mb_substr(Util::squash($reason), 0, 1000);
        if ($reason === '') {
            throw new MergeError('Please record why these are the same. The reason is kept with the merge.');
        }
        return $db->tx(function () use ($db, $editor, $keepPid, $retirePid, $reason, $fillGaps) {
            [$keep, $retire] = self::check($db, $keepPid, $retirePid);
            $kid = (int) $keep['id'];
            $rid = (int) $retire['id'];
            $log = ['dropped' => [], 'moved' => []];
            // names: everything the retired record was called stays searchable on the kept one
            foreach ($db->all('SELECT * FROM entity_names WHERE entity_id=?', [$rid]) as $n) {
                $ntype = $n['name_type'] === 'preferred' ? 'alternate_spelling' : $n['name_type'];
                Entities::addName($db, $kid, $n['name'], $ntype, $n['language'], $n['note']);
            }
            foreach (self::SIMPLE_REFS as [$table, $col]) {
                $n = $db->exec("UPDATE {$table} SET {$col}=? WHERE {$col}=?", [$kid, $rid]);
                if ($n) {
                    $log['moved']["{$table}.{$col}"] = $n;
                }
            }
            foreach (self::UNIQUE_LINKS as [$table, $col, $other]) {
                foreach ($db->all("SELECT rowid AS rid_, * FROM {$table} WHERE {$col}=?", [$rid]) as $row) {
                    if ($row[$other] === null) {
                        continue;
                    }
                    $clash = $db->one("SELECT 1 FROM {$table} WHERE {$col}=? AND {$other}=?", [$kid, $row[$other]]);
                    if ($clash || $row[$other] === $kid) {
                        $db->exec("DELETE FROM {$table} WHERE rowid=?", [$row['rid_']]);
                        $copy = $row;
                        unset($copy['rid_']);
                        $log['dropped'][] = ['table' => $table, 'row' => $copy];
                    } else {
                        $db->exec("UPDATE {$table} SET {$col}=? WHERE rowid=?", [$kid, $row['rid_']]);
                        $log['moved']["{$table}.{$col}"] = ($log['moved']["{$table}.{$col}"] ?? 0) + 1;
                    }
                }
            }
            foreach ($db->all('SELECT * FROM relationships WHERE person_a_id=? OR person_b_id=?', [$rid, $rid]) as $r) {
                $a = $r['person_a_id'] === $rid ? $kid : (int) $r['person_a_id'];
                $b = $r['person_b_id'] === $rid ? $kid : (int) $r['person_b_id'];
                if (!in_array($r['relationship_type'], Vocab::DIRECTED_RELATIONSHIPS, true) && $a > $b) {
                    [$a, $b] = [$b, $a];
                }
                $clash = $db->one('SELECT 1 FROM relationships WHERE person_a_id=? AND person_b_id=? AND relationship_type=? AND id<>?',
                    [$a, $b, $r['relationship_type'], $r['id']]);
                if ($a === $b || $clash) {
                    $db->exec('DELETE FROM relationships WHERE id=?', [$r['id']]);
                    $log['dropped'][] = ['table' => 'relationships', 'row' => $r];
                } else {
                    $db->exec('UPDATE relationships SET person_a_id=?, person_b_id=? WHERE id=?', [$a, $b, $r['id']]);
                    $log['moved']['relationships'] = ($log['moved']['relationships'] ?? 0) + 1;
                }
            }
            // family representatives of a retired family now represent the kept one (one active grant each)
            foreach ($db->all('SELECT * FROM family_representatives WHERE family_id=? AND revoked_at IS NULL', [$rid]) as $gr) {
                if ($db->one('SELECT 1 FROM family_representatives WHERE family_id=? AND user_id=? AND revoked_at IS NULL', [$kid, $gr['user_id']])) {
                    $db->exec('UPDATE family_representatives SET revoked_at=?, revoked_by=? WHERE id=?', [Util::nowIso(), $editor->id, $gr['id']]);
                } else {
                    $db->exec('UPDATE family_representatives SET family_id=? WHERE id=?', [$kid, $gr['id']]);
                }
            }
            // pending corrections now apply to the kept record; editors are told why
            foreach ($db->all("SELECT id, editor_notes FROM submissions WHERE target_entity_id=? AND status IN "
                . "('draft','submitted','under_review','needs_revision','approved')", [$rid]) as $s) {
                $note = '[' . Util::nowIso() . " {$editor->username}] Target {$retire['public_id']} was merged into {$keep['public_id']}; "
                    . 'check the proposed changes against the kept record.';
                $db->exec('UPDATE submissions SET target_entity_id=?, editor_notes=? WHERE id=?', [$kid, trim(((string) $s['editor_notes']) . "\n" . $note), $s['id']]);
            }
            $filled = $fillGaps ? self::fillGaps($db, $keep, $retire) : [];
            $log['filled'] = $filled;
            $db->exec('UPDATE entities SET merged_into=?, updated_at=? WHERE id=?', [$kid, Util::nowIso(), $rid]);
            $db->exec('UPDATE entities SET updated_at=? WHERE id=?', [Util::nowIso(), $kid]);
            $db->exec('INSERT INTO merges(canonical_id, retired_id, performed_by, reason) VALUES (?,?,?,?)', [$kid, $rid, $editor->id, $reason]);
            Entities::addRevision($db, $rid, $editor->id, 'Merged into another record', $reason);
            Entities::addRevision($db, $kid, $editor->id, 'Merged with a duplicate record' . ($filled ? '; filled: ' . implode(', ', $filled) : ''), $reason);
            Audit::log($db, $editor->id, 'record.merged', $keep['kind'], $keep['public_id'], ['retired' => $retire['public_id'], 'reason' => $reason] + $log);
            Search::reindex($db, $rid);
            Search::reindex($db, $kid);
            return [$keep, $log];
        });
    }

    /** Possible duplicate people across the whole archive, for editors. A review aid, never proof. */
    public static function duplicateReport(Db $db, int $limit = 100): array
    {
        $people = $db->all('SELECT e.id, e.public_id, p.preferred_name, p.full_name, p.birth_start, p.birth_precision FROM entities e '
            . 'JOIN people p ON p.entity_id=e.id WHERE e.merged_into IS NULL AND e.deleted_at IS NULL ORDER BY e.id');
        $seen = [];
        $out = [];
        $sort = function (array $o) {
            usort($o, fn ($x, $y) => $y['score'] <=> $x['score']);
            return $o;
        };
        foreach ($people as $p) {
            $names = $db->col('SELECT name FROM entity_names WHERE entity_id=?', [$p['id']]);
            $by = ($p['birth_start'] && $p['birth_precision'] !== 'unknown') ? substr($p['birth_start'], 0, 4) : null;
            foreach (Duplicates::findPersonCandidates($db, $names, $by, 5, (int) $p['id']) as $c) {
                $pair = min($p['id'], $c['entity_id']) . '-' . max($p['id'], $c['entity_id']);
                if (isset($seen[$pair])) {
                    continue;
                }
                $seen[$pair] = true;
                $out[] = ['a' => ['public_id' => $p['public_id'], 'name' => $p['preferred_name']],
                    'b' => ['public_id' => $c['public_id'], 'name' => $c['name']], 'score' => $c['score'], 'why' => $c['why']];
                if (count($out) >= $limit) {
                    return $sort($out);
                }
            }
        }
        return $sort($out);
    }

    public static function mergeHistory(Db $db, int $entityId): array
    {
        return $db->all('SELECT m.*, k.public_id AS keep_pid, r.public_id AS retire_pid, u.username FROM merges m '
            . 'JOIN entities k ON k.id=m.canonical_id JOIN entities r ON r.id=m.retired_id LEFT JOIN users u ON u.id=m.performed_by '
            . 'WHERE m.canonical_id=? OR m.retired_id=? ORDER BY m.id DESC', [$entityId, $entityId]);
    }
}
