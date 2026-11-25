"""Merging duplicate records (spec §6.4).

A merge is always an editor's decision with a recorded reason; similarity scores only suggest
candidates. The record that is kept ("canonical") keeps its permanent id and address. The retired
record is NOT deleted: it becomes a tombstone pointing at the canonical record, so its old address
and permanent id keep working (they redirect). Every name, citation, account, link and photo is
moved to the canonical record in one transaction; links that would become duplicates or
self-links are dropped and listed in the merge log. Both records get a revision, and the full
before-state of the retired record stays in its (append-only) revision history.
"""
import json

from . import audit, duplicates, entities, search
from .timeutil import now_iso
from ..db import tx
from ..vocab import DIRECTED_RELATIONSHIPS

MERGEABLE = ("person", "family", "place", "event", "organization", "source")


class MergeError(Exception):
    pass


def _check(db, keep_pid, retire_pid):
    keep, retire = entities.get_by_public_id(db, keep_pid or ""), entities.get_by_public_id(db, retire_pid or "")
    if not keep or not retire:
        raise MergeError("Both records must exist.")
    if keep["id"] == retire["id"]:
        raise MergeError("Choose two different records.")
    if keep["kind"] != retire["kind"] or keep["kind"] not in MERGEABLE:
        raise MergeError("Only two records of the same kind can be merged.")
    for e in (keep, retire):
        if e["merged_into"] or e["deleted_at"]:
            raise MergeError("One of these records has already been merged or removed.")
    return keep, retire


# (table, column) pairs that can point at an entity, with the uniqueness rule that a move must respect.
_SIMPLE_REFS = [
    ("citations", "target_id"), ("citations", "source_id"), ("conflicting_accounts", "entity_id"),
    ("conflicting_accounts", "source_id"), ("people", "birth_place_id"), ("people", "death_place_id"),
    ("affiliations", "person_id"), ("affiliations", "organization_id"), ("affiliations", "place_id"),
    ("place_alt_locations", "place_id"), ("oral_histories", "interviewee_id"), ("media_files", "owner_id"),
    ("submissions", "family_scope_id"),
]
# Link tables with a uniqueness rule: if the canonical record already has the same link, the
# retired record's copy is dropped (and logged) instead of moved.
_UNIQUE_LINKS = [
    ("family_memberships", "family_id", "person_id"), ("family_memberships", "person_id", "family_id"),
    ("event_places", "event_id", "place_id"), ("event_places", "place_id", "event_id"),
    ("event_participants", "event_id", "person_id"), ("event_participants", "event_id", "organization_id"),
    ("event_participants", "person_id", "event_id"), ("event_participants", "organization_id", "event_id"),
    ("archive_item_subjects", "subject_id", "item_id"),
    ("collection_items", "collection_id", "item_id"),
]


def impact(db, keep_pid, retire_pid):
    """What a merge would move: counts per kind of link (shown on the preview page)."""
    keep, retire = _check(db, keep_pid, retire_pid)
    rid, out = retire["id"], {}
    for table, col in _SIMPLE_REFS:
        n = db.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (rid,)).fetchone()[0]
        if n:
            out[f"{table}.{col}"] = n
    for table, col, _ in _UNIQUE_LINKS:
        n = db.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (rid,)).fetchone()[0]
        if n:
            out[f"{table}.{col}"] = n
    n = db.execute("SELECT COUNT(*) FROM relationships WHERE person_a_id=? OR person_b_id=?", (rid, rid)).fetchone()[0]
    if n:
        out["relationships"] = n
    n = db.execute("SELECT COUNT(*) FROM entity_names WHERE entity_id=?", (rid,)).fetchone()[0]
    out["names"] = n
    pending = db.execute("SELECT COUNT(*) FROM submissions WHERE target_entity_id=? AND status IN "
                         "('draft','submitted','under_review','needs_revision','approved')", (rid,)).fetchone()[0]
    if pending:
        out["pending corrections"] = pending
    return keep, retire, out


def _fill_gaps(db, keep, retire):
    """Copy values the kept record lacks from the retired one (dates as a whole group). Returns fields filled."""
    table = entities.KIND_TABLE[keep["kind"]]
    k, r = entities.subtype_row(db, keep["id"]), entities.subtype_row(db, retire["id"])
    cols, filled = {}, []
    date_prefixes = {c[:-len("_precision")] for c in k.keys() if c.endswith("_precision") and c != "coord_precision"}
    for p in date_prefixes:
        if k[f"{p}_precision"] == "unknown" and r[f"{p}_precision"] != "unknown":
            cols.update({f"{p}_{s}": r[f"{p}_{s}"] for s in ("start", "end", "precision", "note")})
            filled.append(p)
    skip = {"entity_id", "kind"} | {f"{p}_{s}" for p in date_prefixes for s in ("start", "end", "precision", "note")}
    skip |= {"latitude", "longitude", "coord_precision"}
    if "latitude" in k.keys() and k["latitude"] is None and r["latitude"] is not None:   # coordinates move as a set
        cols.update(latitude=r["latitude"], longitude=r["longitude"], coord_precision=r["coord_precision"])
        filled.append("coordinates")
    for c in k.keys():
        if c in skip or c.endswith("_kind"):
            continue
        if k[c] in (None, "") and r[c] not in (None, ""):
            if c == "living_status":
                continue
            cols[c] = r[c]
            filled.append(c)
    if keep["kind"] == "person" and k["living_status"] == "unknown" and r["living_status"] != "unknown":
        cols["living_status"] = r["living_status"]
        filled.append("living_status")
    if cols:
        db.execute(f"UPDATE {table} SET {', '.join(f'{c}=?' for c in cols)} WHERE entity_id=?", (*cols.values(), keep["id"]))
    return filled


def merge(db, editor, keep_pid, retire_pid, reason, *, fill_gaps=True):
    reason = " ".join((reason or "").split())[:1000]
    if not reason:
        raise MergeError("Please record why these are the same. The reason is kept with the merge.")
    with tx(db):
        keep, retire = _check(db, keep_pid, retire_pid)
        kid, rid, log = keep["id"], retire["id"], {"dropped": [], "moved": {}}

        # names: everything the retired record was called stays searchable on the kept one
        for n in db.execute("SELECT * FROM entity_names WHERE entity_id=?", (rid,)).fetchall():
            ntype = "alternate_spelling" if n["name_type"] == "preferred" else n["name_type"]
            entities.add_name(db, kid, n["name"], ntype, language=n["language"], note=n["note"])

        for table, col in _SIMPLE_REFS:
            cur = db.execute(f"UPDATE {table} SET {col}=? WHERE {col}=?", (kid, rid))
            if cur.rowcount:
                log["moved"][f"{table}.{col}"] = cur.rowcount

        for table, col, other in _UNIQUE_LINKS:
            for row in db.execute(f"SELECT rowid AS rid_, * FROM {table} WHERE {col}=?", (rid,)).fetchall():
                if row[other] is None:
                    continue
                clash = db.execute(f"SELECT 1 FROM {table} WHERE {col}=? AND {other}=?", (kid, row[other])).fetchone()
                if clash or row[other] == kid:
                    db.execute(f"DELETE FROM {table} WHERE rowid=?", (row["rid_"],))
                    log["dropped"].append({"table": table, "row": {k: row[k] for k in row.keys() if k != "rid_"}})
                else:
                    db.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (kid, row["rid_"]))
                    log["moved"][f"{table}.{col}"] = log["moved"].get(f"{table}.{col}", 0) + 1

        for r in db.execute("SELECT * FROM relationships WHERE person_a_id=? OR person_b_id=?", (rid, rid)).fetchall():
            a = kid if r["person_a_id"] == rid else r["person_a_id"]
            b = kid if r["person_b_id"] == rid else r["person_b_id"]
            if r["relationship_type"] not in DIRECTED_RELATIONSHIPS and a > b:
                a, b = b, a
            clash = db.execute("SELECT 1 FROM relationships WHERE person_a_id=? AND person_b_id=? AND relationship_type=? AND id<>?",
                               (a, b, r["relationship_type"], r["id"])).fetchone()
            if a == b or clash:
                db.execute("DELETE FROM relationships WHERE id=?", (r["id"],))
                log["dropped"].append({"table": "relationships", "row": dict(r)})
            else:
                db.execute("UPDATE relationships SET person_a_id=?, person_b_id=? WHERE id=?", (a, b, r["id"]))
                log["moved"]["relationships"] = log["moved"].get("relationships", 0) + 1

        # family representatives of a retired family now represent the kept one (one active grant each)
        for gr in db.execute("SELECT * FROM family_representatives WHERE family_id=? AND revoked_at IS NULL", (rid,)).fetchall():
            if db.execute("SELECT 1 FROM family_representatives WHERE family_id=? AND user_id=? AND revoked_at IS NULL",
                          (kid, gr["user_id"])).fetchone():
                db.execute("UPDATE family_representatives SET revoked_at=?, revoked_by=? WHERE id=?", (now_iso(), editor.id, gr["id"]))
            else:
                db.execute("UPDATE family_representatives SET family_id=? WHERE id=?", (kid, gr["id"]))

        # pending corrections now apply to the kept record; editors are told why
        for s in db.execute("SELECT id, editor_notes FROM submissions WHERE target_entity_id=? AND status IN "
                            "('draft','submitted','under_review','needs_revision','approved')", (rid,)).fetchall():
            note = f"[{now_iso()} {editor.username}] Target {retire['public_id']} was merged into {keep['public_id']}; check the proposed changes against the kept record."
            db.execute("UPDATE submissions SET target_entity_id=?, editor_notes=? WHERE id=?",
                       (kid, ((s["editor_notes"] or "") + "\n" + note).strip(), s["id"]))

        filled = _fill_gaps(db, keep, retire) if fill_gaps else []
        log["filled"] = filled
        db.execute("UPDATE entities SET merged_into=?, updated_at=? WHERE id=?", (kid, now_iso(), rid))
        db.execute("UPDATE entities SET updated_at=? WHERE id=?", (now_iso(), kid))
        db.execute("INSERT INTO merges(canonical_id, retired_id, performed_by, reason) VALUES (?,?,?,?)", (kid, rid, editor.id, reason))
        entities.add_revision(db, rid, editor.id, "Merged into another record", reason=reason)
        entities.add_revision(db, kid, editor.id, "Merged with a duplicate record"
                              + (f"; filled: {', '.join(filled)}" if filled else ""), reason=reason)
        audit.log(db, editor.id, "record.merged", keep["kind"], keep["public_id"],
                  {"retired": retire["public_id"], "reason": reason, **log})
        search.reindex(db, rid)
        search.reindex(db, kid)
        # a kept record that is public may now link to people/places it did not before: reindex neighbours lazily
    return keep, log


# ───────────── duplicate report ─────────────
def duplicate_report(db, limit=100):
    """Possible duplicate people across the whole archive, for editors. A review aid, never proof."""
    people = db.execute("SELECT e.id, e.public_id, p.preferred_name, p.full_name, p.birth_start, p.birth_precision FROM entities e "
                        "JOIN people p ON p.entity_id=e.id WHERE e.merged_into IS NULL AND e.deleted_at IS NULL "
                        "ORDER BY e.id").fetchall()
    seen, out = set(), []
    for p in people:
        names = [r["name"] for r in db.execute("SELECT name FROM entity_names WHERE entity_id=?", (p["id"],))]
        by = p["birth_start"][:4] if p["birth_start"] and p["birth_precision"] != "unknown" else None
        for c in duplicates.find_person_candidates(db, names, birth_year=by, limit=5, exclude_entity_id=p["id"]):
            pair = tuple(sorted((p["id"], c["entity_id"])))
            if pair in seen:
                continue
            seen.add(pair)
            out.append({"a": {"public_id": p["public_id"], "name": p["preferred_name"]},
                        "b": {"public_id": c["public_id"], "name": c["name"]}, "score": c["score"], "why": c["why"]})
            if len(out) >= limit:
                return sorted(out, key=lambda x: -x["score"])
    return sorted(out, key=lambda x: -x["score"])


def merge_history(db, entity_id):
    return db.execute("SELECT m.*, k.public_id AS keep_pid, r.public_id AS retire_pid, u.username FROM merges m "
                      "JOIN entities k ON k.id=m.canonical_id JOIN entities r ON r.id=m.retired_id LEFT JOIN users u ON u.id=m.performed_by "
                      "WHERE m.canonical_id=? OR m.retired_id=? ORDER BY m.id DESC", (entity_id, entity_id)).fetchall()


def to_json(log):
    return json.dumps(log, ensure_ascii=False, default=str)
