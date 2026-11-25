"""Public data export: everything a visitor can already see on the site, as JSON and CSV in one ZIP.

Only published, public, unmerged records are included, and only the fields their public pages show.
Each table has an explicit list of exported columns (tests fail if a new column is not classified),
so confidential fields (research notes, editor notes, uploader and reviewer ids, donor and custodian
details, interview codes, redaction notes) can never leak by being added to the schema later.
Links appear only when the link itself and both ends are public. Archive items also need public
access and rights that allow display; oral-history transcripts and translations appear only where
the interviewee's consent allows it and no embargo is in force. Media files are not included; each
record carries its page address. Accounts, submissions, messages and logs are never exported.
"""
import csv
import io
import json
import zipfile

from . import audit, oral
from .entities import PUBLIC_WHERE
from .search import ITEM_OK
from .timeutil import now_iso

FORMAT_VERSION = 1

# Columns exported per record table (entity_id is replaced by the record's permanent public_id).
RECORD_COLUMNS = {
    "person": ("people", ("preferred_name", "full_name", "original_name", "original_name_lang", "summary", "biography",
                          "occupation", "living_status", "birth_start", "birth_end", "birth_precision", "birth_note",
                          "birth_place_id", "death_start", "death_end", "death_precision", "death_note", "death_place_id")),
    "family": ("families", ("display_name", "original_name", "summary", "narrative", "region_note")),
    "place": ("places", ("primary_name", "original_name", "place_type_id", "country", "admin_region", "latitude", "longitude",
                         "coord_precision", "coord_note", "overview", "valid_start", "valid_end", "valid_precision", "valid_note")),
    "event": ("events", ("title", "event_type_id", "summary", "description", "date_start", "date_end", "date_precision", "date_note")),
    "organization": ("organizations", ("name", "original_name", "description", "active_start", "active_end", "active_precision",
                                       "active_note")),
    "source": ("sources", ("title", "source_type", "creator", "publisher", "repository", "identifier", "pub_date_text", "url",
                           "accessed_on", "language", "provenance", "rights_note", "reliability_note")),
    "archive_item": ("archive_items", ("title", "alt_title", "item_type", "media_kind", "description", "created_start", "created_end",
                                       "created_precision", "created_note", "creator", "provenance", "original_language",
                                       "transcript", "transcript_reviewed", "rights_holder", "rights_status")),
    "collection": ("collections", ("title", "description", "rights_note")),
    "oral_history": ("oral_histories", ("title", "interviewee_id", "interviewee_text", "interviewer_text", "recorded_start",
                                        "recorded_end", "recorded_precision", "recorded_note", "recording_location_note", "language",
                                        "topics", "summary", "transcript_text", "transcript_kind", "transcript_reviewed",
                                        "translation_language", "translation_text", "translation_kind")),
}
# Columns deliberately NOT exported (confidential, internal, or not shown publicly). Every column of an
# exported table must appear in exactly one of the two lists; tests/test_export.py enforces this.
NOT_EXPORTED = {
    "people": ("entity_id", "kind", "birth_place_kind", "death_place_kind", "research_notes"),
    "families": ("entity_id", "kind"),
    "places": ("entity_id", "kind"),
    "events": ("entity_id", "kind"),
    "organizations": ("entity_id", "kind"),
    "sources": ("entity_id", "kind"),
    "archive_items": ("entity_id", "kind", "uploaded_by", "donor", "custodian", "collection_note", "access_level", "embargo_until"),
    "collections": ("entity_id", "kind", "is_featured", "created_by"),
    "oral_histories": ("entity_id", "kind", "interview_code", "interviewee_kind", "embargo_until", "redaction_notes",
                       "media_item_id", "media_item_kind"),
}
REF_COLUMNS = {"birth_place_id", "death_place_id", "interviewee_id"}      # entity ids → public ids (only if public)


def _pid_map(db, include_fictional):
    fict = "" if include_fictional else " AND e.is_fictional_test=0"
    return {r["id"]: r for r in db.execute(
        f"SELECT e.id, e.kind, e.public_id, e.slug, e.is_fictional_test, e.created_at, e.updated_at FROM entities e "
        f"WHERE {PUBLIC_WHERE} AND {ITEM_OK}{fict}")}


def build(db, base_url="", include_fictional=False):
    """Returns {"manifest": {...}, "tables": {name: [row dicts]}}."""
    from ..queries import record_url
    ents = _pid_map(db, include_fictional)
    pid = lambda i: ents[i]["public_id"] if i in ents else None  # noqa: E731
    types = {t: {r["id"]: r["label"] for r in db.execute(f"SELECT id, label FROM {t}")} for t in ("place_types", "event_types")}
    tables = {}
    for kind, (table, cols) in RECORD_COLUMNS.items():
        rows = []
        for r in db.execute(f"SELECT entity_id, {', '.join(cols)} FROM {table} ORDER BY entity_id"):
            e = ents.get(r["entity_id"])
            if not e:
                continue
            out = {"public_id": e["public_id"], "url": base_url + record_url(kind, e["slug"]),
                   "created_at": e["created_at"], "updated_at": e["updated_at"]}
            if include_fictional:
                out["is_fictional_test"] = e["is_fictional_test"]
            for c in cols:
                v = r[c]
                if c in REF_COLUMNS:
                    v = pid(v)
                elif c == "place_type_id":
                    c, v = "place_type", types["place_types"].get(v)
                elif c == "event_type_id":
                    c, v = "event_type", types["event_types"].get(v)
                out[c] = v
            if kind == "oral_history":
                ok = oral.allowed(db, r["entity_id"])
                if not ok["publish_transcript"]:
                    out["transcript_text"] = out["transcript_kind"] = None
                if not ok["publish_translation"]:
                    out["translation_text"] = out["translation_kind"] = None
            rows.append(out)
        tables[table] = rows

    tables["names"] = [{"record": pid(r["entity_id"]), "name": r["name"], "name_type": r["name_type"], "language": r["language"],
                        "script": r["script"], "note": r["note"]}
                       for r in db.execute("SELECT * FROM entity_names ORDER BY entity_id, id") if r["entity_id"] in ents]

    def links(sql, cols, required, optional=(), one_of=()):
        """`required` ends must be public records; `optional` ends are blanked when not public;
        of `one_of` (alternatives such as person-or-organization) the one that is set must be public."""
        out = []
        for r in db.execute(sql):
            if not all(r[k] in ents for k in required):
                continue
            if one_of and not any(r[k] in ents for k in one_of if r[k] is not None):
                continue
            out.append({c: (pid(r[c]) if c in (*required, *optional, *one_of) else r[c]) for c in cols})
        return out

    pub = "publication_status='published' AND visibility='public'"
    period = ("period_start", "period_end", "period_precision", "period_note")
    tables["relationships"] = links(f"SELECT * FROM relationships WHERE {pub} ORDER BY id",
                                    ("person_a_id", "person_b_id", "relationship_type", "status", *period, "notes"),
                                    ("person_a_id", "person_b_id"))
    tables["family_memberships"] = links(f"SELECT * FROM family_memberships WHERE {pub} ORDER BY id",
                                         ("family_id", "person_id", "role_note", *period), ("family_id", "person_id"))
    tables["affiliations"] = links(f"SELECT * FROM affiliations WHERE {pub} ORDER BY id",
                                   ("person_id", "organization_id", "role", *period, "place_id", "evidence_status", "notes"),
                                   ("person_id", "organization_id"), optional=("place_id",))
    tables["event_participants"] = links("SELECT * FROM event_participants WHERE publication_status='published' ORDER BY id",
                                         ("event_id", "person_id", "organization_id", "role", "evidence_status", "notes"),
                                         ("event_id",), one_of=("person_id", "organization_id"))
    tables["event_places"] = links("SELECT * FROM event_places ORDER BY id", ("event_id", "place_id", "role_note", "is_uncertain"),
                                   ("event_id", "place_id"))
    tables["collection_items"] = links("SELECT * FROM collection_items ORDER BY collection_id, position",
                                       ("collection_id", "item_id", "position"), ("collection_id", "item_id"))
    tables["archive_item_subjects"] = links("SELECT * FROM archive_item_subjects", ("item_id", "subject_id", "note"),
                                            ("item_id", "subject_id"))
    tables["oral_history_subjects"] = links("SELECT * FROM oral_history_subjects", ("oral_history_id", "subject_id"),
                                            ("oral_history_id", "subject_id"))
    tables["citations"] = links("SELECT * FROM citations ORDER BY id",
                                ("source_id", "target_id", "field_name", "claim_text", "locator", "explanation", "evidence_status"),
                                ("source_id", "target_id"))
    tables["conflicting_accounts"] = links("SELECT * FROM conflicting_accounts WHERE is_public=1 ORDER BY id",
                                           ("entity_id", "topic", "account_text", "attributed_to", "source_id", "basis_note",
                                            "needs_research", "concerns_date", "concerns_location"), ("entity_id",), optional=("source_id",))
    manifest = {
        "title": "ELF Digital Historical Archive: public data export",
        "format_version": FORMAT_VERSION,
        "generated_at": now_iso(),
        "base_url": base_url,
        "includes_fictional_test_records": include_fictional,
        "counts": {k: len(v) for k, v in tables.items()},
        "notes": [
            "Contains only records and fields that are publicly visible on the archive website at the time of export.",
            "Records are identified by their permanent public_id; links refer to records by public_id.",
            "Unknown values are empty (null). Dates carry a precision; an approximate date is not an exact date.",
            "Media files are not included. Being included here does not mean an item is free to reuse: check each record's rights.",
        ],
    }
    return {"manifest": manifest, "tables": tables}


def to_zip(data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(data["manifest"], ensure_ascii=False, indent=1))
        z.writestr("archive.json", json.dumps(data["tables"], ensure_ascii=False, indent=1))
        for name, rows in data["tables"].items():
            s = io.StringIO()
            if rows:
                w = csv.DictWriter(s, fieldnames=list(rows[0]), lineterminator="\n")
                w.writeheader()
                w.writerows(rows)
            z.writestr(f"csv/{name}.csv", "﻿" + s.getvalue())       # BOM so spreadsheet programs read UTF-8 (Ge'ez, Arabic)
    return buf.getvalue()


def export_zip(db, actor_id, base_url="", include_fictional=False, via="admin"):
    data = build(db, base_url, include_fictional)
    audit.log(db, actor_id, "export.public", "export", None,
              {"via": via, "include_fictional": include_fictional, "counts": data["manifest"]["counts"]})
    return to_zip(data), data["manifest"]
