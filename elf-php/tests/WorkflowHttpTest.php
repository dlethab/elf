<?php
declare(strict_types=1);

namespace Elf\Tests;

use Elf\Queries;
use Elf\Services\Entities;
use Elf\Services\Families;
use Elf\Services\Merging;

/** The contribution → review → publication cycle and who may see what, through the site's own pages. */
final class WorkflowHttpTest extends TestCase
{
    public function testFullCycleDraftRevisionPublishSearchAndRelatedPages(): void
    {
        $this->makeUser('contrib');
        $this->makeUser('editor', ['editor']);
        $c = $this->client('contrib');
        $ed = $this->client('editor');

        $r = $c->post('/contribute/person', ['preferred_name' => 'Testperson Cycle (FICTIONAL)', 'living_status' => 'deceased',
            'birth' => 'not a date', 'action' => 'draft']);
        $this->assertStatus(400, $r);                                             // invalid date: the form says why
        $this->assertStringContainsString('aria-invalid="true"', $r->data());
        $r = $c->post('/contribute/person', ['preferred_name' => 'Testperson Cycle (FICTIONAL)', 'aliases' => 'Testperson Cykle',
            'living_status' => 'deceased', 'birth' => 'c. 2099', 'sources' => 'Test Book (FICTIONAL) | p. 4', 'action' => 'submit']);
        $sid = (int) $this->db->val('SELECT MAX(id) FROM submissions');
        $this->assertSame("/dashboard/submissions/{$sid}", $r->get('Location'));
        $this->assertSame('submitted', $this->db->val('SELECT status FROM submissions WHERE id=?', [$sid]));
        $this->assertStringNotContainsString('Testperson Cycle', $this->get('/search?q=Testperson')->data());   // not public yet

        $this->assertStringContainsString('Testperson Cycle', $ed->get('/editor')->data());
        $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'under_review']);
        $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'needs_revision', 'message' => 'Please add the place of birth.']);
        $this->assertStringContainsString('Please add the place of birth.', $c->get("/dashboard/submissions/{$sid}")->data());
        $c->post("/dashboard/submissions/{$sid}/edit", ['preferred_name' => 'Testperson Cycle (FICTIONAL)', 'aliases' => 'Testperson Cykle',
            'living_status' => 'deceased', 'birth' => 'c. 2099', 'sources' => 'Test Book (FICTIONAL) | p. 4', 'action' => 'submit']);
        $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'under_review']);
        $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'approved']);
        $this->assertStringNotContainsString('Testperson Cycle', $this->get('/people')->data(), 'approved is not public');
        $ed->post("/editor/submissions/{$sid}/transition", ['to' => 'published']);

        $e = Entities::get($this->db, (int) $this->db->val('SELECT result_entity_id FROM submissions WHERE id=?', [$sid]));
        $page = $this->get(Queries::recordUrl('person', $e['slug']));
        $this->assertStatus(200, $page);
        $this->assertStringContainsString('c. 2099', $page->data());             // uncertainty shown, not hidden
        $this->assertStringContainsString('Test Book (FICTIONAL)', $page->data());
        $this->assertStringContainsString('Testperson Cycle', $this->get('/search?q=Cykle')->data());   // found by its alias
        // the contributor was told at each step, and the notice links to their submission
        $notes = $this->db->col("SELECT n.link FROM notifications n JOIN users u ON u.id=n.user_id WHERE u.username='contrib'");
        $this->assertGreaterThanOrEqual(3, count($notes));
        $this->assertContains("/dashboard/submissions/{$sid}", $notes);
        $this->assertStringContainsString('published', $c->get('/dashboard/notifications')->data());
    }

    public function testRestrictedRecordDeniedEverywherePublic(): void
    {
        $c = $this->makeUser('c2');
        $ed = $this->makeUser('e2', ['editor']);
        $living = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Living (FICTIONAL)', 'living_status' => 'living']);
        $this->assertSame('restricted', $living['visibility']);
        $draft = Entities::get($this->db, (int) $this->db->val("SELECT id FROM entities WHERE kind='person' AND id<>?", [$living['id']]) ?: 0);
        $this->assertNull($draft);
        foreach (['/people/' . $living['slug'], '/people/' . $living['slug'] . '/tree', '/people/' . $living['slug'] . '/connections',
                  '/id/' . $living['public_id'], '/map/record/' . $living['public_id'] . '.json'] as $url) {
            $this->assertStatus(404, $this->get($url), $url);
        }
        $this->assertStringNotContainsString('Testperson Living', $this->get('/people')->data());
        $this->assertStringNotContainsString('Testperson Living', $this->get('/search?q=Living')->data());
        $this->assertStringNotContainsString('Testperson Living', $this->get('/lookup/person?q=Testperson')->data());
        $this->assertStringNotContainsString('Testperson Living', $this->get('/sitemap.xml')->data());
        // a link that names it is dropped, and the visitor is told
        $this->assertStringContainsString('left out', $this->get('/explore?person=' . $living['public_id'])->data());
    }

    public function testSlugChangeAndMergeRedirectAndPermanentIdResolves(): void
    {
        $c = $this->makeUser('c3');
        $ed = $this->makeUser('e3', ['editor']);
        $keep = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Twin (FICTIONAL)', 'living_status' => 'deceased']);
        $retire = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Twin (FICTIONAL)', 'living_status' => 'deceased']);
        $this->assertSame('/people/' . $keep['slug'], $this->get('/id/' . $keep['public_id'])->get('Location'));
        $edc = $this->client('e3');
        $r = $edc->post("/editor/merge?keep={$keep['public_id']}&retire={$retire['public_id']}", ['reason' => 'Same person (test).', 'fill_gaps' => '1']);
        $this->assertSame('/editor/records/' . $keep['public_id'], $r->get('Location'));
        $r = $this->get('/people/' . $retire['slug']);
        $this->assertSame(301, $r->status);
        $this->assertSame('/people/' . $keep['slug'], $r->get('Location'));
        $this->assertSame('/people/' . $keep['slug'], $this->get('/id/' . $retire['public_id'])->get('Location'));
        $edc->post("/editor/records/{$keep['public_id']}/slug", ['slug' => 'testperson-renamed']);
        $this->assertSame('/people/testperson-renamed', $this->get('/people/' . $keep['slug'])->get('Location'));
        $this->assertNotEmpty(Merging::mergeHistory($this->db, (int) $keep['id']));
    }

    public function testCorrectionShowsDiffAndKeepsOldName(): void
    {
        $c = $this->makeUser('c4');
        $ed = $this->makeUser('e4', ['editor']);
        $p = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Old (FICTIONAL)', 'living_status' => 'deceased']);
        $cc = $this->client('c4');
        $form = \Elf\Services\Records::formValues(\Elf\Services\Records::currentClean($this->db, 'person', (int) $p['id']), 'person', $this->db);
        $r = $cc->post("/contribute/correction/{$p['public_id']}", ['action' => 'submit'] + $form);
        $this->assertStatus(400, $r);
        $this->assertStringContainsString('You have not changed anything yet', $r->data());
        $cc->post("/contribute/correction/{$p['public_id']}", ['preferred_name' => 'Testperson New (FICTIONAL)', 'action' => 'submit'] + $form);
        $sid = (int) $this->db->val("SELECT MAX(id) FROM submissions WHERE kind='correction'");
        $review = $this->client('e4')->get("/editor/submissions/{$sid}");
        $this->assertStringContainsString('Testperson Old (FICTIONAL)', $review->data());
        $this->assertStringContainsString('Testperson New (FICTIONAL)', $review->data());
        $this->publish($ed, $sid);
        $page = $this->get('/people/' . Entities::get($this->db, (int) $p['id'])['slug']);
        $this->assertStringContainsString('Testperson New (FICTIONAL)', $page->data());
        $this->assertStringContainsString('Testperson Old (FICTIONAL)', $page->data(), 'the earlier name stays as an other name');
    }

    public function testEditorCannotReviewOwnSubmission(): void
    {
        $ed = $this->makeUser('solo', ['editor']);
        $sid = $this->submitNew($ed, 'place', ['primary_name' => 'Testville Own (FICTIONAL)']);
        $c = $this->client('solo');
        $c->post("/editor/submissions/{$sid}/transition", ['to' => 'under_review']);
        $this->assertSame('submitted', $this->db->val('SELECT status FROM submissions WHERE id=?', [$sid]));
        $this->assertStringContainsString('notice--error', $c->get("/editor/submissions/{$sid}")->data());
    }

    public function testContributorSubmissionsArePrivateToThem(): void
    {
        $a = $this->makeUser('alice');
        $this->makeUser('bob');
        $sid = $this->submitNew($a, 'place', ['primary_name' => 'Testville Private (FICTIONAL)']);
        $this->assertStatus(404, $this->client('bob')->get("/dashboard/submissions/{$sid}"));
        $this->assertStatus(403, $this->client('bob')->get("/editor/submissions/{$sid}"));
        $this->assertStatus(200, $this->client('alice')->get("/dashboard/submissions/{$sid}"));
    }

    public function testRolesAndPermissions(): void
    {
        $this->makeUser('mod', ['moderator']);
        $plain = $this->makeUser('plain');
        $admin = $this->makeUser('root', ['administrator']);
        foreach (['/editor', '/editor/records', '/admin', '/admin/users'] as $url) {
            $this->assertStatus(403, $this->client('mod')->get($url), "moderator {$url}");
            $this->assertStatus(403, $this->client('plain')->get($url), "contributor {$url}");
        }
        $this->assertStatus(200, $this->client('mod')->get('/moderation'));
        $this->assertSame('/auth/login?next=%2Fadmin', $this->get('/admin')->get('Location'));
        // nobody raises their own role; an administrator's grant is audited
        $this->assertStatus(403, $this->client('plain')->post("/admin/users/{$plain->id}/roles", ['role' => 'administrator', 'action' => 'grant']));
        $this->client('root')->post("/admin/users/{$plain->id}/roles", ['role' => 'editor', 'action' => 'grant']);
        $this->assertSame(['editor'], \Elf\Services\Accounts::getRoles($this->db, $plain->id));
        $this->assertSame(1, (int) $this->db->val("SELECT COUNT(*) FROM audit_logs WHERE action='role.granted' AND actor_id=?", [$admin->id]));
    }

    public function testFamilyRepProposesButCannotPublish(): void
    {
        $c = $this->makeUser('c5');
        $ed = $this->makeUser('e5', ['editor']);
        $rep = $this->makeUser('rep');
        $fam = $this->publishNew($c, $ed, 'family', ['display_name' => 'Testfamily (FICTIONAL)']);
        $a = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Parent (FICTIONAL)', 'living_status' => 'deceased']);
        $b = $this->publishNew($c, $ed, 'person', ['preferred_name' => 'Testperson Child (FICTIONAL)', 'living_status' => 'deceased']);
        $this->assertStatus(403, $this->client('rep')->get('/contribute/relationship?family=' . $fam['public_id']));
        Families::grant($this->db, $ed->id, 'rep', (int) $fam['id']);
        $r = $this->client('rep')->post('/contribute/relationship', ['family' => $fam['public_id'], 'person_a' => $a['public_id'],
            'person_b' => $b['public_id'], 'relationship_type' => 'parent_of', 'status' => 'current', 'action' => 'submit']);
        $this->assertStatus(302, $r);
        $sid = (int) $this->db->val("SELECT MAX(id) FROM submissions WHERE kind='relationship'");
        $this->assertSame('submitted', $this->db->val('SELECT status FROM submissions WHERE id=?', [$sid]));
        $this->assertStatus(403, $this->client('rep')->post("/editor/submissions/{$sid}/transition", ['to' => 'published']));
    }

    public function testLookupAndMapOnlyShowPublishedRecords(): void
    {
        $c = $this->makeUser('c6');
        $ed = $this->makeUser('e6', ['editor']);
        $this->publishNew($c, $ed, 'place', ['primary_name' => 'Testhaven (FICTIONAL)', 'latitude' => '15.62', 'longitude' => '39.42',
            'coord_precision' => 'approximate', 'coord_note' => 'Test-only location (FICTIONAL).']);
        $this->submitNew($c, 'place', ['primary_name' => 'Testhaven Pending (FICTIONAL)', 'latitude' => '15.7', 'longitude' => '39.5',
            'coord_precision' => 'exact']);
        $map = $this->get('/map/data.json')->getJson();
        $this->assertSame(['Testhaven (FICTIONAL)'], array_column($map['places'], 'name'));
        $this->assertSame(15.62, $map['places'][0]['lat']);
        $this->assertCount(1, $this->get('/map/places.json')->getJson()['places']);
        $review = $this->client('e6')->get('/map/review.json')->getJson();
        $this->assertSame(['Testhaven Pending (FICTIONAL)'], array_column($review['proposals'], 'title'));
        $this->assertSame('private, no-store', $this->client('e6')->get('/map/review.json')->get('Cache-Control'));
    }
}
