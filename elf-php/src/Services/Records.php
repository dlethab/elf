<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;
use Elf\Vocab;

/**
 * Record specifications, validation, and application of approved submissions.
 *
 * Contributions are validated into plain JSON (`proposed_data`). NOTHING is written to the entity tables until an
 * editor publishes the submission, at which point `apply*` runs in one transaction.
 *
 * References to other records ("ref" fields: a birthplace, a family, an organization…) always point at a PUBLISHED
 * record by its permanent id. Forms show "Name [per-abc12345]" so people can type to search; the id in brackets is
 * what is stored.
 */
final class Records
{
    public const REF_COLUMN = ['birth_place' => 'birth_place_id', 'death_place' => 'death_place_id', 'interviewee' => 'interviewee_id'];
    public const LINK_KINDS = ['relationship', 'affiliation', 'membership', 'participation'];
    public const RECORD_KINDS = ['person', 'family', 'place', 'event', 'source', 'organization'];
    public const CORRECTABLE_KINDS = ['person', 'family', 'place', 'event', 'source', 'organization', 'oral_history'];
    public const TITLE_FIELD = ['person' => 'preferred_name', 'family' => 'display_name', 'place' => 'primary_name',
        'event' => 'title', 'source' => 'title', 'organization' => 'name', 'oral_history' => 'title'];
    public const NOT_NULL_DEFAULTS = ['living_status' => 'unknown', 'source_type' => 'other', 'status' => 'current'];
    public const TAXON_TABLE = ['place_type' => ['place_types', 'place_type_id'], 'event_type' => ['event_types', 'event_type_id']];
    public const NAME_FIELD_TYPES = ['preferred_name' => 'preferred', 'full_name' => 'full', 'display_name' => 'preferred',
        'primary_name' => 'preferred', 'title' => 'preferred', 'name' => 'preferred'];
    public const LINKABLE = ['person', 'family', 'place', 'event', 'organization'];
    public const PID_IN_BRACKETS = '/\[([a-z]{3}-[a-z0-9]{8})\]\s*$/';
    public const PID = '/^[a-z]{3}-[a-z0-9]{8}$/';
    private const CTRL = '/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/';

    /** @return Field[] */
    public static function specFor(string $kind, bool $withSources = true): array
    {
        return Specs::specFor($kind, $withSources);
    }

    // ───────────── references to other records ─────────────
    public static function refLabel(Db $db, ?string $publicId): string
    {
        $e = $publicId ? Entities::getByPublicId($db, $publicId) : null;
        return $e ? Entities::titleOf($db, (int) $e['id']) . " [{$publicId}]" : (string) $publicId;
    }

    private static function pidOf(string $v): ?string
    {
        if (preg_match(self::PID_IN_BRACKETS, $v, $m)) {
            return $m[1];
        }
        return preg_match(self::PID, $v) ? $v : null;
    }

    /**
     * [public_id, error]. Accepts 'Name [per-abc12345]', a bare permanent id, or a name that matches exactly one
     * published record. Never confirms that a private record exists.
     */
    public static function parseRef(Db $db, ?string $value, string $kind): array
    {
        $v = Util::squash($value);
        if ($v === '') {
            return [null, null];
        }
        $pid = self::pidOf($v);
        if ($pid) {
            return Entities::getPublicByPublicId($db, $pid, $kind) ? [$pid, null] : [null, 'That record was not found.'];
        }
        $rows = $db->col('SELECT DISTINCT e.public_id FROM entity_names n JOIN entities e ON e.id=n.entity_id '
            . 'WHERE e.kind=? AND ' . Entities::PUBLIC_WHERE . ' AND n.normalized=? LIMIT 2', [$kind, Names::normalize($v)]);
        if (count($rows) === 1) {
            return [$rows[0], null];
        }
        if (count($rows) > 1) {
            return [null, 'More than one record has this name. Choose the right one from the list.'];
        }
        return [null, 'That record was not found.'];
    }

    /** Like parseRef, for a field that may point at a person, family, place, event or organization. */
    public static function parseAnyRef(Db $db, ?string $value): array
    {
        $v = Util::squash($value);
        $pid = self::pidOf($v);
        if ($pid) {
            $kind = array_flip(Entities::ID_PREFIX)[substr($pid, 0, 3)] ?? null;
            return ($kind && in_array($kind, self::LINKABLE, true) && Entities::getPublicByPublicId($db, $pid, $kind))
                ? [$pid, null] : [null, 'That record was not found.'];
        }
        $ph = implode(',', array_fill(0, count(self::LINKABLE), '?'));
        $rows = $db->col("SELECT DISTINCT e.public_id FROM entity_names n JOIN entities e ON e.id=n.entity_id "
            . "WHERE e.kind IN ({$ph}) AND " . Entities::PUBLIC_WHERE . ' AND n.normalized=? LIMIT 2', [...self::LINKABLE, Names::normalize($v)]);
        if (count($rows) === 1) {
            return [$rows[0], null];
        }
        return [null, $rows ? 'More than one record has this name. Choose the right one from the list.' : 'That record was not found.'];
    }

    /** Typeahead suggestions: published records only, matched on any recorded name. */
    public static function lookup(Db $db, string $kind, ?string $q, int $limit = 20): array
    {
        $nq = Names::normalize($q);
        if (!isset(Entities::TITLE_COL[$kind]) || $nq === '') {
            return [];
        }
        $t = Entities::KIND_TABLE[$kind];
        $col = Entities::TITLE_COL[$kind];
        $rows = $db->all("SELECT DISTINCT e.public_id, x.{$col} AS title FROM entity_names n JOIN entities e ON e.id=n.entity_id "
            . "JOIN {$t} x ON x.entity_id=e.id WHERE e.kind=? AND " . Entities::PUBLIC_WHERE . ' AND (n.normalized LIKE ? OR n.normalized LIKE ?) '
            . "ORDER BY lower(x.{$col}) LIMIT ?", [$kind, $nq . '%', '% ' . $nq . '%', $limit]);
        return array_map(fn ($r) => ['id' => $r['public_id'], 'label' => "{$r['title']} [{$r['public_id']}]"], $rows);
    }

    // ───────────── choices for select inputs ─────────────
    public static function choicesFor(Db $db, Field $f): ?array
    {
        if ($f->kind === 'choice') {
            return $f->choices;
        }
        if ($f->kind === 'taxon') {
            $table = self::TAXON_TABLE[$f->name][0];
            return array_merge([['', '—']], array_map(fn ($r) => [$r['slug'], $r['label']],
                $db->all("SELECT slug, label FROM {$table} WHERE is_active=1 ORDER BY sort_order")));
        }
        if ($f->kind === 'ref') {       // initial suggestions for the type-to-search list; the rest come from /lookup
            $t = Entities::KIND_TABLE[$f->ref];
            $col = Entities::TITLE_COL[$f->ref];
            $rows = $db->all("SELECT e.public_id, x.{$col} AS t FROM entities e JOIN {$t} x ON x.entity_id=e.id "
                . 'WHERE e.kind=? AND ' . Entities::PUBLIC_WHERE . " ORDER BY lower(x.{$col}) LIMIT 300", [$f->ref]);
            return array_map(fn ($r) => [$r['public_id'], "{$r['t']} [{$r['public_id']}]"], $rows);
        }
        return null;
    }

    // ───────────── validation ─────────────
    private static function cleanText(?string $v, bool $multiline): string
    {
        $v = preg_replace(self::CTRL, '', str_replace(["\r\n", "\r"], "\n", (string) $v));
        return $multiline ? trim($v) : Util::squash($v);
    }

    public static function okUrl(string $v): bool
    {
        $u = parse_url($v);
        return is_array($u) && in_array(strtolower($u['scheme'] ?? ''), ['http', 'https'], true) && !empty($u['host']);
    }

    /** Python str.splitlines(), for form text. */
    private static function lines(string $v): array
    {
        $v = str_replace(["\r\n", "\r"], "\n", $v);
        $out = explode("\n", $v);
        if (end($out) === '') {
            array_pop($out);
        }
        return $out;
    }

    /** Python float(), for the coordinate fields. */
    private static function toFloat(string $v): ?float
    {
        $v = trim($v);
        if (is_numeric($v)) {
            return (float) $v;
        }
        $l = strtolower($v);
        if (in_array($l, ['nan', '+nan', '-nan'], true)) {
            return NAN;
        }
        if (in_array($l, ['inf', '+inf', 'infinity', '+infinity'], true)) {
            return INF;
        }
        if (in_array($l, ['-inf', '-infinity'], true)) {
            return -INF;
        }
        throw new \ValueError('not a number');
    }

    /** Return [clean, errors]. `raw` is a mapping of form strings. Unknown keys are ignored. */
    public static function validate(Db $db, string $kind, array $raw, bool $strictConsent = true): array
    {
        $clean = [];
        $errors = [];
        foreach (self::specFor($kind) as $f) {
            $v = $raw[$f->name] ?? '';
            $v = is_string($v) ? $v : ($v === null ? '' : (is_scalar($v) ? (string) $v : ''));
            switch ($f->kind) {
                case 'text':
                case 'area':
                case 'url':
                    $v = self::cleanText($v, $f->kind === 'area');
                    if ($f->required && $v === '') {
                        $errors[$f->name] = 'This field is required.';
                    } elseif (mb_strlen($v, 'UTF-8') > $f->max) {
                        $errors[$f->name] = "Use at most {$f->max} characters.";
                    } elseif ($f->kind === 'url' && $v !== '' && !self::okUrl($v)) {
                        $errors[$f->name] = 'Enter a full http(s) URL.';
                    }
                    $clean[$f->name] = $v !== '' ? $v : null;
                    break;
                case 'choice':
                    $v = trim($v);
                    $allowed = array_map(fn ($c) => $c[0], $f->choices);
                    if ($f->required && $v === '') {
                        $errors[$f->name] = 'This field is required.';
                    } elseif ($v !== '' && !in_array($v, $allowed, true)) {
                        $errors[$f->name] = 'Choose one of the listed options.';
                    }
                    $clean[$f->name] = $v !== '' ? $v : null;
                    break;
                case 'taxon':
                    $v = trim($v);
                    if ($v !== '' && !$db->one('SELECT 1 FROM ' . self::TAXON_TABLE[$f->name][0] . ' WHERE slug=? AND is_active=1', [$v])) {
                        $errors[$f->name] = 'Choose one of the listed options.';
                    }
                    $clean[$f->name] = $v !== '' ? $v : null;
                    break;
                case 'date':
                    try {
                        $clean[$f->name] = Dates::parse($v)->asArray();
                    } catch (DateError $e) {
                        $errors[$f->name] = $e->getMessage();
                    }
                    break;
                case 'ref':
                    [$pid, $err] = self::parseRef($db, $v, $f->ref);
                    if ($f->required && trim($v) === '') {
                        $errors[$f->name] = 'This field is required.';
                    } elseif ($err) {
                        $errors[$f->name] = $err;
                    }
                    $clean[$f->name] = $pid;
                    break;
                case 'refs':
                    $out = [];
                    $items = array_values(array_filter(array_map('trim', self::lines(preg_replace(self::CTRL, '', $v))), fn ($x) => $x !== ''));
                    foreach (array_slice($items, 0, $f->max) as $line) {
                        [$pid, $err] = self::parseAnyRef($db, $line);
                        if ($err) {
                            $errors[$f->name] = 'One or more of these records could not be found. Choose names from the suggestions.';
                        } elseif (!in_array($pid, $out, true)) {
                            $out[] = $pid;
                        }
                    }
                    $clean[$f->name] = $out;
                    break;
                case 'consents':
                    $granted = array_values(array_filter(array_keys(Specs::CONSENT_LABELS), fn ($t) => ($raw["consent_{$t}"] ?? null) === '1'));
                    $note = mb_substr(self::cleanText((string) ($raw['consent_note'] ?? ''), true), 0, 2000);
                    if ($strictConsent && ($raw['consent_declared'] ?? null) !== '1') {
                        $errors[$f->name] = 'Please confirm how consent was obtained.';
                    }
                    $clean[$f->name] = ['granted' => $granted, 'note' => $note !== '' ? $note : null];
                    break;
                case 'float':
                    $v = trim($v);
                    try {
                        $clean[$f->name] = $v !== '' ? self::toFloat($v) : null;
                    } catch (\ValueError) {
                        $errors[$f->name] = 'Enter a number.';
                    }
                    break;
                case 'lines':
                    $vals = [];
                    foreach (self::lines(preg_replace(self::CTRL, '', $v)) as $x) {
                        if (trim($x) !== '') {
                            $vals[] = Util::squash($x);
                        }
                    }
                    $tooLong = array_filter($vals, fn ($x) => mb_strlen($x, 'UTF-8') > 200);
                    if (count($vals) > 30 || $tooLong) {
                        $errors[$f->name] = 'At most 30 lines of up to 200 characters.';
                    }
                    $clean[$f->name] = $vals;
                    break;
                case 'sources':
                    $out = [];
                    $items = array_values(array_filter(self::lines(preg_replace(self::CTRL, '', $v)), fn ($x) => trim($x) !== ''));
                    foreach (array_slice($items, 0, 10) as $line) {
                        $parts = array_map('trim', explode('|', $line));
                        [$title, $locator, $url] = array_slice(array_merge($parts, ['', '', '']), 0, 3);
                        if ($title === '' || mb_strlen($title, 'UTF-8') > 300 || mb_strlen($locator, 'UTF-8') > 200) {
                            $errors[$f->name] = 'Each source needs a title (≤300 chars) and a short locator.';
                            break;
                        }
                        if ($url !== '' && !self::okUrl($url)) {
                            $errors[$f->name] = 'Source URLs must be full http(s) addresses.';
                            break;
                        }
                        $out[] = ['title' => $title, 'locator' => $locator !== '' ? $locator : null, 'url' => $url !== '' ? $url : null];
                    }
                    $clean[$f->name] = $out;
                    break;
            }
        }
        if (!$errors) {
            self::crossValidate($db, $kind, $clean, $errors);
        }
        return [$clean, $errors];
    }

    private static function crossValidate(Db $db, string $kind, array &$clean, array &$errors): void
    {
        if ($kind === 'place') {
            $la = $clean['latitude'] ?? null;
            $lo = $clean['longitude'] ?? null;
            $pr = $clean['coord_precision'] ?? null;
            if (($la === null) !== ($lo === null)) {
                $errors['longitude'] = 'Give both latitude and longitude, or neither.';
            } elseif ($la !== null) {
                if (!($la >= -90 && $la <= 90)) {
                    $errors['latitude'] = 'Latitude must be between -90 and 90.';
                }
                if (!($lo >= -180 && $lo <= 180)) {
                    $errors['longitude'] = 'Longitude must be between -180 and 180.';
                }
                if (!$pr) {
                    $errors['coord_precision'] = 'Say how precise these coordinates are.';
                }
            } elseif ($pr) {
                $errors['coord_precision'] = 'Precision applies only when coordinates are given.';
            }
        } elseif ($kind === 'relationship') {
            $a = $clean['person_a'];
            $b = $clean['person_b'];
            if ($a === $b) {
                $errors['person_b'] = 'A person cannot be related to themselves.';
            } elseif (self::findRelationship($db, $a, $b, $clean['relationship_type'])) {
                $errors['relationship_type'] = 'This relationship is already recorded.';
            }
            $clean['status'] = ($clean['status'] ?? null) ?: 'current';
        } elseif ($kind === 'membership') {
            if (self::idsExist($db, 'SELECT 1 FROM family_memberships WHERE family_id=? AND person_id=?', $clean['family'], $clean['person'])) {
                $errors['person'] = 'This person is already listed as a member of this family.';
            }
        } elseif ($kind === 'participation') {
            if ((bool) ($clean['person'] ?? null) === (bool) ($clean['organization'] ?? null)) {
                $errors['person'] = 'Choose a person or an organization (one of them).';
            } elseif (!empty($clean['person']) && self::idsExist($db, 'SELECT 1 FROM event_participants WHERE event_id=? AND person_id=?',
                $clean['event'], $clean['person'])) {
                $errors['person'] = 'This participant is already recorded for this event.';
            } elseif (!empty($clean['organization']) && self::idsExist($db, 'SELECT 1 FROM event_participants WHERE event_id=? AND organization_id=?',
                $clean['event'], $clean['organization'])) {
                $errors['organization'] = 'This participant is already recorded for this event.';
            }
        }
    }

    private static function idsExist(Db $db, string $sql, ?string ...$publicIds): bool
    {
        $ids = array_map(fn ($p) => Entities::getByPublicId($db, $p), $publicIds);
        foreach ($ids as $e) {
            if (!$e) {
                return false;
            }
        }
        return $db->one($sql, array_map(fn ($e) => $e['id'], $ids)) !== null;
    }

    public static function canonicalPair(int $a, int $b, string $rtype): array
    {
        return (in_array($rtype, Vocab::DIRECTED_RELATIONSHIPS, true) || $a < $b) ? [$a, $b] : [$b, $a];
    }

    private static function findRelationship(Db $db, ?string $pubA, ?string $pubB, string $rtype): ?array
    {
        $a = Entities::getByPublicId($db, $pubA);
        $b = Entities::getByPublicId($db, $pubB);
        if (!$a || !$b) {
            return null;
        }
        [$x, $y] = self::canonicalPair((int) $a['id'], (int) $b['id'], $rtype);
        return $db->one('SELECT id FROM relationships WHERE person_a_id=? AND person_b_id=? AND relationship_type=?', [$x, $y, $rtype]);
    }

    // ───────────── column mapping ─────────────
    /** Map validated fields to subtype-table columns. */
    public static function rowValues(Db $db, string $kind, array $clean, ?array $only = null): array
    {
        $cols = [];
        foreach (self::specFor($kind, false) as $f) {
            if ($only !== null && !in_array($f->name, $only, true)) {
                continue;
            }
            if (in_array($f->kind, ['lines', 'sources', 'refs', 'consents'], true) || !array_key_exists($f->name, $clean)) {
                continue;
            }
            $v = $clean[$f->name];
            if ($f->kind === 'date') {
                $cols += Dates::columns($f->name, Dates::fromArray($v));
            } elseif ($f->kind === 'ref' && isset(self::REF_COLUMN[$f->name])) {
                $cols[self::REF_COLUMN[$f->name]] = $v ? (int) Entities::getByPublicId($db, $v)['id'] : null;
            } elseif ($f->kind === 'ref') {       // event.place → event_places (handled separately)
                continue;
            } elseif ($f->kind === 'taxon') {
                [$table, $col] = self::TAXON_TABLE[$f->name];
                $cols[$col] = $v ? (int) $db->val("SELECT id FROM {$table} WHERE slug=?", [$v]) : null;
            } else {
                $cols[$f->name] = ($v === null && isset(self::NOT_NULL_DEFAULTS[$f->name])) ? self::NOT_NULL_DEFAULTS[$f->name] : $v;
            }
        }
        return $cols;
    }

    /** Current stored values in the same shape `validate` produces (used for diffs and prefilled forms). */
    public static function currentClean(Db $db, string $kind, int $entityId): array
    {
        $row = Entities::subtypeRow($db, $entityId);
        $out = [];
        foreach (self::specFor($kind, false) as $f) {
            switch (true) {
                case in_array($f->kind, ['lines', 'sources'], true):
                    $out[$f->name] = [];
                    break;
                case $f->kind === 'refs':
                    $out[$f->name] = $db->col('SELECT e.public_id FROM oral_history_subjects s JOIN entities e ON e.id=s.subject_id '
                        . 'WHERE s.oral_history_id=? ORDER BY e.id', [$entityId]);
                    break;
                case $f->kind === 'consents':
                    $out[$f->name] = ['granted' => $db->col('SELECT consent_type FROM consent_records WHERE oral_history_id=? AND revoked_at IS NULL AND granted=1',
                        [$entityId]), 'note' => null];
                    break;
                case $f->kind === 'date':
                    $out[$f->name] = Dates::fromRow($row, $f->name)->asArray();
                    break;
                case $f->kind === 'ref' && isset(self::REF_COLUMN[$f->name]):
                    $pid = $row[self::REF_COLUMN[$f->name]];
                    $out[$f->name] = $pid ? Entities::get($db, (int) $pid)['public_id'] : null;
                    break;
                case $f->kind === 'ref':
                    $out[$f->name] = $db->val('SELECT e.public_id FROM event_places ep JOIN entities e ON e.id=ep.place_id '
                        . 'WHERE ep.event_id=? ORDER BY ep.id LIMIT 1', [$entityId]);
                    break;
                case $f->kind === 'taxon':
                    [$table, $col] = self::TAXON_TABLE[$f->name];
                    $out[$f->name] = $row[$col] ? $db->val("SELECT slug FROM {$table} WHERE id=?", [$row[$col]]) : null;
                    break;
                default:
                    $out[$f->name] = $row[$f->name];
            }
        }
        return $out;
    }

    public static function isEmpty(mixed $v): bool
    {
        return $v === null || $v === '' || $v === [];
    }

    /** Python repr() of a float: shortest round-trip form, always with a decimal point. */
    public static function floatRepr(float $v): string
    {
        // Python's repr(float): the shortest digits that read back as the same number; scientific notation when the
        // decimal point would fall more than 4 places before the first digit or more than 16 after it
        if (is_nan($v)) {
            return 'nan';
        }
        if (is_infinite($v)) {
            return $v > 0 ? 'inf' : '-inf';
        }
        $sign = ($v < 0 || ($v == 0.0 && fdiv(1.0, $v) < 0)) ? '-' : '';
        $a = abs($v);
        if ($a == 0.0) {
            return $sign . '0.0';
        }
        for ($p = 0; $p < 17; $p++) {
            $e = sprintf('%.' . $p . 'e', $a);
            if ((float) $e === $a) {
                break;
            }
        }
        [$mant, $exp] = explode('e', $e);
        $digits = rtrim(str_replace('.', '', $mant), '0') ?: '0';
        $decpt = (int) $exp + 1;                                     // digits before the decimal point
        if ($decpt <= -4 || $decpt > 16) {
            $m = $digits[0] . (strlen($digits) > 1 ? '.' . substr($digits, 1) : '');
            return $sign . $m . 'e' . ($decpt - 1 < 0 ? '-' : '+') . sprintf('%02d', abs($decpt - 1));
        }
        if ($decpt <= 0) {
            return $sign . '0.' . str_repeat('0', -$decpt) . $digits;
        }
        if ($decpt >= strlen($digits)) {
            return $sign . $digits . str_repeat('0', $decpt - strlen($digits)) . '.0';
        }
        return $sign . substr($digits, 0, $decpt) . '.' . substr($digits, $decpt);
    }

    /** Turn validated/stored data back into form strings (for re-displaying a draft). */
    public static function formValues(array $clean, string $kind, ?Db $db = null): array
    {
        $out = [];
        foreach (self::specFor($kind) as $f) {
            $v = $clean[$f->name] ?? null;
            if (self::isEmpty($v)) {
                $out[$f->name] = '';
            } elseif ($f->kind === 'date') {
                $out[$f->name] = Dates::toInput($v['start'] ?? null, $v['end'] ?? null, $v['precision'] ?? 'unknown');
            } elseif ($f->kind === 'ref') {
                $out[$f->name] = $db ? self::refLabel($db, $v) : $v;
            } elseif ($f->kind === 'refs') {
                $out[$f->name] = implode("\n", array_map(fn ($x) => $db ? self::refLabel($db, $x) : $x, $v));
            } elseif ($f->kind === 'consents') {
                foreach ($v['granted'] ?? [] as $t) {
                    $out["consent_{$t}"] = '1';
                }
                $out['consent_note'] = $v['note'] ?? '';
                $out[$f->name] = '';
            } elseif ($f->kind === 'lines') {
                $out[$f->name] = implode("\n", $v);
            } elseif ($f->kind === 'sources') {
                $out[$f->name] = implode("\n", array_map(fn ($s) => rtrim(implode(' | ', [$s['title'], $s['locator'] ?? '', $s['url'] ?? '']), ' |'), $v));
            } elseif ($f->kind === 'float') {
                $out[$f->name] = self::floatRepr((float) $v);
            } else {
                $out[$f->name] = (string) $v;
            }
        }
        return $out;
    }

    public static function displayValue(Db $db, Field $f, mixed $v): string
    {
        if (self::isEmpty($v)) {
            return '—';
        }
        switch ($f->kind) {
            case 'date':
                return Dates::format($v['start'] ?? null, $v['end'] ?? null, $v['precision'] ?? 'unknown');
            case 'ref':
                $e = Entities::getByPublicId($db, $v);
                return $e ? (string) Entities::titleOf($db, (int) $e['id']) : (string) $v;
            case 'refs':
                return implode('; ', array_map(fn ($x) => self::displayValue($db, new Field('x', 'x', 'ref'), $x), $v));
            case 'consents':
                $l = array_map(fn ($t) => Specs::CONSENT_LABELS[$t] ?? $t, $v['granted'] ?? []);
                return $l ? implode('; ', $l) : 'None';
            case 'choice':
            case 'taxon':
                foreach (self::choicesFor($db, $f) ?? [] as [$val, $label]) {
                    if ($val === $v) {
                        return $label;
                    }
                }
                return (string) $v;
            case 'lines':
                return implode('; ', $v);
            case 'sources':
                return implode('; ', array_map(fn ($s) => $s['title'] . (!empty($s['locator']) ? " ({$s['locator']})" : ''), $v));
            case 'float':
                return self::floatRepr((float) $v);
        }
        return is_bool($v) ? ($v ? 'True' : 'False') : (string) $v;
    }

    /** [[label, value]] for a proposed new record, skipping empty fields. */
    public static function displayRows(Db $db, string $kind, array $data): array
    {
        $rows = [];
        foreach (self::specFor($kind) as $f) {
            $v = self::displayValue($db, $f, $data[$f->name] ?? null);
            if ($v !== '—' && !($f->kind === 'date' && $v === 'Unknown')) {
                $rows[] = [$f->label, $v];
            }
        }
        return $rows;
    }

    public static function diff(Db $db, string $kind, int $entityId, array $changes): array
    {
        $cur = self::currentClean($db, $kind, $entityId);
        $byname = [];
        foreach (self::specFor($kind) as $f) {
            $byname[$f->name] = $f;
        }
        $out = [];
        foreach ($changes as $n => $new) {
            if (isset($byname[$n])) {
                $out[] = ['label' => $byname[$n]->label, 'old' => self::displayValue($db, $byname[$n], $cur[$n] ?? null),
                    'new' => self::displayValue($db, $byname[$n], $new), 'additive' => $byname[$n]->additive];
            }
        }
        return $out;
    }

    /** Value equality as Python compares the stored and submitted forms (numbers by value, lists/dicts by content). */
    public static function same(mixed $a, mixed $b): bool
    {
        if (is_numeric($a) && is_numeric($b) && !is_string($a) && !is_string($b)) {
            return (float) $a === (float) $b;
        }
        if (is_array($a) && is_array($b)) {
            if (array_is_list($a) !== array_is_list($b) || count($a) !== count($b)) {
                return false;
            }
            foreach ($a as $k => $x) {
                if (!array_key_exists($k, $b) || !self::same($x, $b[$k])) {
                    return false;
                }
            }
            return true;
        }
        return $a === $b;
    }

    /** Reduce a full validated form to only what differs from the stored record. */
    public static function changedFields(Db $db, string $kind, int $entityId, array $clean): array
    {
        $cur = self::currentClean($db, $kind, $entityId);
        $out = [];
        foreach (self::specFor($kind) as $f) {
            if ($f->kind === 'consents') {       // consent is managed by editors with evidence, never by editing the record
                continue;
            }
            $v = $clean[$f->name] ?? null;
            if ($f->additive) {
                if ($v) {
                    $out[$f->name] = $v;
                }
            } elseif (!self::same($v, $cur[$f->name] ?? null) && !(in_array($v, [null, ''], true) && in_array($cur[$f->name] ?? null, [null, ''], true))) {
                $out[$f->name] = $v;
            }
        }
        return $out;
    }

    // ───────────── applying approved submissions ─────────────
    public static function storeSources(Db $db, int $targetId, ?array $sources, ?int $actorId, ?string $field = null, ?string $claim = null): void
    {
        foreach ($sources ?? [] as $s) {
            $existing = $db->one("SELECT s.entity_id FROM sources s JOIN entities e ON e.id=s.entity_id "
                . "WHERE lower(s.title)=lower(?) AND COALESCE(s.url,'')=COALESCE(?, '') AND e.merged_into IS NULL", [$s['title'], $s['url'] ?? null]);
            if ($existing) {
                $sid = (int) $existing['entity_id'];     // reuse: one source can support claims on many records
            } else {
                [$sid] = Entities::create($db, 'source', $s['title'], $actorId, 'published', 'public');
                $db->exec('INSERT INTO sources(entity_id, title, url) VALUES (?,?,?)', [$sid, $s['title'], $s['url'] ?? null]);
                Entities::addName($db, $sid, $s['title'], 'preferred');
                Entities::addRevision($db, $sid, $actorId, 'Source created from approved contribution');
                Search::reindex($db, $sid);
            }
            $db->exec("INSERT INTO citations(source_id, target_id, field_name, claim_text, locator, evidence_status, created_by) "
                . "VALUES (?,?,?,?,?, 'unverified', ?)", [$sid, $targetId, $field, $claim, $s['locator'] ?? null, $actorId]);
        }
    }

    private static function addNames(Db $db, int $entityId, string $kind, array $clean): void
    {
        foreach (self::specFor($kind, false) as $f) {
            $v = $clean[$f->name] ?? null;
            if (!$v) {
                continue;
            }
            if (isset(self::NAME_FIELD_TYPES[$f->name])) {
                Entities::addName($db, $entityId, $v, self::NAME_FIELD_TYPES[$f->name]);
            } elseif ($f->name === 'original_name') {
                Entities::addName($db, $entityId, $v, 'original', $clean['original_name_lang'] ?? null);
            } elseif ($f->name === 'aliases') {
                foreach ($v as $a) {
                    Entities::addName($db, $entityId, $a, 'alternate_spelling');
                }
            }
        }
    }

    private static function insertRow(Db $db, string $table, array $cols): int
    {
        $keys = array_keys($cols);
        return $db->insert("INSERT INTO {$table}(" . implode(',', $keys) . ') VALUES (' . implode(',', array_fill(0, count($keys), '?')) . ')',
            array_values($cols));
    }

    /** Create a published record from validated data. Caller supplies the surrounding transaction. */
    public static function applyNew(Db $db, string $kind, array $clean, ?int $actorId, ?int $submissionId, bool $consentConfirmed = false, bool $fictional = false): int
    {
        $living = $kind === 'person' && ($clean['living_status'] ?? null) === 'living';
        $visibility = (($living && !$consentConfirmed) || $kind === 'oral_history') ? 'restricted' : 'public';
        $title = $clean[self::TITLE_FIELD[$kind]];
        [$eid, $pid] = Entities::create($db, $kind, $title, $actorId, 'published', $visibility, $fictional);
        $cols = ['entity_id' => $eid] + self::rowValues($db, $kind, $clean);
        self::insertRow($db, Entities::KIND_TABLE[$kind], $cols);
        if ($kind === 'event' && !empty($clean['place'])) {
            $db->exec('INSERT INTO event_places(event_id, place_id) VALUES (?,?)', [$eid, Entities::getByPublicId($db, $clean['place'])['id']]);
        }
        self::addNames($db, $eid, $kind, $clean);
        self::storeSources($db, $eid, $clean['sources'] ?? null, $actorId);
        Entities::addRevision($db, $eid, $actorId, 'Created from an approved submission', null, $submissionId);
        if ($kind === 'oral_history') {          // consent decides what becomes public (Services\Oral)
            Oral::afterCreate($db, $eid, $clean, $actorId, $consentConfirmed);
            if (Oral::shouldBePublic($db, $eid)) {
                $db->exec("UPDATE entities SET visibility='public' WHERE id=?", [$eid]);
                $visibility = 'public';
            }
        }
        Audit::log($db, $actorId, 'record.published', $kind, $pid, ['submission' => $submissionId, 'visibility' => $visibility]);
        Search::reindex($db, $eid);
        return $eid;
    }

    public static function applyCorrection(Db $db, array $entity, array $changes, ?int $actorId, ?int $submissionId, ?string $reason = null,
                                           string $summaryPrefix = 'Correction'): void
    {
        $kind = $entity['kind'];
        $eid = (int) $entity['id'];
        $cols = self::rowValues($db, $kind, $changes, array_keys($changes));
        if ($cols) {
            $sets = implode(', ', array_map(fn ($c) => "{$c}=?", array_keys($cols)));
            $db->exec('UPDATE ' . Entities::KIND_TABLE[$kind] . " SET {$sets} WHERE entity_id=?", [...array_values($cols), $eid]);
        }
        if ($kind === 'oral_history' && array_key_exists('related', $changes)) {
            $db->exec('DELETE FROM oral_history_subjects WHERE oral_history_id=?', [$eid]);
            foreach ($changes['related'] ?? [] as $pid) {
                $db->exec('INSERT OR IGNORE INTO oral_history_subjects(oral_history_id, subject_id) VALUES (?,?)',
                    [$eid, Entities::getByPublicId($db, $pid)['id']]);
            }
        }
        if ($kind === 'event' && array_key_exists('place', $changes)) {
            $db->exec('DELETE FROM event_places WHERE event_id=?', [$eid]);
            if ($changes['place']) {
                $db->exec('INSERT INTO event_places(event_id, place_id) VALUES (?,?)', [$eid, Entities::getByPublicId($db, $changes['place'])['id']]);
            }
        }
        $tf = self::TITLE_FIELD[$kind];
        if (!empty($changes[$tf])) {
            // keep the previous preferred spelling searchable as an alternate; never discard it
            $db->exec("UPDATE OR IGNORE entity_names SET name_type='alternate_spelling' WHERE entity_id=? AND name_type='preferred'", [$eid]);
            $db->exec("DELETE FROM entity_names WHERE entity_id=? AND name_type='preferred'", [$eid]);
            Entities::addName($db, $eid, $changes[$tf], 'preferred');
        }
        if (!empty($changes['full_name'])) {
            Entities::addName($db, $eid, $changes['full_name'], 'full');
        }
        if (!empty($changes['original_name'])) {
            Entities::addName($db, $eid, $changes['original_name'], 'original');
        }
        foreach ($changes['aliases'] ?? [] as $a) {
            Entities::addName($db, $eid, $a, 'alternate_spelling');
        }
        self::storeSources($db, $eid, $changes['sources'] ?? null, $actorId);
        $labels = [];
        foreach (self::specFor($kind) as $f) {
            $labels[$f->name] = $f->label;
        }
        Entities::addRevision($db, $eid, $actorId, "{$summaryPrefix}: " . implode(', ', array_map(fn ($k) => $labels[$k] ?? $k, array_keys($changes))),
            $reason, $submissionId);
        $db->exec('UPDATE entities SET updated_at=? WHERE id=?', [Util::nowIso(), $eid]);
        $fields = array_keys($changes);
        sort($fields, SORT_STRING);
        Audit::log($db, $actorId, 'record.corrected', $kind, $entity['public_id'], ['fields' => $fields, 'submission' => $submissionId]);
        if ($kind === 'person' && ($changes['living_status'] ?? null) === 'living' && $entity['visibility'] === 'public') {
            Entities::setState($db, $eid, null, 'restricted', $actorId, 'Automatically restricted: person recorded as living');
        }
        Search::reindex($db, $eid);
    }

    // ───────────── links between records ─────────────
    private static function pub(Db $db, ?string $publicId, string $kind): ?array
    {
        $e = $publicId ? Entities::getPublicByPublicId($db, $publicId, $kind) : null;
        if ($publicId && !$e) {
            throw new \InvalidArgumentException("The {$kind} must still be published.");
        }
        return $e;
    }

    /** Links that involve a person recorded as living are restricted (privacy by default). */
    private static function linkVisibility(Db $db, ?int ...$personIds): string
    {
        foreach ($personIds as $pid) {
            if ($pid && (Entities::subtypeRow($db, $pid)['living_status'] ?? null) === 'living') {
                return 'restricted';
            }
        }
        return 'public';
    }

    private static function title(Db $db, array $e): string
    {
        return (string) Entities::titleOf($db, (int) $e['id']);
    }

    public static function applyRelationship(Db $db, array $clean, ?int $actorId, ?int $submissionId): int
    {
        $a = self::pub($db, $clean['person_a'], 'person');
        $b = self::pub($db, $clean['person_b'], 'person');
        [$x, $y] = self::canonicalPair((int) $a['id'], (int) $b['id'], $clean['relationship_type']);
        $cols = ['person_a_id' => $x, 'person_b_id' => $y, 'relationship_type' => $clean['relationship_type'],
            'status' => ($clean['status'] ?? null) ?: 'current', 'notes' => $clean['notes'] ?? null, 'publication_status' => 'published',
            'visibility' => self::linkVisibility($db, (int) $a['id'], (int) $b['id']), 'created_by' => $actorId,
            'submission_id' => $submissionId] + Dates::columns('period', Dates::fromArray($clean['period'] ?? null));
        $id = self::insertRow($db, 'relationships', $cols);
        $claim = self::title($db, $a) . ' — ' . strtolower(Vocab::RELATIONSHIP_TYPES[$clean['relationship_type']][0]) . ' — ' . self::title($db, $b);
        foreach ([$a, $b] as $p) {
            self::storeSources($db, (int) $p['id'], $clean['sources'] ?? null, $actorId, 'relationship', $claim);
            Entities::addRevision($db, (int) $p['id'], $actorId, 'Relationship added (' . str_replace('_', ' ', $clean['relationship_type']) . ')', null, $submissionId);
        }
        Audit::log($db, $actorId, 'relationship.published', 'relationship', $id, ['submission' => $submissionId]);
        return $id;
    }

    public static function applyAffiliation(Db $db, array $clean, ?int $actorId, ?int $submissionId): int
    {
        $p = self::pub($db, $clean['person'], 'person');
        $o = self::pub($db, $clean['organization'], 'organization');
        $pl = self::pub($db, $clean['place'] ?? null, 'place');
        $cols = ['person_id' => $p['id'], 'organization_id' => $o['id'], 'role' => $clean['role'] ?? null]
            + Dates::columns('period', Dates::fromArray($clean['period'] ?? null))
            + ['place_id' => $pl ? $pl['id'] : null, 'evidence_status' => 'unverified', 'notes' => $clean['notes'] ?? null,
                'publication_status' => 'published', 'visibility' => self::linkVisibility($db, (int) $p['id']),
                'submission_id' => $submissionId, 'created_by' => $actorId];
        $id = self::insertRow($db, 'affiliations', $cols);
        $claim = self::title($db, $o) . (!empty($clean['role']) ? " — {$clean['role']}" : '');
        self::storeSources($db, (int) $p['id'], $clean['sources'] ?? null, $actorId, 'affiliation', $claim);
        foreach ([$p, $o] as $e) {
            Entities::addRevision($db, (int) $e['id'], $actorId, 'Affiliation added', null, $submissionId);
        }
        Audit::log($db, $actorId, 'affiliation.published', 'affiliation', $id, ['submission' => $submissionId]);
        return $id;
    }

    public static function applyMembership(Db $db, array $clean, ?int $actorId, ?int $submissionId): int
    {
        $f = self::pub($db, $clean['family'], 'family');
        $p = self::pub($db, $clean['person'], 'person');
        $cols = ['family_id' => $f['id'], 'person_id' => $p['id'], 'role_note' => $clean['role_note'] ?? null]
            + Dates::columns('period', Dates::fromArray($clean['period'] ?? null))
            + ['publication_status' => 'published', 'visibility' => self::linkVisibility($db, (int) $p['id']),
                'created_by' => $actorId, 'submission_id' => $submissionId];
        $id = self::insertRow($db, 'family_memberships', $cols);
        self::storeSources($db, (int) $f['id'], $clean['sources'] ?? null, $actorId, 'members', 'Member: ' . self::title($db, $p));
        foreach ([$f, $p] as $e) {
            Entities::addRevision($db, (int) $e['id'], $actorId, 'Family member added', null, $submissionId);
        }
        Audit::log($db, $actorId, 'membership.published', 'family_membership', $id, ['submission' => $submissionId]);
        return $id;
    }

    public static function applyParticipation(Db $db, array $clean, ?int $actorId, ?int $submissionId): int
    {
        $ev = self::pub($db, $clean['event'], 'event');
        $p = self::pub($db, $clean['person'] ?? null, 'person');
        $o = self::pub($db, $clean['organization'] ?? null, 'organization');
        $who = $p ?: $o;
        $cols = ['event_id' => $ev['id'], 'person_id' => $p ? $p['id'] : null, 'organization_id' => $o ? $o['id'] : null,
            'role' => $clean['role'] ?? null, 'evidence_status' => 'unverified', 'notes' => $clean['notes'] ?? null,
            'publication_status' => 'published', 'submission_id' => $submissionId, 'created_by' => $actorId];
        $id = self::insertRow($db, 'event_participants', $cols);
        $claim = 'Participant: ' . self::title($db, $who) . (!empty($clean['role']) ? " — {$clean['role']}" : '');
        self::storeSources($db, (int) $ev['id'], $clean['sources'] ?? null, $actorId, 'participants', $claim);
        foreach ([$ev, $who] as $e) {
            Entities::addRevision($db, (int) $e['id'], $actorId, 'Event participant added', null, $submissionId);
        }
        Audit::log($db, $actorId, 'participation.published', 'event_participant', $id, ['submission' => $submissionId]);
        return $id;
    }

    public static function applyLink(Db $db, string $kind, array $clean, ?int $actorId, ?int $submissionId): int
    {
        return match ($kind) {
            'relationship' => self::applyRelationship($db, $clean, $actorId, $submissionId),
            'affiliation' => self::applyAffiliation($db, $clean, $actorId, $submissionId),
            'membership' => self::applyMembership($db, $clean, $actorId, $submissionId),
            'participation' => self::applyParticipation($db, $clean, $actorId, $submissionId),
        };
    }
}
