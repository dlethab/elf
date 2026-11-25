<?php
declare(strict_types=1);

namespace Elf;

use Elf\Services\Dates;
use Elf\Services\Entities;

/**
 * Read-side data for the historical atlas (the 3D map): marker categories, place and record previews, and the
 * geographic associations of any public record.
 *
 * Rules (the same as every public page):
 * - only published, public, unmerged records are returned, and archive items only when their own access level and
 *   rights allow display;
 * - a record is placed on the map ONLY through a public place with documented coordinates; nothing is located by
 *   guesswork, and records without such a place say so;
 * - two places are never linked on the map just because both appear in it; links come from records.
 */
final class Atlas
{
    /** Marker shape by place type. Shapes (not colour) carry the category; the outline carries precision. */
    public const MARKER_CATEGORY = [
        'town_city' => 'settlement', 'village' => 'settlement', 'historical_settlement' => 'settlement',
        'region' => 'area', 'geographic_feature' => 'area',
        'conflict_location' => 'conflict',
        'historical_site' => 'site', 'memorial_site' => 'site', 'organizational_location' => 'site',
        'displacement_location' => 'site', 'other' => 'site',
    ];
    public const CATEGORY_LABELS = ['settlement' => 'Town, city or village', 'area' => 'Region or geographic area',
        'conflict' => 'Conflict or battle location', 'site' => 'Historical, memorial or organizational site'];
    public const LOCATION_FIELDS = ['latitude', 'longitude', 'coord_precision', 'coord_note', 'location', 'coordinates'];
    /** Event shape by event type (the timeline's markers; colour is secondary and never the only cue). */
    public const EVENT_CATEGORY = [
        'battle_conflict' => 'conflict',
        'political_development' => 'political', 'organizational_development' => 'political', 'meeting_conference' => 'political',
        'statement_publication' => 'political',
        'personal_life_event' => 'people', 'displacement_migration' => 'people', 'humanitarian_event' => 'people',
        'community_event' => 'community', 'commemoration' => 'community', 'other' => 'community',
    ];
    public const EVENT_CATEGORY_LABELS = ['conflict' => 'Armed conflict', 'political' => 'Political and organizational',
        'people' => 'Lives, displacement and humanitarian', 'community' => 'Community, commemoration and other'];
    public const SUMMARY_FIELDS = ['event' => 'summary', 'person' => 'summary', 'organization' => 'description', 'archive_item' => 'description',
        'oral_history' => 'summary', 'family' => 'summary', 'source' => 'provenance', 'place' => 'overview', 'collection' => 'description'];

    public static function category(?string $placeTypeSlug): string
    {
        return self::MARKER_CATEGORY[$placeTypeSlug ?: 'other'] ?? 'site';
    }

    public static function eventCategory(?string $typeSlug): string
    {
        return self::EVENT_CATEGORY[$typeSlug ?: 'other'] ?? 'community';
    }

    public static function validCoords(mixed $lat, mixed $lon): bool
    {
        return $lat !== null && $lon !== null && $lat >= -90 && $lat <= 90 && $lon >= -180 && $lon <= 180;
    }

    private static function fmt(?callable $fmt): callable
    {
        return $fmt ?? fn ($s, $e, $p) => Dates::format($s, $e, $p);
    }

    /** For each mapped place: public people and organizations linked to it by a record, and the number of public archive items about it. */
    public static function placeRelations(Db $db, array $placeIds): array
    {
        $out = [];
        foreach ($placeIds as $pid) {
            $out[$pid] = ['persons' => [], 'orgs' => [], 'items' => 0];
        }
        if (!$placeIds) {
            return $out;
        }
        $ph = implode(',', array_fill(0, count($placeIds), '?'));
        $ids = array_values($placeIds);
        $peopleSql = 'SELECT x.pl, pe.public_id FROM ('
            . '  SELECT birth_place_id AS pl, entity_id AS pid FROM people UNION SELECT death_place_id, entity_id FROM people'
            . '  UNION SELECT ep.place_id, x.person_id FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id'
            . '    JOIN entities ee ON ee.id=x.event_id AND ' . Queries::pub('ee') . " WHERE x.person_id IS NOT NULL AND x.publication_status='published'"
            . "  UNION SELECT place_id, person_id FROM affiliations WHERE publication_status='published' AND visibility='public'"
            . ') x JOIN entities pe ON pe.id=x.pid AND ' . Queries::pub('pe') . " WHERE x.pl IN ({$ph})";
        foreach ($db->all($peopleSql, $ids) as $r) {
            $out[$r['pl']]['persons'][$r['public_id']] = true;
        }
        $orgSql = 'SELECT x.pl, oe.public_id FROM ('
            . '  SELECT ep.place_id AS pl, x.organization_id AS oid FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id'
            . '    JOIN entities ee ON ee.id=x.event_id AND ' . Queries::pub('ee') . " WHERE x.organization_id IS NOT NULL AND x.publication_status='published'"
            . "  UNION SELECT place_id, organization_id FROM affiliations WHERE publication_status='published' AND visibility='public'"
            . ') x JOIN entities oe ON oe.id=x.oid AND ' . Queries::pub('oe') . " WHERE x.pl IN ({$ph})";
        foreach ($db->all($orgSql, $ids) as $r) {
            $out[$r['pl']]['orgs'][$r['public_id']] = true;
        }
        foreach ($db->all('SELECT s.subject_id AS pl, COUNT(*) AS n FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND ' . Entities::PUBLIC_WHERE . ' '
            . 'JOIN archive_items a ON a.entity_id=e.id AND ' . Queries::publicItem() . " WHERE s.subject_id IN ({$ph}) GROUP BY s.subject_id", $ids) as $r) {
            $out[$r['pl']]['items'] = (int) $r['n'];
        }
        return $out;
    }

    private static function publicEntity(Db $db, ?string $publicId): ?array
    {
        return $publicId ? $db->one('SELECT e.* FROM entities e WHERE e.public_id=? AND ' . Entities::PUBLIC_WHERE, [$publicId]) : null;
    }

    /**
     * Public archive items about a record (their own access level and rights allow display), with the details a
     * caption needs: what it is, when it was made (if known), who made it and its rights.
     */
    public static function photos(Db $db, int $entityId, int $limit = 6, ?callable $fmt = null): array
    {
        $fmt = self::fmt($fmt);
        $out = [];
        foreach (array_slice(Queries::recordPhotos($db, $entityId), 0, $limit) as $p) {
            $known = !in_array($p['created_precision'], [null, 'unknown'], true);
            $out[] = ['title' => $p['title'], 'url' => Queries::recordUrl('archive_item', $p['slug']),
                'thumb' => $p['thumb_key'] ? Queries::mediaUrl($p['thumb_key']) : null, 'item_type' => $p['item_type'],
                'date' => $known ? $fmt($p['created_start'], $p['created_end'], $p['created_precision']) : null,
                'creator' => $p['creator'], 'rights_holder' => $p['rights_holder'], 'rights' => $p['rights_status']];
        }
        return $out;
    }

    /**
     * The first public image with a thumbnail: shown at the top of a panel, always with its caption and a link to the
     * full archive record. Never a stand-in or generated picture: no image, no lead.
     */
    public static function leadImage(array $photos): ?array
    {
        foreach ($photos as $ph) {
            if ($ph['thumb']) {
                return $ph;
            }
        }
        return null;
    }

    /**
     * Public families with a public member documented at this place: born or died here, or took part in an event here.
     * The link is derived from those records, and the number of such members is given.
     */
    public static function placeFamilies(Db $db, int $placeId, int $limit = 8): array
    {
        $rows = $db->all('SELECT fe.slug, f.display_name, COUNT(DISTINCT x.pid) AS n FROM ('
            . '  SELECT entity_id AS pid FROM people WHERE birth_place_id=:p OR death_place_id=:p'
            . '  UNION SELECT x.person_id FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id'
            . '    JOIN entities ee ON ee.id=x.event_id AND ' . Queries::pub('ee')
            . "    WHERE ep.place_id=:p AND x.person_id IS NOT NULL AND x.publication_status='published'"
            . ') x JOIN entities pe ON pe.id=x.pid AND ' . Queries::pub('pe') . ' '
            . "JOIN family_memberships m ON m.person_id=x.pid AND m.publication_status='published' AND m.visibility='public' "
            . 'JOIN entities fe ON fe.id=m.family_id AND ' . Queries::pub('fe') . ' JOIN families f ON f.entity_id=fe.id '
            . 'GROUP BY fe.id ORDER BY n DESC, lower(f.display_name) LIMIT :n', ['p' => $placeId, 'n' => $limit]);
        return array_map(fn ($r) => ['title' => $r['display_name'], 'url' => Queries::recordUrl('family', $r['slug']), 'n' => (int) $r['n']], $rows);
    }

    /** Public collections holding public archive items about any of these records. */
    public static function subjectCollections(Db $db, array $subjectIds, int $limit = 4): array
    {
        if (!$subjectIds) {
            return [];
        }
        $ph = implode(',', array_fill(0, count($subjectIds), '?'));
        $rows = $db->all('SELECT ce.slug, c.title, COUNT(DISTINCT ci.item_id) AS n FROM archive_item_subjects s '
            . 'JOIN entities ie ON ie.id=s.item_id AND ' . Queries::pub('ie') . ' JOIN archive_items a ON a.entity_id=ie.id AND ' . Queries::publicItem() . ' '
            . 'JOIN collection_items ci ON ci.item_id=s.item_id JOIN entities ce ON ce.id=ci.collection_id AND ' . Queries::pub('ce') . ' '
            . "JOIN collections c ON c.entity_id=ce.id WHERE s.subject_id IN ({$ph}) GROUP BY ce.id ORDER BY n DESC, lower(c.title) LIMIT ?",
            [...array_values($subjectIds), $limit]);
        return array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('collection', $r['slug']), 'n' => (int) $r['n']], $rows);
    }

    /** Public differing accounts about where a place is. */
    public static function locationDisputes(Db $db, int $entityId): array
    {
        return array_map(fn ($r) => ['topic' => $r['topic'], 'text' => $r['account_text'], 'by' => $r['attributed_to']],
            $db->all('SELECT topic, account_text, attributed_to FROM conflicting_accounts WHERE entity_id=? AND is_public=1 AND concerns_location=1 ORDER BY id', [$entityId]));
    }

    private static function cut(?string $text, int $n): string
    {
        $text = (string) $text;
        return mb_substr($text, 0, $n) . (mb_strlen($text) > $n ? '…' : '');
    }

    /** Everything the place panel shows, or null if the place is not public. */
    public static function placePreview(Db $db, ?string $publicId, ?callable $fmt = null): ?array
    {
        $fmt = self::fmt($fmt);
        $e = self::publicEntity($db, $publicId);
        if (!$e || $e['kind'] !== 'place') {
            return null;
        }
        $eid = (int) $e['id'];
        $p = $db->one('SELECT p.*, t.slug AS type_slug, t.label AS type_label FROM places p LEFT JOIN place_types t ON t.id=p.place_type_id WHERE p.entity_id=?', [$eid]);
        $events = array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('event', $r['slug']),
            'date' => $fmt($r['date_start'], $r['date_end'], $r['date_precision']),
            'precision' => $r['date_precision'], 'uncertain_place' => (bool) $r['is_uncertain']], Queries::placeEvents($db, $eid));
        $people = [];
        $seen = [];
        foreach (Queries::placePeople($db, $eid) as $r) {
            $role = ($r['born'] && !$r['died']) ? 'Born here' : (($r['died'] && !$r['born']) ? 'Died here' : 'Born and died here');
            $people[] = ['title' => $r['preferred_name'], 'url' => Queries::recordUrl('person', $r['slug']), 'role' => $role];
            $seen[$r['slug']] = true;
        }
        foreach ($db->all('SELECT DISTINCT pe.slug, p.preferred_name FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id '
            . 'JOIN entities ee ON ee.id=x.event_id AND ' . Queries::pub('ee') . ' JOIN entities pe ON pe.id=x.person_id AND ' . Queries::pub('pe') . ' '
            . "JOIN people p ON p.entity_id=pe.id WHERE ep.place_id=? AND x.publication_status='published' ORDER BY p.preferred_name", [$eid]) as $r) {
            if (!isset($seen[$r['slug']])) {
                $people[] = ['title' => $r['preferred_name'], 'url' => Queries::recordUrl('person', $r['slug']), 'role' => 'Took part in an event here'];
                $seen[$r['slug']] = true;
            }
        }
        $orgs = array_map(fn ($r) => ['title' => $r['name'], 'url' => Queries::recordUrl('organization', $r['slug'])], $db->all(
            'SELECT DISTINCT oe.slug, o.name FROM affiliations a JOIN entities oe ON oe.id=a.organization_id AND ' . Queries::pub('oe') . ' '
            . "JOIN organizations o ON o.entity_id=oe.id WHERE a.place_id=? AND a.publication_status='published' AND a.visibility='public' "
            . 'UNION SELECT oe.slug, o.name FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id '
            . 'JOIN entities ee ON ee.id=x.event_id AND ' . Queries::pub('ee') . ' JOIN entities oe ON oe.id=x.organization_id AND ' . Queries::pub('oe') . ' '
            . "JOIN organizations o ON o.entity_id=oe.id WHERE ep.place_id=? AND x.publication_status='published' ORDER BY 2", [$eid, $eid]));
        $cites = Queries::citations($db, $eid);
        $loc = [];
        foreach ($cites as $c) {
            if (in_array($c['field_name'] ?? '', self::LOCATION_FIELDS, true)) {
                $loc[] = ['title' => $c['title'], 'url' => Queries::recordUrl('source', $c['source_slug']), 'locator' => $c['locator'], 'evidence' => $c['evidence_status']];
            }
        }
        $photos = self::photos($db, $eid, 6, $fmt);
        $valid = !in_array($p['valid_precision'], [null, 'unknown'], true) ? $fmt($p['valid_start'], $p['valid_end'], $p['valid_precision']) : null;
        return [
            'kind' => 'place', 'id' => $e['public_id'], 'title' => $p['primary_name'], 'url' => Queries::recordUrl('place', $e['slug']),
            'type_label' => $p['type_label'] ?: 'Other historically relevant place', 'category' => self::category($p['type_slug']),
            'region' => ($p['admin_region'] ?: $p['country']) ?: null, 'original_name' => $p['original_name'],
            'lat' => $p['latitude'] === null ? null : (float) $p['latitude'], 'lon' => $p['longitude'] === null ? null : (float) $p['longitude'],
            'precision' => $p['coord_precision'], 'note' => $p['coord_note'],
            'summary' => self::cut($p['overview'], 320), 'valid' => $valid,
            'names' => array_map(fn ($n) => ['name' => $n['name'], 'type' => $n['name_type']], Queries::names($db, $eid)),
            'lead' => self::leadImage($photos), 'photos' => $photos,
            'events' => $events, 'people' => array_slice($people, 0, 12), 'people_total' => count($people), 'orgs' => array_slice($orgs, 0, 8),
            'families' => self::placeFamilies($db, $eid), 'collections' => self::subjectCollections($db, [$eid]),
            'location_sources' => $loc, 'location_disputes' => self::locationDisputes($db, $eid),
            'sources_total' => count($cites), 'fictional' => (bool) $e['is_fictional_test'],
        ];
    }

    /**
     * Mapped public places documented for a record, and how many linked public places have no coordinates.
     * Returns [[{id, name, uncertain}], unmapped_count].
     */
    public static function recordPlaces(Db $db, array $entity): array
    {
        $kind = $entity['kind'];
        $eid = (int) $entity['id'];
        switch ($kind) {
            case 'place':
                [$sql, $args] = ['SELECT ? AS pl, 0 AS unc', [$eid]];
                break;
            case 'event':
                [$sql, $args] = ['SELECT place_id AS pl, is_uncertain AS unc FROM event_places WHERE event_id=?', [$eid]];
                break;
            case 'person':
                $sql = 'SELECT birth_place_id AS pl, 0 AS unc FROM people WHERE entity_id=:i UNION SELECT death_place_id, 0 FROM people WHERE entity_id=:i '
                    . 'UNION SELECT ep.place_id, ep.is_uncertain FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id '
                    . 'JOIN entities ee ON ee.id=x.event_id AND ' . Queries::pub('ee') . " WHERE x.person_id=:i AND x.publication_status='published' "
                    . "UNION SELECT place_id, 0 FROM affiliations WHERE person_id=:i AND publication_status='published' AND visibility='public'";
                $args = ['i' => $eid];
                break;
            case 'organization':
                $sql = 'SELECT ep.place_id AS pl, ep.is_uncertain AS unc FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id '
                    . 'JOIN entities ee ON ee.id=x.event_id AND ' . Queries::pub('ee') . " WHERE x.organization_id=:i AND x.publication_status='published' "
                    . "UNION SELECT place_id, 0 FROM affiliations WHERE organization_id=:i AND publication_status='published' AND visibility='public'";
                $args = ['i' => $eid];
                break;
            case 'archive_item':
                [$sql, $args] = ['SELECT subject_id AS pl, 0 AS unc FROM archive_item_subjects WHERE item_id=?', [$eid]];
                break;
            case 'oral_history':
                [$sql, $args] = ['SELECT subject_id AS pl, 0 AS unc FROM oral_history_subjects WHERE oral_history_id=?', [$eid]];
                break;
            default:
                return [[], 0];
        }
        $rows = $db->all("SELECT pe.public_id, p.primary_name, p.latitude, p.longitude, MAX(x.unc) AS unc FROM ({$sql}) x "
            . "JOIN entities pe ON pe.id=x.pl AND pe.kind='place' AND " . Queries::pub('pe') . ' JOIN places p ON p.entity_id=pe.id '
            . 'GROUP BY pe.public_id ORDER BY lower(p.primary_name)', $args);
        $mapped = [];
        foreach ($rows as $r) {
            if (self::validCoords($r['latitude'], $r['longitude'])) {
                $mapped[] = ['id' => $r['public_id'], 'name' => $r['primary_name'], 'uncertain' => (bool) $r['unc']];
            }
        }
        return [$mapped, count($rows) - count($mapped)];
    }

    private static function recordDate(string $kind, array $sub, callable $fmt): ?string
    {
        $fd = function (string $prefix) use ($sub, $fmt) {
            $prec = $sub["{$prefix}_precision"] ?? null;
            return ($prec && $prec !== 'unknown') ? $fmt($sub["{$prefix}_start"], $sub["{$prefix}_end"], $prec) : null;
        };
        switch ($kind) {
            case 'event':
                return $fd('date');
            case 'person':
                $b = $fd('birth');
                $d = $fd('death');
                return ($b || $d) ? ($b ?: '?') . ' – ' . ($d ?: '?') : null;
            case 'organization':
                return $fd('active');
            case 'archive_item':
                return $fd('created');
            case 'oral_history':
                return $fd('recorded');
        }
        return null;
    }

    /** A compact preview of any public record, with its places on the map. */
    public static function recordPreview(Db $db, ?string $publicId, ?callable $fmt = null): ?array
    {
        $fmt = self::fmt($fmt);
        $e = self::publicEntity($db, $publicId);
        if (!$e || !isset(Entities::KIND_TABLE[$e['kind']])) {
            return null;
        }
        $eid = (int) $e['id'];
        if ($e['kind'] === 'archive_item' && !$db->one('SELECT 1 FROM archive_items a WHERE a.entity_id=? AND ' . Queries::publicItem(), [$eid])) {
            return null;
        }
        $sub = $db->one('SELECT * FROM ' . Entities::KIND_TABLE[$e['kind']] . ' WHERE entity_id=?', [$eid]);
        $sf = self::SUMMARY_FIELDS[$e['kind']] ?? null;
        $text = ($sf && array_key_exists($sf, $sub)) ? (string) ($sub[$sf] ?? '') : '';
        [$places, $unmapped] = self::recordPlaces($db, $e);
        $thumb = null;
        $lead = null;
        $photos = [];
        if ($e['kind'] === 'archive_item') {
            $k = $db->val('SELECT ' . Queries::THUMB . ' FROM entities e WHERE e.id=?', [$eid]);
            $thumb = $k ? Queries::mediaUrl($k) : null;
        } else {
            $photos = self::photos($db, $eid, 60, $fmt);
            $lead = self::leadImage($photos);
        }
        $typeLabel = null;
        $extra = [];
        if ($e['kind'] === 'event') {
            $typeLabel = $sub['event_type_id'] ? $db->val('SELECT label FROM event_types WHERE id=?', [$sub['event_type_id']]) : null;
            $extra = self::eventDetails($db, $eid);
            $extra['precision'] = $sub['date_precision'];
            $extra['precision_note'] = !in_array($sub['date_precision'], [null, 'unknown'], true) ? Dates::precisionNote($sub['date_precision']) : null;
            $extra['category'] = self::eventCategory($sub['event_type_id'] ? $db->val('SELECT slug FROM event_types WHERE id=?', [$sub['event_type_id']]) : null);
        }
        return $extra + ['kind' => $e['kind'], 'id' => $e['public_id'], 'title' => $sub[Entities::TITLE_COL[$e['kind']]],
            'url' => Queries::recordUrl($e['kind'], $e['slug']), 'type_label' => $typeLabel, 'date' => self::recordDate($e['kind'], $sub, $fmt),
            'summary' => self::cut($text, 320), 'thumb' => $thumb, 'lead' => $lead,
            'photos_total' => count($photos), 'sources_total' => count(Queries::citations($db, $eid)),
            'places' => $places, 'unmapped' => $unmapped, 'fictional' => (bool) $e['is_fictional_test']];
    }

    // ───────────── timeline ─────────────
    /**
     * A recorded date string ('YYYY', 'YYYY-MM' or 'YYYY-MM-DD') as a decimal year: the start of the period it names,
     * or with $end the end of it. A year stays a whole year; it is never narrowed to a day.
     */
    public static function t(string $s, bool $end = false): float
    {
        $parts = array_map('intval', explode('-', $s));
        $y = $parts[0];
        if (count($parts) === 1) {
            return (float) ($y + ($end ? 1 : 0));
        }
        $m = $parts[1];
        if (count($parts) === 2) {
            return $y + ($m - 1 + ($end ? 1 : 0)) / 12;
        }
        $leap = ($y % 4 === 0 && $y % 100 !== 0) || $y % 400 === 0;
        $days = $leap ? 366 : 365;
        $doy = (int) (new \DateTimeImmutable(sprintf('%04d-%02d-%02d', $y, $m, $parts[2])))->format('z') + 1;
        return $y + ($doy - 1 + ($end ? 1 : 0)) / $days;
    }

    /**
     * [t0, t1, is_point] in decimal years, covering exactly what the record says and nothing more: a day is a point,
     * a month or a year is the whole month or year, a decade the whole decade, a range from the start of its first
     * date to the end of its last. Unknown dates return null (they are listed, not placed).
     */
    public static function dateInterval(?string $start, ?string $end, ?string $precision): ?array
    {
        if (in_array($precision, [null, 'unknown'], true) || !$start) {
            return null;
        }
        $t0 = self::t($start);
        $t1 = self::t($end ?: $start, true);
        if ($precision === 'decade') {
            $d = (int) substr($start, 0, 3) * 10;
            $t0 = (float) $d;
            $t1 = (float) ($d + 10);
        }
        if ($t1 < $t0) {
            [$t0, $t1] = [$t1, $t0];
        }
        $point = $precision === 'exact' && count(explode('-', $start)) === 3 && (!$end || $end === $start);
        return [round($t0, 4), round($t1, 4), $point];
    }

    /**
     * Every public event with what the interactive timeline needs. Filtering happens in the browser with the same
     * rules as the server-rendered list (Queries::timeline), so the two never disagree.
     */
    public static function timelineEvents(Db $db, ?callable $fmt = null): array
    {
        $fmt = self::fmt($fmt);
        $rows = $db->all('SELECT e.id, e.public_id, e.slug, e.is_fictional_test, ev.title, ev.summary, ev.date_start, ev.date_end, ev.date_precision, '
            . 't.slug AS type_slug, t.label AS type_label FROM entities e JOIN events ev ON ev.entity_id=e.id '
            . "LEFT JOIN event_types t ON t.id=ev.event_type_id WHERE e.kind='event' AND " . Entities::PUBLIC_WHERE . ' '
            . 'ORDER BY ev.date_start IS NULL, ev.date_start, lower(ev.title) LIMIT 5000');
        $out = [];
        foreach ($rows as $r) {
            $iv = self::dateInterval($r['date_start'], $r['date_end'], $r['date_precision']);
            $span = $iv ? Dates::yearSpan($r['date_start'], $r['date_end'], $r['date_precision']) : null;
            $out[$r['id']] = [
                'id' => $r['public_id'], 'title' => $r['title'], 'url' => Queries::recordUrl('event', $r['slug']),
                'date' => $fmt($r['date_start'], $r['date_end'], $r['date_precision']), 'precision' => $r['date_precision'],
                't0' => $iv[0] ?? null, 't1' => $iv[1] ?? null, 'point' => $iv[2] ?? false,
                'from' => $span[0] ?? null, 'to' => $span ? max($span) : null,
                'type' => $r['type_slug'] ?: 'other', 'type_label' => $r['type_label'] ?: 'Other historical event',
                'category' => self::eventCategory($r['type_slug']),
                'summary' => self::cut($r['summary'], 240),
                'places' => [], 'persons' => [], 'orgs' => [], 'media' => 0, 'date_disputed' => false, 'fictional' => (bool) $r['is_fictional_test']];
        }
        if (!$out) {
            return [];
        }
        $ids = array_keys($out);
        $ph = implode(',', array_fill(0, count($ids), '?'));
        foreach ($db->all('SELECT x.event_id, pe.public_id, p.primary_name, p.latitude, p.longitude, p.admin_region, p.coord_precision, x.is_uncertain '
            . 'FROM event_places x JOIN entities pe ON pe.id=x.place_id AND ' . Queries::pub('pe') . ' JOIN places p ON p.entity_id=pe.id '
            . "WHERE x.event_id IN ({$ph}) ORDER BY lower(p.primary_name)", $ids) as $r) {
            $out[$r['event_id']]['places'][] = ['id' => $r['public_id'], 'name' => $r['primary_name'], 'region' => $r['admin_region'],
                'mapped' => self::validCoords($r['latitude'], $r['longitude']), 'precision' => $r['coord_precision'], 'uncertain' => (bool) $r['is_uncertain']];
        }
        foreach ($db->all('SELECT x.event_id, pe.public_id, x.person_id IS NOT NULL AS is_person FROM event_participants x '
            . 'JOIN entities pe ON pe.id=COALESCE(x.person_id, x.organization_id) AND ' . Queries::pub('pe') . ' '
            . "WHERE x.event_id IN ({$ph}) AND x.publication_status='published'", $ids) as $r) {
            $out[$r['event_id']][$r['is_person'] ? 'persons' : 'orgs'][] = $r['public_id'];
        }
        foreach ($db->all('SELECT s.subject_id AS ev, COUNT(*) AS n FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND ' . Entities::PUBLIC_WHERE . ' '
            . 'JOIN archive_items a ON a.entity_id=e.id AND ' . Queries::publicItem() . " WHERE s.subject_id IN ({$ph}) GROUP BY s.subject_id", $ids) as $r) {
            $out[$r['ev']]['media'] += (int) $r['n'];
        }
        foreach ($db->all('SELECT s.subject_id AS ev, COUNT(*) AS n FROM oral_history_subjects s JOIN entities e ON e.id=s.oral_history_id AND ' . Entities::PUBLIC_WHERE . ' '
            . "WHERE s.subject_id IN ({$ph}) GROUP BY s.subject_id", $ids) as $r) {
            $out[$r['ev']]['media'] += (int) $r['n'];
        }
        foreach ($db->col("SELECT DISTINCT entity_id FROM conflicting_accounts WHERE is_public=1 AND concerns_date=1 AND entity_id IN ({$ph})", $ids) as $id) {
            $out[$id]['date_disputed'] = true;
        }
        return array_values($out);
    }

    /** The extra parts of an event preview: people, organizations, places with their precision, and date disagreements. */
    public static function eventDetails(Db $db, int $entityId): array
    {
        $people = array_map(fn ($r) => ['title' => $r['name'], 'url' => Queries::recordUrl($r['kind'], $r['slug']), 'role' => $r['role'], 'kind' => $r['kind']],
            Queries::eventParticipants($db, $entityId));
        $places = array_map(fn ($r) => ['id' => $r['public_id'], 'title' => $r['primary_name'], 'url' => Queries::recordUrl('place', $r['slug']),
            'precision' => $r['coord_precision'], 'mapped' => self::validCoords($r['latitude'], $r['longitude']), 'uncertain' => (bool) $r['is_uncertain'],
            'region' => $r['admin_region']], $db->all('SELECT pe.public_id, pe.slug, p.primary_name, p.coord_precision, p.latitude, p.longitude, p.admin_region, x.is_uncertain '
            . 'FROM event_places x JOIN entities pe ON pe.id=x.place_id AND ' . Queries::pub('pe') . ' JOIN places p ON p.entity_id=pe.id '
            . 'WHERE x.event_id=? ORDER BY lower(p.primary_name)', [$entityId]));
        $disputes = array_map(fn ($r) => ['topic' => $r['topic'], 'text' => $r['account_text'], 'by' => $r['attributed_to']],
            $db->all('SELECT topic, account_text, attributed_to FROM conflicting_accounts WHERE entity_id=? AND is_public=1 AND concerns_date=1 ORDER BY id', [$entityId]));
        return ['people' => array_slice(array_values(array_filter($people, fn ($p) => $p['kind'] === 'person')), 0, 8),
            'orgs' => array_slice(array_values(array_filter($people, fn ($p) => $p['kind'] === 'organization')), 0, 6),
            'event_places' => $places, 'date_disputes' => $disputes];
    }

    /** Other public events sharing a documented place or participant with this one (the reason is given). */
    public static function relatedEvents(Db $db, int $entityId, int $limit = 8, ?callable $fmt = null): array
    {
        $fmt = self::fmt($fmt);
        $rows = $db->all('SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, MIN(x.why) AS why FROM ('
            . "  SELECT b.event_id AS eid, 'place' AS why FROM event_places a JOIN event_places b ON b.place_id=a.place_id AND b.event_id<>a.event_id "
            . '    JOIN entities pe ON pe.id=a.place_id AND ' . Queries::pub('pe') . ' WHERE a.event_id=:i'
            . "  UNION SELECT b.event_id, 'participant' FROM event_participants a JOIN event_participants b "
            . '    ON (b.person_id=a.person_id OR b.organization_id=a.organization_id) AND b.event_id<>a.event_id '
            . '    JOIN entities pe ON pe.id=COALESCE(a.person_id, a.organization_id) AND ' . Queries::pub('pe') . ' '
            . "    WHERE a.event_id=:i AND a.publication_status='published' AND b.publication_status='published'"
            . ') x JOIN entities e ON e.id=x.eid AND ' . Entities::PUBLIC_WHERE . ' JOIN events ev ON ev.entity_id=e.id '
            . 'GROUP BY e.id ORDER BY ev.date_start IS NULL, ev.date_start LIMIT :limit', ['i' => $entityId, 'limit' => $limit]);
        return array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('event', $r['slug']), 'why' => $r['why'],
            'date' => $fmt($r['date_start'], $r['date_end'], $r['date_precision'])], $rows);
    }

    // ───────────── context for a period ─────────────
    /**
     * A short, record-derived summary of the events matching the explore filters (a period, region or event type): how
     * many there are and how their dates are known, the most frequent event types, and the places, people, families,
     * collections and sources most often linked to them. Counts only; no narrative is written, and "most documented"
     * means most cited sources, never an editorial judgement of importance.
     */
    public static function periodContext(Db $db, array $f, int $limit = 5): array
    {
        [$dated] = Queries::timeline($db, $f);
        if (!$dated) {
            return ['n' => 0];
        }
        $ids = array_map('intval', $db->col('SELECT id FROM entities WHERE public_id IN (' . implode(',', array_fill(0, count($dated), '?')) . ')',
            array_column($dated, 'public_id')));
        $ph = implode(',', array_fill(0, count($ids), '?'));
        $counter = [];
        foreach ($dated as $r) {
            $k = $r['type_label'] ?: 'Other historical event';
            $counter[$k] = ($counter[$k] ?? 0) + 1;
        }
        $types = [];
        foreach ($counter as $label => $n) {
            $types[] = ['label' => (string) $label, 'n' => $n];
        }
        usort($types, fn ($a, $b) => $b['n'] <=> $a['n']);      // stable: ties keep their first-seen order
        $types = array_slice($types, 0, 4);
        $top = fn (string $sql) => $db->all($sql, $ids);
        $events = $top('SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, COUNT(DISTINCT c.source_id) AS n '
            . 'FROM entities e JOIN events ev ON ev.entity_id=e.id JOIN citations c ON c.target_id=e.id '
            . 'JOIN entities se ON se.id=c.source_id AND ' . Queries::pub('se') . " WHERE e.id IN ({$ph}) GROUP BY e.id "
            . "ORDER BY n DESC, ev.date_start LIMIT {$limit}");
        $places = $top('SELECT pe.id AS eid, pe.slug, pe.public_id, p.primary_name AS title, p.latitude IS NOT NULL AS mapped, COUNT(DISTINCT x.event_id) AS n '
            . 'FROM event_places x JOIN entities pe ON pe.id=x.place_id AND ' . Queries::pub('pe') . ' JOIN places p ON p.entity_id=pe.id '
            . "WHERE x.event_id IN ({$ph}) GROUP BY pe.id ORDER BY n DESC, lower(p.primary_name) LIMIT {$limit}");
        $people = $top('SELECT pe.id, pe.slug, p.preferred_name AS title, COUNT(DISTINCT x.event_id) AS n FROM event_participants x '
            . 'JOIN entities pe ON pe.id=x.person_id AND ' . Queries::pub('pe') . ' JOIN people p ON p.entity_id=pe.id '
            . "WHERE x.event_id IN ({$ph}) AND x.publication_status='published' GROUP BY pe.id ORDER BY n DESC, lower(p.preferred_name) LIMIT {$limit}");
        $families = $top('SELECT fe.slug, f.display_name AS title, COUNT(DISTINCT x.person_id) AS n FROM event_participants x '
            . 'JOIN entities pe ON pe.id=x.person_id AND ' . Queries::pub('pe') . ' '
            . "JOIN family_memberships m ON m.person_id=x.person_id AND m.publication_status='published' AND m.visibility='public' "
            . 'JOIN entities fe ON fe.id=m.family_id AND ' . Queries::pub('fe') . ' JOIN families f ON f.entity_id=fe.id '
            . "WHERE x.event_id IN ({$ph}) AND x.publication_status='published' GROUP BY fe.id ORDER BY n DESC, lower(f.display_name) LIMIT {$limit}");
        $sources = $top('SELECT se.slug, s.title, COUNT(DISTINCT c.target_id) AS n FROM citations c '
            . 'JOIN entities se ON se.id=c.source_id AND ' . Queries::pub('se') . ' JOIN sources s ON s.entity_id=se.id '
            . "WHERE c.target_id IN ({$ph}) GROUP BY se.id ORDER BY n DESC, lower(s.title) LIMIT {$limit}");
        $uncertain = count(array_filter($dated, fn ($r) => in_array($r['date_precision'], ['approximate', 'decade'], true)));
        $years = [];
        foreach ($dated as $r) {
            $years[] = (int) substr($r['date_start'], 0, 4);
            $years[] = (int) substr($r['date_end'] ?: $r['date_start'], 0, 4);
        }
        return [
            'n' => count($dated), 'uncertain' => $uncertain, 'first' => min($years), 'last' => max($years),
            'types' => $types,
            'events' => array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('event', $r['slug']), 'n' => (int) $r['n'],
                'date_start' => $r['date_start'], 'date_end' => $r['date_end'], 'precision' => $r['date_precision']], $events),
            'places' => array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('place', $r['slug']), 'id' => $r['public_id'],
                'mapped' => (bool) $r['mapped'], 'n' => (int) $r['n']], $places),
            'people' => array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('person', $r['slug']), 'n' => (int) $r['n']], $people),
            'families' => array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('family', $r['slug']), 'n' => (int) $r['n']], $families),
            'collections' => self::subjectCollections($db, array_merge($ids, array_map(fn ($p) => (int) $p['eid'], $places)), 3),
            'sources' => array_map(fn ($r) => ['title' => $r['title'], 'url' => Queries::recordUrl('source', $r['slug']), 'n' => (int) $r['n']], $sources),
        ];
    }
}
