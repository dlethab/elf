"""Community forum and moderation (spec §13).

Forum posts are community conversation, never archive records: nothing here changes the archive.
Posting needs a verified account that is not under a moderator's restriction. Every moderation
action is written to the append-only moderation log. Hidden topics and posts disappear from public
view; removed posts leave a placeholder so the conversation still reads correctly.
"""
import re
from datetime import datetime, timedelta, timezone

from markupsafe import Markup, escape

from . import audit, ratelimit
from .names import slugify
from .timeutil import now_iso

EDIT_WINDOW = timedelta(hours=24)
MAX_LINKS = 3
PER_PAGE = 30
REPORT_CATEGORIES = {
    "spam": "Spam or advertising", "harassment": "Harassment or abuse", "private_information": "Someone's private information",
    "threat": "A threat or incitement", "misinformation": "Deliberately false information", "copyright": "Copyright infringement",
    "other": "Something else",
}
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)


class ForumError(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def render(body):
    """Plain text → safe HTML: everything is escaped; http(s) links become links that search engines
    are told not to follow; blank lines separate paragraphs."""
    out = []
    for para in re.split(r"\n\s*\n", (body or "").strip()):
        esc = str(escape(para))
        esc = _URL.sub(lambda m: f'<a href="{m.group(0).rstrip(".,;:)")}" rel="nofollow ugc noopener noreferrer">'
                                 f'{m.group(0).rstrip(".,;:)")}</a>' + m.group(0)[len(m.group(0).rstrip(".,;:)")):], esc)
        out.append("<p>" + esc.replace("\n", "<br>") + "</p>")
    return Markup("".join(out))


def _clean_body(body):
    body = (body or "").replace("\r\n", "\n").strip()
    if len(body) < 2:
        raise ForumError("Write a message.")
    if len(body) > 20000:
        raise ForumError("Messages can be at most 20,000 characters.")
    if len(_URL.findall(body)) > MAX_LINKS:
        raise ForumError("A message can contain at most 3 links.")
    return body


def can_post(db, user):
    """(ok, reason). Verified, active, and not under a moderator's restriction."""
    if not user:
        return False, "Sign in to take part."
    if not user.email_verified:
        return False, "Please verify your email address before posting."
    r = db.execute("SELECT forum_restricted_until FROM users WHERE id=?", (user.id,)).fetchone()
    if r and r["forum_restricted_until"] and r["forum_restricted_until"] > now_iso():
        return False, f"A moderator has paused your posting until {r['forum_restricted_until'][:10]}."
    return True, None


def _require_post(db, user):
    ok, why = can_post(db, user)
    if not ok:
        raise ForumError(why)


def is_mod(user):
    return bool(user and user.can("forum.moderate"))


# ───────────── reading ─────────────
def categories(db):
    return db.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM forum_topics t WHERE t.category_id=c.id AND t.status IN ('open','locked','archived')) AS topics, "
        "(SELECT MAX(t.last_post_at) FROM forum_topics t WHERE t.category_id=c.id AND t.status IN ('open','locked','archived')) AS last "
        "FROM forum_categories c WHERE c.is_active=1 ORDER BY c.sort_order, c.title").fetchall()


def category(db, slug):
    return db.execute("SELECT * FROM forum_categories WHERE slug=? AND is_active=1", (slug,)).fetchone()


def topics(db, category_id, page=1, moderator=False):
    statuses = "('open','locked','archived','hidden')" if moderator else "('open','locked','archived')"
    total = db.execute(f"SELECT COUNT(*) FROM forum_topics WHERE category_id=? AND status IN {statuses}", (category_id,)).fetchone()[0]
    rows = db.execute(
        f"SELECT t.*, u.display_name AS author, u.username AS author_username, u.anonymized_at, "
        f"(SELECT COUNT(*) - 1 FROM forum_posts p WHERE p.topic_id=t.id AND p.status='visible') AS replies "
        f"FROM forum_topics t JOIN users u ON u.id=t.author_id WHERE t.category_id=? AND t.status IN {statuses} "
        f"ORDER BY t.is_pinned DESC, COALESCE(t.last_post_at, t.created_at) DESC LIMIT ? OFFSET ?",
        (category_id, PER_PAGE, (max(page, 1) - 1) * PER_PAGE)).fetchall()
    return rows, total


def topic(db, slug, moderator=False):
    t = db.execute("SELECT t.*, c.slug AS category_slug, c.title AS category_title FROM forum_topics t "
                   "JOIN forum_categories c ON c.id=t.category_id WHERE t.slug=?", (slug,)).fetchone()
    if not t or (t["status"] == "hidden" and not moderator):
        return None
    return t


def posts(db, topic_id, page=1, moderator=False):
    where = "" if moderator else "AND p.status IN ('visible','removed')"
    total = db.execute(f"SELECT COUNT(*) FROM forum_posts p WHERE p.topic_id=? {where}", (topic_id,)).fetchone()[0]
    rows = db.execute(
        f"SELECT p.*, u.display_name AS author, u.username AS author_username, u.anonymized_at FROM forum_posts p "
        f"JOIN users u ON u.id=p.author_id WHERE p.topic_id=? {where} ORDER BY p.created_at, p.id LIMIT ? OFFSET ?",
        (topic_id, PER_PAGE, (max(page, 1) - 1) * PER_PAGE)).fetchall()
    return rows, total


def search(db, q, limit=50):
    q = " ".join((q or "").split())[:100]
    if len(q) < 2:
        return []
    like = f"%{q.lower()}%"
    return db.execute(
        "SELECT DISTINCT t.slug, t.title, c.title AS category_title, COALESCE(t.last_post_at, t.created_at) AS at FROM forum_topics t "
        "JOIN forum_categories c ON c.id=t.category_id LEFT JOIN forum_posts p ON p.topic_id=t.id AND p.status='visible' "
        "WHERE t.status IN ('open','locked','archived') AND (lower(t.title) LIKE ? OR lower(p.body) LIKE ?) "
        "ORDER BY at DESC LIMIT ?", (like, like, limit)).fetchall()


def can_edit(post, user):
    return bool(user and post["author_id"] == user.id and post["status"] == "visible"
                and _now() - _parse(post["created_at"]) <= EDIT_WINDOW)


# ───────────── writing ─────────────
def _unique_slug(db, title):
    base = slugify(title, "topic")
    slug, n = base, 2
    while db.execute("SELECT 1 FROM forum_topics WHERE slug=?", (slug,)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_topic(db, user, cat, title, body, archive_link=None):
    _require_post(db, user)
    title = " ".join((title or "").split())
    if not 4 <= len(title) <= 200:
        raise ForumError("Give the topic a title of 4 to 200 characters.")
    body = _clean_body(body)
    if not ratelimit.allow(db, f"forum-topic:{user.id}", 5, 3600):
        raise ForumError("You have started several topics recently. Please wait a while.")
    now = now_iso()
    slug = _unique_slug(db, title)
    cur = db.execute("INSERT INTO forum_topics(category_id, slug, title, author_id, created_at, last_post_at, archive_link) VALUES (?,?,?,?,?,?,?)",
                     (cat["id"], slug, title, user.id, now, now, archive_link))
    db.execute("INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)", (cur.lastrowid, user.id, body, now))
    audit.log(db, user.id, "forum.topic_created", "forum_topic", cur.lastrowid)
    return slug


def reply(db, user, t, body):
    _require_post(db, user)
    if t["status"] != "open":
        raise ForumError("This topic is closed to new replies.")
    body = _clean_body(body)
    if not ratelimit.allow(db, f"forum-post:{user.id}", 10, 600):
        raise ForumError("You are posting very quickly. Please wait a few minutes.")
    now = now_iso()
    cur = db.execute("INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)", (t["id"], user.id, body, now))
    db.execute("UPDATE forum_topics SET last_post_at=? WHERE id=?", (now, t["id"]))
    # tell the topic's author (if they want to be told, and it is not their own reply)
    author = db.execute("SELECT id, notify_forum_replies FROM users WHERE id=? AND is_active=1", (t["author_id"],)).fetchone()
    if author and author["id"] != user.id and author["notify_forum_replies"]:
        db.execute("INSERT INTO notifications(user_id, kind, message, link) VALUES (?, 'forum.reply', ?, ?)",
                   (author["id"], "Someone replied to your forum topic.", f"/community/topics/{t['slug']}#post-{cur.lastrowid}"))
    return cur.lastrowid


def edit(db, user, post_id, body):
    p = db.execute("SELECT * FROM forum_posts WHERE id=?", (post_id,)).fetchone()
    if not p or not can_edit(p, user):
        raise ForumError("You can edit your own posts for 24 hours after posting.")
    _require_post(db, user)
    body = _clean_body(body)
    db.execute("INSERT INTO forum_post_edits(post_id, previous_body) VALUES (?,?)", (post_id, p["body"]))
    db.execute("UPDATE forum_posts SET body=?, edited_at=?, edit_count=edit_count+1 WHERE id=?", (body, now_iso(), post_id))
    return p["topic_id"]


def report(db, user, post_id, topic_id, category, reason):
    if not user:
        raise ForumError("Sign in to report a post.")
    if category not in REPORT_CATEGORIES:
        raise ForumError("Choose one of the listed options.")
    reason = " ".join((reason or "").split())[:2000]
    if not ratelimit.allow(db, f"forum-report:{user.id}", 20, 3600):
        raise ForumError("You have sent many reports recently. Please wait a while.")
    db.execute("INSERT INTO reports(reporter_id, post_id, topic_id, reason, category) VALUES (?,?,?,?,?)",
               (user.id, post_id, topic_id, reason or REPORT_CATEGORIES[category], category))
    audit.log(db, user.id, "forum.reported", "forum_post" if post_id else "forum_topic", post_id or topic_id, {"category": category})


# ───────────── moderation ─────────────
def _log(db, mod, action, target_type, target_id, reason):
    db.execute("INSERT INTO moderation_actions(moderator_id, action, target_type, target_id, reason) VALUES (?,?,?,?,?)",
               (mod.id, action, target_type, target_id, reason))
    audit.log(db, mod.id, f"moderation.{action}", target_type, target_id, {"reason": reason})


POST_ACTIONS = {"hide": "hidden", "remove": "removed", "restore": "visible"}
TOPIC_ACTIONS = {"lock": "locked", "unlock": "open", "archive": "archived", "hide": "hidden", "restore": "open"}


def moderate_post(db, mod, post_id, action, reason):
    if not is_mod(mod):
        raise ForumError("You do not have permission for this action.")
    reason = " ".join((reason or "").split())[:1000]
    if not reason:
        raise ForumError("Please record a reason. It is kept in the moderation log.")
    if action not in POST_ACTIONS:
        raise ForumError("Choose one of the listed options.")
    p = db.execute("SELECT * FROM forum_posts WHERE id=?", (post_id,)).fetchone()
    if not p:
        raise ForumError("Post not found.")
    db.execute("UPDATE forum_posts SET status=? WHERE id=?", (POST_ACTIONS[action], post_id))
    _log(db, mod, f"post_{action}", "forum_post", post_id, reason)
    return p["topic_id"]


def moderate_topic(db, mod, topic_id, action, reason):
    if not is_mod(mod):
        raise ForumError("You do not have permission for this action.")
    reason = " ".join((reason or "").split())[:1000]
    if not reason:
        raise ForumError("Please record a reason. It is kept in the moderation log.")
    if action in TOPIC_ACTIONS:
        db.execute("UPDATE forum_topics SET status=? WHERE id=?", (TOPIC_ACTIONS[action], topic_id))
    elif action in ("pin", "unpin"):
        db.execute("UPDATE forum_topics SET is_pinned=? WHERE id=?", (int(action == "pin"), topic_id))
    else:
        raise ForumError("Choose one of the listed options.")
    _log(db, mod, f"topic_{action}", "forum_topic", topic_id, reason)


def warn_or_restrict(db, mod, user_id, days, reason):
    """A warning (days=0) or a temporary posting restriction. The member is told, with the reason."""
    if not is_mod(mod):
        raise ForumError("You do not have permission for this action.")
    reason = " ".join((reason or "").split())[:1000]
    if not reason:
        raise ForumError("Please record a reason. It is kept in the moderation log.")
    if not 0 <= days <= 90:
        raise ForumError("A restriction can last at most 90 days.")
    target = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not target or user_id == mod.id:
        raise ForumError("Member not found.")
    if days:
        until = (_now() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.execute("UPDATE users SET forum_restricted_until=? WHERE id=?", (until, user_id))
        msg = f"A moderator has paused your forum posting for {days} days. Reason: {reason}"
    else:
        msg = f"A moderator has sent you a warning about your forum posts. Reason: {reason}"
    db.execute("INSERT INTO notifications(user_id, kind, message, link) VALUES (?, 'forum.moderation', ?, '/community/rules')",
               (user_id, msg))
    _log(db, mod, "restrict" if days else "warn", "user", user_id, reason)


def resolve_report(db, mod, report_id, status, note):
    if not is_mod(mod):
        raise ForumError("You do not have permission for this action.")
    if status not in ("actioned", "dismissed", "escalated"):
        raise ForumError("Choose one of the listed options.")
    r = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not r:
        raise ForumError("Report not found.")
    note = " ".join((note or "").split())[:2000] or None
    db.execute("UPDATE reports SET status=?, handled_by=?, resolution_note=? WHERE id=?", (status, mod.id, note, report_id))
    if status == "escalated":       # serious matters go to administrators
        for a in db.execute("SELECT DISTINCT user_id FROM user_roles WHERE role='administrator' AND revoked_at IS NULL").fetchall():
            db.execute("INSERT INTO notifications(user_id, kind, message, link) VALUES (?, 'forum.escalated', ?, '/moderation?status=escalated')",
                       (a["user_id"], "A moderator escalated a forum report to the administrators."))
    _log(db, mod, f"report_{status}", "report", report_id, note)


def reports_queue(db, status="open"):
    return db.execute(
        "SELECT r.*, u.username AS reporter, p.body AS post_body, p.status AS post_status, p.author_id AS post_author_id, "
        "pa.username AS post_author, t.title AS topic_title, t.slug AS topic_slug, t.status AS topic_status, "
        "COALESCE(t.id, (SELECT topic_id FROM forum_posts WHERE id=r.post_id)) AS tid "
        "FROM reports r JOIN users u ON u.id=r.reporter_id LEFT JOIN forum_posts p ON p.id=r.post_id LEFT JOIN users pa ON pa.id=p.author_id "
        "LEFT JOIN forum_topics t ON t.id=COALESCE(r.topic_id, p.topic_id) WHERE r.status=? ORDER BY r.id DESC LIMIT 200", (status,)).fetchall()


def display_name(row):
    """Authors who removed their account are shown without personal details."""
    return "Former member" if row["anonymized_at"] else row["author"]
