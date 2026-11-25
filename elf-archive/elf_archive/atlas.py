"""Read-side data for the historical atlas (the 3D map): marker categories, place and record
previews, and the geographic associations of any public record.

Rules (the same as every public page):
- only published, public, unmerged records are returned, and archive items only when their own
  access level and rights allow display;
- a record is placed on the map ONLY through a public place with documented coordinates; nothing
  is located by guesswork, and records without such a place say so;
- two places are never linked on the map just because both appear in it; links come from records.
"""
from . import queries
from .queries import PUBLIC_ITEM, _THUMB, _pub, media_url, record_url
from .services import dates
from .services.entities import KIND_TABLE, PUBLIC_WHERE, TITLE_COL

# Marker shape by place type. Shapes (not colour) carry the category; the outline carries precision.
MARKER_CATEGORY = {
    "town_city": "settlement", "village": "settlement", "historical_settlement": "settlement",
    "region": "area", "geographic_feature": "area",
    "conflict_location": "conflict",
    "historical_site": "site", "memorial_site": "site", "organizational_location": "site",
    "displacement_location": "site", "other": "site",
}
CATEGORY_LABELS = {"settlement": "Town, city or village", "area": "Region or geographic area",
                   "conflict": "Conflict or battle location", "site": "Historical, memorial or organizational site"}
LOCATION_FIELDS = ("latitude", "longitude", "coord_precision", "coord_note", "location", "coordinates")


def category(place_type_slug):
    return MARKER_CATEGORY.get(place_type_slug or "other", "site")


def valid_coords(lat, lon):
    return lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180


def place_relations(db, place_ids):
    """For each mapped place: public people and organizations linked to it by a record, and the number
    of public archive items about it. Used by the atlas filters."""
    out = {pid: {"persons": set(), "orgs": set(), "items": 0} for pid in place_ids}
    if not place_ids:
        return out
    ph = ",".join("?" * len(place_ids))
    ids = list(place_ids)
    people_sql = (
        f"SELECT x.pl, pe.public_id FROM ("
        f"  SELECT birth_place_id AS pl, entity_id AS pid FROM people UNION SELECT death_place_id, entity_id FROM people"
        f"  UNION SELECT ep.place_id, x.person_id FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id"
        f"    JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')} WHERE x.person_id IS NOT NULL AND x.publication_status='published'"
        f"  UNION SELECT place_id, person_id FROM affiliations WHERE publication_status='published' AND visibility='public'"
        f") x JOIN entities pe ON pe.id=x.pid AND {_pub('pe')} WHERE x.pl IN ({ph})")
    for r in db.execute(people_sql, ids):
        out[r["pl"]]["persons"].add(r["public_id"])
    org_sql = (
        f"SELECT x.pl, oe.public_id FROM ("
        f"  SELECT ep.place_id AS pl, x.organization_id AS oid FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id"
        f"    JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')} WHERE x.organization_id IS NOT NULL AND x.publication_status='published'"
        f"  UNION SELECT place_id, organization_id FROM affiliations WHERE publication_status='published' AND visibility='public'"
        f") x JOIN entities oe ON oe.id=x.oid AND {_pub('oe')} WHERE x.pl IN ({ph})")
    for r in db.execute(org_sql, ids):
        out[r["pl"]]["orgs"].add(r["public_id"])
    for r in db.execute(
            f"SELECT s.subject_id AS pl, COUNT(*) AS n FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND {PUBLIC_WHERE} "
            f"JOIN archive_items a ON a.entity_id=e.id AND {PUBLIC_ITEM} WHERE s.subject_id IN ({ph}) GROUP BY s.subject_id", ids):
        out[r["pl"]]["items"] = r["n"]
    return out


def _public_entity(db, public_id):
    return db.execute(f"SELECT e.* FROM entities e WHERE e.public_id=? AND {PUBLIC_WHERE}", (public_id,)).fetchone()


def _photos(db, entity_id, limit=6, fmt=dates.format_date):
    """Public archive items about a record (their own access level and rights allow display), with the details
    a caption needs: what it is, when it was made (if known), who made it and its rights."""
    out = []
    for p in queries.record_photos(db, entity_id)[:limit]:
        known = p["created_precision"] not in (None, "unknown")
        out.append({"title": p["title"], "url": record_url("archive_item", p["slug"]),
                    "thumb": media_url(p["thumb_key"]) if p["thumb_key"] else None, "item_type": p["item_type"],
                    "date": fmt(p["created_start"], p["created_end"], p["created_precision"]) if known else None,
                    "creator": p["creator"], "rights_holder": p["rights_holder"], "rights": p["rights_status"]})
    return out


def lead_image(photos):
    """The first public image with a thumbnail: shown at the top of a panel, always with its caption and a link
    to the full archive record. Never a stand-in or generated picture: no image, no lead."""
    return next((ph for ph in photos if ph["thumb"]), None)


def place_families(db, place_id, limit=8):
    """Public families with a public member documented at this place: born or died here, or took part in an
    event here. The link is derived from those records, and the number of such members is given."""
    return [{"title": r["display_name"], "url": record_url("family", r["slug"]), "n": r["n"]} for r in db.execute(
        f"SELECT fe.slug, f.display_name, COUNT(DISTINCT x.pid) AS n FROM ("
        f"  SELECT entity_id AS pid FROM people WHERE birth_place_id=:p OR death_place_id=:p"
        f"  UNION SELECT x.person_id FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id"
        f"    JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')}"
        f"    WHERE ep.place_id=:p AND x.person_id IS NOT NULL AND x.publication_status='published'"
        f") x JOIN entities pe ON pe.id=x.pid AND {_pub('pe')} "
        f"JOIN family_memberships m ON m.person_id=x.pid AND m.publication_status='published' AND m.visibility='public' "
        f"JOIN entities fe ON fe.id=m.family_id AND {_pub('fe')} JOIN families f ON f.entity_id=fe.id "
        f"GROUP BY fe.id ORDER BY n DESC, lower(f.display_name) LIMIT :n", {"p": place_id, "n": limit})]


def subject_collections(db, subject_ids, limit=4):
    """Public collections holding public archive items about any of these records."""
    if not subject_ids:
        return []
    ph = ",".join("?" * len(subject_ids))
    return [{"title": r["title"], "url": record_url("collection", r["slug"]), "n": r["n"]} for r in db.execute(
        f"SELECT ce.slug, c.title, COUNT(DISTINCT ci.item_id) AS n FROM archive_item_subjects s "
        f"JOIN entities ie ON ie.id=s.item_id AND {_pub('ie')} JOIN archive_items a ON a.entity_id=ie.id AND {PUBLIC_ITEM} "
        f"JOIN collection_items ci ON ci.item_id=s.item_id JOIN entities ce ON ce.id=ci.collection_id AND {_pub('ce')} "
        f"JOIN collections c ON c.entity_id=ce.id WHERE s.subject_id IN ({ph}) GROUP BY ce.id ORDER BY n DESC, lower(c.title) LIMIT ?",
        [*subject_ids, limit])]


def location_disputes(db, entity_id):
    """Public differing accounts about where a place is."""
    return [{"topic": r["topic"], "text": r["account_text"], "by": r["attributed_to"]} for r in db.execute(
        "SELECT topic, account_text, attributed_to FROM conflicting_accounts WHERE entity_id=? AND is_public=1 AND concerns_location=1 "
        "ORDER BY id", (entity_id,))]


def place_preview(db, public_id, fmt=dates.format_date):
    """Everything the place panel shows, or None if the place is not public."""
    e = _public_entity(db, public_id)
    if not e or e["kind"] != "place":
        return None
    p = db.execute("SELECT p.*, t.slug AS type_slug, t.label AS type_label FROM places p LEFT JOIN place_types t ON t.id=p.place_type_id "
                   "WHERE p.entity_id=?", (e["id"],)).fetchone()
    events = [{"title": r["title"], "url": record_url("event", r["slug"]),
               "date": fmt(r["date_start"], r["date_end"], r["date_precision"]),
               "precision": r["date_precision"], "uncertain_place": bool(r["is_uncertain"])}
              for r in queries.place_events(db, e["id"])]
    people, seen = [], set()
    for r in queries.place_people(db, e["id"]):
        role = "Born here" if r["born"] and not r["died"] else "Died here" if r["died"] and not r["born"] else "Born and died here"
        people.append({"title": r["preferred_name"], "url": record_url("person", r["slug"]), "role": role})
        seen.add(r["slug"])
    for r in db.execute(
            f"SELECT DISTINCT pe.slug, p.preferred_name FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id "
            f"JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')} JOIN entities pe ON pe.id=x.person_id AND {_pub('pe')} "
            f"JOIN people p ON p.entity_id=pe.id WHERE ep.place_id=? AND x.publication_status='published' ORDER BY p.preferred_name",
            (e["id"],)):
        if r["slug"] not in seen:
            people.append({"title": r["preferred_name"], "url": record_url("person", r["slug"]), "role": "Took part in an event here"})
            seen.add(r["slug"])
    orgs = [{"title": r["name"], "url": record_url("organization", r["slug"])} for r in db.execute(
        f"SELECT DISTINCT oe.slug, o.name FROM affiliations a JOIN entities oe ON oe.id=a.organization_id AND {_pub('oe')} "
        f"JOIN organizations o ON o.entity_id=oe.id WHERE a.place_id=? AND a.publication_status='published' AND a.visibility='public' "
        f"UNION SELECT oe.slug, o.name FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id "
        f"JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')} JOIN entities oe ON oe.id=x.organization_id AND {_pub('oe')} "
        f"JOIN organizations o ON o.entity_id=oe.id WHERE ep.place_id=? AND x.publication_status='published' ORDER BY 2",
        (e["id"], e["id"]))]
    cites = queries.citations(db, e["id"])
    loc = [{"title": c["title"], "url": record_url("source", c["source_slug"]), "locator": c["locator"], "evidence": c["evidence_status"]}
           for c in cites if (c["field_name"] or "") in LOCATION_FIELDS]
    photos = _photos(db, e["id"], fmt=fmt)
    valid = fmt(p["valid_start"], p["valid_end"], p["valid_precision"]) if p["valid_precision"] not in (None, "unknown") else None
    overview = p["overview"] or ""
    return {
        "kind": "place", "id": e["public_id"], "title": p["primary_name"], "url": record_url("place", e["slug"]),
        "type_label": p["type_label"] or "Other historically relevant place", "category": category(p["type_slug"]),
        "region": p["admin_region"] or p["country"], "original_name": p["original_name"],
        "lat": p["latitude"], "lon": p["longitude"], "precision": p["coord_precision"], "note": p["coord_note"],
        "summary": overview[:320] + ("…" if len(overview) > 320 else ""), "valid": valid,
        "names": [{"name": n["name"], "type": n["name_type"]} for n in queries.names(db, e["id"])],
        "lead": lead_image(photos), "photos": photos,
        "events": events, "people": people[:12], "people_total": len(people), "orgs": orgs[:8],
        "families": place_families(db, e["id"]), "collections": subject_collections(db, [e["id"]]),
        "location_sources": loc, "location_disputes": location_disputes(db, e["id"]),
        "sources_total": len(cites), "fictional": bool(e["is_fictional_test"]),
    }


def record_places(db, entity):
    """Mapped public places documented for a record, and how many linked public places have no coordinates.
    Returns ([{id, name, uncertain}], unmapped_count)."""
    kind, eid = entity["kind"], entity["id"]
    if kind == "place":
        sql, args = "SELECT ? AS pl, 0 AS unc", [eid]
    elif kind == "event":
        sql, args = "SELECT place_id AS pl, is_uncertain AS unc FROM event_places WHERE event_id=?", [eid]
    elif kind == "person":
        sql = (f"SELECT birth_place_id AS pl, 0 AS unc FROM people WHERE entity_id=:i UNION SELECT death_place_id, 0 FROM people WHERE entity_id=:i "
               f"UNION SELECT ep.place_id, ep.is_uncertain FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id "
               f"JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')} WHERE x.person_id=:i AND x.publication_status='published' "
               f"UNION SELECT place_id, 0 FROM affiliations WHERE person_id=:i AND publication_status='published' AND visibility='public'")
        args = {"i": eid}
    elif kind == "organization":
        sql = (f"SELECT ep.place_id AS pl, ep.is_uncertain AS unc FROM event_participants x JOIN event_places ep ON ep.event_id=x.event_id "
               f"JOIN entities ee ON ee.id=x.event_id AND {_pub('ee')} WHERE x.organization_id=:i AND x.publication_status='published' "
               f"UNION SELECT place_id, 0 FROM affiliations WHERE organization_id=:i AND publication_status='published' AND visibility='public'")
        args = {"i": eid}
    elif kind == "archive_item":
        sql, args = "SELECT subject_id AS pl, 0 AS unc FROM archive_item_subjects WHERE item_id=?", [eid]
    elif kind == "oral_history":
        sql, args = "SELECT subject_id AS pl, 0 AS unc FROM oral_history_subjects WHERE oral_history_id=?", [eid]
    else:
        return [], 0
    rows = db.execute(
        f"SELECT pe.public_id, p.primary_name, p.latitude, p.longitude, MAX(x.unc) AS unc FROM ({sql}) x "
        f"JOIN entities pe ON pe.id=x.pl AND pe.kind='place' AND {_pub('pe')} JOIN places p ON p.entity_id=pe.id "
        f"GROUP BY pe.public_id ORDER BY lower(p.primary_name)", args).fetchall()
    mapped = [{"id": r["public_id"], "name": r["primary_name"], "uncertain": bool(r["unc"])}
              for r in rows if valid_coords(r["latitude"], r["longitude"])]
    return mapped, len(rows) - len(mapped)


def _record_date(kind, sub, fmt=dates.format_date):
    def fd(prefix):
        prec = sub[f"{prefix}_precision"]
        return fmt(sub[f"{prefix}_start"], sub[f"{prefix}_end"], prec) if prec and prec != "unknown" else None
    if kind == "event":
        return fd("date")
    if kind == "person":
        b, d = fd("birth"), fd("death")
        return f"{b or '?'} – {d or '?'}" if (b or d) else None
    if kind == "organization":
        return fd("active")
    if kind == "archive_item":
        return fd("created")
    if kind == "oral_history":
        return fd("recorded")
    return None


SUMMARY_FIELDS = {"event": "summary", "person": "summary", "organization": "description", "archive_item": "description",
                  "oral_history": "summary", "family": "summary", "source": "provenance", "place": "overview", "collection": "description"}


def record_preview(db, public_id, fmt=dates.format_date):
    """A compact preview of any public record, with its places on the map."""
    e = _public_entity(db, public_id)
    if not e or e["kind"] not in KIND_TABLE:
        return None
    if e["kind"] == "archive_item" and not db.execute(f"SELECT 1 FROM archive_items a WHERE a.entity_id=? AND {PUBLIC_ITEM}", (e["id"],)).fetchone():
        return None
    sub = db.execute(f"SELECT * FROM {KIND_TABLE[e['kind']]} WHERE entity_id=?", (e["id"],)).fetchone()
    text = (sub[SUMMARY_FIELDS[e["kind"]]] or "") if SUMMARY_FIELDS.get(e["kind"]) in sub.keys() else ""
    places, unmapped = record_places(db, e)
    thumb, lead, photos = None, None, []
    if e["kind"] == "archive_item":
        r = db.execute(f"SELECT {_THUMB} AS k FROM entities e WHERE e.id=?", (e["id"],)).fetchone()
        thumb = media_url(r["k"]) if r and r["k"] else None
    else:
        photos = _photos(db, e["id"], 60, fmt=fmt)
        lead = lead_image(photos)
    type_label = None
    if e["kind"] == "event":
        t = db.execute("SELECT label FROM event_types WHERE id=?", (sub["event_type_id"],)).fetchone()
        type_label = t["label"] if t else None
    extra = event_details(db, e["id"]) if e["kind"] == "event" else {}
    if e["kind"] == "event":
        extra["precision"] = sub["date_precision"]
        extra["precision_note"] = dates.precision_note(sub["date_precision"]) if sub["date_precision"] not in (None, "unknown") else None
        extra["category"] = event_category(db.execute("SELECT slug FROM event_types WHERE id=?", (sub["event_type_id"],)).fetchone()[0]
                                           if sub["event_type_id"] else None)
    return {**extra, "kind": e["kind"], "id": e["public_id"], "title": sub[TITLE_COL[e["kind"]]],
            "url": record_url(e["kind"], e["slug"]), "type_label": type_label, "date": _record_date(e["kind"], sub, fmt),
            "summary": text[:320] + ("…" if len(text) > 320 else ""), "thumb": thumb, "lead": lead,
            "photos_total": len(photos), "sources_total": len(queries.citations(db, e["id"])),
            "places": places, "unmapped": unmapped, "fictional": bool(e["is_fictional_test"])}


# ───────────── timeline ─────────────
# Event shape by event type (the timeline's markers; colour is secondary and never the only cue).
EVENT_CATEGORY = {
    "battle_conflict": "conflict",
    "political_development": "political", "organizational_development": "political", "meeting_conference": "political",
    "statement_publication": "political",
    "personal_life_event": "people", "displacement_migration": "people", "humanitarian_event": "people",
    "community_event": "community", "commemoration": "community", "other": "community",
}
EVENT_CATEGORY_LABELS = {"conflict": "Armed conflict", "political": "Political and organizational",
                         "people": "Lives, displacement and humanitarian", "community": "Community, commemoration and other"}


def event_category(type_slug):
    return EVENT_CATEGORY.get(type_slug or "other", "community")


def _t(s, end=False):
    """A recorded date string ('YYYY', 'YYYY-MM' or 'YYYY-MM-DD') as a decimal year: the start of the period it
    names, or with end=True the end of it. A year stays a whole year; it is never narrowed to a day."""
    import calendar
    parts = [int(x) for x in s.split("-")]
    y = parts[0]
    if len(parts) == 1:
        return float(y + (1 if end else 0))
    m = parts[1]
    if len(parts) == 2:
        return y + (m - 1 + (1 if end else 0)) / 12
    days = 366 if calendar.isleap(y) else 365
    from datetime import date
    doy = date(y, m, parts[2]).timetuple().tm_yday
    return y + (doy - 1 + (1 if end else 0)) / days


def date_interval(start, end, precision):
    """(t0, t1, is_point) in decimal years, covering exactly what the record says and nothing more:
    a day is a point, a month or a year is the whole month or year, a decade the whole decade, a range from the
    start of its first date to the end of its last. Unknown dates return None (they are listed, not placed)."""
    if precision in (None, "unknown") or not start:
        return None
    t0, t1 = _t(start), _t(end or start, end=True)
    if precision == "decade":
        d = int(start[:3]) * 10
        t0, t1 = float(d), float(d + 10)
    if t1 < t0:
        t0, t1 = t1, t0
    point = precision == "exact" and len(start.split("-")) == 3 and (not end or end == start)
    return round(t0, 4), round(t1, 4), point


def timeline_events(db, fmt=dates.format_date):
    """Every public event with what the interactive timeline needs. Filtering happens in the browser with the
    same rules as the server-rendered list (queries.timeline), so the two never disagree."""
    rows = db.execute(
        f"SELECT e.id, e.public_id, e.slug, e.is_fictional_test, ev.title, ev.summary, ev.date_start, ev.date_end, ev.date_precision, "
        f"t.slug AS type_slug, t.label AS type_label FROM entities e JOIN events ev ON ev.entity_id=e.id "
        f"LEFT JOIN event_types t ON t.id=ev.event_type_id WHERE e.kind='event' AND {PUBLIC_WHERE} "
        f"ORDER BY ev.date_start IS NULL, ev.date_start, lower(ev.title) LIMIT 5000").fetchall()
    out = {}
    for r in rows:
        iv = date_interval(r["date_start"], r["date_end"], r["date_precision"])
        summary = r["summary"] or ""
        out[r["id"]] = {
            "id": r["public_id"], "title": r["title"], "url": record_url("event", r["slug"]),
            "date": fmt(r["date_start"], r["date_end"], r["date_precision"]), "precision": r["date_precision"],
            "t0": iv[0] if iv else None, "t1": iv[1] if iv else None, "point": iv[2] if iv else False,
            "from": dates.year_span(r["date_start"], r["date_end"], r["date_precision"])[0] if iv else None,
            "to": max(dates.year_span(r["date_start"], r["date_end"], r["date_precision"])) if iv else None,
            "type": r["type_slug"] or "other", "type_label": r["type_label"] or "Other historical event",
            "category": event_category(r["type_slug"]),
            "summary": summary[:240] + ("…" if len(summary) > 240 else ""),
            "places": [], "persons": [], "orgs": [], "media": 0, "date_disputed": False, "fictional": bool(r["is_fictional_test"])}
    if not out:
        return []
    ids = list(out)
    ph = ",".join("?" * len(ids))
    for r in db.execute(
            f"SELECT x.event_id, pe.public_id, p.primary_name, p.latitude, p.longitude, p.admin_region, p.coord_precision, x.is_uncertain "
            f"FROM event_places x JOIN entities pe ON pe.id=x.place_id AND {_pub('pe')} JOIN places p ON p.entity_id=pe.id "
            f"WHERE x.event_id IN ({ph}) ORDER BY lower(p.primary_name)", ids):
        out[r["event_id"]]["places"].append({"id": r["public_id"], "name": r["primary_name"], "region": r["admin_region"],
                                             "mapped": valid_coords(r["latitude"], r["longitude"]),
                                             "precision": r["coord_precision"], "uncertain": bool(r["is_uncertain"])})
    for r in db.execute(
            f"SELECT x.event_id, pe.public_id, x.person_id IS NOT NULL AS is_person FROM event_participants x "
            f"JOIN entities pe ON pe.id=COALESCE(x.person_id, x.organization_id) AND {_pub('pe')} "
            f"WHERE x.event_id IN ({ph}) AND x.publication_status='published'", ids):
        out[r["event_id"]]["persons" if r["is_person"] else "orgs"].append(r["public_id"])
    for r in db.execute(
            f"SELECT s.subject_id AS ev, COUNT(*) AS n FROM archive_item_subjects s JOIN entities e ON e.id=s.item_id AND {PUBLIC_WHERE} "
            f"JOIN archive_items a ON a.entity_id=e.id AND {PUBLIC_ITEM} WHERE s.subject_id IN ({ph}) GROUP BY s.subject_id", ids):
        out[r["ev"]]["media"] += r["n"]
    for r in db.execute(
            f"SELECT s.subject_id AS ev, COUNT(*) AS n FROM oral_history_subjects s JOIN entities e ON e.id=s.oral_history_id AND {PUBLIC_WHERE} "
            f"WHERE s.subject_id IN ({ph}) GROUP BY s.subject_id", ids):
        out[r["ev"]]["media"] += r["n"]
    for r in db.execute(f"SELECT DISTINCT entity_id FROM conflicting_accounts WHERE is_public=1 AND concerns_date=1 AND entity_id IN ({ph})", ids):
        out[r["entity_id"]]["date_disputed"] = True
    return list(out.values())


def event_details(db, entity_id):
    """The extra parts of an event preview: people, organizations, places with their precision, and date disagreements."""
    people = [{"title": r["name"], "url": record_url(r["kind"], r["slug"]), "role": r["role"], "kind": r["kind"]}
              for r in queries.event_participants(db, entity_id)]
    places = [{"id": r["public_id"], "title": r["primary_name"], "url": record_url("place", r["slug"]), "precision": r["coord_precision"],
               "mapped": valid_coords(r["latitude"], r["longitude"]), "uncertain": bool(r["is_uncertain"]), "region": r["admin_region"]}
              for r in db.execute(
                  f"SELECT pe.public_id, pe.slug, p.primary_name, p.coord_precision, p.latitude, p.longitude, p.admin_region, x.is_uncertain "
                  f"FROM event_places x JOIN entities pe ON pe.id=x.place_id AND {_pub('pe')} JOIN places p ON p.entity_id=pe.id "
                  f"WHERE x.event_id=? ORDER BY lower(p.primary_name)", (entity_id,))]
    disputes = [{"topic": r["topic"], "text": r["account_text"], "by": r["attributed_to"]}
                for r in db.execute("SELECT topic, account_text, attributed_to FROM conflicting_accounts "
                                    "WHERE entity_id=? AND is_public=1 AND concerns_date=1 ORDER BY id", (entity_id,))]
    return {"people": [p for p in people if p["kind"] == "person"][:8], "orgs": [p for p in people if p["kind"] == "organization"][:6],
            "event_places": places, "date_disputes": disputes}


def related_events(db, entity_id, limit=8, fmt=dates.format_date):
    """Other public events sharing a documented place or participant with this one (the reason is given)."""
    rows = db.execute(
        f"SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, MIN(x.why) AS why FROM ("
        f"  SELECT b.event_id AS eid, 'place' AS why FROM event_places a JOIN event_places b ON b.place_id=a.place_id AND b.event_id<>a.event_id "
        f"    JOIN entities pe ON pe.id=a.place_id AND {_pub('pe')} WHERE a.event_id=:i"
        f"  UNION SELECT b.event_id, 'participant' FROM event_participants a JOIN event_participants b "
        f"    ON (b.person_id=a.person_id OR b.organization_id=a.organization_id) AND b.event_id<>a.event_id "
        f"    JOIN entities pe ON pe.id=COALESCE(a.person_id, a.organization_id) AND {_pub('pe')} "
        f"    WHERE a.event_id=:i AND a.publication_status='published' AND b.publication_status='published'"
        f") x JOIN entities e ON e.id=x.eid AND {PUBLIC_WHERE} JOIN events ev ON ev.entity_id=e.id "
        f"GROUP BY e.id ORDER BY ev.date_start IS NULL, ev.date_start LIMIT :limit", {"i": entity_id, "limit": limit}).fetchall()
    return [{"title": r["title"], "url": record_url("event", r["slug"]), "why": r["why"],
             "date": fmt(r["date_start"], r["date_end"], r["date_precision"])} for r in rows]


# ───────────── context for a period ─────────────
def period_context(db, f, limit=5):
    """A short, record-derived summary of the events matching the explore filters (a period, region or event
    type): how many there are and how their dates are known, the most frequent event types, and the places,
    people, families, collections and sources most often linked to them. Counts only; no narrative is written,
    and "most documented" means most cited sources, never an editorial judgement of importance."""
    from collections import Counter
    dated, _undated = queries.timeline(db, f)
    if not dated:
        return {"n": 0}
    ids = [r["id"] for r in db.execute(
        f"SELECT id FROM entities WHERE public_id IN ({','.join('?' * len(dated))})", [r["public_id"] for r in dated])]
    ph = ",".join("?" * len(ids))
    types = Counter(r["type_label"] or "Other historical event" for r in dated).most_common(4)

    def top(sql, args=ids):
        return [dict(r) for r in db.execute(sql, args)]
    events = top(f"SELECT e.slug, ev.title, ev.date_start, ev.date_end, ev.date_precision, COUNT(DISTINCT c.source_id) AS n "
                 f"FROM entities e JOIN events ev ON ev.entity_id=e.id JOIN citations c ON c.target_id=e.id "
                 f"JOIN entities se ON se.id=c.source_id AND {_pub('se')} WHERE e.id IN ({ph}) GROUP BY e.id "
                 f"ORDER BY n DESC, ev.date_start LIMIT {limit}")
    places = top(f"SELECT pe.id AS eid, pe.slug, pe.public_id, p.primary_name AS title, p.latitude IS NOT NULL AS mapped, COUNT(DISTINCT x.event_id) AS n "
                 f"FROM event_places x JOIN entities pe ON pe.id=x.place_id AND {_pub('pe')} JOIN places p ON p.entity_id=pe.id "
                 f"WHERE x.event_id IN ({ph}) GROUP BY pe.id ORDER BY n DESC, lower(p.primary_name) LIMIT {limit}")
    people = top(f"SELECT pe.id, pe.slug, p.preferred_name AS title, COUNT(DISTINCT x.event_id) AS n FROM event_participants x "
                 f"JOIN entities pe ON pe.id=x.person_id AND {_pub('pe')} JOIN people p ON p.entity_id=pe.id "
                 f"WHERE x.event_id IN ({ph}) AND x.publication_status='published' GROUP BY pe.id ORDER BY n DESC, lower(p.preferred_name) "
                 f"LIMIT {limit}")
    families = top(f"SELECT fe.slug, f.display_name AS title, COUNT(DISTINCT x.person_id) AS n FROM event_participants x "
                   f"JOIN entities pe ON pe.id=x.person_id AND {_pub('pe')} "
                   f"JOIN family_memberships m ON m.person_id=x.person_id AND m.publication_status='published' AND m.visibility='public' "
                   f"JOIN entities fe ON fe.id=m.family_id AND {_pub('fe')} JOIN families f ON f.entity_id=fe.id "
                   f"WHERE x.event_id IN ({ph}) AND x.publication_status='published' GROUP BY fe.id ORDER BY n DESC, lower(f.display_name) "
                   f"LIMIT {limit}")
    sources = top(f"SELECT se.slug, s.title, COUNT(DISTINCT c.target_id) AS n FROM citations c "
                  f"JOIN entities se ON se.id=c.source_id AND {_pub('se')} JOIN sources s ON s.entity_id=se.id "
                  f"WHERE c.target_id IN ({ph}) GROUP BY se.id ORDER BY n DESC, lower(s.title) LIMIT {limit}")
    uncertain = sum(1 for r in dated if r["date_precision"] in ("approximate", "decade"))
    years = [int(r["date_start"][:4]) for r in dated] + [int((r["date_end"] or r["date_start"])[:4]) for r in dated]
    return {
        "n": len(dated), "uncertain": uncertain, "first": min(years), "last": max(years),
        "types": [{"label": t, "n": n} for t, n in types],
        "events": [{"title": r["title"], "url": record_url("event", r["slug"]), "n": r["n"],
                    "date_start": r["date_start"], "date_end": r["date_end"], "precision": r["date_precision"]} for r in events],
        "places": [{"title": r["title"], "url": record_url("place", r["slug"]), "id": r["public_id"], "mapped": bool(r["mapped"]), "n": r["n"]}
                   for r in places],
        "people": [{"title": r["title"], "url": record_url("person", r["slug"]), "n": r["n"]} for r in people],
        "families": [{"title": r["title"], "url": record_url("family", r["slug"]), "n": r["n"]} for r in families],
        "collections": subject_collections(db, ids + [pl["eid"] for pl in places], limit=3),
        "sources": [{"title": r["title"], "url": record_url("source", r["slug"]), "n": r["n"]} for r in sources],
    }
