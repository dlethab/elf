<?php
declare(strict_types=1);

namespace Elf\Tools;

use Elf\App;
use Elf\Config;
use Elf\Db;
use Elf\Services\Collections;
use Elf\Services\Entities;
use Elf\Services\Explorations;
use Elf\Services\Passwords;
use Elf\Services\Records;
use Elf\Services\Util;

/**
 * A SEPARATE sample archive for trying every part of the site: instance/sample.db (+ instance/sample-media).
 *
 * It never touches the real database. Everything in it is fictional and labelled so on every page:
 * - every record is flagged is_fictional_test and its name ends in "(FICTIONAL)";
 * - dates fall between 2040 and 2099, so nothing can be mistaken for history;
 * - places carry TEST-ONLY coordinates (needed to try the map). They are not claims about any real place, and the
 *   regions are fictional ("… Test Region"); this is why the sample lives in its own database;
 * - images are generated placeholder graphics marked "SAMPLE IMAGE · FICTIONAL", never pictures of real events.
 *
 * Records reach the archive through the same code a real contribution uses: published records through the validation
 * and publication functions, and the workflow examples (photos, drafts, review, revision, corrections, forum, contact)
 * through the site's own forms, driven by an in-process client as a contributor, editors and moderators.
 * The same sample as the Python edition's (elf_archive/sampledata.py).
 */
final class SampleData
{
    public const TAG = ' (FICTIONAL)';

    /** username, roles, verified, what the account is for */
    public const USERS = [
        ['sample_admin', ['administrator', 'editor'], true, 'administrator: users, roles, audit log, export'],
        ['sample_editor', ['editor'], true, 'editor: review queue, publish, curate, explorations'],
        ['sample_editor2', ['editor'], true, 'second editor (an editor cannot review their own submissions)'],
        ['sample_moderator', ['moderator'], true, 'forum moderator: reports and moderation log'],
        ['sample_researcher', ['researcher'], true, 'vetted researcher: sees restricted research material'],
        ['sample_contrib', [], true, 'contributor: drafts, submissions, photos, corrections, notifications'],
        ['sample_family', [], true, 'family representative for the Testfield family'],
        ['sample_member', [], true, 'community member: forum posts and replies'],
        ['sample_newcomer', [], false, 'new account whose email is not verified yet (can draft, cannot submit)'],
    ];

    /** name, type, region, lat, lon, precision, aliases, note */
    public const PLACES = [
        ['Saltmere', 'town_city', 'Coastal Test Region', '15.70', '39.36', 'exact', "Salt Mere\nSaltmeer", ''],
        ['Highridge', 'town_city', 'Central Test Region', '15.05', '38.80', 'exact', 'High Ridge', ''],
        ['Amber Hollow', 'village', 'North Test Region', '15.95', '38.35', 'approximate', 'Amberhollow',
            'Only the valley is known; the exact site of the village is not documented in the sample sources.'],
        ['Greenvale', 'village', 'West Test Region', '15.10', '37.60', 'exact', '', ''],
        ['Redcliff Pass', 'conflict_location', 'Central Test Region', '15.55', '38.70', 'exact', '', ''],
        ['Lowland Plain', 'region', 'West Test Region', '15.20', '37.10', 'region_centroid', 'The Lowlands',
            'Shown at the centre of the plain; the sample records do not name a single point.'],
        ['Stonebridge Memorial', 'memorial_site', 'South Test Region', '14.95', '39.15', 'exact', '', ''],
        ['Cedar Wells', 'displacement_location', 'North Test Region', '16.30', '38.05', 'approximate', 'Cedar Springs',
            'The camp moved several times; this is the area given in the sample relief reports.'],
        ['Northpass Camp', 'organizational_location', 'North Test Region', '16.60', '38.60', 'exact', '', ''],
        ['Old Market Quarter', 'historical_site', 'Coastal Test Region', null, null, null, '', ''],      // no coordinates
        ['Upper Valley', 'geographic_feature', 'North Test Region', null, null, null, '', ''],
    ];

    public const SOURCES = [
        'minutes' => 'Test Front Minutes, vol. 1 (FICTIONAL) | p. 3',
        'gazette' => 'Saltmere Gazette (FICTIONAL) | issue 12, p. 2 | https://example.test/gazette/12',
        'register' => 'Highridge Municipal Register (FICTIONAL) | folio 22',
        'relief' => 'Relief Association Field Reports (FICTIONAL) | report 7',
        'memoir' => "A Teacher's Notebook, a memoir (FICTIONAL) | ch. 4",
        'survey' => 'Test Survey of Villages (FICTIONAL) | map sheet 3',
    ];

    /** title, type, date, place, summary, source keys */
    public const EVENTS = [
        ['Founding meeting of the Test Front', 'meeting_conference', '2061-04-12', 'Northpass Camp',
            'Delegates meet at Northpass Camp and agree the founding charter of the Test Front.', ['minutes']],
        ['Saltmere harbour strike', 'community_event', '2063-09', 'Saltmere',
            'Harbour workers in Saltmere stop work for nine days over wages.', ['gazette']],
        ['Engagement at Redcliff Pass', 'battle_conflict', 'c. 2065', 'Redcliff Pass',
            'An armed clash at Redcliff Pass. The sample sources disagree about the year.', ['minutes', 'memoir']],
        ['Highridge declaration', 'statement_publication', '2066-01-20', 'Highridge',
            "A public statement read in Highridge setting out the Test Front's aims.", ['register']],
        ['Drought relief at Cedar Wells', 'humanitarian_event', '2068 to 2070', 'Cedar Wells',
            'Food and water distribution for families gathered at Cedar Wells during the drought.', ['relief']],
        ['Displacement from the Lowland Plain', 'displacement_migration', '2070s', 'Lowland Plain',
            'Families leave the Lowland Plain over several years; only the decade is documented.', ['relief']],
        ['Second congress of the Test Front', 'meeting_conference', '2072-03 to 2072-04', 'Northpass Camp',
            'A second, longer congress revises the charter.', ['minutes']],
        ['Opening of the Greenvale school', 'community_event', '2074', 'Greenvale',
            'A village school opens in Greenvale with two teachers.', ['memoir']],
        ['Ceasefire talks near Amber Hollow', 'political_development', '2077-06-02', 'Amber Hollow',
            'Talks held somewhere near Amber Hollow; the meeting place itself is uncertain.', ['gazette']],
        ['Coastal radio broadcast', 'statement_publication', '2079-05', 'Saltmere',
            'A broadcast from Saltmere announces the ceasefire terms.', ['gazette']],
        ['Reorganisation of the Test Front', 'organizational_development', '2081', 'Highridge',
            'The Test Front reorganises into regional committees.', ['minutes']],
        ['Return of displaced families to Cedar Wells', 'displacement_migration', '2083 to 2086', 'Cedar Wells',
            'Families return in stages to the Cedar Wells area.', ['relief']],
        ['Dedication of the Stonebridge Memorial', 'commemoration', '2085-11-11', 'Stonebridge Memorial',
            'A memorial is dedicated to those who died in the Redcliff engagement.', ['register']],
        ['Greenvale harvest festival', 'community_event', '2090s', 'Greenvale',
            'An annual festival revived in the 2090s; only the decade is documented.', []],
        ['Peace conference in Highridge', 'political_development', '2092-07-15', 'Highridge',
            'A conference in Highridge closes the period covered by the sample.', ['register', 'minutes']],
        ['Gathering in the Old Market Quarter', 'other', '', 'Old Market Quarter',
            'A gathering remembered in oral accounts; its date is not documented.', []],
        ['Meeting of the coastal committee', 'meeting_conference', '2069', null,
            'A committee meeting whose location is not established, so it does not appear on the map.', ['minutes']],
    ];

    public const PEOPLE = [
        'amina' => ['preferred_name' => 'Amina Testfield', 'full_name' => 'Amina Selam Testfield', 'aliases' => "Amina T.\nAmina Testfeld",
            'occupation' => 'Teacher', 'living_status' => 'deceased', 'birth' => 'c. 2040', 'birth_place' => 'Amber Hollow',
            'death' => '2091-02', 'death_place' => 'Highridge',
            'summary' => 'A teacher who opened the Greenvale school.',
            'biography' => "Amina Testfield taught in Greenvale for twenty years.\nThis biography is sample text and describes no real person.",
            'sources' => ['memoir']],
        'samuel' => ['preferred_name' => 'Samuel Testfield', 'living_status' => 'deceased', 'birth' => '2062-05-14', 'birth_place' => 'Greenvale',
            'death' => '2098', 'occupation' => 'Radio operator', 'summary' => "Amina's son; worked on the coastal broadcasts.", 'sources' => ['gazette']],
        'hana' => ['preferred_name' => 'Hana Testfield', 'living_status' => 'unknown', 'birth' => '2065', 'birth_place' => 'Greenvale',
            'summary' => "Amina's daughter. Little is documented about her later life."],
        'daniel' => ['preferred_name' => 'Daniel Testmark', 'aliases' => 'Dani Testmark', 'occupation' => 'Organizer', 'living_status' => 'deceased',
            'birth' => '2042-03-02', 'birth_place' => 'Saltmere', 'death' => '2087', 'death_place' => 'Saltmere',
            'summary' => 'A founding member of the Test Front.', 'sources' => ['minutes']],
        'omar' => ['preferred_name' => 'Omar Testmark', 'living_status' => 'deceased', 'birth' => 'c. 2045', 'birth_place' => 'Saltmere',
            'death' => 'c. 2070', 'occupation' => 'Harbour worker', 'summary' => "Daniel's brother; took part in the harbour strike."],
        'yonas' => ['preferred_name' => 'Yonas Testbrook', 'living_status' => 'deceased', 'birth' => 'c. 2038', 'death' => '2065',
            'death_place' => 'Redcliff Pass', 'summary' => 'Died in the Redcliff engagement.', 'sources' => ['memoir']],
        'selam' => ['preferred_name' => 'Selam Testbrook', 'living_status' => 'deceased', 'birth' => '2041', 'death' => '2093',
            'birth_place' => 'Greenvale', 'occupation' => 'Nurse', 'summary' => 'Worked with the relief association at Cedar Wells.',
            'sources' => ['relief']],
        'ibrahim' => ['preferred_name' => 'Ibrahim Testlake', 'living_status' => 'deceased', 'birth' => '2047 to 2049', 'death' => '2095',
            'occupation' => 'Relief coordinator', 'summary' => 'Coordinated the drought relief; his birth year is given only as a range.',
            'sources' => ['relief']],
        'ruth' => ['preferred_name' => 'Ruth Teststone', 'living_status' => 'unknown', 'birth' => '2052',
            'summary' => 'Named in the Highridge register; nothing else is known yet.'],
        'messenger' => ['preferred_name' => 'Unknown messenger of Northpass', 'living_status' => 'unknown',
            'summary' => 'A messenger mentioned in the minutes without a name or dates.'],
        'lula' => ['preferred_name' => 'Lula Testrow', 'living_status' => 'living', 'birth' => '2071',
            'summary' => 'A living person: kept private until an editor records consent (you will not see her publicly).'],
    ];

    // ───────────── generated placeholder files ─────────────
    /** An abstract placeholder graphic, plainly labelled as a fictional sample (not a photograph). */
    public static function image(string $title, array $colours, int $seed): string
    {
        [$w, $h] = [1200, 800];
        $im = imagecreatetruecolor($w, $h);
        $c = fn (array $rgb) => imagecolorallocate($im, $rgb[0], $rgb[1], $rgb[2]);
        imagefilledrectangle($im, 0, 0, $w, $h, $c($colours[0]));
        imagesetthickness($im, 6);
        for ($i = 0; $i < $w + $h; $i += 36) {                       // diagonal hatching: obviously a graphic
            imageline($im, $i, 0, $i - $h, $h, $c($colours[1]));
        }
        imagesetthickness($im, 1);
        $pts = [0, $h];
        for ($x = 0; $x <= $w; $x += 150) {
            array_push($pts, $x, (int) ($h * (0.55 + 0.12 * (($x * ($seed + 3)) % 7) / 7)));
        }
        array_push($pts, $w, $h);
        imagefilledpolygon($im, $pts, $c($colours[2]));
        imagefilledrectangle($im, 60, 60, $w - 60, 250, $c([255, 255, 255]));
        self::text($im, 90, 85, 'SAMPLE IMAGE · FICTIONAL', [27, 122, 56], 4);
        self::text($im, 90, 170, mb_substr($title, 0, 60), [28, 35, 41], 2);
        ob_start();
        imagejpeg($im, null, 85);
        return (string) ob_get_clean();
    }

    /** Text in GD's built-in font, enlarged (no font file needed). */
    private static function text(\GdImage $im, int $x, int $y, string $text, array $rgb, int $scale): void
    {
        $text = (string) mb_convert_encoding($text, 'ISO-8859-2', 'UTF-8');
        $fw = imagefontwidth(5);
        $fh = imagefontheight(5);
        $tw = max(1, $fw * strlen($text));
        $t = imagecreatetruecolor($tw, $fh);
        imagefilledrectangle($t, 0, 0, $tw, $fh, imagecolorallocate($t, 255, 255, 255));
        imagestring($t, 5, 0, 0, $text, imagecolorallocate($t, $rgb[0], $rgb[1], $rgb[2]));
        imagecopyresampled($im, $t, $x, $y, 0, 0, $tw * $scale, $fh * $scale, $tw, $fh);
    }

    /** A one-page PDF with plain text and no active content. */
    public static function pdf(array $lines): string
    {
        $text = 'BT /F1 18 Tf 60 760 Td 24 TL ' . implode(' ', array_map(fn ($ln) => '(' . str_replace(['(', ')'], ['[', ']'], $ln) . ') Tj T*', $lines)) . ' ET';
        $objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
            '<< /Length ' . strlen($text) . " >>\nstream\n{$text}\nendstream", '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
        $out = "%PDF-1.4\n";
        $offsets = [];
        foreach ($objs as $i => $o) {
            $offsets[] = strlen($out);
            $out .= ($i + 1) . " 0 obj\n{$o}\nendobj\n";
        }
        $xref = strlen($out);
        $out .= "xref\n0 " . (count($objs) + 1) . "\n0000000000 65535 f \n";
        foreach ($offsets as $o) {
            $out .= sprintf("%010d 00000 n \n", $o);
        }
        $out .= 'trailer' . "\n<< /Size " . (count($objs) + 1) . " /Root 1 0 R >>\nstartxref\n{$xref}\n%%EOF\n";
        return $out;
    }

    private static function src(array $keys): string
    {
        return implode("\n", array_map(fn ($k) => self::SOURCES[$k], $keys));
    }

    /** Create the sample database from scratch. Returns [password, report lines]. */
    public static function build(string $dbPath, string $mediaRoot, string $realDbPath): array
    {
        $abs = fn (string $p) => str_replace('\\', '/', (string) (realpath(dirname(Config::path($p))) ?: dirname(Config::path($p)))) . '/' . basename($p);
        if (strtolower($abs($dbPath)) === strtolower($abs($realDbPath))) {
            throw new \RuntimeException("The sample must go in its own database, not the archive's.");
        }
        foreach ([$dbPath, $dbPath . '-wal', $dbPath . '-shm'] as $p) {
            if (is_file(Config::path($p))) {
                unlink(Config::path($p));
            }
        }
        self::rmtree(Config::path($mediaRoot));

        $password = 'sample-' . Util::tokenUrlsafe(8);
        $app = new App(['ENV' => 'development', 'DATABASE_PATH' => $dbPath, 'MEDIA_ROOT' => $mediaRoot, 'AUTO_MIGRATE' => true,
            'SECRET_KEY' => bin2hex(random_bytes(32)), 'REQUIRE_EMAIL_VERIFICATION' => true]);
        $db = $app->db();
        $report = [];

        // accounts
        $ids = [];
        $db->tx(function () use ($db, $password, &$ids) {
            foreach (self::USERS as [$name, $roles, $verified]) {
                $ids[$name] = $db->insert('INSERT INTO users(email, username, display_name, password_hash, email_verified_at) VALUES (?,?,?,?,?)',
                    ["{$name}@example.test", $name, ucwords(str_replace('_', ' ', $name)), Passwords::hash($password), $verified ? Util::nowIso() : null]);
                foreach ($roles as $r) {
                    $db->exec('INSERT INTO user_roles(user_id, role) VALUES (?,?)', [$ids[$name], $r]);
                }
            }
        });
        $editor = $ids['sample_editor'];

        // A published record through the normal validation and publication code.
        $make = function (string $kind, array $raw, ?array $consents = null) use ($db, $ids, $editor): array {
            [$clean, $errors] = Records::validate($db, $kind, $raw, false);
            if ($errors) {
                throw new \RuntimeException("sample {$kind}: " . json_encode($errors));
            }
            if ($consents !== null) {
                $clean['consents'] = ['granted' => $consents, 'note' => 'FICTIONAL sample consent; no real interview exists.'];
            }
            $sid = $db->insert("INSERT INTO submissions(kind, proposed_data, status, submitter_id, submitted_at, published_at, reviewer_id) "
                . "VALUES (?,?, 'published', ?, ?, ?, ?)", [$kind, Util::json($clean), $ids['sample_contrib'], Util::nowIso(), Util::nowIso(), $editor]);
            $eid = Records::applyNew($db, $kind, $clean, $editor, $sid, $consents !== null, true);
            $db->exec('UPDATE submissions SET result_entity_id=? WHERE id=?', [$eid, $sid]);
            return Entities::get($db, $eid);
        };
        $link = function (string $kind, array $raw) use ($db, $editor): void {
            [$clean, $errors] = Records::validate($db, $kind, $raw);
            if ($errors) {
                throw new \RuntimeException("sample {$kind}: " . json_encode($errors));
            }
            Records::applyLink($db, $kind, $clean, $editor, null);
        };

        $P = $E = $H = $F = $ORG = [];
        $db->tx(function () use ($db, $make, $link, $ids, $editor, &$P, &$E, &$H, &$F, &$ORG) {
            foreach (self::PLACES as [$name, $ptype, $region, $lat, $lon, $prec, $aliases, $note]) {
                $raw = ['primary_name' => $name . self::TAG, 'place_type' => $ptype, 'country' => 'Sample country (FICTIONAL)', 'admin_region' => $region,
                    'aliases' => $aliases, 'coord_note' => $note,
                    'overview' => "{$name} is a fictional place in the sample archive. Its coordinates are test values for trying the map, "
                        . 'not a claim about any real location.',
                    'sources' => $lat ? self::SOURCES['survey'] : ''];
                if ($lat) {
                    $raw += ['latitude' => $lat, 'longitude' => $lon, 'coord_precision' => $prec];
                }
                $P[$name] = $make('place', $raw);
            }
            foreach (self::EVENTS as [$title, $etype, $date, $place, $summary, $srcs]) {
                $E[$title] = $make('event', ['title' => $title . self::TAG, 'event_type' => $etype, 'date' => $date,
                    'place' => $place ? $P[$place]['public_id'] : '', 'summary' => $summary,
                    'description' => $summary . "\n\nThis account is sample text written for trying the archive. It describes nothing real.",
                    'sources' => self::src($srcs)]);
            }
            foreach (self::PEOPLE as $key => $f) {
                $raw = array_merge($f, ['preferred_name' => $f['preferred_name'] . self::TAG, 'sources' => self::src($f['sources'] ?? [])]);
                foreach (['birth_place', 'death_place'] as $k) {
                    if (!empty($raw[$k])) {
                        $raw[$k] = $P[$raw[$k]]['public_id'];
                    }
                }
                $H[$key] = $make('person', $raw);
            }
            foreach ([['testfield', 'Testfield family', 'Amber Hollow and Greenvale (fictional)', ['amina', 'samuel', 'hana'],
                        'Three generations of teachers and radio operators.'],
                      ['testmark', 'Testmark family', 'Saltmere (fictional)', ['daniel', 'omar'], 'A harbour family from Saltmere.'],
                      ['testbrook', 'Testbrook family', 'Greenvale (fictional)', ['yonas', 'selam'], 'Remembered through the Redcliff memorial.']]
                     as [$key, $name, $region, $members, $summary]) {
                $F[$key] = $make('family', ['display_name' => $name . self::TAG, 'region_note' => $region, 'summary' => $summary,
                    'narrative' => "{$summary}\nThis family history is sample text and describes no real family."]);
                foreach ($members as $m) {
                    $db->exec("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility, created_by) "
                        . "VALUES (?,?, 'published', 'public', ?)", [$F[$key]['id'], $H[$m]['id'], $editor]);
                }
            }
            foreach ([['amina', 'parent_of', 'samuel', 'current'], ['amina', 'parent_of', 'hana', 'current'],
                      ['samuel', 'sibling_of', 'hana', 'current'], ['daniel', 'sibling_of', 'omar', 'current'],
                      ['yonas', 'spouse_of', 'selam', 'historical']] as [$a, $rel, $b, $status]) {
                $link('relationship', ['person_a' => $H[$a]['public_id'], 'person_b' => $H[$b]['public_id'], 'relationship_type' => $rel,
                    'status' => $status, 'notes' => 'Sample relationship (FICTIONAL).']);
            }
            $db->exec('INSERT INTO family_representatives(user_id, family_id, granted_by) VALUES (?,?,?)',
                [$ids['sample_family'], $F['testfield']['id'], $ids['sample_admin']]);
            foreach ([['front', 'Test Front', '2060 to 2090', 'A fictional political organization used throughout the sample.'],
                      ['relief', 'Test Relief Association', '2068 to 2099', 'A fictional relief association.'],
                      ['teachers', "Test Teachers' Union", 'c. 2074', 'A fictional union of village teachers.']] as [$key, $name, $active, $desc]) {
                $ORG[$key] = $make('organization', ['name' => $name . self::TAG, 'active' => $active, 'description' => $desc . ' It never existed.']);
            }
            foreach ([['daniel', 'front', 'Founding member', '2061 to 2087', 'Northpass Camp'], ['yonas', 'front', 'Member', '2061 to 2065', ''],
                      ['amina', 'teachers', 'Member', '2074 to 2091', 'Greenvale'], ['ibrahim', 'relief', 'Coordinator', '2068 to 2086', 'Cedar Wells'],
                      ['selam', 'relief', 'Nurse', '2068 to 2070', 'Cedar Wells']] as [$person, $org, $role, $period, $place]) {
                $link('affiliation', ['person' => $H[$person]['public_id'], 'organization' => $ORG[$org]['public_id'], 'role' => $role . ' (fictional)',
                    'period' => $period, 'place' => $place ? $P[$place]['public_id'] : '', 'notes' => 'Sample affiliation (FICTIONAL).']);
            }
            foreach ([['Founding meeting of the Test Front', 'daniel', 'Chair'], ['Founding meeting of the Test Front', 'yonas', 'Delegate'],
                      ['Saltmere harbour strike', 'omar', 'Striker'], ['Engagement at Redcliff Pass', 'yonas', 'Combatant'],
                      ['Drought relief at Cedar Wells', 'ibrahim', 'Coordinator'], ['Drought relief at Cedar Wells', 'selam', 'Nurse'],
                      ['Opening of the Greenvale school', 'amina', 'Teacher'], ['Coastal radio broadcast', 'samuel', 'Radio operator'],
                      ['Second congress of the Test Front', 'daniel', 'Delegate'], ['Peace conference in Highridge', 'ruth', 'Observer']] as [$ev, $who, $role]) {
                $link('participation', ['event' => $E[$ev]['public_id'], 'person' => $H[$who]['public_id'], 'role' => $role . ' (fictional)']);
            }
            foreach ([['Founding meeting of the Test Front', 'front'], ['Second congress of the Test Front', 'front'],
                      ['Drought relief at Cedar Wells', 'relief'], ['Return of displaced families to Cedar Wells', 'relief']] as [$ev, $org]) {
                $link('participation', ['event' => $E[$ev]['public_id'], 'organization' => $ORG[$org]['public_id'], 'role' => 'Organizer (fictional)']);
            }
            // evidence: assessed citations, a location source, and where the sources disagree
            foreach ([['Test Front Minutes, vol. 1 (FICTIONAL)', 'well_supported'], ['Saltmere Gazette (FICTIONAL)', 'source_cited'],
                      ['Relief Association Field Reports (FICTIONAL)', 'testimony'], ["A Teacher's Notebook, a memoir (FICTIONAL)", 'family_recollection'],
                      ['Test Survey of Villages (FICTIONAL)', 'source_cited']] as [$title, $status]) {
                $db->exec('UPDATE citations SET evidence_status=? WHERE source_id IN (SELECT entity_id FROM sources WHERE title=?)', [$status, $title]);
            }
            $db->exec("UPDATE citations SET field_name='coordinates' WHERE source_id IN (SELECT entity_id FROM sources WHERE title=?)",
                ['Test Survey of Villages (FICTIONAL)']);
            $redcliff = $E['Engagement at Redcliff Pass'];
            $db->exec("UPDATE citations SET evidence_status='disputed' WHERE target_id=?", [$redcliff['id']]);
            foreach ([[$redcliff['id'], 'Year of the engagement', 'The memoir places the engagement in 2066, a year later than the minutes.',
                       "A Teacher's Notebook (FICTIONAL)", 1, 0],
                      [$P['Amber Hollow']['id'], 'Location of the village', 'A second account places the village on the far side of the valley, about 8 km east.',
                       'Test witness (FICTIONAL)', 0, 1]] as [$eid, $topic, $text, $by, $d, $loc]) {
                $db->exec('INSERT INTO conflicting_accounts(entity_id, topic, account_text, attributed_to, is_public, concerns_date, '
                    . 'concerns_location, created_by) VALUES (?,?,?,?,1,?,?,?)', [$eid, $topic . self::TAG, $text, $by, $d, $loc, $editor]);
            }
            $db->exec('UPDATE event_places SET is_uncertain=1 WHERE event_id=?', [$E['Ceasefire talks near Amber Hollow']['id']]);
            // oral histories: one with a published transcript, one whose consent does not allow publication
            $make('oral_history', ['title' => 'Interview about the Greenvale school' . self::TAG, 'interviewee' => $H['hana']['public_id'],
                'interviewer_text' => 'Sample Interviewer (FICTIONAL)', 'recorded' => '2096-06',
                'recording_location_note' => 'Greenvale (fictional)', 'language' => 'English',
                'summary' => "Hana Testfield remembers her mother's school. Sample text only.",
                'topics' => "Schools\nGreenvale\nFamily", 'related' => "{$P['Greenvale']['public_id']}\n{$H['amina']['public_id']}",
                'transcript_text' => "[00:00] Interviewer: This is a FICTIONAL sample transcript.\n"
                    . "[00:06] Hana Testfield: My mother opened the school in 2074.\n"
                    . '[00:15] Hana Testfield: Nothing in this transcript describes real events.',
                'transcript_kind' => 'verbatim'],
                ['record', 'store', 'publish_transcript', 'use_excerpts', 'research_access']);
            $make('oral_history', ['title' => 'Interview about the harbour strike' . self::TAG, 'interviewee_text' => 'A harbour worker (FICTIONAL)',
                'recorded' => '2097', 'language' => 'English', 'summary' => 'Recorded, but the interviewee did not agree to publication.',
                'transcript_text' => '[00:00] FICTIONAL restricted transcript.', 'transcript_kind' => 'verbatim'],
                ['record', 'store', 'research_access']);
            $db->exec('UPDATE entities SET is_fictional_test=1');
        });
        $report[] = count($P) . ' places, ' . count($E) . ' events, ' . count($H) . ' people, ' . count($F) . ' families, '
            . count($ORG) . ' organizations, 2 oral histories';

        // ── journeys through the site's own forms ──
        $users = [];
        foreach (['sample_contrib', 'sample_editor', 'sample_editor2', 'sample_member', 'sample_moderator', 'sample_family'] as $n) {
            $users[$n] = new Client($app, $n, $password);
        }
        [$contrib, $ed, $ed2] = [$users['sample_contrib'], $users['sample_editor'], $users['sample_editor2']];
        $tmp = sys_get_temp_dir() . '/elf-sample-' . bin2hex(random_bytes(4));
        mkdir($tmp);

        $lastSid = fn () => (int) $db->val('SELECT MAX(id) FROM submissions WHERE submitter_id=?', [$ids['sample_contrib']]);
        $status = fn (int $sid) => $db->val('SELECT status FROM submissions WHERE id=?', [$sid]);
        $upload = function (int $sid, string $data, string $name, array $meta) use ($contrib, $tmp) {
            $path = $tmp . '/' . bin2hex(random_bytes(6));
            file_put_contents($path, $data);
            $r = $contrib->post("/dashboard/submissions/{$sid}/photos", ['rights_declared' => '1'] + $meta, ['photo' => [$path, $name]]);
            @unlink($path);
            return $r;
        };
        $draft = function (string $kind, array $fields, array $files = []) use ($contrib, $lastSid, $upload) {
            $contrib->post("/contribute/{$kind}", $fields + ['action' => 'draft',
                'contributor_note' => 'Sample contribution (FICTIONAL), made by the sample builder.']);
            $sid = $lastSid();
            foreach ($files as [$data, $name, $meta]) {
                $r = $upload($sid, $data, $name, $meta);
                if (!in_array($r->status, [200, 302], true)) {
                    throw new \RuntimeException("sample upload failed: {$r->status}");
                }
            }
            return $sid;
        };
        $submit = function (int $sid) use ($contrib, $status) {
            $contrib->post("/dashboard/submissions/{$sid}/submit");
            if ($status($sid) !== 'submitted') {
                throw new \RuntimeException("sample: submission {$sid} is {$status($sid)}");
            }
        };
        $publish = function (int $sid, bool $public = true) use ($ed, $db, $status) {
            $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'under_review']);
            foreach ($db->all('SELECT id, rights_status FROM submission_photos WHERE submission_id=?', [$sid]) as $ph) {
                $ed->post("/editor/submissions/{$sid}/photos/{$ph['id']}", ['decision' => 'accept', 'access' => $public ? 'public' : 'restricted',
                    'rights_status' => $ph['rights_status']]);
            }
            $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'approved', 'message' => 'Thank you: checked against the sample sources.']);
            $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'published']);
            if ($status($sid) !== 'published') {
                throw new \RuntimeException("sample: submission {$sid} is {$status($sid)}");
            }
            return (int) $db->val('SELECT result_entity_id FROM submissions WHERE id=?', [$sid]);
        };
        $green = [[180, 215, 244], [160, 200, 236], [35, 158, 70]];
        $blue = [[226, 239, 250], [200, 222, 240], [47, 111, 168]];
        $meta = fn (string $caption, string $creator, string $taken, string $rights = 'public_domain', string $holder = '') => [
            'caption' => $caption . ' (FICTIONAL sample image)', 'creator_text' => $creator, 'taken' => $taken, 'rights_status' => $rights,
            'rights_holder' => $holder];

        // 1. a place with photographs, contributed with a point chosen on the map, reviewed and published
        $sid = $draft('place', ['primary_name' => 'Saltmere Lighthouse' . self::TAG, 'place_type' => 'historical_site', 'admin_region' => 'Coastal Test Region',
            'latitude' => '15.74000', 'longitude' => '39.40000', 'coord_precision' => 'approximate',
            'coord_note' => 'Point chosen on the map by the contributor; test value.',
            'overview' => 'A fictional lighthouse on the Saltmere coast.', 'sources' => self::SOURCES['gazette']],
            [[self::image('Saltmere Lighthouse, sample graphic', $green, 1), 'lighthouse.jpg',
                $meta('The lighthouse seen from the harbour', 'Sample Photographer (FICTIONAL)', 'c. 2070')],
             [self::image('Harbour wall, sample graphic', $blue, 2), 'harbour.jpg',
                $meta('The harbour wall below the lighthouse', 'Sample Photographer (FICTIONAL)', '2071-08',
                    'copyrighted_permission_granted', 'Saltmere Gazette (FICTIONAL)')]]);
        $submit($sid);
        $lighthouse = $publish($sid);
        // 2. an event with photographs and a document
        $sid = $draft('event', ['title' => 'Opening of the Saltmere reading room' . self::TAG, 'event_type' => 'community_event', 'date' => '2075-10-03',
            'place' => $P['Saltmere']['public_id'], 'summary' => 'A public reading room opens in Saltmere.', 'sources' => self::SOURCES['gazette']],
            [[self::image('Reading room, sample graphic', $green, 3), 'reading-room.jpg',
                $meta('Readers on the opening day', 'Saltmere Gazette (FICTIONAL)', '2075-10-03')],
             [self::pdf(['FICTIONAL SAMPLE DOCUMENT', 'Programme for the opening of the reading room', 'Saltmere, 3 October 2075',
                    'This document was generated for the sample archive.']), 'programme.pdf',
                ['item_type' => 'pamphlet_newsletter', 'caption' => 'Printed programme for the opening (FICTIONAL sample document)']
                + $meta('Printed programme for the opening', 'Reading room committee (FICTIONAL)', '2075-10')]]);
        $submit($sid);
        $reading = $publish($sid);
        // 3. photographs added to existing records through photo-only corrections
        foreach ([[$E['Dedication of the Stonebridge Memorial'], 'Memorial stone, sample graphic', $blue, 4],
                  [$P['Greenvale'], 'Greenvale school building, sample graphic', $green, 5],
                  [$P['Highridge'], 'Highridge main street, sample graphic', $blue, 6],
                  [$E['Drought relief at Cedar Wells'], 'Water distribution point, sample graphic', $green, 7],
                  [$H['amina'], 'Portrait of Amina Testfield, sample graphic', $blue, 9],
                  [$H['daniel'], 'Portrait of Daniel Testmark, sample graphic', $green, 10],
                  [$H['selam'], 'Portrait of Selam Testbrook, sample graphic', $blue, 11]] as [$target, $title, $colours, $n]) {
            $contrib->get("/contribute/correction/{$target['public_id']}");
            $current = Records::formValues(Records::currentClean($db, $target['kind'], (int) $target['id']), $target['kind'], $db);
            $contrib->post("/contribute/correction/{$target['public_id']}",
                ['action' => 'draft', 'contributor_note' => 'Adding a photograph (FICTIONAL sample).'] + $current);
            $sid = $lastSid();
            $upload($sid, self::image($title, $colours, $n), "photo-{$n}.jpg",
                $meta(str_replace(', sample graphic', '', $title), 'Sample Photographer (FICTIONAL)', 'c. ' . (2040 + 5 * $n)));
            $submit($sid);
            $publish($sid);
        }
        $report[] = "10 photographs (3 of them on people's profiles) and 1 document published through contributions with editor review";

        // 4. contributions waiting at each step of the review workflow (for the editor and contributor dashboards)
        $sid = $draft('person', ['preferred_name' => 'Testperson Awaiting Review' . self::TAG, 'living_status' => 'deceased', 'birth' => 'c. 2050',
            'birth_place' => $P['Highridge']['public_id'], 'summary' => "Submitted and waiting in the editors' queue.",
            'sources' => self::SOURCES['register']]);
        $submit($sid);
        $sid = $draft('event', ['title' => 'Market day dispute' . self::TAG, 'event_type' => 'community_event', 'date' => '2078',
            'place' => $P['Saltmere']['public_id'], 'summary' => 'Being reviewed by an editor right now.']);
        $submit($sid);
        $ed2->post("/editor/submissions/{$sid}/transition", ['to' => 'under_review']);
        $sid = $draft('place', ['primary_name' => 'Eastern Well' . self::TAG, 'place_type' => 'village', 'latitude' => '15.40000', 'longitude' => '38.20000',
            'coord_precision' => 'exact', 'overview' => 'Returned to the contributor: the editor asks for a source.']);
        $submit($sid);
        $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'under_review']);
        $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'needs_revision',
            'message' => 'Please add the source for these coordinates, or mark them as approximate.']);
        $sid = $draft('place', ['primary_name' => 'Hilltop Shrine' . self::TAG, 'place_type' => 'historical_site', 'latitude' => '15.85000', 'longitude' => '38.90000',
            'coord_precision' => 'approximate', 'overview' => "A proposed place: shows on the reviewers' map layer.",
            'sources' => self::SOURCES['survey']]);
        $submit($sid);
        $draft('person', ['preferred_name' => 'Testperson Draft' . self::TAG, 'living_status' => 'unknown', 'summary' => 'A draft only the contributor can see.'],
            [[self::image('Unsorted family photograph, sample graphic', $blue, 8), 'draft.jpg',
                $meta('A photograph not yet submitted', 'Unknown', '', 'rights_unknown')]]);
        $daniel = $H['daniel'];
        $current = Records::formValues(Records::currentClean($db, 'person', (int) $daniel['id']), 'person', $db);
        $contrib->post("/contribute/correction/{$daniel['public_id']}", ['occupation' => 'Organizer and harbour clerk', 'action' => 'submit',
            'contributor_note' => 'The Saltmere Gazette (FICTIONAL) also calls him a harbour clerk.'] + $current);
        $report[] = 'review queue: 1 new, 1 under review, 1 returned for revision, 1 proposed place, 1 correction; 1 private draft';

        // 5. a collection and a curated exploration
        $ed->post('/editor/collections', ['title' => 'Saltmere in pictures' . self::TAG, 'description' => 'Sample photographs and documents of Saltmere.',
            'visibility' => 'public', 'is_featured' => '1']);
        $coll = $db->one("SELECT e.* FROM entities e WHERE e.kind='collection' ORDER BY id DESC LIMIT 1");
        $db->tx(function () use ($db, $coll, $editor, $lighthouse, $reading, $E, $H, $ORG, $P) {
            foreach ($db->col('SELECT s.item_id FROM archive_item_subjects s WHERE s.subject_id IN (?,?)', [$lighthouse, $reading]) as $item) {
                Collections::addItem($db, $editor, $coll, ['item' => Entities::get($db, (int) $item)['public_id']]);
            }
            $label = fn (array $e) => Records::refLabel($db, $e['public_id']);
            Explorations::create($db, $editor, [
                'title' => 'The Test Front in the 2060s' . self::TAG,
                'description' => 'How the Test Front began: the founding meeting at Northpass Camp, the Redcliff engagement and the Highridge '
                    . "declaration.\nThe sources disagree about the year of the Redcliff engagement; both accounts are kept.",
                'sources_note' => "Test Front Minutes, vol. 1 (FICTIONAL); A Teacher's Notebook (FICTIONAL).",
                'period_from' => '2060', 'period_to' => '2069', 'is_published' => '1',
                'items' => implode("\n", [$label($E['Founding meeting of the Test Front']) . ' | Where the organization was founded.',
                    $label($E['Engagement at Redcliff Pass']) . ' | The date is disputed.',
                    $label($E['Highridge declaration']), $label($H['daniel']), $label($H['yonas']), $label($ORG['front']),
                    $label($P['Northpass Camp'])])]);
            Explorations::create($db, $editor, [
                'title' => 'Drought and return at Cedar Wells' . self::TAG,
                'description' => "The relief effort at Cedar Wells and the families' return a decade later.",
                'sources_note' => 'Relief Association Field Reports (FICTIONAL).', 'period_from' => '2068', 'period_to' => '2086', 'is_published' => '1',
                'items' => implode("\n", [$label($E['Drought relief at Cedar Wells']), $label($E['Return of displaced families to Cedar Wells']),
                    $label($H['ibrahim']), $label($H['selam']), $label($ORG['relief']), $label($P['Cedar Wells'])])]);
        });

        // 6. community forum: topics, replies, a report for the moderator; and a message to the editors
        [$member, $fam] = [$users['sample_member'], $users['sample_family']];
        foreach ([[$contrib, 'hometowns', 'Memories of Saltmere harbour (FICTIONAL)', 'Does anyone remember the harbour before the lighthouse was built? (Sample post.)'],
                  [$member, 'photo-identification', 'Who is in the reading room photograph? (FICTIONAL)', 'I think I recognise someone on the left. (Sample post.)'],
                  [$fam, 'family-histories', 'The Testfield family of Greenvale (FICTIONAL)', 'I represent the Testfield family and am collecting memories. (Sample post.)']]
                 as [$user, $cat, $title, $body]) {
            $user->post("/community/c/{$cat}/new", ['title' => $title, 'body' => $body]);
        }
        $topics = $db->all('SELECT id, slug FROM forum_topics ORDER BY id');
        $replies = [[$member, 'My grandmother worked there. (Sample reply.)'], [$contrib, 'Could be Samuel Testfield? (Sample reply.)'],
            [$contrib, 'Thank you, I will send what I have. (Sample reply.)']];
        foreach ($topics as $i => $t) {
            if (!isset($replies[$i])) {
                break;
            }
            $replies[$i][0]->post("/community/topics/{$t['slug']}/reply", ['body' => $replies[$i][1]]);
        }
        if ($topics) {
            $member->post("/community/topics/{$topics[0]['slug']}/reply", ['body' => 'BUY CHEAP WATCHES (a sample spam post for the moderator)']);
            $spam = (int) $db->val('SELECT MAX(id) FROM forum_posts');
            $contrib->post('/community/report', ['post_id' => (string) $spam, 'category' => 'spam', 'reason' => 'Advertising (sample report).']);
        }
        $contrib->post('/contact', ['message' => 'I may have a photograph of the Greenvale school. Who should I send it to? (Sample message.)',
            'about' => $P['Greenvale']['public_id']]);
        $nTopics = (int) $db->val('SELECT COUNT(*) FROM forum_topics');
        $report[] = "forum: {$nTopics} topics with replies and 1 open report; 1 message to the editors";
        $db->exec('UPDATE entities SET is_fictional_test=1');
        @rmdir($tmp);
        $counts = [];
        foreach (['place', 'event', 'person', 'family', 'organization', 'source', 'archive_item', 'oral_history', 'collection'] as $k) {
            $counts[] = $db->val('SELECT COUNT(*) FROM entities WHERE kind=?', [$k]) . ' ' . str_replace('_', ' ', $k);
        }
        array_unshift($report, 'Records: ' . implode(', ', $counts));
        return [$password, $report];
    }

    private static function rmtree(string $dir): void
    {
        if (!is_dir($dir)) {
            return;
        }
        $it = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($dir, \FilesystemIterator::SKIP_DOTS), \RecursiveIteratorIterator::CHILD_FIRST);
        foreach ($it as $f) {
            $f->isDir() ? rmdir($f->getPathname()) : unlink($f->getPathname());
        }
        rmdir($dir);
    }
}
