"""Curated collections of archive items (spec §10.5). Editors create and arrange them; a collection
page shows only the items that are themselves public, so a public collection never exposes a
restricted photo or document."""
from . import audit, entities, records, search
from .timeutil import now_iso


class CollectionError(Exception):
    pass


def _values(form):
    title = " ".join((form.get("title") or "").split())[:300]
    if not title:
        raise CollectionError("Give the collection a title.")
    vis = form.get("visibility") or "public"
    if vis not in ("public", "restricted"):
        raise CollectionError("Choose one of the listed options.")
    return {"title": title, "description": (form.get("description") or "").strip()[:20000] or None,
            "rights_note": (form.get("rights_note") or "").strip()[:2000] or None,
            "is_featured": int(form.get("is_featured") == "1")}, vis


def create(db, editor, form):
    vals, vis = _values(form)
    eid, pid, _ = entities.create_entity(db, "collection", vals["title"], created_by=editor.id, status="published", visibility=vis)
    db.execute("INSERT INTO collections(entity_id, title, description, rights_note, is_featured, created_by) VALUES (?,?,?,?,?,?)",
               (eid, vals["title"], vals["description"], vals["rights_note"], vals["is_featured"], editor.id))
    entities.add_name(db, eid, vals["title"], "preferred")
    entities.add_revision(db, eid, editor.id, "Collection created")
    audit.log(db, editor.id, "collection.created", "collection", pid, vals)
    search.reindex(db, eid)
    return pid


def update(db, editor, coll, form):
    vals, vis = _values(form)
    reason = " ".join((form.get("reason") or "").split())[:1000]
    if not reason:
        raise CollectionError("Please record a reason. It is kept in the audit log.")
    old = dict(entities.subtype_row(db, coll["id"]))
    db.execute("UPDATE collections SET title=?, description=?, rights_note=?, is_featured=? WHERE entity_id=?",
               (vals["title"], vals["description"], vals["rights_note"], vals["is_featured"], coll["id"]))
    if vals["title"] != old["title"]:
        db.execute("UPDATE OR IGNORE entity_names SET name_type='alternate_spelling' WHERE entity_id=? AND name_type='preferred'", (coll["id"],))
        db.execute("DELETE FROM entity_names WHERE entity_id=? AND name_type='preferred'", (coll["id"],))
        entities.add_name(db, coll["id"], vals["title"], "preferred")
    if vis != coll["visibility"]:
        entities.set_state(db, coll["id"], visibility=vis, actor_id=editor.id, reason=reason)
    entities.add_revision(db, coll["id"], editor.id, "Collection details updated", reason=reason)
    db.execute("UPDATE entities SET updated_at=? WHERE id=?", (now_iso(), coll["id"]))
    audit.log(db, editor.id, "collection.updated", "collection", coll["public_id"],
              {"before": {k: old[k] for k in vals}, "after": vals, "reason": reason})
    search.reindex(db, coll["id"])


def add_item(db, editor, coll, form):
    v = " ".join((form.get("item") or "").split())
    m = records._PID_IN_BRACKETS.search(v)
    pid = m.group(1) if m else v
    item = entities.get_by_public_id(db, pid)
    if not item or item["kind"] != "archive_item" or item["merged_into"] or item["deleted_at"]:
        raise CollectionError("That archive item was not found. Use its permanent ID, for example itm-abc12345.")
    if db.execute("SELECT 1 FROM collection_items WHERE collection_id=? AND item_id=?", (coll["id"], item["id"])).fetchone():
        raise CollectionError("This item is already in the collection.")
    pos = db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM collection_items WHERE collection_id=?", (coll["id"],)).fetchone()[0]
    db.execute("INSERT INTO collection_items(collection_id, item_id, position) VALUES (?,?,?)", (coll["id"], item["id"], pos))
    entities.add_revision(db, coll["id"], editor.id, "Item added to the collection")
    audit.log(db, editor.id, "collection.item_added", "collection", coll["public_id"], {"item": item["public_id"]})


def remove_item(db, editor, coll, item_id):
    db.execute("DELETE FROM collection_items WHERE collection_id=? AND item_id=?", (coll["id"], item_id))
    entities.add_revision(db, coll["id"], editor.id, "Item removed from the collection")
    audit.log(db, editor.id, "collection.item_removed", "collection", coll["public_id"], {"item_id": item_id})


def move_item(db, editor, coll, item_id, direction):
    rows = db.execute("SELECT item_id FROM collection_items WHERE collection_id=? ORDER BY position, item_id", (coll["id"],)).fetchall()
    order = [r["item_id"] for r in rows]
    if item_id not in order:
        return
    i = order.index(item_id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(order):
        order[i], order[j] = order[j], order[i]
    for pos, iid in enumerate(order, start=1):
        db.execute("UPDATE collection_items SET position=? WHERE collection_id=? AND item_id=?", (pos, coll["id"], iid))


def items(db, coll_id, public_only=True):
    from ..queries import PUBLIC_ITEM, _THUMB
    from .entities import PUBLIC_WHERE
    where = f"AND {PUBLIC_WHERE} AND {PUBLIC_ITEM}" if public_only else ""
    return db.execute(
        f"SELECT e.id, e.public_id, e.slug, e.visibility, e.is_fictional_test, a.title, a.media_kind, a.item_type, a.access_level, "
        f"a.created_start, a.created_end, a.created_precision, {_THUMB} AS thumb_key FROM collection_items ci "
        f"JOIN entities e ON e.id=ci.item_id JOIN archive_items a ON a.entity_id=e.id WHERE ci.collection_id=? {where} "
        f"ORDER BY ci.position, e.id", (coll_id,)).fetchall()


def public_list(db, featured_only=False, limit=200):
    from .entities import PUBLIC_WHERE
    rows = db.execute(f"SELECT e.id, e.slug, e.is_fictional_test, c.title, c.description, c.is_featured FROM entities e "
                      f"JOIN collections c ON c.entity_id=e.id WHERE e.kind='collection' AND {PUBLIC_WHERE}"
                      + (" AND c.is_featured=1" if featured_only else "") + " ORDER BY c.is_featured DESC, lower(c.title) LIMIT ?",
                      (limit,)).fetchall()
    out = []
    for r in rows:
        its = items(db, r["id"])
        if its:                      # a collection with nothing public in it is not listed publicly
            out.append({"row": r, "count": len(its), "cover": next((i for i in its if i["thumb_key"]), its[0])})
    return out
