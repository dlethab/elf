"""Administration: users and roles, audit log, taxonomies, operational overview.
All counts shown are computed from the database; nothing is estimated."""
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..db import get_db, tx
from ..security import require
from ..services import accounts, audit
from ..services.entities import PUBLIC_WHERE
from ..vocab import ROLES

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _ip():
    return request.remote_addr or "?"


@bp.route("")
@require("admin.overview")
def overview():
    db = get_db()
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
    stats = {
        "pending": one("SELECT COUNT(*) FROM submissions WHERE status IN ('submitted','under_review')"),
        "awaiting_publication": one("SELECT COUNT(*) FROM submissions WHERE status='approved'"),
        "pending_corrections": one("SELECT COUNT(*) FROM submissions WHERE kind='correction' AND status IN ('submitted','under_review','approved')"),
        "public_records": one(f"SELECT COUNT(*) FROM entities e WHERE {PUBLIC_WHERE}"),
        "restricted_records": one("SELECT COUNT(*) FROM entities WHERE visibility<>'public' AND deleted_at IS NULL AND merged_into IS NULL"),
        "no_citations": one(f"SELECT COUNT(*) FROM entities e WHERE {PUBLIC_WHERE} AND e.kind IN ('person','family','place','event') "
                            f"AND NOT EXISTS (SELECT 1 FROM citations c WHERE c.target_id=e.id)"),
        "unknown_dates_events": one(f"SELECT COUNT(*) FROM entities e JOIN events ev ON ev.entity_id=e.id WHERE {PUBLIC_WHERE} AND ev.date_precision='unknown'"),
        "places_no_coords": one(f"SELECT COUNT(*) FROM entities e JOIN places p ON p.entity_id=e.id WHERE {PUBLIC_WHERE} AND p.latitude IS NULL"),
        "living_restricted": one("SELECT COUNT(*) FROM people p JOIN entities e ON e.id=p.entity_id WHERE p.living_status='living' AND e.visibility<>'public'"),
        "users": one("SELECT COUNT(*) FROM users WHERE is_active=1"),
        "unverified": one("SELECT COUNT(*) FROM users WHERE is_active=1 AND email_verified_at IS NULL"),
        "outbox_unsent": one("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL"),
        "outbox_failed": one("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL AND attempts >= ?", accounts.MAX_EMAIL_ATTEMPTS),
        "messages_new": one("SELECT COUNT(*) FROM contact_messages WHERE status='new'"),
        "fictional": one("SELECT COUNT(*) FROM entities WHERE is_fictional_test=1"),
        # community
        "reports_open": one("SELECT COUNT(*) FROM reports WHERE status IN ('open','escalated')"),
        "reports_escalated": one("SELECT COUNT(*) FROM reports WHERE status='escalated'"),
        # media, rights and consent
        "media_files": one("SELECT COUNT(*) FROM media_files WHERE file_role='original'"),
        "media_bytes": one("SELECT COALESCE(SUM(size_bytes),0) FROM media_files"),
        "media_failed": one("SELECT COUNT(*) FROM media_files WHERE processing_status='failed'"),
        "items_rights_unknown": one("SELECT COUNT(*) FROM archive_items a JOIN entities e ON e.id=a.entity_id "
                                    "WHERE a.rights_status='rights_unknown' AND e.deleted_at IS NULL AND e.merged_into IS NULL"),
        "oral_no_consent": one("SELECT COUNT(*) FROM oral_histories o JOIN entities e ON e.id=o.entity_id WHERE e.deleted_at IS NULL "
                               "AND e.merged_into IS NULL AND NOT EXISTS (SELECT 1 FROM consent_records c WHERE c.oral_history_id=o.entity_id "
                               "AND c.revoked_at IS NULL AND c.granted=1 AND c.consent_type IN ('publish_recording','publish_transcript'))"),
        "oral_embargoed": one("SELECT COUNT(*) FROM oral_histories WHERE embargo_until > date('now')"),
        # security
        "staff_without_mfa": one("SELECT COUNT(DISTINCT u.id) FROM users u JOIN user_roles r ON r.user_id=u.id AND r.revoked_at IS NULL "
                                 "WHERE u.is_active=1 AND r.role IN ('editor','moderator','administrator') AND u.totp_enabled_at IS NULL"),
    }
    last = lambda action: db.execute("SELECT created_at FROM audit_logs WHERE action=? ORDER BY id DESC LIMIT 1", (action,)).fetchone()  # noqa: E731
    stats["last_backup"] = (last("system.backup") or [None])[0]
    stats["last_export"] = (last("export.public") or [None])[0]
    recent = db.execute("SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 15").fetchall()
    return render_template("admin/overview.html", stats=stats, recent=recent)


@bp.route("/export", methods=["GET", "POST"])
@require("admin.overview")
def export():
    """Public data export (only what the public site shows). Each download is audited."""
    from flask import Response, current_app
    from ..services import export as ex
    db = get_db()
    if request.method == "POST":
        fictional = request.form.get("include_fictional") == "1" and current_app.config["ENV"] != "production"
        with tx(db):
            data, manifest = ex.export_zip(db, g.user.id, current_app.config["BASE_URL"], include_fictional=fictional)
        name = f"elf-archive-public-{manifest['generated_at'][:10]}.zip"
        return Response(data, mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                                   "Cache-Control": "no-store"})
    counts = ex.build(db)["manifest"]["counts"]
    return render_template("admin/export.html", counts=counts, is_production=current_app.config["ENV"] == "production")


@bp.route("/users")
@require("users.manage")
def users():
    db = get_db()
    q = (request.args.get("q") or "").strip()[:100]
    sql = ("SELECT u.*, (SELECT GROUP_CONCAT(role, ', ') FROM user_roles r WHERE r.user_id=u.id AND r.revoked_at IS NULL) AS roles "
           "FROM users u")
    args = []
    if q:
        sql += " WHERE u.username LIKE ? OR u.email LIKE ? OR u.display_name LIKE ?"
        args = [f"%{q}%"] * 3
    rows = db.execute(sql + " ORDER BY u.id DESC LIMIT 300", args).fetchall()
    return render_template("admin/users.html", rows=rows, q=q)


def _user(uid):
    u = get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        abort(404)
    return u


@bp.route("/users/<int:uid>")
@require("users.manage")
def user(uid):
    db = get_db()
    u = _user(uid)
    sessions = db.execute("SELECT created_at, expires_at, revoked_at, ip, user_agent FROM user_sessions WHERE user_id=? ORDER BY created_at DESC LIMIT 10",
                          (uid,)).fetchall()
    subs = db.execute("SELECT status, COUNT(*) AS n FROM submissions WHERE submitter_id=? GROUP BY status", (uid,)).fetchall()
    return render_template("admin/user.html", u=u, roles=accounts.get_roles(db, uid), all_roles=ROLES, sessions=sessions, subs=subs)


@bp.route("/users/<int:uid>/roles", methods=["POST"])
@require("roles.assign")
def user_roles(uid):
    db = get_db()
    _user(uid)
    role, action = request.form.get("role"), request.form.get("action")
    if role not in ROLES or action not in ("grant", "revoke"):
        abort(400)
    try:
        with tx(db):
            (accounts.grant_role if action == "grant" else accounts.revoke_role)(db, g.user.id, uid, role, _ip())
        flash(f"Role “{role}” {'granted' if action == 'grant' else 'revoked'}.", "ok")
    except accounts.AccountError as e:
        flash(" ".join(e.errors.values()), "error")
    return redirect(url_for("admin.user", uid=uid))


@bp.route("/users/<int:uid>/<any(deactivate,reactivate,anonymize,verify,reset_mfa):action>", methods=["POST"])
@require("users.manage")
def user_action(uid, action):
    db = get_db()
    _user(uid)
    try:
        with tx(db):
            if action == "reset_mfa":           # lost phone: the user signs in with their password and sets it up again
                from ..services import mfa
                mfa.disable(db, uid, actor_id=g.user.id)
                accounts.revoke_all_sessions(db, uid)
            elif action == "verify":
                from ..services.timeutil import now_iso
                db.execute("UPDATE users SET email_verified_at=? WHERE id=? AND email_verified_at IS NULL", (now_iso(), uid))
                audit.log(db, g.user.id, "account.verified_by_admin", "user", uid, ip=_ip())
            else:
                getattr(accounts, action)(db, g.user.id, uid, _ip())
        flash({"deactivate": "Account deactivated and signed out everywhere.", "reactivate": "Account reactivated.",
               "anonymize": "Account anonymised. Contribution history is kept without personal details.",
               "verify": "Email marked as verified.",
               "reset_mfa": "Two-step sign-in reset and sessions ended. The user can set it up again after signing in."}[action], "ok")
    except accounts.AccountError as e:
        flash(" ".join(e.errors.values()), "error")
    return redirect(url_for("admin.user", uid=uid))


@bp.route("/audit")
@require("audit.view")
def audit_log():
    db = get_db()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    action = (request.args.get("action") or "").strip()[:60]
    sql, args = "SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id", []
    if action:
        sql, args = sql + " WHERE a.action LIKE ?", [action + "%"]
    total = db.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    rows = db.execute(sql + " ORDER BY a.id DESC LIMIT 100 OFFSET ?", args + [(page - 1) * 100]).fetchall()
    return render_template("admin/audit.html", rows=rows, total=total, page=page, action=action)


@bp.route("/taxonomies", methods=["GET", "POST"])
@require("settings.manage")
def taxonomies():
    db = get_db()
    tables = {"place": "place_types", "event": "event_types"}
    if request.method == "POST":
        table = tables.get(request.form.get("which"))
        if not table:
            abort(400)
        if request.form.get("op") == "toggle":
            with tx(db):
                db.execute(f"UPDATE {table} SET is_active=1-is_active WHERE id=?", (request.form.get("id"),))
                audit.log(db, g.user.id, "taxonomy.toggled", table, request.form.get("id"))
        else:
            label = " ".join((request.form.get("label") or "").split())[:80]
            slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40]
            if not label or not slug:
                flash("Enter a label.", "error")
            elif db.execute(f"SELECT 1 FROM {table} WHERE slug=?", (slug,)).fetchone():
                flash("A category with that name already exists.", "error")
            else:
                with tx(db):
                    db.execute(f"INSERT INTO {table}(slug, label, sort_order) VALUES (?,?,500)", (slug, label))
                    audit.log(db, g.user.id, "taxonomy.added", table, slug, {"label": label})
                flash(f"Added “{label}”.", "ok")
        return redirect(url_for("admin.taxonomies"))
    return render_template("admin/taxonomies.html",
                           place=db.execute("SELECT * FROM place_types ORDER BY sort_order, label").fetchall(),
                           event=db.execute("SELECT * FROM event_types ORDER BY sort_order, label").fetchall())
