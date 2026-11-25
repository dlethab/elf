"""Full-text search over PUBLIC records only (SQLite FTS5).

The index is rebuilt per entity whenever its state or content changes (`reindex`), and every query
re-checks PUBLIC_WHERE against the registry as defence in depth, so a stale index entry can never
surface a record that has since been unpublished or restricted. One row per entity: aliases are
folded into that row, so a person with five spellings is still one result."""
import difflib

from . import dates
from .entities import KIND_TABLE, PUBLIC_WHERE, SUMMARY_COL, TITLE_COL
from .names import normalize, tokens
from ..vocab import PUBLIC_RIGHTS

_BODY_COLS = {
    "person": ("summary", "biography", "occupation", "full_name"),
    "family": ("summary", "narrative", "region_note"),
    "place": ("overview", "country", "admin_region"),
    "event": ("summary", "description"),
    "source": ("creator", "publisher", "repository"),
    "organization": ("description",),
    "archive_item": ("description", "creator"),
    "collection": ("description",),
    "oral_history": ("summary", "topics", "interviewee_text", "interviewer_text"),
}
SEARCHABLE_KINDS = ("person", "family", "place", "event", "organization", "source", "archive_item", "oral_history", "collection")
# Archive items also need their OWN access level and rights to allow public display.
_PUBLIC_RIGHTS = ",".join(f"'{r}'" for r in PUBLIC_RIGHTS)
ITEM_OK = (f"(e.kind <> 'archive_item' OR EXISTS (SELECT 1 FROM archive_items a WHERE a.entity_id=e.id "
           f"AND a.access_level='public' AND a.rights_status IN ({_PUBLIC_RIGHTS})))")


def reindex(db, entity_id):
    db.execute("DELETE FROM search_fts WHERE rowid=?", (entity_id,))
    e = db.execute(f"SELECT e.* FROM entities e WHERE e.id=? AND {PUBLIC_WHERE} AND {ITEM_OK}", (entity_id,)).fetchone()
    if not e:
        return
    kind = e["kind"]
    sub = db.execute(f"SELECT * FROM {KIND_TABLE[kind]} WHERE entity_id=?", (entity_id,)).fetchone()
    if not sub:
        return
    title = normalize(sub[TITLE_COL[kind]])
    aliases = " ".join(r["normalized"] for r in db.execute("SELECT normalized FROM entity_names WHERE entity_id=?", (entity_id,)))
    body_parts = [str(sub[c]) for c in _BODY_COLS.get(kind, ()) if sub[c]]
    if kind == "oral_history" and sub["transcript_text"]:
        from . import oral                # the transcript is searchable only where it may be published
        if oral.allowed(db, entity_id)["publish_transcript"]:
            body_parts.append(sub["transcript_text"])
    body = normalize(" ".join(body_parts))
    db.execute("INSERT INTO search_fts(rowid, title, aliases, body) VALUES (?,?,?,?)", (entity_id, title, aliases, body))


def rebuild_all(db):
    db.execute("DELETE FROM search_fts")
    for r in db.execute("SELECT id FROM entities").fetchall():
        reindex(db, r["id"])


def _match_expr(q):
    toks = [t[:40] for t in tokens(q)[:8]]
    return " ".join(f'"{t}"*' for t in toks), toks


def _context(kind, sub):
    if kind == "person":
        b = dates.format_date(sub["birth_start"], sub["birth_end"], sub["birth_precision"])
        d = dates.format_date(sub["death_start"], sub["death_end"], sub["death_precision"])
        parts = [f"Born {b}" if b != "Unknown" else "", f"Died {d}" if d != "Unknown" else ""]
        return " · ".join(p for p in parts if p) or None
    if kind == "event":
        d = dates.format_date(sub["date_start"], sub["date_end"], sub["date_precision"])
        return None if d == "Unknown" else d
    if kind == "place":
        return sub["admin_region"] or sub["country"]
    return None


def search(db, q, *, kind=None, page=1, per_page=20):
    expr, toks = _match_expr(q)
    out = {"query": q, "results": [], "total": 0, "page": page, "per_page": per_page, "suggestions": []}
    if not expr:
        return out
    where = f"search_fts MATCH ? AND {PUBLIC_WHERE} AND {ITEM_OK}" + (" AND e.kind=?" if kind else "")
    args = [expr] + ([kind] if kind else [])
    out["total"] = db.execute(f"SELECT COUNT(*) FROM search_fts JOIN entities e ON e.id=search_fts.rowid WHERE {where}", args).fetchone()[0]
    rows = db.execute(
        f"SELECT e.id, e.kind, e.public_id, e.slug, e.is_fictional_test FROM search_fts JOIN entities e ON e.id=search_fts.rowid "
        f"WHERE {where} ORDER BY bm25(search_fts, 8.0, 5.0, 1.0), e.id LIMIT ? OFFSET ?",
        args + [per_page, (max(page, 1) - 1) * per_page]).fetchall()
    for r in rows:
        sub = db.execute(f"SELECT * FROM {KIND_TABLE[r['kind']]} WHERE entity_id=?", (r["id"],)).fetchone()
        summ = SUMMARY_COL[r["kind"]]
        text = (sub[summ] or "") if summ else ""
        matched = None
        title_norm = normalize(sub[TITLE_COL[r["kind"]]])
        if toks and not all(any(w.startswith(t) for w in title_norm.split()) for t in toks):
            for n in db.execute("SELECT name, normalized, name_type FROM entity_names WHERE entity_id=? AND name_type<>'preferred'",
                                (r["id"],)):
                if all(any(w.startswith(t) for w in n["normalized"].split()) for t in toks):
                    matched = f"{n['name']} ({n['name_type'].replace('_', ' ')})"
                    break
        out["results"].append({
            "kind": r["kind"], "public_id": r["public_id"], "slug": r["slug"],
            "title": sub[TITLE_COL[r["kind"]]], "summary": text[:240] + ("…" if len(text) > 240 else ""),
            "context": _context(r["kind"], sub), "matched_name": matched,
            "fictional": bool(r["is_fictional_test"]),
        })
    if out["total"] == 0:
        out["suggestions"] = suggest(db, q)
    return out


def suggest(db, q, limit=3):
    """'Did you mean' from known public names. Suggestions are shown as suggestions, never as results."""
    nq = normalize(q)
    if len(nq) < 3:
        return []
    names = db.execute(
        f"SELECT n.normalized, n.name, e.kind, e.slug FROM entity_names n JOIN entities e ON e.id=n.entity_id "
        f"WHERE {PUBLIC_WHERE} AND {ITEM_OK} LIMIT 20000").fetchall()
    by_norm = {}
    for n in names:
        by_norm.setdefault(n["normalized"], n)
    close = difflib.get_close_matches(nq, list(by_norm), n=limit, cutoff=0.75)
    return [{"name": by_norm[c]["name"], "kind": by_norm[c]["kind"], "slug": by_norm[c]["slug"]} for c in close]
