"""A SEPARATE sample archive for trying every part of the site: instance/sample.db (+ instance/sample-media).

It never touches the real database. Everything in it is fictional and labelled so on every page:
- every record is flagged is_fictional_test and its name ends in "(FICTIONAL)";
- dates fall between 2040 and 2099, so nothing can be mistaken for history;
- places carry TEST-ONLY coordinates (needed to try the map). They are not claims about any real place, and
  the regions are fictional ("… Test Region") — this is why the sample lives in its own database;
- images are generated placeholder graphics marked "SAMPLE IMAGE · FICTIONAL", never pictures of real events.

Records reach the archive through the same code a real contribution uses: published records through the
validation and publication functions, and the workflow examples (photos, drafts, review, revision, corrections,
forum, contact) through the site's own forms, driven by the test client as a contributor, editors and moderators."""
import io
import json
import os
import secrets
import shutil
from types import SimpleNamespace

from werkzeug.security import generate_password_hash

TAG = " (FICTIONAL)"
TOKEN = "sample-builder-csrf"

USERS = [  # username, roles, verified, what the account is for
    ("sample_admin", ("administrator", "editor"), True, "administrator: users, roles, audit log, export"),
    ("sample_editor", ("editor",), True, "editor: review queue, publish, curate, explorations"),
    ("sample_editor2", ("editor",), True, "second editor (an editor cannot review their own submissions)"),
    ("sample_moderator", ("moderator",), True, "forum moderator: reports and moderation log"),
    ("sample_researcher", ("researcher",), True, "vetted researcher: sees restricted research material"),
    ("sample_contrib", (), True, "contributor: drafts, submissions, photos, corrections, notifications"),
    ("sample_family", (), True, "family representative for the Testfield family"),
    ("sample_member", (), True, "community member: forum posts and replies"),
    ("sample_newcomer", (), False, "new account whose email is not verified yet (can draft, cannot submit)"),
]


class _Client:
    """The site's forms, as a signed-in user (CSRF token pinned as in the tests)."""
    def __init__(self, app, username=None, password=None):
        self.c = app.test_client()
        if username:
            r = self.post("/auth/login", {"identifier": username, "password": password})
            if r.status_code != 302:
                raise RuntimeError(f"sample: could not sign in as {username}")

    def get(self, url):
        return self.c.get(url)

    def post(self, url, data=None):
        with self.c.session_transaction() as s:
            s["csrf"] = TOKEN
        return self.c.post(url, data={**(data or {}), "csrf_token": TOKEN})


# ───────────── generated placeholder files ─────────────
def _image(title, colours, seed):
    """An abstract placeholder graphic, plainly labelled as a fictional sample (not a photograph)."""
    from PIL import Image, ImageDraw, ImageFont
    w, h = 1200, 800
    im = Image.new("RGB", (w, h), colours[0])
    d = ImageDraw.Draw(im)
    for i in range(0, w + h, 36):                       # diagonal hatching: obviously a graphic
        d.line([(i, 0), (i - h, h)], fill=colours[1], width=6)
    hills = [(0, h)] + [(x, int(h * (0.55 + 0.12 * ((x * (seed + 3)) % 7) / 7))) for x in range(0, w + 1, 150)] + [(w, h)]
    d.polygon(hills, fill=colours[2])
    try:
        big, small = ImageFont.load_default(size=56), ImageFont.load_default(size=30)
    except TypeError:                                   # older Pillow: the small built-in font
        big = small = ImageFont.load_default()
    d.rectangle([60, 60, w - 60, 250], fill=(255, 255, 255))
    d.text((90, 85), "SAMPLE IMAGE · FICTIONAL", fill=(27, 122, 56), font=big)
    d.text((90, 170), title[:60], fill=(28, 35, 41), font=small)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _pdf(lines):
    """A one-page PDF with plain text and no active content."""
    text = "BT /F1 18 Tf 60 760 Td 24 TL " + " ".join(f"({ln.replace('(', '[').replace(')', ']')}) Tj T*" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(text)} >>\nstream\n{text}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


# ───────────── the sample ─────────────
PLACES = [  # name, type, region, lat, lon, precision, aliases, note
    ("Saltmere", "town_city", "Coastal Test Region", "15.70", "39.36", "exact", "Salt Mere\nSaltmeer", ""),
    ("Highridge", "town_city", "Central Test Region", "15.05", "38.80", "exact", "High Ridge", ""),
    ("Amber Hollow", "village", "North Test Region", "15.95", "38.35", "approximate", "Amberhollow",
     "Only the valley is known; the exact site of the village is not documented in the sample sources."),
    ("Greenvale", "village", "West Test Region", "15.10", "37.60", "exact", "", ""),
    ("Redcliff Pass", "conflict_location", "Central Test Region", "15.55", "38.70", "exact", "", ""),
    ("Lowland Plain", "region", "West Test Region", "15.20", "37.10", "region_centroid", "The Lowlands",
     "Shown at the centre of the plain; the sample records do not name a single point."),
    ("Stonebridge Memorial", "memorial_site", "South Test Region", "14.95", "39.15", "exact", "", ""),
    ("Cedar Wells", "displacement_location", "North Test Region", "16.30", "38.05", "approximate", "Cedar Springs",
     "The camp moved several times; this is the area given in the sample relief reports."),
    ("Northpass Camp", "organizational_location", "North Test Region", "16.60", "38.60", "exact", "", ""),
    ("Old Market Quarter", "historical_site", "Coastal Test Region", None, None, None, "", ""),      # no coordinates
    ("Upper Valley", "geographic_feature", "North Test Region", None, None, None, "", ""),
]

SOURCES = {
    "minutes": "Test Front Minutes, vol. 1 (FICTIONAL) | p. 3",
    "gazette": "Saltmere Gazette (FICTIONAL) | issue 12, p. 2 | https://example.test/gazette/12",
    "register": "Highridge Municipal Register (FICTIONAL) | folio 22",
    "relief": "Relief Association Field Reports (FICTIONAL) | report 7",
    "memoir": "A Teacher's Notebook, a memoir (FICTIONAL) | ch. 4",
    "survey": "Test Survey of Villages (FICTIONAL) | map sheet 3",
}

EVENTS = [  # title, type, date, place, summary, source keys
    ("Founding meeting of the Test Front", "meeting_conference", "2061-04-12", "Northpass Camp",
     "Delegates meet at Northpass Camp and agree the founding charter of the Test Front.", ["minutes"]),
    ("Saltmere harbour strike", "community_event", "2063-09", "Saltmere",
     "Harbour workers in Saltmere stop work for nine days over wages.", ["gazette"]),
    ("Engagement at Redcliff Pass", "battle_conflict", "c. 2065", "Redcliff Pass",
     "An armed clash at Redcliff Pass. The sample sources disagree about the year.", ["minutes", "memoir"]),
    ("Highridge declaration", "statement_publication", "2066-01-20", "Highridge",
     "A public statement read in Highridge setting out the Test Front's aims.", ["register"]),
    ("Drought relief at Cedar Wells", "humanitarian_event", "2068 to 2070", "Cedar Wells",
     "Food and water distribution for families gathered at Cedar Wells during the drought.", ["relief"]),
    ("Displacement from the Lowland Plain", "displacement_migration", "2070s", "Lowland Plain",
     "Families leave the Lowland Plain over several years; only the decade is documented.", ["relief"]),
    ("Second congress of the Test Front", "meeting_conference", "2072-03 to 2072-04", "Northpass Camp",
     "A second, longer congress revises the charter.", ["minutes"]),
    ("Opening of the Greenvale school", "community_event", "2074", "Greenvale",
     "A village school opens in Greenvale with two teachers.", ["memoir"]),
    ("Ceasefire talks near Amber Hollow", "political_development", "2077-06-02", "Amber Hollow",
     "Talks held somewhere near Amber Hollow; the meeting place itself is uncertain.", ["gazette"]),
    ("Coastal radio broadcast", "statement_publication", "2079-05", "Saltmere",
     "A broadcast from Saltmere announces the ceasefire terms.", ["gazette"]),
    ("Reorganisation of the Test Front", "organizational_development", "2081", "Highridge",
     "The Test Front reorganises into regional committees.", ["minutes"]),
    ("Return of displaced families to Cedar Wells", "displacement_migration", "2083 to 2086", "Cedar Wells",
     "Families return in stages to the Cedar Wells area.", ["relief"]),
    ("Dedication of the Stonebridge Memorial", "commemoration", "2085-11-11", "Stonebridge Memorial",
     "A memorial is dedicated to those who died in the Redcliff engagement.", ["register"]),
    ("Greenvale harvest festival", "community_event", "2090s", "Greenvale",
     "An annual festival revived in the 2090s; only the decade is documented.", []),
    ("Peace conference in Highridge", "political_development", "2092-07-15", "Highridge",
     "A conference in Highridge closes the period covered by the sample.", ["register", "minutes"]),
    ("Gathering in the Old Market Quarter", "other", "", "Old Market Quarter",
     "A gathering remembered in oral accounts; its date is not documented.", []),
    ("Meeting of the coastal committee", "meeting_conference", "2069", None,
     "A committee meeting whose location is not established, so it does not appear on the map.", ["minutes"]),
]

PEOPLE = [  # key, fields
    ("amina", {"preferred_name": "Amina Testfield", "full_name": "Amina Selam Testfield", "aliases": "Amina T.\nAmina Testfeld",
               "occupation": "Teacher", "living_status": "deceased", "birth": "c. 2040", "birth_place": "Amber Hollow",
               "death": "2091-02", "death_place": "Highridge",
               "summary": "A teacher who opened the Greenvale school.",
               "biography": "Amina Testfield taught in Greenvale for twenty years.\nThis biography is sample text and describes no real person.",
               "sources": ["memoir"]}),
    ("samuel", {"preferred_name": "Samuel Testfield", "living_status": "deceased", "birth": "2062-05-14", "birth_place": "Greenvale",
                "death": "2098", "occupation": "Radio operator", "summary": "Amina's son; worked on the coastal broadcasts.", "sources": ["gazette"]}),
    ("hana", {"preferred_name": "Hana Testfield", "living_status": "unknown", "birth": "2065", "birth_place": "Greenvale",
              "summary": "Amina's daughter. Little is documented about her later life."}),
    ("daniel", {"preferred_name": "Daniel Testmark", "aliases": "Dani Testmark", "occupation": "Organizer", "living_status": "deceased",
                "birth": "2042-03-02", "birth_place": "Saltmere", "death": "2087", "death_place": "Saltmere",
                "summary": "A founding member of the Test Front.", "sources": ["minutes"]}),
    ("omar", {"preferred_name": "Omar Testmark", "living_status": "deceased", "birth": "c. 2045", "birth_place": "Saltmere",
              "death": "c. 2070", "occupation": "Harbour worker", "summary": "Daniel's brother; took part in the harbour strike."}),
    ("yonas", {"preferred_name": "Yonas Testbrook", "living_status": "deceased", "birth": "c. 2038", "death": "2065",
               "death_place": "Redcliff Pass", "summary": "Died in the Redcliff engagement.", "sources": ["memoir"]}),
    ("selam", {"preferred_name": "Selam Testbrook", "living_status": "deceased", "birth": "2041", "death": "2093",
               "birth_place": "Greenvale", "occupation": "Nurse", "summary": "Worked with the relief association at Cedar Wells.",
               "sources": ["relief"]}),
    ("ibrahim", {"preferred_name": "Ibrahim Testlake", "living_status": "deceased", "birth": "2047 to 2049", "death": "2095",
                 "occupation": "Relief coordinator", "summary": "Coordinated the drought relief; his birth year is given only as a range.",
                 "sources": ["relief"]}),
    ("ruth", {"preferred_name": "Ruth Teststone", "living_status": "unknown", "birth": "2052",
              "summary": "Named in the Highridge register; nothing else is known yet."}),
    ("messenger", {"preferred_name": "Unknown messenger of Northpass", "living_status": "unknown",
                   "summary": "A messenger mentioned in the minutes without a name or dates."}),
    ("lula", {"preferred_name": "Lula Testrow", "living_status": "living", "birth": "2071",
              "summary": "A living person: kept private until an editor records consent (you will not see her publicly)."}),
]


def build(db_path, media_root, real_db_path):
    """Create the sample database from scratch. Returns (password, report lines)."""
    if os.path.abspath(db_path) == os.path.abspath(real_db_path):
        raise RuntimeError("The sample must go in its own database, not the archive's.")
    for p in (db_path, db_path + "-wal", db_path + "-shm"):
        if os.path.exists(p):
            os.remove(p)
    shutil.rmtree(media_root, ignore_errors=True)

    from . import create_app, db as dbm
    from .db import tx
    from .services import collections, entities, explorations, records
    from .services.timeutil import now_iso

    password = "sample-" + secrets.token_urlsafe(8)
    app = create_app({"ENV": "development", "DATABASE_PATH": db_path, "MEDIA_ROOT": media_root, "AUTO_MIGRATE": True,
                      "SECRET_KEY": secrets.token_hex(32), "REQUIRE_EMAIL_VERIFICATION": True})
    conn = dbm.connect(db_path)
    report = []

    # accounts
    ids = {}
    with tx(conn):
        for name, roles, verified, _why in USERS:
            ids[name] = conn.execute(
                "INSERT INTO users(email, username, display_name, password_hash, email_verified_at) VALUES (?,?,?,?,?)",
                (f"{name}@example.test", name, name.replace("_", " ").title(), generate_password_hash(password),
                 now_iso() if verified else None)).lastrowid
            for r in roles:
                conn.execute("INSERT INTO user_roles(user_id, role) VALUES (?,?)", (ids[name], r))
    editor = ids["sample_editor"]

    def make(kind, raw, consents=None):
        """A published record through the normal validation and publication code."""
        clean, errors = records.validate(conn, kind, raw, strict_consent=False)
        if errors:
            raise RuntimeError(f"sample {kind}: {errors}")
        if consents is not None:
            clean["consents"] = {"granted": list(consents), "note": "FICTIONAL sample consent; no real interview exists."}
        sid = conn.execute("INSERT INTO submissions(kind, proposed_data, status, submitter_id, submitted_at, published_at, reviewer_id) "
                           "VALUES (?,?, 'published', ?, ?, ?, ?)",
                           (kind, json.dumps(clean), ids["sample_contrib"], now_iso(), now_iso(), editor)).lastrowid
        eid = records.apply_new(conn, kind, clean, actor_id=editor, submission_id=sid, fictional=True, consent_confirmed=consents is not None)
        conn.execute("UPDATE submissions SET result_entity_id=? WHERE id=?", (eid, sid))
        return entities.get(conn, eid)

    def link(kind, raw):
        clean, errors = records.validate(conn, kind, raw)
        if errors:
            raise RuntimeError(f"sample {kind}: {errors}")
        getattr(records, f"apply_{kind}")(conn, clean, actor_id=editor, submission_id=None)

    src = lambda keys: "\n".join(SOURCES[k] for k in keys)  # noqa: E731

    with tx(conn):
        P = {}
        for name, ptype, region, lat, lon, prec, aliases, note in PLACES:
            raw = {"primary_name": name + TAG, "place_type": ptype, "country": "Sample country (FICTIONAL)", "admin_region": region,
                   "aliases": aliases, "coord_note": note,
                   "overview": f"{name} is a fictional place in the sample archive. Its coordinates are test values for trying the map, "
                               f"not a claim about any real location.",
                   "sources": SOURCES["survey"] if lat else ""}
            if lat:
                raw.update(latitude=lat, longitude=lon, coord_precision=prec)
            P[name] = make("place", raw)
        E = {}
        for title, etype, date, place, summary, srcs in EVENTS:
            E[title] = make("event", {"title": title + TAG, "event_type": etype, "date": date,
                                      "place": P[place]["public_id"] if place else "", "summary": summary,
                                      "description": summary + "\n\nThis account is sample text written for trying the archive. It describes nothing real.",
                                      "sources": src(srcs)})
        H = {}
        for key, f in PEOPLE:
            raw = dict(f, preferred_name=f["preferred_name"] + TAG, sources=src(f.get("sources", [])))
            for k in ("birth_place", "death_place"):
                if raw.get(k):
                    raw[k] = P[raw[k]]["public_id"]
            H[key] = make("person", raw)
        F = {}
        for key, name, region, members, summary in (
                ("testfield", "Testfield family", "Amber Hollow and Greenvale (fictional)", ("amina", "samuel", "hana"),
                 "Three generations of teachers and radio operators."),
                ("testmark", "Testmark family", "Saltmere (fictional)", ("daniel", "omar"), "A harbour family from Saltmere."),
                ("testbrook", "Testbrook family", "Greenvale (fictional)", ("yonas", "selam"), "Remembered through the Redcliff memorial.")):
            F[key] = make("family", {"display_name": name + TAG, "region_note": region, "summary": summary,
                                     "narrative": f"{summary}\nThis family history is sample text and describes no real family."})
            for m in members:
                conn.execute("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility, created_by) "
                             "VALUES (?,?, 'published', 'public', ?)", (F[key]["id"], H[m]["id"], editor))
        for a, rel, b, status in (("amina", "parent_of", "samuel", "current"), ("amina", "parent_of", "hana", "current"),
                                  ("samuel", "sibling_of", "hana", "current"), ("daniel", "sibling_of", "omar", "current"),
                                  ("yonas", "spouse_of", "selam", "historical")):
            link("relationship", {"person_a": H[a]["public_id"], "person_b": H[b]["public_id"], "relationship_type": rel,
                                  "status": status, "notes": "Sample relationship (FICTIONAL)."})
        conn.execute("INSERT INTO family_representatives(user_id, family_id, granted_by) VALUES (?,?,?)",
                     (ids["sample_family"], F["testfield"]["id"], ids["sample_admin"]))
        ORG = {}
        for key, name, active, desc in (
                ("front", "Test Front", "2060 to 2090", "A fictional political organization used throughout the sample."),
                ("relief", "Test Relief Association", "2068 to 2099", "A fictional relief association."),
                ("teachers", "Test Teachers' Union", "c. 2074", "A fictional union of village teachers.")):
            ORG[key] = make("organization", {"name": name + TAG, "active": active, "description": desc + " It never existed."})
        for person, org, role, period, place in (("daniel", "front", "Founding member", "2061 to 2087", "Northpass Camp"),
                                                 ("yonas", "front", "Member", "2061 to 2065", ""),
                                                 ("amina", "teachers", "Member", "2074 to 2091", "Greenvale"),
                                                 ("ibrahim", "relief", "Coordinator", "2068 to 2086", "Cedar Wells"),
                                                 ("selam", "relief", "Nurse", "2068 to 2070", "Cedar Wells")):
            link("affiliation", {"person": H[person]["public_id"], "organization": ORG[org]["public_id"], "role": role + " (fictional)",
                                 "period": period, "place": P[place]["public_id"] if place else "", "notes": "Sample affiliation (FICTIONAL)."})
        for ev, who, role in (("Founding meeting of the Test Front", "daniel", "Chair"), ("Founding meeting of the Test Front", "yonas", "Delegate"),
                              ("Saltmere harbour strike", "omar", "Striker"), ("Engagement at Redcliff Pass", "yonas", "Combatant"),
                              ("Drought relief at Cedar Wells", "ibrahim", "Coordinator"), ("Drought relief at Cedar Wells", "selam", "Nurse"),
                              ("Opening of the Greenvale school", "amina", "Teacher"), ("Coastal radio broadcast", "samuel", "Radio operator"),
                              ("Second congress of the Test Front", "daniel", "Delegate"), ("Peace conference in Highridge", "ruth", "Observer")):
            link("participation", {"event": E[ev]["public_id"], "person": H[who]["public_id"], "role": role + " (fictional)"})
        for ev, org in (("Founding meeting of the Test Front", "front"), ("Second congress of the Test Front", "front"),
                        ("Drought relief at Cedar Wells", "relief"), ("Return of displaced families to Cedar Wells", "relief")):
            link("participation", {"event": E[ev]["public_id"], "organization": ORG[org]["public_id"], "role": "Organizer (fictional)"})
        # evidence: assessed citations, a location source, and where the sources disagree
        for title, status in (("Test Front Minutes, vol. 1 (FICTIONAL)", "well_supported"), ("Saltmere Gazette (FICTIONAL)", "source_cited"),
                              ("Relief Association Field Reports (FICTIONAL)", "testimony"), ("A Teacher's Notebook, a memoir (FICTIONAL)", "family_recollection"),
                              ("Test Survey of Villages (FICTIONAL)", "source_cited")):
            conn.execute("UPDATE citations SET evidence_status=? WHERE source_id IN (SELECT entity_id FROM sources WHERE title=?)", (status, title))
        conn.execute("UPDATE citations SET field_name='coordinates' WHERE source_id IN (SELECT entity_id FROM sources WHERE title=?)",
                     ("Test Survey of Villages (FICTIONAL)",))
        redcliff = E["Engagement at Redcliff Pass"]
        conn.execute("UPDATE citations SET evidence_status='disputed' WHERE target_id=?", (redcliff["id"],))
        for eid, topic, text, by, d, loc in (
                (redcliff["id"], "Year of the engagement", "The memoir places the engagement in 2066, a year later than the minutes.",
                 "A Teacher's Notebook (FICTIONAL)", 1, 0),
                (P["Amber Hollow"]["id"], "Location of the village", "A second account places the village on the far side of the valley, about 8 km east.",
                 "Test witness (FICTIONAL)", 0, 1)):
            conn.execute("INSERT INTO conflicting_accounts(entity_id, topic, account_text, attributed_to, is_public, concerns_date, "
                         "concerns_location, created_by) VALUES (?,?,?,?,1,?,?,?)", (eid, topic + TAG, text, by, d, loc, editor))
        conn.execute("UPDATE event_places SET is_uncertain=1 WHERE event_id=?", (E["Ceasefire talks near Amber Hollow"]["id"],))
        # oral histories: one with a published transcript, one whose consent does not allow publication
        make("oral_history", {"title": "Interview about the Greenvale school" + TAG, "interviewee": H["hana"]["public_id"],
                              "interviewer_text": "Sample Interviewer (FICTIONAL)", "recorded": "2096-06",
                              "recording_location_note": "Greenvale (fictional)", "language": "English",
                              "summary": "Hana Testfield remembers her mother's school. Sample text only.",
                              "topics": "Schools\nGreenvale\nFamily", "related": f"{P['Greenvale']['public_id']}\n{H['amina']['public_id']}",
                              "transcript_text": "[00:00] Interviewer: This is a FICTIONAL sample transcript.\n"
                                                 "[00:06] Hana Testfield: My mother opened the school in 2074.\n"
                                                 "[00:15] Hana Testfield: Nothing in this transcript describes real events.",
                              "transcript_kind": "verbatim"},
             consents=("record", "store", "publish_transcript", "use_excerpts", "research_access"))
        make("oral_history", {"title": "Interview about the harbour strike" + TAG, "interviewee_text": "A harbour worker (FICTIONAL)",
                              "recorded": "2097", "language": "English", "summary": "Recorded, but the interviewee did not agree to publication.",
                              "transcript_text": "[00:00] FICTIONAL restricted transcript.", "transcript_kind": "verbatim"},
             consents=("record", "store", "research_access"))
        conn.execute("UPDATE entities SET is_fictional_test=1")
    report.append(f"{len(P)} places, {len(E)} events, {len(H)} people, {len(F)} families, {len(ORG)} organizations, 2 oral histories")

    # ── journeys through the site's own forms ──
    users = {n: _Client(app, n, password) for n in ("sample_contrib", "sample_editor", "sample_editor2", "sample_member", "sample_moderator", "sample_family")}
    contrib, ed, ed2 = users["sample_contrib"], users["sample_editor"], users["sample_editor2"]

    def last_sid():
        return conn.execute("SELECT MAX(id) FROM submissions WHERE submitter_id=?", (ids["sample_contrib"],)).fetchone()[0]

    def status(sid):
        return conn.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0]

    def draft(kind, fields, files=()):
        contrib.post(f"/contribute/{kind}", {**fields, "action": "draft",
                                             "contributor_note": "Sample contribution (FICTIONAL), made by the sample builder."})
        sid = last_sid()
        for data, name, meta in files:
            r = contrib.c.post(f"/dashboard/submissions/{sid}/photos",
                               data={"csrf_token": TOKEN, "photo": (io.BytesIO(data), name), "rights_declared": "1", **meta},
                               content_type="multipart/form-data")
            if r.status_code not in (200, 302):
                raise RuntimeError(f"sample upload failed: {r.status_code}")
        return sid

    def submit(sid):
        contrib.post(f"/dashboard/submissions/{sid}/submit")
        if status(sid) != "submitted":
            raise RuntimeError(f"sample: submission {sid} is {status(sid)}")

    def publish(sid, public=True):
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        for (pid, rights) in conn.execute("SELECT id, rights_status FROM submission_photos WHERE submission_id=?", (sid,)).fetchall():
            ed.post(f"/editor/submissions/{sid}/photos/{pid}", {"decision": "accept", "access": "public" if public else "restricted",
                                                                "rights_status": rights})
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "approved", "message": "Thank you: checked against the sample sources."})
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "published"})
        if status(sid) != "published":
            raise RuntimeError(f"sample: submission {sid} is {status(sid)}")
        return conn.execute("SELECT result_entity_id FROM submissions WHERE id=?", (sid,)).fetchone()[0]

    green, blue = ((180, 215, 244), (160, 200, 236), (35, 158, 70)), ((226, 239, 250), (200, 222, 240), (47, 111, 168))
    meta = lambda caption, creator, taken, rights="public_domain", holder="": {  # noqa: E731
        "caption": caption + " (FICTIONAL sample image)", "creator_text": creator, "taken": taken, "rights_status": rights, "rights_holder": holder}
    with app.app_context():
        # 1. a place with photographs, contributed with a point chosen on the map, reviewed and published
        sid = draft("place", {"primary_name": "Saltmere Lighthouse" + TAG, "place_type": "historical_site", "admin_region": "Coastal Test Region",
                              "latitude": "15.74000", "longitude": "39.40000", "coord_precision": "approximate",
                              "coord_note": "Point chosen on the map by the contributor; test value.",
                              "overview": "A fictional lighthouse on the Saltmere coast.", "sources": SOURCES["gazette"]},
                    [(_image("Saltmere Lighthouse, sample graphic", green, 1), "lighthouse.jpg",
                      meta("The lighthouse seen from the harbour", "Sample Photographer (FICTIONAL)", "c. 2070")),
                     (_image("Harbour wall, sample graphic", blue, 2), "harbour.jpg",
                      meta("The harbour wall below the lighthouse", "Sample Photographer (FICTIONAL)", "2071-08",
                           "copyrighted_permission_granted", "Saltmere Gazette (FICTIONAL)"))])
        submit(sid)
        lighthouse = publish(sid)
        # 2. an event with photographs and a document
        sid = draft("event", {"title": "Opening of the Saltmere reading room" + TAG, "event_type": "community_event", "date": "2075-10-03",
                              "place": P["Saltmere"]["public_id"], "summary": "A public reading room opens in Saltmere.",
                              "sources": SOURCES["gazette"]},
                    [(_image("Reading room, sample graphic", green, 3), "reading-room.jpg",
                      meta("Readers on the opening day", "Saltmere Gazette (FICTIONAL)", "2075-10-03")),
                     (_pdf(["FICTIONAL SAMPLE DOCUMENT", "Programme for the opening of the reading room", "Saltmere, 3 October 2075",
                            "This document was generated for the sample archive."]), "programme.pdf",
                      {**meta("Printed programme for the opening", "Reading room committee (FICTIONAL)", "2075-10"), "item_type": "pamphlet_newsletter", "caption": "Printed programme for the opening (FICTIONAL sample document)"})])
        submit(sid)
        reading = publish(sid)
        # 3. photographs added to existing records through photo-only corrections
        for target, title, colours, n in ((E["Dedication of the Stonebridge Memorial"], "Memorial stone, sample graphic", blue, 4),
                                          (P["Greenvale"], "Greenvale school building, sample graphic", green, 5),
                                          (P["Highridge"], "Highridge main street, sample graphic", blue, 6),
                                          (E["Drought relief at Cedar Wells"], "Water distribution point, sample graphic", green, 7),
                                          (H["amina"], "Portrait of Amina Testfield, sample graphic", blue, 9),
                                          (H["daniel"], "Portrait of Daniel Testmark, sample graphic", green, 10),
                                          (H["selam"], "Portrait of Selam Testbrook, sample graphic", blue, 11)):
            contrib.get(f"/contribute/correction/{target['public_id']}")
            current = records.form_values(records.current_clean(conn, target["kind"], target["id"]), target["kind"], conn)
            contrib.post(f"/contribute/correction/{target['public_id']}",
                         {**current, "action": "draft", "contributor_note": "Adding a photograph (FICTIONAL sample)."})
            sid = last_sid()
            contrib.c.post(f"/dashboard/submissions/{sid}/photos",
                           data={"csrf_token": TOKEN, "photo": (io.BytesIO(_image(title, colours, n)), f"photo-{n}.jpg"), "rights_declared": "1",
                                 **meta(title.replace(", sample graphic", ""), "Sample Photographer (FICTIONAL)", f"c. {2040 + 5 * n}")},
                           content_type="multipart/form-data")
            submit(sid)
            publish(sid)
        report.append("10 photographs (3 of them on people's profiles) and 1 document published through contributions with editor review")

        # 4. contributions waiting at each step of the review workflow (for the editor and contributor dashboards)
        sid = draft("person", {"preferred_name": "Testperson Awaiting Review" + TAG, "living_status": "deceased", "birth": "c. 2050",
                               "birth_place": P["Highridge"]["public_id"], "summary": "Submitted and waiting in the editors' queue.",
                               "sources": SOURCES["register"]})
        submit(sid)
        sid = draft("event", {"title": "Market day dispute" + TAG, "event_type": "community_event", "date": "2078",
                              "place": P["Saltmere"]["public_id"], "summary": "Being reviewed by an editor right now."})
        submit(sid)
        ed2.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        sid = draft("place", {"primary_name": "Eastern Well" + TAG, "place_type": "village", "latitude": "15.40000", "longitude": "38.20000",
                              "coord_precision": "exact", "overview": "Returned to the contributor: the editor asks for a source."})
        submit(sid)
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "needs_revision",
                                                          "message": "Please add the source for these coordinates, or mark them as approximate."})
        sid = draft("place", {"primary_name": "Hilltop Shrine" + TAG, "place_type": "historical_site", "latitude": "15.85000", "longitude": "38.90000",
                              "coord_precision": "approximate", "overview": "A proposed place: shows on the reviewers' map layer.",
                              "sources": SOURCES["survey"]})
        submit(sid)
        draft("person", {"preferred_name": "Testperson Draft" + TAG, "living_status": "unknown", "summary": "A draft only the contributor can see."},
              [(_image("Unsorted family photograph, sample graphic", blue, 8), "draft.jpg",
                meta("A photograph not yet submitted", "Unknown", "", "rights_unknown"))])
        daniel = H["daniel"]
        current = records.form_values(records.current_clean(conn, "person", daniel["id"]), "person", conn)
        contrib.post(f"/contribute/correction/{daniel['public_id']}",
                     {**current, "occupation": "Organizer and harbour clerk", "action": "submit",
                      "contributor_note": "The Saltmere Gazette (FICTIONAL) also calls him a harbour clerk."})
        report.append("review queue: 1 new, 1 under review, 1 returned for revision, 1 proposed place, 1 correction; 1 private draft")

        # 5. a collection and a curated exploration
        ed.post("/editor/collections", {"title": "Saltmere in pictures" + TAG, "description": "Sample photographs and documents of Saltmere.",
                                        "visibility": "public", "is_featured": "1"})
        coll = conn.execute("SELECT e.* FROM entities e WHERE e.kind='collection' ORDER BY id DESC LIMIT 1").fetchone()
        with tx(conn):
            for (item,) in conn.execute("SELECT s.item_id FROM archive_item_subjects s WHERE s.subject_id IN (?,?)", (lighthouse, reading)).fetchall():
                collections.add_item(conn, SimpleNamespace(id=editor), coll, {"item": entities.get(conn, item)["public_id"]})
            label = lambda e: records.ref_label(conn, e["public_id"])  # noqa: E731
            explorations.create(conn, SimpleNamespace(id=editor), {
                "title": "The Test Front in the 2060s" + TAG,
                "description": "How the Test Front began: the founding meeting at Northpass Camp, the Redcliff engagement and the Highridge "
                               "declaration.\nThe sources disagree about the year of the Redcliff engagement; both accounts are kept.",
                "sources_note": "Test Front Minutes, vol. 1 (FICTIONAL); A Teacher's Notebook (FICTIONAL).",
                "period_from": "2060", "period_to": "2069", "is_published": "1",
                "items": "\n".join([label(E["Founding meeting of the Test Front"]) + " | Where the organization was founded.",
                                    label(E["Engagement at Redcliff Pass"]) + " | The date is disputed.",
                                    label(E["Highridge declaration"]), label(H["daniel"]), label(H["yonas"]), label(ORG["front"]),
                                    label(P["Northpass Camp"])])})
            explorations.create(conn, SimpleNamespace(id=editor), {
                "title": "Drought and return at Cedar Wells" + TAG,
                "description": "The relief effort at Cedar Wells and the families' return a decade later.",
                "sources_note": "Relief Association Field Reports (FICTIONAL).", "period_from": "2068", "period_to": "2086", "is_published": "1",
                "items": "\n".join([label(E["Drought relief at Cedar Wells"]), label(E["Return of displaced families to Cedar Wells"]),
                                    label(H["ibrahim"]), label(H["selam"]), label(ORG["relief"]), label(P["Cedar Wells"])])})

        # 6. community forum: topics, replies, a report for the moderator; and a message to the editors
        member, fam = users["sample_member"], users["sample_family"]
        for user, cat, title, body in (
                (contrib, "hometowns", "Memories of Saltmere harbour (FICTIONAL)", "Does anyone remember the harbour before the lighthouse was built? (Sample post.)"),
                (member, "photo-identification", "Who is in the reading room photograph? (FICTIONAL)", "I think I recognise someone on the left. (Sample post.)"),
                (fam, "family-histories", "The Testfield family of Greenvale (FICTIONAL)", "I represent the Testfield family and am collecting memories. (Sample post.)")):
            user.post(f"/community/c/{cat}/new", {"title": title, "body": body})
        topics = conn.execute("SELECT id, slug FROM forum_topics ORDER BY id").fetchall()
        for t, (user, body) in zip(topics, ((member, "My grandmother worked there. (Sample reply.)"),
                                            (contrib, "Could be Samuel Testfield? (Sample reply.)"),
                                            (contrib, "Thank you, I will send what I have. (Sample reply.)")), strict=False):
            user.post(f"/community/topics/{t['slug']}/reply", {"body": body})
        if topics:
            member.post(f"/community/topics/{topics[0]['slug']}/reply", {"body": "BUY CHEAP WATCHES (a sample spam post for the moderator)"})
            spam = conn.execute("SELECT MAX(id) FROM forum_posts").fetchone()[0]
            contrib.post("/community/report", {"post_id": str(spam), "category": "spam", "reason": "Advertising (sample report)."})
        contrib.post("/contact", {"message": "I may have a photograph of the Greenvale school. Who should I send it to? (Sample message.)",
                                  "about": P["Greenvale"]["public_id"]})
        n_cats = conn.execute("SELECT COUNT(*) FROM forum_topics").fetchone()[0]
        report.append(f"forum: {n_cats} topics with replies and 1 open report; 1 message to the editors")
    conn.execute("UPDATE entities SET is_fictional_test=1")
    conn.commit()
    counts = {k: conn.execute(f"SELECT COUNT(*) FROM entities WHERE kind='{k}'").fetchone()[0]
              for k in ("place", "event", "person", "family", "organization", "source", "archive_item", "oral_history", "collection")}
    conn.close()
    report.insert(0, "Records: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()))
    return password, report
