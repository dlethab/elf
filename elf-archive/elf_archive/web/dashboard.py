"""Contributor dashboard and contribution forms. Every route checks ownership on the server;
a submission that is not yours returns 404 (it is never confirmed to exist)."""
import json

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for

from ..db import get_db, tx
from ..i18n import gettext as _
from ..security import login_required
from ..services import accounts, duplicates, entities, families, mfa, photos, records, storage, workflow
from ..services.workflow import PermissionDenied, WorkflowError
from ..vocab import CONTRIBUTOR_RIGHTS, KIND_LABELS

bp = Blueprint("dashboard", __name__)

NEW_KINDS = ("person", "family", "place", "event", "organization", "source")


def _cfg(drafting=False):
    cfg = dict(current_app.config)
    if drafting:                       # drafts may be saved before email verification; submitting may not
        cfg["REQUIRE_EMAIL_VERIFICATION"] = False
    return cfg


def _choices(db, kind):
    return {f.name: records.choices_for(db, f) for f in records.spec_for(kind) if records.choices_for(db, f) is not None}


def _own(sid):
    s = get_db().execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
    if not s or s["submitter_id"] != g.user.id:
        abort(404)
    return s


def _form_kind(s):
    if s["kind"] == "correction":
        return entities.get(get_db(), s["target_entity_id"])["kind"]
    return s["kind"]


# ───────────── overview ─────────────
@bp.route("/dashboard")
@login_required
def home():
    db = get_db()
    counts = {r["status"]: r["n"] for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM submissions WHERE submitter_id=? GROUP BY status", (g.user.id,))}
    recent = workflow.user_submissions(db, g.user.id)[:8]
    return render_template("dashboard/home.html", counts=counts, recent=[(s, workflow.title_for(db, s)) for s in recent],
                           fams=families.families_for_user(db, g.user.id), new_kinds=NEW_KINDS, kind_labels=KIND_LABELS,
                           notes=db.execute("SELECT * FROM notifications WHERE user_id=? AND read_at IS NULL ORDER BY id DESC LIMIT 5",
                                            (g.user.id,)).fetchall())


@bp.route("/dashboard/submissions")
@login_required
def submissions():
    db = get_db()
    status = request.args.get("status") or None
    rows = workflow.user_submissions(db, g.user.id, status)
    return render_template("dashboard/submissions.html", rows=[(s, workflow.title_for(db, s)) for s in rows], status=status)


@bp.route("/dashboard/submissions/<int:sid>")
@login_required
def submission(sid, photo_errors=None, photo_values=None, status=200):
    db = get_db()
    s = _own(sid)
    data = json.loads(s["proposed_data"])
    ctx = {"s": s, "title": workflow.title_for(db, s), "events": workflow.visible_events(db, g.user, sid),
           "published": entities.get(db, s["result_entity_id"]) if s["result_entity_id"] else None,
           "photos": photos.list_for_submission(db, sid), "photo_errors": photo_errors or {},
           "photo_values": photo_values or {}, "rights_choices": CONTRIBUTOR_RIGHTS,
           "can_add_photos": s["status"] in workflow.EDITABLE and s["kind"] in workflow.PHOTO_KINDS,
           "takes_photos": s["kind"] in workflow.PHOTO_KINDS,
           "max_photo_mb": current_app.config["MAX_PHOTO_BYTES"] // (1024 * 1024),
           "max_doc_mb": current_app.config["MAX_DOCUMENT_BYTES"] // (1024 * 1024),
           "max_av_mb": current_app.config["MAX_AV_BYTES"] // (1024 * 1024),
           "max_photos": current_app.config["MAX_PHOTOS_PER_SUBMISSION"]}
    if s["kind"] == "correction":
        ctx["diff"] = records.diff(db, _form_kind(s), s["target_entity_id"], data["changes"])
        ctx["target"] = entities.get(db, s["target_entity_id"])
    else:
        ctx["rows"] = records.display_rows(db, s["kind"], data)
    if s["kind"] == "person" and s["status"] in workflow.EDITABLE + ("submitted",):
        cands = duplicates.find_person_candidates(db, [data.get("preferred_name"), data.get("full_name")] + data.get("aliases", []))
        ctx["possible_existing"] = [c for c in cands if entities.get_public_by_public_id(db, c["public_id"], "person")]
    return render_template("dashboard/submission.html", **ctx), status


# ───────────── photos ─────────────
def _wants_json():
    return request.headers.get("X-Upload-Progress") == "1"     # sent by site.js when it shows a progress bar


@bp.route("/dashboard/submissions/<int:sid>/photos", methods=["POST"])
@login_required
def add_photo(sid):
    db = get_db()
    _own(sid)
    f = request.files.get("photo")
    try:
        photos.add(db, storage.from_config(current_app.config), g.user, sid, f.stream if f else b"", f.filename if f else None,
                   request.form, config=current_app.config)
    except photos.PhotoError as e:
        if _wants_json():
            return jsonify(errors={k: _(v) for k, v in e.errors.items()}), 400
        return submission(sid, photo_errors=e.errors, photo_values=request.form, status=400)
    except (PermissionDenied, WorkflowError) as e:
        if _wants_json():
            return jsonify(errors={"photo": _(str(e))}), 400
        flash(str(e), "error")
        return redirect(url_for("dashboard.submission", sid=sid))
    flash("Photo added. It will be seen only by you and the editors unless an editor approves it for publication.", "ok")
    target = url_for("dashboard.submission", sid=sid) + "#photos"
    return jsonify(redirect=target) if _wants_json() else redirect(target)


@bp.route("/dashboard/submissions/<int:sid>/photos/<int:pid>/remove", methods=["POST"])
@login_required
def remove_photo(sid, pid):
    db = get_db()
    _own(sid)
    try:
        photos.remove(db, storage.from_config(current_app.config), g.user, sid, pid)
        flash("Photo removed.", "ok")
    except (PermissionDenied, WorkflowError) as e:
        flash(str(e), "error")
    return redirect(url_for("dashboard.submission", sid=sid) + "#photos")


# ───────────── create / edit ─────────────
def _save(kind, form_kind, *, sid=None, target=None, family=None):
    """Validate the posted form; create or update the draft; optionally submit. Returns (response | None, errors)."""
    db = get_db()
    clean, errors = records.validate(db, form_kind, request.form)
    if not errors and target is not None:
        changes = records.changed_fields(db, form_kind, target["id"], clean)
        # An unchanged correction may be saved as a draft so that photos can be added to it.
        if not changes and request.form.get("action") == "submit" and not (sid and photos.count(db, sid)):
            errors["form"] = "You have not changed anything yet. Edit the fields that are wrong, add a source, or save a draft and add a photo."
        data = {"changes": changes}
    else:
        data = clean
    note, rights = request.form.get("contributor_note"), request.form.get("rights_note")
    if errors:
        return None, errors
    try:
        if sid is None:
            with tx(db):
                sid = workflow.create(db, g.user, kind, data, target=target, family=family,
                                      contributor_note=note, rights_note=rights, config=_cfg())
        else:
            workflow.update_draft(db, g.user, sid, data, contributor_note=note, rights_note=rights)
        if request.form.get("action") == "submit":
            workflow.transition(db, g.user, sid, "submitted", config=_cfg())
            flash("Submitted for editorial review. You will be notified when an editor responds.", "ok")
        else:
            flash("Draft saved. It is visible only to you until you submit it.", "ok")
    except PermissionDenied as e:
        if sid is None:
            return None, {"form": str(e)}
        flash(f"Your draft was saved, but it could not be submitted: {e}", "error")
    except WorkflowError as e:
        if sid is None:
            return None, {"form": str(e)}
        flash(str(e), "error")
    return redirect(url_for("dashboard.submission", sid=sid)), {}


def _form(kind, form_kind, values, errors, *, heading, target=None, family=None, s=None, status=200):
    db = get_db()
    return render_template("dashboard/contribute.html", fields=records.spec_for(form_kind), values=values, errors=errors,
                           choices=_choices(db, form_kind), kind=kind, form_kind=form_kind, heading=heading,
                           target=target, family=family, s=s, kind_label=KIND_LABELS[form_kind],
                           contributor_note=(request.form.get("contributor_note") if request.method == "POST" else (s["contributor_note"] if s else "")) or "",
                           rights_note=(request.form.get("rights_note") if request.method == "POST" else (s["rights_note"] if s else "")) or ""), status


def _prefill(db, kind):
    """Reference fields can be pre-filled from the address, e.g. /contribute/affiliation?person=per-abc12345,
    and a new place's coordinates from the map picker (/contribute/place?latitude=15.3&longitude=38.9).
    Pre-filled coordinates carry no precision: the contributor must still choose one."""
    out = {}
    for f in records.spec_for(kind):
        v = request.args.get(f.name)
        if f.kind == "ref" and v and entities.get_public_by_public_id(db, v, f.ref):
            out[f.name] = records.ref_label(db, v)
    if kind == "place":
        try:
            la, lo = float(request.args.get("latitude", "")), float(request.args.get("longitude", ""))
        except ValueError:
            return out
        if -90 <= la <= 90 and -180 <= lo <= 180:
            out["latitude"], out["longitude"] = f"{la:.5f}", f"{lo:.5f}"
    return out


@bp.route("/contribute/<any(person,family,place,event,source,organization,affiliation,membership,participation,oral_history):kind>",
          methods=["GET", "POST"])
@login_required
def contribute(kind):
    db = get_db()
    try:
        workflow.authorize_new(db, g.user, kind, config=_cfg(drafting=True))
    except PermissionDenied:
        abort(403)
    heading = _("New record: {kind}", kind=_(KIND_LABELS[kind]))
    if request.method == "POST":
        resp, errors = _save(kind, kind)
        if resp:
            return resp
        return _form(kind, kind, request.form, errors, heading=heading, status=400)
    return _form(kind, kind, _prefill(db, kind), {}, heading=heading)


@bp.route("/contribute/correction/<public_id>", methods=["GET", "POST"])
@login_required
def correction(public_id):
    db = get_db()
    try:
        target, _family = workflow.authorize_new(db, g.user, "correction", target_public_id=public_id, config=_cfg(drafting=True))
    except WorkflowError:
        abort(404)
    except PermissionDenied:
        abort(403)
    fk = target["kind"]
    title = entities.title_of(db, target["id"])
    if request.method == "POST":
        resp, errors = _save("correction", fk, target=target)
        if resp:
            return resp
        return _form("correction", fk, request.form, errors, heading=_("Suggest a correction: {title}", title=title), target=target, status=400)
    return _form("correction", fk, records.form_values(records.current_clean(db, fk, target["id"]), fk, db), {},
                 heading=_("Suggest a correction: {title}", title=title), target=target)


@bp.route("/contribute/relationship", methods=["GET", "POST"])
@login_required
def relationship():
    db = get_db()
    fam_pid = request.values.get("family") or None
    try:
        _target, family = workflow.authorize_new(db, g.user, "relationship", family_public_id=fam_pid, config=_cfg(drafting=True))
    except PermissionDenied:
        abort(403)
    heading = _("Propose a family relationship") + (f": {entities.title_of(db, family['id'])}" if family else "")
    if request.method == "POST":
        resp, errors = _save("relationship", "relationship", family=family)
        if resp:
            return resp
        return _form("relationship", "relationship", request.form, errors, heading=heading, family=family, status=400)
    return _form("relationship", "relationship", _prefill(db, "relationship"), {}, heading=heading, family=family)


@bp.route("/dashboard/submissions/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def edit(sid):
    db = get_db()
    s = _own(sid)
    if s["status"] not in workflow.EDITABLE:
        flash("This submission can no longer be edited.", "error")
        return redirect(url_for("dashboard.submission", sid=sid))
    fk = _form_kind(s)
    target = entities.get(db, s["target_entity_id"]) if s["kind"] == "correction" else None
    family = entities.get(db, s["family_scope_id"]) if s["family_scope_id"] else None
    heading = _("Edit: {title}", title=workflow.title_for(db, s))
    if request.method == "POST":
        resp, errors = _save(s["kind"], fk, sid=sid, target=target, family=family)
        if resp:
            return resp
        return _form(s["kind"], fk, request.form, errors, heading=heading, target=target, family=family, s=s, status=400)
    data = json.loads(s["proposed_data"])
    if target is not None:
        base = records.current_clean(db, fk, target["id"])
        base.update(data["changes"])
        data = base
    return _form(s["kind"], fk, records.form_values(data, fk, db), {}, heading=heading, target=target, family=family, s=s)


@bp.route("/dashboard/submissions/<int:sid>/<any(submit,withdraw):action>", methods=["POST"])
@login_required
def act(sid, action):
    db = get_db()
    _own(sid)
    try:
        workflow.transition(db, g.user, sid, "submitted" if action == "submit" else "withdrawn", config=_cfg())
        flash("Submitted for editorial review." if action == "submit" else "Submission withdrawn.", "ok")
    except (PermissionDenied, WorkflowError) as e:
        flash(str(e), "error")
    return redirect(url_for("dashboard.submission", sid=sid))


# ───────────── account ─────────────
@bp.route("/dashboard/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    errors = {}
    if request.method == "POST":
        try:
            with tx(db):
                accounts.update_profile(db, g.user.id, request.form)
            flash("Profile saved.", "ok")
            return redirect(url_for("dashboard.profile"))
        except accounts.AccountError as e:
            errors = e.errors
    u = db.execute("SELECT username, email, display_name, bio, languages, research_interests, attribution_pref, "
                   "notify_submission_updates, notify_forum_replies, email_verified_at FROM users WHERE id=?", (g.user.id,)).fetchone()
    return render_template("dashboard/profile.html", u=u, errors=errors), (400 if errors else 200)


@bp.route("/dashboard/password", methods=["GET", "POST"])
@login_required
def password():
    db = get_db()
    errors = {}
    if request.method == "POST":
        if request.form.get("new_password") != request.form.get("new_password2"):
            errors["new_password2"] = "The passwords do not match."
        else:
            try:
                with tx(db):
                    accounts.change_password(db, g.user.id, request.form.get("current_password"),
                                             request.form.get("new_password"), keep_session_raw=session.get("sid"))
                flash("Password changed. Your other sessions have been signed out.", "ok")
                return redirect(url_for("dashboard.home"))
            except accounts.AccountError as e:
                errors = e.errors
    return render_template("dashboard/password.html", errors=errors), (400 if errors else 200)


@bp.route("/dashboard/security", methods=["GET", "POST"])
@login_required
def security():
    """Two-step sign-in. The new secret is kept in the session until the first code confirms it."""
    db = get_db()
    codes, error = None, None
    if request.method == "POST":
        op = request.form.get("op")
        if op == "start":
            session["mfa_setup"] = mfa.new_secret()
        elif op == "confirm" and session.get("mfa_setup"):
            with tx(db):
                codes = mfa.enable(db, g.user.id, session["mfa_setup"], request.form.get("code"))
            if codes:
                session.pop("mfa_setup", None)
                flash("Two-step sign-in is on.", "ok")
            else:
                error = "That code is not valid. Enter the current code from your app, or one of your recovery codes."
        elif op in ("disable", "codes"):
            with tx(db):
                ok = accounts.authenticate(db, g.user.username, request.form.get("password", ""), request.remote_addr or "?") == g.user.id
                if ok and op == "disable":
                    mfa.disable(db, g.user.id)
                    flash("Two-step sign-in is off.", "ok")
                elif ok:
                    codes = mfa.regenerate_codes(db, g.user.id)
            if not ok:
                error = "That password is not correct."
            elif op == "disable":
                return redirect(url_for("dashboard.security"))
    u = db.execute("SELECT totp_enabled_at FROM users WHERE id=?", (g.user.id,)).fetchone()
    setup = session.get("mfa_setup") if not u["totp_enabled_at"] else None
    return render_template("dashboard/security.html", enabled=bool(u["totp_enabled_at"]), setup=setup, codes=codes, error=error,
                           remaining=mfa.remaining_codes(db, g.user.id),
                           uri=mfa.otpauth_uri(setup, g.user.username) if setup else None,
                           qr=mfa.qr_svg_data_uri(mfa.otpauth_uri(setup, g.user.username)) if setup else None,
                           required=current_app.config.get("REQUIRE_STAFF_MFA") and bool(g.user.roles)), (400 if error else 200)


@bp.route("/dashboard/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    db = get_db()
    if request.method == "POST":
        from ..services.timeutil import now_iso
        db.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL", (now_iso(), g.user.id))
        return redirect(url_for("dashboard.notifications"))
    rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100", (g.user.id,)).fetchall()
    return render_template("dashboard/notifications.html", rows=rows)
