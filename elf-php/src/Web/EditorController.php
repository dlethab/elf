<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Http\Response;
use Elf\Security;
use Elf\Services\Audit;
use Elf\Services\CollectionError;
use Elf\Services\Collections;
use Elf\Services\ConsentError;
use Elf\Services\Curation;
use Elf\Services\CurationError;
use Elf\Services\Duplicates;
use Elf\Services\Entities;
use Elf\Services\ExplorationError;
use Elf\Services\Explorations;
use Elf\Services\Families;
use Elf\Services\Field;
use Elf\Services\ImportError;
use Elf\Services\Importer;
use Elf\Services\MergeError;
use Elf\Services\Merging;
use Elf\Services\Oral;
use Elf\Services\PermissionDenied;
use Elf\Services\Photos;
use Elf\Services\Records;
use Elf\Services\Search;
use Elf\Services\Workflow;
use Elf\Services\WorkflowError;
use Elf\Vocab;

/**
 * Editorial queue, review, publication and staff record management. Every route is gated by requirePerm(<permission>);
 * the workflow service re-checks permissions on every transition.
 */
final class EditorController extends Controller
{
    public const STAFF_KINDS = ['person', 'family', 'place', 'event', 'organization', 'source', 'archive_item', 'collection', 'oral_history'];
    public const TABS = [['new', 'New', ['submitted']], ['review', 'Under review', ['under_review']],
        ['approved', 'Approved, awaiting publication', ['approved']],
        ['with_contributor', 'Returned to contributor', ['needs_revision']],
        ['decided', 'Recently decided', ['published', 'rejected']]];

    public static function routes(App $app): void
    {
        $c = new self($app);
        $c->route('GET', '/editor', 'queue', 'editor.queue');
        $c->route('GET', '/editor/submissions/<int:sid>', 'review', 'editor.review');
        $c->route('POST', '/editor/submissions/<int:sid>/photos/<int:pid>', 'photoDecision', 'editor.photo_decision');
        $c->route('POST', '/editor/submissions/<int:sid>/transition', 'transition', 'editor.transition');
        $c->route('POST', '/editor/submissions/<int:sid>/note', 'note', 'editor.note');
        $c->route('GET', '/editor/records', 'recordsList', 'editor.records_list');
        $c->route('GET', '/editor/records/<public_id>', 'record', 'editor.record');
        $c->route('GET|POST', '/editor/records/<public_id>/edit', 'recordEdit', 'editor.record_edit');
        $c->route('POST', '/editor/records/<public_id>/citations', 'citationAdd', 'editor.citation_add');
        $c->route('POST', '/editor/records/<public_id>/citations/<int:cid>', 'citationUpdate', 'editor.citation_update');
        $c->route('POST', '/editor/records/<public_id>/accounts', 'accountAdd', 'editor.account_add');
        $c->route('POST', '/editor/records/<public_id>/accounts/<int:aid>', 'accountUpdate', 'editor.account_update');
        $c->route('POST', '/editor/records/<public_id>/links/<any(relationships,family_memberships,affiliations,event_participants):table>/<int:lid>',
            'linkUpdate', 'editor.link_update');
        $c->route('GET', '/editor/duplicates', 'duplicatesReport', 'editor.duplicates_report');
        $c->route('GET|POST', '/editor/merge', 'merge', 'editor.merge');
        $c->route('GET|POST', '/editor/import', 'importStart', 'editor.import_start');
        $c->route('GET', '/editor/import/template/<kind>.csv', 'importTemplate', 'editor.import_template');
        $c->route('GET|POST', '/editor/import/<int:iid>', 'importPreview', 'editor.import_preview');
        $c->route('POST', '/editor/bulk', 'bulk', 'editor.bulk');
        $c->route('GET', '/editor/quality', 'quality', 'editor.quality');
        $c->route('POST', '/editor/records/<public_id>/state', 'recordState', 'editor.record_state');
        $c->route('POST', '/editor/records/<public_id>/rights', 'recordRights', 'editor.record_rights');
        $c->route('POST', '/editor/records/<public_id>/slug', 'recordSlug', 'editor.record_slug');
        $c->route('POST', '/editor/families/<public_id>/representatives', 'grantRep', 'editor.grant_rep');
        $c->route('POST', '/editor/families/<public_id>/representatives/<int:gid>/revoke', 'revokeRep', 'editor.revoke_rep');
        $c->route('GET', '/editor/messages', 'messages', 'editor.messages');
        $c->route('POST', '/editor/messages/<int:mid>/handled', 'messageHandled', 'editor.message_handled');
        $c->route('POST', '/editor/records/<public_id>/consent/<consent_type>', 'consentSet', 'editor.consent_set');
        $c->route('POST', '/editor/records/<public_id>/oral-controls', 'oralControls', 'editor.oral_controls');
        $c->route('GET|POST', '/editor/explorations', 'explorationIndex', 'editor.exploration_index');
        $c->route('GET|POST', '/editor/explorations/<int:xid>', 'explorationEdit', 'editor.exploration_edit');
        $c->route('GET|POST', '/editor/collections', 'collectionIndex', 'editor.collection_index');
        $c->route('POST', '/editor/records/<public_id>/collection', 'collectionUpdate', 'editor.collection_update');
        $c->route('POST', '/editor/records/<public_id>/collection/items', 'collectionItems', 'editor.collection_items');
    }

    /** Review aids shown in the queue. They inform; they never decide. */
    private function flags(array $s): array
    {
        $db = $this->db();
        $out = [];
        $d = Workflow::data($s);
        $data = (isset($d['changes']) && is_array($d['changes'])) ? $d['changes'] : $d;
        if ($s['kind'] === 'person' && ($data['living_status'] ?? null) === 'living') {
            $out[] = 'Living person: consent needed';
        }
        if ($s['kind'] === 'correction' && ($data['living_status'] ?? null) === 'living') {
            $out[] = 'Marks person as living';
        }
        if (in_array($s['kind'], ['person', 'family', 'place', 'event'], true) && empty($data['sources'])) {
            $out[] = 'No sources';
        }
        if ($s['kind'] === 'person') {
            $names = array_merge([$data['preferred_name'] ?? null, $data['full_name'] ?? null], (array) ($data['aliases'] ?? []));
            if (Duplicates::findPersonCandidates($db, $names, null, 1)) {
                $out[] = 'Possible duplicate';
            }
        }
        if ($s['kind'] === 'correction' && $s['base_revision'] !== null
            && Entities::latestRevisionNumber($db, (int) $s['target_entity_id']) > (int) $s['base_revision']) {
            $out[] = 'Record changed since submission';
        }
        if ($s['rights_note']) {
            $out[] = 'Rights/consent note';
        }
        $n = Photos::count($db, (int) $s['id']);
        if ($n) {
            $out[] = "{$n} photo" . ($n !== 1 ? 's' : '');
            if (Photos::pendingCount($db, (int) $s['id']) && in_array($s['status'], Photos::REVIEW_STATES, true)) {
                $out[] = 'Photo decisions needed';
            }
        }
        return $out;
    }

    public function queue(): Response
    {
        $this->requirePerm('queue.view');
        $db = $this->db();
        $tab = $this->arg('tab', 'new');
        $statuses = null;
        foreach (self::TABS as [$k, , $st]) {
            if ($k === $tab) {
                $statuses = $st;
            }
        }
        if (!$statuses) {
            $this->abort(404);
        }
        $kind = $this->arg('kind') ?: null;
        if ($kind && !isset(Vocab::KIND_LABELS[$kind])) {
            $kind = null;
        }
        $b = trim((string) $this->arg('batch', ''));
        $batch = preg_match('/^[+-]?\d+$/', $b) ? ((int) $b ?: null) : null;
        $rows = Workflow::queue($db, $statuses, $kind, 200, $batch);
        if ($tab === 'decided') {
            usort($rows, fn ($a, $b) => strcmp((string) $b['updated_at'], (string) $a['updated_at']));
            $rows = array_slice($rows, 0, 50);
        }
        $counts = [];
        foreach (self::TABS as [$k, , $st]) {
            if ($k !== 'decided') {
                $counts[$k] = (int) $db->val('SELECT COUNT(*) FROM submissions WHERE status IN (' . implode(',', array_fill(0, count($st), '?')) . ')', $st);
            }
        }
        $items = array_map(fn ($s) => ['s' => $s, 'title' => Workflow::titleFor($db, $s), 'flags' => $this->flags($s)], $rows);
        return $this->render('editor/queue.html', ['items' => $items, 'tab' => $tab, 'tabs' => self::TABS, 'counts' => $counts,
            'kind' => $kind, 'batch' => $batch,
            'batches' => $db->all("SELECT id, kind, filename FROM imports WHERE status='created' ORDER BY id DESC LIMIT 50"),
            'bulk_ok' => in_array($tab, ['new', 'review', 'approved'], true) && $this->me()->can('submission.publish'),
            'kinds' => ['person', 'family', 'place', 'event', 'organization', 'source', 'relationship', 'affiliation', 'membership',
                'participation', 'correction'],
            'new_msgs' => (int) $db->val("SELECT COUNT(*) FROM contact_messages WHERE status='new'")]);
    }

    private function staffSubmission(int $sid): array
    {
        $s = Workflow::getForUser($this->db(), $this->me(), $sid);
        if (!$s) {
            $this->abort(404);
        }
        return $s;
    }

    public function review(int $sid): Response
    {
        $this->requirePerm('submission.review');
        $db = $this->db();
        $s = $this->staffSubmission($sid);
        $d = Workflow::data($s);
        $me = $this->me();
        $ctx = ['s' => $s, 'title' => Workflow::titleFor($db, $s), 'flags' => $this->flags($s),
            'events' => Workflow::visibleEvents($db, $me, $sid, true),
            'submitter' => $db->one('SELECT username, display_name FROM users WHERE id=?', [$s['submitter_id']]),
            'is_own' => (int) $s['submitter_id'] === $me->id && !$this->app->config['ALLOW_SELF_REVIEW']];
        $data = $d;
        if ($s['kind'] === 'correction') {
            $target = Entities::get($db, $s['target_entity_id']);
            $ctx['target'] = $target;
            $ctx['target_title'] = Entities::titleOf($db, (int) $target['id']);
            $changes = (array) ($d['changes'] ?? []);
            $ctx['diff'] = Records::diff($db, $target['kind'], (int) $target['id'], $changes);
            $data = $changes;
        } else {
            $ctx['rows'] = Records::displayRows($db, $s['kind'], $d);
        }
        if ($s['kind'] === 'person' || ($s['kind'] === 'correction' && $ctx['target']['kind'] === 'person')) {
            $names = array_merge([$data['preferred_name'] ?? null, $data['full_name'] ?? null], (array) ($data['aliases'] ?? []));
            $by = $data['birth']['start'] ?? null;
            $ctx['candidates'] = Duplicates::findPersonCandidates($db, $names, $by ? substr($by, 0, 4) : null, 5,
                $s['target_entity_id'] !== null ? (int) $s['target_entity_id'] : null);
        }
        $ctx['needs_consent'] = $s['kind'] === 'person' && ($data['living_status'] ?? null) === 'living';
        $ctx['oral_consent'] = $s['kind'] === 'oral_history';
        $ctx['family'] = $s['family_scope_id'] ? Entities::get($db, $s['family_scope_id']) : null;
        $ctx['sources'] = ($data['sources'] ?? null) ?: [];
        $ctx['photos'] = Photos::listForSubmission($db, $sid);
        $ctx['photo_decidable'] = in_array($s['status'], Photos::REVIEW_STATES, true) && !$ctx['is_own'];
        $ctx['rights_statuses'] = Vocab::RIGHTS_STATUSES;
        $ctx['public_rights'] = Vocab::PUBLIC_RIGHTS;
        return $this->render('editor/review.html', $ctx);
    }

    public function photoDecision(int $sid, int $pid): Response
    {
        $this->requirePerm('submission.review');
        $this->staffSubmission($sid);
        try {
            Photos::decide($this->db(), $this->me(), $sid, $pid, $this->req()->form, $this->app->config);
            $this->flash('Photo decision saved. It takes effect when the submission is published.', 'ok');
        } catch (PermissionDenied|WorkflowError $e) {
            $this->flash($e->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.review', ['sid' => $sid]) . "#photo-{$pid}");
    }

    public function transition(int $sid): Response
    {
        $this->requirePerm('submission.review');
        $this->staffSubmission($sid);
        $to = (string) $this->req()->post('to', '');
        try {
            Workflow::transition($this->db(), $this->me(), $sid, $to, $this->app->config, $this->req()->post('message'),
                $this->req()->post('internal_note'), $this->req()->post('consent_confirmed') === '1');
            $msgs = ['under_review' => 'Review started.', 'needs_revision' => 'Returned to the contributor with your message.',
                'approved' => 'Approved. It is not public until you publish it.', 'rejected' => 'Rejected. The contributor has been told why.',
                'published' => 'Published. The record is now part of the archive.'];
            $this->flash($msgs[$to] ?? 'Updated.', 'ok');
        } catch (PermissionDenied|WorkflowError $e) {
            $this->flash($e->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.review', ['sid' => $sid]));
    }

    public function note(int $sid): Response
    {
        $this->requirePerm('confidential.view');
        $this->staffSubmission($sid);
        try {
            Workflow::addInternalNote($this->db(), $this->me(), $sid, $this->req()->post('internal_note'));
            $this->flash('Internal note added. The contributor cannot see it.', 'ok');
        } catch (PermissionDenied|WorkflowError $e) {
            $this->flash($e->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.review', ['sid' => $sid]));
    }

    // ───────────── staff record management ─────────────
    public function recordsList(): Response
    {
        $this->requirePerm('record.view_any');
        $kind = $this->arg('kind', 'person');
        if (!in_array($kind, self::STAFF_KINDS, true)) {
            $this->abort(404);
        }
        $vis = $this->arg('visibility') ?: null;
        $q = mb_substr(trim((string) $this->arg('q', '')), 0, 100);
        $col = Entities::TITLE_COL[$kind];
        $sql = "SELECT e.*, t.{$col} AS title FROM entities e JOIN " . Entities::KIND_TABLE[$kind] . ' t ON t.entity_id=e.id '
            . 'WHERE e.kind=? AND e.deleted_at IS NULL';
        $args = [$kind];
        if (in_array($vis, Vocab::VISIBILITIES, true)) {
            $sql .= ' AND e.visibility=?';
            $args[] = $vis;
        }
        if ($q !== '') {
            $sql .= " AND (t.{$col} LIKE ? OR e.public_id=?)";
            array_push($args, "%{$q}%", $q);
        }
        $rows = $this->db()->all($sql . " ORDER BY lower(t.{$col}) LIMIT 500", $args);
        return $this->render('editor/records.html', ['rows' => $rows, 'kind' => $kind, 'vis' => $vis, 'q' => $q]);
    }

    private function staffEntity(string $publicId): array
    {
        $e = Entities::getByPublicId($this->db(), $publicId);
        if (!$e || !in_array($e['kind'], self::STAFF_KINDS, true)) {
            $this->abort(404);
        }
        return $e;
    }

    public function record(string $publicId): Response
    {
        $this->requirePerm('record.view_any');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        $id = (int) $e['id'];
        $sub = Entities::subtypeRow($db, $id);
        $revs = $db->all('SELECT r.revision_number, r.change_summary, r.reason, r.created_at, r.submission_id, u.username '
            . 'FROM revisions r LEFT JOIN users u ON u.id=r.actor_id WHERE r.entity_id=? ORDER BY r.revision_number DESC', [$id]);
        $cites = $db->all('SELECT c.*, s.title FROM citations c JOIN sources s ON s.entity_id=c.source_id WHERE c.target_id=? ORDER BY c.id', [$id]);
        $names = $db->all('SELECT * FROM entity_names WHERE entity_id=? ORDER BY id', [$id]);
        $reps = $e['kind'] === 'family' ? Families::listForFamily($db, $id) : [];
        $fields = [];
        foreach ($sub as $k => $v) {
            if (!in_array($k, ['entity_id', 'kind'], true) && $v !== null && $v !== '') {
                $fields[$k] = $v;
            }
        }
        $itemFiles = $linked = null;
        if ($e['kind'] === 'archive_item') {
            $itemFiles = [];
            foreach ($db->all('SELECT * FROM media_files WHERE owner_id=?', [$id]) as $r) {
                $itemFiles[$r['file_role']] = $r;
            }
            $linked = array_map(fn ($r) => [$r['public_id'], $r['kind'], Entities::titleOf($db, (int) $r['subject_id'])],
                $db->all('SELECT s.subject_id, x.public_id, x.kind FROM archive_item_subjects s JOIN entities x ON x.id=s.subject_id '
                    . 'WHERE s.item_id=?', [$id]));
        }
        $itemPhotos = $db->all('SELECT x.public_id, a.title, a.access_level, (SELECT storage_key FROM media_files m WHERE m.owner_id=x.id '
            . "AND m.file_role='thumbnail') AS thumb_key FROM archive_item_subjects s JOIN entities x ON x.id=s.item_id "
            . 'JOIN archive_items a ON a.entity_id=x.id WHERE s.subject_id=? ORDER BY x.id', [$id]);
        $accts = $db->all('SELECT a.*, s.title AS source_title, x.public_id AS source_pid FROM conflicting_accounts a '
            . 'LEFT JOIN sources s ON s.entity_id=a.source_id LEFT JOIN entities x ON x.id=a.source_id '
            . 'WHERE a.entity_id=? ORDER BY a.id', [$id]);
        $mergedInto = $e['merged_into'] ? Entities::get($db, $e['merged_into']) : null;
        $extra = [];
        if ($e['kind'] === 'oral_history') {
            $extra = ['consents' => Oral::consents($db, $id), 'oh' => $sub, 'ok' => Oral::allowed($db, $id)];
        }
        if ($e['kind'] === 'collection') {
            $extra = ['coll_items' => Collections::items($db, $id, false), 'coll' => $sub];
        }
        $mergeable = in_array($e['kind'], Merging::MERGEABLE, true);
        return $this->render('editor/record.html', [
            'e' => $e, 'title' => Entities::titleOf($db, $id), 'fields' => $fields, 'revs' => $revs,
            'cites' => $cites, 'names' => $names, 'reps' => $reps, 'visibilities' => Vocab::VISIBILITIES,
            'living' => $e['kind'] === 'person' && $sub['living_status'] === 'living',
            'item_files' => $itemFiles, 'linked' => $linked, 'item_photos' => $itemPhotos,
            'rights_statuses' => Vocab::RIGHTS_STATUSES, 'public_rights' => Vocab::PUBLIC_RIGHTS, 'accts' => $accts,
            'links' => Curation::linksFor($db, $e), 'citation_fields' => Curation::citationFields($e['kind']),
            'editable' => in_array($e['kind'], Records::CORRECTABLE_KINDS, true) && !$e['merged_into'],
            'mergeable' => $mergeable && !$e['merged_into'],
            'merges' => Merging::mergeHistory($db, $id), 'merged_into' => $mergedInto,
            'source_choices' => Records::choicesFor($db, new Field('source', 'Source', 'ref', ref: 'source')),
            'same_kind_choices' => $mergeable ? Records::choicesFor($db, new Field('other', 'Other', 'ref', ref: $e['kind'])) : [],
            'EVIDENCE_KEYS' => array_keys(Vocab::EVIDENCE), 'REL_STATUSES' => Vocab::RELATIONSHIP_STATUSES,
        ] + $extra);
    }

    private function back(string $publicId): Response
    {
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]) . ($this->req()->post('anchor') ?: ''));
    }

    /** Run one curation action in a transaction and report the outcome on the staff record page. */
    private function curate(string $publicId, callable $fn, array $args, string $ok = 'Saved.', string $perm = 'citation.manage'): Response
    {
        if (!$this->me()->can($perm)) {
            $this->abort(403);
        }
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        try {
            $db->tx(function () use ($db, $e, $fn, $args) {
                $fn($db, $this->me(), $e, ...[...$args, $this->req()->form]);
                Search::reindex($db, (int) $e['id']);
            });
            $this->flash($ok, 'ok');
        } catch (CurationError $exc) {
            $this->flash($exc->getMessage(), 'error');
        }
        return $this->back($publicId);
    }

    /** Direct editing by an editor: applied immediately, with a reason that is kept in the history. */
    public function recordEdit(string $publicId): Response
    {
        $this->requirePerm('record.edit');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        if (!in_array($e['kind'], Records::CORRECTABLE_KINDS, true) || $e['merged_into']) {
            $this->abort(404);
        }
        $kind = $e['kind'];
        $errors = [];
        $values = Records::formValues(Records::currentClean($db, $kind, (int) $e['id']), $kind, $db);
        if ($this->isPost()) {
            try {
                [$changes, $errors] = $db->tx(fn () => Curation::directEdit($db, $this->me(), $e, $this->req()->form));
                if ($changes) {
                    $this->flash('Record updated. The change and your reason are in its history.', 'ok');
                    return $this->redirect($this->url('editor.record', ['public_id' => $publicId]));
                }
            } catch (CurationError $exc) {
                $errors = ['reason' => $exc->getMessage()];
            }
            $values = $this->req()->form;
        }
        $choices = [];
        foreach (Records::specFor($kind) as $f) {
            $c = Records::choicesFor($db, $f);
            if ($c !== null) {
                $choices[$f->name] = $c;
            }
        }
        return $this->render('editor/edit.html', ['e' => $e, 'title' => Entities::titleOf($db, (int) $e['id']), 'fields' => Records::specFor($kind),
            'values' => $values, 'errors' => $errors, 'choices' => $choices,
            'reason' => (string) $this->req()->post('reason', '')], $errors ? 400 : 200);
    }

    public function citationAdd(string $publicId): Response
    {
        $this->requirePerm('citation.manage');
        return $this->curate($publicId, Curation::addCitation(...), [], 'Citation added.');
    }

    public function citationUpdate(string $publicId, int $cid): Response
    {
        $this->requirePerm('citation.manage');
        if ($this->req()->post('op') === 'remove') {
            return $this->curate($publicId, Curation::removeCitation(...), [$cid], 'Citation removed. It is kept in the audit log.');
        }
        return $this->curate($publicId, Curation::updateCitation(...), [$cid], 'Citation updated.');
    }

    public function accountAdd(string $publicId): Response
    {
        $this->requirePerm('citation.manage');
        return $this->curate($publicId, Curation::addAccount(...), [], 'Account recorded.');
    }

    public function accountUpdate(string $publicId, int $aid): Response
    {
        $this->requirePerm('citation.manage');
        return $this->curate($publicId, Curation::updateAccount(...), [$aid], 'Account revised. The previous text is kept in the audit log.');
    }

    public function linkUpdate(string $publicId, string $table, int $lid): Response
    {
        $this->requirePerm('record.edit');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        $row = $db->one("SELECT * FROM {$table} WHERE id=?", [$lid]);       // $table is one of four names fixed by the route
        if (!$row || !in_array((int) $e['id'], array_map('intval', Curation::linkEntities($row, $table)), true)) {
            $this->abort(404);
        }
        $remove = $this->req()->post('op') === 'remove';
        try {
            $db->tx(function () use ($db, $table, $lid, $remove) {
                if ($remove) {
                    Curation::removeLink($db, $this->me(), $table, $lid, $this->req()->form);
                } else {
                    Curation::updateLink($db, $this->me(), $table, $lid, $this->req()->form);
                }
            });
            $this->flash($remove ? 'Link removed. It is kept in the audit log.' : 'Link updated.', 'ok');
        } catch (CurationError $exc) {
            $this->flash($exc->getMessage(), 'error');
        }
        return $this->back($publicId);
    }

    // ───────────── duplicates and merging ─────────────
    public function duplicatesReport(): Response
    {
        $this->requirePerm('record.merge');
        return $this->render('editor/duplicates.html', ['pairs' => Merging::duplicateReport($this->db())]);
    }

    public function merge(): Response
    {
        $this->requirePerm('record.merge');
        $db = $this->db();
        $keepPid = trim((string) $this->req()->value('keep', ''));
        $retirePid = trim((string) $this->req()->value('retire', ''));
        // the forms let editors type "Name [per-…]"; keep only the permanent id
        foreach (['keep', 'retire'] as $name) {
            $v = (string) ($this->req()->value($name) ?? '');
            if (preg_match(Records::PID_IN_BRACKETS, $v, $m)) {
                if ($name === 'keep') {
                    $keepPid = $m[1];
                } else {
                    $retirePid = $m[1];
                }
            }
        }
        try {
            [$keep, $retire, $counts] = Merging::impact($db, $keepPid, $retirePid);
        } catch (MergeError $exc) {
            $this->flash($exc->getMessage(), 'error');
            return $this->redirect($this->url('editor.duplicates_report'));
        }
        if ($this->isPost()) {
            try {
                Merging::merge($db, $this->me(), $keep['public_id'], $retire['public_id'], $this->req()->post('reason'),
                    $this->req()->post('fill_gaps') === '1');
                $this->flash("Merged. {$retire['public_id']} now redirects to this record.", 'ok');
                return $this->redirect($this->url('editor.record', ['public_id' => $keep['public_id']]));
            } catch (MergeError $exc) {
                $this->flash($exc->getMessage(), 'error');
            }
        }
        $side = function (array $e) use ($db) {
            $fields = [];
            foreach (Entities::subtypeRow($db, (int) $e['id']) as $k => $v) {
                if (!in_array($k, ['entity_id', 'kind'], true) && $v !== null && $v !== '' && !str_ends_with($k, '_kind')) {
                    $fields[$k] = $v;
                }
            }
            return ['e' => $e, 'title' => Entities::titleOf($db, (int) $e['id']), 'fields' => $fields,
                'names' => $db->all('SELECT name, name_type FROM entity_names WHERE entity_id=?', [$e['id']])];
        };
        return $this->render('editor/merge.html', ['keep' => $side($keep), 'retire' => $side($retire), 'counts' => $counts]);
    }

    // ───────────── CSV import ─────────────
    public function importStart(): Response
    {
        $this->requirePerm('import.run');
        $db = $this->db();
        if ($this->isPost()) {
            $f = $this->req()->file('file');
            try {
                $data = $f ? (string) file_get_contents($f['path'], false, null, 0, Importer::MAX_BYTES + 1) : '';
                $iid = Importer::createPreview($db, $this->me(), (string) $this->req()->post('kind', ''), $data, $f ? $f['name'] : null);
                return $this->redirect($this->url('editor.import_preview', ['iid' => $iid]));
            } catch (ImportError $exc) {
                $this->flash($exc->getMessage(), 'error');
            }
        }
        $recent = $db->all('SELECT i.*, u.username FROM imports i JOIN users u ON u.id=i.created_by ORDER BY i.id DESC LIMIT 20');
        $columns = [];
        foreach (Importer::IMPORT_KINDS as $k) {
            $columns[$k] = Importer::columns($k);
        }
        return $this->render('editor/import.html', ['kinds' => Importer::IMPORT_KINDS, 'recent' => $recent, 'columns' => $columns]);
    }

    public function importTemplate(string $kind): Response
    {
        $this->requirePerm('import.run');
        if (!in_array($kind, Importer::IMPORT_KINDS, true)) {
            $this->abort(404);
        }
        return new Response(Importer::templateCsv($kind), 200, ['Content-Type' => 'text/csv; charset=utf-8',
            'Content-Disposition' => "attachment; filename=elf-archive-{$kind}-template.csv"]);
    }

    public function importPreview(int $iid): Response
    {
        $this->requirePerm('import.run');
        $db = $this->db();
        [$imp, $rows] = Importer::get($db, $iid);
        if (!$imp) {
            $this->abort(404);
        }
        if ($this->isPost()) {
            try {
                if ($this->req()->post('op') === 'discard') {
                    Importer::discard($db, $this->me(), $iid);
                    $this->flash('Import discarded. Nothing was created.', 'ok');
                    return $this->redirect($this->url('editor.import_start'));
                }
                $n = Importer::confirm($db, $this->me(), $iid, $this->app->config);
                $this->flash("{$n} submissions created. They are in the queue for review; nothing is public yet.", 'ok');
                return $this->redirect($this->url('editor.queue', ['tab' => 'new', 'batch' => $iid]));
            } catch (ImportError|WorkflowError|PermissionDenied $exc) {
                $this->flash($exc->getMessage(), 'error');
            }
        }
        return $this->render('editor/import_preview.html', ['imp' => $imp, 'rows' => $rows]);
    }

    public function bulk(): Response
    {
        $this->requirePerm('submission.publish');
        $sids = [];
        foreach ($this->req()->postList('sid') as $x) {
            if (ctype_digit($x)) {
                $sids[] = (int) $x;
            }
        }
        $sids = array_slice($sids, 0, 500);
        $back = Security::safeNext($this->req()->post('back'), '/editor');
        if ($this->req()->post('action') !== 'publish' || !$sids) {
            $this->flash('Select at least one submission.', 'error');
            return $this->redirect($back);
        }
        [$published, $failures] = Importer::bulkPublish($this->db(), $this->me(), $sids, $this->app->config);
        $this->flash("{$published} published.", 'ok');
        foreach (array_slice($failures, 0, 20) as [$sid, $title, $why]) {
            $this->flash("Not published: {$title} (#{$sid}) — {$why}", 'error');
        }
        return $this->redirect($back);
    }

    // ───────────── data quality ─────────────
    /** Records that may need attention. Warnings help editors investigate; nothing is changed automatically. */
    public function quality(): Response
    {
        $this->requirePerm('record.view_any');
        $db = $this->db();
        $live = 'e.merged_into IS NULL AND e.deleted_at IS NULL';
        $checks = [
            ['Published records without any citation',
                "SELECT e.public_id, e.kind FROM entities e WHERE {$live} AND e.publication_status='published' "
                . "AND e.kind IN ('person','family','place','event','organization') AND NOT EXISTS (SELECT 1 FROM citations c WHERE c.target_id=e.id) "
                . 'ORDER BY e.kind, e.id LIMIT 200'],
            ['Citations still marked unverified',
                "SELECT DISTINCT e.public_id, e.kind FROM citations c JOIN entities e ON e.id=c.target_id WHERE {$live} "
                . "AND c.evidence_status='unverified' ORDER BY e.kind, e.id LIMIT 200"],
            ['Events without a documented date',
                "SELECT e.public_id, e.kind FROM entities e JOIN events ev ON ev.entity_id=e.id WHERE {$live} AND ev.date_precision='unknown' LIMIT 200"],
            ['Events without a place',
                "SELECT e.public_id, e.kind FROM entities e WHERE {$live} AND e.kind='event' AND NOT EXISTS "
                . '(SELECT 1 FROM event_places p WHERE p.event_id=e.id) LIMIT 200'],
            ['Places without coordinates',
                "SELECT e.public_id, e.kind FROM entities e JOIN places p ON p.entity_id=e.id WHERE {$live} AND p.latitude IS NULL LIMIT 200"],
            ['Records without a description or summary',
                'SELECT e.public_id, e.kind FROM entities e LEFT JOIN people p ON p.entity_id=e.id LEFT JOIN families f ON f.entity_id=e.id '
                . "LEFT JOIN events ev ON ev.entity_id=e.id LEFT JOIN places pl ON pl.entity_id=e.id WHERE {$live} AND "
                . "((e.kind='person' AND p.summary IS NULL AND p.biography IS NULL) OR (e.kind='family' AND f.summary IS NULL AND f.narrative IS NULL) "
                . "OR (e.kind='event' AND ev.summary IS NULL AND ev.description IS NULL) OR (e.kind='place' AND pl.overview IS NULL)) LIMIT 200"],
            ['Disputed or uncertain relationships',
                'SELECT DISTINCT e.public_id, e.kind FROM relationships r JOIN entities e ON e.id=r.person_a_id '
                . "WHERE r.status IN ('disputed','uncertain') LIMIT 200"],
            ['Differing accounts marked as needing research',
                "SELECT DISTINCT e.public_id, e.kind FROM conflicting_accounts a JOIN entities e ON e.id=a.entity_id WHERE {$live} AND a.needs_research=1 LIMIT 200"],
            ['Photos without rights that allow public display',
                "SELECT e.public_id, e.kind FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE {$live} "
                . "AND a.rights_status IN ('rights_unknown','copyrighted_permission_pending') LIMIT 200"],
            ['Living people (kept restricted unless consent is confirmed)',
                "SELECT e.public_id, e.kind FROM entities e JOIN people p ON p.entity_id=e.id WHERE {$live} AND p.living_status='living' LIMIT 200"],
            ['Links pointing at a merged record',
                'SELECT DISTINCT e.public_id, e.kind FROM entities e WHERE e.merged_into IS NOT NULL AND ('
                . 'EXISTS (SELECT 1 FROM relationships r WHERE r.person_a_id=e.id OR r.person_b_id=e.id) OR '
                . 'EXISTS (SELECT 1 FROM citations c WHERE c.target_id=e.id)) LIMIT 200'],
        ];
        $out = [];
        foreach ($checks as [$label, $sql]) {
            $out[] = [$label, array_map(fn ($r) => [$r['public_id'], $r['kind'],
                Entities::titleOf($db, (int) Entities::getByPublicId($db, $r['public_id'])['id'])], $db->all($sql))];
        }
        return $this->render('editor/quality.html', ['checks' => $out]);
    }

    public function recordState(string $publicId): Response
    {
        $this->requirePerm('record.restrict');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        $vis = $this->req()->post('visibility');
        $status = $this->req()->post('status') ?: null;
        $reason = mb_substr(trim((string) $this->req()->post('reason', '')), 0, 1000);
        if (!in_array($vis, Vocab::VISIBILITIES, true) || !in_array($status, [null, 'published', 'archived'], true)) {
            $this->abort(400);
        }
        $back = $this->url('editor.record', ['public_id' => $publicId]);
        if ($reason === '') {
            $this->flash('Please record a reason. It is kept in the audit log.', 'error');
            return $this->redirect($back);
        }
        $sub = Entities::subtypeRow($db, (int) $e['id']);
        if ($e['kind'] === 'person' && $sub['living_status'] === 'living' && $vis === 'public' && $this->req()->post('consent_confirmed') !== '1') {
            $this->flash('This person is recorded as living. Confirm that consent to publish has been obtained.', 'error');
            return $this->redirect($back);
        }
        if ($e['kind'] === 'archive_item' && $vis === 'public' && !in_array($sub['rights_status'], Vocab::PUBLIC_RIGHTS, true)) {
            $this->flash("This item's rights do not allow public display. Update its rights status first.", 'error');
            return $this->redirect($back);
        }
        $db->tx(function () use ($db, $e, $status, $vis, $reason) {
            Entities::setState($db, (int) $e['id'], $status, $vis, $this->me()->id, $reason);
            if ($e['kind'] === 'archive_item') {
                Photos::syncItemAccess($db, (int) $e['id']);
            }
        });
        $this->flash('Record access updated.', 'ok');
        return $this->redirect($back);
    }

    /** Rights of a published archive item. Rights that forbid public display also restrict the item. */
    public function recordRights(string $publicId): Response
    {
        $this->requirePerm('record.restrict');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        $rights = $this->req()->post('rights_status');
        $reason = mb_substr(trim((string) $this->req()->post('reason', '')), 0, 1000);
        if ($e['kind'] !== 'archive_item' || !in_array($rights, Vocab::RIGHTS_STATUSES, true)) {
            $this->abort(400);
        }
        $back = $this->url('editor.record', ['public_id' => $publicId]);
        if ($reason === '') {
            $this->flash('Please record a reason. It is kept in the audit log.', 'error');
            return $this->redirect($back);
        }
        $words = preg_split('/\s+/u', trim((string) $this->req()->post('rights_holder', '')), -1, PREG_SPLIT_NO_EMPTY);
        $holder = mb_substr(implode(' ', $words), 0, 300) ?: null;
        $db->tx(function () use ($db, $e, $rights, $holder, $reason) {
            $id = (int) $e['id'];
            $old = Entities::subtypeRow($db, $id);
            $db->exec('UPDATE archive_items SET rights_status=?, rights_holder=? WHERE entity_id=?', [$rights, $holder, $id]);
            Audit::log($db, $this->me()->id, 'archive_item.rights_changed', 'archive_item', $e['public_id'],
                ['from' => $old['rights_status'], 'to' => $rights, 'reason' => $reason]);
            if (!in_array($rights, Vocab::PUBLIC_RIGHTS, true) && $e['visibility'] === 'public') {
                Entities::setState($db, $id, null, 'restricted', $this->me()->id, "Rights changed to {$rights}: {$reason}");
            } else {
                Entities::addRevision($db, $id, $this->me()->id, 'Rights changed to ' . str_replace('_', ' ', $rights), $reason);
                Search::reindex($db, $id);
            }
            Photos::syncItemAccess($db, $id);
        });
        $this->flash('Rights updated.', 'ok');
        return $this->redirect($back);
    }

    public function recordSlug(string $publicId): Response
    {
        $this->requirePerm('record.restrict');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        $new = $db->tx(fn () => Entities::changeSlug($db, (int) $e['id'], (string) $this->req()->post('slug', ''), $this->me()->id));
        $this->flash("Address changed to “{$new}”. The old address redirects here.", 'ok');
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]));
    }

    public function grantRep(string $publicId): Response
    {
        $this->requirePerm('family_rep.manage');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        if ($e['kind'] !== 'family') {
            $this->abort(404);
        }
        try {
            $db->tx(fn () => Families::grant($db, $this->me()->id, (string) $this->req()->post('username', ''), (int) $e['id'],
                (bool) $this->req()->post('can_suggest_edits'), (bool) $this->req()->post('can_propose_tree'),
                (bool) $this->req()->post('can_submit_media')));
            $this->flash('Representative added.', 'ok');
        } catch (\InvalidArgumentException $exc) {
            $this->flash($exc->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]));
    }

    public function revokeRep(string $publicId, int $gid): Response
    {
        $this->requirePerm('family_rep.manage');
        $db = $this->db();
        $e = $this->staffEntity($publicId);
        $grant = $db->one('SELECT * FROM family_representatives WHERE id=? AND family_id=?', [$gid, $e['id']]);
        if (!$grant) {
            $this->abort(404);
        }
        $db->tx(fn () => Families::revoke($db, $this->me()->id, $gid));
        $this->flash('Representative permission revoked.', 'ok');
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]));
    }

    // ───────────── contact messages / public correction requests ─────────────
    public function messages(): Response
    {
        $this->requirePerm('messages.view');
        $status = $this->arg('status') === 'handled' ? 'handled' : 'new';
        $rows = $this->db()->all('SELECT * FROM contact_messages WHERE status=? ORDER BY id DESC LIMIT 200', [$status]);
        return $this->render('editor/messages.html', ['rows' => $rows, 'status' => $status]);
    }

    public function messageHandled(int $mid): Response
    {
        $this->requirePerm('messages.view');
        $db = $this->db();
        $db->tx(function () use ($db, $mid) {
            $db->exec("UPDATE contact_messages SET status='handled', handled_by=? WHERE id=?", [$this->me()->id, $mid]);
            Audit::log($db, $this->me()->id, 'contact.handled', 'contact_message', $mid);
        });
        return $this->redirect($this->url('editor.messages'));
    }

    // ───────────── oral history consent and controls ─────────────
    private function oral(string $publicId): array
    {
        $e = $this->staffEntity($publicId);
        if ($e['kind'] !== 'oral_history') {
            $this->abort(404);
        }
        return $e;
    }

    public function consentSet(string $publicId, string $consentType): Response
    {
        $this->requirePerm('record.restrict');
        $db = $this->db();
        $e = $this->oral($publicId);
        try {
            $db->tx(fn () => Oral::setConsent($db, $this->me(), (int) $e['id'], $consentType, $this->req()->form));
            $this->flash('Consent recorded. What is public now follows this decision.', 'ok');
        } catch (ConsentError $exc) {
            $this->flash($exc->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]) . '#consent');
    }

    public function oralControls(string $publicId): Response
    {
        $this->requirePerm('record.restrict');
        $db = $this->db();
        $e = $this->oral($publicId);
        try {
            $db->tx(fn () => Oral::setControls($db, $this->me(), (int) $e['id'], $this->req()->form));
            $this->flash('Access controls updated.', 'ok');
        } catch (ConsentError $exc) {
            $this->flash($exc->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]) . '#consent');
    }

    // ───────────── curated explorations (the atlas) ─────────────
    public function explorationIndex(): Response
    {
        $this->requirePerm('record.edit');
        $db = $this->db();
        $form = $this->isPost() ? $this->req()->form : [];
        if ($this->isPost()) {
            try {
                $xid = $db->tx(fn () => Explorations::create($db, $this->me(), $this->req()->form));
                $this->flash('Exploration saved.', 'ok');
                return $this->redirect($this->url('editor.exploration_edit', ['xid' => $xid]));
            } catch (ExplorationError $exc) {
                $this->flash($exc->getMessage(), 'error');
            }
        }
        $rows = $db->all('SELECT x.id, x.slug, x.title, x.is_published, x.period_from, x.period_to, x.region, x.updated_at, '
            . '(SELECT COUNT(*) FROM exploration_items i WHERE i.exploration_id=x.id) AS n FROM explorations x ORDER BY lower(x.title)');
        return $this->render('editor/explorations.html', ['rows' => $rows, 'x' => null, 'form' => $form, 'items' => $form['items'] ?? '']);
    }

    public function explorationEdit(int $xid): Response
    {
        $this->requirePerm('record.edit');
        $db = $this->db();
        $x = $db->one('SELECT * FROM explorations WHERE id=?', [$xid]);
        if (!$x) {
            $this->abort(404);
        }
        if ($this->isPost()) {
            try {
                $deleted = $db->tx(function () use ($db, $xid) {
                    if ($this->req()->post('op') === 'delete') {
                        Explorations::delete($db, $this->me(), $xid);
                        return true;
                    }
                    Explorations::update($db, $this->me(), $xid, $this->req()->form);
                    return false;
                });
                if ($deleted) {
                    $this->flash('Exploration deleted.', 'ok');
                    return $this->redirect($this->url('editor.exploration_index'));
                }
                $this->flash('Exploration saved.', 'ok');
                return $this->redirect($this->url('editor.exploration_edit', ['xid' => $xid]));
            } catch (ExplorationError $exc) {
                $this->flash($exc->getMessage(), 'error');
                return $this->render('editor/exploration.html', ['x' => $x, 'form' => $this->req()->form,
                    'items' => $this->req()->post('items', '')], 400);
            }
        }
        return $this->render('editor/exploration.html', ['x' => $x, 'form' => $x, 'items' => Explorations::formItems($db, $xid),
            'shown' => Explorations::publicItems($db, $xid)]);
    }

    // ───────────── collections ─────────────
    public function collectionIndex(): Response
    {
        $this->requirePerm('record.edit');
        $db = $this->db();
        if ($this->isPost()) {
            try {
                $pid = $db->tx(fn () => Collections::create($db, $this->me(), $this->req()->form));
                $this->flash('Collection created. Add items to it below.', 'ok');
                return $this->redirect($this->url('editor.record', ['public_id' => $pid]));
            } catch (CollectionError $exc) {
                $this->flash($exc->getMessage(), 'error');
            }
        }
        $rows = $db->all('SELECT e.public_id, e.visibility, c.title, c.is_featured, (SELECT COUNT(*) FROM collection_items i WHERE i.collection_id=e.id) AS n '
            . 'FROM entities e JOIN collections c ON c.entity_id=e.id WHERE e.deleted_at IS NULL ORDER BY lower(c.title)');
        return $this->render('editor/collections.html', ['rows' => $rows]);
    }

    private function coll(string $publicId): array
    {
        $e = $this->staffEntity($publicId);
        if ($e['kind'] !== 'collection') {
            $this->abort(404);
        }
        return $e;
    }

    public function collectionUpdate(string $publicId): Response
    {
        $this->requirePerm('record.edit');
        $db = $this->db();
        $e = $this->coll($publicId);
        try {
            $db->tx(fn () => Collections::update($db, $this->me(), $e, $this->req()->form));
            $this->flash('Collection updated.', 'ok');
        } catch (CollectionError $exc) {
            $this->flash($exc->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]));
    }

    public function collectionItems(string $publicId): Response
    {
        $this->requirePerm('record.edit');
        $db = $this->db();
        $e = $this->coll($publicId);
        $op = $this->req()->post('op');
        if (!in_array($op, ['add', 'up', 'down', 'remove'], true)) {
            $this->abort(400);
        }
        $itemId = (int) ($this->req()->post('item_id') ?: 0);
        try {
            $db->tx(function () use ($db, $e, $op, $itemId) {
                if ($op === 'add') {
                    Collections::addItem($db, $this->me(), $e, $this->req()->form);
                } elseif ($op === 'remove') {
                    Collections::removeItem($db, $this->me(), $e, $itemId);
                } else {
                    Collections::moveItem($db, $this->me(), $e, $itemId, $op);
                }
            });
            $this->flash('Collection updated.', 'ok');
        } catch (CollectionError $exc) {
            $this->flash($exc->getMessage(), 'error');
        }
        return $this->redirect($this->url('editor.record', ['public_id' => $publicId]) . '#items');
    }
}
