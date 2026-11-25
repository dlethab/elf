<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Family trees and the connections explorer, computed from explicit, PUBLIC relationship records only.
 *
 * Nothing is inferred: a line is drawn only where a published relationship, membership, affiliation, participation or
 * photo record exists, and each connection carries its explanation. People who are not public (for example living
 * people without consent) never appear, nor do their relationships. Layout is computed on the server and rendered as
 * SVG, so the views work without JavaScript.
 */
final class Graph
{
    public const NODE_W = 168;
    public const NODE_H = 54;
    public const GAP_X = 28;
    public const GAP_Y = 70;
    public const PARTNER_TYPES = ['spouse_of', 'partner_of'];
    public const MAX_NODES = 150;
    public const CATEGORIES = [
        'family' => 'Family relationship', 'family_record' => 'Family record', 'event' => 'Shared event',
        'organization' => 'Shared organization', 'place' => 'Shared place', 'document' => 'Shared photograph',
    ];

    private static function person(Db $db, int $pid): ?array
    {
        $r = $db->one('SELECT e.id, e.public_id, e.slug, e.is_fictional_test, p.preferred_name, p.birth_start, p.birth_end, '
            . 'p.birth_precision, p.death_start, p.death_end, p.death_precision FROM entities e JOIN people p ON p.entity_id=e.id '
            . 'WHERE e.id=? AND ' . Entities::PUBLIC_WHERE, [$pid]);
        if (!$r) {
            return null;
        }
        $b = Dates::format($r['birth_start'], $r['birth_end'], $r['birth_precision']);
        $d = Dates::format($r['death_start'], $r['death_end'], $r['death_precision']);
        $life = ($b === 'Unknown' && $d === 'Unknown') ? '' : (($b === 'Unknown' ? '' : $b) . '–' . ($d === 'Unknown' ? '' : $d));
        return ['id' => (int) $r['id'], 'public_id' => $r['public_id'], 'slug' => $r['slug'], 'name' => $r['preferred_name'], 'life' => $life,
            'fictional' => (bool) $r['is_fictional_test']];
    }

    /** Public relationships of one person where the other person is public too. */
    private static function relationships(Db $db, int $personId): array
    {
        return $db->all('SELECT r.* FROM relationships r JOIN entities a ON a.id=r.person_a_id AND ' . Entities::pub('a') . ' '
            . 'JOIN entities b ON b.id=r.person_b_id AND ' . Entities::pub('b') . ' WHERE (r.person_a_id=? OR r.person_b_id=?) '
            . "AND r.publication_status='published' AND r.visibility='public'", [$personId, $personId]);
    }

    public static function short(string $name, int $n = 22): string
    {
        return mb_strlen($name) <= $n ? $name : rtrim(mb_substr($name, 0, $n - 1)) . '…';
    }

    private static function f0(float $v): string
    {
        return sprintf('%.0f', $v);
    }

    /** Nodes and edges reachable from the roots through public relationships, laid out by generation. */
    public static function buildTree(Db $db, array $rootIds, int $depth = 3, array $members = []): ?array
    {
        $members = array_flip($members);
        $nodes = [];
        $edges = [];
        $seenEdges = [];
        $queue = array_map(fn ($rid) => [(int) $rid, 0], $rootIds);
        while ($queue && count($nodes) < self::MAX_NODES) {
            [$pid, $d] = array_shift($queue);
            if (isset($nodes[$pid])) {
                continue;
            }
            $info = self::person($db, $pid);
            if (!$info) {
                continue;
            }
            $info['member'] = isset($members[$pid]);
            $nodes[$pid] = $info;
            if ($d >= $depth) {
                continue;
            }
            foreach (self::relationships($db, $pid) as $r) {
                if (!isset($seenEdges[$r['id']])) {
                    $seenEdges[$r['id']] = true;
                    $edges[] = $r;
                }
                $other = (int) ($r['person_a_id'] === $pid ? $r['person_b_id'] : $r['person_a_id']);
                if (!isset($nodes[$other])) {
                    $queue[] = [$other, $d + 1];
                }
            }
        }
        $edges = array_values(array_filter($edges, fn ($e) => isset($nodes[$e['person_a_id']]) && isset($nodes[$e['person_b_id']])));
        return self::layout($nodes, $edges, array_map('intval', $rootIds));
    }

    private static function layout(array $nodes, array $edges, array $rootIds): ?array
    {
        if (!$nodes) {
            return null;
        }
        // generations: a parent is one row above the child; partners and siblings share a row
        $adj = [];
        foreach ($edges as $e) {
            [$a, $b, $t] = [(int) $e['person_a_id'], (int) $e['person_b_id'], $e['relationship_type']];
            if (in_array($t, Vocab::DIRECTED_RELATIONSHIPS, true)) {
                $adj[$a][] = [$b, 1];
                $adj[$b][] = [$a, -1];
            } elseif (in_array($t, self::PARTNER_TYPES, true) || $t === 'sibling_of') {
                $adj[$a][] = [$b, 0];
                $adj[$b][] = [$a, 0];
            }
        }
        $gen = [];
        $order = array_values(array_filter($rootIds, fn ($r) => isset($nodes[$r])));
        foreach (array_keys($nodes) as $n) {
            if (!in_array($n, $rootIds, true)) {
                $order[] = $n;
            }
        }
        foreach ($order as $start) {
            if (isset($gen[$start])) {
                continue;
            }
            $gen[$start] = 0;
            $q = [$start];
            while ($q) {
                $cur = array_shift($q);
                foreach ($adj[$cur] ?? [] as [$nxt, $delta]) {
                    if (!isset($gen[$nxt])) {
                        $gen[$nxt] = $gen[$cur] + $delta;
                        $q[] = $nxt;
                    }
                }
            }
        }
        $low = min($gen);
        $rows = [];
        foreach ($order as $n) {
            $rows[$gen[$n] - $low][] = $n;
        }
        ksort($rows);
        $parentsOf = [];
        $partners = [];
        foreach ($edges as $e) {
            if (in_array($e['relationship_type'], Vocab::DIRECTED_RELATIONSHIPS, true)) {
                $parentsOf[(int) $e['person_b_id']][] = (int) $e['person_a_id'];
            } elseif (in_array($e['relationship_type'], self::PARTNER_TYPES, true)) {
                $partners[(int) $e['person_a_id']][(int) $e['person_b_id']] = true;
                $partners[(int) $e['person_b_id']][(int) $e['person_a_id']] = true;
            }
        }
        // order each row: children under their parents (barycentre), partners side by side
        $pos = [];
        foreach ($rows as $g => $row) {
            if ($g > 0) {
                $key = function ($n) use ($parentsOf, &$pos) {
                    $ps = array_filter($parentsOf[$n] ?? [], fn ($p) => isset($pos[$p]));
                    return $ps ? array_sum(array_map(fn ($p) => $pos[$p], $ps)) / max(1, count($ps)) : 1e9;
                };
                usort($row, fn ($x, $y) => $key($x) <=> $key($y));
            }
            $arranged = [];
            foreach ($row as $n) {
                if (in_array($n, $arranged, true)) {
                    continue;
                }
                $arranged[] = $n;
                $ps = array_keys($partners[$n] ?? []);
                sort($ps);
                foreach ($ps as $p) {
                    if (in_array($p, $row, true) && !in_array($p, $arranged, true)) {
                        $arranged[] = $p;
                    }
                }
            }
            $rows[$g] = $arranged;
            foreach ($arranged as $i => $n) {
                $pos[$n] = $i;
            }
        }
        $widest = max(array_map('count', $rows));
        $width = $widest * (self::NODE_W + self::GAP_X) + self::GAP_X;
        $height = count($rows) * (self::NODE_H + self::GAP_Y) + self::GAP_Y;
        foreach ($rows as $g => $row) {
            $offset = ($width - count($row) * (self::NODE_W + self::GAP_X) + self::GAP_X) / 2;
            foreach ($row as $i => $n) {
                $nodes[$n]['x'] = (int) round($offset + $i * (self::NODE_W + self::GAP_X));
                $nodes[$n]['y'] = (int) round(self::GAP_Y / 2 + $g * (self::NODE_H + self::GAP_Y));
                $nodes[$n]['gen'] = $g;
                $nodes[$n]['label'] = self::short($nodes[$n]['name']);
            }
        }
        $lines = [];
        $drawnChildren = [];
        foreach ($edges as $e) {
            $a = $nodes[(int) $e['person_a_id']];
            $b = $nodes[(int) $e['person_b_id']];
            $t = $e['relationship_type'];
            $cls = "edge edge--{$t} edge--{$e['status']}";
            if (in_array($t, Vocab::DIRECTED_RELATIONSHIPS, true)) {
                $child = $b;
                $parents = [];
                foreach ($parentsOf[(int) $e['person_b_id']] ?? [] as $p) {
                    if (isset($nodes[$p])) {
                        $parents[] = $nodes[$p];
                    }
                }
                $couple = count($parents) === 2 && isset($partners[$parents[0]['id']][$parents[1]['id']]) && $t === 'parent_of';
                if ($couple && isset($drawnChildren[$child['id']])) {
                    continue;
                }
                if ($couple) {
                    $drawnChildren[$child['id']] = true;
                    $sx = ($parents[0]['x'] + $parents[1]['x']) / 2 + self::NODE_W / 2;
                    $sy = $parents[0]['y'] + self::NODE_H / 2;
                } else {
                    $sx = $a['x'] + self::NODE_W / 2;
                    $sy = $a['y'] + self::NODE_H;
                }
                $ex = $child['x'] + self::NODE_W / 2;
                $ey = $child['y'];
                $mid = $ey - self::GAP_Y / 2;
                $lines[] = ['d' => 'M' . self::f0($sx) . ',' . self::f0($sy) . ' V' . self::f0($mid) . ' H' . self::f0($ex) . ' V' . self::f0($ey), 'cls' => $cls];
            } elseif (in_array($t, self::PARTNER_TYPES, true) || $t === 'sibling_of' || $t === 'other_documented') {
                [$left, $right] = $a['x'] <= $b['x'] ? [$a, $b] : [$b, $a];
                if ($left['y'] === $right['y']) {
                    $y = $left['y'] + (in_array($t, self::PARTNER_TYPES, true) ? self::NODE_H / 2 : -6);
                    $lines[] = ['d' => in_array($t, self::PARTNER_TYPES, true)
                        ? 'M' . self::f0($left['x'] + self::NODE_W) . ',' . self::f0($y) . ' H' . self::f0($right['x'])
                        : 'M' . self::f0($left['x'] + self::NODE_W / 2) . ',' . self::f0($left['y']) . ' V' . self::f0($y) . ' H'
                            . self::f0($right['x'] + self::NODE_W / 2) . ' V' . self::f0($right['y']), 'cls' => $cls];
                } else {
                    $lines[] = ['d' => 'M' . self::f0($a['x'] + self::NODE_W / 2) . ',' . self::f0($a['y'] + self::NODE_H / 2) . ' L'
                        . self::f0($b['x'] + self::NODE_W / 2) . ',' . self::f0($b['y'] + self::NODE_H / 2), 'cls' => $cls];
                }
            }
        }
        $table = [];
        foreach ($edges as $e) {
            $t = $e['relationship_type'];
            $table[] = ['a' => $nodes[(int) $e['person_a_id']], 'label' => Vocab::RELATIONSHIP_TYPES[$t][0], 'b' => $nodes[(int) $e['person_b_id']],
                'status' => $e['status'], 'period' => Dates::format($e['period_start'], $e['period_end'], $e['period_precision']),
                'period_start' => $e['period_start'], 'period_end' => $e['period_end'], 'period_precision' => $e['period_precision'],
                'notes' => $e['notes']];
        }
        $generations = [];
        foreach ($rows as $row) {
            $generations[] = array_map(fn ($n) => $nodes[$n], $row);
        }
        $noParents = [];
        foreach ($nodes as $n => $node) {
            if (empty($parentsOf[$n])) {
                $noParents[] = $node;
            }
        }
        return ['nodes' => array_values($nodes), 'lines' => $lines, 'width' => $width, 'height' => $height,
            'generations' => $generations, 'table' => $table, 'node_w' => self::NODE_W, 'node_h' => self::NODE_H,
            'truncated' => count($nodes) >= self::MAX_NODES, 'no_parents' => $noParents];
    }

    public static function familyTree(Db $db, int $familyId): ?array
    {
        $members = array_map('intval', $db->col('SELECT m.person_id FROM family_memberships m JOIN entities e ON e.id=m.person_id AND '
            . Entities::PUBLIC_WHERE . " WHERE m.family_id=? AND m.publication_status='published' AND m.visibility='public' ORDER BY m.id", [$familyId]));
        return $members ? self::buildTree($db, $members, 1, $members) : null;
    }

    public static function personTree(Db $db, int $personId): ?array
    {
        return self::buildTree($db, [$personId], 3, [$personId]);
    }

    // ───────────── connections explorer ─────────────
    /**
     * A person, the records they are explicitly linked to, and other people linked to those same records. Each
     * connection says how it is documented; none says that two people knew each other.
     */
    public static function network(Db $db, int $personId, int $perHub = 12): ?array
    {
        $center = self::person($db, $personId);
        if (!$center) {
            return null;
        }
        $hubs = [];
        $people = [];
        $rows = [];
        $addPerson = function ($pid, ?array $viaHub, string $category, string $explanation) use ($db, $personId, &$people, &$rows) {
            $pid = (int) $pid;
            $p = self::person($db, $pid);
            if (!$p || $pid === $personId) {
                return;
            }
            $people[$pid] ??= $p + ['via' => []];
            $people[$pid]['via'][] = $viaHub;
            $rows[] = ['record' => $p, 'kind' => 'person', 'category' => $category, 'via' => $viaHub, 'explanation' => $explanation];
        };
        foreach (self::relationships($db, $personId) as $r) {
            $isA = $r['person_a_id'] === $personId;
            $other = $isA ? $r['person_b_id'] : $r['person_a_id'];
            $label = Vocab::RELATIONSHIP_TYPES[$r['relationship_type']][$isA ? 0 : 1];
            $addPerson($other, null, 'family', "{$label} (relationship record" . ($r['status'] !== 'current' ? ', ' . $r['status'] : '') . ')');
        }
        $hub = function (string $kind, $eid, string $slug, string $title, string $category, string $explanation, string $othersSql, array $args,
                         string $otherExpl) use ($db, $perHub, $addPerson, &$hubs, &$rows) {
            $h = ['kind' => $kind, 'id' => (int) $eid, 'slug' => $slug, 'title' => $title, 'category' => $category];
            $hubs[] = $h;
            $rows[] = ['record' => $h, 'kind' => $kind, 'category' => $category, 'via' => null, 'explanation' => $explanation];
            foreach (array_slice($db->q($othersSql, $args)->fetchAll(\PDO::FETCH_NUM), 0, $perHub) as $o) {
                $addPerson($o[0], $h, $category, $otherExpl);
            }
        };
        foreach ($db->all('SELECT e.id, e.slug, f.display_name FROM family_memberships m JOIN entities e ON e.id=m.family_id AND ' . Entities::PUBLIC_WHERE . ' '
            . "JOIN families f ON f.entity_id=e.id WHERE m.person_id=? AND m.publication_status='published' AND m.visibility='public'", [$personId]) as $r) {
            $hub('family', $r['id'], $r['slug'], $r['display_name'], 'family_record', 'Listed as a member of this family',
                "SELECT m.person_id FROM family_memberships m WHERE m.family_id=? AND m.person_id<>? AND m.publication_status='published' AND m.visibility='public'",
                [$r['id'], $personId], "Also a member of {$r['display_name']}");
        }
        foreach ($db->all('SELECT e.id, e.slug, ev.title, x.role FROM event_participants x JOIN entities e ON e.id=x.event_id AND ' . Entities::PUBLIC_WHERE . ' '
            . "JOIN events ev ON ev.entity_id=e.id WHERE x.person_id=? AND x.publication_status='published'", [$personId]) as $r) {
            $hub('event', $r['id'], $r['slug'], $r['title'], 'event', 'Documented as a participant' . ($r['role'] ? " ({$r['role']})" : ''),
                "SELECT x.person_id FROM event_participants x WHERE x.event_id=? AND x.person_id IS NOT NULL AND x.person_id<>? AND x.publication_status='published'",
                [$r['id'], $personId], "Also documented as a participant in {$r['title']}");
        }
        foreach ($db->all('SELECT DISTINCT e.id, e.slug, o.name FROM affiliations a JOIN entities e ON e.id=a.organization_id AND ' . Entities::PUBLIC_WHERE . ' '
            . "JOIN organizations o ON o.entity_id=e.id WHERE a.person_id=? AND a.publication_status='published' AND a.visibility='public'", [$personId]) as $r) {
            $hub('organization', $r['id'], $r['slug'], $r['name'], 'organization', 'Documented affiliation',
                "SELECT DISTINCT a.person_id FROM affiliations a WHERE a.organization_id=? AND a.person_id<>? AND a.publication_status='published' AND a.visibility='public'",
                [$r['id'], $personId], "Also affiliated with {$r['name']}. This does not mean they knew each other.");
        }
        foreach ($db->all('SELECT DISTINCT e.id, e.slug, pl.primary_name, (p.birth_place_id=e.id) AS born FROM people p '
            . 'JOIN entities e ON e.id IN (p.birth_place_id, p.death_place_id) AND ' . Entities::PUBLIC_WHERE . ' JOIN places pl ON pl.entity_id=e.id '
            . 'WHERE p.entity_id=?', [$personId]) as $r) {
            $hub('place', $r['id'], $r['slug'], $r['primary_name'], 'place', $r['born'] ? 'Birthplace' : 'Place of death',
                'SELECT p.entity_id FROM people p WHERE (p.birth_place_id=? OR p.death_place_id=?) AND p.entity_id<>?',
                [$r['id'], $r['id'], $personId], "Also born or died in {$r['primary_name']}. This does not mean they knew each other.");
        }
        foreach ($db->all('SELECT e.id, e.slug, a.title FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND ' . Entities::PUBLIC_WHERE . ' '
            . "JOIN archive_items a ON a.entity_id=e.id AND a.access_level='public' WHERE s.subject_id=?", [$personId]) as $r) {
            $hub('archive_item', $r['id'], $r['slug'], $r['title'], 'document', 'Shown or documented in this photograph',
                "SELECT s.subject_id FROM archive_item_subjects s JOIN entities x ON x.id=s.subject_id AND x.kind='person' WHERE s.item_id=? AND s.subject_id<>?",
                [$r['id'], $personId], "Also linked to the photograph {$r['title']}");
        }
        return self::radial($center, $hubs, $people, $rows);
    }

    private static function radial(array $center, array $hubs, array $people, array $rows): array
    {
        $R1 = 230;
        $R2 = 420;
        $size = 2 * ($R2 + 140);
        $cx = $cy = $size / 2;
        $direct = array_values(array_filter($people, fn ($p) => in_array(null, $p['via'], true)));
        $ring1 = array_merge(array_map(fn ($h) => ['hub', $h], $hubs), array_map(fn ($p) => ['person', $p], $direct));
        $n1 = max(1, count($ring1));
        $angle = [];
        $placed = [];
        foreach ($ring1 as $i => [$kind, $item]) {
            $a = 2 * M_PI * $i / $n1 - M_PI / 2;
            $angle["{$kind}:{$item['id']}"] = $a;
            $placed[] = ['kind' => $kind === 'person' ? 'person' : $item['kind'], 'item' => $item, 'x' => (int) round($cx + $R1 * cos($a)),
                'y' => (int) round($cy + $R1 * sin($a)), 'category' => $kind === 'person' ? 'family' : $item['category'], 'ring' => 1];
        }
        $byHub = [];
        foreach ($people as $p) {
            if (!in_array(null, $p['via'], true)) {
                $byHub[$p['via'][0]['id']][] = $p;
            }
        }
        foreach ($byHub as $hid => $ps) {
            $base = $angle["hub:{$hid}"] ?? 0;
            $spread = min(M_PI / 3, 2 * M_PI / $n1);
            $cnt = count($ps);
            foreach ($ps as $j => $p) {
                $a = $base + ($spread * ($j - ($cnt - 1) / 2) / max(1, $cnt));
                $placed[] = ['kind' => 'person', 'item' => $p, 'x' => (int) round($cx + $R2 * cos($a)), 'y' => (int) round($cy + $R2 * sin($a)),
                    'category' => $p['via'][0]['category'], 'ring' => 2, 'hub' => $hid];
            }
        }
        $pos = [];
        foreach ($placed as $n) {
            $pos[($n['kind'] === 'person' ? 'person' : 'hub') . ':' . $n['item']['id']] = $n;
        }
        $lines = [];
        foreach ($placed as $n) {
            if ($n['ring'] === 1) {
                $lines[] = ['x1' => $cx, 'y1' => $cy, 'x2' => $n['x'], 'y2' => $n['y'], 'cat' => $n['category']];
            } else {
                $h = $pos["hub:{$n['hub']}"] ?? null;
                if ($h) {
                    $lines[] = ['x1' => $h['x'], 'y1' => $h['y'], 'x2' => $n['x'], 'y2' => $n['y'], 'cat' => $n['category']];
                }
            }
        }
        foreach ($placed as &$n) {
            $n['label'] = self::short((string) (($n['item']['name'] ?? null) ?: ($n['item']['title'] ?? '')), 26);
        }
        unset($n);
        // fit the drawing to its content (labels extend about 90px either side and 45px below a node)
        $xs = array_merge([$cx], array_column($placed, 'x'));
        $ys = array_merge([$cy], array_column($placed, 'y'));
        $padX = 100;
        $padTop = 40;
        $padBottom = 60;
        $dx = $padX - min($xs);
        $dy = $padTop - min($ys);
        foreach ($placed as &$n) {
            $n['x'] += $dx;
            $n['y'] += $dy;
        }
        unset($n);
        foreach ($lines as &$ln) {
            $ln['x1'] += $dx;
            $ln['x2'] += $dx;
            $ln['y1'] += $dy;
            $ln['y2'] += $dy;
        }
        unset($ln);
        $w = (int) round(max($xs) - min($xs) + 2 * $padX);
        $h = (int) round(max($ys) - min($ys) + $padTop + $padBottom);
        return ['center' => $center + ['x' => $cx + $dx, 'y' => $cy + $dy, 'label' => self::short($center['name'], 26)], 'nodes' => $placed,
            'lines' => $lines, 'w' => $w, 'h' => $h, 'rows' => $rows, 'categories' => self::CATEGORIES];
    }
}
