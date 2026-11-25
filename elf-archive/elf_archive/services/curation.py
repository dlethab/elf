"""Editorial curation of published records: direct edits, claim-level citations, conflicting
accounts, and the links between records (relationships, memberships, affiliations, participation).

Every change requires a reason (except adding new evidence), writes a revision on each affected
record, and writes an audit entry that keeps the PREVIOUS values, so nothing an editor changes or
removes is lost from the history."""
from . import audit, dates, entities, records, search
from .timeutil import now_iso
from ..vocab import EVIDENCE, RELATIONSHIP_STATUSES, VISIBILITIES


class CurationError(Exception):
    """A user-facing problem (shown as a form message)."""


def _reason(form, required=True):
    r = " ".join((form.get("reason") or "").split())[:1000]
    if required and not r:
        raise CurationError("Please record a reason. It is kept in the audit log.")
    return r or None


def _text(form, name, limit, multiline=False):
    v = (form.get(name) or "").replace("\r\n", "\n")
    v = v.strip() if multiline else " ".join(v.split())
    return v[:limit] or None


# ───────────── direct edits by editors ─────────────
def direct_edit(db, editor, entity, form):
    """Apply an editor's edit immediately (no second review), with a reason. Returns the changed fields."""
    kind = entity["kind"]
    if kind not in records.CORRECTABLE_KINDS:
        raise CurationError("This kind of record cannot be edited here.")
    reason = _reason(form)
    clean, errors = records.validate(db, kind, form, strict_consent=False)
    if errors:
        return None, errors
    changes = records.changed_fields(db, kind, entity["id"], clean)
    if not changes:
        return None, {"form": "Nothing was changed."}
    records.apply_correction(db, entity, changes, actor_id=editor.id, submission_id=None, reason=reason,
                             summary_prefix="Edited by an editor")
    return changes, {}


# ───────────── citations ─────────────
def citation_fields(kind):
    """Which claims a citation can support on this kind of record."""
    out = [("", "General (the record as a whole)")]
    # archive items and collections have no record form: a citation supports the record as a whole
    fields = records.spec_for(kind, with_sources=False) if kind in records.SPECS else []
    out += [(f.name, f.label) for f in fields if f.kind not in ("lines", "refs", "consents")]
    out += [(n, n.capitalize()) for n in ("relationship", "affiliation", "members", "participants") if kind in
            {"relationship": ("person",), "affiliation": ("person",), "members": ("family",),
             "participants": ("event",)}[n]]
    return out


def _citation_values(db, kind, form):
    field = form.get("field_name") or ""
    if field not in {k for k, _ in citation_fields(kind)}:
        raise CurationError("Choose one of the listed options.")
    ev = form.get("evidence_status") or "unverified"
    if ev not in EVIDENCE:
        raise CurationError("Choose one of the listed options.")
    return {"field_name": field or None, "claim_text": _text(form, "claim_text", 1000), "locator": _text(form, "locator", 200),
            "explanation": _text(form, "explanation", 2000, True), "evidence_status": ev,
            "editor_note": _text(form, "editor_note", 2000, True)}


def add_citation(db, editor, entity, form):
    src_pid, err = records.parse_ref(db, form.get("source"), "source")
    if err or not src_pid:
        raise CurationError(err or "Choose a source.")
    src = entities.get_by_public_id(db, src_pid)
    vals = _citation_values(db, entity["kind"], form)
    cur = db.execute("INSERT INTO citations(source_id, target_id, field_name, claim_text, locator, explanation, evidence_status, "
                     "editor_note, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                     (src["id"], entity["id"], vals["field_name"], vals["claim_text"], vals["locator"], vals["explanation"],
                      vals["evidence_status"], vals["editor_note"], editor.id))
    entities.add_revision(db, entity["id"], editor.id, f"Citation added: {entities.title_of(db, src['id'])} "
                                                       f"({EVIDENCE[vals['evidence_status']][0]})")
    audit.log(db, editor.id, "citation.added", entity["kind"], entity["public_id"], {"citation": cur.lastrowid, **vals})
    return cur.lastrowid


def _citation(db, entity, cid):
    c = db.execute("SELECT * FROM citations WHERE id=? AND target_id=?", (cid, entity["id"])).fetchone()
    if not c:
        raise CurationError("Citation not found.")
    return c


def update_citation(db, editor, entity, cid, form):
    old = _citation(db, entity, cid)
    vals = _citation_values(db, entity["kind"], form)
    reason = _reason(form, required=False)
    db.execute("UPDATE citations SET field_name=?, claim_text=?, locator=?, explanation=?, evidence_status=?, editor_note=? WHERE id=?",
               (*vals.values(), cid))
    title = entities.title_of(db, old["source_id"])
    entities.add_revision(db, entity["id"], editor.id, f"Citation assessed: {title} — {EVIDENCE[vals['evidence_status']][0]}", reason=reason)
    audit.log(db, editor.id, "citation.updated", entity["kind"], entity["public_id"],
              {"citation": cid, "before": {k: old[k] for k in vals}, "after": vals, "reason": reason})


def remove_citation(db, editor, entity, cid, form):
    old = _citation(db, entity, cid)
    reason = _reason(form)
    db.execute("DELETE FROM citations WHERE id=?", (cid,))
    entities.add_revision(db, entity["id"], editor.id, f"Citation removed: {entities.title_of(db, old['source_id'])}", reason=reason)
    audit.log(db, editor.id, "citation.removed", entity["kind"], entity["public_id"], {"removed": dict(old), "reason": reason})


# ───────────── conflicting accounts ─────────────
def _account_values(db, form):
    topic, text = _text(form, "topic", 200), _text(form, "account_text", 5000, True)
    if not topic or not text:
        raise CurationError("Give the topic and the account.")
    src_id = None
    if (form.get("source") or "").strip():
        pid, err = records.parse_ref(db, form.get("source"), "source")
        if err:
            raise CurationError(err)
        src_id = entities.get_by_public_id(db, pid)["id"]
    return {"topic": topic, "account_text": text, "attributed_to": _text(form, "attributed_to", 300), "source_id": src_id,
            "basis_note": _text(form, "basis_note", 2000, True), "needs_research": int(form.get("needs_research") == "1"),
            "is_public": int(form.get("is_public") == "1"), "concerns_date": int(form.get("concerns_date") == "1"),
            "concerns_location": int(form.get("concerns_location") == "1")}


def add_account(db, editor, entity, form):
    vals = _account_values(db, form)
    cur = db.execute(f"INSERT INTO conflicting_accounts(entity_id, {', '.join(vals)}, created_by) VALUES (?,{','.join('?' * len(vals))},?)",
                     (entity["id"], *vals.values(), editor.id))
    entities.add_revision(db, entity["id"], editor.id, "Differing account recorded")
    audit.log(db, editor.id, "account.added", entity["kind"], entity["public_id"], {"account": cur.lastrowid, **vals})
    return cur.lastrowid


def update_account(db, editor, entity, aid, form):
    old = db.execute("SELECT * FROM conflicting_accounts WHERE id=? AND entity_id=?", (aid, entity["id"])).fetchone()
    if not old:
        raise CurationError("Account not found.")
    reason = _reason(form)
    vals = _account_values(db, form)
    db.execute(f"UPDATE conflicting_accounts SET {', '.join(f'{k}=?' for k in vals)}, updated_at=?, updated_by=? WHERE id=?",
               (*vals.values(), now_iso(), editor.id, aid))
    entities.add_revision(db, entity["id"], editor.id, "Differing account revised", reason=reason)
    audit.log(db, editor.id, "account.updated", entity["kind"], entity["public_id"],
              {"account": aid, "before": {k: old[k] for k in vals}, "after": vals, "reason": reason})


# ───────────── links between records ─────────────
LINKS = {
    # table: (entity columns, editable fields)
    "relationships": (("person_a_id", "person_b_id"), ("status", "visibility", "notes", "period")),
    "family_memberships": (("family_id", "person_id"), ("visibility", "role_note", "period")),
    "affiliations": (("person_id", "organization_id"), ("evidence_status", "visibility", "role", "notes", "period")),
    "event_participants": (("event_id", "person_id", "organization_id"), ("evidence_status", "role", "notes")),
}


def _link(db, table, link_id):
    if table not in LINKS:
        raise CurationError("Unknown link.")
    row = db.execute(f"SELECT * FROM {table} WHERE id=?", (link_id,)).fetchone()
    if not row:
        raise CurationError("Link not found.")
    return row


def link_entities(row, table):
    return [row[c] for c in LINKS[table][0] if row[c] is not None]


def update_link(db, editor, table, link_id, form):
    old = _link(db, table, link_id)
    reason = _reason(form)
    sets = {}
    for f in LINKS[table][1]:
        if f == "period":
            try:
                sets.update(dates.columns("period", dates.parse(form.get("period") or "")))
            except dates.DateError as e:
                raise CurationError(str(e)) from e
        elif f == "status":
            if form.get("status") not in RELATIONSHIP_STATUSES:
                raise CurationError("Choose one of the listed options.")
            sets["status"] = form["status"]
        elif f == "visibility":
            if form.get("visibility") not in VISIBILITIES:
                raise CurationError("Choose one of the listed options.")
            sets["visibility"] = form["visibility"]
        elif f == "evidence_status":
            if form.get("evidence_status") not in EVIDENCE:
                raise CurationError("Choose one of the listed options.")
            sets["evidence_status"] = form["evidence_status"]
        else:
            sets[f] = _text(form, f, 2000, multiline=(f == "notes"))
    if sets.get("visibility") == "public":
        for eid in link_entities(old, table):
            e = entities.get(db, eid)
            if e["kind"] == "person" and entities.subtype_row(db, eid)["living_status"] == "living" and form.get("consent_confirmed") != "1":
                raise CurationError("This link involves a person recorded as living. Confirm that consent to publish has been obtained.")
    db.execute(f"UPDATE {table} SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), link_id))
    for eid in link_entities(old, table):
        entities.add_revision(db, eid, editor.id, f"Link revised ({table.replace('_', ' ')})", reason=reason)
    audit.log(db, editor.id, "link.updated", table, link_id, {"before": {k: old[k] for k in sets}, "after": sets, "reason": reason})


def remove_link(db, editor, table, link_id, form):
    old = _link(db, table, link_id)
    reason = _reason(form)
    db.execute(f"DELETE FROM {table} WHERE id=?", (link_id,))
    for eid in link_entities(old, table):
        entities.add_revision(db, eid, editor.id, f"Link removed ({table.replace('_', ' ')})", reason=reason)
    audit.log(db, editor.id, "link.removed", table, link_id, {"removed": dict(old), "reason": reason})


def links_for(db, entity):
    """Every link touching a record, for the staff view (including restricted ones)."""
    eid, out = entity["id"], []

    def name(i):
        e = entities.get(db, i)
        return {"id": e["public_id"], "kind": e["kind"], "title": entities.title_of(db, i)} if e else None

    for table, (cols, _) in LINKS.items():
        where = " OR ".join(f"{c}=?" for c in cols)
        for r in db.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY id", (eid,) * len(cols)).fetchall():
            others = [name(r[c]) for c in cols if r[c] is not None and r[c] != eid]
            out.append({"table": table, "row": r, "others": [o for o in others if o],
                        "period": dates.format_date(r["period_start"], r["period_end"], r["period_precision"])
                        if "period_start" in r.keys() else None,
                        "period_input": dates.to_input(r["period_start"], r["period_end"], r["period_precision"])
                        if "period_start" in r.keys() else None})
    return out


def reindex(db, entity_id):
    search.reindex(db, entity_id)
