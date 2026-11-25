"""Curated explorations: an editor's saved selection of reviewed records about a period, a region or a theme,
with a description, the sources it rests on and the editor's name. It is a list of real records, not a
slideshow: what visitors see is always each record as it is now, and only while that record is public.

Rules:
- every record added must be published and public when it is added (checked here, on the server);
- a record that later becomes private, unpublished or merged simply drops out of the public view;
- an exploration with no public record left is not listed publicly;
- every change is audited."""
import re

from . import audit, entities, records
from .names import slugify
from .timeutil import now_iso

ITEM_KINDS = ("place", "event", "person", "family", "organization", "source", "archive_item", "oral_history", "collection")
MAX_ITEMS = 60


class ExplorationError(Exception):
    pass


def _year(v):
    v = (v or "").strip()
    if not v:
        return None
    if not re.fullmatch(r"\d{4}", v) or not 1000 <= int(v) <= 2100:
        raise ExplorationError("Give years as four digits, for example 1961.")
    return int(v)


def _items(db, text):
    """Lines of 'Name [per-abc12345]' or 'Name [per-abc12345] | why it is included'. Only public records."""
    out, seen = [], set()
    for line in (text or "").splitlines():
        ref, _, note = line.partition("|")
        if not ref.strip():
            continue
        m = records._PID_IN_BRACKETS.search(" ".join(ref.split())) or re.fullmatch(r"\s*([a-z]{3}-[a-z0-9]{8})\s*", ref)
        pid = m.group(1) if m else None
        e = entities.get_public_by_public_id(db, pid) if pid else None
        if not e or e["kind"] not in ITEM_KINDS:
            raise ExplorationError(f"“{ref.strip()[:80]}” is not a published, public record. Choose records from the suggestions.")
        if e["id"] in seen:
            continue
        seen.add(e["id"])
        out.append((e["id"], " ".join(note.split())[:500] or None))
    if len(out) > MAX_ITEMS:
        raise ExplorationError(f"An exploration can hold at most {MAX_ITEMS} records.")
    return out


def _values(db, form):
    title = " ".join((form.get("title") or "").split())[:200]
    description = (form.get("description") or "").strip()[:4000]
    if not title or not description:
        raise ExplorationError("Give the exploration a title and a description.")
    frm, to = _year(form.get("period_from")), _year(form.get("period_to"))
    if frm and to and frm > to:
        raise ExplorationError("The period must start before it ends.")
    items = _items(db, form.get("items"))
    published = int(form.get("is_published") == "1")
    if published and not items:
        raise ExplorationError("Add at least one record before publishing.")
    return {"title": title, "description": description, "sources_note": (form.get("sources_note") or "").strip()[:4000] or None,
            "period_from": frm, "period_to": to, "region": " ".join((form.get("region") or "").split())[:200] or None,
            "is_published": published}, items


def _unique_slug(db, title, own_id=None):
    base = slugify(title, "exploration")
    slug, n = base, 2
    while db.execute("SELECT 1 FROM explorations WHERE slug=? AND id IS NOT ?", (slug, own_id)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _set_items(db, xid, items):
    db.execute("DELETE FROM exploration_items WHERE exploration_id=?", (xid,))
    for pos, (eid, note) in enumerate(items, start=1):
        db.execute("INSERT INTO exploration_items(exploration_id, entity_id, position, note) VALUES (?,?,?,?)", (xid, eid, pos, note))


def create(db, editor, form):
    vals, items = _values(db, form)
    slug = _unique_slug(db, vals["title"])
    cur = db.execute(f"INSERT INTO explorations(slug, {', '.join(vals)}, created_by, updated_by) VALUES (?,{','.join('?' * len(vals))},?,?)",
                     (slug, *vals.values(), editor.id, editor.id))
    _set_items(db, cur.lastrowid, items)
    audit.log(db, editor.id, "exploration.created", "exploration", slug, {**vals, "items": len(items)})
    return cur.lastrowid


def update(db, editor, xid, form):
    old = db.execute("SELECT * FROM explorations WHERE id=?", (xid,)).fetchone()
    if not old:
        raise ExplorationError("Exploration not found.")
    vals, items = _values(db, form)
    db.execute(f"UPDATE explorations SET {', '.join(k + '=?' for k in vals)}, updated_by=?, updated_at=? WHERE id=?",
               (*vals.values(), editor.id, now_iso(), xid))
    _set_items(db, xid, items)
    audit.log(db, editor.id, "exploration.updated", "exploration", old["slug"],
              {"before": {k: old[k] for k in vals}, "after": vals, "items": len(items)})


def delete(db, editor, xid):
    old = db.execute("SELECT slug, title FROM explorations WHERE id=?", (xid,)).fetchone()
    if old:
        db.execute("DELETE FROM explorations WHERE id=?", (xid,))
        audit.log(db, editor.id, "exploration.deleted", "exploration", old["slug"], {"title": old["title"]})


def form_items(db, xid):
    """The items as the editing form shows them."""
    return "\n".join(f"{records.ref_label(db, r['public_id'])}" + (f" | {r['note']}" if r["note"] else "") for r in db.execute(
        "SELECT e.public_id, i.note FROM exploration_items i JOIN entities e ON e.id=i.entity_id WHERE i.exploration_id=? "
        "ORDER BY i.position", (xid,)))


def public_items(db, xid):
    """The exploration's records that are public NOW, in the editor's order, each with its title and address."""
    from ..queries import record_url
    from .entities import KIND_TABLE, PUBLIC_WHERE, TITLE_COL
    out = []
    for r in db.execute(f"SELECT e.id, e.kind, e.slug, e.public_id, e.is_fictional_test, i.note FROM exploration_items i "
                        f"JOIN entities e ON e.id=i.entity_id AND {PUBLIC_WHERE} WHERE i.exploration_id=? ORDER BY i.position",
                        (xid,)).fetchall():
        if r["kind"] == "archive_item":
            from ..queries import PUBLIC_ITEM
            if not db.execute(f"SELECT 1 FROM archive_items a WHERE a.entity_id=? AND {PUBLIC_ITEM}", (r["id"],)).fetchone():
                continue                       # its own access level or rights do not allow public display
        t = db.execute(f"SELECT {TITLE_COL[r['kind']]} AS t FROM {KIND_TABLE[r['kind']]} WHERE entity_id=?", (r["id"],)).fetchone()
        out.append({"id": r["public_id"], "kind": r["kind"], "title": t["t"], "url": record_url(r["kind"], r["slug"]),
                    "note": r["note"], "fictional": bool(r["is_fictional_test"])})
    return out


def published(db, slug=None):
    """Published explorations that still have at least one public record (or the one with this slug)."""
    rows = db.execute("SELECT x.*, COALESCE(u.display_name, u.username) AS curator FROM explorations x "
                      "LEFT JOIN users u ON u.id=x.created_by WHERE x.is_published=1" + (" AND x.slug=?" if slug else "")
                      + " ORDER BY x.period_from IS NULL, x.period_from, lower(x.title)", (slug,) if slug else ()).fetchall()
    out = []
    for r in rows:
        items = public_items(db, r["id"])
        if items:
            out.append({"x": r, "items": items})
    return out
