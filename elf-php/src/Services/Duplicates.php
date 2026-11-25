<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;

/** Duplicate-person candidates. A REVIEW AID ONLY: similarity never merges anything and is not evidence of identity. Editors decide. */
final class Duplicates
{
    public static function findPersonCandidates(Db $db, array $names, ?string $birthYear = null, int $limit = 5, ?int $excludeEntityId = null): array
    {
        $wanted = [];
        foreach ($names as $n) {
            if ($n) {
                $k = Names::normalize($n);
                if ($k !== '') {
                    $wanted[$k] = true;
                }
            }
        }
        if (!$wanted) {
            return [];
        }
        $found = [];
        $rows = $db->all("SELECT n.entity_id, n.normalized, n.name, p.preferred_name, p.birth_start, p.birth_precision, "
            . 'e.public_id, e.slug, e.visibility FROM entity_names n JOIN entities e ON e.id=n.entity_id '
            . "JOIN people p ON p.entity_id=e.id WHERE e.kind='person' AND e.merged_into IS NULL AND e.deleted_at IS NULL");
        foreach ($rows as $r) {
            if ($r['entity_id'] === $excludeEntityId) {
                continue;
            }
            foreach (array_keys($wanted) as $w) {
                $w = (string) $w;
                if ($w === $r['normalized']) {
                    $score = 1.0;
                    $why = 'same name or spelling';
                } else {
                    $sm = new SequenceMatcher($w, (string) $r['normalized']);
                    if ($sm->realQuickRatio() < 0.8 || $sm->quickRatio() < 0.8) {
                        continue;
                    }
                    $score = $sm->ratio();
                    if ($score < 0.85) {
                        continue;
                    }
                    $why = 'similar spelling';
                }
                $by = ($r['birth_start'] && $r['birth_precision'] !== 'unknown') ? substr($r['birth_start'], 0, 4) : null;
                if ($birthYear && $by && (string) $birthYear === $by) {
                    $score = min(1.0, $score + 0.05);
                    $why .= '; same birth year';
                }
                $cur = $found[$r['entity_id']] ?? null;
                if (!$cur || $score > $cur['score']) {
                    $found[$r['entity_id']] = ['entity_id' => $r['entity_id'], 'public_id' => $r['public_id'], 'slug' => $r['slug'],
                        'name' => $r['preferred_name'], 'matched' => $r['name'], 'score' => round($score, 2),
                        'why' => $why, 'visibility' => $r['visibility']];
                }
            }
        }
        $out = array_values($found);
        usort($out, fn ($x, $y) => $y['score'] <=> $x['score']);
        return array_slice($out, 0, $limit);
    }
}
