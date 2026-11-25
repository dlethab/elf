<?php
declare(strict_types=1);

namespace Elf\Tools;

use Elf\Db;
use Elf\Services\Entities;
use Elf\Services\Passwords;
use Elf\Services\Records;
use Elf\Services\Util;

/**
 * DEVELOPMENT-ONLY fictional records for trying the interface (php bin/elf seed-test-data).
 *
 * Every record is flagged is_fictional_test=1 and visibly labelled on every page; names end in "(FICTIONAL)"; no
 * coordinates are given (geography is never invented, even for tests); dated events use the year 2099 so nothing can
 * be mistaken for history. Refuses to run in production (see bin/elf). Records still pass through the normal
 * validation and publication code. The same records as the Python edition's devseed.py.
 */
final class DevSeed
{
    public const DEV_USERS = [['dev_admin', ['administrator', 'editor']], ['dev_editor', ['editor']], ['dev_editor2', ['editor']],
        ['dev_moderator', ['moderator']], ['dev_contrib', []], ['dev_rep', []]];
    public const TAG = ' (FICTIONAL)';

    private static function maker(Db $db, array $ids, int $actor): callable
    {
        return function (string $kind, array $raw, ?array $consents = null) use ($db, $ids, $actor): array {
            [$clean, $errors] = Records::validate($db, $kind, $raw, false);
            if ($errors) {
                throw new \RuntimeException("seed {$kind}: " . json_encode($errors));
            }
            if ($consents !== null) {
                $clean['consents'] = ['granted' => $consents, 'note' => 'FICTIONAL test consent; no real interview exists.'];
            }
            $sid = $db->insert("INSERT INTO submissions(kind, proposed_data, status, submitter_id, submitted_at, published_at, reviewer_id) "
                . "VALUES (?,?, 'published', ?, ?, ?, ?)", [$kind, Util::json($clean), $ids['dev_contrib'], Util::nowIso(), Util::nowIso(), $actor]);
            $eid = Records::applyNew($db, $kind, $clean, $actor, $sid, $consents !== null, true);
            $db->exec('UPDATE submissions SET result_entity_id=? WHERE id=?', [$eid, $sid]);
            return Entities::get($db, $eid);
        };
    }

    private static function valid(Db $db, string $kind, array $raw): array
    {
        [$clean, $errors] = Records::validate($db, $kind, $raw);
        if ($errors) {
            throw new \RuntimeException("seed {$kind}: " . json_encode($errors));
        }
        return $clean;
    }

    private static function addUser(Db $db, string $name, array $roles, string $password): int
    {
        $id = $db->insert('INSERT INTO users(email, username, display_name, password_hash, email_verified_at) VALUES (?,?,?,?,?)',
            ["{$name}@example.test", $name, ucwords(str_replace('_', ' ', $name)), Passwords::hash($password), Util::nowIso()]);
        foreach ($roles as $r) {
            $db->exec('INSERT INTO user_roles(user_id, role) VALUES (?,?)', [$id, $r]);
        }
        return $id;
    }

    public static function seed(Db $db): string
    {
        if ($db->one("SELECT 1 FROM users WHERE username='dev_admin'")) {
            return self::seedMore($db);
        }
        $password = 'dev-' . Util::tokenUrlsafe(9);
        $first = (int) $db->val('SELECT COALESCE(MAX(id), 0) FROM entities');
        $db->tx(function () use ($db, $password, $first) {
            $ids = [];
            foreach (self::DEV_USERS as [$name, $roles]) {
                $ids[$name] = self::addUser($db, $name, $roles, $password);
            }
            $actor = $ids['dev_editor'];
            $make = self::maker($db, $ids, $actor);
            $place = $make('place', ['primary_name' => 'Testville' . self::TAG, 'aliases' => "Testvil\nTestvilla", 'place_type' => 'town_city',
                'overview' => 'FICTIONAL test place for development. It has no coordinates on purpose.']);
            $fam = $make('family', ['display_name' => 'Testfamily' . self::TAG, 'region_note' => 'Testville (fictional)',
                'summary' => 'FICTIONAL family record for development testing.',
                'narrative' => "This narrative is placeholder text for interface testing only.\nIt describes no real family."]);
            $a = $make('person', ['preferred_name' => 'Testperson Alpha' . self::TAG, 'aliases' => "Testperson Alfa\nT. Alpha",
                'living_status' => 'deceased', 'birth' => 'c. 2099', 'birth_place' => $place['public_id'],
                'summary' => 'FICTIONAL person used to test profiles, aliases and uncertain dates.',
                'sources' => 'Test Source Book (FICTIONAL) | p. 1 | https://example.test/book']);
            $b = $make('person', ['preferred_name' => 'Testperson Beta' . self::TAG, 'living_status' => 'unknown', 'birth' => '2099',
                'summary' => 'FICTIONAL person used to test relationships.']);
            $make('person', ['preferred_name' => 'Testperson Living' . self::TAG, 'living_status' => 'living',
                'summary' => 'FICTIONAL living person: must stay restricted and never appear publicly.']);
            $ev = $make('event', ['title' => 'Test event: interface drill' . self::TAG, 'event_type' => 'community_event',
                'date' => '2099-03 to 2099-05', 'place' => $place['public_id'],
                'summary' => 'FICTIONAL event used to test the timeline and date ranges.']);
            $make('event', ['title' => 'Test event with unknown date' . self::TAG, 'event_type' => 'other',
                'summary' => 'FICTIONAL event: its date is unknown and must be shown as unknown.']);
            $rel = self::valid($db, 'relationship', ['person_a' => $a['public_id'], 'person_b' => $b['public_id'],
                'relationship_type' => 'parent_of', 'status' => 'uncertain', 'notes' => 'FICTIONAL relationship for testing.']);
            Records::applyRelationship($db, $rel, $actor, null);
            foreach ([$a, $b] as $p) {
                $db->exec("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility, created_by) "
                    . "VALUES (?,?, 'published', 'public', ?)", [$fam['id'], $p['id'], $actor]);
            }
            $db->exec("INSERT INTO event_participants(event_id, person_id, role, evidence_status, publication_status) "
                . "VALUES (?,?, 'Participant (fictional)', 'unverified', 'published')", [$ev['id'], $a['id']]);
            $db->exec('INSERT INTO family_representatives(user_id, family_id, granted_by) VALUES (?,?,?)', [$ids['dev_rep'], $fam['id'], $ids['dev_admin']]);
            // records created along the way (e.g. a source record made from a citation) are test data too
            $db->exec('UPDATE entities SET is_fictional_test=1 WHERE id>?', [$first]);
        });
        $more = self::seedMore($db, $password);
        return 'Added fictional test records and dev accounts: ' . implode(', ', array_column(self::DEV_USERS, 0))
            . "\nPassword for all dev accounts: {$password}\n(Development only. Do not reuse.)\n" . $more;
    }

    /**
     * Organizations, affiliations, an oral history, forum topics and a researcher account. Added to a database seeded
     * before these sections existed, too (each part is skipped if already present).
     */
    public static function seedMore(Db $db, ?string $password = null): string
    {
        if ($db->one('SELECT 1 FROM organizations WHERE name=?', ['Test Front' . self::TAG])) {
            return 'Test data already present. Delete the database file to start over.';
        }
        $newPassword = $password ?? 'dev-' . Util::tokenUrlsafe(9);
        $uid = fn (string $n) => (int) $db->val('SELECT id FROM users WHERE username=?', [$n]);
        $pid = fn (string $name) => $db->val('SELECT e.public_id FROM entities e JOIN entity_names n ON n.entity_id=e.id '
            . "WHERE n.name=? AND n.name_type='preferred'", [$name]);
        $first = (int) $db->val('SELECT COALESCE(MAX(id), 0) FROM entities');
        $created = [];
        $db->tx(function () use ($db, $uid, $pid, $first, $newPassword, &$created) {
            $ids = [];
            foreach (self::DEV_USERS as [$n]) {
                $ids[$n] = $uid($n);
            }
            if (!$db->one("SELECT 1 FROM users WHERE username='dev_researcher'")) {
                $ids['dev_researcher'] = self::addUser($db, 'dev_researcher', ['researcher'], $newPassword);
                $created[] = 'dev_researcher';
            }
            $actor = $ids['dev_editor'];
            $make = self::maker($db, $ids, $actor);
            [$alpha, $beta] = [$pid('Testperson Alpha' . self::TAG), $pid('Testperson Beta' . self::TAG)];
            [$place, $event] = [$pid('Testville' . self::TAG), $pid('Test event: interface drill' . self::TAG)];
            $org = $make('organization', ['name' => 'Test Front' . self::TAG, 'aliases' => 'TF-F', 'active' => '2098 to 2099',
                'description' => 'FICTIONAL organization used to test affiliations, organization pages and connection diagrams. It never existed.']);
            $make('organization', ['name' => 'Test Support Committee' . self::TAG, 'active' => 'c. 2099',
                'description' => 'FICTIONAL second organization, with no documented members, to test empty states.']);
            foreach ([[$alpha, 'Test role: organizer (fictional)', '2098 to 2099'], [$beta, null, null]] as [$person, $role, $period]) {
                $clean = self::valid($db, 'affiliation', ['person' => $person, 'organization' => $org['public_id'], 'role' => $role ?? '',
                    'period' => $period ?? '', 'place' => $role ? $place : '', 'notes' => 'FICTIONAL affiliation for testing.']);
                Records::applyAffiliation($db, $clean, $actor, null);
            }
            $clean = self::valid($db, 'participation', ['event' => $event, 'organization' => $org['public_id'], 'role' => 'Organizer (fictional)']);
            Records::applyParticipation($db, $clean, $actor, null);
            $make('oral_history', ['title' => 'Test interview about Testville' . self::TAG, 'interviewee' => $alpha,
                'interviewer_text' => 'Test Interviewer (FICTIONAL)', 'recorded' => '2099-06',
                'recording_location_note' => 'Testville (fictional)', 'language' => 'English',
                'summary' => 'FICTIONAL interview with a transcript and no recording, used to test consent display.',
                'topics' => "Testing\nInterface", 'related' => $place,
                'transcript_text' => "[00:00] Interviewer: This is a FICTIONAL test transcript.\n"
                    . "[00:05] Testperson Alpha: Nothing in it describes real events.\n[00:12] Interviewer: Thank you.",
                'transcript_kind' => 'verbatim'],
                ['record', 'store', 'publish_transcript', 'research_access']);
            $cat = fn (string $slug) => (int) $db->val('SELECT id FROM forum_categories WHERE slug=?', [$slug]);
            foreach ([['hometowns', 'Test topic: memories of Testville (FICTIONAL)',
                       'This is a FICTIONAL forum post for development testing.', 'A FICTIONAL reply, to test threads and notifications.'],
                      ['photo-identification', 'Test topic: who is in this photo? (FICTIONAL)',
                       'A FICTIONAL request for help identifying people in a photograph.', null]] as [$slug, $title, $body, $reply]) {
                $now = Util::nowIso();
                $tslug = substr(str_replace([' ', ':', '?', '(', ')'], ['-', '', '', '', ''], strtolower($title)), 0, 80);
                $t = $db->insert('INSERT INTO forum_topics(category_id, slug, title, author_id, created_at, last_post_at) VALUES (?,?,?,?,?,?)',
                    [$cat($slug), $tslug, $title, $ids['dev_contrib'], $now, $now]);
                $db->exec('INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)', [$t, $ids['dev_contrib'], $body, $now]);
                if ($reply) {
                    $db->exec('INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)', [$t, $ids['dev_rep'], $reply, $now]);
                }
            }
            $db->exec('UPDATE entities SET is_fictional_test=1 WHERE id>?', [$first]);
        });
        $msg = 'Added fictional organizations, affiliations, an oral history and forum topics.';
        if ($created && !$password) {
            $msg .= "\nNew dev account: dev_researcher, password: {$newPassword}\n(Development only. Do not reuse.)";
        } elseif ($created) {
            $msg .= ' Also added dev_researcher (same password).';
        }
        return $msg;
    }
}
