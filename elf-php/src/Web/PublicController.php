<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Atlas;
use Elf\Config;
use Elf\Http\Response;
use Elf\I18n;
use Elf\Queries;
use Elf\Security;
use Elf\Services\Audit;
use Elf\Services\Collections;
use Elf\Services\Dates;
use Elf\Services\Entities;
use Elf\Services\Explorations;
use Elf\Services\Families;
use Elf\Services\Graph;
use Elf\Services\Oral;
use Elf\Services\Photos;
use Elf\Services\RateLimit;
use Elf\Services\Records;
use Elf\Services\Search;
use Elf\Services\Storage;
use Elf\Vocab;

/**
 * Public, anonymous-safe pages. Every record lookup goes through Entities::resolvePublic / PUBLIC_WHERE, so drafts,
 * restricted (e.g. living) people and merged records 404 exactly like records that never existed.
 */
final class PublicController extends Controller
{
    public const LIST_KINDS = ['people' => 'person', 'families' => 'family', 'places' => 'place', 'events' => 'event',
        'sources' => 'source', 'organizations' => 'organization'];
    public const SECTION_TITLES = ['person' => 'People', 'family' => 'Families', 'place' => 'Places', 'event' => 'Events',
        'source' => 'Sources', 'organization' => 'Organizations', 'archive_item' => 'Digital Archive'];
    public const INFO_PAGES = ['about' => 'About the archive', 'standards' => 'Historical and editorial standards',
        'how-to-contribute' => 'How to contribute', 'corrections' => 'How to submit corrections',
        'privacy' => 'Privacy policy', 'terms' => 'Terms of use', 'copyright' => 'Copyright and permissions',
        'accessibility' => 'Accessibility statement', 'data-policy' => 'Data and licensing policy'];
    private const LIST_PAGE = 300;

    public static function routes(App $app): void
    {
        $c = new self($app);
        $c->route('GET', '/', 'home', 'public.home');
        $c->route('GET', '/id/<public_id>', 'byPermanentId', 'public.by_permanent_id');
        foreach (self::LIST_KINDS as $section => $_kind) {
            $app->router->add('GET', "/{$section}", fn () => $c->listPage($section), "public.list_{$section}");
        }
        $c->route('GET', '/people/<slug>', 'person', 'public.person');
        $c->route('GET', '/families/<slug>', 'family', 'public.family');
        $c->route('GET', '/places/<slug>', 'place', 'public.place');
        $c->route('GET', '/events/<slug>', 'event', 'public.event');
        $c->route('GET', '/families/<slug>/tree', 'familyTree', 'public.family_tree');
        $c->route('GET', '/people/<slug>/tree', 'personTree', 'public.person_tree');
        $c->route('GET', '/people/<slug>/connections', 'personConnections', 'public.person_connections');
        $c->route('GET', '/organizations/<slug>', 'organization', 'public.organization');
        $c->route('GET', '/sources/<slug>', 'source', 'public.source');
        $c->route('GET', '/search', 'searchPage', 'public.search_page');
        $c->route('GET', '/timeline/data.json', 'timelineJson', 'public.timeline_json');
        $c->route('GET', '/explore', 'explore', 'public.explore');
        $c->route('GET', '/map', 'mapPage', 'public.map_page');
        $c->route('GET', '/timeline', 'timeline', 'public.timeline');
        $c->route('GET', '/explore/curated', 'curatedList', 'public.curated_list');
        $c->route('GET', '/explore/curated/<slug>', 'curated', 'public.curated');
        $c->route('GET', '/map/data.json', 'mapJson', 'public.map_json');
        $c->route('GET', '/map/place/<public_id>.json', 'mapPlace', 'public.map_place');
        $c->route('GET', '/map/record/<public_id>.json', 'mapRecord', 'public.map_record');
        $c->route('GET', '/explore/context.json', 'exploreContext', 'public.explore_context');
        $c->route('GET', '/map/review.json', 'mapReview', 'public.map_review');
        $c->route('GET', '/map/search.json', 'mapSearch', 'public.map_search');
        $c->route('GET', '/map/places.json', 'mapPlaces', 'public.map_places');
        $c->route('GET', '/map/basemap.json', 'basemap', 'public.basemap');
        $c->route('GET', '/archive', 'archiveList', 'public.archive_list');
        $c->route('GET', '/archive/<slug>', 'archiveItem', 'public.archive_item');
        $c->route('GET', '/media/<key>', 'media', 'public.media');
        $c->route('GET', '/lookup/<any(person,family,place,event,organization,source,archive_item,any):kind>', 'lookup', 'public.lookup');
        $c->route('GET', '/language/<code>', 'setLanguage', 'public.set_language');
        $c->route('GET', '/collections', 'collectionList', 'public.collection_list');
        $c->route('GET', '/collections/<slug>', 'collection', 'public.collection');
        $c->route('GET', '/oral-histories', 'oralList', 'public.oral_list');
        $c->route('GET|POST', '/oral-histories/request', 'interviewRequest', 'public.interview_request');
        $c->route('GET', '/oral-histories/<slug>', 'oralHistory', 'public.oral_history');
        $c->route('GET', '/<any(' . implode(',', array_keys(self::INFO_PAGES)) . '):page>', 'info', 'public.info');
        $c->route('GET|POST', '/contact', 'contact', 'public.contact');
        $c->route('GET', '/robots.txt', 'robots', 'public.robots');
        $c->route('GET', '/sitemap.xml', 'sitemap', 'public.sitemap');
    }

    private function fmt(): callable
    {
        return I18n::fdate(...);
    }

    /** [entity, null] or [null, redirect response]; 404 for anything not public. */
    private function resolve(string $kind, string $slug): array
    {
        $res = Entities::resolvePublic($this->db(), $kind, $slug);
        if ($res === null) {
            $this->abort(404);
        }
        [$state, $e] = $res;
        if ($state === 'redirect') {
            return [null, $this->redirect(Queries::recordUrl($kind, $e['slug']), 301)];
        }
        return [$e, null];
    }

    public function home(): Response
    {
        $db = $this->db();
        return $this->render('home.html', ['counts' => Queries::counts($db), 'events' => Queries::latestEvents($db, 5),
            'featured' => array_slice(Collections::publicList($db, true, 6), 0, 3)]);
    }

    /** Permanent identifier → current canonical URL (follows merges). */
    public function byPermanentId(string $publicId): Response
    {
        $db = $this->db();
        $e = Entities::getByPublicId($db, $publicId);
        if (!$e) {
            $this->abort(404);
        }
        $seen = [];
        while ($e && $e['merged_into'] && !isset($seen[$e['id']])) {
            $seen[$e['id']] = true;
            $e = Entities::get($db, $e['merged_into']);
        }
        $pub = $e ? Entities::getPublicByPublicId($db, $e['public_id']) : null;
        if (!$pub || !isset(Entities::URL_SECTION[$pub['kind']]) || !isset(self::SECTION_TITLES[$pub['kind']])) {
            $this->abort(404);
        }
        return $this->redirect(Queries::recordUrl($pub['kind'], $pub['slug']), 301);
    }

    // ───────────── lists ─────────────
    public function listPage(string $section): Response
    {
        $kind = self::LIST_KINDS[$section];
        $letter = mb_substr(mb_strtoupper(trim((string) $this->arg('letter', ''))), 0, 1) ?: null;
        [$rows, $total] = Queries::listPublic($this->db(), $kind, $this->page(), $letter);
        return $this->render('records/list.html', ['kind' => $kind, 'section' => $section, 'title' => self::SECTION_TITLES[$kind],
            'rows' => $rows, 'total' => $total, 'page' => $this->page(), 'per_page' => Queries::PER_PAGE, 'letter' => $letter]);
    }

    // ───────────── record pages ─────────────
    public function person(string $slug): Response
    {
        [$e, $r] = $this->resolve('person', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        $p = Queries::sub($db, $id, 'person');
        $photos = Queries::recordPhotos($db, $id);
        // The profile photograph: the first public image about this person (its own access level and rights allow
        // display). It is always captioned and links to its archive record; without one, no stand-in is shown.
        $portrait = null;
        $rest = [];
        foreach ($photos as $ph) {
            if ($portrait === null && $ph['media_kind'] === 'image' && ($ph['display_key'] || $ph['thumb_key'])) {
                $portrait = $ph;
            } else {
                $rest[] = $ph;
            }
        }
        return $this->render('records/person.html', ['e' => $e, 'p' => $p, 'names' => Queries::names($db, $id), 'portrait' => $portrait,
            'photos' => $rest,
            'birth_place' => Queries::placeLink($db, $p['birth_place_id']), 'death_place' => Queries::placeLink($db, $p['death_place_id']),
            'relationships' => Queries::personRelationships($db, $id), 'families' => Queries::personFamilies($db, $id),
            'events' => Queries::personEvents($db, $id), 'cites' => Queries::citations($db, $id), 'accts' => Queries::accounts($db, $id),
            'revisions' => Queries::publicRevisions($db, $id), 'affiliations' => Queries::personAffiliations($db, $id)]);
    }

    public function family(string $slug): Response
    {
        [$e, $r] = $this->resolve('family', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        return $this->render('records/family.html', ['e' => $e, 'f' => Queries::sub($db, $id, 'family'), 'names' => Queries::names($db, $id),
            'members' => Queries::familyMembers($db, $id), 'cites' => Queries::citations($db, $id), 'accts' => Queries::accounts($db, $id),
            'revisions' => Queries::publicRevisions($db, $id), 'can_propose' => $this->canProposeFor($e),
            'photos' => Queries::recordPhotos($db, $id)]);
    }

    private function canProposeFor(array $fam): bool
    {
        $u = $this->viewer();
        if (!$u) {
            return false;
        }
        if ($u->can('record.view_any')) {
            return true;
        }
        $grant = Families::activeGrant($this->db(), $u->id, (int) $fam['id']);
        return (bool) ($grant && $grant['can_propose_tree']);
    }

    public function place(string $slug): Response
    {
        [$e, $r] = $this->resolve('place', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        $p = Queries::sub($db, $id, 'place');
        $ptype = $p['place_type_id'] ? $db->one('SELECT label FROM place_types WHERE id=?', [$p['place_type_id']]) : null;
        return $this->render('records/place.html', ['e' => $e, 'p' => $p, 'ptype' => $ptype, 'names' => Queries::names($db, $id),
            'events' => Queries::placeEvents($db, $id), 'people' => Queries::placePeople($db, $id),
            'cites' => Queries::citations($db, $id), 'accts' => Queries::accounts($db, $id),
            'revisions' => Queries::publicRevisions($db, $id), 'photos' => Queries::recordPhotos($db, $id)]);
    }

    public function event(string $slug): Response
    {
        [$e, $r] = $this->resolve('event', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        $ev = Queries::sub($db, $id, 'event');
        $etype = $ev['event_type_id'] ? $db->one('SELECT label FROM event_types WHERE id=?', [$ev['event_type_id']]) : null;
        return $this->render('records/event.html', ['e' => $e, 'ev' => $ev, 'etype' => $etype, 'names' => Queries::names($db, $id),
            'places' => Queries::eventPlacesFor($db, $id), 'participants' => Queries::eventParticipants($db, $id),
            'cites' => Queries::citations($db, $id), 'accts' => Queries::accounts($db, $id),
            'revisions' => Queries::publicRevisions($db, $id), 'photos' => Queries::recordPhotos($db, $id),
            'details' => Atlas::eventDetails($db, $id), 'related' => Atlas::relatedEvents($db, $id, 8, $this->fmt()),
            'orals' => Queries::subjectOralHistories($db, $id),
            'year' => Dates::yearSpan($ev['date_start'], $ev['date_end'], $ev['date_precision'])]);
    }

    public function familyTree(string $slug): Response
    {
        [$e, $r] = $this->resolve('family', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $title = Queries::sub($db, (int) $e['id'], 'family')['display_name'];
        return $this->render('records/tree.html', ['e' => $e, 'kind' => 'family', 'title' => $title, 'tree' => Graph::familyTree($db, (int) $e['id'])]);
    }

    public function personTree(string $slug): Response
    {
        [$e, $r] = $this->resolve('person', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $title = Queries::sub($db, (int) $e['id'], 'person')['preferred_name'];
        return $this->render('records/tree.html', ['e' => $e, 'kind' => 'person', 'title' => $title, 'tree' => Graph::personTree($db, (int) $e['id'])]);
    }

    public function personConnections(string $slug): Response
    {
        [$e, $r] = $this->resolve('person', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        return $this->render('records/connections.html', ['e' => $e, 'title' => Queries::sub($db, (int) $e['id'], 'person')['preferred_name'],
            'net' => Graph::network($db, (int) $e['id'])]);
    }

    public function organization(string $slug): Response
    {
        [$e, $r] = $this->resolve('organization', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        return $this->render('records/organization.html', ['e' => $e, 'o' => Queries::sub($db, $id, 'organization'),
            'names' => Queries::names($db, $id), 'members' => Queries::orgMembers($db, $id), 'events' => Queries::orgEvents($db, $id),
            'cites' => Queries::citations($db, $id), 'accts' => Queries::accounts($db, $id),
            'revisions' => Queries::publicRevisions($db, $id), 'photos' => Queries::recordPhotos($db, $id)]);
    }

    public function source(string $slug): Response
    {
        [$e, $r] = $this->resolve('source', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        return $this->render('records/source.html', ['e' => $e, 's' => Queries::sub($db, $id, 'source'),
            'cited_by' => Queries::citedBy($db, $id), 'revisions' => Queries::publicRevisions($db, $id)]);
    }

    // ───────────── discovery ─────────────
    public function searchPage(): Response
    {
        $q = mb_substr(trim((string) $this->arg('q', '')), 0, 200);
        $kind = $this->arg('type') ?: null;
        if (!in_array($kind, Search::SEARCHABLE_KINDS, true)) {
            $kind = null;
        }
        $res = $q !== '' ? Search::search($this->db(), $q, $kind, $this->page()) : null;
        return $this->render('search.html', ['q' => $q, 'kind' => $kind, 'res' => $res, 'kinds' => Search::SEARCHABLE_KINDS,
            'kind_labels' => Vocab::KIND_LABELS]);
    }

    private static function year(?string $v): ?int
    {
        $v = trim((string) $v);
        if (!preg_match('/^[+-]?\d+$/', $v)) {
            return null;
        }
        $y = (int) $v;
        return ($y >= 1000 && $y <= 2100) ? $y : null;
    }

    /** Regions recorded on public places (real values only, for the region filter). */
    private function regions(): array
    {
        return $this->db()->col('SELECT DISTINCT p.admin_region FROM places p JOIN entities e ON e.id=p.entity_id AND ' . Entities::PUBLIC_WHERE
            . " WHERE p.admin_region IS NOT NULL AND p.admin_region<>'' ORDER BY lower(p.admin_region)");
    }

    /** All public events for the interactive timeline. Dates carry their real precision (see Atlas::dateInterval). */
    public function timelineJson(): Response
    {
        $evs = Atlas::timelineEvents($this->db(), $this->fmt());
        foreach ($evs as &$ev) {
            $ev['type_label'] = $this->_($ev['type_label']);
            $ev['precision_note'] = !in_array($ev['precision'], [null, 'unknown'], true) ? I18n::precisionNote($ev['precision']) : null;
            if ($ev['date'] === 'Unknown') {
                $ev['date'] = $this->_('Unknown');
            }
        }
        unset($ev);
        return $this->json(['events' => $evs]);
    }

    private const PID = '/(?:\[)?([a-z]{3}-[a-z0-9]{8})\]?\s*$/';

    /** The permanent id in a link value, if it names a PUBLIC record of one of these kinds; otherwise null. */
    private function publicId(string $value, array $kinds): ?string
    {
        $db = $this->db();
        $pid = preg_match(self::PID, trim($value), $m) ? $m[1] : null;
        if (!$pid && count($kinds) === 1) {        // older links may name the record ("Test Front"): accepted if it is unambiguous
            [$pid] = Records::parseRef($db, $value, $kinds[0]);
        }
        if (!$pid) {
            return null;
        }
        $kind = $db->val('SELECT e.kind FROM entities e WHERE e.public_id=? AND ' . Entities::PUBLIC_WHERE, [$pid]);
        return ($kind !== null && in_array($kind, $kinds, true)) ? $pid : null;
    }

    /** urlencode() of the explore state: True → "1", empty values left out. */
    private static function stateQuery(array $s): string
    {
        $q = [];
        foreach ($s as $k => $v) {
            if ($v === null || $v === '' || $v === false) {
                continue;
            }
            $q[$k] = $v === true ? '1' : $v;
        }
        return http_build_query($q, '', '&', PHP_QUERY_RFC1738);
    }

    /**
     * The historical atlas: the 3D map and the timeline on one page, sharing one exploration state. Every identifier in
     * the address is checked here: only public records enter the page's state, and the visitor is told when part of a
     * link was left out (a private, unpublished or deleted record).
     */
    private function exploreView(string $defaultMode, ?string $legacy = null): Response
    {
        $db = $this->db();
        $a = $this->req()->query;
        $get = fn (string $k) => isset($a[$k]) ? (string) $a[$k] : null;
        $types = $db->all('SELECT slug, label FROM event_types WHERE is_active=1 ORDER BY sort_order');
        $placeTypes = $db->all('SELECT slug, label FROM place_types WHERE is_active=1 ORDER BY sort_order');
        $regions = $this->regions();
        $ptypes = array_merge(array_column($placeTypes, 'slug'), array_map(fn ($c) => "cat:{$c}", array_keys(Atlas::CATEGORY_LABELS)));
        $st = [
            'mode' => in_array($get('mode'), ['map', 'timeline', 'both'], true) ? $get('mode') : $defaultMode,
            'q' => mb_substr(trim((string) $get('q')), 0, 100), 'from' => self::year($get('from')), 'to' => self::year($get('to')),
            'type' => in_array($get('type'), array_column($types, 'slug'), true) ? $get('type') : '',
            'region' => in_array($get('region'), $regions, true) ? $get('region') : '', 'media' => $get('media') === '1',
            'ptype' => in_array($get('ptype'), $ptypes, true) ? $get('ptype') : '',
        ];
        // the old timeline used ?place= for "events at this place"; on the explore page that is ?at=
        $raw = [];
        foreach (['at', 'person', 'organization', 'place', 'event', 'record'] as $k) {
            $raw[$k] = $get($k);
        }
        if ($legacy === 'timeline' && $raw['place'] && !$raw['at']) {
            [$raw['at'], $raw['place']] = [$raw['place'], null];
        }
        $kinds = ['at' => ['place'], 'person' => ['person'], 'organization' => ['organization'], 'place' => ['place'], 'event' => ['event'],
            'record' => ['person', 'family', 'organization', 'source', 'archive_item', 'oral_history', 'collection']];
        $dropped = false;
        $labels = [];
        foreach ($raw as $k => $v) {
            $pid = $v ? $this->publicId($v, $kinds[$k]) : null;
            if ($k === 'record' && $pid && Atlas::recordPreview($db, $pid) === null) {      // e.g. an archive item whose rights forbid display
                $pid = null;
            }
            if ($v && !$pid) {
                $dropped = true;
            }
            $st[$k] = $pid ?: '';
            if ($pid && in_array($k, ['at', 'person', 'organization'], true)) {
                $labels[$pid] = Queries::filterLabel($db, $kinds[$k][0], $pid);
            }
        }
        // the server-rendered lists (used without JavaScript) apply the same filters
        $f = ['type' => $st['type'] ?: null, 'q' => $st['q'] ?: null, 'from' => $st['from'], 'to' => $st['to'], 'region' => $st['region'] ?: null,
            'media' => $st['media'] ?: null, 'place' => $st['at'] ?: null, 'person' => $st['person'] ?: null,
            'organization' => $st['organization'] ?: null];
        $wantList = in_array($st['mode'], ['timeline', 'both'], true);      // with JavaScript the timeline builds its own list
        [$dated, $undated] = $wantList ? Queries::timeline($db, $f) : [[], []];
        $ruler = Queries::timelineRuler($dated);
        $lpages = max(1, intdiv(count($dated) + self::LIST_PAGE - 1, self::LIST_PAGE));
        $lpage = min(max(1, $this->req()->argInt('lpage', 1)), $lpages);
        $total = count($dated) + count($undated);
        $dated = array_slice($dated, ($lpage - 1) * self::LIST_PAGE, self::LIST_PAGE);
        $groups = [];
        foreach ($dated as $ev) {
            $decade = substr($ev['date_start'], 0, 3) . '0s';
            if (!$groups || $groups[count($groups) - 1][0] !== $decade) {
                $groups[] = [$decade, []];
            }
            $groups[count($groups) - 1][1][] = $ev;
        }
        $rows = $db->all('SELECT e.slug, e.public_id, e.is_fictional_test, p.primary_name, p.latitude, p.longitude, p.coord_precision, p.admin_region, p.country '
            . "FROM entities e JOIN places p ON p.entity_id=e.id WHERE e.kind='place' AND " . Entities::PUBLIC_WHERE . ' ORDER BY lower(p.primary_name)');
        $active = false;
        foreach (['q', 'type', 'from', 'to', 'region', 'media', 'ptype', 'at', 'person', 'organization'] as $k) {
            $active = $active || (bool) $st[$k];
        }
        $embed = $get('embed') === '1';
        $this->app->g['embed'] = $embed;      // base.html leaves out the site header and footer; Security allows the listed sites to frame it
        // links that work without JavaScript (mode switch, chips); same state, one value changed
        $nojs = function (array $kw = []) use ($st, $embed): string {
            $q = self::stateQuery(array_merge($st, $kw));
            $e = $embed ? 'embed=1' : '';
            return '/explore?' . $q . ($q !== '' && $e !== '' ? '&' : '') . $e;
        };
        $this->app->g['nojs'] = $nojs;
        $clear = [];
        foreach (['q', 'type', 'from', 'to', 'region', 'media', 'ptype', 'at', 'person', 'organization', 'place', 'event', 'record'] as $k) {
            $clear[$k] = null;
        }
        $placeGroups = [];
        foreach (Atlas::CATEGORY_LABELS as $c => $label) {
            $placeGroups[] = [$c, $label, array_values(array_filter($placeTypes, fn ($t) => Atlas::category($t['slug']) === $c))];
        }
        $typeCategories = [];
        foreach ($types as $t) {
            $typeCategories[$t['slug']] = Atlas::eventCategory($t['slug']);
        }
        $u = $this->viewer();
        return $this->render('explore.html', [
            'st' => $st, 'labels' => $labels ?: new \stdClass(), 'dropped' => $dropped, 'active' => $active,
            'clear_url' => $nojs($clear),
            'groups' => $groups, 'undated' => $undated, 'total' => $total, 'ruler' => $ruler, 'lpage' => $lpage, 'lpages' => $lpages,
            'want_list' => $wantList,
            'place_ctx' => $st['at'] ? Atlas::placePreview($db, $st['at'], $this->fmt()) : null,
            'located' => array_values(array_filter($rows, fn ($r) => Atlas::validCoords($r['latitude'], $r['longitude']))),
            'unlocated' => array_values(array_filter($rows, fn ($r) => !Atlas::validCoords($r['latitude'], $r['longitude']))),
            'types' => $types, 'regions' => $regions, 'place_groups' => $placeGroups,
            'category_labels' => Atlas::CATEGORY_LABELS, 'category_labels_tr' => array_map(fn ($v) => $this->_($v), Atlas::CATEGORY_LABELS),
            'event_categories' => Atlas::EVENT_CATEGORY_LABELS,
            'event_categories_tr' => array_map(fn ($v) => $this->_($v), Atlas::EVENT_CATEGORY_LABELS),
            'type_categories' => $typeCategories,
            'tile' => $this->app->config['MAP_TILE_URL'], 'tile_attribution' => $this->app->config['MAP_TILE_ATTRIBUTION'],
            'can_review' => (bool) ($u && $u->can('submission.review')), 'embed' => $embed,
            'full_url' => '/explore?' . self::stateQuery($st),
            'curated_n' => count(Explorations::published($db)),
        ]);
    }

    public function explore(): Response
    {
        return $this->exploreView('both');
    }

    public function mapPage(): Response
    {
        return $this->exploreView('map');
    }

    public function timeline(): Response
    {
        return $this->exploreView('timeline', 'timeline');
    }

    /** Editor-curated explorations: saved selections of reviewed records, each with its description and sources. */
    public function curatedList(): Response
    {
        return $this->render('explore_curated.html', ['rows' => Explorations::published($this->db())]);
    }

    public function curated(string $slug): Response
    {
        $db = $this->db();
        $found = Explorations::published($db, $slug);
        if (!$found) {
            $this->abort(404);
        }
        $x = $found[0]['x'];
        $items = $found[0]['items'];
        $mapped = array_flip($db->col('SELECT e.public_id FROM entities e JOIN places p ON p.entity_id=e.id WHERE ' . Entities::PUBLIC_WHERE
            . ' AND p.latitude IS NOT NULL'));
        foreach ($items as &$it) {
            $it['kind_label'] = $this->_(Vocab::KIND_LABELS[$it['kind']] ?? $it['kind']);
            $e = Entities::getByPublicId($db, $it['id']);
            if ($it['kind'] === 'place') {
                $it['map'] = isset($mapped[$it['id']]);
            } elseif (in_array($it['kind'], ['event', 'person', 'organization', 'archive_item', 'oral_history'], true)) {
                $it['map'] = (bool) Atlas::recordPlaces($db, $e)[0];
            }
        }
        unset($it);
        $q = ['mode' => 'both'];
        $regionOk = $x['region'] && in_array($x['region'], $this->regions(), true);
        foreach (['from' => $x['period_from'], 'to' => $x['period_to'], 'region' => $regionOk ? $x['region'] : null] as $k => $v) {
            if ($v) {
                $q[$k] = $v;
            }
        }
        return $this->render('explore_guide.html', ['x' => $x, 'items' => $items,
            'atlas_url' => '/explore?' . http_build_query($q, '', '&', PHP_QUERY_RFC1738)]);
    }

    /** Public place data for the interactive map (same visibility rule as every public page). */
    public function mapJson(): Response
    {
        $data = Queries::mapData($this->db());
        $labels = ['exact' => 'Exact', 'approximate' => 'Approximate', 'region_centroid' => 'Region centroid'];
        foreach ($data as &$p) {
            $p['type_label'] = $this->_($p['type_label']);
            $p['precision_label'] = $this->_($labels[$p['precision']] ?? $p['precision']);
        }
        unset($p);
        return $this->json(['places' => $data]);
    }

    private function tr(array $d, string ...$keys): array
    {
        foreach ($keys as $k) {
            if (!empty($d[$k])) {
                $d[$k] = $this->_($d[$k]);
            }
        }
        return $d;
    }

    /** Interface labels for archive-item captions (the titles, creators and rights holders are shown as recorded). */
    private function caption(?array $ph): ?array
    {
        if ($ph) {
            $ph['rights_label'] = $this->_(Vocab::RIGHTS_LABELS[$ph['rights']] ?? $ph['rights']);
            $ph['item_type_label'] = $this->_(Vocab::ITEM_TYPE_LABELS[$ph['item_type']] ?? $ph['item_type']);
        }
        return $ph;
    }

    /** The atlas place panel (loaded only when a place is opened). */
    public function mapPlace(string $publicId): Response
    {
        $p = Atlas::placePreview($this->db(), $publicId, $this->fmt());
        if ($p === null) {
            $this->abort(404);
        }
        $p['photos'] = array_map(fn ($ph) => $this->caption($ph), $p['photos']);
        $p['lead'] = $this->caption($p['lead']);
        $p = $this->tr($p, 'type_label');
        $p['category_label'] = $this->_(Atlas::CATEGORY_LABELS[$p['category']]);
        $p['people'] = array_map(fn ($x) => $this->tr($x, 'role'), $p['people']);
        foreach ($p['events'] as &$ev) {
            $ev['date'] = $ev['date'] === 'Unknown' ? $this->_($ev['date']) : $ev['date'];
        }
        unset($ev);
        return $this->json($p);
    }

    /** Preview of any public record and its places on the map (search results, timeline links). */
    public function mapRecord(string $publicId): Response
    {
        $r = Atlas::recordPreview($this->db(), $publicId, $this->fmt());
        if ($r === null) {
            $this->abort(404);
        }
        $r['kind_label'] = $this->_(Vocab::KIND_LABELS[$r['kind']] ?? $r['kind']);
        $r['lead'] = $this->caption($r['lead']);
        return $this->json($this->tr($r, 'type_label', 'precision_note'));
    }

    /** The explore filters a period summary may use, validated like the explore page's own. */
    private function contextFilters(array $a): array
    {
        $types = $this->db()->col('SELECT slug FROM event_types WHERE is_active=1');
        $type = $a['type'] ?? null;
        $region = $a['region'] ?? null;
        return ['from' => self::year($a['from'] ?? null), 'to' => self::year($a['to'] ?? null),
            'type' => in_array($type, $types, true) ? $type : null,
            'region' => in_array($region, $this->regions(), true) ? $region : null];
    }

    /**
     * A short summary of the events in a period (and region or event type), derived from the published records:
     * counts and the most-linked places, people, families, collections and sources. No narrative is generated.
     */
    public function exploreContext(): Response
    {
        $f = $this->contextFilters($this->req()->query);
        if (!($f['from'] || $f['to'])) {
            return $this->json(['n' => 0]);
        }
        $c = Atlas::periodContext($this->db(), $f);
        foreach ($c['types'] ?? [] as $i => $t) {
            $c['types'][$i]['label'] = $this->_($t['label']);
        }
        foreach ($c['events'] ?? [] as $i => $ev) {
            $date = I18n::fdate($ev['date_start'], $ev['date_end'], $ev['precision']);
            unset($ev['date_start'], $ev['date_end'], $ev['precision']);
            $ev['date'] = $date;
            $c['events'][$i] = $ev;
        }
        return $this->json($c);
    }

    /**
     * For reviewers only: proposed places and proposed location changes that are awaiting a decision. Never part of
     * the public map data, never cached, and each links to its review page.
     */
    public function mapReview(): Response
    {
        $u = $this->viewer();
        if (!$u || !$u->can('submission.review')) {
            $this->abort(404);
        }
        $db = $this->db();
        $out = [];
        $subs = $db->all("SELECT id, kind, status, proposed_data, target_entity_id FROM submissions "
            . "WHERE status IN ('submitted','under_review','needs_revision','approved') AND kind IN ('place','correction') "
            . 'ORDER BY id DESC LIMIT 500');
        foreach ($subs as $s) {
            $d = json_decode($s['proposed_data'], true) ?: [];
            if ($s['kind'] === 'correction') {
                $target = Entities::get($db, $s['target_entity_id']);
                if (!$target || $target['kind'] !== 'place') {
                    continue;
                }
                $d = is_array($d['changes'] ?? null) ? $d['changes'] : [];
            }
            $lat = $d['latitude'] ?? null;
            $lon = $d['longitude'] ?? null;
            if (!(is_int($lat) || is_float($lat)) || !(is_int($lon) || is_float($lon)) || !($lat >= -90 && $lat <= 90 && $lon >= -180 && $lon <= 180)) {
                continue;
            }
            $out[] = ['sid' => (int) $s['id'], 'lat' => $lat, 'lon' => $lon, 'precision' => $d['coord_precision'] ?? null, 'status' => $s['status'],
                'title' => ($d['primary_name'] ?? null) ?: ($s['target_entity_id'] ? Entities::titleOf($db, $s['target_entity_id']) : ''),
                'change' => $s['kind'] === 'correction', 'url' => $this->url('editor.review', ['sid' => $s['id']])];
        }
        return $this->json(['proposals' => $out]);
    }

    /**
     * Atlas search: places (including historical names and other spellings), people, events, organizations and
     * archive records. Each result says what kind of record it is.
     */
    public function mapSearch(): Response
    {
        $q = mb_substr(trim((string) $this->arg('q', '')), 0, 100);
        if (mb_strlen($q) < 2) {
            return $this->json(['results' => []]);
        }
        if (!RateLimit::allow($this->db(), "atlas-search:{$this->ip()}", 300, 300)) {
            $this->abort(429);
        }
        $res = Search::search($this->db(), $q, null, 1, 12);
        $out = [];
        foreach ($res['results'] as $r) {
            $out[] = ['kind' => $r['kind'], 'kind_label' => $this->_(Vocab::KIND_LABELS[$r['kind']] ?? $r['kind']), 'id' => $r['public_id'],
                'title' => $r['title'], 'context' => $r['context'], 'matched_name' => $r['matched_name'], 'fictional' => $r['fictional']];
        }
        return $this->json(['results' => $out]);
    }

    /**
     * Published places with documented coordinates, for the location picker on the contribution forms: just enough to
     * show and choose them (the same public rule as the map).
     */
    public function mapPlaces(): Response
    {
        $rows = $this->db()->all('SELECT e.public_id, p.primary_name, p.latitude, p.longitude, p.coord_precision FROM entities e '
            . "JOIN places p ON p.entity_id=e.id WHERE e.kind='place' AND " . Entities::PUBLIC_WHERE . ' AND p.latitude IS NOT NULL '
            . 'ORDER BY lower(p.primary_name) LIMIT 5000');
        $out = [];
        foreach ($rows as $r) {
            if (Atlas::validCoords($r['latitude'], $r['longitude'])) {
                $out[] = ['id' => $r['public_id'], 'name' => $r['primary_name'], 'lat' => $r['latitude'], 'lon' => $r['longitude'],
                    'precision' => $r['coord_precision'], 'label' => "{$r['primary_name']} [{$r['public_id']}]"];
            }
        }
        return $this->json(['places' => $out]);
    }

    /** The archive's own base map (Natural Earth, public domain), served from this server. */
    public function basemap(): Response
    {
        $resp = StaticFiles::sendFile($this->req(), Config::root() . '/public/static/map/eritrea-basemap.json', 'application/json');
        $resp->set('Cache-Control', 'public, max-age=86400');
        return $resp;
    }

    public function archiveList(): Response
    {
        [$rows, $total] = Queries::listArchive($this->db(), $this->page());
        return $this->render('archive/list.html', ['rows' => $rows, 'total' => $total, 'page' => $this->page(), 'per_page' => Queries::PER_PAGE]);
    }

    /**
     * Public resolution, or — for a vetted researcher — a restricted record they may consult.
     * Returns [entity, redirect response, research view]. Every research view is logged.
     */
    private function resolveOrResearch(string $kind, string $slug): array
    {
        $db = $this->db();
        $res = Entities::resolvePublic($db, $kind, $slug);
        if ($res !== null) {
            [$state, $e] = $res;
            if ($state === 'redirect') {
                return [null, $this->redirect(Queries::recordUrl($kind, $e['slug']), 301), false];
            }
            return [$e, null, false];
        }
        $e = $db->one('SELECT * FROM entities WHERE kind=? AND slug=?', [$kind, $slug]);
        if ($e === null || !Photos::researchAccess($db, $this->viewer(), (int) $e['id'])) {
            $this->abort(404);
        }
        $db->tx(fn () => Audit::log($db, $this->viewer()->id, 'restricted.viewed', $kind, $e['public_id'], null, $this->ip()));
        return [$e, null, true];
    }

    public function archiveItem(string $slug): Response
    {
        [$e, $r, $research] = $this->resolveOrResearch('archive_item', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        $item = Queries::archiveItem($db, $id, $research);
        if ($item === null) {            // the item's own access level or rights do not allow public display
            $this->abort(404);
        }
        $credit = null;
        if ($item['display_name'] && $item['attribution_pref'] !== 'anonymous') {
            $credit = $item['attribution_pref'] === 'username' ? $item['username'] : $item['display_name'];
        }
        return $this->render('archive/item.html', ['e' => $e, 'item' => $item, 'credit' => $credit, 'subjects' => Queries::itemSubjects($db, $id),
            'research' => $research, 'names' => Queries::names($db, $id), 'cites' => Queries::citations($db, $id),
            'revisions' => Queries::publicRevisions($db, $id)]);
    }

    /**
     * Every stored file goes through here. The access rule is re-checked on every request, so a copied or guessed
     * address reveals nothing (404, exactly like a file that never existed).
     */
    public function media(string $key): Response
    {
        $db = $this->db();
        $m = $db->one('SELECT * FROM media_files WHERE storage_key=?', [$key]);
        $user = $this->viewer();
        if (!$m || !Photos::canViewMedia($db, $user, $m)) {
            $this->abort(404);
        }
        $store = Storage::fromConfig($this->app->config);
        try {
            $path = $store->path($key);
            if (!is_file($path)) {
                throw new \RuntimeException('missing');
            }
        } catch (\Throwable) {
            error_log("[elf] Stored file missing for media id {$m['id']}");
            $this->abort(404);
        }
        // researchers' views of restricted material are logged (once per download, not per byte range)
        if ($m['owner_id'] && $m['access_level'] !== 'public' && $user && !$user->can('record.view_any')
            && str_starts_with((string) $this->req()->header('Range', 'bytes=0-'), 'bytes=0-')) {
            $db->tx(fn () => Audit::log($db, $user->id, 'restricted.viewed', 'media', $m['id'], ['entity' => $m['owner_id']]));
        }
        $asDownload = ($m['file_role'] === 'original' && str_starts_with($m['mime_type'], 'image/')) || $m['mime_type'] === 'application/pdf';
        $name = $asDownload ? ($m['original_filename'] ?: 'archive-file' . (Photos::EXTENSIONS[$m['mime_type']] ?? '')) : null;
        $resp = StaticFiles::sendFile($this->req(), $path, $m['mime_type'], $m['sha256'], $name);
        $resp->set('Cache-Control', ($m['access_level'] !== 'public' || $user) ? 'private, no-store' : 'no-cache');
        return $resp;
    }

    /** Type-to-search suggestions for forms. Published records only (the same data as the public lists). */
    public function lookup(string $kind): Response
    {
        $q = mb_substr(trim((string) $this->arg('q', '')), 0, 100);
        if (!RateLimit::allow($this->db(), "lookup:{$this->ip()}", 600, 600)) {
            $this->abort(429);
        }
        if ($kind === 'any') {
            $out = [];
            foreach (Records::LINKABLE as $k) {
                $out = array_merge($out, Records::lookup($this->db(), $k, $q, 8));
            }
            usort($out, fn ($a, $b) => strcmp(mb_strtolower($a['label']), mb_strtolower($b['label'])));
            return $this->json(array_slice($out, 0, 20));
        }
        return $this->json(Records::lookup($this->db(), $kind, $q));
    }

    /** The visitor's interface language. Remembered in a cookie; historical content is not translated. */
    public function setLanguage(string $code): Response
    {
        if (!isset(I18n::LANGUAGES[$code])) {
            $this->abort(404);
        }
        $resp = $this->redirect(Security::safeNext($this->arg('next'), '/'));
        $resp->setCookie(I18n::COOKIE, $code, 365 * 24 * 3600, '/', true, $this->app->config['ENV'] === 'production');
        $resp->set('Cache-Control', 'private, no-store');
        return $resp;
    }

    public function collectionList(): Response
    {
        return $this->render('archive/collections.html', ['rows' => Collections::publicList($this->db())]);
    }

    public function collection(string $slug): Response
    {
        [$e, $r] = $this->resolve('collection', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        return $this->render('archive/collection.html', ['e' => $e, 'c' => Queries::sub($db, $id, 'collection'),
            'items' => Collections::items($db, $id), 'revisions' => Queries::publicRevisions($db, $id), 'cites' => Queries::citations($db, $id)]);
    }

    /** Lines of a transcript; a leading [mm:ss] or [h:mm:ss] becomes a link to that moment of the recording. */
    public static function transcriptLines(?string $text): array
    {
        $out = [];
        foreach (explode("\n", (string) $text) as $line) {
            if (preg_match('/^\s*\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]\s*/', $line, $m)) {
                $t = ((int) ($m[1] ?? 0)) * 3600 + ((int) $m[2]) * 60 + (int) $m[3];
                $out[] = ['t' => $t, 'stamp' => trim($m[0]), 'text' => substr($line, strlen($m[0]))];
            } else {
                $out[] = ['t' => null, 'stamp' => null, 'text' => $line];
            }
        }
        return $out;
    }

    public function oralList(): Response
    {
        $pw = str_replace('e.', 'pe.', Entities::PUBLIC_WHERE);
        $rows = $this->db()->all(
            'SELECT e.id, e.slug, e.is_fictional_test, o.title, o.summary, o.language, o.recorded_start, o.recorded_end, o.recorded_precision, '
            . 'o.interviewee_text, pe.slug AS person_slug, p.preferred_name AS person_name FROM entities e JOIN oral_histories o ON o.entity_id=e.id '
            . "LEFT JOIN entities pe ON pe.id=o.interviewee_id AND {$pw} LEFT JOIN people p ON p.entity_id=pe.id "
            . "WHERE e.kind='oral_history' AND " . Entities::PUBLIC_WHERE . ' ORDER BY o.recorded_start IS NULL, o.recorded_start, lower(o.title) LIMIT 500');
        return $this->render('oral/list.html', ['rows' => $rows]);
    }

    public function oralHistory(string $slug): Response
    {
        [$e, $r, $research] = $this->resolveOrResearch('oral_history', $slug);
        if ($r) {
            return $r;
        }
        $db = $this->db();
        $id = (int) $e['id'];
        $oh = Queries::sub($db, $id, 'oral_history');
        $ok = Oral::allowed($db, $id);
        $show = ['recording' => $ok['publish_recording'] || $research, 'transcript' => $ok['publish_transcript'] || $research,
            'translation' => $ok['publish_translation'] || $research, 'download' => $ok['allow_download']];
        $media = null;
        if ($oh['media_item_id']) {
            $media = $db->one(
                'SELECT a.media_kind, a.access_level, x.visibility, '
                . "(SELECT storage_key FROM media_files WHERE owner_id=a.entity_id AND file_role='access_derivative') AS d, "
                . "(SELECT storage_key FROM media_files WHERE owner_id=a.entity_id AND file_role='original') AS o "
                . 'FROM archive_items a JOIN entities x ON x.id=a.entity_id WHERE a.entity_id=?', [$oh['media_item_id']]);
            if ($media && !($research || ($media['visibility'] === 'public' && $media['access_level'] === 'public'))) {
                $media = null;
            }
        }
        $interviewee = $oh['interviewee_id'] ? Queries::filterLabel($db, 'person', Entities::get($db, $oh['interviewee_id'])['public_id']) : null;
        $ivSlug = $interviewee ? Entities::get($db, $oh['interviewee_id'])['slug'] : null;
        return $this->render('oral/item.html', ['e' => $e, 'oh' => $oh, 'ok' => $ok, 'show' => $show, 'research' => $research, 'media' => $media,
            'interviewee' => $interviewee, 'interviewee_slug' => $ivSlug, 'subjects' => Oral::subjects($db, $id),
            'lines' => $show['transcript'] ? self::transcriptLines($oh['transcript_text']) : [],
            'consents' => Oral::consents($db, $id), 'cites' => Queries::citations($db, $id), 'revisions' => Queries::publicRevisions($db, $id)]);
    }

    /**
     * Ask the archive to record someone's testimony. Nothing is recorded or published without the interviewee's own,
     * specific consent; this only starts a conversation with the editors.
     */
    public function interviewRequest(): Response
    {
        $db = $this->db();
        $fields = ['name', 'email', 'interviewee', 'connection', 'language', 'message'];
        $values = [];
        foreach ($fields as $k) {
            $values[$k] = $this->isPost() ? $this->f($k) : '';
        }
        $errors = [];
        if ($this->isPost()) {
            if ($this->req()->post('website')) {
                return $this->redirect($this->url('public.oral_list'));
            }
            if (!$values['email'] || !str_contains($values['email'], '@')) {
                $errors['email'] = 'Enter a valid email address.';
            }
            $n = mb_strlen($values['message']);
            if ($n < 10 || $n > 5000) {
                $errors['message'] = 'Write between 10 and 5,000 characters.';
            }
            if (!$errors) {
                $db->tx(function () use ($db, $values) {
                    if (!RateLimit::allow($db, "contact:{$this->ip()}", 5, 3600)) {
                        $this->abort(429);
                    }
                    $lines = [];
                    foreach (['interviewee', 'connection', 'language'] as $k) {
                        if ($values[$k] !== '') {
                            $lines[] = ucfirst($k) . ': ' . self::cut($values[$k], 1000);
                        }
                    }
                    $body = implode("\n", $lines);
                    $db->exec("INSERT INTO contact_messages(name, email, message, related_public_id) VALUES (?,?,?, 'interview-request')",
                        [self::cut($values['name'], 120) ?: null, self::cut($values['email'], 200), "[Interview request]\n{$body}\n\n{$values['message']}"]);
                });
                $this->flash('Thank you. Your message has been received and will be read by the editorial team.', 'ok');
                return $this->redirect($this->url('public.oral_list'));
            }
        }
        return $this->render('oral/request.html', ['values' => $values, 'errors' => $errors], $errors ? 400 : 200);
    }

    // ───────────── static information pages ─────────────
    public function info(string $page): Response
    {
        return $this->render("pages/{$page}.html", ['title' => self::INFO_PAGES[$page]]);
    }

    public function contact(): Response
    {
        $db = $this->db();
        $about = mb_substr(trim((string) $this->req()->value('about', '')), 0, 40);
        $errors = [];
        $values = ['name' => '', 'email' => '', 'message' => '', 'about' => $about];
        if ($this->isPost()) {
            foreach (['name', 'email', 'message'] as $k) {
                $values[$k] = $this->f($k);
            }
            if ($this->req()->post('website')) {            // honeypot: bots fill it, people don't see it
                $this->flash('Thank you. Your message has been received.', 'ok');
                return $this->redirect($this->url('public.home'));
            }
            $n = mb_strlen($values['message']);
            if ($n < 10 || $n > 5000) {
                $errors['message'] = 'Write between 10 and 5,000 characters.';
            }
            if ($values['email'] && !str_contains($values['email'], '@')) {
                $errors['email'] = 'Enter a valid email address, or leave it blank.';
            }
            if (!$errors) {
                $db->tx(function () use ($db, $values, $about) {
                    if (!RateLimit::allow($db, "contact:{$this->ip()}", 5, 3600)) {
                        $this->abort(429);
                    }
                    $pubOk = ($about && Entities::getPublicByPublicId($db, $about)) ? $about : null;
                    $db->exec('INSERT INTO contact_messages(name, email, message, related_public_id) VALUES (?,?,?,?)',
                        [self::cut($values['name'], 120) ?: null, self::cut($values['email'], 200) ?: null, $values['message'], $pubOk]);
                });
                $this->flash('Thank you. Your message has been received and will be read by the editorial team.', 'ok');
                return $this->redirect($this->url('public.home'));
            }
        }
        return $this->render('pages/contact.html', ['title' => 'Contact', 'errors' => $errors, 'values' => $values]);
    }

    // ───────────── machine-readable ─────────────
    public function robots(): Response
    {
        $base = $this->app->config['BASE_URL'];
        $body = "User-agent: *\nDisallow: /dashboard\nDisallow: /editor\nDisallow: /admin\nDisallow: /auth\n"
            . "Disallow: /contribute\nDisallow: /dev\nDisallow: /language\nSitemap: {$base}/sitemap.xml\n";
        return new Response($body, 200, ['Content-Type' => 'text/plain; charset=utf-8']);
    }

    public function sitemap(): Response
    {
        $base = $this->app->config['BASE_URL'];
        $rows = '';
        foreach (Queries::sitemapEntries($this->db()) as $e) {
            $rows .= "<url><loc>{$base}" . Queries::recordUrl($e['kind'], $e['slug']) . '</loc><lastmod>' . substr($e['updated_at'], 0, 10) . '</lastmod></url>';
        }
        $xml = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' . $rows . '</urlset>';
        return new Response($xml, 200, ['Content-Type' => 'application/xml']);
    }
}
