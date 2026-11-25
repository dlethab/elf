"""DEVELOPMENT-ONLY fictional records for trying the interface.

Rules (spec §24.2): every record is flagged is_fictional_test=1 and visibly labelled on every page;
names end in "(FICTIONAL)"; no coordinates are given (we never invent geography, even for tests);
dated events use the year 2099 so nothing can be mistaken for history. Refuses to run in production
(see cli.py). Records still pass through the normal validation and publication code path."""
import json
import secrets

from .db import tx
from .services import entities, records
from .services.timeutil import now_iso
from werkzeug.security import generate_password_hash

DEV_USERS = [("dev_admin", ("administrator", "editor")), ("dev_editor", ("editor",)),
             ("dev_editor2", ("editor",)), ("dev_moderator", ("moderator",)), ("dev_contrib", ()), ("dev_rep", ())]

TAG = " (FICTIONAL)"


def _maker(conn, ids, actor):
    def make(kind, raw, consents=None):
        clean, errors = records.validate(conn, kind, raw, strict_consent=False)
        assert not errors, errors
        if consents is not None:
            clean["consents"] = {"granted": list(consents), "note": "FICTIONAL test consent; no real interview exists."}
        sid = conn.execute("INSERT INTO submissions(kind, proposed_data, status, submitter_id, submitted_at, published_at, reviewer_id) "
                           "VALUES (?,?, 'published', ?, ?, ?, ?)", (kind, json.dumps(clean), ids["dev_contrib"], now_iso(), now_iso(), actor)).lastrowid
        eid = records.apply_new(conn, kind, clean, actor_id=actor, submission_id=sid, fictional=True,
                                consent_confirmed=consents is not None)
        conn.execute("UPDATE submissions SET result_entity_id=? WHERE id=?", (eid, sid))
        return entities.get(conn, eid)
    return make


def _valid(conn, kind, raw):
    clean, errors = records.validate(conn, kind, raw)
    assert not errors, (kind, errors)
    return clean


def _add_user(conn, name, roles, password):
    cur = conn.execute("INSERT INTO users(email, username, display_name, password_hash, email_verified_at) VALUES (?,?,?,?,?)",
                       (f"{name}@example.test", name, name.replace("_", " ").title(), generate_password_hash(password), now_iso()))
    for r in roles:
        conn.execute("INSERT INTO user_roles(user_id, role) VALUES (?,?)", (cur.lastrowid, r))
    return cur.lastrowid


def seed(conn):
    if conn.execute("SELECT 1 FROM users WHERE username='dev_admin'").fetchone():
        return seed_more(conn)
    password = "dev-" + secrets.token_urlsafe(9)
    first = conn.execute("SELECT COALESCE(MAX(id), 0) FROM entities").fetchone()[0]
    with tx(conn):
        ids = {name: _add_user(conn, name, roles, password) for name, roles in DEV_USERS}
        actor = ids["dev_editor"]
        make = _maker(conn, ids, actor)

        place = make("place", {"primary_name": "Testville" + TAG, "aliases": "Testvil\nTestvilla",
                               "place_type": "town_city",
                               "overview": "FICTIONAL test place for development. It has no coordinates on purpose."})
        fam = make("family", {"display_name": "Testfamily" + TAG, "region_note": "Testville (fictional)",
                              "summary": "FICTIONAL family record for development testing.",
                              "narrative": "This narrative is placeholder text for interface testing only.\nIt describes no real family."})
        a = make("person", {"preferred_name": "Testperson Alpha" + TAG, "aliases": "Testperson Alfa\nT. Alpha",
                            "living_status": "deceased", "birth": "c. 2099", "birth_place": place["public_id"],
                            "summary": "FICTIONAL person used to test profiles, aliases and uncertain dates.",
                            "sources": "Test Source Book (FICTIONAL) | p. 1 | https://example.test/book"})
        b = make("person", {"preferred_name": "Testperson Beta" + TAG, "living_status": "unknown", "birth": "2099",
                            "summary": "FICTIONAL person used to test relationships."})
        make("person", {"preferred_name": "Testperson Living" + TAG, "living_status": "living",
                        "summary": "FICTIONAL living person: must stay restricted and never appear publicly."})
        ev = make("event", {"title": "Test event: interface drill" + TAG, "event_type": "community_event",
                            "date": "2099-03 to 2099-05", "place": place["public_id"],
                            "summary": "FICTIONAL event used to test the timeline and date ranges."})
        make("event", {"title": "Test event with unknown date" + TAG, "event_type": "other",
                       "summary": "FICTIONAL event: its date is unknown and must be shown as unknown."})
        rel = records.validate(conn, "relationship", {"person_a": a["public_id"], "person_b": b["public_id"],
                                                      "relationship_type": "parent_of", "status": "uncertain",
                                                      "notes": "FICTIONAL relationship for testing."})[0]
        records.apply_relationship(conn, rel, actor_id=actor, submission_id=None)
        for p in (a, b):
            conn.execute("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility, created_by) "
                         "VALUES (?,?, 'published', 'public', ?)", (fam["id"], p["id"], actor))
        conn.execute("INSERT INTO event_participants(event_id, person_id, role, evidence_status, publication_status) "
                     "VALUES (?,?, 'Participant (fictional)', 'unverified', 'published')", (ev["id"], a["id"]))
        conn.execute("INSERT INTO family_representatives(user_id, family_id, granted_by) VALUES (?,?,?)",
                     (ids["dev_rep"], fam["id"], ids["dev_admin"]))
        # records created along the way (e.g. a source record made from a citation) are test data too
        conn.execute("UPDATE entities SET is_fictional_test=1 WHERE id>?", (first,))
    more = seed_more(conn, password)
    return ("Added fictional test records and dev accounts: " + ", ".join(n for n, _ in DEV_USERS) +
            f"\nPassword for all dev accounts: {password}\n(Development only. Do not reuse.)\n" + more)


def seed_more(conn, password=None):
    """Organizations, affiliations, an oral history, forum topics and a researcher account. Added to a
    database seeded before these sections existed, too (each part is skipped if already present)."""
    if conn.execute("SELECT 1 FROM organizations WHERE name=?", ("Test Front" + TAG,)).fetchone():
        return "Test data already present. Delete instance/archive.db to start over."
    new_password = password or "dev-" + secrets.token_urlsafe(9)
    uid = lambda n: conn.execute("SELECT id FROM users WHERE username=?", (n,)).fetchone()[0]  # noqa: E731
    pid = lambda name: conn.execute("SELECT e.public_id FROM entities e JOIN entity_names n ON n.entity_id=e.id "  # noqa: E731
                                    "WHERE n.name=? AND n.name_type='preferred'", (name,)).fetchone()[0]
    first = conn.execute("SELECT COALESCE(MAX(id), 0) FROM entities").fetchone()[0]
    with tx(conn):
        ids = {n: uid(n) for n, _ in DEV_USERS}
        created = []
        if not conn.execute("SELECT 1 FROM users WHERE username='dev_researcher'").fetchone():
            ids["dev_researcher"] = _add_user(conn, "dev_researcher", ("researcher",), new_password)
            created.append("dev_researcher")
        actor = ids["dev_editor"]
        make = _maker(conn, ids, actor)
        alpha, beta = pid("Testperson Alpha" + TAG), pid("Testperson Beta" + TAG)
        place, event = pid("Testville" + TAG), pid("Test event: interface drill" + TAG)
        org = make("organization", {"name": "Test Front" + TAG, "aliases": "TF-F", "active": "2098 to 2099",
                                    "description": "FICTIONAL organization used to test affiliations, organization pages and "
                                                   "connection diagrams. It never existed."})
        make("organization", {"name": "Test Support Committee" + TAG, "active": "c. 2099",
                              "description": "FICTIONAL second organization, with no documented members, to test empty states."})
        for person, role, period in ((alpha, "Test role: organizer (fictional)", "2098 to 2099"), (beta, None, None)):
            clean = _valid(conn, "affiliation", {"person": person, "organization": org["public_id"], "role": role or "",
                                                 "period": period or "", "place": place if role else "",
                                                 "notes": "FICTIONAL affiliation for testing."})
            records.apply_affiliation(conn, clean, actor_id=actor, submission_id=None)
        clean = _valid(conn, "participation", {"event": event, "organization": org["public_id"], "role": "Organizer (fictional)"})
        records.apply_participation(conn, clean, actor_id=actor, submission_id=None)
        make("oral_history", {"title": "Test interview about Testville" + TAG, "interviewee": alpha,
                              "interviewer_text": "Test Interviewer (FICTIONAL)", "recorded": "2099-06",
                              "recording_location_note": "Testville (fictional)", "language": "English",
                              "summary": "FICTIONAL interview with a transcript and no recording, used to test consent display.",
                              "topics": "Testing\nInterface", "related": place,
                              "transcript_text": "[00:00] Interviewer: This is a FICTIONAL test transcript.\n"
                                                 "[00:05] Testperson Alpha: Nothing in it describes real events.\n"
                                                 "[00:12] Interviewer: Thank you.",
                              "transcript_kind": "verbatim"},
             consents=("record", "store", "publish_transcript", "research_access"))
        cat = lambda slug: conn.execute("SELECT id FROM forum_categories WHERE slug=?", (slug,)).fetchone()[0]  # noqa: E731
        for slug, title, body, reply in (
                ("hometowns", "Test topic: memories of Testville (FICTIONAL)",
                 "This is a FICTIONAL forum post for development testing.", "A FICTIONAL reply, to test threads and notifications."),
                ("photo-identification", "Test topic: who is in this photo? (FICTIONAL)",
                 "A FICTIONAL request for help identifying people in a photograph.", None)):
            now = now_iso()
            t = conn.execute("INSERT INTO forum_topics(category_id, slug, title, author_id, created_at, last_post_at) VALUES (?,?,?,?,?,?)",
                             (cat(slug), title.lower().replace(" ", "-").replace(":", "").replace("?", "").replace("(", "").replace(")", "")[:80],
                              title, ids["dev_contrib"], now, now)).lastrowid
            conn.execute("INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)", (t, ids["dev_contrib"], body, now))
            if reply:
                conn.execute("INSERT INTO forum_posts(topic_id, author_id, body, created_at) VALUES (?,?,?,?)", (t, ids["dev_rep"], reply, now))
        conn.execute("UPDATE entities SET is_fictional_test=1 WHERE id>?", (first,))
    msg = "Added fictional organizations, affiliations, an oral history and forum topics."
    if created and not password:
        msg += f"\nNew dev account: dev_researcher, password: {new_password}\n(Development only. Do not reuse.)"
    elif created:
        msg += " Also added dev_researcher (same password)."
    return msg
