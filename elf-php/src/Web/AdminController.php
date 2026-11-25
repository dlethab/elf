<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Http\Response;
use Elf\Services\AccountError;
use Elf\Services\Accounts;
use Elf\Services\Audit;
use Elf\Services\Entities;
use Elf\Services\Export;
use Elf\Services\Mfa;
use Elf\Services\Util;
use Elf\Vocab;

/** Administration: users and roles, audit log, taxonomies, operational overview. All counts shown are computed from the database; nothing is estimated. */
final class AdminController extends Controller
{
    public static function routes(App $app): void
    {
        $c = new self($app);
        $c->route('GET', '/admin', 'overview', 'admin.overview');
        $c->route('GET|POST', '/admin/export', 'export', 'admin.export');
        $c->route('GET', '/admin/users', 'users', 'admin.users');
        $c->route('GET', '/admin/users/<int:uid>', 'user', 'admin.user');
        $c->route('POST', '/admin/users/<int:uid>/roles', 'userRoles', 'admin.user_roles');
        $c->route('POST', '/admin/users/<int:uid>/<any(deactivate,reactivate,anonymize,verify,reset_mfa):action>', 'userAction', 'admin.user_action');
        $c->route('GET', '/admin/audit', 'auditLog', 'admin.audit_log');
        $c->route('GET|POST', '/admin/taxonomies', 'taxonomies', 'admin.taxonomies');
    }

    public function overview(): Response
    {
        $this->requirePerm('admin.overview');
        $db = $this->db();
        $one = fn (string $sql, array $a = []) => (int) $db->val($sql, $a);
        $pw = Entities::PUBLIC_WHERE;
        $stats = [
            'pending' => $one("SELECT COUNT(*) FROM submissions WHERE status IN ('submitted','under_review')"),
            'awaiting_publication' => $one("SELECT COUNT(*) FROM submissions WHERE status='approved'"),
            'pending_corrections' => $one("SELECT COUNT(*) FROM submissions WHERE kind='correction' AND status IN ('submitted','under_review','approved')"),
            'public_records' => $one("SELECT COUNT(*) FROM entities e WHERE {$pw}"),
            'restricted_records' => $one("SELECT COUNT(*) FROM entities WHERE visibility<>'public' AND deleted_at IS NULL AND merged_into IS NULL"),
            'no_citations' => $one("SELECT COUNT(*) FROM entities e WHERE {$pw} AND e.kind IN ('person','family','place','event') "
                . 'AND NOT EXISTS (SELECT 1 FROM citations c WHERE c.target_id=e.id)'),
            'unknown_dates_events' => $one("SELECT COUNT(*) FROM entities e JOIN events ev ON ev.entity_id=e.id WHERE {$pw} AND ev.date_precision='unknown'"),
            'places_no_coords' => $one("SELECT COUNT(*) FROM entities e JOIN places p ON p.entity_id=e.id WHERE {$pw} AND p.latitude IS NULL"),
            'living_restricted' => $one("SELECT COUNT(*) FROM people p JOIN entities e ON e.id=p.entity_id WHERE p.living_status='living' AND e.visibility<>'public'"),
            'users' => $one('SELECT COUNT(*) FROM users WHERE is_active=1'),
            'unverified' => $one('SELECT COUNT(*) FROM users WHERE is_active=1 AND email_verified_at IS NULL'),
            'outbox_unsent' => $one('SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL'),
            'outbox_failed' => $one('SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL AND attempts >= ?', [Accounts::MAX_EMAIL_ATTEMPTS]),
            'messages_new' => $one("SELECT COUNT(*) FROM contact_messages WHERE status='new'"),
            'fictional' => $one('SELECT COUNT(*) FROM entities WHERE is_fictional_test=1'),
            // community
            'reports_open' => $one("SELECT COUNT(*) FROM reports WHERE status IN ('open','escalated')"),
            'reports_escalated' => $one("SELECT COUNT(*) FROM reports WHERE status='escalated'"),
            // media, rights and consent
            'media_files' => $one("SELECT COUNT(*) FROM media_files WHERE file_role='original'"),
            'media_bytes' => $one('SELECT COALESCE(SUM(size_bytes),0) FROM media_files'),
            'media_failed' => $one("SELECT COUNT(*) FROM media_files WHERE processing_status='failed'"),
            'items_rights_unknown' => $one('SELECT COUNT(*) FROM archive_items a JOIN entities e ON e.id=a.entity_id '
                . "WHERE a.rights_status='rights_unknown' AND e.deleted_at IS NULL AND e.merged_into IS NULL"),
            'oral_no_consent' => $one('SELECT COUNT(*) FROM oral_histories o JOIN entities e ON e.id=o.entity_id WHERE e.deleted_at IS NULL '
                . 'AND e.merged_into IS NULL AND NOT EXISTS (SELECT 1 FROM consent_records c WHERE c.oral_history_id=o.entity_id '
                . "AND c.revoked_at IS NULL AND c.granted=1 AND c.consent_type IN ('publish_recording','publish_transcript'))"),
            'oral_embargoed' => $one("SELECT COUNT(*) FROM oral_histories WHERE embargo_until > date('now')"),
            // security
            'staff_without_mfa' => $one('SELECT COUNT(DISTINCT u.id) FROM users u JOIN user_roles r ON r.user_id=u.id AND r.revoked_at IS NULL '
                . "WHERE u.is_active=1 AND r.role IN ('editor','moderator','administrator') AND u.totp_enabled_at IS NULL"),
        ];
        $last = fn (string $action) => $db->val('SELECT created_at FROM audit_logs WHERE action=? ORDER BY id DESC LIMIT 1', [$action]);
        $stats['last_backup'] = $last('system.backup');
        $stats['last_export'] = $last('export.public');
        $recent = $db->all('SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 15');
        return $this->render('admin/overview.html', ['stats' => $stats, 'recent' => $recent]);
    }

    /** Public data export (only what the public site shows). Each download is audited. */
    public function export(): Response
    {
        $this->requirePerm('admin.overview');
        $db = $this->db();
        $production = $this->app->config['ENV'] === 'production';
        if ($this->isPost()) {
            $fictional = $this->req()->post('include_fictional') === '1' && !$production;
            [$data, $manifest] = $db->tx(fn () => Export::exportZip($db, $this->me()->id, $this->app->config['BASE_URL'], $fictional));
            $name = 'elf-archive-public-' . substr($manifest['generated_at'], 0, 10) . '.zip';
            return new Response($data, 200, ['Content-Type' => 'application/zip', 'Content-Disposition' => "attachment; filename=\"{$name}\"",
                'Cache-Control' => 'no-store']);
        }
        $counts = Export::build($db)['manifest']['counts'];
        return $this->render('admin/export.html', ['counts' => $counts, 'is_production' => $production]);
    }

    public function users(): Response
    {
        $this->requirePerm('users.manage');
        $q = mb_substr(trim((string) $this->arg('q', '')), 0, 100);
        $sql = "SELECT u.*, (SELECT GROUP_CONCAT(role, ', ') FROM user_roles r WHERE r.user_id=u.id AND r.revoked_at IS NULL) AS roles FROM users u";
        $args = [];
        if ($q !== '') {
            $sql .= ' WHERE u.username LIKE ? OR u.email LIKE ? OR u.display_name LIKE ?';
            $args = array_fill(0, 3, "%{$q}%");
        }
        $rows = $this->db()->all($sql . ' ORDER BY u.id DESC LIMIT 300', $args);
        return $this->render('admin/users.html', ['rows' => $rows, 'q' => $q]);
    }

    private function findUser(int $uid): array
    {
        $u = $this->db()->one('SELECT * FROM users WHERE id=?', [$uid]);
        if (!$u) {
            $this->abort(404);
        }
        return $u;
    }

    public function user(int $uid): Response
    {
        $this->requirePerm('users.manage');
        $db = $this->db();
        $u = $this->findUser($uid);
        $sessions = $db->all('SELECT created_at, expires_at, revoked_at, ip, user_agent FROM user_sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 10', [$uid]);
        $subs = $db->all('SELECT status, COUNT(*) AS n FROM submissions WHERE submitter_id=? GROUP BY status', [$uid]);
        return $this->render('admin/user.html', ['u' => $u, 'roles' => Accounts::getRoles($db, $uid), 'all_roles' => Vocab::ROLES,
            'sessions' => $sessions, 'subs' => $subs]);
    }

    public function userRoles(int $uid): Response
    {
        $this->requirePerm('roles.assign');
        $db = $this->db();
        $this->findUser($uid);
        $role = $this->req()->post('role');
        $action = $this->req()->post('action');
        if (!in_array($role, Vocab::ROLES, true) || !in_array($action, ['grant', 'revoke'], true)) {
            $this->abort(400);
        }
        try {
            $db->tx(function () use ($db, $uid, $role, $action) {
                if ($action === 'grant') {
                    Accounts::grantRole($db, $this->me()->id, $uid, $role, $this->ip());
                } else {
                    Accounts::revokeRole($db, $this->me()->id, $uid, $role, $this->ip());
                }
            });
            $this->flash("Role “{$role}” " . ($action === 'grant' ? 'granted' : 'revoked') . '.', 'ok');
        } catch (AccountError $e) {
            $this->flash(implode(' ', $e->errors), 'error');
        }
        return $this->redirect($this->url('admin.user', ['uid' => $uid]));
    }

    public function userAction(int $uid, string $action): Response
    {
        $this->requirePerm('users.manage');
        $db = $this->db();
        $this->findUser($uid);
        try {
            $db->tx(function () use ($db, $uid, $action) {
                $me = $this->me()->id;
                match ($action) {
                    // lost phone: the user signs in with their password and sets it up again
                    'reset_mfa' => (function () use ($db, $uid, $me) {
                        Mfa::disable($db, $uid, $me);
                        Accounts::revokeAllSessions($db, $uid);
                    })(),
                    'verify' => (function () use ($db, $uid, $me) {
                        $db->exec('UPDATE users SET email_verified_at=? WHERE id=? AND email_verified_at IS NULL', [Util::nowIso(), $uid]);
                        Audit::log($db, $me, 'account.verified_by_admin', 'user', $uid, null, $this->ip());
                    })(),
                    'deactivate' => Accounts::deactivate($db, $me, $uid, $this->ip()),
                    'reactivate' => Accounts::reactivate($db, $me, $uid, $this->ip()),
                    'anonymize' => Accounts::anonymize($db, $me, $uid, $this->ip()),
                };
            });
            $msgs = ['deactivate' => 'Account deactivated and signed out everywhere.', 'reactivate' => 'Account reactivated.',
                'anonymize' => 'Account anonymised. Contribution history is kept without personal details.',
                'verify' => 'Email marked as verified.',
                'reset_mfa' => 'Two-step sign-in reset and sessions ended. The user can set it up again after signing in.'];
            $this->flash($msgs[$action], 'ok');
        } catch (AccountError $e) {
            $this->flash(implode(' ', $e->errors), 'error');
        }
        return $this->redirect($this->url('admin.user', ['uid' => $uid]));
    }

    public function auditLog(): Response
    {
        $this->requirePerm('audit.view');
        $db = $this->db();
        $page = max(1, $this->req()->argInt('page', 1));
        $action = mb_substr(trim((string) $this->arg('action', '')), 0, 60);
        $sql = 'SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id';
        $args = [];
        if ($action !== '') {
            $sql .= ' WHERE a.action LIKE ?';
            $args = [$action . '%'];
        }
        $total = (int) $db->val("SELECT COUNT(*) FROM ({$sql})", $args);
        $rows = $db->all($sql . ' ORDER BY a.id DESC LIMIT 100 OFFSET ?', [...$args, ($page - 1) * 100]);
        return $this->render('admin/audit.html', ['rows' => $rows, 'total' => $total, 'page' => $page, 'action' => $action]);
    }

    public function taxonomies(): Response
    {
        $this->requirePerm('settings.manage');
        $db = $this->db();
        $tables = ['place' => 'place_types', 'event' => 'event_types'];
        if ($this->isPost()) {
            $table = $tables[$this->req()->post('which', '')] ?? null;
            if (!$table) {
                $this->abort(400);
            }
            if ($this->req()->post('op') === 'toggle') {
                $id = $this->req()->post('id');
                $db->tx(function () use ($db, $table, $id) {
                    $db->exec("UPDATE {$table} SET is_active=1-is_active WHERE id=?", [$id]);
                    Audit::log($db, $this->me()->id, 'taxonomy.toggled', $table, $id);
                });
            } else {
                $words = preg_split('/\s+/u', trim((string) $this->req()->post('label', '')), -1, PREG_SPLIT_NO_EMPTY);
                $label = mb_substr(implode(' ', $words), 0, 80);
                $slug = substr(trim((string) preg_replace('/[^a-z0-9]+/', '_', mb_strtolower($label)), '_'), 0, 40);
                if ($label === '' || $slug === '') {
                    $this->flash('Enter a label.', 'error');
                } elseif ($db->one("SELECT 1 FROM {$table} WHERE slug=?", [$slug])) {
                    $this->flash('A category with that name already exists.', 'error');
                } else {
                    $db->tx(function () use ($db, $table, $slug, $label) {
                        $db->exec("INSERT INTO {$table}(slug, label, sort_order) VALUES (?,?,500)", [$slug, $label]);
                        Audit::log($db, $this->me()->id, 'taxonomy.added', $table, $slug, ['label' => $label]);
                    });
                    $this->flash("Added “{$label}”.", 'ok');
                }
            }
            return $this->redirect($this->url('admin.taxonomies'));
        }
        return $this->render('admin/taxonomies.html', ['place' => $db->all('SELECT * FROM place_types ORDER BY sort_order, label'),
            'event' => $db->all('SELECT * FROM event_types ORDER BY sort_order, label')]);
    }
}
