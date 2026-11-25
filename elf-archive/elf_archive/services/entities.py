"""Canonical entity registry: permanent ids, slugs (with redirect history), names, revisions,
publication state. Subtype data lives in per-kind tables; this module owns the shared part."""
import json
import secrets

from . import audit
from .names import normalize, slugify
from .timeutil import now_iso

# The ONE definition of "publicly visible". Every public query must use it.
PUBLIC_WHERE = ("e.publication_status = 'published' AND e.visibility = 'public' "
                "AND e.deleted_at IS NULL AND e.merged_into IS NULL")

KIND_TABLE = {"person": "people", "family": "families", "place": "places", "event": "events",
              "organization": "organizations", "source": "sources", "archive_item": "archive_items",
              "collection": "collections", "oral_history": "oral_histories"}
TITLE_COL = {"person": "preferred_name", "family": "display_name", "place": "primary_name",
             "event": "title", "organization": "name", "source": "title", "archive_item": "title",
             "collection": "title", "oral_history": "title"}
SUMMARY_COL = {"person": "summary", "family": "summary", "place": "overview", "event": "summary",
               "organization": "description", "source": None, "archive_item": "description",
               "collection": "description", "oral_history": "summary"}
ID_PREFIX = {"person": "per", "family": "fam", "place": "plc", "event": "evt", "organization": "org",
             "source": "src", "archive_item": "itm", "collection": "col", "oral_history": "ora"}
URL_SECTION = {"person": "people", "family": "families", "place": "places", "event": "events",
               "source": "sources", "archive_item": "archive", "collection": "collections",
               "oral_history": "oral-histories", "organization": "organizations"}
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_public_id(db, kind):
    while True:
        pid = f"{ID_PREFIX[kind]}-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))
        if not db.execute("SELECT 1 FROM entities WHERE public_id=?", (pid,)).fetchone():
            return pid


def unique_slug(db, kind, base, exclude_id=None):
    slug, n = base, 2
    while True:
        r = db.execute("SELECT id FROM entities WHERE kind=? AND slug=?", (kind, slug)).fetchone()
        h = db.execute("SELECT entity_id FROM entity_slug_history WHERE kind=? AND slug=?", (kind, slug)).fetchone()
        owner = (r and r["id"]) or (h and h["entity_id"])
        if not owner or owner == exclude_id:
            return slug
        slug = f"{base}-{n}"
        n += 1


def create_entity(db, kind, title, *, created_by=None, status="draft", visibility="private", fictional=False):
    pid = new_public_id(db, kind)
    slug = unique_slug(db, kind, slugify(title, pid))
    cur = db.execute(
        "INSERT INTO entities(kind, public_id, slug, publication_status, visibility, is_fictional_test, created_by) "
        "VALUES (?,?,?,?,?,?,?)", (kind, pid, slug, status, visibility, int(fictional), created_by))
    return cur.lastrowid, pid, slug


def add_name(db, entity_id, name, name_type, language=None, note=None):
    name = (name or "").strip()
    if not name:
        return
    db.execute("INSERT OR IGNORE INTO entity_names(entity_id, name, normalized, name_type, language, note) "
               "VALUES (?,?,?,?,?,?)", (entity_id, name, normalize(name), name_type, language, note))


def change_slug(db, entity_id, new_slug, actor_id=None):
    e = get(db, entity_id)
    new_slug = unique_slug(db, e["kind"], slugify(new_slug, e["public_id"]), exclude_id=entity_id)
    if new_slug == e["slug"]:
        return new_slug
    db.execute("INSERT OR REPLACE INTO entity_slug_history(kind, slug, entity_id) VALUES (?,?,?)",
               (e["kind"], e["slug"], entity_id))
    db.execute("DELETE FROM entity_slug_history WHERE kind=? AND slug=?", (e["kind"], new_slug))
    db.execute("UPDATE entities SET slug=?, updated_at=? WHERE id=?", (new_slug, now_iso(), entity_id))
    audit.log(db, actor_id, "entity.slug_changed", "entity", e["public_id"], {"from": e["slug"], "to": new_slug})
    return new_slug


def get(db, entity_id):
    return db.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()


def get_by_public_id(db, public_id):
    return db.execute("SELECT * FROM entities WHERE public_id=?", (public_id,)).fetchone()


def get_public_by_public_id(db, public_id, kind=None):
    q = f"SELECT e.* FROM entities e WHERE e.public_id=? AND {PUBLIC_WHERE}"
    args = [public_id]
    if kind:
        q += " AND e.kind=?"
        args.append(kind)
    return db.execute(q, args).fetchone()


def title_of(db, entity_id):
    e = get(db, entity_id)
    if not e:
        return None
    return db.execute(f"SELECT {TITLE_COL[e['kind']]} AS t FROM {KIND_TABLE[e['kind']]} WHERE entity_id=?",
                      (entity_id,)).fetchone()["t"]


def subtype_row(db, entity_id):
    e = get(db, entity_id)
    return db.execute(f"SELECT * FROM {KIND_TABLE[e['kind']]} WHERE entity_id=?", (entity_id,)).fetchone()


def resolve_public(db, kind, slug):
    """('ok', entity) | ('redirect', entity) | None. Non-public records resolve to None (-> 404),
    so the existence of private records is never revealed."""
    row = db.execute(f"SELECT e.* FROM entities e WHERE e.kind=? AND e.slug=? AND {PUBLIC_WHERE}", (kind, slug)).fetchone()
    if row:
        return "ok", row
    raw = db.execute("SELECT * FROM entities WHERE kind=? AND slug=?", (kind, slug)).fetchone()
    if raw is None:
        h = db.execute("SELECT entity_id FROM entity_slug_history WHERE kind=? AND slug=?", (kind, slug)).fetchone()
        raw = get(db, h["entity_id"]) if h else None
    seen = set()
    while raw is not None and raw["merged_into"] and raw["id"] not in seen:   # follow merge tombstones
        seen.add(raw["id"])
        raw = get(db, raw["merged_into"])
    if raw is not None:
        pub = db.execute(f"SELECT e.* FROM entities e WHERE e.id=? AND {PUBLIC_WHERE}", (raw["id"],)).fetchone()
        if pub and pub["kind"] == kind and pub["slug"] != slug:
            return "redirect", pub
    return None


# ───────────── Revisions ─────────────
def snapshot(db, entity_id):
    e = dict(get(db, entity_id))
    sub = subtype_row(db, entity_id)
    names = [dict(r) for r in db.execute(
        "SELECT name, name_type, language FROM entity_names WHERE entity_id=? ORDER BY id", (entity_id,))]
    return {"entity": e, "data": dict(sub) if sub else None, "names": names}


def latest_revision_number(db, entity_id):
    r = db.execute("SELECT MAX(revision_number) AS n FROM revisions WHERE entity_id=?", (entity_id,)).fetchone()
    return r["n"] or 0


def add_revision(db, entity_id, actor_id, summary, reason=None, submission_id=None):
    n = latest_revision_number(db, entity_id) + 1
    db.execute("INSERT INTO revisions(entity_id, revision_number, snapshot_json, change_summary, reason, actor_id, "
               "submission_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
               (entity_id, n, json.dumps(snapshot(db, entity_id), ensure_ascii=False, default=str),
                summary, reason, actor_id, submission_id, now_iso()))
    return n


def set_state(db, entity_id, *, status=None, visibility=None, actor_id=None, reason=None):
    """Change publication state/visibility with revision + audit + search-index maintenance."""
    from . import search  # local import: search depends on this module
    e = get(db, entity_id)
    status = status or e["publication_status"]
    visibility = visibility or e["visibility"]
    db.execute("UPDATE entities SET publication_status=?, visibility=?, updated_at=? WHERE id=?",
               (status, visibility, now_iso(), entity_id))
    add_revision(db, entity_id, actor_id, f"State changed: {e['publication_status']}/{e['visibility']} → {status}/{visibility}", reason)
    audit.log(db, actor_id, "entity.state_changed", "entity", e["public_id"],
              {"from": [e["publication_status"], e["visibility"]], "to": [status, visibility], "reason": reason})
    search.reindex(db, entity_id)
