"""Spreadsheet (CSV) import with preview (spec §24.1).

1. An editor uploads a CSV for one kind of record. Nothing is created yet.
2. Every row is validated with exactly the same rules as the contribution forms. The preview shows
   each row's errors, possible duplicates already in the archive, and repeated rows within the file.
3. On confirmation, each valid row becomes a normal SUBMITTED contribution (tagged with the batch),
   so imported records still go through editorial review before anything is public. Invalid rows
   are skipped and listed.

Columns are the field names of the contribution form (a template can be downloaded). Inside a
cell, several aliases are separated by ";" and several sources by "||" (each source is
"Title | page or locator | URL").
"""
import csv
import io
import json

from . import duplicates, records, workflow
from .names import normalize
from ..db import tx

IMPORT_KINDS = ("person", "family", "place", "event", "organization", "source",
                "relationship", "affiliation", "membership", "participation")
MAX_ROWS = 2000
MAX_BYTES = 5 * 1024 * 1024
EXTRA_COLUMNS = ("contributor_note",)


class ImportError_(Exception):
    pass


def columns(kind):
    return [f.name for f in records.spec_for(kind)] + list(EXTRA_COLUMNS)


def template_csv(kind):
    buf = io.StringIO()
    csv.writer(buf).writerow(columns(kind))
    return "﻿" + buf.getvalue()           # BOM so spreadsheet programs open it as UTF-8 (Ge'ez, Arabic)


def _cell_to_form(f, value):
    v = (value or "").strip()
    if f.kind == "lines":
        return "\n".join(x.strip() for x in v.replace("\r", "").replace(";", "\n").split("\n") if x.strip())
    if f.kind == "sources":
        return "\n".join(x.strip() for x in v.replace("\r", "").replace("||", "\n").split("\n") if x.strip())
    return v


def parse(db, kind, data, filename=None):
    if kind not in IMPORT_KINDS:
        raise ImportError_("This kind of record cannot be imported.")
    if not data:
        raise ImportError_("Choose a CSV file to import.")
    if len(data) > MAX_BYTES:
        raise ImportError_("The file is too large (the limit is 5 MB). Split it into smaller files.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportError_("The file is not UTF-8 text. In your spreadsheet program, save it as “CSV UTF-8”.") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or []) if h is not None]
    known = set(columns(kind))
    unknown = [h for h in header if h and h not in known]
    spec = records.spec_for(kind)
    missing = [f.name for f in spec if f.required and f.name not in header]
    if not header:
        raise ImportError_("The file has no header row.")
    if unknown or missing:
        parts = []
        if unknown:
            parts.append("Unknown columns: " + ", ".join(unknown))
        if missing:
            parts.append("Missing required columns: " + ", ".join(missing))
        raise ImportError_(". ".join(parts) + ". Download the template to see the expected columns.")
    rows, seen = [], {}
    title_field = records.TITLE_FIELD.get(kind)
    for i, raw_row in enumerate(reader, start=2):          # line 1 is the header
        if i - 1 > MAX_ROWS:
            raise ImportError_(f"The file has more than {MAX_ROWS} rows. Split it into smaller files.")
        raw_row = {(k or "").strip(): v for k, v in raw_row.items()}
        if not any((v or "").strip() for v in raw_row.values() if isinstance(v, str)):
            continue                                        # blank line
        form = {f.name: _cell_to_form(f, raw_row.get(f.name)) for f in spec}
        clean, errors = records.validate(db, kind, form)
        warnings = []
        if not errors and title_field:
            key = normalize(clean[title_field])
            if key in seen:
                warnings.append(f"Same name as line {seen[key]} in this file.")
            seen.setdefault(key, i)
        if not errors and kind == "person":
            names = [clean.get("preferred_name"), clean.get("full_name")] + clean.get("aliases", [])
            by = (clean.get("birth") or {}).get("start")
            for c in duplicates.find_person_candidates(db, names, birth_year=by[:4] if by else None, limit=3):
                warnings.append(f"Possible duplicate of {c['name']} ({c['public_id']}): {c['why']}.")
        rows.append({"line": i, "form": {k: v for k, v in form.items() if v}, "data": None if errors else clean,
                     "errors": errors, "warnings": warnings, "note": (raw_row.get("contributor_note") or "").strip()[:3000]})
    if not rows:
        raise ImportError_("The file has no data rows.")
    return rows


def create_preview(db, user, kind, data, filename):
    rows = parse(db, kind, data, filename)
    valid = sum(1 for r in rows if r["data"] is not None)
    with tx(db):
        cur = db.execute("INSERT INTO imports(kind, filename, created_by, rows_json, total_rows, valid_rows) VALUES (?,?,?,?,?,?)",
                         (kind, (filename or "")[:200] or None, user.id, json.dumps(rows, ensure_ascii=False), len(rows), valid))
    return cur.lastrowid


def get(db, import_id):
    imp = db.execute("SELECT * FROM imports WHERE id=?", (import_id,)).fetchone()
    return (imp, json.loads(imp["rows_json"])) if imp else (None, None)


def confirm(db, user, import_id, *, config):
    """Turn every valid row into a submitted contribution for review. Returns how many were created."""
    imp, rows = get(db, import_id)
    if not imp or imp["status"] != "preview":
        raise ImportError_("This import has already been processed.")
    if imp["created_by"] != user.id:
        raise ImportError_("Only the editor who uploaded the file can confirm it.")
    created = 0
    with tx(db):
        for r in rows:
            if r["data"] is None:
                continue
            note = (f"Imported from {imp['filename'] or 'a CSV file'}, line {r['line']}." + (f" {r['note']}" if r["note"] else "")).strip()
            sid = workflow.create(db, user, imp["kind"], r["data"], contributor_note=note, config=config, bulk=True,
                                  import_batch_id=import_id)
            workflow.transition(db, user, sid, "submitted", config=config)
            created += 1
        db.execute("UPDATE imports SET status='created' WHERE id=?", (import_id,))
    return created


def discard(db, user, import_id):
    imp, _ = get(db, import_id)
    if not imp or imp["status"] != "preview":
        raise ImportError_("This import has already been processed.")
    with tx(db):
        db.execute("UPDATE imports SET status='discarded', rows_json='[]' WHERE id=?", (import_id,))


def bulk_publish(db, editor, sids, *, config):
    """Move each selected submission through review → approval → publication. Each one is checked
    exactly as if done by hand (permissions, own-work rule, references, photos). Returns (published, failures)."""
    published, failures = 0, []
    for sid in sids:
        s = db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        if not s:
            continue
        try:
            path = {"submitted": ("under_review", "approved", "published"), "under_review": ("approved", "published"),
                    "approved": ("published",)}.get(s["status"])
            if not path:
                raise workflow.WorkflowError(f"cannot be published from the state “{s['status']}”.")
            for to in path:
                workflow.transition(db, editor, sid, to, message="Approved in a batch review." if to == "approved" else None,
                                    config=config)
            published += 1
        except (workflow.WorkflowError, workflow.PermissionDenied) as e:
            failures.append((sid, workflow.title_for(db, s), str(e)))
    return published, failures
