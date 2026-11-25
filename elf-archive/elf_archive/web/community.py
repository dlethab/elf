"""Community forum (public reading, verified members posting) and moderation. Every action is checked
on the server by services/forum.py; templates only reflect those rules."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..db import get_db, tx
from ..security import login_required, require
from ..services import entities, forum

bp = Blueprint("community", __name__)


def _page():
    try:
        return max(1, min(int(request.args.get("page", 1)), 10000))
    except ValueError:
        return 1


def _mod():
    return forum.is_mod(g.get("user"))


@bp.route("/community")
def index():
    db = get_db()
    recent = db.execute(
        "SELECT t.slug, t.title, c.title AS category_title, COALESCE(t.last_post_at, t.created_at) AS at FROM forum_topics t "
        "JOIN forum_categories c ON c.id=t.category_id WHERE t.status IN ('open','locked','archived') ORDER BY at DESC LIMIT 10").fetchall()
    return render_template("community/index.html", cats=forum.categories(db), recent=recent,
                           can_post=forum.can_post(db, g.get("user")))


@bp.route("/community/rules")
def rules():
    return render_template("community/rules.html")


@bp.route("/community/search")
def search():
    q = (request.args.get("q") or "").strip()[:100]
    return render_template("community/search.html", q=q, rows=forum.search(get_db(), q) if q else None)


@bp.route("/community/c/<slug>")
def category(slug):
    db = get_db()
    cat = forum.category(db, slug) or abort(404)
    rows, total = forum.topics(db, cat["id"], _page(), moderator=_mod())
    return render_template("community/category.html", cat=cat, rows=rows, total=total, page=_page(), per_page=forum.PER_PAGE,
                           can_post=forum.can_post(db, g.get("user")))


@bp.route("/community/c/<slug>/new", methods=["GET", "POST"])
@login_required
def new_topic(slug):
    db = get_db()
    cat = forum.category(db, slug) or abort(404)
    ok, why = forum.can_post(db, g.user)
    link = (request.values.get("about") or "").strip()[:20]
    link = link if link and entities.get_public_by_public_id(db, link) else None
    values, error = {"title": request.form.get("title", ""), "body": request.form.get("body", "")}, None
    if request.method == "POST":
        if request.form.get("website"):
            return redirect(url_for("community.category", slug=slug))
        try:
            with tx(db):
                tslug = forum.create_topic(db, g.user, cat, request.form.get("title"), request.form.get("body"), archive_link=link)
            return redirect(url_for("community.topic", slug=tslug))
        except forum.ForumError as e:
            error = str(e)
    return render_template("community/new_topic.html", cat=cat, values=values, error=error, ok=ok, why=why, link=link), (400 if error else 200)


@bp.route("/community/topics/<slug>")
def topic(slug):
    db = get_db()
    t = forum.topic(db, slug, moderator=_mod()) or abort(404)
    rows, total = forum.posts(db, t["id"], _page(), moderator=_mod())
    edits = {}
    if _mod():
        for r in db.execute("SELECT * FROM forum_post_edits WHERE post_id IN (SELECT id FROM forum_posts WHERE topic_id=?) ORDER BY id",
                            (t["id"],)).fetchall():
            edits.setdefault(r["post_id"], []).append(r)
    linked = None
    if t["archive_link"]:
        e = entities.get_public_by_public_id(db, t["archive_link"])
        linked = {"kind": e["kind"], "slug": e["slug"], "title": entities.title_of(db, e["id"])} if e else None
    return render_template("community/topic.html", t=t, rows=rows, total=total, page=_page(), per_page=forum.PER_PAGE,
                           can_post=forum.can_post(db, g.get("user")), edits=edits, linked=linked,
                           report_categories=forum.REPORT_CATEGORIES, render=forum.render, can_edit=forum.can_edit,
                           display_name=forum.display_name, mod=_mod())


@bp.route("/community/topics/<slug>/reply", methods=["POST"])
@login_required
def reply(slug):
    db = get_db()
    t = forum.topic(db, slug, moderator=_mod()) or abort(404)
    try:
        with tx(db):
            pid = forum.reply(db, g.user, t, request.form.get("body"))
        return redirect(url_for("community.topic", slug=slug, page=request.args.get("last") or None) + f"#post-{pid}")
    except forum.ForumError as e:
        flash(str(e), "error")
        return redirect(url_for("community.topic", slug=slug) + "#reply")


@bp.route("/community/posts/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def edit(pid):
    db = get_db()
    p = db.execute("SELECT p.*, t.slug AS topic_slug FROM forum_posts p JOIN forum_topics t ON t.id=p.topic_id WHERE p.id=?", (pid,)).fetchone()
    if not p or p["author_id"] != g.user.id:
        abort(404)
    error = None
    if request.method == "POST":
        try:
            with tx(db):
                forum.edit(db, g.user, pid, request.form.get("body"))
            flash("Your post has been updated.", "ok")
            return redirect(url_for("community.topic", slug=p["topic_slug"]) + f"#post-{pid}")
        except forum.ForumError as e:
            error = str(e)
    return render_template("community/edit.html", p=p, error=error, body=request.form.get("body", p["body"]),
                           allowed=forum.can_edit(p, g.user)), (400 if error else 200)


@bp.route("/community/report", methods=["POST"])
@login_required
def report():
    db = get_db()
    post_id = request.form.get("post_id", type=int)
    topic_id = request.form.get("topic_id", type=int)
    back = "/community"
    if post_id:
        p = db.execute("SELECT p.topic_id, t.slug FROM forum_posts p JOIN forum_topics t ON t.id=p.topic_id WHERE p.id=?", (post_id,)).fetchone()
        if not p:
            abort(404)
        topic_id, back = None, f"/community/topics/{p['slug']}#post-{post_id}"
    elif topic_id:
        t = db.execute("SELECT slug FROM forum_topics WHERE id=?", (topic_id,)).fetchone() or abort(404)
        back = f"/community/topics/{t['slug']}"
    else:
        abort(400)
    try:
        with tx(db):
            forum.report(db, g.user, post_id, topic_id, request.form.get("category"), request.form.get("reason"))
        flash("Thank you. A moderator will look at your report.", "ok")
    except forum.ForumError as e:
        flash(str(e), "error")
    return redirect(back)


@bp.route("/community/users/<username>")
def profile(username):
    db = get_db()
    u = db.execute("SELECT id, username, display_name, bio, languages, research_interests, created_at, anonymized_at, is_active "
                   "FROM users WHERE username=?", (username,)).fetchone()
    if not u or u["anonymized_at"] or not u["is_active"]:
        abort(404)
    topics = db.execute("SELECT slug, title, created_at FROM forum_topics WHERE author_id=? AND status IN ('open','locked','archived') "
                        "ORDER BY created_at DESC LIMIT 20", (u["id"],)).fetchall()
    n_posts = db.execute("SELECT COUNT(*) FROM forum_posts WHERE author_id=? AND status='visible'", (u["id"],)).fetchone()[0]
    return render_template("community/profile.html", u=u, topics=topics, n_posts=n_posts)


# ───────────── moderation ─────────────
@bp.route("/moderation")
@require("forum.moderate")
def moderation():
    db = get_db()
    status = request.args.get("status", "open")
    if status not in ("open", "actioned", "dismissed", "escalated"):
        status = "open"
    log = db.execute("SELECT m.*, u.username FROM moderation_actions m JOIN users u ON u.id=m.moderator_id ORDER BY m.id DESC LIMIT 50").fetchall()
    restricted = db.execute("SELECT id, username, forum_restricted_until FROM users WHERE forum_restricted_until > strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                            "ORDER BY forum_restricted_until").fetchall()
    return render_template("community/moderation.html", reports=forum.reports_queue(db, status), status=status, log=log,
                           restricted=restricted, report_categories=forum.REPORT_CATEGORIES,
                           counts={s: db.execute("SELECT COUNT(*) FROM reports WHERE status=?", (s,)).fetchone()[0]
                                   for s in ("open", "escalated", "actioned", "dismissed")})


def _moderate(fn, *args, back):
    db = get_db()
    try:
        with tx(db):
            fn(db, g.user, *args)
        flash("Done. The action is recorded in the moderation log.", "ok")
    except forum.ForumError as e:
        flash(str(e), "error")
    return redirect(back)


@bp.route("/moderation/posts/<int:pid>", methods=["POST"])
@require("forum.moderate")
def mod_post(pid):
    p = get_db().execute("SELECT t.slug FROM forum_posts p JOIN forum_topics t ON t.id=p.topic_id WHERE p.id=?", (pid,)).fetchone() or abort(404)
    return _moderate(forum.moderate_post, pid, request.form.get("action"), request.form.get("reason"),
                     back=request.form.get("back") or f"/community/topics/{p['slug']}#post-{pid}")


@bp.route("/moderation/topics/<int:tid>", methods=["POST"])
@require("forum.moderate")
def mod_topic(tid):
    t = get_db().execute("SELECT slug FROM forum_topics WHERE id=?", (tid,)).fetchone() or abort(404)
    return _moderate(forum.moderate_topic, tid, request.form.get("action"), request.form.get("reason"),
                     back=request.form.get("back") or f"/community/topics/{t['slug']}")


@bp.route("/moderation/users/<int:uid>", methods=["POST"])
@require("forum.moderate")
def mod_user(uid):
    return _moderate(forum.warn_or_restrict, uid, request.form.get("days", 0, type=int), request.form.get("reason"),
                     back=request.form.get("back") or "/moderation")


@bp.route("/moderation/reports/<int:rid>", methods=["POST"])
@require("forum.moderate")
def mod_report(rid):
    return _moderate(forum.resolve_report, rid, request.form.get("status"), request.form.get("note"), back="/moderation")
