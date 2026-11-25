<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;

/**
 * Submission lifecycle and publication. This class is the ONLY path from a contribution to a public record, and
 * every rule is enforced here on the server:
 *
 *   draft → submitted → under_review → (needs_revision ⇄ submitted) → approved → published
 *   any pre-approval state → withdrawn (submitter) ;  submitted/under_review/approved → rejected (editor)
 *
 * Submitters drive draft/needs_revision → submitted and withdrawal. Reviewing, approving and publishing require
 * editor permissions, and by default an editor cannot review their own submission.
 */
final class Workflow
{
    public const TRANSITIONS = [
        'draft' => ['submitted', 'withdrawn'],
        'submitted' => ['under_review', 'needs_revision', 'rejected', 'withdrawn'],
        'under_review' => ['needs_revision', 'approved', 'rejected', 'withdrawn'],
        'needs_revision' => ['submitted', 'withdrawn'],
        'approved' => ['published', 'under_review', 'rejected'],
        'published' => [], 'rejected' => [], 'withdrawn' => [], 'superseded' => [],
    ];
    public const SUBMITTER_MOVES = ['draft>submitted', 'needs_revision>submitted', 'draft>withdrawn', 'submitted>withdrawn',
        'under_review>withdrawn', 'needs_revision>withdrawn'];
    public const EDITOR_MOVES = [
        'submitted>under_review' => 'submission.review',
        'submitted>needs_revision' => 'submission.request_revision',
        'under_review>needs_revision' => 'submission.request_revision',
        'submitted>rejected' => 'submission.decide',
        'under_review>rejected' => 'submission.decide',
        'approved>rejected' => 'submission.decide',
        'under_review>approved' => 'submission.decide',
        'approved>under_review' => 'submission.review',
        'approved>published' => 'submission.publish',
    ];
    public const REASON_REQUIRED = ['needs_revision', 'rejected'];
    public const CORRECTABLE = ['person', 'family', 'place', 'event', 'source', 'organization'];
    public const PHOTO_KINDS = ['person', 'family', 'place', 'event', 'organization', 'correction', 'oral_history'];
    public const EDITABLE = ['draft', 'needs_revision'];
    public const NOTICE = [
        'under_review' => 'An editor has started reviewing your submission.',
        'needs_revision' => 'An editor has asked for changes to your submission.',
        'approved' => 'Your submission was approved and is awaiting publication.',
        'rejected' => 'Your submission was not accepted.',
        'published' => 'Your submission has been published.',
    ];

    public static function get(Db $db, int $sid): ?array
    {
        return $db->one('SELECT * FROM submissions WHERE id=?', [$sid]);
    }

    /** Proposed data as stored (a JSON object; corrections hold {"changes": {...}}). */
    public static function data(array $s): array
    {
        $d = json_decode((string) $s['proposed_data'], true);
        return is_array($d) ? $d : [];
    }

    /** JSON for proposed data. An empty "changes" mapping stays an object, as the Python edition writes it. */
    public static function encode(array $data): string
    {
        if (array_key_exists('changes', $data) && $data['changes'] === []) {
            $data['changes'] = new \stdClass();
        }
        return Util::json($data);
    }

    private static function event(Db $db, int $sid, ?int $actorId, ?string $from, string $to, ?string $message, bool $visible = true): void
    {
        $db->exec('INSERT INTO submission_events(submission_id, actor_id, from_status, to_status, message, visible_to_submitter) VALUES (?,?,?,?,?,?)',
            [$sid, $actorId, $from, $to, $message, (int) $visible]);
    }

    private static function requireSubmitRights(?CurrentUser $user, array $config): void
    {
        if (!$user || !$user->can('submission.create')) {
            throw new PermissionDenied('You do not have permission to submit.');
        }
        if (($config['REQUIRE_EMAIL_VERIFICATION'] ?? true) && !$user->email_verified) {
            throw new PermissionDenied('Please verify your email address before submitting.');
        }
    }

    /** Kind-specific authorization. Returns [target entity|null, family entity|null]. */
    public static function authorizeNew(Db $db, CurrentUser $user, string $kind, array $config, ?string $targetPublicId = null, ?string $familyPublicId = null): array
    {
        self::requireSubmitRights($user, $config);
        $target = $family = null;
        if ($kind === 'correction') {
            $target = Entities::getPublicByPublicId($db, $targetPublicId ?: '');
            if (!$target || !in_array($target['kind'], self::CORRECTABLE, true)) {
                throw new WorkflowError('That record could not be found.');   // never reveals private records
            }
        }
        if ($kind === 'relationship') {
            $isEditor = $user->can('record.view_any');
            if ($familyPublicId) {
                $family = Entities::getPublicByPublicId($db, $familyPublicId, 'family');
            }
            if (!$family && !$isEditor) {
                throw new PermissionDenied('Relationship proposals are made through a family you represent.');
            }
            if ($family && !$isEditor) {
                $g = Families::activeGrant($db, $user->id, (int) $family['id']);
                if (!$g || !$g['can_propose_tree']) {
                    throw new PermissionDenied('You are not authorised to propose relationships for this family.');
                }
            }
        }
        if ($kind === 'membership' && !$user->can('record.view_any')) {
            $any = false;
            foreach (Families::familiesForUser($db, $user->id) as $f) {
                $any = $any || (bool) $f['can_propose_tree'];
            }
            if (!$any) {
                throw new PermissionDenied('Family members are proposed by the family\'s representatives or by editors.');
            }
        }
        return [$target, $family];
    }

    /**
     * Data-dependent authorization, re-checked whenever proposed data is saved. Returns the family that scopes the
     * proposal (or null). Family representatives may only add members to their own family.
     */
    public static function scopeFor(Db $db, CurrentUser $user, string $kind, array $data): ?array
    {
        if ($kind !== 'membership' || $user->can('record.view_any')) {
            return null;
        }
        $fam = Entities::getPublicByPublicId($db, $data['family'] ?? '', 'family');
        $g = $fam ? Families::activeGrant($db, $user->id, (int) $fam['id']) : null;
        if (!$g || !$g['can_propose_tree']) {
            throw new PermissionDenied('You are not authorised to propose relationships for this family.');
        }
        return $fam;
    }

    /** Create a DRAFT submission. `data` is already validated JSON-able content. */
    public static function create(Db $db, CurrentUser $user, string $kind, array $data, array $config, ?array $target = null, ?array $family = null,
                                  ?string $contributorNote = null, ?string $rightsNote = null, bool $bulk = false, ?int $importBatchId = null): int
    {
        if (!$bulk && !RateLimit::allow($db, "submit:{$user->id}", 30, 3600)) {
            throw new WorkflowError('You have created many submissions recently. Please wait a while before adding more.');
        }
        $family = self::scopeFor($db, $user, $kind, $data) ?? $family;
        $now = Util::nowIso();
        $sid = $db->insert("INSERT INTO submissions(kind, target_entity_id, family_scope_id, proposed_data, contributor_note, rights_note, "
            . "status, submitter_id, import_batch_id, created_at, updated_at) VALUES (?,?,?,?,?,?, 'draft', ?,?,?,?)",
            [$kind, $target['id'] ?? null, $family['id'] ?? null, self::encode($data),
                mb_substr((string) $contributorNote, 0, 3000) ?: null, mb_substr((string) $rightsNote, 0, 2000) ?: null,
                $user->id, $importBatchId, $now, $now]);
        self::event($db, $sid, $user->id, null, 'draft', 'Draft created');
        Audit::log($db, $user->id, 'submission.created', 'submission', $sid, ['kind' => $kind]);
        return $sid;
    }

    public static function updateDraft(Db $db, CurrentUser $user, int $sid, array $data, ?string $contributorNote = null, ?string $rightsNote = null): void
    {
        $db->tx(function () use ($db, $user, $sid, $data, $contributorNote, $rightsNote) {
            $s = self::get($db, $sid);
            if (!$s || $s['submitter_id'] !== $user->id) {
                throw new PermissionDenied('Not your submission.');
            }
            if (!in_array($s['status'], self::EDITABLE, true)) {
                throw new WorkflowError('This submission can no longer be edited.');
            }
            self::scopeFor($db, $user, $s['kind'], $data);
            $db->exec('UPDATE submissions SET proposed_data=?, contributor_note=?, rights_note=?, updated_at=? WHERE id=?',
                [self::encode($data), mb_substr((string) $contributorNote, 0, 3000) ?: null, mb_substr((string) $rightsNote, 0, 2000) ?: null,
                    Util::nowIso(), $sid]);
        });
    }

    /** Move a submission. Throws PermissionDenied / WorkflowError. Publishing is atomic. */
    public static function transition(Db $db, CurrentUser $user, int $sid, string $to, array $config, ?string $message = null,
                                      ?string $internalNote = null, bool $consentConfirmed = false): array
    {
        $message = mb_substr(trim((string) $message), 0, 3000) ?: null;
        $db->tx(function () use ($db, $user, $sid, $to, $config, $message, $internalNote, $consentConfirmed) {
            $s = self::get($db, $sid);
            if (!$s) {
                throw new WorkflowError('Submission not found.');
            }
            $frm = $s['status'];
            if (!in_array($to, self::TRANSITIONS[$frm] ?? [], true)) {
                throw new WorkflowError("A submission that is '" . str_replace('_', ' ', $frm) . "' cannot move to '" . str_replace('_', ' ', $to) . "'.");
            }
            $isSubmitter = $user->id === $s['submitter_id'];
            $move = "{$frm}>{$to}";
            if (in_array($move, self::SUBMITTER_MOVES, true) && $isSubmitter) {
                if ($to === 'submitted') {
                    self::requireSubmitRights($user, $config);
                }
            } elseif (isset(self::EDITOR_MOVES[$move])) {
                if (!$user->can(self::EDITOR_MOVES[$move])) {
                    throw new PermissionDenied('You do not have permission for this action.');
                }
                if ($isSubmitter && !($config['ALLOW_SELF_REVIEW'] ?? false)) {
                    throw new PermissionDenied('You cannot review your own submission. Another editor must do this.');
                }
            } else {
                throw new PermissionDenied('You do not have permission for this action.');
            }
            if (in_array($to, self::REASON_REQUIRED, true) && !$message) {
                throw new WorkflowError('Please give a reason; the contributor will see it.');
            }
            $now = Util::nowIso();
            $updates = ['status' => $to, 'updated_at' => $now];
            if ($to === 'submitted') {
                $updates['submitted_at'] = $now;
                if ($s['kind'] === 'correction') {
                    if (!(self::data($s)['changes'] ?? null) && !self::photoCount($db, $sid)) {
                        throw new WorkflowError('Change at least one field, add a source, or add a photo before submitting.');
                    }
                    $updates['base_revision'] = Entities::latestRevisionNumber($db, (int) $s['target_entity_id']);
                }
            }
            if ($to === 'under_review' && !$isSubmitter) {
                $updates['reviewer_id'] = $user->id;
            }
            if (in_array($to, ['approved', 'rejected', 'needs_revision'], true)) {
                $updates += ['decided_at' => $now, 'reviewer_id' => $user->id, 'decision_reason' => $message];
                $updates['reviewer_id'] = $user->id;
            }
            if ($to === 'published') {
                $updates['published_at'] = $now;
                $updates['reviewer_id'] = $user->id;
                $updates['consent_confirmed'] = (int) $consentConfirmed;
                $updates['result_entity_id'] = self::publish($db, $s, $user, $consentConfirmed);
            }
            if ($internalNote !== null && trim($internalNote) !== '' && $user->can('confidential.view')) {
                $prior = (string) $s['editor_notes'];
                $updates['editor_notes'] = trim($prior . "\n[{$now} {$user->username}] " . mb_substr(trim($internalNote), 0, 2000));
                self::event($db, $sid, $user->id, $frm, $frm, 'Internal note added', false);
            }
            $sets = implode(', ', array_map(fn ($k) => "{$k}=?", array_keys($updates)));
            $db->exec("UPDATE submissions SET {$sets} WHERE id=?", [...array_values($updates), $sid]);
            self::event($db, $sid, $user->id, $frm, $to, $message);
            Audit::log($db, $user->id, "submission.{$to}", 'submission', $sid, ['from' => $frm]);
            self::notify($db, $s, $to);
        });
        return self::get($db, $sid);
    }

    public static function addInternalNote(Db $db, CurrentUser $user, int $sid, ?string $note): void
    {
        if (!$user->can('confidential.view')) {
            throw new PermissionDenied('You do not have permission for this action.');
        }
        $note = mb_substr(trim((string) $note), 0, 2000);
        if ($note === '') {
            throw new WorkflowError('The note is empty.');
        }
        $db->tx(function () use ($db, $user, $sid, $note) {
            $s = self::get($db, $sid);
            if (!$s) {
                throw new WorkflowError('Submission not found.');
            }
            $now = Util::nowIso();
            $db->exec('UPDATE submissions SET editor_notes=?, updated_at=? WHERE id=?',
                [trim(((string) $s['editor_notes']) . "\n[{$now} {$user->username}] {$note}"), $now, $sid]);
            self::event($db, $sid, $user->id, $s['status'], $s['status'], 'Internal note added', false);
        });
    }

    /** Referenced places/people must still be public at publish time. */
    private static function recheckRefs(Db $db, string $kind, array $data): void
    {
        foreach (Records::specFor($kind, false) as $f) {
            if ($f->kind === 'ref' && !empty($data[$f->name])) {
                if (!Entities::getPublicByPublicId($db, $data[$f->name], $f->ref)) {
                    throw new WorkflowError("“{$f->label}” refers to a record that is no longer published. Return the submission for revision.");
                }
            }
        }
    }

    public static function photoCount(Db $db, int $sid): int
    {
        return (int) $db->val('SELECT COUNT(*) FROM submission_photos WHERE submission_id=?', [$sid]);
    }

    private static function publish(Db $db, array $s, CurrentUser $user, bool $consentConfirmed): ?int
    {
        $data = self::data($s);
        $kind = $s['kind'];
        if ($kind === 'correction') {
            $target = Entities::get($db, $s['target_entity_id']);
            if (!$target || $target['publication_status'] !== 'published' || $target['merged_into'] || $target['deleted_at']) {
                throw new WorkflowError('The record to correct is no longer published.');
            }
            $changes = $data['changes'] ?? [];
            if ($changes) {                      // a correction may consist only of photos
                self::recheckRefs($db, $target['kind'], $changes);
                Records::applyCorrection($db, $target, $changes, $user->id, (int) $s['id'], $s['decision_reason']);
            }
            Photos::publishForSubmission($db, $s, (int) $target['id'], $user->id);
            return (int) $target['id'];
        }
        self::recheckRefs($db, $kind, $data);
        if (in_array($kind, Records::LINK_KINDS, true)) {
            try {
                Records::applyLink($db, $kind, $data, $user->id, (int) $s['id']);
            } catch (\PDOException $exc) {
                if (str_contains($exc->getMessage(), 'UNIQUE')) {
                    throw new WorkflowError('This relationship has already been recorded.', 0, $exc);
                }
                throw $exc;
            }
            return null;
        }
        $eid = Records::applyNew($db, $kind, $data, $user->id, (int) $s['id'], $consentConfirmed);
        Photos::publishForSubmission($db, $s, $eid, $user->id);
        if ($kind === 'oral_history') {
            $rec = $db->one("SELECT s.item_id FROM archive_item_subjects s JOIN archive_items a ON a.entity_id=s.item_id "
                . "WHERE s.subject_id=? AND a.media_kind IN ('audio','video') ORDER BY s.item_id LIMIT 1", [$eid]);
            if ($rec) {
                $db->exec('UPDATE oral_histories SET media_item_id=? WHERE entity_id=?', [$rec['item_id'], $eid]);
            }
            Oral::sync($db, $eid, $user->id, 'Published: access follows the recorded consent');
        }
        return $eid;
    }

    private static function notify(Db $db, array $s, string $to): void
    {
        if (isset(self::NOTICE[$to]) && $s['submitter_id']) {
            $u = $db->one('SELECT notify_submission_updates FROM users WHERE id=?', [$s['submitter_id']]);
            if ($u && $u['notify_submission_updates']) {
                $db->exec('INSERT INTO notifications(user_id, kind, message, link) VALUES (?,?,?,?)',
                    [$s['submitter_id'], "submission.{$to}", self::NOTICE[$to], "/dashboard/submissions/{$s['id']}"]);
            }
        }
    }

    // ───────────── reading ─────────────
    /** Own submission, or any submission for staff with queue access. Otherwise null. */
    public static function getForUser(Db $db, CurrentUser $user, int $sid): ?array
    {
        $s = self::get($db, $sid);
        if (!$s) {
            return null;
        }
        return ($s['submitter_id'] === $user->id || $user->can('queue.view')) ? $s : null;
    }

    public static function visibleEvents(Db $db, CurrentUser $user, int $sid, bool $asStaff = false): array
    {
        $q = 'SELECT ev.*, u.display_name AS actor_name FROM submission_events ev LEFT JOIN users u ON u.id=ev.actor_id WHERE ev.submission_id=?';
        if (!($asStaff && $user->can('confidential.view'))) {
            $q .= ' AND ev.visible_to_submitter=1';
        }
        return $db->all($q . ' ORDER BY ev.id', [$sid]);
    }

    public static function userSubmissions(Db $db, int $userId, ?string $status = null): array
    {
        $q = 'SELECT * FROM submissions WHERE submitter_id=?';
        $a = [$userId];
        if ($status) {
            $q .= ' AND status=?';
            $a[] = $status;
        }
        return $db->all($q . ' ORDER BY updated_at DESC, id DESC', $a);
    }

    public static function queue(Db $db, array $statuses = ['submitted', 'under_review', 'approved'], ?string $kind = null, int $limit = 200, ?int $batch = null): array
    {
        $ph = implode(',', array_fill(0, count($statuses), '?'));
        $q = "SELECT s.*, u.display_name AS submitter_name FROM submissions s JOIN users u ON u.id=s.submitter_id WHERE s.status IN ({$ph})";
        $a = $statuses;
        if ($kind) {
            $q .= ' AND s.kind=?';
            $a[] = $kind;
        }
        if ($batch) {
            $q .= ' AND s.import_batch_id=?';
            $a[] = $batch;
        }
        $a[] = $limit;
        return $db->all($q . ' ORDER BY COALESCE(s.submitted_at, s.updated_at), s.id LIMIT ?', $a);
    }

    public static function titleFor(Db $db, array $s): string
    {
        $d = self::data($s);
        if ($s['kind'] === 'correction') {
            return 'Correction: ' . Entities::titleOf($db, (int) $s['target_entity_id']);
        }
        $ref = new Field('x', 'x', 'ref');
        $show = fn ($key) => Records::displayValue($db, $ref, $d[$key] ?? null);
        return match ($s['kind']) {
            'relationship' => $show('person_a') . ' — ' . $show('person_b'),
            'affiliation' => $show('person') . ' — ' . $show('organization'),
            'membership' => $show('person') . ' — ' . $show('family'),
            'participation' => (!empty($d['person']) ? $show('person') : $show('organization')) . ' — ' . $show('event'),
            default => (string) (($d[Records::TITLE_FIELD[$s['kind']] ?? 'title'] ?? null) ?: '(untitled)'),
        };
    }
}
