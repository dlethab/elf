"""Record specifications, validation, and application of approved submissions.

Contributions are validated into plain JSON (`proposed_data`). NOTHING is written to the entity
tables until an editor publishes the submission, at which point `apply_*` runs in one transaction.

References to other records ("ref" fields: a birthplace, a family, an organization…) always point at
a PUBLISHED record by its permanent id. Forms show "Name [per-abc12345]" so people can type to
search; the id in brackets is what is stored.
"""
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from . import audit, dates, entities, search
from .dates import DATE_HELP
from .names import normalize
from .timeutil import now_iso
from ..vocab import (COORD_PRECISIONS, DIRECTED_RELATIONSHIPS, RELATIONSHIP_STATUSES,
                     RELATIONSHIP_TYPES, SOURCE_TYPES)


@dataclass
class F:
    name: str
    label: str
    kind: str = "text"      # text|area|choice|date|ref|refs|consents|taxon|lines|sources|float|url
    required: bool = False
    max: int = 200
    choices: Optional[list] = None
    help: str = ""
    rows: int = 4
    additive: bool = False  # corrections only ADD (aliases, sources) and never delete
    ref: Optional[str] = None   # entity kind a "ref" field points at (refs: any linkable kind)


REF_HELP = "Start typing a name and choose from the list. Only published records can be chosen."

SPECS = {
    "person": [
        F("preferred_name", "Preferred name", required=True),
        F("full_name", "Full name"),
        F("original_name", "Name in original script or language"),
        F("original_name_lang", "Language of that name (code, e.g. ti, ar, en)", max=16),
        F("aliases", "Other spellings, transliterations, aliases (one per line)", "lines", additive=True),
        F("occupation", "Occupation or civilian role", max=300),
        F("living_status", "Living status", "choice",
          choices=[("unknown", "Unknown"), ("deceased", "Deceased"), ("living", "Living")],
          help="People recorded as living are kept private until an editor confirms consent."),
        F("birth", "Birth", "date", help=DATE_HELP),
        F("birth_place", "Birthplace", "ref", ref="place", help="Choose from published places; leave blank if unknown."),
        F("death", "Death", "date", help=DATE_HELP),
        F("death_place", "Place of death", "ref", ref="place"),
        F("summary", "Short summary", "area", max=1000, rows=3),
        F("biography", "Biography and life history", "area", max=20000, rows=10),
    ],
    "family": [
        F("display_name", "Family name", required=True),
        F("original_name", "Name in original script or language"),
        F("aliases", "Other spellings (one per line)", "lines", additive=True),
        F("region_note", "Regions or towns of association", max=500),
        F("summary", "Short summary", "area", max=1000, rows=3),
        F("narrative", "Family history", "area", max=20000, rows=10),
    ],
    "place": [
        F("primary_name", "Primary name", required=True),
        F("original_name", "Name in original script or language"),
        F("aliases", "Historical names and alternate spellings (one per line)", "lines", additive=True),
        F("place_type", "Place type", "taxon"),
        F("country", "Country", max=100),
        F("admin_region", "Region / administrative area", max=200),
        F("latitude", "Latitude (decimal degrees)", "float",
          help="Only enter coordinates you can source. Leave blank if unknown — never estimate silently."),
        F("longitude", "Longitude (decimal degrees)", "float"),
        F("coord_precision", "Coordinate precision", "choice",
          choices=[("", "—")] + [(c, c.replace("_", " ").capitalize()) for c in COORD_PRECISIONS],
          help="Required when coordinates are given. 'Approximate' is shown to visitors as approximate."),
        F("coord_note", "Note on location uncertainty", "area", max=1000, rows=2),
        F("overview", "Historical overview", "area", max=20000, rows=8),
    ],
    "event": [
        F("title", "Event title", required=True),
        F("event_type", "Event type", "taxon"),
        F("date", "Date", "date", help=DATE_HELP),
        F("place", "Place", "ref", ref="place", help="Choose from published places; leave blank if unknown."),
        F("summary", "Short summary", "area", max=1000, rows=3),
        F("description", "Detailed account", "area", max=20000, rows=10),
    ],
    "source": [
        F("title", "Title", required=True, max=300),
        F("source_type", "Source type", "choice", choices=[(s, s.replace("_", " ").capitalize()) for s in SOURCE_TYPES]),
        F("creator", "Author or creator", max=300),
        F("publisher", "Publisher"),
        F("repository", "Repository or archive"),
        F("identifier", "Identifier or catalogue number"),
        F("pub_date_text", "Publication or creation date (free text)", max=100),
        F("url", "URL", "url", max=500),
        F("language", "Language", max=50),
        F("provenance", "Provenance", "area", max=2000, rows=3),
    ],
    "organization": [
        F("name", "Organization name", required=True),
        F("original_name", "Name in original script or language"),
        F("aliases", "Other names, abbreviations and spellings (one per line)", "lines", additive=True),
        F("active", "When it was active", "date", help=DATE_HELP),
        F("description", "Description and history", "area", max=20000, rows=8),
    ],
    "relationship": [
        F("person_a", "Person A", "ref", ref="person", required=True, help=REF_HELP),
        F("relationship_type", "Relationship (A is … of B)", "choice", required=True,
          choices=[(k, v[0]) for k, v in RELATIONSHIP_TYPES.items()]),
        F("person_b", "Person B", "ref", ref="person", required=True, help=REF_HELP),
        F("status", "Status", "choice", choices=[(s, s.capitalize()) for s in RELATIONSHIP_STATUSES]),
        F("period", "Dates, if relevant", "date", help=DATE_HELP),
        F("notes", "Explanation / notes", "area", max=2000, rows=3),
    ],
    "affiliation": [
        F("person", "Person", "ref", ref="person", required=True, help=REF_HELP),
        F("organization", "Organization", "ref", ref="organization", required=True, help=REF_HELP),
        F("role", "Role or position, if known", max=200),
        F("period", "Dates of the affiliation", "date", help=DATE_HELP),
        F("place", "Place, if relevant", "ref", ref="place"),
        F("notes", "Explanation / notes", "area", max=2000, rows=3),
    ],
    "membership": [
        F("family", "Family", "ref", ref="family", required=True, help=REF_HELP),
        F("person", "Person", "ref", ref="person", required=True, help=REF_HELP),
        F("role_note", "Place in the family, if documented (for example: eldest daughter)", max=200),
        F("period", "Dates, if relevant", "date", help=DATE_HELP),
    ],
    "participation": [
        F("event", "Event", "ref", ref="event", required=True, help=REF_HELP),
        F("person", "Person", "ref", ref="person", help="Choose a person or an organization."),
        F("organization", "Organization", "ref", ref="organization"),
        F("role", "Role in the event, if known", max=200),
        F("notes", "Explanation / notes", "area", max=2000, rows=3),
    ],
    "oral_history": [
        F("title", "Title of the interview", required=True, max=300),
        F("interviewee", "Interviewee (if they have a record in the archive)", "ref", ref="person", help=REF_HELP),
        F("interviewee_text", "Interviewee's name, if they have no record in the archive", max=200),
        F("interviewer_text", "Interviewer", max=200),
        F("recorded", "When it was recorded", "date", help=DATE_HELP),
        F("recording_location_note", "Where it was recorded (town or region only; never a home address)", max=300),
        F("language", "Language of the interview", max=100),
        F("summary", "Summary", "area", max=5000, rows=4),
        F("topics", "Topics and keywords (one per line)", "area", max=2000, rows=3),
        F("related", "People, families, places and events it concerns (one per line)", "refs", max=40,
          help="Type each record's name, or its name with the permanent ID in brackets. Only published records can be linked."),
        F("transcript_text", "Transcript", "area", max=300000, rows=10,
          help="Paste the transcript if there is one. Lines that start with a time such as [12:30] become links to that moment of the recording."),
        F("transcript_kind", "What kind of transcript is it?", "choice", choices=[
            ("", "—"), ("verbatim", "Verbatim (word for word)"), ("edited", "Edited for reading"),
            ("translation", "A translation, not the original words"), ("machine_draft", "Automatic transcription, not yet checked")]),
        F("translation_language", "Language of the translation", max=100),
        F("translation_text", "Translation", "area", max=300000, rows=8,
          help="A translation is always kept separate from the original transcript and never replaces it."),
        F("translation_kind", "Who made the translation?", "choice", choices=[
            ("", "—"), ("human_reviewed", "A person, and it has been checked"), ("human_unreviewed", "A person, not yet checked"),
            ("machine_draft", "Automatic translation, not yet checked")]),
        F("consents", "What the interviewee agreed to", "consents"),
    ],
}
CONSENT_LABELS = {
    "record": "Being recorded", "store": "The archive keeping the recording",
    "publish_recording": "Publishing the recording", "publish_transcript": "Publishing the transcript",
    "publish_translation": "Publishing a translation", "use_excerpts": "Quoting excerpts",
    "research_access": "Access by vetted researchers", "allow_download": "Downloading and reuse",
}
REF_COLUMN = {"birth_place": "birth_place_id", "death_place": "death_place_id", "interviewee": "interviewee_id"}
# Every kind except sources themselves may carry contributor-declared sources.
SOURCES_FIELD = F("sources", "Supporting sources (one per line: Title | page or locator | URL)", "sources", additive=True,
                  help="Each line becomes a separate source record, cited as 'unverified' until an editor assesses it.")
LINK_KINDS = ("relationship", "affiliation", "membership", "participation")
RECORD_KINDS = ("person", "family", "place", "event", "source", "organization")
CORRECTABLE_KINDS = RECORD_KINDS + ("oral_history",)     # editors may edit these directly

TITLE_FIELD = {"person": "preferred_name", "family": "display_name", "place": "primary_name",
               "event": "title", "source": "title", "organization": "name", "oral_history": "title"}
NOT_NULL_DEFAULTS = {"living_status": "unknown", "source_type": "other", "status": "current"}
PLACE_COLUMN = REF_COLUMN
TAXON_TABLE = {"place_type": ("place_types", "place_type_id"), "event_type": ("event_types", "event_type_id")}
NAME_FIELD_TYPES = {"preferred_name": "preferred", "full_name": "full", "display_name": "preferred",
                    "primary_name": "preferred", "title": "preferred", "name": "preferred"}


def spec_for(kind, with_sources=True):
    fields = list(SPECS[kind])
    if with_sources and kind != "source":
        fields.append(SOURCES_FIELD)
    return fields


# ───────────── references to other records ─────────────
_PID_IN_BRACKETS = re.compile(r"\[([a-z]{3}-[a-z0-9]{8})\]\s*$")
_PID = re.compile(r"^[a-z]{3}-[a-z0-9]{8}$")


def ref_label(db, public_id):
    e = entities.get_by_public_id(db, public_id) if public_id else None
    return f"{entities.title_of(db, e['id'])} [{public_id}]" if e else (public_id or "")


def parse_ref(db, value, kind):
    """(public_id, error). Accepts 'Name [per-abc12345]', a bare permanent id, or a name that matches
    exactly one published record. Never confirms that a private record exists."""
    v = " ".join((value or "").split())
    if not v:
        return None, None
    m = _PID_IN_BRACKETS.search(v)
    pid = m.group(1) if m else (v if _PID.match(v) else None)
    if pid:
        return (pid, None) if entities.get_public_by_public_id(db, pid, kind) else (None, "That record was not found.")
    rows = db.execute(f"SELECT DISTINCT e.public_id FROM entity_names n JOIN entities e ON e.id=n.entity_id "
                      f"WHERE e.kind=? AND {entities.PUBLIC_WHERE} AND n.normalized=? LIMIT 2", (kind, normalize(v))).fetchall()
    if len(rows) == 1:
        return rows[0][0], None
    if len(rows) > 1:
        return None, "More than one record has this name. Choose the right one from the list."
    return None, "That record was not found."


LINKABLE = ("person", "family", "place", "event", "organization")


def parse_any_ref(db, value):
    """Like parse_ref, for a field that may point at a person, family, place, event or organization."""
    v = " ".join((value or "").split())
    m = _PID_IN_BRACKETS.search(v)
    pid = m.group(1) if m else (v if _PID.match(v) else None)
    if pid:
        kind = {p: k for k, p in entities.ID_PREFIX.items()}.get(pid[:3])
        return (pid, None) if kind in LINKABLE and entities.get_public_by_public_id(db, pid, kind) else (None, "That record was not found.")
    ph = ",".join("?" * len(LINKABLE))
    rows = db.execute(f"SELECT DISTINCT e.public_id FROM entity_names n JOIN entities e ON e.id=n.entity_id "
                      f"WHERE e.kind IN ({ph}) AND {entities.PUBLIC_WHERE} AND n.normalized=? LIMIT 2", (*LINKABLE, normalize(v))).fetchall()
    if len(rows) == 1:
        return rows[0][0], None
    return None, ("More than one record has this name. Choose the right one from the list." if rows else "That record was not found.")


def lookup(db, kind, q, limit=20):
    """Typeahead suggestions: published records only, matched on any recorded name."""
    nq = normalize(q)
    if kind not in entities.TITLE_COL or len(nq) < 1:
        return []
    t, col = entities.KIND_TABLE[kind], entities.TITLE_COL[kind]
    rows = db.execute(
        f"SELECT DISTINCT e.public_id, x.{col} AS title FROM entity_names n JOIN entities e ON e.id=n.entity_id "
        f"JOIN {t} x ON x.entity_id=e.id WHERE e.kind=? AND {entities.PUBLIC_WHERE} AND (n.normalized LIKE ? OR n.normalized LIKE ?) "
        f"ORDER BY lower(x.{col}) LIMIT ?", (kind, nq + "%", "% " + nq + "%", limit)).fetchall()
    return [{"id": r["public_id"], "label": f"{r['title']} [{r['public_id']}]"} for r in rows]


# ───────────── choices for select inputs ─────────────
def choices_for(db, f):
    if f.kind == "choice":
        return f.choices
    if f.kind == "taxon":
        table = TAXON_TABLE[f.name][0]
        return [("", "—")] + [(r["slug"], r["label"]) for r in
                              db.execute(f"SELECT slug, label FROM {table} WHERE is_active=1 ORDER BY sort_order")]
    if f.kind == "ref":           # initial suggestions for the type-to-search list; the rest come from /lookup
        t, col = entities.KIND_TABLE[f.ref], entities.TITLE_COL[f.ref]
        rows = db.execute(f"SELECT e.public_id, x.{col} AS t FROM entities e JOIN {t} x ON x.entity_id=e.id "
                          f"WHERE e.kind=? AND {entities.PUBLIC_WHERE} ORDER BY lower(x.{col}) LIMIT 300", (f.ref,)).fetchall()
        return [(r["public_id"], f"{r['t']} [{r['public_id']}]") for r in rows]
    return None


# ───────────── validation ─────────────
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(v, multiline):
    v = _CTRL.sub("", (v or "").replace("\r\n", "\n").replace("\r", "\n"))
    return v.strip() if multiline else " ".join(v.split())


def _ok_url(v):
    u = urlparse(v)
    return u.scheme in ("http", "https") and bool(u.netloc)


def validate(db, kind, raw, *, strict_consent=True):
    """Return (clean, errors). `raw` is a mapping of form strings. Unknown keys are ignored."""
    clean, errors = {}, {}
    for f in spec_for(kind):
        v = raw.get(f.name, "")
        v = v if isinstance(v, str) else ("" if v is None else str(v))
        if f.kind in ("text", "area", "url"):
            v = _clean_text(v, f.kind == "area")
            if f.required and not v:
                errors[f.name] = "This field is required."
            elif len(v) > f.max:
                errors[f.name] = f"Use at most {f.max} characters."
            elif f.kind == "url" and v and not _ok_url(v):
                errors[f.name] = "Enter a full http(s) URL."
            clean[f.name] = v or None
        elif f.kind == "choice":
            v = v.strip()
            allowed = {c[0] for c in f.choices}
            if f.required and not v:
                errors[f.name] = "This field is required."
            elif v and v not in allowed:
                errors[f.name] = "Choose one of the listed options."
            clean[f.name] = v or None
        elif f.kind == "taxon":
            v = v.strip()
            if v and not db.execute(f"SELECT 1 FROM {TAXON_TABLE[f.name][0]} WHERE slug=? AND is_active=1", (v,)).fetchone():
                errors[f.name] = "Choose one of the listed options."
            clean[f.name] = v or None
        elif f.kind == "date":
            try:
                clean[f.name] = dates.parse(v).as_dict()
            except dates.DateError as e:
                errors[f.name] = str(e)
        elif f.kind == "ref":
            pid, err = parse_ref(db, v, f.ref)
            if f.required and not v.strip():
                errors[f.name] = "This field is required."
            elif err:
                errors[f.name] = err
            clean[f.name] = pid
        elif f.kind == "refs":
            out = []
            for line in [x.strip() for x in _CTRL.sub("", v).splitlines() if x.strip()][:f.max]:
                pid, err = parse_any_ref(db, line)
                if err:
                    errors[f.name] = "One or more of these records could not be found. Choose names from the suggestions."
                elif pid not in out:
                    out.append(pid)
            clean[f.name] = out
        elif f.kind == "consents":
            granted = [t for t in CONSENT_LABELS if raw.get(f"consent_{t}") == "1"]
            note = _clean_text(raw.get("consent_note") or "", True)[:2000] or None
            if strict_consent and raw.get("consent_declared") != "1":
                errors[f.name] = "Please confirm how consent was obtained."
            clean[f.name] = {"granted": granted, "note": note}
        elif f.kind == "float":
            v = v.strip()
            try:
                clean[f.name] = float(v) if v else None
            except ValueError:
                errors[f.name] = "Enter a number."
        elif f.kind == "lines":
            vals = [" ".join(x.split()) for x in _CTRL.sub("", v).splitlines() if x.strip()]
            if len(vals) > 30 or any(len(x) > 200 for x in vals):
                errors[f.name] = "At most 30 lines of up to 200 characters."
            clean[f.name] = vals
        elif f.kind == "sources":
            out = []
            for line in [x for x in _CTRL.sub("", v).splitlines() if x.strip()][:10]:
                parts = [p.strip() for p in line.split("|")]
                title, locator, url = (parts + ["", "", ""])[:3]
                if not title or len(title) > 300 or len(locator) > 200:
                    errors[f.name] = "Each source needs a title (≤300 chars) and a short locator."
                    break
                if url and not _ok_url(url):
                    errors[f.name] = "Source URLs must be full http(s) addresses."
                    break
                out.append({"title": title, "locator": locator or None, "url": url or None})
            clean[f.name] = out
    if not errors:
        _cross_validate(db, kind, clean, errors)
    return clean, errors


def _cross_validate(db, kind, clean, errors):
    if kind == "place":
        la, lo, pr = clean.get("latitude"), clean.get("longitude"), clean.get("coord_precision")
        if (la is None) != (lo is None):
            errors["longitude"] = "Give both latitude and longitude, or neither."
        elif la is not None:
            if not -90 <= la <= 90:
                errors["latitude"] = "Latitude must be between -90 and 90."
            if not -180 <= lo <= 180:
                errors["longitude"] = "Longitude must be between -180 and 180."
            if not pr:
                errors["coord_precision"] = "Say how precise these coordinates are."
        elif pr:
            errors["coord_precision"] = "Precision applies only when coordinates are given."
    elif kind == "relationship":
        a, b = clean["person_a"], clean["person_b"]
        if a == b:
            errors["person_b"] = "A person cannot be related to themselves."
        elif _find_relationship(db, a, b, clean["relationship_type"]):
            errors["relationship_type"] = "This relationship is already recorded."
        clean["status"] = clean.get("status") or "current"
    elif kind == "membership":
        if _ids_exist(db, "SELECT 1 FROM family_memberships WHERE family_id=? AND person_id=?", clean["family"], clean["person"]):
            errors["person"] = "This person is already listed as a member of this family."
    elif kind == "participation":
        if bool(clean.get("person")) == bool(clean.get("organization")):
            errors["person"] = "Choose a person or an organization (one of them)."
        elif clean.get("person") and _ids_exist(db, "SELECT 1 FROM event_participants WHERE event_id=? AND person_id=?",
                                                clean["event"], clean["person"]):
            errors["person"] = "This participant is already recorded for this event."
        elif clean.get("organization") and _ids_exist(db, "SELECT 1 FROM event_participants WHERE event_id=? AND organization_id=?",
                                                      clean["event"], clean["organization"]):
            errors["organization"] = "This participant is already recorded for this event."


def _ids_exist(db, sql, *public_ids):
    ids = [entities.get_by_public_id(db, p) for p in public_ids]
    return all(ids) and db.execute(sql, [e["id"] for e in ids]).fetchone() is not None


def _canonical_pair(a, b, rtype):
    return (a, b) if (rtype in DIRECTED_RELATIONSHIPS or a < b) else (b, a)


def _find_relationship(db, pub_a, pub_b, rtype):
    a, b = entities.get_by_public_id(db, pub_a), entities.get_by_public_id(db, pub_b)
    if not a or not b:
        return None
    x, y = _canonical_pair(a["id"], b["id"], rtype)
    return db.execute("SELECT id FROM relationships WHERE person_a_id=? AND person_b_id=? AND relationship_type=?",
                      (x, y, rtype)).fetchone()


# ───────────── column mapping ─────────────
def _row_values(db, kind, clean, fields=None):
    """Map validated fields to subtype-table columns."""
    cols = {}
    for f in spec_for(kind, with_sources=False):
        if fields is not None and f.name not in fields:
            continue
        if f.kind in ("lines", "sources", "refs", "consents") or f.name not in clean:
            continue
        v = clean[f.name]
        if f.kind == "date":
            cols.update(dates.columns(f.name, dates.FuzzyDate(**v)))
        elif f.kind == "ref" and f.name in PLACE_COLUMN:
            cols[PLACE_COLUMN[f.name]] = (entities.get_by_public_id(db, v)["id"] if v else None)
        elif f.kind == "ref":      # event.place → event_places (handled separately)
            continue
        elif f.kind == "taxon":
            table, col = TAXON_TABLE[f.name]
            cols[col] = (db.execute(f"SELECT id FROM {table} WHERE slug=?", (v,)).fetchone()["id"] if v else None)
        else:
            cols[f.name] = NOT_NULL_DEFAULTS[f.name] if (v is None and f.name in NOT_NULL_DEFAULTS) else v
    return cols


def current_clean(db, kind, entity_id):
    """Current stored values in the same shape `validate` produces (used for diffs and prefilled forms)."""
    row = entities.subtype_row(db, entity_id)
    out = {}
    for f in spec_for(kind, with_sources=False):
        if f.kind in ("lines", "sources"):
            out[f.name] = []
        elif f.kind == "refs":
            out[f.name] = [r["public_id"] for r in db.execute(
                "SELECT e.public_id FROM oral_history_subjects s JOIN entities e ON e.id=s.subject_id WHERE s.oral_history_id=? "
                "ORDER BY e.id", (entity_id,))]
        elif f.kind == "consents":
            out[f.name] = {"granted": [r["consent_type"] for r in db.execute(
                "SELECT consent_type FROM consent_records WHERE oral_history_id=? AND revoked_at IS NULL AND granted=1", (entity_id,))],
                "note": None}
        elif f.kind == "date":
            out[f.name] = dates.from_row(row, f.name).as_dict()
        elif f.kind == "ref" and f.name in PLACE_COLUMN:
            pid = row[PLACE_COLUMN[f.name]]
            out[f.name] = entities.get(db, pid)["public_id"] if pid else None
        elif f.kind == "ref":
            r = db.execute("SELECT e.public_id FROM event_places ep JOIN entities e ON e.id=ep.place_id "
                           "WHERE ep.event_id=? ORDER BY ep.id LIMIT 1", (entity_id,)).fetchone()
            out[f.name] = r["public_id"] if r else None
        elif f.kind == "taxon":
            table, col = TAXON_TABLE[f.name]
            r = db.execute(f"SELECT slug FROM {table} WHERE id=?", (row[col],)).fetchone() if row[col] else None
            out[f.name] = r["slug"] if r else None
        else:
            out[f.name] = row[f.name]
    return out


def form_values(clean, kind, db=None):
    """Turn validated/stored data back into form strings (for re-displaying a draft)."""
    out = {}
    for f in spec_for(kind):
        v = clean.get(f.name)
        if v in (None, [], {}):
            out[f.name] = ""
        elif f.kind == "date":
            out[f.name] = dates.to_input(v["start"], v["end"], v["precision"])
        elif f.kind == "ref":
            out[f.name] = ref_label(db, v) if db is not None else v
        elif f.kind == "refs":
            out[f.name] = "\n".join(ref_label(db, x) if db is not None else x for x in v)
        elif f.kind == "consents":
            out.update({f"consent_{t}": "1" for t in v.get("granted", [])})
            out["consent_note"] = v.get("note") or ""
            out[f.name] = ""
        elif f.kind == "lines":
            out[f.name] = "\n".join(v)
        elif f.kind == "sources":
            out[f.name] = "\n".join(" | ".join(x for x in (s["title"], s.get("locator") or "", s.get("url") or "")).rstrip(" |")
                                    for s in v)
        elif f.kind == "float":
            out[f.name] = repr(v)
        else:
            out[f.name] = str(v)
    return out


def display_value(db, f, v):
    if v in (None, "", [], {}):
        return "—"
    if f.kind == "date":
        return dates.format_date(v["start"], v["end"], v["precision"])
    if f.kind == "ref":
        e = entities.get_by_public_id(db, v)
        return entities.title_of(db, e["id"]) if e else v
    if f.kind == "refs":
        return "; ".join(display_value(db, F("x", "x", "ref"), x) for x in v)
    if f.kind == "consents":
        return "; ".join(CONSENT_LABELS[t] for t in v.get("granted", [])) or "None"
    if f.kind in ("choice", "taxon"):
        for val, label in (choices_for(db, f) or []):
            if val == v:
                return label
        return str(v)
    if f.kind == "lines":
        return "; ".join(v)
    if f.kind == "sources":
        return "; ".join(s["title"] + (f" ({s['locator']})" if s.get("locator") else "") for s in v)
    return str(v)


def display_rows(db, kind, data):
    """[(label, value)] for a proposed new record, skipping empty fields."""
    rows = []
    for f in spec_for(kind):
        v = display_value(db, f, data.get(f.name))
        if v != "—" and not (f.kind == "date" and v == "Unknown"):
            rows.append((f.label, v))
    return rows


def diff(db, kind, entity_id, changes):
    cur = current_clean(db, kind, entity_id)
    byname = {f.name: f for f in spec_for(kind)}
    return [{"label": byname[n].label, "old": display_value(db, byname[n], cur.get(n)),
             "new": display_value(db, byname[n], new), "additive": byname[n].additive}
            for n, new in changes.items() if n in byname]


def changed_fields(db, kind, entity_id, clean):
    """Reduce a full validated form to only what differs from the stored record."""
    cur = current_clean(db, kind, entity_id)
    out = {}
    for f in spec_for(kind):
        if f.kind == "consents":          # consent is managed by editors with evidence, never by editing the record
            continue
        v = clean.get(f.name)
        if f.additive:
            if v:
                out[f.name] = v
        elif v != cur.get(f.name) and not (v in (None, "") and cur.get(f.name) in (None, "")):
            out[f.name] = v
    return out


# ───────────── applying approved submissions ─────────────
def store_sources(db, target_id, sources, actor_id, field=None, claim=None):
    for s in sources or []:
        existing = db.execute(
            "SELECT s.entity_id FROM sources s JOIN entities e ON e.id=s.entity_id "
            "WHERE lower(s.title)=lower(?) AND COALESCE(s.url,'')=COALESCE(?, '') AND e.merged_into IS NULL",
            (s["title"], s["url"])).fetchone()
        if existing:
            sid = existing["entity_id"]     # reuse: one source can support claims on many records
        else:
            sid, _, _ = entities.create_entity(db, "source", s["title"], created_by=actor_id,
                                               status="published", visibility="public")
            db.execute("INSERT INTO sources(entity_id, title, url) VALUES (?,?,?)", (sid, s["title"], s["url"]))
            entities.add_name(db, sid, s["title"], "preferred")
            entities.add_revision(db, sid, actor_id, "Source created from approved contribution")
            search.reindex(db, sid)
        db.execute("INSERT INTO citations(source_id, target_id, field_name, claim_text, locator, evidence_status, created_by) "
                   "VALUES (?,?,?,?,?, 'unverified', ?)", (sid, target_id, field, claim, s.get("locator"), actor_id))


_store_sources = store_sources      # older name, kept for callers


def _add_names(db, entity_id, kind, clean):
    for f in spec_for(kind, with_sources=False):
        v = clean.get(f.name)
        if not v:
            continue
        if f.name in NAME_FIELD_TYPES:
            entities.add_name(db, entity_id, v, NAME_FIELD_TYPES[f.name])
        elif f.name == "original_name":
            entities.add_name(db, entity_id, v, "original", language=clean.get("original_name_lang"))
        elif f.name == "aliases":
            for a in v:
                entities.add_name(db, entity_id, a, "alternate_spelling")


def apply_new(db, kind, clean, *, actor_id, submission_id, consent_confirmed=False, fictional=False):
    """Create a published record from validated data. Caller supplies the surrounding transaction."""
    living = kind == "person" and clean.get("living_status") == "living"
    visibility = "restricted" if (living and not consent_confirmed) or kind == "oral_history" else "public"
    title = clean[TITLE_FIELD[kind]]
    eid, pid, _ = entities.create_entity(db, kind, title, created_by=actor_id, status="published",
                                         visibility=visibility, fictional=fictional)
    cols = _row_values(db, kind, clean)
    keys = ["entity_id"] + list(cols)
    db.execute(f"INSERT INTO {entities.KIND_TABLE[kind]}({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
               [eid, *cols.values()])
    if kind == "event" and clean.get("place"):
        db.execute("INSERT INTO event_places(event_id, place_id) VALUES (?,?)",
                   (eid, entities.get_by_public_id(db, clean["place"])["id"]))
    _add_names(db, eid, kind, clean)
    store_sources(db, eid, clean.get("sources"), actor_id)
    entities.add_revision(db, eid, actor_id, "Created from an approved submission", submission_id=submission_id)
    if kind == "oral_history":            # consent decides what becomes public (services/oral.py)
        from . import oral
        oral.after_create(db, eid, clean, actor_id, consent_confirmed)
        if oral.should_be_public(db, eid):
            db.execute("UPDATE entities SET visibility='public' WHERE id=?", (eid,))
            visibility = "public"
    audit.log(db, actor_id, "record.published", kind, pid, {"submission": submission_id, "visibility": visibility})
    search.reindex(db, eid)
    return eid


def apply_correction(db, entity, changes, *, actor_id, submission_id, reason=None, summary_prefix="Correction"):
    kind, eid = entity["kind"], entity["id"]
    cols = _row_values(db, kind, changes, fields=set(changes))
    if cols:
        sets = ", ".join(f"{c}=?" for c in cols)
        db.execute(f"UPDATE {entities.KIND_TABLE[kind]} SET {sets} WHERE entity_id=?", [*cols.values(), eid])
    if kind == "oral_history" and "related" in changes:
        db.execute("DELETE FROM oral_history_subjects WHERE oral_history_id=?", (eid,))
        for pid in changes["related"] or []:
            db.execute("INSERT OR IGNORE INTO oral_history_subjects(oral_history_id, subject_id) VALUES (?,?)",
                       (eid, entities.get_by_public_id(db, pid)["id"]))
    if kind == "event" and "place" in changes:
        db.execute("DELETE FROM event_places WHERE event_id=?", (eid,))
        if changes["place"]:
            db.execute("INSERT INTO event_places(event_id, place_id) VALUES (?,?)",
                       (eid, entities.get_by_public_id(db, changes["place"])["id"]))
    tf = TITLE_FIELD[kind]
    if tf in changes and changes[tf]:
        # keep the previous preferred spelling searchable as an alternate; never discard it
        db.execute("UPDATE OR IGNORE entity_names SET name_type='alternate_spelling' WHERE entity_id=? AND name_type='preferred'", (eid,))
        db.execute("DELETE FROM entity_names WHERE entity_id=? AND name_type='preferred'", (eid,))
        entities.add_name(db, eid, changes[tf], "preferred")
    if changes.get("full_name"):
        entities.add_name(db, eid, changes["full_name"], "full")
    if changes.get("original_name"):
        entities.add_name(db, eid, changes["original_name"], "original")
    for a in changes.get("aliases", []):
        entities.add_name(db, eid, a, "alternate_spelling")
    store_sources(db, eid, changes.get("sources"), actor_id)
    labels = {f.name: f.label for f in spec_for(kind)}
    entities.add_revision(db, eid, actor_id, f"{summary_prefix}: " + ", ".join(labels[k] for k in changes),
                          reason=reason, submission_id=submission_id)
    db.execute("UPDATE entities SET updated_at=? WHERE id=?", (now_iso(), eid))
    audit.log(db, actor_id, "record.corrected", kind, entity["public_id"],
              {"fields": sorted(changes), "submission": submission_id})
    if kind == "person" and changes.get("living_status") == "living" and entity["visibility"] == "public":
        entities.set_state(db, eid, visibility="restricted", actor_id=actor_id,
                           reason="Automatically restricted: person recorded as living")
    search.reindex(db, eid)


# ───────────── links between records ─────────────
def _pub(db, public_id, kind):
    e = entities.get_public_by_public_id(db, public_id, kind) if public_id else None
    if public_id and not e:
        raise ValueError(f"The {kind} must still be published.")
    return e


def _link_visibility(db, *person_ids):
    """Links that involve a person recorded as living are restricted (privacy by default)."""
    for pid in person_ids:
        if pid and entities.subtype_row(db, pid)["living_status"] == "living":
            return "restricted"
    return "public"


def _title(db, e):
    return entities.title_of(db, e["id"])


def apply_relationship(db, clean, *, actor_id, submission_id):
    a, b = _pub(db, clean["person_a"], "person"), _pub(db, clean["person_b"], "person")
    x, y = _canonical_pair(a["id"], b["id"], clean["relationship_type"])
    fd = dates.FuzzyDate(**clean["period"])
    cols = {"person_a_id": x, "person_b_id": y, "relationship_type": clean["relationship_type"],
            "status": clean.get("status") or "current", "notes": clean.get("notes"), "publication_status": "published",
            "visibility": _link_visibility(db, a["id"], b["id"]), "created_by": actor_id,
            "submission_id": submission_id, **dates.columns("period", fd)}
    cur = db.execute(f"INSERT INTO relationships({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    claim = f"{_title(db, a)} — {RELATIONSHIP_TYPES[clean['relationship_type']][0].lower()} — {_title(db, b)}"
    for p in (a, b):
        store_sources(db, p["id"], clean.get("sources"), actor_id, field="relationship", claim=claim)
        entities.add_revision(db, p["id"], actor_id, f"Relationship added ({clean['relationship_type'].replace('_', ' ')})",
                              submission_id=submission_id)
    audit.log(db, actor_id, "relationship.published", "relationship", cur.lastrowid, {"submission": submission_id})
    return cur.lastrowid


def apply_affiliation(db, clean, *, actor_id, submission_id):
    p, o = _pub(db, clean["person"], "person"), _pub(db, clean["organization"], "organization")
    pl = _pub(db, clean.get("place"), "place")
    cols = {"person_id": p["id"], "organization_id": o["id"], "role": clean.get("role"),
            **dates.columns("period", dates.FuzzyDate(**clean["period"])), "place_id": pl["id"] if pl else None,
            "evidence_status": "unverified", "notes": clean.get("notes"), "publication_status": "published",
            "visibility": _link_visibility(db, p["id"]), "submission_id": submission_id, "created_by": actor_id}
    cur = db.execute(f"INSERT INTO affiliations({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    claim = f"{_title(db, o)}" + (f" — {clean['role']}" if clean.get("role") else "")
    store_sources(db, p["id"], clean.get("sources"), actor_id, field="affiliation", claim=claim)
    for e in (p, o):
        entities.add_revision(db, e["id"], actor_id, "Affiliation added", submission_id=submission_id)
    audit.log(db, actor_id, "affiliation.published", "affiliation", cur.lastrowid, {"submission": submission_id})
    return cur.lastrowid


def apply_membership(db, clean, *, actor_id, submission_id):
    f, p = _pub(db, clean["family"], "family"), _pub(db, clean["person"], "person")
    cols = {"family_id": f["id"], "person_id": p["id"], "role_note": clean.get("role_note"),
            **dates.columns("period", dates.FuzzyDate(**clean["period"])), "publication_status": "published",
            "visibility": _link_visibility(db, p["id"]), "created_by": actor_id, "submission_id": submission_id}
    cur = db.execute(f"INSERT INTO family_memberships({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    store_sources(db, f["id"], clean.get("sources"), actor_id, field="members", claim=f"Member: {_title(db, p)}")
    for e in (f, p):
        entities.add_revision(db, e["id"], actor_id, "Family member added", submission_id=submission_id)
    audit.log(db, actor_id, "membership.published", "family_membership", cur.lastrowid, {"submission": submission_id})
    return cur.lastrowid


def apply_participation(db, clean, *, actor_id, submission_id):
    ev = _pub(db, clean["event"], "event")
    p, o = _pub(db, clean.get("person"), "person"), _pub(db, clean.get("organization"), "organization")
    who = p or o
    cols = {"event_id": ev["id"], "person_id": p["id"] if p else None, "organization_id": o["id"] if o else None,
            "role": clean.get("role"), "evidence_status": "unverified", "notes": clean.get("notes"),
            "publication_status": "published", "submission_id": submission_id, "created_by": actor_id}
    cur = db.execute(f"INSERT INTO event_participants({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", list(cols.values()))
    claim = f"Participant: {_title(db, who)}" + (f" — {clean['role']}" if clean.get("role") else "")
    store_sources(db, ev["id"], clean.get("sources"), actor_id, field="participants", claim=claim)
    for e in (ev, who):
        entities.add_revision(db, e["id"], actor_id, "Event participant added", submission_id=submission_id)
    audit.log(db, actor_id, "participation.published", "event_participant", cur.lastrowid, {"submission": submission_id})
    return cur.lastrowid


APPLY_LINK = {"relationship": apply_relationship, "affiliation": apply_affiliation,
              "membership": apply_membership, "participation": apply_participation}
