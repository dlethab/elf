"""Editorial queue, review, publication and staff record management. Every route is gated by
security.require(<permission>); the workflow service re-checks permissions on every transition."""
import json

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..db import get_db, tx
from ..security import require, safe_next
from ..services import (audit, collections, curation, duplicates, entities, explorations, families, importer, merging, oral,
                        photos, records, workflow)
from ..services.entities import KIND_TABLE, TITLE_COL
from ..services.workflow import PermissionDenied, WorkflowError
from ..vocab import EVIDENCE, KIND_LABELS, PUBLIC_RIGHTS, RELATIONSHIP_STATUSES, RIGHTS_STATUSES, VISIBILITIES

STAFF_KINDS = ("person", "family", "place", "event", "organization", "source", "archive_item", "collection", "oral_history")

bp = Blueprint("editor", __name__, url_prefix="/editor")

TABS = [("new", "New", ("submitted",)), ("review", "Under review", ("under_review",)),
        ("approved", "Approved, awaiting publication", ("approved",)),
        ("with_contributor", "Returned to contributor", ("needs_revision",)),
        ("decided", "Recently decided", ("published", "rejected"))]


def _flags(db, s):
    """Review aids shown in the queue. They inform; they never decide."""
    out = []
    d = json.loads(s["proposed_data"])
    data = d.get("changes", d)
    if s["kind"] == "person" and data.get("living_status") == "living":
        out.append("Living person: consent needed")
    if s["kind"] == "correction" and data.get("living_status") == "living":
        out.append("Marks person as living")
    if s["kind"] in ("person", "family", "place", "event") and not data.get("sources"):
        out.append("No sources")
    if s["kind"] == "person":
        names = [data.get("preferred_name"), data.get("full_name")] + data.get("aliases", [])
        if duplicates.find_person_candidates(db, names, limit=1):
            out.append("Possible duplicate")
    if s["kind"] == "correction" and s["base_revision"] is not None and \
            entities.latest_revision_number(db, s["target_entity_id"]) > s["base_revision"]:
        out.append("Record changed since submission")
    if s["rights_note"]:
        out.append("Rights/consent note")
    n = photos.count(db, s["id"])
    if n:
        out.append(f"{n} photo{'s' if n != 1 else ''}")
        if photos.pending_count(db, s["id"]) and s["status"] in photos.REVIEW_STATES:
            out.append("Photo decisions needed")
    return out


@bp.route("")
@require("queue.view")
def queue():
    db = get_db()
    tab = request.args.get("tab", "new")
    statuses = dict((k, st) for k, _, st in TABS).get(tab)
    if not statuses:
        abort(404)
    kind = request.args.get("kind") or None
    if kind and kind not in KIND_LABELS:
        kind = None
    try:
        batch = int(request.args.get("batch") or 0) or None
    except ValueError:
        batch = None
    rows = workflow.queue(db, statuses, kind=kind, limit=200, batch=batch)
    if tab == "decided":
        rows = sorted(rows, key=lambda r: r["updated_at"], reverse=True)[:50]
    counts = {k: db.execute(f"SELECT COUNT(*) FROM submissions WHERE status IN ({','.join('?' * len(st))})", st).fetchone()[0]
              for k, _, st in TABS if k != "decided"}
    items = [{"s": s, "title": workflow.title_for(db, s), "flags": _flags(db, s)} for s in rows]
    new_msgs = db.execute("SELECT COUNT(*) FROM contact_messages WHERE status='new'").fetchone()[0]
    batches = db.execute("SELECT id, kind, filename FROM imports WHERE status='created' ORDER BY id DESC LIMIT 50").fetchall()
    return render_template("editor/queue.html", items=items, tab=tab, tabs=TABS, counts=counts, kind=kind, batch=batch,
                           batches=batches, bulk_ok=tab in ("new", "review", "approved") and g.user.can("submission.publish"),
                           kinds=("person", "family", "place", "event", "organization", "source", "relationship",
                                  "affiliation", "membership", "participation", "correction"),
                           new_msgs=new_msgs)


def _staff_submission(sid):
    s = workflow.get_for_user(get_db(), g.user, sid)
    if not s:
        abort(404)
    return s


@bp.route("/submissions/<int:sid>")
@require("submission.review")
def review(sid):
    db = get_db()
    s = _staff_submission(sid)
    d = json.loads(s["proposed_data"])
    ctx = {"s": s, "title": workflow.title_for(db, s), "flags": _flags(db, s),
           "events": workflow.visible_events(db, g.user, sid, as_staff=True),
           "submitter": db.execute("SELECT username, display_name FROM users WHERE id=?", (s["submitter_id"],)).fetchone(),
           "is_own": s["submitter_id"] == g.user.id and not current_app.config["ALLOW_SELF_REVIEW"]}
    data = d
    if s["kind"] == "correction":
        target = entities.get(db, s["target_entity_id"])
        ctx["target"], ctx["target_title"] = target, entities.title_of(db, target["id"])
        ctx["diff"] = records.diff(db, target["kind"], target["id"], d["changes"])
        data = d["changes"]
    else:
        ctx["rows"] = records.display_rows(db, s["kind"], d)
    if s["kind"] == "person" or (s["kind"] == "correction" and ctx["target"]["kind"] == "person"):  # target is set above for corrections
        names = [data.get("preferred_name"), data.get("full_name")] + data.get("aliases", [])
        by = (data.get("birth") or {}).get("start")
        ctx["candidates"] = duplicates.find_person_candidates(
            db, names, birth_year=by[:4] if by else None,
            exclude_entity_id=s["target_entity_id"])
    ctx["needs_consent"] = (s["kind"] == "person" and data.get("living_status") == "living")
    ctx["oral_consent"] = s["kind"] == "oral_history"
    ctx["family"] = entities.get(db, s["family_scope_id"]) if s["family_scope_id"] else None
    ctx["sources"] = data.get("sources") or []
    ctx["photos"] = photos.list_for_submission(db, sid)
    ctx["photo_decidable"] = s["status"] in photos.REVIEW_STATES and not ctx["is_own"]
    ctx["rights_statuses"], ctx["public_rights"] = RIGHTS_STATUSES, PUBLIC_RIGHTS
    return render_template("editor/review.html", **ctx)


@bp.route("/submissions/<int:sid>/photos/<int:pid>", methods=["POST"])
@require("submission.review")
def photo_decision(sid, pid):
    _staff_submission(sid)
    try:
        photos.decide(get_db(), g.user, sid, pid, request.form, config=current_app.config)
        flash("Photo decision saved. It takes effect when the submission is published.", "ok")
    except (PermissionDenied, WorkflowError) as e:
        flash(str(e), "error")
    return redirect(url_for("editor.review", sid=sid) + f"#photo-{pid}")


@bp.route("/submissions/<int:sid>/transition", methods=["POST"])
@require("submission.review")
def transition(sid):
    db = get_db()
    _staff_submission(sid)
    to = request.form.get("to", "")
    try:
        workflow.transition(db, g.user, sid, to, message=request.form.get("message"),
                            internal_note=request.form.get("internal_note"),
                            consent_confirmed=request.form.get("consent_confirmed") == "1",
                            config=current_app.config)
        flash({"under_review": "Review started.", "needs_revision": "Returned to the contributor with your message.",
               "approved": "Approved. It is not public until you publish it.", "rejected": "Rejected. The contributor has been told why.",
               "published": "Published. The record is now part of the archive."}.get(to, "Updated."), "ok")
    except PermissionDenied as e:
        flash(str(e), "error")
    except WorkflowError as e:
        flash(str(e), "error")
    return redirect(url_for("editor.review", sid=sid))


@bp.route("/submissions/<int:sid>/note", methods=["POST"])
@require("confidential.view")
def note(sid):
    _staff_submission(sid)
    try:
        workflow.add_internal_note(get_db(), g.user, sid, request.form.get("internal_note"))
        flash("Internal note added. The contributor cannot see it.", "ok")
    except (PermissionDenied, WorkflowError) as e:
        flash(str(e), "error")
    return redirect(url_for("editor.review", sid=sid))


# ───────────── staff record management ─────────────
@bp.route("/records")
@require("record.view_any")
def records_list():
    db = get_db()
    kind = request.args.get("kind", "person")
    if kind not in STAFF_KINDS:
        abort(404)
    vis = request.args.get("visibility") or None
    q = (request.args.get("q") or "").strip()[:100]
    sql = (f"SELECT e.*, t.{TITLE_COL[kind]} AS title FROM entities e JOIN {KIND_TABLE[kind]} t ON t.entity_id=e.id "
           f"WHERE e.kind=? AND e.deleted_at IS NULL")
    args = [kind]
    if vis in VISIBILITIES:
        sql, args = sql + " AND e.visibility=?", args + [vis]
    if q:
        sql, args = sql + f" AND (t.{TITLE_COL[kind]} LIKE ? OR e.public_id=?)", args + [f"%{q}%", q]
    rows = db.execute(sql + f" ORDER BY lower(t.{TITLE_COL[kind]}) LIMIT 500", args).fetchall()
    return render_template("editor/records.html", rows=rows, kind=kind, vis=vis, q=q)


def _staff_entity(public_id):
    e = entities.get_by_public_id(get_db(), public_id)
    if not e or e["kind"] not in STAFF_KINDS:
        abort(404)
    return e


@bp.route("/records/<public_id>")
@require("record.view_any")
def record(public_id):
    db = get_db()
    e = _staff_entity(public_id)
    sub = entities.subtype_row(db, e["id"])
    revs = db.execute("SELECT r.revision_number, r.change_summary, r.reason, r.created_at, r.submission_id, u.username "
                      "FROM revisions r LEFT JOIN users u ON u.id=r.actor_id WHERE r.entity_id=? ORDER BY r.revision_number DESC",
                      (e["id"],)).fetchall()
    cites = db.execute("SELECT c.*, s.title FROM citations c JOIN sources s ON s.entity_id=c.source_id WHERE c.target_id=? ORDER BY c.id",
                       (e["id"],)).fetchall()
    names = db.execute("SELECT * FROM entity_names WHERE entity_id=? ORDER BY id", (e["id"],)).fetchall()
    reps = families.list_for_family(db, e["id"]) if e["kind"] == "family" else []
    fields = {k: sub[k] for k in sub.keys() if k not in ("entity_id", "kind") and sub[k] not in (None, "")}
    item_files = linked = None
    if e["kind"] == "archive_item":
        item_files = {r["file_role"]: r for r in db.execute("SELECT * FROM media_files WHERE owner_id=?", (e["id"],))}
        linked = db.execute("SELECT s.subject_id, x.public_id, x.kind FROM archive_item_subjects s JOIN entities x ON x.id=s.subject_id "
                            "WHERE s.item_id=?", (e["id"],)).fetchall()
        linked = [(r["public_id"], r["kind"], entities.title_of(db, r["subject_id"])) for r in linked]
    item_photos = db.execute(
        "SELECT x.public_id, a.title, a.access_level, (SELECT storage_key FROM media_files m WHERE m.owner_id=x.id "
        "AND m.file_role='thumbnail') AS thumb_key FROM archive_item_subjects s JOIN entities x ON x.id=s.item_id "
        "JOIN archive_items a ON a.entity_id=x.id WHERE s.subject_id=? ORDER BY x.id", (e["id"],)).fetchall()
    accts = db.execute("SELECT a.*, s.title AS source_title, x.public_id AS source_pid FROM conflicting_accounts a "
                       "LEFT JOIN sources s ON s.entity_id=a.source_id LEFT JOIN entities x ON x.id=a.source_id "
                       "WHERE a.entity_id=? ORDER BY a.id", (e["id"],)).fetchall()
    merged_into = entities.get(db, e["merged_into"]) if e["merged_into"] else None
    extra = {}
    if e["kind"] == "oral_history":
        extra = {"consents": oral.consents(db, e["id"]), "oh": sub, "ok": oral.allowed(db, e["id"])}
    if e["kind"] == "collection":
        extra = {"coll_items": collections.items(db, e["id"], public_only=False), "coll": sub}
    return render_template("editor/record.html", e=e, title=entities.title_of(db, e["id"]), fields=fields, revs=revs,
                           cites=cites, names=names, reps=reps, visibilities=VISIBILITIES,
                           living=(e["kind"] == "person" and sub["living_status"] == "living"),
                           item_files=item_files, linked=linked, item_photos=item_photos,
                           rights_statuses=RIGHTS_STATUSES, public_rights=PUBLIC_RIGHTS, accts=accts,
                           links=curation.links_for(db, e), citation_fields=curation.citation_fields(e["kind"]),
                           editable=e["kind"] in records.CORRECTABLE_KINDS and not e["merged_into"],
                           mergeable=e["kind"] in merging.MERGEABLE and not e["merged_into"],
                           merges=merging.merge_history(db, e["id"]), merged_into=merged_into,
                           source_choices=records.choices_for(db, records.F("source", "Source", "ref", ref="source")),
                           same_kind_choices=records.choices_for(db, records.F("other", "Other", "ref", ref=e["kind"]))
                           if e["kind"] in merging.MERGEABLE else [],
                           EVIDENCE_KEYS=list(EVIDENCE), REL_STATUSES=RELATIONSHIP_STATUSES, **extra)


def _back(public_id):
    return redirect(url_for("editor.record", public_id=public_id) + (request.form.get("anchor") or ""))


def _curate(public_id, fn, *args, ok="Saved.", perm="citation.manage"):
    """Run one curation action in a transaction and report the outcome on the staff record page."""
    if not g.user.can(perm):
        abort(403)
    db = get_db()
    e = _staff_entity(public_id)
    try:
        with tx(db):
            fn(db, g.user, e, *args, request.form)
            curation.reindex(db, e["id"])
        flash(ok, "ok")
    except curation.CurationError as exc:
        flash(str(exc), "error")
    return _back(public_id)


@bp.route("/records/<public_id>/edit", methods=["GET", "POST"])
@require("record.edit")
def record_edit(public_id):
    """Direct editing by an editor: applied immediately, with a reason that is kept in the history."""
    db = get_db()
    e = _staff_entity(public_id)
    if e["kind"] not in records.CORRECTABLE_KINDS or e["merged_into"]:
        abort(404)
    kind, errors = e["kind"], {}
    values = records.form_values(records.current_clean(db, kind, e["id"]), kind, db)
    if request.method == "POST":
        try:
            with tx(db):
                changes, errors = curation.direct_edit(db, g.user, e, request.form)
            if changes:
                flash("Record updated. The change and your reason are in its history.", "ok")
                return redirect(url_for("editor.record", public_id=public_id))
        except curation.CurationError as exc:
            errors = {"reason": str(exc)}
        values = request.form
    choices = {f.name: records.choices_for(db, f) for f in records.spec_for(kind) if records.choices_for(db, f) is not None}
    return render_template("editor/edit.html", e=e, title=entities.title_of(db, e["id"]), fields=records.spec_for(kind),
                           values=values, errors=errors, choices=choices,
                           reason=request.form.get("reason", "")), (400 if errors else 200)


@bp.route("/records/<public_id>/citations", methods=["POST"])
@require("citation.manage")
def citation_add(public_id):
    return _curate(public_id, curation.add_citation, ok="Citation added.")


@bp.route("/records/<public_id>/citations/<int:cid>", methods=["POST"])
@require("citation.manage")
def citation_update(public_id, cid):
    if request.form.get("op") == "remove":
        return _curate(public_id, curation.remove_citation, cid, ok="Citation removed. It is kept in the audit log.")
    return _curate(public_id, curation.update_citation, cid, ok="Citation updated.")


@bp.route("/records/<public_id>/accounts", methods=["POST"])
@require("citation.manage")
def account_add(public_id):
    return _curate(public_id, curation.add_account, ok="Account recorded.")


@bp.route("/records/<public_id>/accounts/<int:aid>", methods=["POST"])
@require("citation.manage")
def account_update(public_id, aid):
    return _curate(public_id, curation.update_account, aid, ok="Account revised. The previous text is kept in the audit log.")


@bp.route("/records/<public_id>/links/<any(relationships,family_memberships,affiliations,event_participants):table>/<int:lid>",
          methods=["POST"])
@require("record.edit")
def link_update(public_id, table, lid):
    db = get_db()
    e = _staff_entity(public_id)
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (lid,)).fetchone()
    if not row or e["id"] not in curation.link_entities(row, table):
        abort(404)
    fn = curation.remove_link if request.form.get("op") == "remove" else curation.update_link
    try:
        with tx(db):
            fn(db, g.user, table, lid, request.form)
        flash("Link removed. It is kept in the audit log." if fn is curation.remove_link else "Link updated.", "ok")
    except curation.CurationError as exc:
        flash(str(exc), "error")
    return _back(public_id)


# ───────────── duplicates and merging ─────────────
@bp.route("/duplicates")
@require("record.merge")
def duplicates_report():
    return render_template("editor/duplicates.html", pairs=merging.duplicate_report(get_db()))


@bp.route("/merge", methods=["GET", "POST"])
@require("record.merge")
def merge():
    db = get_db()
    keep_pid = (request.values.get("keep") or "").strip()
    retire_pid = (request.values.get("retire") or "").strip()
    # the forms let editors type "Name [per-…]"; keep only the permanent id
    for name in ("keep", "retire"):
        v = request.values.get(name) or ""
        m = records._PID_IN_BRACKETS.search(v)
        if m:
            if name == "keep":
                keep_pid = m.group(1)
            else:
                retire_pid = m.group(1)
    try:
        keep, retire, counts = merging.impact(db, keep_pid, retire_pid)
    except merging.MergeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("editor.duplicates_report"))
    if request.method == "POST":
        try:
            merging.merge(db, g.user, keep["public_id"], retire["public_id"], request.form.get("reason"),
                          fill_gaps=request.form.get("fill_gaps") == "1")
            flash(f"Merged. {retire['public_id']} now redirects to this record.", "ok")
            return redirect(url_for("editor.record", public_id=keep["public_id"]))
        except merging.MergeError as exc:
            flash(str(exc), "error")
    side = lambda e: {"e": e, "title": entities.title_of(db, e["id"]),  # noqa: E731
                      "fields": {k: v for k, v in dict(entities.subtype_row(db, e["id"])).items()
                                 if k not in ("entity_id", "kind") and v not in (None, "") and not k.endswith("_kind")},
                      "names": db.execute("SELECT name, name_type FROM entity_names WHERE entity_id=?", (e["id"],)).fetchall()}
    return render_template("editor/merge.html", keep=side(keep), retire=side(retire), counts=counts)


# ───────────── CSV import ─────────────
@bp.route("/import", methods=["GET", "POST"])
@require("import.run")
def import_start():
    db = get_db()
    if request.method == "POST":
        f = request.files.get("file")
        try:
            iid = importer.create_preview(db, g.user, request.form.get("kind"), f.read(importer.MAX_BYTES + 1) if f else b"",
                                          f.filename if f else None)
            return redirect(url_for("editor.import_preview", iid=iid))
        except importer.ImportError_ as exc:
            flash(str(exc), "error")
    recent = db.execute("SELECT i.*, u.username FROM imports i JOIN users u ON u.id=i.created_by ORDER BY i.id DESC LIMIT 20").fetchall()
    return render_template("editor/import.html", kinds=importer.IMPORT_KINDS, recent=recent,
                           columns={k: importer.columns(k) for k in importer.IMPORT_KINDS})


@bp.route("/import/template/<kind>.csv")
@require("import.run")
def import_template(kind):
    if kind not in importer.IMPORT_KINDS:
        abort(404)
    return Response(importer.template_csv(kind), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=elf-archive-{kind}-template.csv"})


@bp.route("/import/<int:iid>", methods=["GET", "POST"])
@require("import.run")
def import_preview(iid):
    db = get_db()
    imp, rows = importer.get(db, iid)
    if not imp:
        abort(404)
    if request.method == "POST":
        try:
            if request.form.get("op") == "discard":
                importer.discard(db, g.user, iid)
                flash("Import discarded. Nothing was created.", "ok")
                return redirect(url_for("editor.import_start"))
            n = importer.confirm(db, g.user, iid, config=current_app.config)
            flash(f"{n} submissions created. They are in the queue for review; nothing is public yet.", "ok")
            return redirect(url_for("editor.queue", tab="new", batch=iid))
        except (importer.ImportError_, WorkflowError, PermissionDenied) as exc:
            flash(str(exc), "error")
    return render_template("editor/import_preview.html", imp=imp, rows=rows)


@bp.route("/bulk", methods=["POST"])
@require("submission.publish")
def bulk():
    db = get_db()
    sids = [int(x) for x in request.form.getlist("sid") if x.isdigit()][:500]
    if request.form.get("action") != "publish" or not sids:
        flash("Select at least one submission.", "error")
        return redirect(safe_next(request.form.get("back"), "/editor"))
    published, failures = importer.bulk_publish(db, g.user, sids, config=current_app.config)
    flash(f"{published} published.", "ok")
    for sid, title, why in failures[:20]:
        flash(f"Not published: {title} (#{sid}) — {why}", "error")
    return redirect(safe_next(request.form.get("back"), "/editor"))


# ───────────── data quality ─────────────
@bp.route("/quality")
@require("record.view_any")
def quality():
    """Records that may need attention. Warnings help editors investigate; nothing is changed automatically."""
    db = get_db()
    live = "e.merged_into IS NULL AND e.deleted_at IS NULL"
    q = lambda sql: db.execute(sql).fetchall()  # noqa: E731
    checks = [
        ("Published records without any citation",
         q(f"SELECT e.public_id, e.kind FROM entities e WHERE {live} AND e.publication_status='published' "
           f"AND e.kind IN ('person','family','place','event','organization') AND NOT EXISTS (SELECT 1 FROM citations c WHERE c.target_id=e.id) "
           f"ORDER BY e.kind, e.id LIMIT 200")),
        ("Citations still marked unverified",
         q(f"SELECT DISTINCT e.public_id, e.kind FROM citations c JOIN entities e ON e.id=c.target_id WHERE {live} "
           f"AND c.evidence_status='unverified' ORDER BY e.kind, e.id LIMIT 200")),
        ("Events without a documented date",
         q(f"SELECT e.public_id, e.kind FROM entities e JOIN events ev ON ev.entity_id=e.id WHERE {live} AND ev.date_precision='unknown' LIMIT 200")),
        ("Events without a place",
         q(f"SELECT e.public_id, e.kind FROM entities e WHERE {live} AND e.kind='event' AND NOT EXISTS "
           f"(SELECT 1 FROM event_places p WHERE p.event_id=e.id) LIMIT 200")),
        ("Places without coordinates",
         q(f"SELECT e.public_id, e.kind FROM entities e JOIN places p ON p.entity_id=e.id WHERE {live} AND p.latitude IS NULL LIMIT 200")),
        ("Records without a description or summary",
         q(f"SELECT e.public_id, e.kind FROM entities e LEFT JOIN people p ON p.entity_id=e.id LEFT JOIN families f ON f.entity_id=e.id "
           f"LEFT JOIN events ev ON ev.entity_id=e.id LEFT JOIN places pl ON pl.entity_id=e.id WHERE {live} AND "
           f"((e.kind='person' AND p.summary IS NULL AND p.biography IS NULL) OR (e.kind='family' AND f.summary IS NULL AND f.narrative IS NULL) "
           f"OR (e.kind='event' AND ev.summary IS NULL AND ev.description IS NULL) OR (e.kind='place' AND pl.overview IS NULL)) LIMIT 200")),
        ("Disputed or uncertain relationships",
         q("SELECT DISTINCT e.public_id, e.kind FROM relationships r JOIN entities e ON e.id=r.person_a_id "
           "WHERE r.status IN ('disputed','uncertain') LIMIT 200")),
        ("Differing accounts marked as needing research",
         q(f"SELECT DISTINCT e.public_id, e.kind FROM conflicting_accounts a JOIN entities e ON e.id=a.entity_id WHERE {live} AND a.needs_research=1 LIMIT 200")),
        ("Photos without rights that allow public display",
         q(f"SELECT e.public_id, e.kind FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE {live} "
           f"AND a.rights_status IN ('rights_unknown','copyrighted_permission_pending') LIMIT 200")),
        ("Living people (kept restricted unless consent is confirmed)",
         q(f"SELECT e.public_id, e.kind FROM entities e JOIN people p ON p.entity_id=e.id WHERE {live} AND p.living_status='living' LIMIT 200")),
        ("Links pointing at a merged record",
         q("SELECT DISTINCT e.public_id, e.kind FROM entities e WHERE e.merged_into IS NOT NULL AND ("
           "EXISTS (SELECT 1 FROM relationships r WHERE r.person_a_id=e.id OR r.person_b_id=e.id) OR "
           "EXISTS (SELECT 1 FROM citations c WHERE c.target_id=e.id)) LIMIT 200")),
    ]
    out = [(label, [(r["public_id"], r["kind"], entities.title_of(db, entities.get_by_public_id(db, r["public_id"])["id"])) for r in rows])
           for label, rows in checks]
    return render_template("editor/quality.html", checks=out)


@bp.route("/records/<public_id>/state", methods=["POST"])
@require("record.restrict")
def record_state(public_id):
    db = get_db()
    e = _staff_entity(public_id)
    vis = request.form.get("visibility")
    status = request.form.get("status") or None
    reason = (request.form.get("reason") or "").strip()[:1000]
    if vis not in VISIBILITIES or status not in (None, "published", "archived"):
        abort(400)
    if not reason:
        flash("Please record a reason. It is kept in the audit log.", "error")
        return redirect(url_for("editor.record", public_id=public_id))
    sub = entities.subtype_row(db, e["id"])
    if e["kind"] == "person" and sub["living_status"] == "living" and vis == "public" and request.form.get("consent_confirmed") != "1":
        flash("This person is recorded as living. Confirm that consent to publish has been obtained.", "error")
        return redirect(url_for("editor.record", public_id=public_id))
    if e["kind"] == "archive_item" and vis == "public" and sub["rights_status"] not in PUBLIC_RIGHTS:
        flash("This item's rights do not allow public display. Update its rights status first.", "error")
        return redirect(url_for("editor.record", public_id=public_id))
    with tx(db):
        entities.set_state(db, e["id"], status=status, visibility=vis, actor_id=g.user.id, reason=reason)
        if e["kind"] == "archive_item":
            photos.sync_item_access(db, e["id"])
    flash("Record access updated.", "ok")
    return redirect(url_for("editor.record", public_id=public_id))


@bp.route("/records/<public_id>/rights", methods=["POST"])
@require("record.restrict")
def record_rights(public_id):
    """Rights of a published archive item. Rights that forbid public display also restrict the item."""
    db = get_db()
    e = _staff_entity(public_id)
    rights = request.form.get("rights_status")
    reason = (request.form.get("reason") or "").strip()[:1000]
    if e["kind"] != "archive_item" or rights not in RIGHTS_STATUSES:
        abort(400)
    if not reason:
        flash("Please record a reason. It is kept in the audit log.", "error")
        return redirect(url_for("editor.record", public_id=public_id))
    holder = " ".join((request.form.get("rights_holder") or "").split())[:300] or None
    with tx(db):
        old = entities.subtype_row(db, e["id"])
        db.execute("UPDATE archive_items SET rights_status=?, rights_holder=? WHERE entity_id=?", (rights, holder, e["id"]))
        audit.log(db, g.user.id, "archive_item.rights_changed", "archive_item", e["public_id"],
                  {"from": old["rights_status"], "to": rights, "reason": reason})
        if rights not in PUBLIC_RIGHTS and e["visibility"] == "public":
            entities.set_state(db, e["id"], visibility="restricted", actor_id=g.user.id,
                               reason=f"Rights changed to {rights}: {reason}")
        else:
            entities.add_revision(db, e["id"], g.user.id, f"Rights changed to {rights.replace('_', ' ')}", reason=reason)
            from ..services import search
            search.reindex(db, e["id"])
        photos.sync_item_access(db, e["id"])
    flash("Rights updated.", "ok")
    return redirect(url_for("editor.record", public_id=public_id))


@bp.route("/records/<public_id>/slug", methods=["POST"])
@require("record.restrict")
def record_slug(public_id):
    db = get_db()
    e = _staff_entity(public_id)
    with tx(db):
        new = entities.change_slug(db, e["id"], request.form.get("slug", ""), g.user.id)
    flash(f"Address changed to “{new}”. The old address redirects here.", "ok")
    return redirect(url_for("editor.record", public_id=public_id))


@bp.route("/families/<public_id>/representatives", methods=["POST"])
@require("family_rep.manage")
def grant_rep(public_id):
    db = get_db()
    e = _staff_entity(public_id)
    if e["kind"] != "family":
        abort(404)
    try:
        with tx(db):
            families.grant(db, g.user.id, request.form.get("username", ""), e["id"],
                           suggest_edits=bool(request.form.get("can_suggest_edits")),
                           propose_tree=bool(request.form.get("can_propose_tree")),
                           submit_media=bool(request.form.get("can_submit_media")))
        flash("Representative added.", "ok")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("editor.record", public_id=public_id))


@bp.route("/families/<public_id>/representatives/<int:gid>/revoke", methods=["POST"])
@require("family_rep.manage")
def revoke_rep(public_id, gid):
    db = get_db()
    e = _staff_entity(public_id)
    grant = db.execute("SELECT * FROM family_representatives WHERE id=? AND family_id=?", (gid, e["id"])).fetchone()
    if not grant:
        abort(404)
    with tx(db):
        families.revoke(db, g.user.id, gid)
    flash("Representative permission revoked.", "ok")
    return redirect(url_for("editor.record", public_id=public_id))


# ───────────── contact messages / public correction requests ─────────────
@bp.route("/messages")
@require("messages.view")
def messages():
    status = "handled" if request.args.get("status") == "handled" else "new"
    rows = get_db().execute("SELECT * FROM contact_messages WHERE status=? ORDER BY id DESC LIMIT 200", (status,)).fetchall()
    return render_template("editor/messages.html", rows=rows, status=status)


@bp.route("/messages/<int:mid>/handled", methods=["POST"])
@require("messages.view")
def message_handled(mid):
    db = get_db()
    with tx(db):
        db.execute("UPDATE contact_messages SET status='handled', handled_by=? WHERE id=?", (g.user.id, mid))
        audit.log(db, g.user.id, "contact.handled", "contact_message", mid)
    return redirect(url_for("editor.messages"))


# ───────────── oral history consent and controls ─────────────
def _oral(public_id):
    e = _staff_entity(public_id)
    if e["kind"] != "oral_history":
        abort(404)
    return e


@bp.route("/records/<public_id>/consent/<consent_type>", methods=["POST"])
@require("record.restrict")
def consent_set(public_id, consent_type):
    db = get_db()
    e = _oral(public_id)
    try:
        with tx(db):
            oral.set_consent(db, g.user, e["id"], consent_type, request.form)
        flash("Consent recorded. What is public now follows this decision.", "ok")
    except oral.ConsentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("editor.record", public_id=public_id) + "#consent")


@bp.route("/records/<public_id>/oral-controls", methods=["POST"])
@require("record.restrict")
def oral_controls(public_id):
    db = get_db()
    e = _oral(public_id)
    try:
        with tx(db):
            oral.set_controls(db, g.user, e["id"], request.form)
        flash("Access controls updated.", "ok")
    except oral.ConsentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("editor.record", public_id=public_id) + "#consent")


# ───────────── curated explorations (the atlas) ─────────────
@bp.route("/explorations", methods=["GET", "POST"])
@require("record.edit")
def exploration_index():
    db = get_db()
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        try:
            with tx(db):
                xid = explorations.create(db, g.user, request.form)
            flash("Exploration saved.", "ok")
            return redirect(url_for("editor.exploration_edit", xid=xid))
        except explorations.ExplorationError as exc:
            flash(str(exc), "error")
    rows = db.execute("SELECT x.id, x.slug, x.title, x.is_published, x.period_from, x.period_to, x.region, x.updated_at, "
                      "(SELECT COUNT(*) FROM exploration_items i WHERE i.exploration_id=x.id) AS n FROM explorations x "
                      "ORDER BY lower(x.title)").fetchall()
    return render_template("editor/explorations.html", rows=rows, x=None, form=form, items=form.get("items", ""))


@bp.route("/explorations/<int:xid>", methods=["GET", "POST"])
@require("record.edit")
def exploration_edit(xid):
    db = get_db()
    x = db.execute("SELECT * FROM explorations WHERE id=?", (xid,)).fetchone()
    if not x:
        abort(404)
    if request.method == "POST":
        try:
            with tx(db):
                if request.form.get("op") == "delete":
                    explorations.delete(db, g.user, xid)
                    flash("Exploration deleted.", "ok")
                    return redirect(url_for("editor.exploration_index"))
                explorations.update(db, g.user, xid, request.form)
            flash("Exploration saved.", "ok")
            return redirect(url_for("editor.exploration_edit", xid=xid))
        except explorations.ExplorationError as exc:
            flash(str(exc), "error")
            return render_template("editor/exploration.html", x=x, form=request.form, items=request.form.get("items", "")), 400
    shown = explorations.public_items(db, xid)
    return render_template("editor/exploration.html", x=x, form=x, items=explorations.form_items(db, xid), shown=shown)


# ───────────── collections ─────────────
@bp.route("/collections", methods=["GET", "POST"])
@require("record.edit")
def collection_index():
    db = get_db()
    if request.method == "POST":
        try:
            with tx(db):
                pid = collections.create(db, g.user, request.form)
            flash("Collection created. Add items to it below.", "ok")
            return redirect(url_for("editor.record", public_id=pid))
        except collections.CollectionError as exc:
            flash(str(exc), "error")
    rows = db.execute("SELECT e.public_id, e.visibility, c.title, c.is_featured, (SELECT COUNT(*) FROM collection_items i WHERE i.collection_id=e.id) AS n "
                      "FROM entities e JOIN collections c ON c.entity_id=e.id WHERE e.deleted_at IS NULL ORDER BY lower(c.title)").fetchall()
    return render_template("editor/collections.html", rows=rows)


def _coll(public_id):
    e = _staff_entity(public_id)
    if e["kind"] != "collection":
        abort(404)
    return e


@bp.route("/records/<public_id>/collection", methods=["POST"])
@require("record.edit")
def collection_update(public_id):
    db = get_db()
    e = _coll(public_id)
    try:
        with tx(db):
            collections.update(db, g.user, e, request.form)
        flash("Collection updated.", "ok")
    except collections.CollectionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("editor.record", public_id=public_id))


@bp.route("/records/<public_id>/collection/items", methods=["POST"])
@require("record.edit")
def collection_items(public_id):
    db = get_db()
    e = _coll(public_id)
    try:
        with tx(db):
            op = request.form.get("op")
            if op == "add":
                collections.add_item(db, g.user, e, request.form)
            elif op in ("up", "down"):
                collections.move_item(db, g.user, e, int(request.form.get("item_id", 0)), op)
            elif op == "remove":
                collections.remove_item(db, g.user, e, int(request.form.get("item_id", 0)))
            else:
                abort(400)
        flash("Collection updated.", "ok")
    except collections.CollectionError as exc:
        flash(str(exc), "error")
    return redirect(url_for("editor.record", public_id=public_id) + "#items")
