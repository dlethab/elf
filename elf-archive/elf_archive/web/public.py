"""Public, anonymous-safe pages. Every record lookup goes through entities.resolve_public / PUBLIC_WHERE,
so drafts, restricted (e.g. living) people and merged records 404 exactly like records that never existed."""
import json
import re
from urllib.parse import urlencode

from flask import Blueprint, Response, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from .. import i18n, queries
from ..db import get_db, tx
from ..security import safe_next
from ..services import audit, collections, entities, explorations, graph, oral, photos, ratelimit, records, search, storage
from ..services.entities import PUBLIC_WHERE
from ..services.search import SEARCHABLE_KINDS
from ..vocab import ITEM_TYPE_LABELS, KIND_LABELS, RIGHTS_LABELS

bp = Blueprint("public", __name__)

LIST_KINDS = {"people": "person", "families": "family", "places": "place", "events": "event", "sources": "source",
              "organizations": "organization"}
SECTION_TITLES = {"person": "People", "family": "Families", "place": "Places", "event": "Events", "source": "Sources",
                  "organization": "Organizations",
                  "archive_item": "Digital Archive"}


def _page():
    try:
        return max(1, min(int(request.args.get("page", 1)), 10000))
    except ValueError:
        return 1


def _resolve(kind, slug):
    res = entities.resolve_public(get_db(), kind, slug)
    if res is None:
        abort(404)
    state, e = res
    if state == "redirect":
        return None, redirect(queries.record_url(kind, e["slug"]), 301)
    return e, None


@bp.route("/")
def home():
    db = get_db()
    return render_template("home.html", counts=queries.counts(db), events=queries.latest_events(db, 5),
                           featured=collections.public_list(db, featured_only=True, limit=6)[:3])


@bp.route("/id/<public_id>")
def by_permanent_id(public_id):
    """Permanent identifier → current canonical URL (follows merges)."""
    e = entities.get_by_public_id(get_db(), public_id)
    if not e:
        abort(404)
    seen = set()
    while e["merged_into"] and e["id"] not in seen:
        seen.add(e["id"])
        e = entities.get(get_db(), e["merged_into"])
    pub = entities.get_public_by_public_id(get_db(), e["public_id"])
    if not pub or pub["kind"] not in entities.URL_SECTION or pub["kind"] not in SECTION_TITLES:
        abort(404)
    return redirect(queries.record_url(pub["kind"], pub["slug"]), 301)


# ───────────── lists ─────────────
def _list(section):
    kind = LIST_KINDS[section]
    letter = (request.args.get("letter") or "").strip().upper()[:1] or None
    rows, total = queries.list_public(get_db(), kind, _page(), letter)
    return render_template("records/list.html", kind=kind, section=section, title=SECTION_TITLES[kind],
                           rows=rows, total=total, page=_page(), per_page=queries.PER_PAGE, letter=letter)


for _section in LIST_KINDS:
    bp.add_url_rule(f"/{_section}", f"list_{_section}", (lambda s: lambda: _list(s))(_section))


# ───────────── record pages ─────────────
@bp.route("/people/<slug>")
def person(slug):
    e, r = _resolve("person", slug)
    if r:
        return r
    db = get_db()
    p = queries.sub(db, e["id"], "person")
    photos_ = queries.record_photos(db, e["id"])
    # The profile photograph: the first public image about this person (its own access level and rights allow
    # display). It is always captioned and links to its archive record; without one, no stand-in is shown.
    portrait = next((ph for ph in photos_ if ph["media_kind"] == "image" and (ph["display_key"] or ph["thumb_key"])), None)
    return render_template("records/person.html", e=e, p=p, names=queries.names(db, e["id"]), portrait=portrait,
                           photos=[ph for ph in photos_ if ph is not portrait],
                           birth_place=queries.place_link(db, p["birth_place_id"]),
                           death_place=queries.place_link(db, p["death_place_id"]),
                           relationships=queries.person_relationships(db, e["id"]),
                           families=queries.person_families(db, e["id"]), events=queries.person_events(db, e["id"]),
                           cites=queries.citations(db, e["id"]), accts=queries.accounts(db, e["id"]),
                           revisions=queries.public_revisions(db, e["id"]),
                           affiliations=queries.person_affiliations(db, e["id"]))


@bp.route("/families/<slug>")
def family(slug):
    e, r = _resolve("family", slug)
    if r:
        return r
    db = get_db()
    return render_template("records/family.html", e=e, f=queries.sub(db, e["id"], "family"), names=queries.names(db, e["id"]),
                           members=queries.family_members(db, e["id"]), cites=queries.citations(db, e["id"]),
                           accts=queries.accounts(db, e["id"]), revisions=queries.public_revisions(db, e["id"]),
                           can_propose=_can_propose_for(e), photos=queries.record_photos(db, e["id"]))


def _can_propose_for(fam):
    if not g.get("user"):
        return False
    if g.user.can("record.view_any"):
        return True
    from ..services import families
    grant = families.active_grant(get_db(), g.user.id, fam["id"])
    return bool(grant and grant["can_propose_tree"])


@bp.route("/places/<slug>")
def place(slug):
    e, r = _resolve("place", slug)
    if r:
        return r
    db = get_db()
    p = queries.sub(db, e["id"], "place")
    ptype = db.execute("SELECT label FROM place_types WHERE id=?", (p["place_type_id"],)).fetchone() if p["place_type_id"] else None
    return render_template("records/place.html", e=e, p=p, ptype=ptype, names=queries.names(db, e["id"]),
                           events=queries.place_events(db, e["id"]), people=queries.place_people(db, e["id"]),
                           cites=queries.citations(db, e["id"]), accts=queries.accounts(db, e["id"]),
                           revisions=queries.public_revisions(db, e["id"]), photos=queries.record_photos(db, e["id"]))


@bp.route("/events/<slug>")
def event(slug):
    from .. import atlas
    from ..services import dates
    e, r = _resolve("event", slug)
    if r:
        return r
    db = get_db()
    ev = queries.sub(db, e["id"], "event")
    etype = db.execute("SELECT label FROM event_types WHERE id=?", (ev["event_type_id"],)).fetchone() if ev["event_type_id"] else None
    return render_template("records/event.html", e=e, ev=ev, etype=etype, names=queries.names(db, e["id"]),
                           places=queries.event_places_for(db, e["id"]), participants=queries.event_participants(db, e["id"]),
                           cites=queries.citations(db, e["id"]), accts=queries.accounts(db, e["id"]),
                           revisions=queries.public_revisions(db, e["id"]), photos=queries.record_photos(db, e["id"]),
                           details=atlas.event_details(db, e["id"]), related=atlas.related_events(db, e["id"], fmt=i18n.fdate),
                           orals=queries.subject_oral_histories(db, e["id"]),
                           year=dates.year_span(ev["date_start"], ev["date_end"], ev["date_precision"]))


@bp.route("/families/<slug>/tree")
def family_tree(slug):
    e, r = _resolve("family", slug)
    if r:
        return r
    db = get_db()
    title = queries.sub(db, e["id"], "family")["display_name"]
    return render_template("records/tree.html", e=e, kind="family", title=title, tree=graph.family_tree(db, e["id"]))


@bp.route("/people/<slug>/tree")
def person_tree(slug):
    e, r = _resolve("person", slug)
    if r:
        return r
    db = get_db()
    title = queries.sub(db, e["id"], "person")["preferred_name"]
    return render_template("records/tree.html", e=e, kind="person", title=title, tree=graph.person_tree(db, e["id"]))


@bp.route("/people/<slug>/connections")
def person_connections(slug):
    e, r = _resolve("person", slug)
    if r:
        return r
    db = get_db()
    return render_template("records/connections.html", e=e, title=queries.sub(db, e["id"], "person")["preferred_name"],
                           net=graph.network(db, e["id"]))


@bp.route("/organizations/<slug>")
def organization(slug):
    e, r = _resolve("organization", slug)
    if r:
        return r
    db = get_db()
    return render_template("records/organization.html", e=e, o=queries.sub(db, e["id"], "organization"),
                           names=queries.names(db, e["id"]), members=queries.org_members(db, e["id"]),
                           events=queries.org_events(db, e["id"]), cites=queries.citations(db, e["id"]),
                           accts=queries.accounts(db, e["id"]), revisions=queries.public_revisions(db, e["id"]),
                           photos=queries.record_photos(db, e["id"]))


@bp.route("/sources/<slug>")
def source(slug):
    e, r = _resolve("source", slug)
    if r:
        return r
    db = get_db()
    return render_template("records/source.html", e=e, s=queries.sub(db, e["id"], "source"),
                           cited_by=queries.cited_by(db, e["id"]), revisions=queries.public_revisions(db, e["id"]))


# ───────────── discovery ─────────────
@bp.route("/search")
def search_page():
    q = (request.args.get("q") or "").strip()[:200]
    kind = request.args.get("type") or None
    if kind not in SEARCHABLE_KINDS:
        kind = None
    res = search.search(get_db(), q, kind=kind, page=_page()) if q else None
    return render_template("search.html", q=q, kind=kind, res=res, kinds=SEARCHABLE_KINDS, kind_labels=KIND_LABELS)


def _year(v):
    try:
        y = int((v or "").strip())
        return y if 1000 <= y <= 2100 else None
    except ValueError:
        return None


def _regions(db):
    """Regions recorded on public places that have events (real values only, for the region filter)."""
    return [r[0] for r in db.execute(
        f"SELECT DISTINCT p.admin_region FROM places p JOIN entities e ON e.id=p.entity_id AND {PUBLIC_WHERE} "
        f"WHERE p.admin_region IS NOT NULL AND p.admin_region<>'' ORDER BY lower(p.admin_region)")]


@bp.route("/timeline/data.json")
def timeline_json():
    """All public events for the interactive timeline. Dates carry their real precision (see atlas.date_interval)."""
    from .. import atlas
    evs = atlas.timeline_events(get_db(), fmt=i18n.fdate)
    for ev in evs:
        ev["type_label"] = i18n.gettext(ev["type_label"])
        ev["precision_note"] = i18n.precision_note(ev["precision"]) if ev["precision"] not in (None, "unknown") else None
        if ev["date"] == "Unknown":
            ev["date"] = i18n.gettext("Unknown")
    return jsonify(events=evs)


_PID = re.compile(r"(?:\[)?([a-z]{3}-[a-z0-9]{8})\]?\s*$")


def _public_id(db, value, kinds):
    """The permanent id in a link value, if it names a PUBLIC record of one of these kinds; otherwise None."""
    m = _PID.search((value or "").strip())
    pid = m.group(1) if m else None
    if not pid and len(kinds) == 1:            # older links may name the record ("Test Front"): accepted if it is unambiguous
        pid, _err = records.parse_ref(db, value, kinds[0])
    if not pid:
        return None
    e = db.execute(f"SELECT e.kind FROM entities e WHERE e.public_id=? AND {PUBLIC_WHERE}", (pid,)).fetchone()
    return pid if e and e["kind"] in kinds else None


def _explore(default_mode, legacy=None):
    """The historical atlas: the 3D map and the timeline on one page, sharing one exploration state.
    Every identifier in the address is checked here: only public records enter the page's state, and the
    visitor is told when part of a link was left out (a private, unpublished or deleted record)."""
    from .. import atlas
    db = get_db()
    a = request.args
    types = db.execute("SELECT slug, label FROM event_types WHERE is_active=1 ORDER BY sort_order").fetchall()
    place_types = db.execute("SELECT slug, label FROM place_types WHERE is_active=1 ORDER BY sort_order").fetchall()
    regions = _regions(db)
    ptypes = {t["slug"] for t in place_types} | {f"cat:{c}" for c in atlas.CATEGORY_LABELS}
    st = {"mode": a.get("mode") if a.get("mode") in ("map", "timeline", "both") else default_mode,
          "q": (a.get("q") or "").strip()[:100], "from": _year(a.get("from")), "to": _year(a.get("to")),
          "type": a.get("type") if a.get("type") in {t["slug"] for t in types} else "",
          "region": a.get("region") if a.get("region") in regions else "", "media": a.get("media") == "1",
          "ptype": a.get("ptype") if a.get("ptype") in ptypes else ""}
    # the old timeline used ?place= for "events at this place"; on the explore page that is ?at=
    raw = {k: a.get(k) for k in ("at", "person", "organization", "place", "event", "record")}
    if legacy == "timeline" and raw["place"] and not raw["at"]:
        raw["at"], raw["place"] = raw["place"], None
    kinds = {"at": ("place",), "person": ("person",), "organization": ("organization",), "place": ("place",), "event": ("event",),
             "record": ("person", "family", "organization", "source", "archive_item", "oral_history", "collection")}
    dropped, labels = False, {}
    for k, v in raw.items():
        pid = _public_id(db, v, kinds[k]) if v else None
        if k == "record" and pid and atlas.record_preview(db, pid) is None:      # e.g. an archive item whose rights forbid display
            pid = None
        if v and not pid:
            dropped = True
        st[k] = pid or ""
        if pid and k in ("at", "person", "organization"):
            labels[pid] = queries.filter_label(db, kinds[k][0], pid)
    # the server-rendered lists (used without JavaScript) apply the same filters
    f = {"type": st["type"] or None, "q": st["q"] or None, "from": st["from"], "to": st["to"], "region": st["region"] or None,
         "media": st["media"] or None, "place": st["at"] or None, "person": st["person"] or None, "organization": st["organization"] or None}
    LIST_PAGE = 300
    want_list = st["mode"] in ("timeline", "both")            # with JavaScript the timeline builds its own list
    dated, undated = queries.timeline(db, f) if want_list else ([], [])
    ruler = queries.timeline_ruler(dated)
    lpages = max(1, -(-len(dated) // LIST_PAGE))
    lpage = min(max(1, request.args.get("lpage", 1, type=int)), lpages)
    total = len(dated) + len(undated)
    dated = dated[(lpage - 1) * LIST_PAGE: lpage * LIST_PAGE]
    groups = []
    for ev in dated:
        decade = f"{ev['date_start'][:3]}0s"
        if not groups or groups[-1][0] != decade:
            groups.append((decade, []))
        groups[-1][1].append(ev)
    rows = db.execute(
        f"SELECT e.slug, e.public_id, e.is_fictional_test, p.primary_name, p.latitude, p.longitude, p.coord_precision, p.admin_region, p.country "
        f"FROM entities e JOIN places p ON p.entity_id=e.id WHERE e.kind='place' AND {PUBLIC_WHERE} ORDER BY lower(p.primary_name)").fetchall()
    active = any(st[k] for k in ("q", "type", "from", "to", "region", "media", "ptype", "at", "person", "organization"))
    embed = a.get("embed") == "1"
    g.embed = embed                      # base.html leaves out the site header and footer; security.py allows the listed sites to frame it

    def nojs(**kw):           # links that work without JavaScript (mode switch, chips); same state, one value changed
        s = {**st, **kw}
        q = {k: ("1" if v is True else v) for k, v in s.items() if v not in (None, "", False)}
        return "/explore?" + urlencode({**q, **({"embed": "1"} if embed else {})})
    return render_template(
        "explore.html", st=st, labels=labels, dropped=dropped, active=active, nojs=nojs,
        clear_url=nojs(**{k: None for k in ("q", "type", "from", "to", "region", "media", "ptype", "at", "person", "organization",
                                             "place", "event", "record")}),
        groups=groups, undated=undated, total=total, ruler=ruler, lpage=lpage, lpages=lpages, want_list=want_list,
        place_ctx=atlas.place_preview(db, st["at"], fmt=i18n.fdate) if st["at"] else None,
        located=[r for r in rows if atlas.valid_coords(r["latitude"], r["longitude"])],
        unlocated=[r for r in rows if not atlas.valid_coords(r["latitude"], r["longitude"])],
        types=types, regions=regions,
        place_groups=[(c, label, [t for t in place_types if atlas.category(t["slug"]) == c]) for c, label in atlas.CATEGORY_LABELS.items()],
        category_labels=atlas.CATEGORY_LABELS, category_labels_tr={k: i18n.gettext(v) for k, v in atlas.CATEGORY_LABELS.items()},
        event_categories=atlas.EVENT_CATEGORY_LABELS,
        event_categories_tr={k: i18n.gettext(v) for k, v in atlas.EVENT_CATEGORY_LABELS.items()},
        type_categories={t["slug"]: atlas.event_category(t["slug"]) for t in types},
        tile=current_app.config.get("MAP_TILE_URL"), tile_attribution=current_app.config.get("MAP_TILE_ATTRIBUTION"),
        can_review=bool(g.get("user") and g.user.can("submission.review")), embed=embed,
        full_url="/explore?" + urlencode({k: ("1" if v is True else v) for k, v in st.items() if v not in (None, "", False)}),
        curated_n=len(explorations.published(db)))


@bp.route("/explore")
def explore():
    return _explore("both")


@bp.route("/map")
def map_page():
    return _explore("map")


@bp.route("/timeline")
def timeline():
    return _explore("timeline", legacy="timeline")

@bp.route("/explore/curated")
def curated_list():
    """Editor-curated explorations: saved selections of reviewed records, each with its description and sources."""
    from ..services import explorations
    return render_template("explore_curated.html", rows=explorations.published(get_db()))


@bp.route("/explore/curated/<slug>")
def curated(slug):
    from .. import atlas
    from ..services import explorations
    db = get_db()
    found = explorations.published(db, slug)
    if not found:
        abort(404)
    x, items = found[0]["x"], found[0]["items"]
    mapped = {r["public_id"] for r in db.execute(
        f"SELECT e.public_id FROM entities e JOIN places p ON p.entity_id=e.id WHERE {PUBLIC_WHERE} AND p.latitude IS NOT NULL")}
    for it in items:
        it["kind_label"] = i18n.gettext(KIND_LABELS.get(it["kind"], it["kind"]))
        e = entities.get_by_public_id(db, it["id"])
        if it["kind"] == "place":
            it["map"] = it["id"] in mapped
        elif it["kind"] in ("event", "person", "organization", "archive_item", "oral_history"):
            it["map"] = bool(atlas.record_places(db, e)[0])
    q = {k: v for k, v in (("from", x["period_from"]), ("to", x["period_to"]), ("region", x["region"] if x["region"] in _regions(db) else None)) if v}
    return render_template("explore_guide.html", x=x, items=items, atlas_url="/explore?" + urlencode({"mode": "both", **q}))


@bp.route("/map/data.json")
def map_json():
    """Public place data for the interactive map (same visibility rule as every public page)."""
    data = queries.map_data(get_db())
    for p in data:
        p["type_label"] = i18n.gettext(p["type_label"])
        p["precision_label"] = i18n.gettext({"exact": "Exact", "approximate": "Approximate",
                                             "region_centroid": "Region centroid"}.get(p["precision"], p["precision"]))
    resp = jsonify(places=data)
    return resp


def _tr(d, *keys):
    for k in keys:
        if d.get(k):
            d[k] = i18n.gettext(d[k])
    return d


def _captions(photos):
    """Interface labels for archive-item captions (the titles, creators and rights holders are shown as recorded)."""
    for ph in photos:
        if ph:
            ph["rights_label"] = i18n.gettext(RIGHTS_LABELS.get(ph["rights"], ph["rights"]))
            ph["item_type_label"] = i18n.gettext(ITEM_TYPE_LABELS.get(ph["item_type"], ph["item_type"]))


@bp.route("/map/place/<public_id>.json")
def map_place(public_id):
    """The atlas place panel (loaded only when a place is opened)."""
    from .. import atlas
    p = atlas.place_preview(get_db(), public_id, fmt=i18n.fdate)
    if p is None:
        abort(404)
    _captions(p["photos"] + [p["lead"]])
    _tr(p, "type_label")
    p["category_label"] = i18n.gettext(atlas.CATEGORY_LABELS[p["category"]])
    for x in p["people"]:
        _tr(x, "role")
    for ev in p["events"]:
        ev["date"] = i18n.gettext(ev["date"]) if ev["date"] == "Unknown" else ev["date"]
    return jsonify(p)


@bp.route("/map/record/<public_id>.json")
def map_record(public_id):
    """Preview of any public record and its places on the map (search results, timeline links)."""
    from .. import atlas
    r = atlas.record_preview(get_db(), public_id, fmt=i18n.fdate)
    if r is None:
        abort(404)
    r["kind_label"] = i18n.gettext(KIND_LABELS.get(r["kind"], r["kind"]))
    _captions([r["lead"]])
    return jsonify(_tr(r, "type_label", "precision_note"))


def _context_filters(db, a):
    """The explore filters a period summary may use, validated like the explore page's own."""
    types = {r[0] for r in db.execute("SELECT slug FROM event_types WHERE is_active=1")}
    return {"from": _year(a.get("from")), "to": _year(a.get("to")),
            "type": a.get("type") if a.get("type") in types else None,
            "region": a.get("region") if a.get("region") in _regions(db) else None}


@bp.route("/explore/context.json")
def explore_context():
    """A short summary of the events in a period (and region or event type), derived from the published records:
    counts and the most-linked places, people, families, collections and sources. No narrative is generated."""
    from .. import atlas
    db = get_db()
    f = _context_filters(db, request.args)
    if not (f["from"] or f["to"]):
        return jsonify(n=0)
    c = atlas.period_context(db, f)
    for t in c.get("types", []):
        t["label"] = i18n.gettext(t["label"])
    for ev in c.get("events", []):
        ev["date"] = i18n.fdate(ev.pop("date_start"), ev.pop("date_end"), ev.pop("precision"))
    return jsonify(c)


@bp.route("/map/review.json")
def map_review():
    """For reviewers only: proposed places and proposed location changes that are awaiting a decision. Never
    part of the public map data, never cached, and each links to its review page."""
    if not g.get("user") or not g.user.can("submission.review"):
        abort(404)
    db = get_db()
    out = []
    for s in db.execute("SELECT id, kind, status, proposed_data, target_entity_id FROM submissions "
                        "WHERE status IN ('submitted','under_review','needs_revision','approved') AND kind IN ('place','correction') "
                        "ORDER BY id DESC LIMIT 500").fetchall():
        d = json.loads(s["proposed_data"])
        if s["kind"] == "correction":
            target = entities.get(db, s["target_entity_id"])
            if not target or target["kind"] != "place":
                continue
            d = d.get("changes", {})
        lat, lon = d.get("latitude"), d.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        out.append({"sid": s["id"], "lat": lat, "lon": lon, "precision": d.get("coord_precision"), "status": s["status"],
                    "title": d.get("primary_name") or (entities.title_of(db, s["target_entity_id"]) if s["target_entity_id"] else ""),
                    "change": s["kind"] == "correction", "url": url_for("editor.review", sid=s["id"])})
    return jsonify(proposals=out)


@bp.route("/map/search.json")
def map_search():
    """Atlas search: places (including historical names and other spellings), people, events,
    organizations and archive records. Each result says what kind of record it is."""
    q = (request.args.get("q") or "").strip()[:100]
    if len(q) < 2:
        return jsonify(results=[])
    if not ratelimit.allow(get_db(), f"atlas-search:{request.remote_addr or '?'}", 300, 300):
        abort(429)
    res = search.search(get_db(), q, per_page=12)
    out = [{"kind": r["kind"], "kind_label": i18n.gettext(KIND_LABELS.get(r["kind"], r["kind"])), "id": r["public_id"],
            "title": r["title"], "context": r["context"], "matched_name": r["matched_name"], "fictional": r["fictional"]}
           for r in res["results"]]
    return jsonify(results=out)


@bp.route("/map/places.json")
def map_places():
    """Published places with documented coordinates, for the location picker on the contribution forms:
    just enough to show and choose them (the same public rule as the map)."""
    from .. import atlas
    rows = get_db().execute(
        f"SELECT e.public_id, p.primary_name, p.latitude, p.longitude, p.coord_precision FROM entities e "
        f"JOIN places p ON p.entity_id=e.id WHERE e.kind='place' AND {PUBLIC_WHERE} AND p.latitude IS NOT NULL "
        f"ORDER BY lower(p.primary_name) LIMIT 5000").fetchall()
    return jsonify(places=[{"id": r["public_id"], "name": r["primary_name"], "lat": r["latitude"], "lon": r["longitude"],
                            "precision": r["coord_precision"], "label": f"{r['primary_name']} [{r['public_id']}]"}
                           for r in rows if atlas.valid_coords(r["latitude"], r["longitude"])])


@bp.route("/map/basemap.json")
def basemap():
    """The archive's own base map (Natural Earth, public domain), served from this server."""
    from flask import send_from_directory
    resp = send_from_directory(current_app.static_folder, "map/eritrea-basemap.json", mimetype="application/json", max_age=86400)
    return resp


@bp.route("/archive")
def archive_list():
    rows, total = queries.list_archive(get_db(), _page())
    return render_template("archive/list.html", rows=rows, total=total, page=_page(), per_page=queries.PER_PAGE)


def _resolve_or_research(kind, slug):
    """Public resolution, or — for a vetted researcher — a restricted record they may consult.
    Returns (entity, redirect_response, research_view: bool). Every research view is logged."""
    res = entities.resolve_public(get_db(), kind, slug)
    if res is not None:
        state, e = res
        if state == "redirect":
            return None, redirect(queries.record_url(kind, e["slug"]), 301), False
        return e, None, False
    db = get_db()
    e = db.execute("SELECT * FROM entities WHERE kind=? AND slug=?", (kind, slug)).fetchone()
    if e is None or not photos.research_access(db, g.get("user"), e["id"]):
        abort(404)
    with tx(db):
        audit.log(db, g.user.id, "restricted.viewed", kind, e["public_id"], ip=request.remote_addr)
    return e, None, True


@bp.route("/archive/<slug>")
def archive_item(slug):
    e, r, research = _resolve_or_research("archive_item", slug)
    if r:
        return r
    db = get_db()
    item = queries.archive_item(db, e["id"], allow_restricted=research)
    if item is None:            # the item's own access level or rights do not allow public display
        abort(404)
    credit = None
    if item["display_name"] and item["attribution_pref"] != "anonymous":
        credit = item["username"] if item["attribution_pref"] == "username" else item["display_name"]
    return render_template("archive/item.html", e=e, item=item, credit=credit, subjects=queries.item_subjects(db, e["id"]), research=research,
                           names=queries.names(db, e["id"]), cites=queries.citations(db, e["id"]),
                           revisions=queries.public_revisions(db, e["id"]))


@bp.route("/media/<key>")
def media(key):
    """Every stored file goes through here. The access rule is re-checked on every request, so a
    copied or guessed address reveals nothing (404, exactly like a file that never existed)."""
    db = get_db()
    m = db.execute("SELECT * FROM media_files WHERE storage_key=?", (key,)).fetchone()
    user = g.get("user")
    if not m or not photos.can_view_media(db, user, m):
        abort(404)
    store = storage.from_config(current_app.config)
    try:
        path = store.path(key)
        if not path.exists():
            raise FileNotFoundError(key)
    except (FileNotFoundError, ValueError):
        current_app.logger.error("Stored file missing for media id %s", m["id"])
        abort(404)
    # researchers' views of restricted material are logged (once per download, not per byte range)
    if m["owner_id"] and m["access_level"] != "public" and user and not user.can("record.view_any") \
            and request.headers.get("Range", "bytes=0-").startswith("bytes=0-"):
        with tx(db):
            audit.log(db, user.id, "restricted.viewed", "media", m["id"], {"entity": m["owner_id"]})
    from flask import send_file
    as_download = m["file_role"] == "original" and m["mime_type"].startswith("image/") or m["mime_type"] == "application/pdf"
    resp = send_file(path, mimetype=m["mime_type"], conditional=True, etag=m["sha256"], max_age=0,
                     as_attachment=as_download,
                     download_name=(m["original_filename"] or f"archive-file{photos.EXTENSIONS.get(m['mime_type'], '')}") if as_download else None)
    if m["access_level"] != "public" or user:
        resp.headers["Cache-Control"] = "private, no-store"
    return resp


@bp.route("/lookup/<any(person,family,place,event,organization,source,archive_item,any):kind>")
def lookup(kind):
    """Type-to-search suggestions for forms. Published records only (the same data as the public lists)."""
    q = (request.args.get("q") or "").strip()[:100]
    if not ratelimit.allow(get_db(), f"lookup:{request.remote_addr or '?'}", 600, 600):
        abort(429)
    if kind == "any":
        out = []
        for k in records.LINKABLE:
            out += records.lookup(get_db(), k, q, limit=8)
        return jsonify(sorted(out, key=lambda x: x["label"].lower())[:20])
    return jsonify(records.lookup(get_db(), kind, q))


@bp.route("/language/<code>")
def set_language(code):
    """The visitor's interface language. Remembered in a cookie; historical content is not translated."""
    if code not in i18n.LANGUAGES:
        abort(404)
    resp = redirect(safe_next(request.args.get("next"), "/"))
    resp.set_cookie(i18n.COOKIE, code, max_age=365 * 24 * 3600, samesite="Lax", httponly=True,
                    secure=current_app.config["ENV"] == "production")
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


@bp.route("/collections")
def collection_list():
    return render_template("archive/collections.html", rows=collections.public_list(get_db()))


@bp.route("/collections/<slug>")
def collection(slug):
    e, r = _resolve("collection", slug)
    if r:
        return r
    db = get_db()
    return render_template("archive/collection.html", e=e, c=queries.sub(db, e["id"], "collection"),
                           items=collections.items(db, e["id"]), revisions=queries.public_revisions(db, e["id"]),
                           cites=queries.citations(db, e["id"]))


_STAMP = re.compile(r"^\s*\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]\s*")


def _transcript_lines(text):
    """Lines of a transcript; a leading [mm:ss] or [h:mm:ss] becomes a link to that moment of the recording."""
    out = []
    for line in (text or "").split("\n"):
        m = _STAMP.match(line)
        if m:
            h, mnt, s = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
            out.append({"t": h * 3600 + mnt * 60 + s, "stamp": m.group(0).strip(), "text": line[m.end():]})
        else:
            out.append({"t": None, "stamp": None, "text": line})
    return out


@bp.route("/oral-histories")
def oral_list():
    db = get_db()
    rows = db.execute(
        f"SELECT e.id, e.slug, e.is_fictional_test, o.title, o.summary, o.language, o.recorded_start, o.recorded_end, o.recorded_precision, "
        f"o.interviewee_text, pe.slug AS person_slug, p.preferred_name AS person_name FROM entities e JOIN oral_histories o ON o.entity_id=e.id "
        f"LEFT JOIN entities pe ON pe.id=o.interviewee_id AND {PUBLIC_WHERE.replace('e.', 'pe.')} LEFT JOIN people p ON p.entity_id=pe.id "
        f"WHERE e.kind='oral_history' AND {PUBLIC_WHERE} ORDER BY o.recorded_start IS NULL, o.recorded_start, lower(o.title) LIMIT 500").fetchall()
    return render_template("oral/list.html", rows=rows)


@bp.route("/oral-histories/<slug>")
def oral_history(slug):
    e, r, research = _resolve_or_research("oral_history", slug)
    if r:
        return r
    db = get_db()
    oh = queries.sub(db, e["id"], "oral_history")
    ok = oral.allowed(db, e["id"])
    show = {"recording": ok["publish_recording"] or research, "transcript": ok["publish_transcript"] or research,
            "translation": ok["publish_translation"] or research, "download": ok["allow_download"]}
    media = None
    if oh["media_item_id"]:
        media = db.execute(
            "SELECT a.media_kind, a.access_level, x.visibility, "
            "(SELECT storage_key FROM media_files WHERE owner_id=a.entity_id AND file_role='access_derivative') AS d, "
            "(SELECT storage_key FROM media_files WHERE owner_id=a.entity_id AND file_role='original') AS o "
            "FROM archive_items a JOIN entities x ON x.id=a.entity_id WHERE a.entity_id=?", (oh["media_item_id"],)).fetchone()
        if media and not (research or (media["visibility"] == "public" and media["access_level"] == "public")):
            media = None
    interviewee = queries.filter_label(db, "person", entities.get(db, oh["interviewee_id"])["public_id"]) if oh["interviewee_id"] else None
    iv_slug = entities.get(db, oh["interviewee_id"])["slug"] if interviewee else None
    return render_template("oral/item.html", e=e, oh=oh, ok=ok, show=show, research=research, media=media,
                           interviewee=interviewee, interviewee_slug=iv_slug, subjects=oral.subjects(db, e["id"]),
                           lines=_transcript_lines(oh["transcript_text"]) if show["transcript"] else [],
                           consents=oral.consents(db, e["id"]), cites=queries.citations(db, e["id"]),
                           revisions=queries.public_revisions(db, e["id"]))


@bp.route("/oral-histories/request", methods=["GET", "POST"])
def interview_request():
    """Ask the archive to record someone's testimony. Nothing is recorded or published without the
    interviewee's own, specific consent; this only starts a conversation with the editors."""
    db = get_db()
    fields = ("name", "email", "interviewee", "connection", "language", "message")
    values = {k: (request.form.get(k) or "").strip() for k in fields} if request.method == "POST" else {k: "" for k in fields}
    errors = {}
    if request.method == "POST":
        if request.form.get("website"):
            return redirect(url_for("public.oral_list"))
        if not values["email"] or "@" not in values["email"]:
            errors["email"] = "Enter a valid email address."
        if not 10 <= len(values["message"]) <= 5000:
            errors["message"] = "Write between 10 and 5,000 characters."
        if not errors:
            with tx(db):
                if not ratelimit.allow(db, f"contact:{request.remote_addr or '?'}", 5, 3600):
                    abort(429)
                body = "\n".join(f"{k.capitalize()}: {values[k][:1000]}" for k in ("interviewee", "connection", "language") if values[k])
                db.execute("INSERT INTO contact_messages(name, email, message, related_public_id) VALUES (?,?,?, 'interview-request')",
                           (values["name"][:120] or None, values["email"][:200], f"[Interview request]\n{body}\n\n{values['message']}"))
            flash("Thank you. Your message has been received and will be read by the editorial team.", "ok")
            return redirect(url_for("public.oral_list"))
    return render_template("oral/request.html", values=values, errors=errors), (400 if errors else 200)




# ───────────── static information pages ─────────────
INFO_PAGES = {"about": "About the archive", "standards": "Historical and editorial standards",
              "how-to-contribute": "How to contribute", "corrections": "How to submit corrections",
              "privacy": "Privacy policy", "terms": "Terms of use", "copyright": "Copyright and permissions",
              "accessibility": "Accessibility statement", "data-policy": "Data and licensing policy"}


@bp.route("/<any(" + ",".join(f'"{p}"' for p in INFO_PAGES) + "):page>")
def info(page):
    return render_template(f"pages/{page}.html", title=INFO_PAGES[page])


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    db = get_db()
    about = (request.values.get("about") or "").strip()[:40]
    errors, values = {}, {"name": "", "email": "", "message": "", "about": about}
    if request.method == "POST":
        values.update({k: (request.form.get(k) or "").strip() for k in ("name", "email", "message")})
        if request.form.get("website"):            # honeypot: bots fill it, people don't see it
            flash("Thank you. Your message has been received.", "ok")
            return redirect(url_for("public.home"))
        if not 10 <= len(values["message"]) <= 5000:
            errors["message"] = "Write between 10 and 5,000 characters."
        if values["email"] and "@" not in values["email"]:
            errors["email"] = "Enter a valid email address, or leave it blank."
        if not errors:
            ip = request.remote_addr or "?"
            with tx(db):
                if not ratelimit.allow(db, f"contact:{ip}", 5, 3600):
                    abort(429)
                pub_ok = about if (about and entities.get_public_by_public_id(db, about)) else None
                db.execute("INSERT INTO contact_messages(name, email, message, related_public_id) VALUES (?,?,?,?)",
                           (values["name"][:120] or None, values["email"][:200] or None, values["message"], pub_ok))
            flash("Thank you. Your message has been received and will be read by the editorial team.", "ok")
            return redirect(url_for("public.home"))
    return render_template("pages/contact.html", title="Contact", errors=errors, values=values)


# ───────────── machine-readable ─────────────
@bp.route("/robots.txt")
def robots():
    base = current_app.config["BASE_URL"]
    body = ("User-agent: *\nDisallow: /dashboard\nDisallow: /editor\nDisallow: /admin\nDisallow: /auth\n"
            f"Disallow: /contribute\nDisallow: /dev\nDisallow: /language\nSitemap: {base}/sitemap.xml\n")
    return Response(body, mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap():
    base = current_app.config["BASE_URL"]
    entries = [e for e in queries.sitemap_entries(get_db())]
    rows = "".join(f"<url><loc>{base}{queries.record_url(e['kind'], e['slug'])}</loc><lastmod>{e['updated_at'][:10]}</lastmod></url>"
                   for e in entries)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'
    return Response(xml, mimetype="application/xml")
