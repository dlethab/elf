"""Read-side queries for PUBLIC pages. Every query goes through PUBLIC_WHERE; confidential columns
(research_notes, editor notes) are never selected here."""
from .services import dates
from .services.entities import KIND_TABLE, PUBLIC_WHERE, SUMMARY_COL, TITLE_COL, URL_SECTION
from .vocab import PUBLIC_RIGHTS, RELATIONSHIP_TYPES

PER_PAGE = 24
# An archive item is shown publicly only when the record is public AND its own access level and
# rights allow it. Checked separately from the record it illustrates.
_RIGHTS_IN = "(" + ",".join(f"'{r}'" for r in PUBLIC_RIGHTS) + ")"
PUBLIC_ITEM = f"a.access_level = 'public' AND a.rights_status IN {_RIGHTS_IN}"

# PUBLIC_WHERE written against a different table alias.
def _pub(alias):
    return PUBLIC_WHERE.replace("e.", f"{alias}.")


def record_url(kind, slug):
    return f"/{URL_SECTION[kind]}/{slug}"


def media_url(key):
    return f"/media/{key}"


_THUMB = "(SELECT m.storage_key FROM media_files m WHERE m.owner_id=e.id AND m.file_role='thumbnail' LIMIT 1)"
_DISPLAY = "(SELECT m.storage_key FROM media_files m WHERE m.owner_id=e.id AND m.file_role='access_derivative' LIMIT 1)"


def record_photos(db, subject_id):
    """Public photographs linked to a record."""
    return db.execute(
        f"SELECT e.slug, a.title, a.media_kind, a.item_type, a.created_start, a.created_end, a.created_precision, {_THUMB} AS thumb_key, "
        f"a.creator, a.rights_holder, a.rights_status, {_DISPLAY} AS display_key "
        f"FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND {PUBLIC_WHERE} "
        f"JOIN archive_items a ON a.entity_id=e.id AND {PUBLIC_ITEM} WHERE s.subject_id=? ORDER BY e.id LIMIT 60",
        (subject_id,)).fetchall()


def list_archive(db, page=1):
    where = f"e.kind='archive_item' AND {PUBLIC_WHERE} AND {PUBLIC_ITEM}"
    total = db.execute(f"SELECT COUNT(*) FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE {where}").fetchone()[0]
    rows = db.execute(
        f"SELECT e.slug, e.is_fictional_test, a.title, a.media_kind, a.item_type, a.created_start, a.created_end, a.created_precision, {_THUMB} AS thumb_key "
        f"FROM entities e JOIN archive_items a ON a.entity_id=e.id WHERE {where} ORDER BY e.id DESC LIMIT ? OFFSET ?",
        (PER_PAGE, (max(page, 1) - 1) * PER_PAGE)).fetchall()
    return rows, total


def archive_item(db, entity_id, allow_restricted=False):
    """The item with its display file, or None when the item itself may not be shown publicly
    (unless the caller has already established research access)."""
    return db.execute(
        "SELECT a.*, (SELECT m.storage_key FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='access_derivative' LIMIT 1) "
        "AS display_key, (SELECT m.width FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='access_derivative' LIMIT 1) AS w, "
        "(SELECT m.height FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='access_derivative' LIMIT 1) AS h, "
        "(SELECT m.storage_key FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='original' LIMIT 1) AS original_key, "
        "(SELECT m.size_bytes FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='original' LIMIT 1) AS original_size, "
        "(SELECT m.mime_type FROM media_files m WHERE m.owner_id=a.entity_id AND m.file_role='original' LIMIT 1) AS original_mime, "
        "u.display_name, u.username, u.attribution_pref "
        "FROM archive_items a LEFT JOIN users u ON u.id=a.uploaded_by AND u.anonymized_at IS NULL "
        "WHERE a.entity_id=?" + ("" if allow_restricted else f" AND {PUBLIC_ITEM}"), (entity_id,)).fetchone()


def item_subjects(db, item_id):
    out = []
    for r in db.execute(f"SELECT e.id, e.kind, e.slug FROM archive_item_subjects s JOIN entities e ON e.id=s.subject_id "
                        f"AND {PUBLIC_WHERE} WHERE s.item_id=? ORDER BY e.kind, e.id", (item_id,)).fetchall():
        t = db.execute(f"SELECT {TITLE_COL[r['kind']]} AS t FROM {KIND_TABLE[r['kind']]} WHERE entity_id=?", (r["id"],)).fetchone()
        out.append({"kind": r["kind"], "url": record_url(r["kind"], r["slug"]), "title": t["t"]})
    return out


def list_public(db, kind, page=1, letter=None):
    t, title, summ = KIND_TABLE[kind], TITLE_COL[kind], SUMMARY_COL[kind]
    where, args = f"e.kind=? AND {PUBLIC_WHERE}", [kind]
    if letter:
        where += f" AND upper(substr(t.{title},1,1))=?"
        args.append(letter)
    total = db.execute(f"SELECT COUNT(*) FROM entities e JOIN {t} t ON t.entity_id=e.id WHERE {where}", args).fetchone()[0]
    sel = f"t.{summ} AS summary_text," if summ else "NULL AS summary_text,"
    rows = db.execute(
        f"SELECT e.public_id, e.slug, e.is_fictional_test, t.{title} AS title, {sel} t.* "
        f"FROM entities e JOIN {t} t ON t.entity_id=e.id WHERE {where} "
        f"ORDER BY lower(t.{title}), e.id LIMIT ? OFFSET ?", args + [PER_PAGE, (max(page, 1) - 1) * PER_PAGE]).fetchall()
    return rows, total


def sub(db, entity_id, kind):
    return db.execute(f"SELECT * FROM {KIND_TABLE[kind]} WHERE entity_id=?", (entity_id,)).fetchone()


def names(db, entity_id):
    return db.execute("SELECT name, name_type, language FROM entity_names WHERE entity_id=? AND name_type<>'preferred' ORDER BY id",
                      (entity_id,)).fetchall()


def citations(db, entity_id):
    return db.execute(
        f"SELECT c.field_name, c.claim_text, c.locator, c.explanation, c.evidence_status, s.title, s.source_type, "
        f"s.creator, s.url, se.slug AS source_slug FROM citations c JOIN entities se ON se.id=c.source_id AND {_pub('se')} "
        f"JOIN sources s ON s.entity_id=se.id WHERE c.target_id=? ORDER BY c.id", (entity_id,)).fetchall()


def cited_by(db, source_id):
    """Public records that cite a source."""
    out = []
    for r in db.execute(f"SELECT DISTINCT e.id, e.kind, e.slug, c.locator FROM citations c JOIN entities e ON e.id=c.target_id "
                        f"AND {PUBLIC_WHERE} WHERE c.source_id=? ORDER BY e.kind, e.id", (source_id,)).fetchall():
        t = db.execute(f"SELECT {TITLE_COL[r['kind']]} AS t FROM {KIND_TABLE[r['kind']]} WHERE entity_id=?", (r["id"],)).fetchone()
        out.append({"kind": r["kind"], "url": record_url(r["kind"], r["slug"]), "title": t["t"], "locator": r["locator"]})
    return out


def accounts(db, entity_id):
    return db.execute("SELECT topic, account_text, attributed_to, basis_note, needs_research, concerns_date, concerns_location FROM conflicting_accounts "
                      "WHERE entity_id=? AND is_public=1 ORDER BY id", (entity_id,)).fetchall()


def public_revisions(db, entity_id):
    """Public change history: date and summary only. No actor identities, reasons or snapshots."""
    return db.execute("SELECT revision_number, change_summary, created_at FROM revisions WHERE entity_id=? ORDER BY revision_number DESC",
                      (entity_id,)).fetchall()


def person_relationships(db, person_id):
    out = []
    rows = db.execute(
        "SELECT r.*, (r.person_a_id=?) AS viewer_is_a FROM relationships r WHERE (r.person_a_id=? OR r.person_b_id=?) "
        "AND r.publication_status='published' AND r.visibility='public'", (person_id,) * 3).fetchall()
    for r in rows:
        other = r["person_b_id"] if r["viewer_is_a"] else r["person_a_id"]
        o = db.execute(f"SELECT e.public_id, e.slug, p.preferred_name FROM entities e JOIN people p ON p.entity_id=e.id "
                       f"WHERE e.id=? AND {PUBLIC_WHERE}", (other,)).fetchone()
        if not o:   # relationship to a non-public person is never revealed
            continue
        labels = RELATIONSHIP_TYPES[r["relationship_type"]]
        out.append({"label": labels[0] if r["viewer_is_a"] else labels[1], "status": r["status"], "notes": r["notes"],
                    "period": dates.format_date(r["period_start"], r["period_end"], r["period_precision"]),
                    "period_start": r["period_start"], "period_end": r["period_end"],
                    "period_precision": r["period_precision"],
                    "name": o["preferred_name"], "url": record_url("person", o["slug"])})
    return out


def person_families(db, person_id):
    return db.execute(
        f"SELECT e.slug, f.display_name, m.role_note FROM family_memberships m JOIN entities e ON e.id=m.family_id AND {PUBLIC_WHERE} "
        f"JOIN families f ON f.entity_id=e.id WHERE m.person_id=? AND m.publication_status='published' AND m.visibility='public'",
        (person_id,)).fetchall()


def person_events(db, person_id):
    return db.execute(
        f"SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, p.role, p.evidence_status FROM event_participants p "
        f"JOIN entities e ON e.id=p.event_id AND {PUBLIC_WHERE} JOIN events ev ON ev.entity_id=e.id "
        f"WHERE p.person_id=? AND p.publication_status='published' ORDER BY ev.date_start", (person_id,)).fetchall()


def place_link(db, place_id):
    if not place_id:
        return None
    return db.execute(f"SELECT e.slug, p.primary_name FROM entities e JOIN places p ON p.entity_id=e.id WHERE e.id=? AND {PUBLIC_WHERE}",
                      (place_id,)).fetchone()


def family_members(db, family_id):
    return db.execute(
        f"SELECT e.slug, p.preferred_name, m.role_note FROM family_memberships m JOIN entities e ON e.id=m.person_id AND {PUBLIC_WHERE} "
        f"JOIN people p ON p.entity_id=e.id WHERE m.family_id=? AND m.publication_status='published' AND m.visibility='public' "
        f"ORDER BY p.preferred_name", (family_id,)).fetchall()


def place_events(db, place_id):
    return db.execute(
        f"SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, ep.is_uncertain FROM event_places ep "
        f"JOIN entities e ON e.id=ep.event_id AND {PUBLIC_WHERE} JOIN events ev ON ev.entity_id=e.id WHERE ep.place_id=? "
        f"ORDER BY ev.date_start", (place_id,)).fetchall()


def place_people(db, place_id):
    return db.execute(
        f"SELECT e.slug, p.preferred_name, (p.birth_place_id=?) AS born, (p.death_place_id=?) AS died FROM people p "
        f"JOIN entities e ON e.id=p.entity_id AND {PUBLIC_WHERE} WHERE p.birth_place_id=? OR p.death_place_id=? "
        f"ORDER BY p.preferred_name", (place_id,) * 4).fetchall()


def event_participants(db, event_id):
    """People and organizations that took part, each only if their own record is public."""
    return db.execute(
        f"SELECT 'person' AS kind, e.slug, p.preferred_name AS name, ep.role, ep.evidence_status FROM event_participants ep "
        f"JOIN entities e ON e.id=ep.person_id AND {PUBLIC_WHERE} JOIN people p ON p.entity_id=e.id "
        f"WHERE ep.event_id=? AND ep.publication_status='published' "
        f"UNION ALL SELECT 'organization', e.slug, o.name, ep.role, ep.evidence_status FROM event_participants ep "
        f"JOIN entities e ON e.id=ep.organization_id AND {PUBLIC_WHERE} JOIN organizations o ON o.entity_id=e.id "
        f"WHERE ep.event_id=? AND ep.publication_status='published' ORDER BY 1 DESC, 3", (event_id, event_id)).fetchall()


_AFF_COLS = "a.role, a.period_start, a.period_end, a.period_precision, a.evidence_status, a.notes"


def person_affiliations(db, person_id):
    return db.execute(
        f"SELECT {_AFF_COLS}, oe.slug, o.name, ple.slug AS place_slug, pl.primary_name AS place_name FROM affiliations a "
        f"JOIN entities oe ON oe.id=a.organization_id AND {_pub('oe')} JOIN organizations o ON o.entity_id=oe.id "
        f"LEFT JOIN entities ple ON ple.id=a.place_id AND {_pub('ple')} LEFT JOIN places pl ON pl.entity_id=ple.id "
        f"WHERE a.person_id=? AND a.publication_status='published' AND a.visibility='public' "
        f"ORDER BY a.period_start IS NULL, a.period_start, o.name", (person_id,)).fetchall()


def org_members(db, org_id):
    return db.execute(
        f"SELECT {_AFF_COLS}, pe.slug, p.preferred_name AS name FROM affiliations a "
        f"JOIN entities pe ON pe.id=a.person_id AND {_pub('pe')} JOIN people p ON p.entity_id=pe.id "
        f"WHERE a.organization_id=? AND a.publication_status='published' AND a.visibility='public' "
        f"ORDER BY p.preferred_name, a.period_start", (org_id,)).fetchall()


def org_events(db, org_id):
    return db.execute(
        f"SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, p.role, p.evidence_status FROM event_participants p "
        f"JOIN entities e ON e.id=p.event_id AND {PUBLIC_WHERE} JOIN events ev ON ev.entity_id=e.id "
        f"WHERE p.organization_id=? AND p.publication_status='published' ORDER BY ev.date_start", (org_id,)).fetchall()


def event_places_for(db, event_id):
    return db.execute(
        f"SELECT e.slug, p.primary_name, ep.is_uncertain, p.latitude, p.coord_precision FROM event_places ep "
        f"JOIN entities e ON e.id=ep.place_id AND {PUBLIC_WHERE} JOIN places p ON p.entity_id=e.id WHERE ep.event_id=?",
        (event_id,)).fetchall()


def timeline(db, f=None):
    """Public events, dated ones in order, undated ones listed separately (never given a false date).
    Filters (all optional): type (event type slug), place / person / organization (permanent id),
    q (words in the title or summary), from / to (years; an event matches if its span overlaps)."""
    f = f or {}
    where, args = ["e.kind='event'", PUBLIC_WHERE], []
    if f.get("type"):
        where.append("t.slug=?")
        args.append(f["type"])
    for key, sql in (("place", "EXISTS (SELECT 1 FROM event_places x JOIN entities xe ON xe.id=x.place_id WHERE x.event_id=e.id AND xe.public_id=?)"),
                     ("person", "EXISTS (SELECT 1 FROM event_participants x JOIN entities xe ON xe.id=x.person_id WHERE x.event_id=e.id AND x.publication_status='published' AND xe.public_id=?)"),
                     ("organization", "EXISTS (SELECT 1 FROM event_participants x JOIN entities xe ON xe.id=x.organization_id WHERE x.event_id=e.id AND x.publication_status='published' AND xe.public_id=?)")):
        if f.get(key):
            where.append(sql)
            args.append(f[key])
    if f.get("region"):
        where.append(f"EXISTS (SELECT 1 FROM event_places x JOIN entities xe ON xe.id=x.place_id AND {_pub('xe')} "
                     f"JOIN places xp ON xp.entity_id=xe.id WHERE x.event_id=e.id AND xp.admin_region=?)")
        args.append(f["region"])
    if f.get("media"):        # photographs, documents or recordings about the event that the public may see
        where.append(f"(EXISTS (SELECT 1 FROM archive_item_subjects s JOIN entities ie ON ie.id=s.item_id AND {_pub('ie')} "
                     f"JOIN archive_items a ON a.entity_id=ie.id AND {PUBLIC_ITEM} WHERE s.subject_id=e.id) "
                     f"OR EXISTS (SELECT 1 FROM oral_history_subjects s JOIN entities oe ON oe.id=s.oral_history_id AND {_pub('oe')} WHERE s.subject_id=e.id))")
    if f.get("q"):
        where.append("(lower(ev.title) LIKE ? OR lower(COALESCE(ev.summary,'')) LIKE ?)")
        args += [f"%{f['q'].lower()}%"] * 2
    if f.get("from"):
        where.append("ev.date_precision<>'unknown' AND CAST(substr(COALESCE(ev.date_end, ev.date_start),1,4) AS INTEGER) >= ?")
        args.append(int(f["from"]))
    if f.get("to"):
        where.append("ev.date_precision<>'unknown' AND CAST(substr(ev.date_start,1,4) AS INTEGER) <= ?")
        args.append(int(f["to"]))
    rows = db.execute(
        f"SELECT e.slug, e.public_id, e.is_fictional_test, ev.title, ev.summary, ev.date_start, ev.date_end, ev.date_precision, "
        f"t.label AS type_label, t.slug AS type_slug FROM entities e JOIN events ev ON ev.entity_id=e.id "
        f"LEFT JOIN event_types t ON t.id=ev.event_type_id WHERE {' AND '.join(where)} "
        f"ORDER BY ev.date_start IS NULL, ev.date_start, lower(ev.title) LIMIT 2000", args).fetchall()
    rows = [dict(r, places=[]) for r in rows]
    if rows:
        by_id = {r["public_id"]: r for r in rows}
        ph = ",".join("?" * len(by_id))
        for p in db.execute(          # each event's PUBLIC places; `mapped` = it has documented coordinates
                f"SELECT ee.public_id AS event_id, pe.public_id, pe.slug, p.primary_name, p.latitude IS NOT NULL AS mapped, x.is_uncertain "
                f"FROM event_places x JOIN entities ee ON ee.id=x.event_id JOIN entities pe ON pe.id=x.place_id "
                f"JOIN places p ON p.entity_id=pe.id WHERE ee.public_id IN ({ph}) AND {_pub('pe')} ORDER BY lower(p.primary_name)",
                list(by_id)):
            by_id[p["event_id"]]["places"].append(dict(p))
    dated = [r for r in rows if r["date_precision"] != "unknown"]
    undated = [r for r in rows if r["date_precision"] == "unknown"]
    return dated, undated


DATE_CERTAINTY = {"exact": "precise", "month": "precise", "year": "precise", "range": "range",
                  "approximate": "uncertain", "decade": "uncertain"}


def timeline_ruler(dated):
    """How dated events spread over the years, for the timeline's time ruler. An event counts in every
    year its documented span covers; approximate and decade-only dates are counted separately so the
    ruler never presents them as exact."""
    spans = []
    for ev in dated:
        span = dates.year_span(ev["date_start"], ev["date_end"], ev["date_precision"])
        if span:
            spans.append((span[0], max(span), DATE_CERTAINTY.get(ev["date_precision"], "uncertain")))
    if not spans:
        return None
    lo = min(s[0] for s in spans) // 10 * 10
    hi = max(s[1] for s in spans) // 10 * 10 + 9
    years = {y: {"precise": 0, "range": 0, "uncertain": 0} for y in range(lo, hi + 1)}
    for y0, y1, kind in spans:
        for y in range(y0, y1 + 1):
            years[y][kind] += 1
    peak = max(sum(c.values()) for c in years.values()) or 1
    decades = [{"label": f"{d}s", "start": d, "count": sum(1 for s in spans if d <= s[0] <= d + 9)} for d in range(lo, hi + 1, 10)]
    return {"lo": lo, "hi": hi, "n": len(spans), "peak": peak, "decades": decades,
            "bars": [{"year": y, **c} for y, c in years.items()]}


def subject_oral_histories(db, subject_id):
    """Public oral histories that concern a record (whether their recording or transcript may be shown is decided on their own page)."""
    return db.execute(
        f"SELECT e.slug, o.title, o.recorded_start, o.recorded_end, o.recorded_precision FROM oral_history_subjects s "
        f"JOIN entities e ON e.id=s.oral_history_id AND {PUBLIC_WHERE} JOIN oral_histories o ON o.entity_id=e.id "
        f"WHERE s.subject_id=? ORDER BY o.recorded_start", (subject_id,)).fetchall()


def filter_label(db, kind, public_id):
    """Title of a public record used as a filter (None when it is not public)."""
    t, col = KIND_TABLE[kind], TITLE_COL[kind]
    r = db.execute(f"SELECT x.{col} AS t FROM entities e JOIN {t} x ON x.entity_id=e.id WHERE e.public_id=? AND e.kind=? AND {PUBLIC_WHERE}",
                   (public_id, kind)).fetchone()
    return r["t"] if r else None


def map_data(db):
    """Everything the interactive map draws, from the same public records as the rest of the site.
    Places without documented coordinates are never placed on the map."""
    places = {}
    for r in db.execute(
            f"SELECT e.id, e.public_id, e.slug, e.is_fictional_test, p.primary_name, p.latitude, p.longitude, p.coord_precision, "
            f"p.coord_note, p.admin_region, p.country, t.slug AS type_slug, t.label AS type_label "
            f"FROM entities e JOIN places p ON p.entity_id=e.id LEFT JOIN place_types t ON t.id=p.place_type_id "
            f"WHERE e.kind='place' AND {PUBLIC_WHERE} AND p.latitude BETWEEN -90 AND 90 AND p.longitude BETWEEN -180 AND 180").fetchall():
        places[r["id"]] = {"id": r["public_id"], "name": r["primary_name"], "url": record_url("place", r["slug"]),
                           "lat": r["latitude"], "lon": r["longitude"], "precision": r["coord_precision"],
                           "note": r["coord_note"], "region": r["admin_region"] or r["country"],
                           "type": r["type_slug"] or "other", "type_label": r["type_label"] or "Other historically relevant place",
                           "category": _atlas().category(r["type_slug"]),
                           "names": "", "fictional": bool(r["is_fictional_test"]), "events": [], "people": 0}
    if places:
        ph = ",".join("?" * len(places))
        names = {}
        for r in db.execute(f"SELECT entity_id, normalized FROM entity_names WHERE entity_id IN ({ph})", list(places)):
            names.setdefault(r["entity_id"], []).append(r["normalized"])
        for pid, ns in names.items():
            places[pid]["names"] = " ".join(ns)
        for r in db.execute(
                f"SELECT ep.place_id, e.public_id, e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, ep.is_uncertain, "
                f"t.slug AS type_slug FROM event_places ep JOIN entities e ON e.id=ep.event_id AND {PUBLIC_WHERE} "
                f"JOIN events ev ON ev.entity_id=e.id LEFT JOIN event_types t ON t.id=ev.event_type_id "
                f"WHERE ep.place_id IN ({ph}) ORDER BY ev.date_start", list(places)).fetchall():
            span = dates.year_span(r["date_start"], r["date_end"], r["date_precision"])
            # only what the map filters and the period ribbon use; titles and dates come with the place panel (/map/place/<id>.json)
            places[r["place_id"]]["events"].append({
                "id": r["public_id"], "type": r["type_slug"] or "other",
                "from": span[0] if span else None, "to": span[1] if span else None, "precision": r["date_precision"]})
        for r in db.execute(
                f"SELECT pl, COUNT(DISTINCT pid) AS n FROM (SELECT p.birth_place_id AS pl, p.entity_id AS pid FROM people p "
                f"UNION ALL SELECT p.death_place_id, p.entity_id FROM people p) x JOIN entities e ON e.id=x.pid AND {PUBLIC_WHERE} "
                f"WHERE pl IN ({ph}) GROUP BY pl", list(places)).fetchall():
            places[r["pl"]]["people"] = r["n"]
        for r in db.execute(f"SELECT DISTINCT entity_id FROM conflicting_accounts WHERE is_public=1 AND concerns_location=1 "
                            f"AND entity_id IN ({ph})", list(places)):
            places[r["entity_id"]]["disputed"] = True       # sources disagree about where this place is
        for pl, rel in _atlas().place_relations(db, list(places)).items():
            places[pl].update(persons=sorted(rel["persons"]), orgs=sorted(rel["orgs"]), items=rel["items"])
    return list(places.values())


def _atlas():
    from . import atlas            # imported lazily: atlas.py builds on this module
    return atlas


def person_place_ids(db, person_public_id):
    """Places documented for one person: birth and death places, places of their events and affiliations."""
    pe = db.execute(f"SELECT e.id FROM entities e WHERE e.public_id=? AND e.kind='person' AND {PUBLIC_WHERE}", (person_public_id,)).fetchone()
    if not pe:
        return None
    rows = db.execute(
        f"SELECT DISTINCT e.public_id FROM entities e WHERE e.kind='place' AND {PUBLIC_WHERE} AND e.id IN ("
        f"SELECT birth_place_id FROM people WHERE entity_id=:p UNION SELECT death_place_id FROM people WHERE entity_id=:p "
        f"UNION SELECT ep.place_id FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id "
        f"JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')} WHERE x.person_id=:p AND x.publication_status='published' "
        f"UNION SELECT place_id FROM affiliations WHERE person_id=:p AND publication_status='published' AND visibility='public')",
        {"p": pe["id"]}).fetchall()
    return [r["public_id"] for r in rows]


def latest_events(db, limit=5):
    return db.execute(
        f"SELECT e.slug, ev.title, ev.summary, ev.date_start, ev.date_end, ev.date_precision FROM entities e JOIN events ev ON ev.entity_id=e.id "
        f"WHERE e.kind='event' AND {PUBLIC_WHERE} AND ev.date_precision<>'unknown' ORDER BY ev.date_start LIMIT ?", (limit,)).fetchall()


def counts(db):
    """Real counts of PUBLIC records. Never fabricated."""
    return {r["kind"]: r["n"] for r in db.execute(
        f"SELECT e.kind, COUNT(*) AS n FROM entities e WHERE {PUBLIC_WHERE} GROUP BY e.kind")}


def sitemap_entries(db):
    return db.execute(f"SELECT e.kind, e.slug, e.updated_at FROM entities e LEFT JOIN archive_items a ON a.entity_id=e.id "
                      f"WHERE {PUBLIC_WHERE} AND e.is_fictional_test=0 AND (e.kind IN ('person','family','place','event','source','organization') "
                      f"OR (e.kind='archive_item' AND {PUBLIC_ITEM})) ORDER BY e.kind, e.id LIMIT 50000").fetchall()
