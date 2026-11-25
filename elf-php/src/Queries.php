<?php
declare(strict_types=1);

namespace Elf;

use Elf\Services\Dates;
use Elf\Services\Entities;

/**
 * Read-side queries for PUBLIC pages. Every query goes through PUBLIC_WHERE; confidential columns
 * (research_notes, editor notes) are never selected here.
 */
final class Queries
{
    public const PER_PAGE = 24;
    public const THUMB = "(SELECT m.storage_key FROM media_files m WHERE m.owner_id=e.id AND m.file_role='thumbnail' LIMIT 1)";
    public const DISPLAY = "(SELECT m.storage_key FROM media_files m WHERE m.owner_id=e.id AND m.file_role='access_derivative' LIMIT 1)";
    public const DATE_CERTAINTY = ['exact' => 'precise', 'month' => 'precise', 'year' => 'precise', 'range' => 'range',
        'approximate' => 'uncertain', 'decade' => 'uncertain'];

    /** An archive item is shown publicly only when the record is public AND its own access level and rights allow it. */
    public static function publicItem(): string
    {
        return "a.access_level = 'public' AND a.rights_status IN (" . implode(',', array_map(fn ($r) => "'{$r}'", Vocab::PUBLIC_RIGHTS)) . ')';
    }

    public static function pub(string $alias): string
    {
        return Entities::pub($alias);
    }

    public static function recordUrl(string $kind, string $slug): string
    {
        return '/' . Entities::URL_SECTION[$kind] . '/' . $slug;
    }

    public static function mediaUrl(string $key): string
    {
        return '/media/' . $key;
    }

    /** Public photographs linked to a record. */
    public static function recordPhotos(Db $db, int $subjectId): array
    {
        return $db->all('SELECT e.slug, a.title, a.media_kind, a.item_type, a.created_start, a.created_end, a.created_precision, ' . self::THUMB . ' AS thumb_key, '
            . 'a.creator, a.rights_holder, a.rights_status, ' . self::DISPLAY . ' AS display_key '
            . 'FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND ' . Entities::PUBLIC_WHERE . ' '
            . 'JOIN archive_items a ON a.entity_id=e.id AND ' . self::publicItem() . ' WHERE s.subject_id=? ORDER BY e.id LIMIT 60', [$subjectId]);
    }

    public static function listArchive(Db $db, int $page = 1): array
    {
        $where = "e.kind='archive_item' AND " . Entities::PUBLIC_WHERE . ' AND ' . self::publicItem();
        $total = (int) $db->val("SELECT COUNT(*) FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE {$where}");
        $rows = $db->all('SELECT e.slug, e.is_fictional_test, a.title, a.media_kind, a.item_type, a.created_start, a.created_end, a.created_precision, '
            . self::THUMB . " AS thumb_key FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE {$where} ORDER BY e.id DESC LIMIT ? OFFSET ?",
            [self::PER_PAGE, (max($page, 1) - 1) * self::PER_PAGE]);
        return [$rows, $total];
    }

    /**
     * The item with its display file, or null when the item itself may not be shown publicly
     * (unless the caller has already established research access).
     */
    public static function archiveItem(Db $db, int $entityId, bool $allowRestricted = false): ?array
    {
        return $db->one("SELECT a.*, (SELECT m.storage_key FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='access_derivative' LIMIT 1) "
            . "AS display_key, (SELECT m.width FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='access_derivative' LIMIT 1) AS w, "
            . "(SELECT m.height FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='access_derivative' LIMIT 1) AS h, "
            . "(SELECT m.storage_key FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='original' LIMIT 1) AS original_key, "
            . "(SELECT m.size_bytes FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='original' LIMIT 1) AS original_size, "
            . "(SELECT m.mime_type FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='original' LIMIT 1) AS original_mime, "
            . 'u.display_name, u.username, u.attribution_pref '
            . 'FROM archive_items a LEFT JOIN users u ON u.id=a.uploaded_by AND u.anonymized_at IS NULL '
            . 'WHERE a.entity_id=?' . ($allowRestricted ? '' : ' AND ' . self::publicItem()), [$entityId]);
    }

    public static function itemSubjects(Db $db, int $itemId): array
    {
        $out = [];
        foreach ($db->all('SELECT e.id, e.kind, e.slug FROM archive_item_subjects s JOIN entities e ON e.id=s.subject_id AND '
            . Entities::PUBLIC_WHERE . ' WHERE s.item_id=? ORDER BY e.kind, e.id', [$itemId]) as $r) {
            $t = $db->val('SELECT ' . Entities::TITLE_COL[$r['kind']] . ' FROM ' . Entities::KIND_TABLE[$r['kind']] . ' WHERE entity_id=?', [$r['id']]);
            $out[] = ['kind' => $r['kind'], 'url' => self::recordUrl($r['kind'], $r['slug']), 'title' => $t];
        }
        return $out;
    }

    public static function listPublic(Db $db, string $kind, int $page = 1, ?string $letter = null): array
    {
        $t = Entities::KIND_TABLE[$kind];
        $title = Entities::TITLE_COL[$kind];
        $summ = Entities::SUMMARY_COL[$kind];
        $where = 'e.kind=? AND ' . Entities::PUBLIC_WHERE;
        $args = [$kind];
        if ($letter) {
            $where .= " AND upper(substr(t.{$title},1,1))=?";
            $args[] = $letter;
        }
        $total = (int) $db->val("SELECT COUNT(*) FROM entities e JOIN {$t} t ON t.entity_id=e.id WHERE {$where}", $args);
        $sel = $summ ? "t.{$summ} AS summary_text," : 'NULL AS summary_text,';
        $rows = $db->all("SELECT t.*, e.public_id, e.slug, e.is_fictional_test, t.{$title} AS title, {$sel} t.entity_id AS entity_id "
            . "FROM entities e JOIN {$t} t ON t.entity_id=e.id WHERE {$where} ORDER BY lower(t.{$title}), e.id LIMIT ? OFFSET ?",
            [...$args, self::PER_PAGE, (max($page, 1) - 1) * self::PER_PAGE]);
        return [$rows, $total];
    }

    public static function sub(Db $db, int $entityId, string $kind): ?array
    {
        return $db->one('SELECT * FROM ' . Entities::KIND_TABLE[$kind] . ' WHERE entity_id=?', [$entityId]);
    }

    public static function names(Db $db, int $entityId): array
    {
        return $db->all("SELECT name, name_type, language FROM entity_names WHERE entity_id=? AND name_type<>'preferred' ORDER BY id", [$entityId]);
    }

    public static function citations(Db $db, int $entityId): array
    {
        return $db->all('SELECT c.field_name, c.claim_text, c.locator, c.explanation, c.evidence_status, s.title, s.source_type, '
            . 's.creator, s.url, se.slug AS source_slug FROM citations c JOIN entities se ON se.id=c.source_id AND ' . self::pub('se') . ' '
            . 'JOIN sources s ON s.entity_id=se.id WHERE c.target_id=? ORDER BY c.id', [$entityId]);
    }

    /** Public records that cite a source. */
    public static function citedBy(Db $db, int $sourceId): array
    {
        $out = [];
        foreach ($db->all('SELECT DISTINCT e.id, e.kind, e.slug, c.locator FROM citations c JOIN entities e ON e.id=c.target_id AND '
            . Entities::PUBLIC_WHERE . ' WHERE c.source_id=? ORDER BY e.kind, e.id', [$sourceId]) as $r) {
            $t = $db->val('SELECT ' . Entities::TITLE_COL[$r['kind']] . ' FROM ' . Entities::KIND_TABLE[$r['kind']] . ' WHERE entity_id=?', [$r['id']]);
            $out[] = ['kind' => $r['kind'], 'url' => self::recordUrl($r['kind'], $r['slug']), 'title' => $t, 'locator' => $r['locator']];
        }
        return $out;
    }

    public static function accounts(Db $db, int $entityId): array
    {
        return $db->all('SELECT topic, account_text, attributed_to, basis_note, needs_research, concerns_date, concerns_location FROM conflicting_accounts '
            . 'WHERE entity_id=? AND is_public=1 ORDER BY id', [$entityId]);
    }

    /** Public change history: date and summary only. No actor identities, reasons or snapshots. */
    public static function publicRevisions(Db $db, int $entityId): array
    {
        return $db->all('SELECT revision_number, change_summary, created_at FROM revisions WHERE entity_id=? ORDER BY revision_number DESC', [$entityId]);
    }

    public static function personRelationships(Db $db, int $personId): array
    {
        $out = [];
        $rows = $db->all("SELECT r.*, (r.person_a_id=?) AS viewer_is_a FROM relationships r WHERE (r.person_a_id=? OR r.person_b_id=?) "
            . "AND r.publication_status='published' AND r.visibility='public'", [$personId, $personId, $personId]);
        foreach ($rows as $r) {
            $other = $r['viewer_is_a'] ? $r['person_b_id'] : $r['person_a_id'];
            $o = $db->one('SELECT e.public_id, e.slug, p.preferred_name FROM entities e JOIN people p ON p.entity_id=e.id WHERE e.id=? AND '
                . Entities::PUBLIC_WHERE, [$other]);
            if (!$o) {        // relationship to a non-public person is never revealed
                continue;
            }
            $labels = Vocab::RELATIONSHIP_TYPES[$r['relationship_type']];
            $out[] = ['label' => $r['viewer_is_a'] ? $labels[0] : $labels[1], 'status' => $r['status'], 'notes' => $r['notes'],
                'period' => Dates::format($r['period_start'], $r['period_end'], $r['period_precision']),
                'period_start' => $r['period_start'], 'period_end' => $r['period_end'], 'period_precision' => $r['period_precision'],
                'name' => $o['preferred_name'], 'url' => self::recordUrl('person', $o['slug'])];
        }
        return $out;
    }

    public static function personFamilies(Db $db, int $personId): array
    {
        return $db->all('SELECT e.slug, f.display_name, m.role_note FROM family_memberships m JOIN entities e ON e.id=m.family_id AND '
            . Entities::PUBLIC_WHERE . ' JOIN families f ON f.entity_id=e.id WHERE m.person_id=? '
            . "AND m.publication_status='published' AND m.visibility='public'", [$personId]);
    }

    public static function personEvents(Db $db, int $personId): array
    {
        return $db->all('SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, p.role, p.evidence_status FROM event_participants p '
            . 'JOIN entities e ON e.id=p.event_id AND ' . Entities::PUBLIC_WHERE . ' JOIN events ev ON ev.entity_id=e.id '
            . "WHERE p.person_id=? AND p.publication_status='published' ORDER BY ev.date_start", [$personId]);
    }

    public static function placeLink(Db $db, ?int $placeId): ?array
    {
        if (!$placeId) {
            return null;
        }
        return $db->one('SELECT e.slug, p.primary_name FROM entities e JOIN places p ON p.entity_id=e.id WHERE e.id=? AND ' . Entities::PUBLIC_WHERE, [$placeId]);
    }

    public static function familyMembers(Db $db, int $familyId): array
    {
        return $db->all('SELECT e.slug, p.preferred_name, m.role_note FROM family_memberships m JOIN entities e ON e.id=m.person_id AND '
            . Entities::PUBLIC_WHERE . " JOIN people p ON p.entity_id=e.id WHERE m.family_id=? AND m.publication_status='published' "
            . "AND m.visibility='public' ORDER BY p.preferred_name", [$familyId]);
    }

    public static function placeEvents(Db $db, int $placeId): array
    {
        return $db->all('SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, ep.is_uncertain FROM event_places ep '
            . 'JOIN entities e ON e.id=ep.event_id AND ' . Entities::PUBLIC_WHERE . ' JOIN events ev ON ev.entity_id=e.id WHERE ep.place_id=? '
            . 'ORDER BY ev.date_start', [$placeId]);
    }

    public static function placePeople(Db $db, int $placeId): array
    {
        return $db->all('SELECT e.slug, p.preferred_name, (p.birth_place_id=?) AS born, (p.death_place_id=?) AS died FROM people p '
            . 'JOIN entities e ON e.id=p.entity_id AND ' . Entities::PUBLIC_WHERE . ' WHERE p.birth_place_id=? OR p.death_place_id=? '
            . 'ORDER BY p.preferred_name', [$placeId, $placeId, $placeId, $placeId]);
    }

    /** People and organizations that took part, each only if their own record is public. */
    public static function eventParticipants(Db $db, int $eventId): array
    {
        return $db->all("SELECT 'person' AS kind, e.slug, p.preferred_name AS name, ep.role, ep.evidence_status FROM event_participants ep "
            . 'JOIN entities e ON e.id=ep.person_id AND ' . Entities::PUBLIC_WHERE . ' JOIN people p ON p.entity_id=e.id '
            . "WHERE ep.event_id=? AND ep.publication_status='published' "
            . "UNION ALL SELECT 'organization', e.slug, o.name, ep.role, ep.evidence_status FROM event_participants ep "
            . 'JOIN entities e ON e.id=ep.organization_id AND ' . Entities::PUBLIC_WHERE . ' JOIN organizations o ON o.entity_id=e.id '
            . "WHERE ep.event_id=? AND ep.publication_status='published' ORDER BY 1 DESC, 3", [$eventId, $eventId]);
    }

    private const AFF_COLS = 'a.role, a.period_start, a.period_end, a.period_precision, a.evidence_status, a.notes';

    public static function personAffiliations(Db $db, int $personId): array
    {
        return $db->all('SELECT ' . self::AFF_COLS . ', oe.slug, o.name, ple.slug AS place_slug, pl.primary_name AS place_name FROM affiliations a '
            . 'JOIN entities oe ON oe.id=a.organization_id AND ' . self::pub('oe') . ' JOIN organizations o ON o.entity_id=oe.id '
            . 'LEFT JOIN entities ple ON ple.id=a.place_id AND ' . self::pub('ple') . ' LEFT JOIN places pl ON pl.entity_id=ple.id '
            . "WHERE a.person_id=? AND a.publication_status='published' AND a.visibility='public' "
            . 'ORDER BY a.period_start IS NULL, a.period_start, o.name', [$personId]);
    }

    public static function orgMembers(Db $db, int $orgId): array
    {
        return $db->all('SELECT ' . self::AFF_COLS . ', pe.slug, p.preferred_name AS name FROM affiliations a '
            . 'JOIN entities pe ON pe.id=a.person_id AND ' . self::pub('pe') . ' JOIN people p ON p.entity_id=pe.id '
            . "WHERE a.organization_id=? AND a.publication_status='published' AND a.visibility='public' "
            . 'ORDER BY p.preferred_name, a.period_start', [$orgId]);
    }

    public static function orgEvents(Db $db, int $orgId): array
    {
        return $db->all('SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, p.role, p.evidence_status FROM event_participants p '
            . 'JOIN entities e ON e.id=p.event_id AND ' . Entities::PUBLIC_WHERE . ' JOIN events ev ON ev.entity_id=e.id '
            . "WHERE p.organization_id=? AND p.publication_status='published' ORDER BY ev.date_start", [$orgId]);
    }

    public static function eventPlacesFor(Db $db, int $eventId): array
    {
        return $db->all('SELECT e.slug, p.primary_name, ep.is_uncertain, p.latitude, p.coord_precision FROM event_places ep '
            . 'JOIN entities e ON e.id=ep.place_id AND ' . Entities::PUBLIC_WHERE . ' JOIN places p ON p.entity_id=e.id WHERE ep.event_id=?', [$eventId]);
    }

    /**
     * Public events, dated ones in order, undated ones listed separately (never given a false date).
     * Filters (all optional): type (event type slug), place / person / organization (permanent id),
     * q (words in the title or summary), from / to (years; an event matches if its span overlaps).
     */
    public static function timeline(Db $db, array $f = []): array
    {
        $where = ["e.kind='event'", Entities::PUBLIC_WHERE];
        $args = [];
        if (!empty($f['type'])) {
            $where[] = 't.slug=?';
            $args[] = $f['type'];
        }
        foreach ([
            'place' => 'EXISTS (SELECT 1 FROM event_places x JOIN entities xe ON xe.id=x.place_id WHERE x.event_id=e.id AND xe.public_id=?)',
            'person' => "EXISTS (SELECT 1 FROM event_participants x JOIN entities xe ON xe.id=x.person_id WHERE x.event_id=e.id AND x.publication_status='published' AND xe.public_id=?)",
            'organization' => "EXISTS (SELECT 1 FROM event_participants x JOIN entities xe ON xe.id=x.organization_id WHERE x.event_id=e.id AND x.publication_status='published' AND xe.public_id=?)",
        ] as $key => $sql) {
            if (!empty($f[$key])) {
                $where[] = $sql;
                $args[] = $f[$key];
            }
        }
        if (!empty($f['region'])) {
            $where[] = 'EXISTS (SELECT 1 FROM event_places x JOIN entities xe ON xe.id=x.place_id AND ' . self::pub('xe') . ' '
                . 'JOIN places xp ON xp.entity_id=xe.id WHERE x.event_id=e.id AND xp.admin_region=?)';
            $args[] = $f['region'];
        }
        if (!empty($f['media'])) {        // photographs, documents or recordings about the event that the public may see
            $where[] = '(EXISTS (SELECT 1 FROM archive_item_subjects s JOIN entities ie ON ie.id=s.item_id AND ' . self::pub('ie') . ' '
                . 'JOIN archive_items a ON a.entity_id=ie.id AND ' . self::publicItem() . ' WHERE s.subject_id=e.id) '
                . 'OR EXISTS (SELECT 1 FROM oral_history_subjects s JOIN entities oe ON oe.id=s.oral_history_id AND ' . self::pub('oe') . ' WHERE s.subject_id=e.id))';
        }
        if (!empty($f['q'])) {
            $where[] = "(lower(ev.title) LIKE ? OR lower(COALESCE(ev.summary,'')) LIKE ?)";
            $like = '%' . mb_strtolower($f['q'], 'UTF-8') . '%';
            $args[] = $like;
            $args[] = $like;
        }
        if (!empty($f['from'])) {
            $where[] = "ev.date_precision<>'unknown' AND CAST(substr(COALESCE(ev.date_end, ev.date_start),1,4) AS INTEGER) >= ?";
            $args[] = (int) $f['from'];
        }
        if (!empty($f['to'])) {
            $where[] = "ev.date_precision<>'unknown' AND CAST(substr(ev.date_start,1,4) AS INTEGER) <= ?";
            $args[] = (int) $f['to'];
        }
        $rows = $db->all('SELECT e.slug, e.public_id, e.is_fictional_test, ev.title, ev.summary, ev.date_start, ev.date_end, ev.date_precision, '
            . 't.label AS type_label, t.slug AS type_slug FROM entities e JOIN events ev ON ev.entity_id=e.id '
            . 'LEFT JOIN event_types t ON t.id=ev.event_type_id WHERE ' . implode(' AND ', $where) . ' '
            . 'ORDER BY ev.date_start IS NULL, ev.date_start, lower(ev.title) LIMIT 2000', $args);
        $byId = [];
        foreach ($rows as $r) {
            $r['places'] = [];
            $byId[$r['public_id']] = $r;
        }
        if ($byId) {
            $ph = implode(',', array_fill(0, count($byId), '?'));
            foreach ($db->all('SELECT ee.public_id AS event_id, pe.public_id, pe.slug, p.primary_name, p.latitude IS NOT NULL AS mapped, x.is_uncertain '
                . 'FROM event_places x JOIN entities ee ON ee.id=x.event_id JOIN entities pe ON pe.id=x.place_id '
                . "JOIN places p ON p.entity_id=pe.id WHERE ee.public_id IN ({$ph}) AND " . self::pub('pe') . ' ORDER BY lower(p.primary_name)',
                array_keys($byId)) as $p) {
                $byId[$p['event_id']]['places'][] = $p;
            }
        }
        $all = array_values($byId);
        $dated = array_values(array_filter($all, fn ($r) => $r['date_precision'] !== 'unknown'));
        $undated = array_values(array_filter($all, fn ($r) => $r['date_precision'] === 'unknown'));
        return [$dated, $undated];
    }

    /**
     * How dated events spread over the years, for the timeline's time ruler. An event counts in every year its
     * documented span covers; approximate and decade-only dates are counted separately so the ruler never presents
     * them as exact.
     */
    public static function timelineRuler(array $dated): ?array
    {
        $spans = [];
        foreach ($dated as $ev) {
            $span = Dates::yearSpan($ev['date_start'], $ev['date_end'], $ev['date_precision']);
            if ($span) {
                $spans[] = [$span[0], max($span), self::DATE_CERTAINTY[$ev['date_precision']] ?? 'uncertain'];
            }
        }
        if (!$spans) {
            return null;
        }
        $lo = intdiv(min(array_column($spans, 0)), 10) * 10;
        $hi = intdiv(max(array_column($spans, 1)), 10) * 10 + 9;
        $years = [];
        for ($y = $lo; $y <= $hi; $y++) {
            $years[$y] = ['precise' => 0, 'range' => 0, 'uncertain' => 0];
        }
        foreach ($spans as [$y0, $y1, $kind]) {
            for ($y = $y0; $y <= $y1; $y++) {
                $years[$y][$kind]++;
            }
        }
        $peak = max(array_map(fn ($c) => array_sum($c), $years)) ?: 1;
        $decades = [];
        for ($d = $lo; $d <= $hi; $d += 10) {
            $decades[] = ['label' => "{$d}s", 'start' => $d, 'count' => count(array_filter($spans, fn ($s) => $d <= $s[0] && $s[0] <= $d + 9))];
        }
        $bars = [];
        foreach ($years as $y => $c) {
            $bars[] = ['year' => $y] + $c;
        }
        return ['lo' => $lo, 'hi' => $hi, 'n' => count($spans), 'peak' => $peak, 'decades' => $decades, 'bars' => $bars];
    }

    /** Public oral histories that concern a record (whether their recording or transcript may be shown is decided on their own page). */
    public static function subjectOralHistories(Db $db, int $subjectId): array
    {
        return $db->all('SELECT e.slug, o.title, o.recorded_start, o.recorded_end, o.recorded_precision FROM oral_history_subjects s '
            . 'JOIN entities e ON e.id=s.oral_history_id AND ' . Entities::PUBLIC_WHERE . ' JOIN oral_histories o ON o.entity_id=e.id '
            . 'WHERE s.subject_id=? ORDER BY o.recorded_start', [$subjectId]);
    }

    /** Title of a public record used as a filter (null when it is not public). */
    public static function filterLabel(Db $db, string $kind, string $publicId): ?string
    {
        $t = Entities::KIND_TABLE[$kind];
        $col = Entities::TITLE_COL[$kind];
        $v = $db->val("SELECT x.{$col} FROM entities e JOIN {$t} x ON x.entity_id=e.id WHERE e.public_id=? AND e.kind=? AND " . Entities::PUBLIC_WHERE, [$publicId, $kind]);
        return $v === null ? null : (string) $v;
    }

    /**
     * Everything the interactive map draws, from the same public records as the rest of the site.
     * Places without documented coordinates are never placed on the map.
     */
    public static function mapData(Db $db): array
    {
        $places = [];
        foreach ($db->all('SELECT e.id, e.public_id, e.slug, e.is_fictional_test, p.primary_name, p.latitude, p.longitude, p.coord_precision, '
            . 'p.coord_note, p.admin_region, p.country, t.slug AS type_slug, t.label AS type_label '
            . 'FROM entities e JOIN places p ON p.entity_id=e.id LEFT JOIN place_types t ON t.id=p.place_type_id '
            . "WHERE e.kind='place' AND " . Entities::PUBLIC_WHERE . ' AND p.latitude BETWEEN -90 AND 90 AND p.longitude BETWEEN -180 AND 180') as $r) {
            $places[$r['id']] = ['id' => $r['public_id'], 'name' => $r['primary_name'], 'url' => self::recordUrl('place', $r['slug']),
                'lat' => (float) $r['latitude'], 'lon' => (float) $r['longitude'], 'precision' => $r['coord_precision'],
                'note' => $r['coord_note'], 'region' => ($r['admin_region'] ?: $r['country']) ?: null,
                'type' => $r['type_slug'] ?: 'other', 'type_label' => $r['type_label'] ?: 'Other historically relevant place',
                'category' => Atlas::category($r['type_slug']),
                'names' => '', 'fictional' => (bool) $r['is_fictional_test'], 'events' => [], 'people' => 0];
        }
        if ($places) {
            $ids = array_keys($places);
            $ph = implode(',', array_fill(0, count($ids), '?'));
            $names = [];
            foreach ($db->all("SELECT entity_id, normalized FROM entity_names WHERE entity_id IN ({$ph})", $ids) as $r) {
                $names[$r['entity_id']][] = $r['normalized'];
            }
            foreach ($names as $pid => $ns) {
                $places[$pid]['names'] = implode(' ', $ns);
            }
            foreach ($db->all('SELECT ep.place_id, e.public_id, e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, ep.is_uncertain, '
                . 't.slug AS type_slug FROM event_places ep JOIN entities e ON e.id=ep.event_id AND ' . Entities::PUBLIC_WHERE . ' '
                . 'JOIN events ev ON ev.entity_id=e.id LEFT JOIN event_types t ON t.id=ev.event_type_id '
                . "WHERE ep.place_id IN ({$ph}) ORDER BY ev.date_start", $ids) as $r) {
                $span = Dates::yearSpan($r['date_start'], $r['date_end'], $r['date_precision']);
                // only what the map filters and the period ribbon use; titles and dates come with the place panel (/map/place/<id>.json)
                $places[$r['place_id']]['events'][] = ['id' => $r['public_id'], 'type' => $r['type_slug'] ?: 'other',
                    'from' => $span[0] ?? null, 'to' => $span[1] ?? null, 'precision' => $r['date_precision']];
            }
            foreach ($db->all('SELECT pl, COUNT(DISTINCT pid) AS n FROM (SELECT p.birth_place_id AS pl, p.entity_id AS pid FROM people p '
                . 'UNION ALL SELECT p.death_place_id, p.entity_id FROM people p) x JOIN entities e ON e.id=x.pid AND ' . Entities::PUBLIC_WHERE . ' '
                . "WHERE pl IN ({$ph}) GROUP BY pl", $ids) as $r) {
                $places[$r['pl']]['people'] = (int) $r['n'];
            }
            foreach ($db->col('SELECT DISTINCT entity_id FROM conflicting_accounts WHERE is_public=1 AND concerns_location=1 '
                . "AND entity_id IN ({$ph})", $ids) as $id) {
                $places[$id]['disputed'] = true;       // sources disagree about where this place is
            }
            foreach (Atlas::placeRelations($db, $ids) as $pl => $rel) {
                $persons = array_keys($rel['persons']);
                $orgs = array_keys($rel['orgs']);
                sort($persons, SORT_STRING);
                sort($orgs, SORT_STRING);
                $places[$pl] += ['persons' => $persons, 'orgs' => $orgs, 'items' => $rel['items']];
            }
        }
        return array_values($places);
    }

    /** Places documented for one person: birth and death places, places of their events and affiliations. */
    public static function personPlaceIds(Db $db, string $personPublicId): ?array
    {
        $pe = $db->one("SELECT e.id FROM entities e WHERE e.public_id=? AND e.kind='person' AND " . Entities::PUBLIC_WHERE, [$personPublicId]);
        if (!$pe) {
            return null;
        }
        return $db->col("SELECT DISTINCT e.public_id FROM entities e WHERE e.kind='place' AND " . Entities::PUBLIC_WHERE . ' AND e.id IN ('
            . 'SELECT birth_place_id FROM people WHERE entity_id=:p UNION SELECT death_place_id FROM people WHERE entity_id=:p '
            . 'UNION SELECT ep.place_id FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id '
            . 'JOIN entities ee ON ee.id=x.event_id AND ' . self::pub('ee') . " WHERE x.person_id=:p AND x.publication_status='published' "
            . "UNION SELECT place_id FROM affiliations WHERE person_id=:p AND publication_status='published' AND visibility='public')", ['p' => $pe['id']]);
    }

    public static function latestEvents(Db $db, int $limit = 5): array
    {
        return $db->all('SELECT e.slug, ev.title, ev.summary, ev.date_start, ev.date_end, ev.date_precision FROM entities e JOIN events ev ON ev.entity_id=e.id '
            . "WHERE e.kind='event' AND " . Entities::PUBLIC_WHERE . " AND ev.date_precision<>'unknown' ORDER BY ev.date_start LIMIT ?", [$limit]);
    }

    /** Real counts of PUBLIC records. Never fabricated. */
    public static function counts(Db $db): array
    {
        $out = [];
        foreach ($db->all('SELECT e.kind, COUNT(*) AS n FROM entities e WHERE ' . Entities::PUBLIC_WHERE . ' GROUP BY e.kind') as $r) {
            $out[$r['kind']] = (int) $r['n'];
        }
        return $out;
    }

    public static function sitemapEntries(Db $db): array
    {
        return $db->all('SELECT e.kind, e.slug, e.updated_at FROM entities e LEFT JOIN archive_items a ON a.entity_id=e.id '
            . 'WHERE ' . Entities::PUBLIC_WHERE . " AND e.is_fictional_test=0 AND (e.kind IN ('person','family','place','event','source','organization') "
            . "OR (e.kind='archive_item' AND " . self::publicItem() . ')) ORDER BY e.kind, e.id LIMIT 50000');
    }
}
