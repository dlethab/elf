"""Oral histories and consent (spec §11).

Consent is recorded per use (record, store, publish the recording, publish the transcript, publish
a translation, quote excerpts, research access, download). Each public element of an interview is
shown only if ITS consent is on record and not revoked, and nothing is shown while an embargo is in
force. "Uploaded" never means "published": a contributor's declaration of consent becomes a consent
record only when an editor confirms, at publication, that they have seen evidence of it.

This module is the single place that answers "may this part of this interview be shown?".
"""
from datetime import date

from . import audit, entities, search
from .timeutil import now_iso
from ..vocab import CONSENT_TYPES


class ConsentError(Exception):
    pass


def consents(db, oh_id):
    """{consent_type: row or None} for the active (unrevoked) consent records."""
    rows = {r["consent_type"]: r for r in db.execute(
        "SELECT c.*, u.username AS recorded_by_name FROM consent_records c LEFT JOIN users u ON u.id=c.recorded_by "
        "WHERE c.oral_history_id=? AND c.revoked_at IS NULL", (oh_id,))}
    return {t: rows.get(t) for t in CONSENT_TYPES}


def embargoed(oh):
    return bool(oh["embargo_until"]) and oh["embargo_until"] > date.today().isoformat()


def allowed(db, oh_id):
    """What may be shown publicly, as a dict of booleans. Embargo overrides everything."""
    oh = db.execute("SELECT * FROM oral_histories WHERE entity_id=?", (oh_id,)).fetchone()
    c = consents(db, oh_id)
    ok = {t: bool(c[t] and c[t]["granted"]) for t in CONSENT_TYPES}
    if embargoed(oh):
        ok = {t: False for t in ok} | {"research_access": ok["research_access"]}
    ok["embargoed"] = embargoed(oh)
    return ok


def should_be_public(db, oh_id):
    a = allowed(db, oh_id)
    return a["publish_recording"] or a["publish_transcript"]


def sync(db, oh_id, actor_id, reason):
    """Bring the record's visibility, its recording and the search index into line with consent."""
    e = entities.get(db, oh_id)
    want = "public" if should_be_public(db, oh_id) else "restricted"
    if e["visibility"] != want and e["visibility"] != "private":
        entities.set_state(db, oh_id, visibility=want, actor_id=actor_id, reason=reason)
    oh = db.execute("SELECT media_item_id FROM oral_histories WHERE entity_id=?", (oh_id,)).fetchone()
    if oh["media_item_id"]:
        from . import photos
        item = entities.get(db, oh["media_item_id"])
        a = db.execute("SELECT rights_status FROM archive_items WHERE entity_id=?", (item["id"],)).fetchone()
        from ..vocab import PUBLIC_RIGHTS
        decision = db.execute("SELECT editor_access FROM submission_photos WHERE result_item_id=?", (item["id"],)).fetchone()
        rec_ok = (allowed(db, oh_id)["publish_recording"] and a["rights_status"] in PUBLIC_RIGHTS
                  and (decision is None or decision["editor_access"] == "public"))     # consent never overrides an editor's "restricted"
        want_item = "public" if rec_ok else "restricted"
        if item["visibility"] != want_item:
            entities.set_state(db, item["id"], visibility=want_item, actor_id=actor_id, reason=reason)
        photos.sync_item_access(db, item["id"])
    search.reindex(db, oh_id)


def after_create(db, oh_id, clean, actor_id, consent_confirmed):
    """At publication: link the records it concerns, and record consent only if an editor confirmed it."""
    for pid in clean.get("related") or []:
        e = entities.get_by_public_id(db, pid)
        if e:
            db.execute("INSERT OR IGNORE INTO oral_history_subjects(oral_history_id, subject_id) VALUES (?,?)", (oh_id, e["id"]))
    if clean.get("interviewee"):
        e = entities.get_by_public_id(db, clean["interviewee"])
        db.execute("INSERT OR IGNORE INTO oral_history_subjects(oral_history_id, subject_id) VALUES (?,?)", (oh_id, e["id"]))
    declared = (clean.get("consents") or {}).get("granted", [])
    if consent_confirmed:
        note = (clean.get("consents") or {}).get("note")
        for t in CONSENT_TYPES:
            db.execute("INSERT INTO consent_records(oral_history_id, consent_type, granted, granted_on, granted_by_text, evidence_note, "
                       "recorded_by) VALUES (?,?,?,?,?,?,?)",
                       (oh_id, t, int(t in declared), None, "Declared by the contributor",
                        ("Confirmed by an editor at publication. " + (note or "")).strip(), actor_id))
    audit.log(db, actor_id, "oral_history.consent_recorded" if consent_confirmed else "oral_history.consent_not_confirmed",
              "oral_history", entities.get(db, oh_id)["public_id"], {"declared": declared, "confirmed": bool(consent_confirmed)})


def set_consent(db, editor, oh_id, consent_type, form):
    """Grant or withdraw one kind of consent, with evidence. The previous record is kept (revoked, not deleted)."""
    if consent_type not in CONSENT_TYPES:
        raise ConsentError("Choose one of the listed options.")
    granted = form.get("granted") == "1"
    evidence = " ".join((form.get("evidence_note") or "").split())[:2000]
    if not evidence:
        raise ConsentError("Record the evidence for this consent decision (for example: signed form dated …, kept in …).")
    on = (form.get("granted_on") or "").strip()[:10] or None
    by = " ".join((form.get("granted_by_text") or "").split())[:200] or None
    db.execute("UPDATE consent_records SET revoked_at=? WHERE oral_history_id=? AND consent_type=? AND revoked_at IS NULL",
               (now_iso(), oh_id, consent_type))
    db.execute("INSERT INTO consent_records(oral_history_id, consent_type, granted, granted_on, granted_by_text, evidence_note, recorded_by) "
               "VALUES (?,?,?,?,?,?,?)", (oh_id, consent_type, int(granted), on, by, evidence, editor.id))
    e = entities.get(db, oh_id)
    entities.add_revision(db, oh_id, editor.id, f"Consent updated: {consent_type.replace('_', ' ')}", reason=evidence)
    audit.log(db, editor.id, "oral_history.consent_changed", "oral_history", e["public_id"],
              {"type": consent_type, "granted": granted, "evidence": evidence})
    sync(db, oh_id, editor.id, f"Consent changed: {consent_type}")


def set_controls(db, editor, oh_id, form):
    """Embargo, transcript review and redaction notes."""
    emb = (form.get("embargo_until") or "").strip()[:10] or None
    if emb:
        try:
            date.fromisoformat(emb)
        except ValueError:
            raise ConsentError("Use a date like 2030-01-31.") from None
    reviewed = int(form.get("transcript_reviewed") == "1")
    notes = (form.get("redaction_notes") or "").strip()[:5000] or None
    reason = " ".join((form.get("reason") or "").split())[:1000]
    if not reason:
        raise ConsentError("Please record a reason. It is kept in the audit log.")
    old = db.execute("SELECT embargo_until, transcript_reviewed, redaction_notes FROM oral_histories WHERE entity_id=?", (oh_id,)).fetchone()
    db.execute("UPDATE oral_histories SET embargo_until=?, transcript_reviewed=?, redaction_notes=? WHERE entity_id=?",
               (emb, reviewed, notes, oh_id))
    entities.add_revision(db, oh_id, editor.id, "Access controls updated", reason=reason)
    audit.log(db, editor.id, "oral_history.controls_changed", "oral_history", entities.get(db, oh_id)["public_id"],
              {"before": dict(old), "after": {"embargo_until": emb, "transcript_reviewed": reviewed}, "reason": reason})
    sync(db, oh_id, editor.id, reason)


def subjects(db, oh_id, public_only=True):
    from .entities import KIND_TABLE, PUBLIC_WHERE, TITLE_COL
    out = []
    q = "SELECT e.* FROM oral_history_subjects s JOIN entities e ON e.id=s.subject_id WHERE s.oral_history_id=?"
    if public_only:
        q += f" AND {PUBLIC_WHERE}"
    for e in db.execute(q + " ORDER BY e.kind, e.id", (oh_id,)).fetchall():
        t = db.execute(f"SELECT {TITLE_COL[e['kind']]} AS t FROM {KIND_TABLE[e['kind']]} WHERE entity_id=?", (e["id"],)).fetchone()
        out.append({"kind": e["kind"], "slug": e["slug"], "public_id": e["public_id"], "title": t["t"]})
    return out
