"""Family trees and the connections explorer, computed from explicit, PUBLIC relationship records only.

Nothing is inferred: a line is drawn only where a published relationship, membership, affiliation,
participation or photo record exists, and each connection carries its explanation. People who are
not public (for example living people without consent) never appear, nor do their relationships.
Layout is computed on the server and rendered as SVG, so the views work without JavaScript.
"""
from collections import defaultdict, deque

from . import dates
from .entities import PUBLIC_WHERE
from ..vocab import DIRECTED_RELATIONSHIPS, RELATIONSHIP_TYPES

NODE_W, NODE_H, GAP_X, GAP_Y = 168, 54, 28, 70
PARENT_TYPES = DIRECTED_RELATIONSHIPS             # parent_of, adoptive_parent_of, step_parent_of, guardian_of
PARTNER_TYPES = ("spouse_of", "partner_of")
MAX_NODES = 150


def _pub(alias):
    return PUBLIC_WHERE.replace("e.", f"{alias}.")


def _person(db, pid):
    r = db.execute(f"SELECT e.id, e.public_id, e.slug, e.is_fictional_test, p.preferred_name, p.birth_start, p.birth_end, "
                   f"p.birth_precision, p.death_start, p.death_end, p.death_precision FROM entities e JOIN people p ON p.entity_id=e.id "
                   f"WHERE e.id=? AND {PUBLIC_WHERE}", (pid,)).fetchone()
    if not r:
        return None
    b = dates.format_date(r["birth_start"], r["birth_end"], r["birth_precision"])
    d = dates.format_date(r["death_start"], r["death_end"], r["death_precision"])
    life = "" if b == "Unknown" and d == "Unknown" else f"{'' if b == 'Unknown' else b}–{'' if d == 'Unknown' else d}"
    return {"id": r["id"], "public_id": r["public_id"], "slug": r["slug"], "name": r["preferred_name"], "life": life,
            "fictional": bool(r["is_fictional_test"])}


def _relationships(db, person_id):
    """Public relationships of one person where the other person is public too."""
    return db.execute(
        f"SELECT r.* FROM relationships r JOIN entities a ON a.id=r.person_a_id AND {_pub('a')} "
        f"JOIN entities b ON b.id=r.person_b_id AND {_pub('b')} WHERE (r.person_a_id=? OR r.person_b_id=?) "
        f"AND r.publication_status='published' AND r.visibility='public'", (person_id, person_id)).fetchall()


def _short(name, n=22):
    return name if len(name) <= n else name[:n - 1].rstrip() + "…"


def build_tree(db, root_ids, *, depth=3, members=None):
    """Nodes and edges reachable from the roots through public relationships, laid out by generation."""
    members = set(members or [])
    nodes, edges, seen_edges = {}, [], set()
    queue = deque((rid, 0) for rid in root_ids)
    while queue and len(nodes) < MAX_NODES:
        pid, d = queue.popleft()
        if pid in nodes:
            continue
        info = _person(db, pid)
        if not info:
            continue
        info["member"] = pid in members
        nodes[pid] = info
        if d >= depth:
            continue
        for r in _relationships(db, pid):
            if r["id"] not in seen_edges:
                seen_edges.add(r["id"])
                edges.append(r)
            other = r["person_b_id"] if r["person_a_id"] == pid else r["person_a_id"]
            if other not in nodes:
                queue.append((other, d + 1))
    edges = [e for e in edges if e["person_a_id"] in nodes and e["person_b_id"] in nodes]
    return _layout(nodes, edges, root_ids)


def _layout(nodes, edges, root_ids):
    if not nodes:
        return None
    # generations: a parent is one row above the child; partners and siblings share a row
    adj = defaultdict(list)
    for e in edges:
        a, b, t = e["person_a_id"], e["person_b_id"], e["relationship_type"]
        if t in PARENT_TYPES:
            adj[a].append((b, 1))
            adj[b].append((a, -1))
        elif t in PARTNER_TYPES or t == "sibling_of":
            adj[a].append((b, 0))
            adj[b].append((a, 0))
    gen = {}
    order = [r for r in root_ids if r in nodes] + [n for n in nodes if n not in root_ids]
    for start in order:
        if start in gen:
            continue
        gen[start] = 0
        q = deque([start])
        while q:
            cur = q.popleft()
            for nxt, delta in adj[cur]:
                if nxt not in gen:
                    gen[nxt] = gen[cur] + delta
                    q.append(nxt)
    low = min(gen.values())
    rows = defaultdict(list)
    for n in order:
        rows[gen[n] - low].append(n)

    parents_of = defaultdict(list)
    partners = defaultdict(set)
    for e in edges:
        if e["relationship_type"] in PARENT_TYPES:
            parents_of[e["person_b_id"]].append(e["person_a_id"])
        elif e["relationship_type"] in PARTNER_TYPES:
            partners[e["person_a_id"]].add(e["person_b_id"])
            partners[e["person_b_id"]].add(e["person_a_id"])

    # order each row: children under their parents (barycentre), partners side by side
    pos = {}
    for g in sorted(rows):
        row = rows[g]
        if g > 0:
            row.sort(key=lambda n: (sum(pos[p] for p in parents_of[n] if p in pos) / max(1, len([p for p in parents_of[n] if p in pos]))
                                    if any(p in pos for p in parents_of[n]) else 1e9))
        arranged = []
        for n in row:
            if n in arranged:
                continue
            arranged.append(n)
            for p in sorted(partners[n]):
                if p in row and p not in arranged:
                    arranged.append(p)
        rows[g] = arranged
        for i, n in enumerate(arranged):
            pos[n] = i
    widest = max(len(r) for r in rows.values())
    width = widest * (NODE_W + GAP_X) + GAP_X
    height = len(rows) * (NODE_H + GAP_Y) + GAP_Y
    for g, row in rows.items():
        offset = (width - len(row) * (NODE_W + GAP_X) + GAP_X) / 2
        for i, n in enumerate(row):
            nodes[n]["x"] = round(offset + i * (NODE_W + GAP_X))
            nodes[n]["y"] = round(GAP_Y / 2 + g * (NODE_H + GAP_Y))
            nodes[n]["gen"] = g
            nodes[n]["label"] = _short(nodes[n]["name"])

    lines = []
    drawn_children = set()
    for e in edges:
        a, b, t = nodes[e["person_a_id"]], nodes[e["person_b_id"]], e["relationship_type"]
        cls = f"edge edge--{t} edge--{e['status']}"
        if t in PARENT_TYPES:
            child = b
            parents = [nodes[p] for p in parents_of[e["person_b_id"]] if p in nodes]
            couple = len(parents) == 2 and parents[1]["id"] in partners[parents[0]["id"]] and t == "parent_of"
            if couple and (child["id"], "couple") in drawn_children:
                continue
            if couple:
                drawn_children.add((child["id"], "couple"))
                sx = (parents[0]["x"] + parents[1]["x"]) / 2 + NODE_W / 2
                sy = parents[0]["y"] + NODE_H / 2
            else:
                sx, sy = a["x"] + NODE_W / 2, a["y"] + NODE_H
            ex, ey = child["x"] + NODE_W / 2, child["y"]
            mid = ey - GAP_Y / 2
            lines.append({"d": f"M{sx:.0f},{sy:.0f} V{mid:.0f} H{ex:.0f} V{ey:.0f}", "cls": cls})
        elif t in PARTNER_TYPES or t == "sibling_of" or t == "other_documented":
            left, right = (a, b) if a["x"] <= b["x"] else (b, a)
            if left["y"] == right["y"]:
                y = left["y"] + (NODE_H / 2 if t in PARTNER_TYPES else -6)
                lines.append({"d": f"M{left['x'] + NODE_W:.0f},{y:.0f} H{right['x']:.0f}" if t in PARTNER_TYPES
                              else f"M{left['x'] + NODE_W / 2:.0f},{left['y']:.0f} V{y:.0f} H{right['x'] + NODE_W / 2:.0f} V{right['y']:.0f}",
                              "cls": cls})
            else:
                lines.append({"d": f"M{a['x'] + NODE_W / 2:.0f},{a['y'] + NODE_H / 2:.0f} L{b['x'] + NODE_W / 2:.0f},{b['y'] + NODE_H / 2:.0f}",
                              "cls": cls})
    table = []
    for e in edges:
        a, b, t = nodes[e["person_a_id"]], nodes[e["person_b_id"]], e["relationship_type"]
        table.append({"a": a, "label": RELATIONSHIP_TYPES[t][0], "b": b, "status": e["status"],
                      "period": dates.format_date(e["period_start"], e["period_end"], e["period_precision"]),
                      "period_start": e["period_start"], "period_end": e["period_end"], "period_precision": e["period_precision"],
                      "notes": e["notes"]})
    return {"nodes": list(nodes.values()), "lines": lines, "width": width, "height": height,
            "generations": [[nodes[n] for n in rows[g]] for g in sorted(rows)], "table": table,
            "node_w": NODE_W, "node_h": NODE_H, "truncated": len(nodes) >= MAX_NODES,
            "no_parents": [nodes[n] for n in nodes if not parents_of[n]]}


def family_tree(db, family_id):
    members = [r["person_id"] for r in db.execute(
        f"SELECT m.person_id FROM family_memberships m JOIN entities e ON e.id=m.person_id AND {PUBLIC_WHERE} "
        f"WHERE m.family_id=? AND m.publication_status='published' AND m.visibility='public' ORDER BY m.id", (family_id,))]
    return build_tree(db, members, depth=1, members=members) if members else None


def person_tree(db, person_id):
    return build_tree(db, [person_id], depth=3, members=[person_id])


# ───────────── connections explorer ─────────────
CATEGORIES = {
    "family": "Family relationship", "family_record": "Family record", "event": "Shared event",
    "organization": "Shared organization", "place": "Shared place", "document": "Shared photograph",
}


def network(db, person_id, per_hub=12):
    """A person, the records they are explicitly linked to, and other people linked to those same
    records. Each connection says how it is documented; none says that two people knew each other."""
    center = _person(db, person_id)
    if not center:
        return None
    hubs, people, rows = [], {}, []

    def add_person(pid, via_hub, category, explanation):
        p = _person(db, pid)
        if not p or pid == person_id:
            return
        people.setdefault(pid, {**p, "via": []})["via"].append(via_hub)
        rows.append({"record": p, "kind": "person", "category": category, "via": via_hub, "explanation": explanation})

    for r in _relationships(db, person_id):
        other = r["person_b_id"] if r["person_a_id"] == person_id else r["person_a_id"]
        label = RELATIONSHIP_TYPES[r["relationship_type"]][0 if r["person_a_id"] == person_id else 1]
        add_person(other, None, "family", f"{label} (relationship record{', ' + r['status'] if r['status'] != 'current' else ''})")

    def hub(kind, eid, slug, title, category, explanation, others_sql, args, other_expl):
        h = {"kind": kind, "id": eid, "slug": slug, "title": title, "category": category}
        hubs.append(h)
        rows.append({"record": h, "kind": kind, "category": category, "via": None, "explanation": explanation})
        for o in db.execute(others_sql, args).fetchall()[:per_hub]:
            add_person(o[0], h, category, other_expl)

    for r in db.execute(f"SELECT e.id, e.slug, f.display_name FROM family_memberships m JOIN entities e ON e.id=m.family_id AND {PUBLIC_WHERE} "
                        f"JOIN families f ON f.entity_id=e.id WHERE m.person_id=? AND m.publication_status='published' AND m.visibility='public'",
                        (person_id,)).fetchall():
        hub("family", r["id"], r["slug"], r["display_name"], "family_record", "Listed as a member of this family",
            "SELECT m.person_id FROM family_memberships m WHERE m.family_id=? AND m.person_id<>? AND m.publication_status='published' AND m.visibility='public'",
            (r["id"], person_id), f"Also a member of {r['display_name']}")
    for r in db.execute(f"SELECT e.id, e.slug, ev.title, x.role FROM event_participants x JOIN entities e ON e.id=x.event_id AND {PUBLIC_WHERE} "
                        f"JOIN events ev ON ev.entity_id=e.id WHERE x.person_id=? AND x.publication_status='published'", (person_id,)).fetchall():
        hub("event", r["id"], r["slug"], r["title"], "event", "Documented as a participant" + (f" ({r['role']})" if r["role"] else ""),
            "SELECT x.person_id FROM event_participants x WHERE x.event_id=? AND x.person_id IS NOT NULL AND x.person_id<>? AND x.publication_status='published'",
            (r["id"], person_id), f"Also documented as a participant in {r['title']}")
    for r in db.execute(f"SELECT DISTINCT e.id, e.slug, o.name FROM affiliations a JOIN entities e ON e.id=a.organization_id AND {PUBLIC_WHERE} "
                        f"JOIN organizations o ON o.entity_id=e.id WHERE a.person_id=? AND a.publication_status='published' AND a.visibility='public'",
                        (person_id,)).fetchall():
        hub("organization", r["id"], r["slug"], r["name"], "organization", "Documented affiliation",
            "SELECT DISTINCT a.person_id FROM affiliations a WHERE a.organization_id=? AND a.person_id<>? AND a.publication_status='published' AND a.visibility='public'",
            (r["id"], person_id), f"Also affiliated with {r['name']}. This does not mean they knew each other.")
    for r in db.execute(f"SELECT DISTINCT e.id, e.slug, pl.primary_name, (p.birth_place_id=e.id) AS born FROM people p "
                        f"JOIN entities e ON e.id IN (p.birth_place_id, p.death_place_id) AND {PUBLIC_WHERE} JOIN places pl ON pl.entity_id=e.id "
                        f"WHERE p.entity_id=?", (person_id,)).fetchall():
        hub("place", r["id"], r["slug"], r["primary_name"], "place", "Birthplace" if r["born"] else "Place of death",
            "SELECT p.entity_id FROM people p WHERE (p.birth_place_id=? OR p.death_place_id=?) AND p.entity_id<>?",
            (r["id"], r["id"], person_id), f"Also born or died in {r['primary_name']}. This does not mean they knew each other.")
    for r in db.execute(f"SELECT e.id, e.slug, a.title FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND {PUBLIC_WHERE} "
                        f"JOIN archive_items a ON a.entity_id=e.id AND a.access_level='public' WHERE s.subject_id=?", (person_id,)).fetchall():
        hub("archive_item", r["id"], r["slug"], r["title"], "document", "Shown or documented in this photograph",
            "SELECT s.subject_id FROM archive_item_subjects s JOIN entities x ON x.id=s.subject_id AND x.kind='person' WHERE s.item_id=? AND s.subject_id<>?",
            (r["id"], person_id), f"Also linked to the photograph {r['title']}")

    return _radial(center, hubs, people, rows)


def _radial(center, hubs, people, rows):
    import math
    R1, R2 = 230, 420
    size = 2 * (R2 + 140)
    cx = cy = size / 2
    direct = [p for p in people.values() if None in p["via"]]
    ring1 = [("hub", h) for h in hubs] + [("person", p) for p in direct]
    n1 = max(1, len(ring1))
    angle = {}
    placed = []
    for i, (kind, item) in enumerate(ring1):
        a = 2 * math.pi * i / n1 - math.pi / 2
        x, y = cx + R1 * math.cos(a), cy + R1 * math.sin(a)
        key = (kind, item["id"])
        angle[key] = a
        placed.append({"kind": "person" if kind == "person" else item["kind"], "item": item, "x": round(x), "y": round(y),
                       "category": "family" if kind == "person" else item["category"], "ring": 1})
    ring2 = [p for p in people.values() if None not in p["via"]]
    by_hub = defaultdict(list)
    for p in ring2:
        by_hub[p["via"][0]["id"]].append(p)
    for hid, ps in by_hub.items():
        base = angle.get(("hub", hid), 0)
        spread = min(math.pi / 3, 2 * math.pi / n1)
        for j, p in enumerate(ps):
            a = base + (spread * (j - (len(ps) - 1) / 2) / max(1, len(ps)))
            placed.append({"kind": "person", "item": p, "x": round(cx + R2 * math.cos(a)), "y": round(cy + R2 * math.sin(a)),
                           "category": p["via"][0]["category"], "ring": 2, "hub": hid})
    pos = {(n["kind"] if n["kind"] == "person" else "hub", n["item"]["id"]): n for n in placed}
    lines = []
    for n in placed:
        if n["ring"] == 1:
            lines.append({"x1": cx, "y1": cy, "x2": n["x"], "y2": n["y"], "cat": n["category"]})
        else:
            h = pos.get(("hub", n["hub"]))
            if h:
                lines.append({"x1": h["x"], "y1": h["y"], "x2": n["x"], "y2": n["y"], "cat": n["category"]})
    for n in placed:
        n["label"] = _short(n["item"].get("name") or n["item"].get("title") or "", 26)
    # fit the drawing to its content (labels extend about 90px either side and 45px below a node)
    xs = [cx] + [n["x"] for n in placed]
    ys = [cy] + [n["y"] for n in placed]
    pad_x, pad_top, pad_bottom = 100, 40, 60
    dx, dy = pad_x - min(xs), pad_top - min(ys)
    for n in placed:
        n["x"] += dx
        n["y"] += dy
    for ln in lines:
        ln["x1"] += dx
        ln["x2"] += dx
        ln["y1"] += dy
        ln["y2"] += dy
    w = round(max(xs) - min(xs) + 2 * pad_x)
    h = round(max(ys) - min(ys) + pad_top + pad_bottom)
    return {"center": {**center, "x": cx + dx, "y": cy + dy, "label": _short(center["name"], 26)}, "nodes": placed,
            "lines": lines, "w": w, "h": h, "rows": rows, "categories": CATEGORIES}
