<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Http\Response;
use Elf\Services\AccountError;
use Elf\Services\Accounts;
use Elf\Services\Duplicates;
use Elf\Services\Entities;
use Elf\Services\Families;
use Elf\Services\Mfa;
use Elf\Services\PermissionDenied;
use Elf\Services\PhotoError;
use Elf\Services\Photos;
use Elf\Services\Records;
use Elf\Services\Storage;
use Elf\Services\Util;
use Elf\Services\Workflow;
use Elf\Services\WorkflowError;
use Elf\Vocab;

/**
 * Contributor dashboard and contribution forms. Every route checks ownership on the server; a submission that is not
 * yours returns 404 (it is never confirmed to exist).
 */
final class DashboardController extends Controller
{
    public const NEW_KINDS = ['person', 'family', 'place', 'event', 'organization', 'source'];

    public static function routes(App $app): void
    {
        $c = new self($app);
        $c->route('GET', '/dashboard', 'home', 'dashboard.home');
        $c->route('GET', '/dashboard/submissions', 'submissions', 'dashboard.submissions');
        $c->route('GET', '/dashboard/submissions/<int:sid>', 'submission', 'dashboard.submission');
        $c->route('POST', '/dashboard/submissions/<int:sid>/photos', 'addPhoto', 'dashboard.add_photo');
        $c->route('POST', '/dashboard/submissions/<int:sid>/photos/<int:pid>/remove', 'removePhoto', 'dashboard.remove_photo');
        $c->route('GET|POST', '/contribute/<any(person,family,place,event,source,organization,affiliation,membership,participation,oral_history):kind>',
            'contribute', 'dashboard.contribute');
        $c->route('GET|POST', '/contribute/correction/<public_id>', 'correction', 'dashboard.correction');
        $c->route('GET|POST', '/contribute/relationship', 'relationship', 'dashboard.relationship');
        $c->route('GET|POST', '/dashboard/submissions/<int:sid>/edit', 'edit', 'dashboard.edit');
        $c->route('POST', '/dashboard/submissions/<int:sid>/<any(submit,withdraw):action>', 'act', 'dashboard.act');
        $c->route('GET|POST', '/dashboard/profile', 'profile', 'dashboard.profile');
        $c->route('GET|POST', '/dashboard/password', 'password', 'dashboard.password');
        $c->route('GET|POST', '/dashboard/security', 'security', 'dashboard.security');
        $c->route('GET|POST', '/dashboard/notifications', 'notifications', 'dashboard.notifications');
    }

    private function cfg(bool $drafting = false): array
    {
        $cfg = $this->app->config;
        if ($drafting) {                       // drafts may be saved before email verification; submitting may not
            $cfg['REQUIRE_EMAIL_VERIFICATION'] = false;
        }
        return $cfg;
    }

    private function choices(string $kind): array
    {
        $out = [];
        foreach (Records::specFor($kind) as $f) {
            $c = Records::choicesFor($this->db(), $f);
            if ($c !== null) {
                $out[$f->name] = $c;
            }
        }
        return $out;
    }

    private function own(int $sid): array
    {
        $s = $this->db()->one('SELECT * FROM submissions WHERE id=?', [$sid]);
        if (!$s || (int) $s['submitter_id'] !== $this->me()->id) {
            $this->abort(404);
        }
        return $s;
    }

    private function formKind(array $s): string
    {
        if ($s['kind'] === 'correction') {
            return Entities::get($this->db(), $s['target_entity_id'])['kind'];
        }
        return $s['kind'];
    }

    private function withTitles(array $subs): array
    {
        return array_map(fn ($s) => [$s, Workflow::titleFor($this->db(), $s)], $subs);
    }

    // ───────────── overview ─────────────
    public function home(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $uid = $this->me()->id;
        $counts = [];
        foreach ($db->all('SELECT status, COUNT(*) AS n FROM submissions WHERE submitter_id=? GROUP BY status', [$uid]) as $r) {
            $counts[$r['status']] = (int) $r['n'];
        }
        $recent = array_slice(Workflow::userSubmissions($db, $uid), 0, 8);
        return $this->render('dashboard/home.html', ['counts' => $counts, 'recent' => $this->withTitles($recent),
            'fams' => Families::familiesForUser($db, $uid), 'new_kinds' => self::NEW_KINDS, 'kind_labels' => Vocab::KIND_LABELS,
            'notes' => $db->all('SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 5', [$uid])]);
    }

    public function submissions(): Response
    {
        $this->loginRequired();
        $status = $this->arg('status') ?: null;
        $rows = Workflow::userSubmissions($this->db(), $this->me()->id, $status);
        return $this->render('dashboard/submissions.html', ['rows' => $this->withTitles($rows), 'status' => $status]);
    }

    public function submission(int $sid, ?array $photoErrors = null, ?array $photoValues = null, int $status = 200): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $s = $this->own($sid);
        $data = Workflow::data($s);
        $cfg = $this->app->config;
        $ctx = ['s' => $s, 'title' => Workflow::titleFor($db, $s), 'events' => Workflow::visibleEvents($db, $this->me(), $sid),
            'published' => $s['result_entity_id'] ? Entities::get($db, $s['result_entity_id']) : null,
            'photos' => Photos::listForSubmission($db, $sid), 'photo_errors' => $photoErrors ?: [],
            'photo_values' => $photoValues ?: [], 'rights_choices' => Vocab::CONTRIBUTOR_RIGHTS,
            'can_add_photos' => in_array($s['status'], Workflow::EDITABLE, true) && in_array($s['kind'], Workflow::PHOTO_KINDS, true),
            'takes_photos' => in_array($s['kind'], Workflow::PHOTO_KINDS, true),
            'max_photo_mb' => intdiv((int) $cfg['MAX_PHOTO_BYTES'], 1024 * 1024),
            'max_doc_mb' => intdiv((int) $cfg['MAX_DOCUMENT_BYTES'], 1024 * 1024),
            'max_av_mb' => intdiv((int) $cfg['MAX_AV_BYTES'], 1024 * 1024),
            'max_photos' => $cfg['MAX_PHOTOS_PER_SUBMISSION']];
        if ($s['kind'] === 'correction') {
            $ctx['diff'] = Records::diff($db, $this->formKind($s), (int) $s['target_entity_id'], (array) ($data['changes'] ?? []));
            $ctx['target'] = Entities::get($db, $s['target_entity_id']);
        } else {
            $ctx['rows'] = Records::displayRows($db, $s['kind'], $data);
        }
        if ($s['kind'] === 'person' && in_array($s['status'], [...Workflow::EDITABLE, 'submitted'], true)) {
            $names = array_merge([$data['preferred_name'] ?? null, $data['full_name'] ?? null], (array) ($data['aliases'] ?? []));
            $cands = Duplicates::findPersonCandidates($db, $names);
            $ctx['possible_existing'] = array_values(array_filter($cands, fn ($c) => Entities::getPublicByPublicId($db, $c['public_id'], 'person')));
        }
        return $this->render('dashboard/submission.html', $ctx, $status);
    }

    // ───────────── photos ─────────────
    private function wantsJson(): bool
    {
        return $this->req()->header('X-Upload-Progress') === '1';     // sent by site.js when it shows a progress bar
    }

    public function addPhoto(int $sid): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $this->own($sid);
        $f = $this->req()->file('photo');
        $err = $this->req()->files['photo']['error'] ?? UPLOAD_ERR_OK;
        try {
            if (in_array($err, [UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE], true)) {      // over the server's upload_max_filesize
                throw new PhotoError(['photo' => 'This photo is too large. Reduce its size and try again.']);
            }
            if ($err === UPLOAD_ERR_PARTIAL) {
                throw new PhotoError(['photo' => 'The upload did not finish. Please try again.']);
            }
            Photos::add($db, Storage::fromConfig($this->app->config), $this->me(), $sid, $f ? ['path' => $f['path'], 'name' => $f['name']] : null,
                $this->req()->form, $this->app->config);
        } catch (PhotoError $e) {
            if ($this->wantsJson()) {
                return $this->json(['errors' => array_map(fn ($v) => $this->_($v), $e->errors)], 400);
            }
            return $this->submission($sid, $e->errors, $this->req()->form, 400);
        } catch (PermissionDenied|WorkflowError $e) {
            if ($this->wantsJson()) {
                return $this->json(['errors' => ['photo' => $this->_($e->getMessage())]], 400);
            }
            $this->flash($e->getMessage(), 'error');
            return $this->redirect($this->url('dashboard.submission', ['sid' => $sid]));
        }
        $this->flash('Photo added. It will be seen only by you and the editors unless an editor approves it for publication.', 'ok');
        $target = $this->url('dashboard.submission', ['sid' => $sid]) . '#photos';
        return $this->wantsJson() ? $this->json(['redirect' => $target]) : $this->redirect($target);
    }

    public function removePhoto(int $sid, int $pid): Response
    {
        $this->loginRequired();
        $this->own($sid);
        try {
            Photos::remove($this->db(), Storage::fromConfig($this->app->config), $this->me(), $sid, $pid);
            $this->flash('Photo removed.', 'ok');
        } catch (PermissionDenied|WorkflowError $e) {
            $this->flash($e->getMessage(), 'error');
        }
        return $this->redirect($this->url('dashboard.submission', ['sid' => $sid]) . '#photos');
    }

    // ───────────── create / edit ─────────────
    /** Validate the posted form; create or update the draft; optionally submit. Returns [response|null, errors]. */
    private function save(string $kind, string $formKind, ?int $sid = null, ?array $target = null, ?array $family = null): array
    {
        $db = $this->db();
        $form = $this->req()->form;
        [$clean, $errors] = Records::validate($db, $formKind, $form);
        if (!$errors && $target !== null) {
            $changes = Records::changedFields($db, $formKind, (int) $target['id'], $clean);
            // An unchanged correction may be saved as a draft so that photos can be added to it.
            if (!$changes && ($form['action'] ?? null) === 'submit' && !($sid && Photos::count($db, $sid))) {
                $errors['form'] = 'You have not changed anything yet. Edit the fields that are wrong, add a source, or save a draft and add a photo.';
            }
            $data = ['changes' => $changes];
        } else {
            $data = $clean;
        }
        $note = $form['contributor_note'] ?? null;
        $rights = $form['rights_note'] ?? null;
        if ($errors) {
            return [null, $errors];
        }
        $u = $this->me();
        try {
            if ($sid === null) {
                $sid = $db->tx(fn () => Workflow::create($db, $u, $kind, $data, $this->cfg(), $target, $family, $note, $rights));
            } else {
                Workflow::updateDraft($db, $u, $sid, $data, $note, $rights);
            }
            if (($form['action'] ?? null) === 'submit') {
                Workflow::transition($db, $u, $sid, 'submitted', $this->cfg());
                $this->flash('Submitted for editorial review. You will be notified when an editor responds.', 'ok');
            } else {
                $this->flash('Draft saved. It is visible only to you until you submit it.', 'ok');
            }
        } catch (PermissionDenied $e) {
            if ($sid === null) {
                return [null, ['form' => $e->getMessage()]];
            }
            $this->flash("Your draft was saved, but it could not be submitted: {$e->getMessage()}", 'error');
        } catch (WorkflowError $e) {
            if ($sid === null) {
                return [null, ['form' => $e->getMessage()]];
            }
            $this->flash($e->getMessage(), 'error');
        }
        return [$this->redirect($this->url('dashboard.submission', ['sid' => $sid])), []];
    }

    private function form(string $kind, string $formKind, array $values, array $errors, string $heading, ?array $target = null,
                          ?array $family = null, ?array $s = null, int $status = 200): Response
    {
        $post = $this->isPost();
        $note = $post ? ($this->req()->post('contributor_note') ?? '') : ($s ? ($s['contributor_note'] ?? '') : '');
        $rights = $post ? ($this->req()->post('rights_note') ?? '') : ($s ? ($s['rights_note'] ?? '') : '');
        return $this->render('dashboard/contribute.html', ['fields' => Records::specFor($formKind), 'values' => $values, 'errors' => $errors,
            'choices' => $this->choices($formKind), 'kind' => $kind, 'form_kind' => $formKind, 'heading' => $heading,
            'target' => $target, 'family' => $family, 's' => $s, 'kind_label' => Vocab::KIND_LABELS[$formKind],
            'contributor_note' => (string) $note, 'rights_note' => (string) $rights], $status);
    }

    /**
     * Reference fields can be pre-filled from the address, e.g. /contribute/affiliation?person=per-abc12345, and a new
     * place's coordinates from the map picker (/contribute/place?latitude=15.3&longitude=38.9). Pre-filled coordinates
     * carry no precision: the contributor must still choose one.
     */
    private function prefill(string $kind): array
    {
        $db = $this->db();
        $out = [];
        foreach (Records::specFor($kind) as $f) {
            $v = $this->arg($f->name);
            if ($f->kind === 'ref' && $v && Entities::getPublicByPublicId($db, $v, $f->ref)) {
                $out[$f->name] = Records::refLabel($db, $v);
            }
        }
        if ($kind === 'place') {
            $la = self::pyFloat($this->arg('latitude', ''));
            $lo = self::pyFloat($this->arg('longitude', ''));
            if ($la === null || $lo === null) {
                return $out;
            }
            if ($la >= -90 && $la <= 90 && $lo >= -180 && $lo <= 180) {
                $out['latitude'] = sprintf('%.5f', $la);
                $out['longitude'] = sprintf('%.5f', $lo);
            }
        }
        return $out;
    }

    /** float(text) as Python parses it (surrounding spaces allowed), or null. */
    private static function pyFloat(?string $v): ?float
    {
        $v = trim((string) $v);
        return ($v !== '' && is_numeric($v)) ? (float) $v : null;
    }

    public function contribute(string $kind): Response
    {
        $this->loginRequired();
        try {
            Workflow::authorizeNew($this->db(), $this->me(), $kind, $this->cfg(true));
        } catch (PermissionDenied) {
            $this->abort(403);
        }
        $heading = $this->_('New record: {kind}', ['kind' => $this->_(Vocab::KIND_LABELS[$kind])]);
        if ($this->isPost()) {
            [$resp, $errors] = $this->save($kind, $kind);
            if ($resp) {
                return $resp;
            }
            return $this->form($kind, $kind, $this->req()->form, $errors, $heading, status: 400);
        }
        return $this->form($kind, $kind, $this->prefill($kind), [], $heading);
    }

    public function correction(string $publicId): Response
    {
        $this->loginRequired();
        $db = $this->db();
        try {
            [$target] = Workflow::authorizeNew($db, $this->me(), 'correction', $this->cfg(true), $publicId);
        } catch (WorkflowError) {
            $this->abort(404);
        } catch (PermissionDenied) {
            $this->abort(403);
        }
        $fk = $target['kind'];
        $title = Entities::titleOf($db, (int) $target['id']);
        $heading = $this->_('Suggest a correction: {title}', ['title' => $title]);
        if ($this->isPost()) {
            [$resp, $errors] = $this->save('correction', $fk, target: $target);
            if ($resp) {
                return $resp;
            }
            return $this->form('correction', $fk, $this->req()->form, $errors, $heading, $target, status: 400);
        }
        return $this->form('correction', $fk, Records::formValues(Records::currentClean($db, $fk, (int) $target['id']), $fk, $db), [], $heading, $target);
    }

    public function relationship(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $famPid = $this->req()->value('family') ?: null;
        try {
            [, $family] = Workflow::authorizeNew($db, $this->me(), 'relationship', $this->cfg(true), null, $famPid);
        } catch (PermissionDenied) {
            $this->abort(403);
        }
        $heading = $this->_('Propose a family relationship') . ($family ? ': ' . Entities::titleOf($db, (int) $family['id']) : '');
        if ($this->isPost()) {
            [$resp, $errors] = $this->save('relationship', 'relationship', family: $family);
            if ($resp) {
                return $resp;
            }
            return $this->form('relationship', 'relationship', $this->req()->form, $errors, $heading, family: $family, status: 400);
        }
        return $this->form('relationship', 'relationship', $this->prefill('relationship'), [], $heading, family: $family);
    }

    public function edit(int $sid): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $s = $this->own($sid);
        if (!in_array($s['status'], Workflow::EDITABLE, true)) {
            $this->flash('This submission can no longer be edited.', 'error');
            return $this->redirect($this->url('dashboard.submission', ['sid' => $sid]));
        }
        $fk = $this->formKind($s);
        $target = $s['kind'] === 'correction' ? Entities::get($db, $s['target_entity_id']) : null;
        $family = $s['family_scope_id'] ? Entities::get($db, $s['family_scope_id']) : null;
        $heading = $this->_('Edit: {title}', ['title' => Workflow::titleFor($db, $s)]);
        if ($this->isPost()) {
            [$resp, $errors] = $this->save($s['kind'], $fk, $sid, $target, $family);
            if ($resp) {
                return $resp;
            }
            return $this->form($s['kind'], $fk, $this->req()->form, $errors, $heading, $target, $family, $s, 400);
        }
        $data = Workflow::data($s);
        if ($target !== null) {
            $base = Records::currentClean($db, $fk, (int) $target['id']);
            foreach ((array) ($data['changes'] ?? []) as $k => $v) {
                $base[$k] = $v;
            }
            $data = $base;
        }
        return $this->form($s['kind'], $fk, Records::formValues($data, $fk, $db), [], $heading, $target, $family, $s);
    }

    public function act(int $sid, string $action): Response
    {
        $this->loginRequired();
        $this->own($sid);
        try {
            Workflow::transition($this->db(), $this->me(), $sid, $action === 'submit' ? 'submitted' : 'withdrawn', $this->cfg());
            $this->flash($action === 'submit' ? 'Submitted for editorial review.' : 'Submission withdrawn.', 'ok');
        } catch (PermissionDenied|WorkflowError $e) {
            $this->flash($e->getMessage(), 'error');
        }
        return $this->redirect($this->url('dashboard.submission', ['sid' => $sid]));
    }

    // ───────────── account ─────────────
    public function profile(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $errors = [];
        if ($this->isPost()) {
            try {
                $db->tx(fn () => Accounts::updateProfile($db, $this->me()->id, $this->req()->form));
                $this->flash('Profile saved.', 'ok');
                return $this->redirect($this->url('dashboard.profile'));
            } catch (AccountError $e) {
                $errors = $e->errors;
            }
        }
        $u = $db->one('SELECT username, email, display_name, bio, languages, research_interests, attribution_pref, '
            . 'notify_submission_updates, notify_forum_replies, email_verified_at FROM users WHERE id=?', [$this->me()->id]);
        return $this->render('dashboard/profile.html', ['u' => $u, 'errors' => $errors], $errors ? 400 : 200);
    }

    public function password(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $errors = [];
        if ($this->isPost()) {
            if ($this->req()->post('new_password') !== $this->req()->post('new_password2')) {
                $errors['new_password2'] = 'The passwords do not match.';
            } else {
                try {
                    $db->tx(fn () => Accounts::changePassword($db, $this->me()->id, $this->req()->post('current_password'),
                        $this->req()->post('new_password'), $this->app->session->get('sid')));
                    $this->flash('Password changed. Your other sessions have been signed out.', 'ok');
                    return $this->redirect($this->url('dashboard.home'));
                } catch (AccountError $e) {
                    $errors = $e->errors;
                }
            }
        }
        return $this->render('dashboard/password.html', ['errors' => $errors], $errors ? 400 : 200);
    }

    /** Two-step sign-in. The new secret is kept in the session until the first code confirms it. */
    public function security(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $u = $this->me();
        $session = $this->app->session;
        $codes = null;
        $error = null;
        if ($this->isPost()) {
            $op = $this->req()->post('op');
            if ($op === 'start') {
                $session->set('mfa_setup', Mfa::newSecret());
            } elseif ($op === 'confirm' && $session->get('mfa_setup')) {
                $codes = $db->tx(fn () => Mfa::enable($db, $u->id, $session->get('mfa_setup'), $this->req()->post('code')));
                if ($codes) {
                    $session->pop('mfa_setup');
                    $this->flash('Two-step sign-in is on.', 'ok');
                } else {
                    $error = 'That code is not valid. Enter the current code from your app, or one of your recovery codes.';
                }
            } elseif (in_array($op, ['disable', 'codes'], true)) {
                $ok = $db->tx(function () use ($db, $u, $op, &$codes) {
                    $ok = Accounts::authenticate($db, $u->username, (string) $this->req()->post('password', ''), $this->ip()) === $u->id;
                    if ($ok && $op === 'disable') {
                        Mfa::disable($db, $u->id);
                        $this->flash('Two-step sign-in is off.', 'ok');
                    } elseif ($ok) {
                        $codes = Mfa::regenerateCodes($db, $u->id);
                    }
                    return $ok;
                });
                if (!$ok) {
                    $error = 'That password is not correct.';
                } elseif ($op === 'disable') {
                    return $this->redirect($this->url('dashboard.security'));
                }
            }
        }
        $row = $db->one('SELECT totp_enabled_at FROM users WHERE id=?', [$u->id]);
        $setup = !$row['totp_enabled_at'] ? $session->get('mfa_setup') : null;
        return $this->render('dashboard/security.html', ['enabled' => (bool) $row['totp_enabled_at'], 'setup' => $setup, 'codes' => $codes,
            'error' => $error, 'remaining' => Mfa::remainingCodes($db, $u->id),
            'uri' => $setup ? Mfa::otpauthUri($setup, $u->username) : null,
            'qr' => $setup ? Mfa::qrSvgDataUri(Mfa::otpauthUri($setup, $u->username)) : null,
            'required' => ($this->app->config['REQUIRE_STAFF_MFA'] ?? false) && (bool) $u->roles], $error ? 400 : 200);
    }

    public function notifications(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        if ($this->isPost()) {
            $db->exec('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL', [Util::nowIso(), $this->me()->id]);
            return $this->redirect($this->url('dashboard.notifications'));
        }
        $rows = $db->all('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100', [$this->me()->id]);
        return $this->render('dashboard/notifications.html', ['rows' => $rows]);
    }
}
