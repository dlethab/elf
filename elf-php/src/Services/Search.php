<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Full-text search over PUBLIC records only (SQLite FTS5).
 *
 * The index is rebuilt per entity whenever its state or content changes (`reindex`), and every query re-checks
 * PUBLIC_WHERE against the registry as defence in depth, so a stale index entry can never surface a record that has
 * since been unpublished or restricted. One row per entity: aliases are folded into that row, so a person with five
 * spellings is still one result.
 */
final class Search
{
    private const BODY_COLS = [
        'person' => ['summary', 'biography', 'occupation', 'full_name'],
        'family' => ['summary', 'narrative', 'region_note'],
        'place' => ['overview', 'country', 'admin_region'],
        'event' => ['summary', 'description'],
        'source' => ['creator', 'publisher', 'repository'],
        'organization' => ['description'],
        'archive_item' => ['description', 'creator'],
        'collection' => ['description'],
        'oral_history' => ['summary', 'topics', 'interviewee_text', 'interviewer_text'],
    ];
    public const SEARCHABLE_KINDS = ['person', 'family', 'place', 'event', 'organization', 'source', 'archive_item', 'oral_history', 'collection'];

    /** Archive items also need their OWN access level and rights to allow public display. */
    public static function itemOk(): string
    {
        $rights = implode(',', array_map(fn ($r) => "'{$r}'", Vocab::PUBLIC_RIGHTS));
        return "(e.kind <> 'archive_item' OR EXISTS (SELECT 1 FROM archive_items a WHERE a.entity_id=e.id "
            . "AND a.access_level='public' AND a.rights_status IN ({$rights})))";
    }

    public static function reindex(Db $db, int $entityId): void
    {
        $db->exec('DELETE FROM search_fts WHERE rowid=?', [$entityId]);
        $e = $db->one('SELECT e.* FROM entities e WHERE e.id=? AND ' . Entities::PUBLIC_WHERE . ' AND ' . self::itemOk(), [$entityId]);
        if (!$e) {
            return;
        }
        $kind = $e['kind'];
        $sub = $db->one('SELECT * FROM ' . Entities::KIND_TABLE[$kind] . ' WHERE entity_id=?', [$entityId]);
        if (!$sub) {
            return;
        }
        $title = Names::normalize($sub[Entities::TITLE_COL[$kind]]);
        $aliases = implode(' ', $db->col('SELECT normalized FROM entity_names WHERE entity_id=?', [$entityId]));
        $body = [];
        foreach (self::BODY_COLS[$kind] ?? [] as $c) {
            if ($sub[$c] !== null && $sub[$c] !== '' && $sub[$c] !== 0) {
                $body[] = (string) $sub[$c];
            }
        }
        if ($kind === 'oral_history' && $sub['transcript_text']) {
            if (Oral::allowed($db, $entityId)['publish_transcript']) {   // the transcript is searchable only where it may be published
                $body[] = $sub['transcript_text'];
            }
        }
        $db->exec('INSERT INTO search_fts(rowid, title, aliases, body) VALUES (?,?,?,?)',
            [$entityId, $title, $aliases, Names::normalize(implode(' ', $body))]);
    }

    public static function rebuildAll(Db $db): void
    {
        $db->exec('DELETE FROM search_fts');
        foreach ($db->col('SELECT id FROM entities') as $id) {
            self::reindex($db, (int) $id);
        }
    }

    private static function matchExpr(string $q): array
    {
        $toks = array_map(fn ($t) => mb_substr($t, 0, 40), array_slice(Names::tokens($q), 0, 8));
        return [implode(' ', array_map(fn ($t) => "\"{$t}\"*", $toks)), $toks];
    }

    private static function context(string $kind, array $sub): ?string
    {
        if ($kind === 'person') {
            $b = Dates::format($sub['birth_start'], $sub['birth_end'], $sub['birth_precision']);
            $d = Dates::format($sub['death_start'], $sub['death_end'], $sub['death_precision']);
            $parts = array_filter([$b !== 'Unknown' ? "Born {$b}" : '', $d !== 'Unknown' ? "Died {$d}" : '']);
            return $parts ? implode(' · ', $parts) : null;
        }
        if ($kind === 'event') {
            $d = Dates::format($sub['date_start'], $sub['date_end'], $sub['date_precision']);
            return $d === 'Unknown' ? null : $d;
        }
        if ($kind === 'place') {
            return ($sub['admin_region'] ?: $sub['country']) ?: null;
        }
        return null;
    }

    private static function allTokensPrefix(array $toks, string $normalized): bool
    {
        $words = $normalized === '' ? [] : explode(' ', $normalized);
        foreach ($toks as $t) {
            $hit = false;
            foreach ($words as $w) {
                if (str_starts_with($w, $t)) {
                    $hit = true;
                    break;
                }
            }
            if (!$hit) {
                return false;
            }
        }
        return true;
    }

    public static function search(Db $db, ?string $q, ?string $kind = null, int $page = 1, int $perPage = 20): array
    {
        [$expr, $toks] = self::matchExpr((string) $q);
        $out = ['query' => $q, 'results' => [], 'total' => 0, 'page' => $page, 'per_page' => $perPage, 'suggestions' => []];
        if ($expr === '') {
            return $out;
        }
        $where = 'search_fts MATCH ? AND ' . Entities::PUBLIC_WHERE . ' AND ' . self::itemOk() . ($kind ? ' AND e.kind=?' : '');
        $args = $kind ? [$expr, $kind] : [$expr];
        $out['total'] = (int) $db->val("SELECT COUNT(*) FROM search_fts JOIN entities e ON e.id=search_fts.rowid WHERE {$where}", $args);
        $rows = $db->all("SELECT e.id, e.kind, e.public_id, e.slug, e.is_fictional_test FROM search_fts JOIN entities e ON e.id=search_fts.rowid "
            . "WHERE {$where} ORDER BY bm25(search_fts, 8.0, 5.0, 1.0), e.id LIMIT ? OFFSET ?",
            [...$args, $perPage, (max($page, 1) - 1) * $perPage]);
        foreach ($rows as $r) {
            $sub = $db->one('SELECT * FROM ' . Entities::KIND_TABLE[$r['kind']] . ' WHERE entity_id=?', [$r['id']]);
            $summ = Entities::SUMMARY_COL[$r['kind']];
            $text = $summ ? (string) ($sub[$summ] ?? '') : '';
            $matched = null;
            $titleNorm = Names::normalize($sub[Entities::TITLE_COL[$r['kind']]]);
            if ($toks && !self::allTokensPrefix($toks, $titleNorm)) {
                foreach ($db->all("SELECT name, normalized, name_type FROM entity_names WHERE entity_id=? AND name_type<>'preferred'", [$r['id']]) as $n) {
                    if (self::allTokensPrefix($toks, (string) $n['normalized'])) {
                        $matched = $n['name'] . ' (' . str_replace('_', ' ', $n['name_type']) . ')';
                        break;
                    }
                }
            }
            $out['results'][] = [
                'kind' => $r['kind'], 'public_id' => $r['public_id'], 'slug' => $r['slug'],
                'title' => $sub[Entities::TITLE_COL[$r['kind']]],
                'summary' => mb_substr($text, 0, 240) . (mb_strlen($text) > 240 ? '…' : ''),
                'context' => self::context($r['kind'], $sub), 'matched_name' => $matched,
                'fictional' => (bool) $r['is_fictional_test'],
            ];
        }
        if ($out['total'] === 0) {
            $out['suggestions'] = self::suggest($db, (string) $q);
        }
        return $out;
    }

    /** "Did you mean" from known public names. Suggestions are shown as suggestions, never as results. */
    public static function suggest(Db $db, string $q, int $limit = 3): array
    {
        $nq = Names::normalize($q);
        if (mb_strlen($nq) < 3) {
            return [];
        }
        $names = $db->all('SELECT n.normalized, n.name, e.kind, e.slug FROM entity_names n JOIN entities e ON e.id=n.entity_id '
            . 'WHERE ' . Entities::PUBLIC_WHERE . ' AND ' . self::itemOk() . ' LIMIT 20000');
        $byNorm = [];
        foreach ($names as $n) {
            $byNorm[(string) $n['normalized']] ??= $n;
        }
        $close = self::closeMatches($nq, array_map('strval', array_keys($byNorm)), $limit, 0.75);
        return array_map(fn ($c) => ['name' => $byNorm[$c]['name'], 'kind' => $byNorm[$c]['kind'], 'slug' => $byNorm[$c]['slug']], $close);
    }

    /** difflib.get_close_matches */
    public static function closeMatches(string $word, array $possibilities, int $n = 3, float $cutoff = 0.6): array
    {
        $result = [];
        foreach ($possibilities as $x) {
            $s = new SequenceMatcher($x, $word);
            if ($s->realQuickRatio() >= $cutoff && $s->quickRatio() >= $cutoff) {
                $r = $s->ratio();
                if ($r >= $cutoff) {
                    $result[] = [$r, $x];
                }
            }
        }
        usort($result, fn ($a, $b) => [$b[0], $b[1]] <=> [$a[0], $a[1]]);
        return array_map(fn ($p) => $p[1], array_slice($result, 0, $n));
    }
}
