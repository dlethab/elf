<?php
declare(strict_types=1);

namespace Elf\Services;

use Elf\Db;

/**
 * Community forum and moderation.
 *
 * Forum posts are community conversation, never archive records: nothing here changes the archive. Posting needs a
 * verified account that is not under a moderator's restriction. Every moderation action is written to the
 * append-only moderation log. Hidden topics and posts disappear from public view; removed posts leave a placeholder
 * so the conversation still reads correctly.
 */
final class Forum
{
    public const EDIT_WINDOW = 24 * 3600;
    public const MAX_LINKS = 3;
    public const PER_PAGE = 30;
    public const REPORT_CATEGORIES = [
        'spam' => 'Spam or advertising', 'harassment' => 'Harassment or abuse', 'private_information' => "Someone's private information",
        'threat' => 'A threat or incitement', 'misinformation' => 'Deliberately false information', 'copyright' => 'Copyright infringement',
        'other' => 'Something else',
    ];
    public const POST_ACTIONS = ['hide' => 'hidden', 'remove' => 'removed', 'restore' => 'visible'];
    public const TOPIC_ACTIONS = ['lock' => 'locked', 'unlock' => 'open', 'archive' => 'archived', 'hide' => 'hidden', 'restore' => 'open'];
    private const URL = '~https?://[^\s<>"\']+~i';

    private static function esc(string $s): string
    {
        return htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE | ENT_HTML5, 'UTF-8');
    }

    /**
     * Plain text → safe HTML: everything is escaped; http(s) links become links that search engines are told not to
     * follow; blank lines separate paragraphs.
     */
    public static function render(?string $body): string
    {
        $out = [];
        foreach (preg_split('/\n\s*\n/', trim((string) $body)) as $para) {
            $esc = htmlspecialchars($para, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
            $esc = preg_replace_callback('~https?://[^\s<>"\']+~i', function ($m) {
                // the escaped text contains &amp; etc.; stop at an escaped quote or bracket as the raw pattern would
                $raw = $m[0];
                $cut = preg_split('/&(?:quot|#039|lt|gt);/', $raw)[0];
                $tail = substr($raw, strlen($cut));
                $url = rtrim($cut, '.,;:)');
                return '<a href="' . $url . '" rel="nofollow ugc noopener noreferrer">' . $url . '</a>' . substr($cut, strlen($url)) . $tail;
            }, $esc);
            $out[] = '<p>' . str_replace("\n", '<br>', $esc) . '</p>';
        }
        return implode('', $out);
    }

    private static function cleanBody(?string $body): string
    {
        $body = trim(str_replace("\r\n", "\n", (string) $body));
        $len = mb_strlen($body, 'UTF-8');
        if ($len < 2) {
            throw new ForumError('Write a message.');
        }
        if ($len > 20000) {
            throw new ForumError('Messages can be at most 20,000 characters.');
        }
        if (preg_match_all(self::URL, $body) > self::MAX_LINKS) {
            throw new ForumError('A message can contain at most 3 links.');
        }
        return $body;
    }

    /** [ok, reason]. Verified, active, and not under a moderator's restriction. */
    public static function canPost(Db $db, ?CurrentUser $user): array
    {
        if (!$user) {
            return [false, 'Sign in to take part.'];
        }
        if (!$user->email_verified) {
            return [false, 'Please verify your email address before posting.'];
        }
        $r = $db->one('SELECT forum_restricted_until FROM users WHERE id=?', [$user->id]);
        if ($r && $r['forum_restricted_until'] && $r['forum_restricted_until'] > Util::nowIso()) {
            return [false, 'A moderator has paused your posting until ' . substr($r['forum_restricted_until'], 0, 10) . '.'];
        }
        return [true, null];
    }

    private static function requirePost(Db $db, ?CurrentUser $user): void
    {
        [$ok, $why] = self::canPost($db, $user);
        if (!$ok) {
            throw new ForumError($why);
        }
    }

    public static function isMod(?CurrentUser $user): bool
    {
        return (bool) ($user && $user->can('forum.moderate'));
    }

    // ───────────── reading ─────────────
    public static function categories(Db $db): array
    {
        return $db->all("SELECT c.*, (SELECT COUNT(*) FROM forum_topics t WHERE t.category_id=c.id AND t.status IN ('open','locked','archived')) AS topics, "
            . "(SELECT MAX(t.last_post_at) FROM forum_topics t WHERE t.category_id=c.id AND t.status IN ('open','locked','archived')) AS last "
            . 'FROM forum_categories c WHERE c.is_active=1 ORDER BY c.sort_order, c.title');
    }

    public static function category(Db $db, string $slug): ?array
    {
        return $db->one('SELECT * FROM forum_categories WHERE slug=? AND is_active=1', [$slug]);
    }

    public static function topics(Db $db, int $categoryId, int $page = 1, bool $moderator = false): array
    {
        $statuses = $moderator ? "('open','locked','archived','hidden')" : "('open','locked','archived')";
        $total = (int) $db->val("SELECT COUNT(*) FROM forum_topics WHERE category_id=? AND status IN {$statuses}", [$categoryId]);
        $rows = $db->all('SELECT t.*, u.display_name AS author, u.username AS author_username, u.anonymized_at, '
            . "(SELECT COUNT(*) - 1 FROM forum_posts p WHERE p.topic_id=t.id AND p.status='visible') AS replies "
            . "FROM forum_topics t JOIN users u ON u.id=t.author_id WHERE t.category_id=? AND t.status IN {$statuses} "
            . 'ORDER BY t.is_pinned DESC, COALESCE(t.last_post_at, t.created_at) DESC LIMIT ? OFFSET ?',
            [$categoryId, self::PER_PAGE, (max($page, 1) - 1) * self::PER_PAGE]);
        return [$rows, $total];
    }

    public static function topic(Db $db, string $slug, bool $moderator = false): ?array
    {
        $t = $db->one('SELECT t.*, c.slug AS category_slug, c.title AS category_title FROM forum_topics t '
            . 'JOIN forum_categories c ON c.id=t.category_id WHERE t.slug=?', [$slug]);
        if (!$t || ($t['status'] === 'hidden' && !$moderator)) {
            return null;
        }
        return $t;
    }

    public static function posts(Db $db, int $topicId, int $page = 1, bool $moderator = false): array
    {
        $where = $moderator ? '' : "AND p.status IN ('visible','removed')";
        $total = (int) $db->val("SELECT COUNT(*) FROM forum_posts p WHERE p.topic_id=? {$where}", [$topicId]);
        $rows = $db->all('SELECT p.*, u.display_name AS author, u.username AS author_username, u.anonymized_at FROM forum_posts p '
            . "JOIN users u ON u.id=p.author_id WHERE p.topic_id=? {$where} ORDER BY p.created_at, p.id LIMIT ? OFFSET ?",
            [$topicId, self::PER_PAGE, (max($page, 1) - 1) * self::PER_PAGE]);
        return [$rows, $total];
    }

    public static function search(Db $db, ?string $q, int $limit = 50): array
    {
        $q = mb_substr(Util::squash($q), 0, 100);
        if (mb_strlen($q) < 2) {
            return [];
        }
        $like = '%' . mb_strtolower($q, 'UTF-8') . '%';
        return $db->all('SELECT DISTINCT t.slug, t.title, c.title AS category_title, COALESCE(t.last_post_at, t.created_at) AS at FROM forum_topics t '
            . "JOIN forum_categories c ON c.id=t.category_id LEFT JOIN forum_posts p ON p.topic_id=t.id AND p.status='visible' "
            . "WHERE t.status IN ('open','locked','archived') AND (lower(t.title) LIKE ? OR lower(p.body) LIKE ?) "
            . 'ORDER BY at DESC LIMIT ?', [$like, $like, $limit]);
    }

    public static function canEdit(array $post, ?CurrentUser $user): bool
    {
        if (!$user || $post['author_id'] !== $user->id || $post['status'] !== 'visible') {
            return false;
        }
        $at = \DateTimeImmutable::createFromFormat('Y-m-d\TH:i:s\Z', (string) $post['created_at'], new \DateTimeZone('UTC'));
        return $at && time() - $at->getTimestamp() <= self::EDIT_WINDOW;
    }

    // ───────────── writing ─────────────
    private static function uniqueSlug(Db $db, string $title): string
    {
        $base = Names::slugify($title, 'topic');
        $slug = $base;
        $n = 2;
        while ($db->one('SELECT 1 FROM forum_topics WHERE slug=?', [$slug])) {
            $slug = "{$base}-{$n}";
            $n++;
        }
        return $slug;
    }

    public static function createTopic(Db $db, ?CurrentUser $user, array $cat, ?string $title, ?string $body, ?string $archiveLink = null): string
    {
        self::requirePost($db, $user);
        $title = Util::squash($title);
        $tl = mb_strlen($title, 'UTF-8');
        if ($tl < 4 || $tl > 200) {
            throw new ForumError('Give the topic a title of 4 to 200 characters.');
        }
        $body = self::cleanBody($body);
        if (!RateLimit::allow($db, "forum-topic:{$user->id}", 5, 3600)) {
            throw new ForumError('You have started several topics recently. Please wait a while.');
        }
        $now = Util::nowIso();
        $slug = self::uniqueSlug($db, $title);
        $tid = $db->insert('INSERT INTO forum_topics(category_id, slug, title, author_id, created_at, last_post_at, archive_link) VALUES (?,?,?,?,?,?,?)',
            [$cat['id'], $slug, $title, $user->id, $now, $now, $archiveLink]);
        $db->exec('INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)', [$tid, $user->id, $body, $now]);
        Audit::log($db, $user->id, 'forum.topic_created', 'forum_topic', $tid);
        return $slug;
    }

    public static function reply(Db $db, ?CurrentUser $user, array $t, ?string $body): int
    {
        self::requirePost($db, $user);
        if ($t['status'] !== 'open') {
            throw new ForumError('This topic is closed to new replies.');
        }
        $body = self::cleanBody($body);
        if (!RateLimit::allow($db, "forum-post:{$user->id}", 10, 600)) {
            throw new ForumError('You are posting very quickly. Please wait a few minutes.');
        }
        $now = Util::nowIso();
        $pid = $db->insert('INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)', [$t['id'], $user->id, $body, $now]);
        $db->exec('UPDATE forum_topics SET last_post_at=? WHERE id=?', [$now, $t['id']]);
        // tell the topic's author (if they want to be told, and it is not their own reply)
        $author = $db->one('SELECT id, notify_forum_replies FROM users WHERE id=? AND is_active=1', [$t['author_id']]);
        if ($author && $author['id'] !== $user->id && $author['notify_forum_replies']) {
            $db->exec("INSERT INTO notifications(user_id, kind, message, link) VALUES (?, 'forum.reply', ?, ?)",
                [$author['id'], 'Someone replied to your forum topic.', "/community/topics/{$t['slug']}#post-{$pid}"]);
        }
        return $pid;
    }

    public static function edit(Db $db, ?CurrentUser $user, int $postId, ?string $body): int
    {
        $p = $db->one('SELECT * FROM forum_posts WHERE id=?', [$postId]);
        if (!$p || !self::canEdit($p, $user)) {
            throw new ForumError('You can edit your own posts for 24 hours after posting.');
        }
        self::requirePost($db, $user);
        $body = self::cleanBody($body);
        $db->exec('INSERT INTO forum_post_edits(post_id, previous_body) VALUES (?,?)', [$postId, $p['body']]);
        $db->exec('UPDATE forum_posts SET body=?, edited_at=?, edit_count=edit_count+1 WHERE id=?', [$body, Util::nowIso(), $postId]);
        return (int) $p['topic_id'];
    }

    public static function report(Db $db, ?CurrentUser $user, ?int $postId, ?int $topicId, ?string $category, ?string $reason): void
    {
        if (!$user) {
            throw new ForumError('Sign in to report a post.');
        }
        if (!isset(self::REPORT_CATEGORIES[$category ?? ''])) {
            throw new ForumError('Choose one of the listed options.');
        }
        $reason = mb_substr(Util::squash($reason), 0, 2000);
        if (!RateLimit::allow($db, "forum-report:{$user->id}", 20, 3600)) {
            throw new ForumError('You have sent many reports recently. Please wait a while.');
        }
        $db->exec('INSERT INTO reports(reporter_id, post_id, topic_id, reason, category) VALUES (?,?,?,?,?)',
            [$user->id, $postId, $topicId, $reason !== '' ? $reason : self::REPORT_CATEGORIES[$category], $category]);
        Audit::log($db, $user->id, 'forum.reported', $postId ? 'forum_post' : 'forum_topic', $postId ?: $topicId, ['category' => $category]);
    }

    // ───────────── moderation ─────────────
    private static function log(Db $db, CurrentUser $mod, string $action, string $targetType, int $targetId, ?string $reason): void
    {
        $db->exec('INSERT INTO moderation_actions(moderator_id, action, target_type, target_id, reason) VALUES (?,?,?,?,?)',
            [$mod->id, $action, $targetType, $targetId, $reason]);
        Audit::log($db, $mod->id, "moderation.{$action}", $targetType, $targetId, ['reason' => $reason]);
    }

    private static function modReason(?CurrentUser $mod, ?string $reason): string
    {
        if (!self::isMod($mod)) {
            throw new ForumError('You do not have permission for this action.');
        }
        $reason = mb_substr(Util::squash($reason), 0, 1000);
        if ($reason === '') {
            throw new ForumError('Please record a reason. It is kept in the moderation log.');
        }
        return $reason;
    }

    public static function moderatePost(Db $db, ?CurrentUser $mod, int $postId, ?string $action, ?string $reason): int
    {
        $reason = self::modReason($mod, $reason);
        if (!isset(self::POST_ACTIONS[$action ?? ''])) {
            throw new ForumError('Choose one of the listed options.');
        }
        $p = $db->one('SELECT * FROM forum_posts WHERE id=?', [$postId]);
        if (!$p) {
            throw new ForumError('Post not found.');
        }
        $db->exec('UPDATE forum_posts SET status=? WHERE id=?', [self::POST_ACTIONS[$action], $postId]);
        self::log($db, $mod, "post_{$action}", 'forum_post', $postId, $reason);
        return (int) $p['topic_id'];
    }

    public static function moderateTopic(Db $db, ?CurrentUser $mod, int $topicId, ?string $action, ?string $reason): void
    {
        $reason = self::modReason($mod, $reason);
        if (isset(self::TOPIC_ACTIONS[$action ?? ''])) {
            $db->exec('UPDATE forum_topics SET status=? WHERE id=?', [self::TOPIC_ACTIONS[$action], $topicId]);
        } elseif (in_array($action, ['pin', 'unpin'], true)) {
            $db->exec('UPDATE forum_topics SET is_pinned=? WHERE id=?', [(int) ($action === 'pin'), $topicId]);
        } else {
            throw new ForumError('Choose one of the listed options.');
        }
        self::log($db, $mod, "topic_{$action}", 'forum_topic', $topicId, $reason);
    }

    /** A warning (days=0) or a temporary posting restriction. The member is told, with the reason. */
    public static function warnOrRestrict(Db $db, ?CurrentUser $mod, int $userId, int $days, ?string $reason): void
    {
        $reason = self::modReason($mod, $reason);
        if ($days < 0 || $days > 90) {
            throw new ForumError('A restriction can last at most 90 days.');
        }
        $target = $db->one('SELECT id FROM users WHERE id=?', [$userId]);
        if (!$target || $userId === $mod->id) {
            throw new ForumError('Member not found.');
        }
        if ($days) {
            $until = gmdate(Util::FMT, time() + $days * 86400);
            $db->exec('UPDATE users SET forum_restricted_until=? WHERE id=?', [$until, $userId]);
            $msg = "A moderator has paused your forum posting for {$days} days. Reason: {$reason}";
        } else {
            $msg = "A moderator has sent you a warning about your forum posts. Reason: {$reason}";
        }
        $db->exec("INSERT INTO notifications(user_id, kind, message, link) VALUES (?, 'forum.moderation', ?, '/community/rules')", [$userId, $msg]);
        self::log($db, $mod, $days ? 'restrict' : 'warn', 'user', $userId, $reason);
    }

    public static function resolveReport(Db $db, ?CurrentUser $mod, int $reportId, ?string $status, ?string $note): void
    {
        if (!self::isMod($mod)) {
            throw new ForumError('You do not have permission for this action.');
        }
        if (!in_array($status, ['actioned', 'dismissed', 'escalated'], true)) {
            throw new ForumError('Choose one of the listed options.');
        }
        $r = $db->one('SELECT * FROM reports WHERE id=?', [$reportId]);
        if (!$r) {
            throw new ForumError('Report not found.');
        }
        $note = mb_substr(Util::squash($note), 0, 2000) ?: null;
        $db->exec('UPDATE reports SET status=?, handled_by=?, resolution_note=? WHERE id=?', [$status, $mod->id, $note, $reportId]);
        if ($status === 'escalated') {       // serious matters go to administrators
            foreach ($db->col("SELECT DISTINCT user_id FROM user_roles WHERE role='administrator' AND revoked_at IS NULL") as $uid) {
                $db->exec("INSERT INTO notifications(user_id, kind, message, link) VALUES (?, 'forum.escalated', ?, '/moderation?status=escalated')",
                    [$uid, 'A moderator escalated a forum report to the administrators.']);
            }
        }
        self::log($db, $mod, "report_{$status}", 'report', $reportId, $note);
    }

    public static function reportsQueue(Db $db, string $status = 'open'): array
    {
        return $db->all('SELECT r.*, u.username AS reporter, p.body AS post_body, p.status AS post_status, p.author_id AS post_author_id, '
            . 'pa.username AS post_author, t.title AS topic_title, t.slug AS topic_slug, t.status AS topic_status, '
            . 'COALESCE(t.id, (SELECT topic_id FROM forum_posts WHERE id=r.post_id)) AS tid '
            . 'FROM reports r JOIN users u ON u.id=r.reporter_id LEFT JOIN forum_posts p ON p.id=r.post_id LEFT JOIN users pa ON pa.id=p.author_id '
            . 'LEFT JOIN forum_topics t ON t.id=COALESCE(r.topic_id, p.topic_id) WHERE r.status=? ORDER BY r.id DESC LIMIT 200', [$status]);
    }

    /** Authors who removed their account are shown without personal details. */
    public static function displayName(array $row): string
    {
        return $row['anonymized_at'] ? 'Former member' : (string) $row['author'];
    }
}
