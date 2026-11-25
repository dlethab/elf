"""Submission lifecycle and publication. This module is the ONLY path from a contribution to a
public record, and every rule is enforced here on the server:

  draft → submitted → under_review → (needs_revision ⇄ submitted) → approved → published
  any pre-approval state → withdrawn (submitter) ;  submitted/under_review/approved → rejected (editor)

Submitters drive draft/needs_revision → submitted and withdrawal. Reviewing, approving and
publishing require editor permissions, and by default an editor cannot review their own submission.
"""
import json

from . import audit, entities, ratelimit, records
from .timeutil import now_iso
from ..db import tx

TRANSITIONS = {
    "draft": {"submitted", "withdrawn"},
    "submitted": {"under_review", "needs_revision", "rejected", "withdrawn"},
    "under_review": {"needs_revision", "approved", "rejected", "withdrawn"},
    "needs_revision": {"submitted", "withdrawn"},
    "approved": {"published", "under_review", "rejected"},
    "published": set(), "rejected": set(), "withdrawn": set(), "superseded": set(),
}
SUBMITTER_MOVES = {("draft", "submitted"), ("needs_revision", "submitted"),
                   ("draft", "withdrawn"), ("submitted", "withdrawn"),
                   ("under_review", "withdrawn"), ("needs_revision", "withdrawn")}
EDITOR_MOVES = {
    ("submitted", "under_review"): "submission.review",
    ("submitted", "needs_revision"): "submission.request_revision",
    ("under_review", "needs_revision"): "submission.request_revision",
    ("submitted", "rejected"): "submission.decide",
    ("under_review", "rejected"): "submission.decide",
    ("approved", "rejected"): "submission.decide",
    ("under_review", "approved"): "submission.decide",
    ("approved", "under_review"): "submission.review",
    ("approved", "published"): "submission.publish",
}
REASON_REQUIRED = {"needs_revision", "rejected"}
CORRECTABLE = ("person", "family", "place", "event", "source", "organization")
PHOTO_KINDS = ("person", "family", "place", "event", "organization", "correction", "oral_history")
EDITABLE = ("draft", "needs_revision")


class WorkflowError(Exception):
    """A user-facing, recoverable problem (shown as a form message)."""


class PermissionDenied(Exception):
    pass


def _get(db, sid):
    return db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()


def _event(db, sid, actor_id, frm, to, message, visible=True):
    db.execute("INSERT INTO submission_events(submission_id, actor_id, from_status, to_status, message, visible_to_submitter) "
               "VALUES (?,?,?,?,?,?)", (sid, actor_id, frm, to, message, int(visible)))


def _require_submit_rights(user, config):
    if not user or not user.can("submission.create"):
        raise PermissionDenied("You do not have permission to submit.")
    if config.get("REQUIRE_EMAIL_VERIFICATION", True) and not user.email_verified:
        raise PermissionDenied("Please verify your email address before submitting.")


def authorize_new(db, user, kind, *, target_public_id=None, family_public_id=None, config):
    """Kind-specific authorization. Returns (target_entity_row|None, family_entity_row|None)."""
    _require_submit_rights(user, config)
    target = family = None
    if kind == "correction":
        target = entities.get_public_by_public_id(db, target_public_id or "")
        if not target or target["kind"] not in CORRECTABLE:
            raise WorkflowError("That record could not be found.")   # never reveals private records
    if kind == "relationship":
        is_editor = user.can("record.view_any")
        if family_public_id:
            family = entities.get_public_by_public_id(db, family_public_id, "family")
        if not family and not is_editor:
            raise PermissionDenied("Relationship proposals are made through a family you represent.")
        if family and not is_editor:
            from . import families
            g = families.active_grant(db, user.id, family["id"])
            if not g or not g["can_propose_tree"]:
                raise PermissionDenied("You are not authorised to propose relationships for this family.")
    if kind == "membership" and not user.can("record.view_any"):
        from . import families
        if not any(f["can_propose_tree"] for f in families.families_for_user(db, user.id)):
            raise PermissionDenied("Family members are proposed by the family's representatives or by editors.")
    return target, family


def scope_for(db, user, kind, data):
    """Data-dependent authorization, re-checked whenever proposed data is saved. Returns the family
    that scopes the proposal (or None). Family representatives may only add members to their own family."""
    if kind != "membership" or user.can("record.view_any"):
        return None
    from . import families
    fam = entities.get_public_by_public_id(db, data.get("family") or "", "family")
    g = families.active_grant(db, user.id, fam["id"]) if fam else None
    if not g or not g["can_propose_tree"]:
        raise PermissionDenied("You are not authorised to propose relationships for this family.")
    return fam


def create(db, user, kind, data, *, target=None, family=None, contributor_note=None, rights_note=None, config,
           bulk=False, import_batch_id=None):
    """Create a DRAFT submission. `data` is already validated JSON-able content."""
    if not bulk and not ratelimit.allow(db, f"submit:{user.id}", 30, 3600):
        raise WorkflowError("You have created many submissions recently. Please wait a while before adding more.")
    family = scope_for(db, user, kind, data) or family
    now = now_iso()
    cur = db.execute(
        "INSERT INTO submissions(kind, target_entity_id, family_scope_id, proposed_data, contributor_note, rights_note, "
        "status, submitter_id, import_batch_id, created_at, updated_at) VALUES (?,?,?,?,?,?, 'draft', ?,?,?,?)",
        (kind, target["id"] if target else None, family["id"] if family else None,
         json.dumps(data, ensure_ascii=False), (contributor_note or "")[:3000] or None,
         (rights_note or "")[:2000] or None, user.id, import_batch_id, now, now))
    sid = cur.lastrowid
    _event(db, sid, user.id, None, "draft", "Draft created")
    audit.log(db, user.id, "submission.created", "submission", sid, {"kind": kind})
    return sid


def update_draft(db, user, sid, data, *, contributor_note=None, rights_note=None):
    with tx(db):
        s = _get(db, sid)
        if not s or s["submitter_id"] != user.id:
            raise PermissionDenied("Not your submission.")
        if s["status"] not in EDITABLE:
            raise WorkflowError("This submission can no longer be edited.")
        scope_for(db, user, s["kind"], data)
        db.execute("UPDATE submissions SET proposed_data=?, contributor_note=?, rights_note=?, updated_at=? WHERE id=?",
                   (json.dumps(data, ensure_ascii=False), (contributor_note or "")[:3000] or None,
                    (rights_note or "")[:2000] or None, now_iso(), sid))


def transition(db, user, sid, to, *, message=None, internal_note=None, consent_confirmed=False, config):
    """Move a submission. Raises PermissionDenied / WorkflowError. Publishing is atomic."""
    message = (message or "").strip()[:3000] or None
    with tx(db):
        s = _get(db, sid)
        if not s:
            raise WorkflowError("Submission not found.")
        frm = s["status"]
        if to not in TRANSITIONS.get(frm, set()):
            raise WorkflowError(f"A submission that is '{frm.replace('_', ' ')}' cannot move to '{to.replace('_', ' ')}'.")
        is_submitter = user.id == s["submitter_id"]
        if (frm, to) in SUBMITTER_MOVES and is_submitter:
            if to == "submitted":
                _require_submit_rights(user, config)
        elif (frm, to) in EDITOR_MOVES:
            if not user.can(EDITOR_MOVES[(frm, to)]):
                raise PermissionDenied("You do not have permission for this action.")
            if is_submitter and not config.get("ALLOW_SELF_REVIEW", False):
                raise PermissionDenied("You cannot review your own submission. Another editor must do this.")
        else:
            raise PermissionDenied("You do not have permission for this action.")
        if to in REASON_REQUIRED and not message:
            raise WorkflowError("Please give a reason; the contributor will see it.")

        now = now_iso()
        updates = {"status": to, "updated_at": now}
        if to == "submitted":
            updates["submitted_at"] = now
            if s["kind"] == "correction":
                if not json.loads(s["proposed_data"]).get("changes") and not _photo_count(db, sid):
                    raise WorkflowError("Change at least one field, add a source, or add a photo before submitting.")
                updates["base_revision"] = entities.latest_revision_number(db, s["target_entity_id"])
        if to == "under_review" and not is_submitter:
            updates["reviewer_id"] = user.id
        if to in ("approved", "rejected", "needs_revision"):
            updates.update(decided_at=now, reviewer_id=user.id, decision_reason=message)
        if to == "published":
            updates.update(published_at=now, reviewer_id=user.id, consent_confirmed=int(bool(consent_confirmed)))
            updates["result_entity_id"] = _publish(db, s, user, bool(consent_confirmed))
        if internal_note and internal_note.strip() and user.can("confidential.view"):
            prior = s["editor_notes"] or ""
            updates["editor_notes"] = (prior + f"\n[{now} {user.username}] {internal_note.strip()[:2000]}").strip()
            _event(db, sid, user.id, frm, frm, "Internal note added", visible=False)
        sets = ", ".join(f"{k}=?" for k in updates)
        db.execute(f"UPDATE submissions SET {sets} WHERE id=?", [*updates.values(), sid])
        _event(db, sid, user.id, frm, to, message)
        audit.log(db, user.id, f"submission.{to}", "submission", sid, {"from": frm})
        _notify(db, s, to)
    return _get(db, sid)


def add_internal_note(db, user, sid, note):
    if not user.can("confidential.view"):
        raise PermissionDenied("You do not have permission for this action.")
    note = (note or "").strip()[:2000]
    if not note:
        raise WorkflowError("The note is empty.")
    with tx(db):
        s = _get(db, sid)
        if not s:
            raise WorkflowError("Submission not found.")
        now = now_iso()
        db.execute("UPDATE submissions SET editor_notes=?, updated_at=? WHERE id=?",
                   (((s["editor_notes"] or "") + f"\n[{now} {user.username}] {note}").strip(), now, sid))
        _event(db, sid, user.id, s["status"], s["status"], "Internal note added", visible=False)


def _recheck_refs(db, kind, data):
    """Referenced places/people must still be public at publish time."""
    for f in records.spec_for(kind, with_sources=False):
        if f.kind == "ref" and data.get(f.name):
            if not entities.get_public_by_public_id(db, data[f.name], f.ref):
                raise WorkflowError(f"“{f.label}” refers to a record that is no longer published. Return the submission for revision.")


def _photo_count(db, sid):
    return db.execute("SELECT COUNT(*) FROM submission_photos WHERE submission_id=?", (sid,)).fetchone()[0]


def _publish(db, s, user, consent_confirmed):
    from . import photos     # local import: photos depends on this module
    data = json.loads(s["proposed_data"])
    kind = s["kind"]
    if kind == "correction":
        target = entities.get(db, s["target_entity_id"])
        if not target or target["publication_status"] != "published" or target["merged_into"] or target["deleted_at"]:
            raise WorkflowError("The record to correct is no longer published.")
        changes = data["changes"]
        if changes:                       # a correction may consist only of photos
            _recheck_refs(db, target["kind"], changes)
            records.apply_correction(db, target, changes, actor_id=user.id, submission_id=s["id"], reason=s["decision_reason"])
        photos.publish_for_submission(db, s, target["id"], user.id)
        return target["id"]
    _recheck_refs(db, kind, data)
    if kind in records.LINK_KINDS:
        try:
            records.APPLY_LINK[kind](db, data, actor_id=user.id, submission_id=s["id"])
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise WorkflowError("This relationship has already been recorded.") from exc
            raise
        return None
    eid = records.apply_new(db, kind, data, actor_id=user.id, submission_id=s["id"], consent_confirmed=consent_confirmed)
    photos.publish_for_submission(db, s, eid, user.id)
    if kind == "oral_history":
        from . import oral
        rec = db.execute("SELECT s.item_id FROM archive_item_subjects s JOIN archive_items a ON a.entity_id=s.item_id "
                         "WHERE s.subject_id=? AND a.media_kind IN ('audio','video') ORDER BY s.item_id LIMIT 1", (eid,)).fetchone()
        if rec:
            db.execute("UPDATE oral_histories SET media_item_id=? WHERE entity_id=?", (rec["item_id"], eid))
        oral.sync(db, eid, user.id, "Published: access follows the recorded consent")
    return eid


_NOTICE = {
    "under_review": "An editor has started reviewing your submission.",
    "needs_revision": "An editor has asked for changes to your submission.",
    "approved": "Your submission was approved and is awaiting publication.",
    "rejected": "Your submission was not accepted.",
    "published": "Your submission has been published.",
}


def _notify(db, s, to):
    if to in _NOTICE and s["submitter_id"]:
        u = db.execute("SELECT notify_submission_updates FROM users WHERE id=?", (s["submitter_id"],)).fetchone()
        if u and u["notify_submission_updates"]:
            db.execute("INSERT INTO notifications(user_id, kind, message, link) VALUES (?,?,?,?)",
                       (s["submitter_id"], f"submission.{to}", _NOTICE[to], f"/dashboard/submissions/{s['id']}"))


# ───────────── reading ─────────────
def get_for_user(db, user, sid):
    """Own submission, or any submission for staff with queue access. Otherwise None."""
    s = _get(db, sid)
    if not s:
        return None
    if s["submitter_id"] == user.id or user.can("queue.view"):
        return s
    return None


def visible_events(db, user, sid, as_staff=False):
    q = ("SELECT ev.*, u.display_name AS actor_name FROM submission_events ev LEFT JOIN users u ON u.id=ev.actor_id "
         "WHERE ev.submission_id=?")
    if not (as_staff and user.can("confidential.view")):
        q += " AND ev.visible_to_submitter=1"
    return db.execute(q + " ORDER BY ev.id", (sid,)).fetchall()


def user_submissions(db, user_id, status=None):
    q, a = "SELECT * FROM submissions WHERE submitter_id=?", [user_id]
    if status:
        q, a = q + " AND status=?", a + [status]
    return db.execute(q + " ORDER BY updated_at DESC, id DESC", a).fetchall()


def queue(db, statuses=("submitted", "under_review", "approved"), kind=None, limit=200, batch=None):
    ph = ",".join("?" * len(statuses))
    q = (f"SELECT s.*, u.display_name AS submitter_name FROM submissions s JOIN users u ON u.id=s.submitter_id "
         f"WHERE s.status IN ({ph})")
    a = list(statuses)
    if kind:
        q, a = q + " AND s.kind=?", a + [kind]
    if batch:
        q, a = q + " AND s.import_batch_id=?", a + [batch]
    return db.execute(q + " ORDER BY COALESCE(s.submitted_at, s.updated_at), s.id LIMIT ?", a + [limit]).fetchall()


def title_for(db, s):
    d = json.loads(s["proposed_data"])
    if s["kind"] == "correction":
        return f"Correction: {entities.title_of(db, s['target_entity_id'])}"
    ref = records.F("x", "x", "ref")
    show = lambda key: records.display_value(db, ref, d.get(key))  # noqa: E731
    if s["kind"] == "relationship":
        return f"{show('person_a')} — {show('person_b')}"
    if s["kind"] == "affiliation":
        return f"{show('person')} — {show('organization')}"
    if s["kind"] == "membership":
        return f"{show('person')} — {show('family')}"
    if s["kind"] == "participation":
        return f"{show('person') if d.get('person') else show('organization')} — {show('event')}"
    return d.get(records.TITLE_FIELD.get(s["kind"], "title")) or "(untitled)"
