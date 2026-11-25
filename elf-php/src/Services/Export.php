<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Queries;

/**
 * Public data export: everything a visitor can already see on the site, as JSON and CSV in one ZIP.
 *
 * Only published, public, unmerged records are included, and only the fields their public pages show. Each table
 * has an explicit list of exported columns (tests fail if a new column is not classified), so confidential fields
 * (research notes, editor notes, uploader and reviewer ids, donor and custodian details, interview codes, redaction
 * notes) can never leak by being added to the schema later. Links appear only when the link itself and both ends
 * are public. Archive items also need public access and rights that allow display; oral-history transcripts and
 * translations appear only where the interviewee's consent allows it and no embargo is in force. Media files are not
 * included; each record carries its page address. Accounts, submissions, messages and logs are never exported.
 */
final class Export
{
    public const FORMAT_VERSION = 1;
    /** Columns exported per record table (entity_id is replaced by the record's permanent public_id). */
    public const RECORD_COLUMNS = [
        'person' => ['people', ['preferred_name', 'full_name', 'original_name', 'original_name_lang', 'summary', 'biography',
            'occupation', 'living_status', 'birth_start', 'birth_end', 'birth_precision', 'birth_note',
            'birth_place_id', 'death_start', 'death_end', 'death_precision', 'death_note', 'death_place_id']],
        'family' => ['families', ['display_name', 'original_name', 'summary', 'narrative', 'region_note']],
        'place' => ['places', ['primary_name', 'original_name', 'place_type_id', 'country', 'admin_region', 'latitude', 'longitude',
            'coord_precision', 'coord_note', 'overview', 'valid_start', 'valid_end', 'valid_precision', 'valid_note']],
        'event' => ['events', ['title', 'event_type_id', 'summary', 'description', 'date_start', 'date_end', 'date_precision', 'date_note']],
        'organization' => ['organizations', ['name', 'original_name', 'description', 'active_start', 'active_end', 'active_precision', 'active_note']],
        'source' => ['sources', ['title', 'source_type', 'creator', 'publisher', 'repository', 'identifier', 'pub_date_text', 'url',
            'accessed_on', 'language', 'provenance', 'rights_note', 'reliability_note']],
        'archive_item' => ['archive_items', ['title', 'alt_title', 'item_type', 'media_kind', 'description', 'created_start', 'created_end',
            'created_precision', 'created_note', 'creator', 'provenance', 'original_language',
            'transcript', 'transcript_reviewed', 'rights_holder', 'rights_status']],
        'collection' => ['collections', ['title', 'description', 'rights_note']],
        'oral_history' => ['oral_histories', ['title', 'interviewee_id', 'interviewee_text', 'interviewer_text', 'recorded_start',
            'recorded_end', 'recorded_precision', 'recorded_note', 'recording_location_note', 'language',
            'topics', 'summary', 'transcript_text', 'transcript_kind', 'transcript_reviewed',
            'translation_language', 'translation_text', 'translation_kind']],
    ];
    /** Columns deliberately NOT exported. Every column of an exported table must appear in exactly one of the two lists. */
    public const NOT_EXPORTED = [
        'people' => ['entity_id', 'kind', 'birth_place_kind', 'death_place_kind', 'research_notes'],
        'families' => ['entity_id', 'kind'],
        'places' => ['entity_id', 'kind'],
        'events' => ['entity_id', 'kind'],
        'organizations' => ['entity_id', 'kind'],
        'sources' => ['entity_id', 'kind'],
        'archive_items' => ['entity_id', 'kind', 'uploaded_by', 'donor', 'custodian', 'collection_note', 'access_level', 'embargo_until'],
        'collections' => ['entity_id', 'kind', 'is_featured', 'created_by'],
        'oral_histories' => ['entity_id', 'kind', 'interview_code', 'interviewee_kind', 'embargo_until', 'redaction_notes',
            'media_item_id', 'media_item_kind'],
    ];
    public const REF_COLUMNS = ['birth_place_id', 'death_place_id', 'interviewee_id'];

    private static function pidMap(Db $db, bool $includeFictional): array
    {
        $fict = $includeFictional ? '' : ' AND e.is_fictional_test=0';
        $out = [];
        foreach ($db->all('SELECT e.id, e.kind, e.public_id, e.slug, e.is_fictional_test, e.created_at, e.updated_at FROM entities e '
            . 'WHERE ' . Entities::PUBLIC_WHERE . ' AND ' . Search::itemOk() . $fict) as $r) {
            $out[$r['id']] = $r;
        }
        return $out;
    }

    /** Returns ["manifest" => [...], "tables" => [name => [row arrays]]]. */
    public static function build(Db $db, string $baseUrl = '', bool $includeFictional = false): array
    {
        $ents = self::pidMap($db, $includeFictional);
        $pid = fn ($i) => ($i !== null && isset($ents[$i])) ? $ents[$i]['public_id'] : null;
        $types = [];
        foreach (['place_types', 'event_types'] as $t) {
            foreach ($db->all("SELECT id, label FROM {$t}") as $r) {
                $types[$t][$r['id']] = $r['label'];
            }
        }
        $tables = [];
        foreach (self::RECORD_COLUMNS as $kind => [$table, $cols]) {
            $rows = [];
            foreach ($db->all('SELECT entity_id, ' . implode(', ', $cols) . " FROM {$table} ORDER BY entity_id") as $r) {
                $e = $ents[$r['entity_id']] ?? null;
                if (!$e) {
                    continue;
                }
                $out = ['public_id' => $e['public_id'], 'url' => $baseUrl . Queries::recordUrl($kind, $e['slug']),
                    'created_at' => $e['created_at'], 'updated_at' => $e['updated_at']];
                if ($includeFictional) {
                    $out['is_fictional_test'] = $e['is_fictional_test'];
                }
                foreach ($cols as $c) {
                    $v = $r[$c];
                    if (in_array($c, self::REF_COLUMNS, true)) {
                        $v = $pid($v);
                    } elseif ($c === 'place_type_id') {
                        [$c, $v] = ['place_type', $types['place_types'][$v] ?? null];
                    } elseif ($c === 'event_type_id') {
                        [$c, $v] = ['event_type', $types['event_types'][$v] ?? null];
                    }
                    $out[$c] = $v;
                }
                if ($kind === 'oral_history') {
                    $ok = Oral::allowed($db, (int) $r['entity_id']);
                    if (!$ok['publish_transcript']) {
                        $out['transcript_text'] = $out['transcript_kind'] = null;
                    }
                    if (!$ok['publish_translation']) {
                        $out['translation_text'] = $out['translation_kind'] = null;
                    }
                }
                $rows[] = $out;
            }
            $tables[$table] = $rows;
        }
        $tables['names'] = [];
        foreach ($db->all('SELECT * FROM entity_names ORDER BY entity_id, id') as $r) {
            if (isset($ents[$r['entity_id']])) {
                $tables['names'][] = ['record' => $pid($r['entity_id']), 'name' => $r['name'], 'name_type' => $r['name_type'], 'language' => $r['language'],
                    'script' => $r['script'], 'note' => $r['note']];
            }
        }
        /** `required` ends must be public records; `optional` ends are blanked when not public; of `oneOf` the one that is set must be public. */
        $links = function (string $sql, array $cols, array $required, array $optional = [], array $oneOf = []) use ($db, $ents, $pid) {
            $out = [];
            $idCols = array_merge($required, $optional, $oneOf);
            foreach ($db->all($sql) as $r) {
                foreach ($required as $k) {
                    if (!isset($ents[$r[$k]])) {
                        continue 2;
                    }
                }
                if ($oneOf) {
                    $any = false;
                    foreach ($oneOf as $k) {
                        if ($r[$k] !== null && isset($ents[$r[$k]])) {
                            $any = true;
                        }
                    }
                    if (!$any) {
                        continue;
                    }
                }
                $row = [];
                foreach ($cols as $c) {
                    $row[$c] = in_array($c, $idCols, true) ? $pid($r[$c]) : $r[$c];
                }
                $out[] = $row;
            }
            return $out;
        };
        $pub = "publication_status='published' AND visibility='public'";
        $period = ['period_start', 'period_end', 'period_precision', 'period_note'];
        $tables['relationships'] = $links("SELECT * FROM relationships WHERE {$pub} ORDER BY id",
            ['person_a_id', 'person_b_id', 'relationship_type', 'status', ...$period, 'notes'], ['person_a_id', 'person_b_id']);
        $tables['family_memberships'] = $links("SELECT * FROM family_memberships WHERE {$pub} ORDER BY id",
            ['family_id', 'person_id', 'role_note', ...$period], ['family_id', 'person_id']);
        $tables['affiliations'] = $links("SELECT * FROM affiliations WHERE {$pub} ORDER BY id",
            ['person_id', 'organization_id', 'role', ...$period, 'place_id', 'evidence_status', 'notes'], ['person_id', 'organization_id'], ['place_id']);
        $tables['event_participants'] = $links("SELECT * FROM event_participants WHERE publication_status='published' ORDER BY id",
            ['event_id', 'person_id', 'organization_id', 'role', 'evidence_status', 'notes'], ['event_id'], [], ['person_id', 'organization_id']);
        $tables['event_places'] = $links('SELECT * FROM event_places ORDER BY id', ['event_id', 'place_id', 'role_note', 'is_uncertain'], ['event_id', 'place_id']);
        $tables['collection_items'] = $links('SELECT * FROM collection_items ORDER BY collection_id, position', ['collection_id', 'item_id', 'position'], ['collection_id', 'item_id']);
        $tables['archive_item_subjects'] = $links('SELECT * FROM archive_item_subjects', ['item_id', 'subject_id', 'note'], ['item_id', 'subject_id']);
        $tables['oral_history_subjects'] = $links('SELECT * FROM oral_history_subjects', ['oral_history_id', 'subject_id'], ['oral_history_id', 'subject_id']);
        $tables['citations'] = $links('SELECT * FROM citations ORDER BY id',
            ['source_id', 'target_id', 'field_name', 'claim_text', 'locator', 'explanation', 'evidence_status'], ['source_id', 'target_id']);
        $tables['conflicting_accounts'] = $links('SELECT * FROM conflicting_accounts WHERE is_public=1 ORDER BY id',
            ['entity_id', 'topic', 'account_text', 'attributed_to', 'source_id', 'basis_note', 'needs_research', 'concerns_date', 'concerns_location'],
            ['entity_id'], ['source_id']);
        $counts = [];
        foreach ($tables as $k => $v) {
            $counts[$k] = count($v);
        }
        $manifest = [
            'title' => 'ELF Digital Historical Archive: public data export',
            'format_version' => self::FORMAT_VERSION,
            'generated_at' => Util::nowIso(),
            'base_url' => $baseUrl,
            'includes_fictional_test_records' => $includeFictional,
            'counts' => $counts,
            'notes' => [
                'Contains only records and fields that are publicly visible on the archive website at the time of export.',
                'Records are identified by their permanent public_id; links refer to records by public_id.',
                'Unknown values are empty (null). Dates carry a precision; an approximate date is not an exact date.',
                'Media files are not included. Being included here does not mean an item is free to reuse: check each record\'s rights.',
            ],
        ];
        return ['manifest' => $manifest, 'tables' => $tables];
    }

    public static function toZip(array $data): string
    {
        $tmp = tempnam(sys_get_temp_dir(), 'elfexp');
        $z = new \ZipArchive();
        $z->open($tmp, \ZipArchive::OVERWRITE);
        $json = fn ($v) => json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT | JSON_PRESERVE_ZERO_FRACTION);
        $z->addFromString('manifest.json', $json($data['manifest']));
        $z->addFromString('archive.json', $json($data['tables']));
        foreach ($data['tables'] as $name => $rows) {
            $csv = '';
            if ($rows) {
                $csv = Csv::write(array_merge([array_keys($rows[0])], array_map('array_values', $rows)), "\n");
            }
            $z->addFromString("csv/{$name}.csv", "\u{FEFF}" . $csv);     // BOM so spreadsheet programs read UTF-8 (Ge'ez, Arabic)
        }
        $z->close();
        $out = (string) file_get_contents($tmp);
        @unlink($tmp);
        return $out;
    }

    public static function exportZip(Db $db, ?int $actorId, string $baseUrl = '', bool $includeFictional = false, string $via = 'admin'): array
    {
        $data = self::build($db, $baseUrl, $includeFictional);
        Audit::log($db, $actorId, 'export.public', 'export', null,
            ['via' => $via, 'include_fictional' => $includeFictional, 'counts' => $data['manifest']['counts']]);
        return [self::toZip($data), $data['manifest']];
    }
}
