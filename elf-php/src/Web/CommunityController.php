<?php
declare(strict_types=1);

namespace Elf\Web;

use Elf\App;
use Elf\Http\Response;
use Elf\Security;
use Elf\Services\Entities;
use Elf\Services\Forum;
use Elf\Services\ForumError;

/**
 * Community forum (public reading, verified members posting) and moderation. Every action is checked on the server by
 * Services\Forum; templates only reflect those rules.
 */
final class CommunityController extends Controller
{
    public static function routes(App $app): void
    {
        $c = new self($app);
        $c->route('GET', '/community', 'index', 'community.index');
        $c->route('GET', '/community/rules', 'rules', 'community.rules');
        $c->route('GET', '/community/search', 'search', 'community.search');
        $c->route('GET', '/community/c/<slug>', 'category', 'community.category');
        $c->route('GET|POST', '/community/c/<slug>/new', 'newTopic', 'community.new_topic');
        $c->route('GET', '/community/topics/<slug>', 'topic', 'community.topic');
        $c->route('POST', '/community/topics/<slug>/reply', 'reply', 'community.reply');
        $c->route('GET|POST', '/community/posts/<int:pid>/edit', 'edit', 'community.edit');
        $c->route('POST', '/community/report', 'report', 'community.report');
        $c->route('GET', '/community/users/<username>', 'profile', 'community.profile');
        $c->route('GET', '/moderation', 'moderation', 'community.moderation');
        $c->route('POST', '/moderation/posts/<int:pid>', 'modPost', 'community.mod_post');
        $c->route('POST', '/moderation/topics/<int:tid>', 'modTopic', 'community.mod_topic');
        $c->route('POST', '/moderation/users/<int:uid>', 'modUser', 'community.mod_user');
        $c->route('POST', '/moderation/reports/<int:rid>', 'modReport', 'community.mod_report');
    }

    private function mod(): bool
    {
        return Forum::isMod($this->viewer());
    }

    public function index(): Response
    {
        $db = $this->db();
        $recent = $db->all('SELECT t.slug, t.title, c.title AS category_title, COALESCE(t.last_post_at, t.created_at) AS at FROM forum_topics t '
            . "JOIN forum_categories c ON c.id=t.category_id WHERE t.status IN ('open','locked','archived') ORDER BY at DESC LIMIT 10");
        return $this->render('community/index.html', ['cats' => Forum::categories($db), 'recent' => $recent,
            'can_post' => Forum::canPost($db, $this->viewer())]);
    }

    public function rules(): Response
    {
        return $this->render('community/rules.html');
    }

    public function search(): Response
    {
        $q = mb_substr(trim((string) $this->arg('q', '')), 0, 100);
        return $this->render('community/search.html', ['q' => $q, 'rows' => $q !== '' ? Forum::search($this->db(), $q) : null]);
    }

    private function cat(string $slug): array
    {
        $cat = Forum::category($this->db(), $slug);
        if (!$cat) {
            $this->abort(404);
        }
        return $cat;
    }

    public function category(string $slug): Response
    {
        $db = $this->db();
        $cat = $this->cat($slug);
        [$rows, $total] = Forum::topics($db, (int) $cat['id'], $this->page(), $this->mod());
        return $this->render('community/category.html', ['cat' => $cat, 'rows' => $rows, 'total' => $total, 'page' => $this->page(),
            'per_page' => Forum::PER_PAGE, 'can_post' => Forum::canPost($db, $this->viewer())]);
    }

    public function newTopic(string $slug): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $cat = $this->cat($slug);
        [$ok, $why] = Forum::canPost($db, $this->viewer());
        $link = mb_substr(trim((string) $this->req()->value('about', '')), 0, 20);
        $link = ($link !== '' && Entities::getPublicByPublicId($db, $link)) ? $link : null;
        $values = ['title' => (string) $this->req()->post('title', ''), 'body' => (string) $this->req()->post('body', '')];
        $error = null;
        if ($this->isPost()) {
            if ($this->req()->post('website')) {
                return $this->redirect($this->url('community.category', ['slug' => $slug]));
            }
            try {
                $tslug = $db->tx(fn () => Forum::createTopic($db, $this->me(), $cat, $this->req()->post('title'), $this->req()->post('body'), $link));
                return $this->redirect($this->url('community.topic', ['slug' => $tslug]));
            } catch (ForumError $e) {
                $error = $e->getMessage();
            }
        }
        return $this->render('community/new_topic.html', ['cat' => $cat, 'values' => $values, 'error' => $error, 'ok' => $ok, 'why' => $why,
            'link' => $link], $error ? 400 : 200);
    }

    private function findTopic(string $slug): array
    {
        $t = Forum::topic($this->db(), $slug, $this->mod());
        if (!$t) {
            $this->abort(404);
        }
        return $t;
    }

    public function topic(string $slug): Response
    {
        $db = $this->db();
        $t = $this->findTopic($slug);
        [$rows, $total] = Forum::posts($db, (int) $t['id'], $this->page(), $this->mod());
        $edits = [];
        if ($this->mod()) {
            foreach ($db->all('SELECT * FROM forum_post_edits WHERE post_id IN (SELECT id FROM forum_posts WHERE topic_id=?) ORDER BY id', [$t['id']]) as $r) {
                $edits[$r['post_id']][] = $r;
            }
        }
        $linked = null;
        if ($t['archive_link']) {
            $e = Entities::getPublicByPublicId($db, $t['archive_link']);
            $linked = $e ? ['kind' => $e['kind'], 'slug' => $e['slug'], 'title' => Entities::titleOf($db, (int) $e['id'])] : null;
        }
        return $this->render('community/topic.html', ['t' => $t, 'rows' => $rows, 'total' => $total, 'page' => $this->page(),
            'per_page' => Forum::PER_PAGE, 'can_post' => Forum::canPost($db, $this->viewer()), 'edits' => $edits, 'linked' => $linked,
            'report_categories' => Forum::REPORT_CATEGORIES, 'mod' => $this->mod()]);
    }

    public function reply(string $slug): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $t = $this->findTopic($slug);
        try {
            $pid = $db->tx(fn () => Forum::reply($db, $this->me(), $t, $this->req()->post('body')));
            return $this->redirect($this->url('community.topic', ['slug' => $slug, 'page' => $this->arg('last') ?: null]) . "#post-{$pid}");
        } catch (ForumError $e) {
            $this->flash($e->getMessage(), 'error');
            return $this->redirect($this->url('community.topic', ['slug' => $slug]) . '#reply');
        }
    }

    public function edit(int $pid): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $p = $db->one('SELECT p.*, t.slug AS topic_slug FROM forum_posts p JOIN forum_topics t ON t.id=p.topic_id WHERE p.id=?', [$pid]);
        if (!$p || (int) $p['author_id'] !== $this->me()->id) {
            $this->abort(404);
        }
        $error = null;
        if ($this->isPost()) {
            try {
                $db->tx(fn () => Forum::edit($db, $this->me(), $pid, $this->req()->post('body')));
                $this->flash('Your post has been updated.', 'ok');
                return $this->redirect($this->url('community.topic', ['slug' => $p['topic_slug']]) . "#post-{$pid}");
            } catch (ForumError $e) {
                $error = $e->getMessage();
            }
        }
        return $this->render('community/edit.html', ['p' => $p, 'error' => $error, 'body' => $this->req()->post('body', $p['body']),
            'allowed' => Forum::canEdit($p, $this->me())], $error ? 400 : 200);
    }

    private function postInt(string $k): ?int
    {
        $v = trim((string) $this->req()->post($k, ''));
        return preg_match('/^[+-]?\d+$/', $v) ? (int) $v : null;
    }

    public function report(): Response
    {
        $this->loginRequired();
        $db = $this->db();
        $postId = $this->postInt('post_id');
        $topicId = $this->postInt('topic_id');
        if ($postId) {
            $p = $db->one('SELECT p.topic_id, t.slug FROM forum_posts p JOIN forum_topics t ON t.id=p.topic_id WHERE p.id=?', [$postId]);
            if (!$p) {
                $this->abort(404);
            }
            $topicId = null;
            $back = "/community/topics/{$p['slug']}#post-{$postId}";
        } elseif ($topicId) {
            $t = $db->one('SELECT slug FROM forum_topics WHERE id=?', [$topicId]);
            if (!$t) {
                $this->abort(404);
            }
            $back = "/community/topics/{$t['slug']}";
        } else {
            $this->abort(400);
        }
        try {
            $db->tx(fn () => Forum::report($db, $this->me(), $postId ?: null, $topicId ?: null, $this->req()->post('category'), $this->req()->post('reason')));
            $this->flash('Thank you. A moderator will look at your report.', 'ok');
        } catch (ForumError $e) {
            $this->flash($e->getMessage(), 'error');
        }
        return $this->redirect($back);
    }

    public function profile(string $username): Response
    {
        $db = $this->db();
        $u = $db->one('SELECT id, username, display_name, bio, languages, research_interests, created_at, anonymized_at, is_active '
            . 'FROM users WHERE username=?', [$username]);
        if (!$u || $u['anonymized_at'] || !$u['is_active']) {
            $this->abort(404);
        }
        $topics = $db->all("SELECT slug, title, created_at FROM forum_topics WHERE author_id=? AND status IN ('open','locked','archived') "
            . 'ORDER BY created_at DESC LIMIT 20', [$u['id']]);
        $nPosts = (int) $db->val("SELECT COUNT(*) FROM forum_posts WHERE author_id=? AND status='visible'", [$u['id']]);
        return $this->render('community/profile.html', ['u' => $u, 'topics' => $topics, 'n_posts' => $nPosts]);
    }

    // ───────────── moderation ─────────────
    public function moderation(): Response
    {
        $this->requirePerm('forum.moderate');
        $db = $this->db();
        $status = $this->arg('status', 'open');
        if (!in_array($status, ['open', 'actioned', 'dismissed', 'escalated'], true)) {
            $status = 'open';
        }
        $log = $db->all('SELECT m.*, u.username FROM moderation_actions m JOIN users u ON u.id=m.moderator_id ORDER BY m.id DESC LIMIT 50');
        $restricted = $db->all("SELECT id, username, forum_restricted_until FROM users WHERE forum_restricted_until > strftime('%Y-%m-%dT%H:%M:%SZ','now') "
            . 'ORDER BY forum_restricted_until');
        $counts = [];
        foreach (['open', 'escalated', 'actioned', 'dismissed'] as $s) {
            $counts[$s] = (int) $db->val('SELECT COUNT(*) FROM reports WHERE status=?', [$s]);
        }
        return $this->render('community/moderation.html', ['reports' => Forum::reportsQueue($db, $status), 'status' => $status, 'log' => $log,
            'restricted' => $restricted, 'report_categories' => Forum::REPORT_CATEGORIES, 'counts' => $counts]);
    }

    private function moderate(callable $fn, array $args, string $back): Response
    {
        $db = $this->db();
        try {
            $db->tx(fn () => $fn($db, $this->me(), ...$args));
            $this->flash('Done. The action is recorded in the moderation log.', 'ok');
        } catch (ForumError $e) {
            $this->flash($e->getMessage(), 'error');
        }
        return $this->redirect($back);
    }

    /** The page to return to: the form's own "back" if it is a path on this site. */
    private function back(string $default): string
    {
        return Security::safeNext($this->req()->post('back') ?: null, $default);
    }

    public function modPost(int $pid): Response
    {
        $this->requirePerm('forum.moderate');
        $p = $this->db()->one('SELECT t.slug FROM forum_posts p JOIN forum_topics t ON t.id=p.topic_id WHERE p.id=?', [$pid]);
        if (!$p) {
            $this->abort(404);
        }
        return $this->moderate(Forum::moderatePost(...), [$pid, $this->req()->post('action'), $this->req()->post('reason')],
            $this->back("/community/topics/{$p['slug']}#post-{$pid}"));
    }

    public function modTopic(int $tid): Response
    {
        $this->requirePerm('forum.moderate');
        $t = $this->db()->one('SELECT slug FROM forum_topics WHERE id=?', [$tid]);
        if (!$t) {
            $this->abort(404);
        }
        return $this->moderate(Forum::moderateTopic(...), [$tid, $this->req()->post('action'), $this->req()->post('reason')],
            $this->back("/community/topics/{$t['slug']}"));
    }

    public function modUser(int $uid): Response
    {
        $this->requirePerm('forum.moderate');
        return $this->moderate(Forum::warnOrRestrict(...), [$uid, $this->postInt('days') ?? 0, $this->req()->post('reason')], $this->back('/moderation'));
    }

    public function modReport(int $rid): Response
    {
        $this->requirePerm('forum.moderate');
        return $this->moderate(Forum::resolveReport(...), [$rid, $this->req()->post('status'), $this->req()->post('note')], '/moderation');
    }
}
