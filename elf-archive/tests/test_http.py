"""HTTP-level tests through the real routes. Covers the spec's end-to-end scenarios 1–9, 13, 14 and 16
plus CSRF, sessions, headers and leak checks. All data is synthetic and labelled fictional."""
import json
import re
import unittest

from elf_archive import create_app
from elf_archive.services import entities, families
from tests.helpers import PASSWORD, make_db, make_user, publish_new

TOKEN = "test-csrf-token"


class Client:
    def __init__(self, app):
        self.c = app.test_client()

    def _csrf(self):
        with self.c.session_transaction() as s:
            s["csrf"] = TOKEN       # pages rendered by GET mint a fresh token; pin ours before each POST

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, data=None, csrf=True, **kw):
        self._csrf()
        data = dict(data or {})
        if csrf:
            data.setdefault("csrf_token", TOKEN)
        return self.c.post(url, data=data, **kw)

    def login(self, username):
        r = self.post("/auth/login", {"identifier": username, "password": PASSWORD})
        assert r.status_code == 302, r.get_data(as_text=True)[:500]
        return r


class Base(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test"})
        self.contrib = make_user(self.db, "contrib")
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.editor2 = make_user(self.db, "editor2", ["editor"])
        self.admin = make_user(self.db, "admin1", ["administrator", "editor"])
        self.mod = make_user(self.db, "mod1", ["moderator"])
        self.place = publish_new(self.db, self.contrib, self.editor, "place", {"primary_name": "Testville (FICTIONAL)"})

    def client(self, username=None):
        c = Client(self.app)
        if username:
            c.login(username)
        return c

    def sub_id(self):
        return self.db.execute("SELECT MAX(id) FROM submissions").fetchone()[0]


class PublicNavigation(Base):
    def test_visitor_follows_person_to_family_to_event(self):            # spec scenario 1
        p = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson Nav (FICTIONAL)"})
        f = publish_new(self.db, self.contrib, self.editor, "family", {"display_name": "Testfamily Nav (FICTIONAL)"})
        ev = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Test event Nav (FICTIONAL)", "date": "2099",
                                                                       "place": self.place["public_id"]})
        self.db.execute("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility) VALUES (?,?, 'published','public')", (f["id"], p["id"]))
        self.db.execute("INSERT INTO event_participants(event_id, person_id, publication_status) VALUES (?,?, 'published')", (ev["id"], p["id"]))
        c = self.client()
        html = c.get(f"/people/{p['slug']}").get_data(as_text=True)
        self.assertIn(f"/families/{f['slug']}", html)
        self.assertIn(f"/events/{ev['slug']}", html)
        fam_html = c.get(f"/families/{f['slug']}").get_data(as_text=True)
        self.assertIn(f"/people/{p['slug']}", fam_html)
        ev_html = c.get(f"/events/{ev['slug']}").get_data(as_text=True)
        self.assertIn(f"/places/{self.place['slug']}", ev_html)
        self.assertIn(f"/people/{p['slug']}", ev_html)
        self.assertEqual(c.get(f"/places/{self.place['slug']}").status_code, 200)

    def test_uncertain_dates_display_honestly(self):                     # spec scenario 14
        a = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Approx event (FICTIONAL)", "date": "c. 2099"})
        u = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Undated event (FICTIONAL)"})
        r = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Range event (FICTIONAL)", "date": "2098 to 2099"})
        c = self.client()
        self.assertIn("c. 2099", c.get(f"/events/{a['slug']}").get_data(as_text=True))
        self.assertIn("2098–2099", c.get(f"/events/{r['slug']}").get_data(as_text=True))
        uh = c.get(f"/events/{u['slug']}").get_data(as_text=True)
        self.assertIn("Unknown", uh)
        self.assertIn("not documented", uh)
        tl = c.get("/timeline").get_data(as_text=True)
        undated_section = tl.split('id="undated"')[1]
        self.assertIn("Undated event (FICTIONAL)", undated_section)       # listed apart, never given a fake date

    def test_alias_search_reaches_canonical_profile_once(self):          # spec scenario 16
        p = publish_new(self.db, self.contrib, self.editor, "person",
                        {"preferred_name": "Testperson Ghebreab (FICTIONAL)", "aliases": "Gebreab\nGhebre'ab\nገብረኣብ"})
        c = self.client()
        for q in ("gebreab", "ghebre'ab", "GHEBREAB", "ገብረኣብ", "gebre"):
            html = c.get(f"/search?q={q}").get_data(as_text=True)
            self.assertEqual(html.count(f'href="/people/{p["slug"]}"'), 1, q)
        self.assertIn("Matched name", c.get("/search?q=gebreab").get_data(as_text=True))

    def test_slug_change_redirects_and_permanent_id_resolves(self):
        p = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson Slug (FICTIONAL)"})
        entities.change_slug(self.db, p["id"], "testperson-renamed", self.editor.id)
        c = self.client()
        r = c.get(f"/people/{p['slug']}")
        self.assertEqual((r.status_code, r.headers["Location"]), (301, "/people/testperson-renamed"))
        r = c.get(f"/id/{p['public_id']}")
        self.assertEqual((r.status_code, r.headers["Location"]), (301, "/people/testperson-renamed"))

    def test_every_main_nav_item_opens(self):
        c = self.client()
        for path in ("/", "/people", "/map", "/timeline", "/families", "/archive", "/oral-histories", "/community", "/about",
                     "/standards", "/how-to-contribute", "/corrections", "/privacy", "/terms", "/copyright",
                     "/accessibility", "/contact", "/data-policy", "/places", "/events", "/sources", "/search"):
            self.assertEqual(c.get(path).status_code, 200, path)


class ContributionWorkflow(Base):
    def test_full_cycle_draft_revision_publish_search_and_related_pages(self):    # spec scenarios 2–7
        c, ed = self.client("contrib"), self.client("editor1")
        form = {"preferred_name": "Testperson Workflow (FICTIONAL)", "living_status": "deceased", "birth": "c. 2099",
                "birth_place": self.place["public_id"], "summary": "Synthetic test person.", "action": "draft"}
        r = c.post("/contribute/person", form)
        self.assertEqual(r.status_code, 302)
        sid = self.sub_id()
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0], "draft")
        self.assertEqual(c.post(f"/dashboard/submissions/{sid}/submit").status_code, 302)
        anon = self.client()
        self.assertNotIn("Workflow", anon.get("/search?q=workflow").get_data(as_text=True).split("<main")[1])

        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "needs_revision", "message": "Please add a source.",
                                                          "internal_note": "CONFIDENTIAL-NOTE"})
        page = c.get(f"/dashboard/submissions/{sid}").get_data(as_text=True)
        self.assertIn("Please add a source.", page)
        self.assertNotIn("CONFIDENTIAL-NOTE", page)                       # contributor never sees internal notes

        form.update(sources="Test Ledger (FICTIONAL) | p. 3 | https://example.test/ledger", action="submit")
        self.assertEqual(c.post(f"/dashboard/submissions/{sid}/edit", form).status_code, 302)
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0], "submitted")

        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "approved"})
        self.assertNotIn("Testperson Workflow", anon.get("/people").get_data(as_text=True))   # approved ≠ public
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "published"})
        s = self.db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        self.assertEqual(s["status"], "published")
        e = entities.get(self.db, s["result_entity_id"])

        self.assertIn(f"/people/{e['slug']}", anon.get("/search?q=workflow").get_data(as_text=True))
        self.assertIn("Testperson Workflow", anon.get("/people").get_data(as_text=True))
        self.assertIn("Testperson Workflow", anon.get(f"/places/{self.place['slug']}").get_data(as_text=True))
        ph = anon.get(f"/people/{e['slug']}").get_data(as_text=True)
        self.assertIn("Test Ledger (FICTIONAL)", ph)
        self.assertIn("c. 2099", ph)
        self.assertIn("Unverified", ph)                                   # contributor sources start unverified
        self.assertTrue(self.db.execute("SELECT 1 FROM notifications WHERE user_id=? AND kind='submission.published'",
                                        (self.contrib.id,)).fetchone())

    def test_correction_via_http_shows_diff_and_keeps_old_name(self):
        p = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson Oldname (FICTIONAL)"})
        c, ed = self.client("contrib"), self.client("editor1")
        self.assertIn("Testperson Oldname", c.get(f"/contribute/correction/{p['public_id']}").get_data(as_text=True))
        r = c.post(f"/contribute/correction/{p['public_id']}", {"preferred_name": "Testperson Newname (FICTIONAL)",
                                                                "living_status": "unknown", "action": "submit"})
        self.assertEqual(r.status_code, 302)
        sid = self.sub_id()
        review = ed.get(f"/editor/submissions/{sid}").get_data(as_text=True)
        self.assertIn("diff-old", review)
        self.assertIn("Testperson Newname", review)
        for to in ("under_review", "approved", "published"):
            ed.post(f"/editor/submissions/{sid}/transition", {"to": to})
        anon = self.client()
        self.assertIn("Testperson Newname", anon.get(f"/people/{p['slug']}").get_data(as_text=True))
        self.assertIn(f"/people/{p['slug']}", anon.get("/search?q=oldname").get_data(as_text=True))

    def test_correction_with_no_change_is_rejected_by_form(self):
        p = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson Same (FICTIONAL)"})
        c = self.client("contrib")
        form = {"preferred_name": "Testperson Same (FICTIONAL)", "living_status": "unknown"}
        r = c.post(f"/contribute/correction/{p['public_id']}", {**form, "action": "submit"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("not changed anything", r.get_data(as_text=True))
        # An unchanged correction MAY be saved as a draft (so a photo can be added), but not submitted empty.
        r = c.post(f"/contribute/correction/{p['public_id']}", {**form, "action": "draft"})
        self.assertEqual(r.status_code, 302)
        sid = self.sub_id()
        c.post(f"/dashboard/submissions/{sid}/submit")
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0], "draft")

    def test_invalid_form_returns_accessible_errors(self):
        r = self.client("contrib").post("/contribute/person", {"preferred_name": "", "birth": "1952-02-30", "action": "draft"})
        self.assertEqual(r.status_code, 400)
        html = r.get_data(as_text=True)
        self.assertIn('id="error-summary"', html)
        self.assertIn('aria-invalid="true"', html)
        self.assertIn("calendar date does not exist", html)

    def test_unverified_user_can_draft_but_not_submit(self):
        make_user(self.db, "newbie", verified=False)
        c = self.client("newbie")
        c.post("/contribute/family", {"display_name": "Testfamily Unverified (FICTIONAL)", "action": "submit"})
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (self.sub_id(),)).fetchone()[0], "draft")

    def test_editor_cannot_review_own_submission_over_http(self):
        ed = self.client("editor1")
        ed.post("/contribute/family", {"display_name": "Testfamily Self (FICTIONAL)", "action": "submit"})
        sid = self.sub_id()
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0], "submitted")
        self.client("editor2").post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0], "under_review")


class Authorization(Base):
    def test_family_rep_proposes_but_cannot_publish(self):              # spec scenario 8
        make_user(self.db, "rep")
        a = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson P (FICTIONAL)"})
        b = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson C (FICTIONAL)"})
        fam = publish_new(self.db, self.contrib, self.editor, "family", {"display_name": "Testfamily Rep (FICTIONAL)"})
        c = self.client("rep")
        self.assertEqual(c.get(f"/contribute/relationship?family={fam['public_id']}").status_code, 403)   # no grant yet
        families.grant(self.db, self.editor.id, "rep", fam["id"])
        r = c.post(f"/contribute/relationship?family={fam['public_id']}",
                   {"family": fam["public_id"], "person_a": a["public_id"], "person_b": b["public_id"],
                    "relationship_type": "parent_of", "action": "submit"})
        self.assertEqual(r.status_code, 302)
        sid = self.sub_id()
        for to in ("under_review", "approved", "published"):             # forged editor requests
            self.assertEqual(c.post(f"/editor/submissions/{sid}/transition", {"to": to}).status_code, 403)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM relationships").fetchone()[0], 0)
        self.assertEqual(c.get("/editor").status_code, 403)

    def test_restricted_record_denied_everywhere_public(self):          # spec scenario 9
        p = publish_new(self.db, self.contrib, self.editor, "person",
                        {"preferred_name": "Testperson Hidden (FICTIONAL)", "living_status": "living", "birth_place": self.place["public_id"]})
        other = publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": "Testperson Visible (FICTIONAL)"})
        self.db.execute("INSERT INTO relationships(person_a_id, person_b_id, relationship_type, publication_status, visibility) "
                        "VALUES (?,?, 'sibling_of', 'published', 'public')", (min(p["id"], other["id"]), max(p["id"], other["id"])))
        for who in (None, "contrib", "mod1"):
            c = self.client(who)
            self.assertEqual(c.get(f"/people/{p['slug']}").status_code, 404)
            self.assertEqual(c.get(f"/id/{p['public_id']}").status_code, 404)
            for page in ("/people", "/search?q=hidden", f"/places/{self.place['slug']}", f"/people/{other['slug']}", "/sitemap.xml"):
                self.assertNotIn("Hidden", c.get(page).get_data(as_text=True), (who, page))
            self.assertEqual(c.get(f"/contribute/correction/{p['public_id']}").status_code, 404 if who else 302)
        self.assertEqual(self.client("editor1").get(f"/editor/records/{p['public_id']}").status_code, 200)

    def test_cannot_elevate_own_role_or_touch_others(self):             # spec scenario 13
        c = self.client("contrib")
        self.assertEqual(c.post(f"/admin/users/{self.contrib.id}/roles", {"role": "administrator", "action": "grant"}).status_code, 403)
        self.assertEqual(c.post(f"/admin/users/{self.editor.id}/deactivate").status_code, 403)
        self.assertEqual(self.client("editor1").post(f"/admin/users/{self.editor.id}/roles", {"role": "administrator", "action": "grant"}).status_code, 403)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM user_roles WHERE role='administrator'").fetchone()[0], 1)
        # someone else's submission is invisible and immutable
        other = self.client("editor2")
        other.post("/contribute/family", {"display_name": "Testfamily Other (FICTIONAL)", "action": "draft"})
        sid = self.sub_id()
        self.assertEqual(c.get(f"/dashboard/submissions/{sid}").status_code, 404)
        self.assertEqual(c.post(f"/dashboard/submissions/{sid}/withdraw").status_code, 404)
        self.assertEqual(c.post(f"/dashboard/submissions/{sid}/edit", {"display_name": "Hijack", "action": "draft"}).status_code, 404)
        self.assertNotIn("Hijack", self.db.execute("SELECT proposed_data FROM submissions WHERE id=?", (sid,)).fetchone()[0])
        # profile updates only ever touch the signed-in user, whatever is posted
        c.post("/dashboard/profile", {"display_name": "Changed", "attribution_pref": "username", "user_id": self.editor.id, "id": self.editor.id})
        self.assertEqual(self.db.execute("SELECT display_name FROM users WHERE id=?", (self.editor.id,)).fetchone()[0], "Editor1")

    def test_moderator_has_no_archive_or_admin_access(self):
        c = self.client("mod1")
        for path in ("/editor", "/editor/records", "/editor/messages", "/admin", "/admin/users", "/admin/audit"):
            self.assertEqual(c.get(path).status_code, 403, path)

    def test_admin_grants_role_and_it_is_audited(self):
        a = self.client("admin1")
        self.assertEqual(a.post(f"/admin/users/{self.contrib.id}/roles", {"role": "editor", "action": "grant"}).status_code, 302)
        self.assertIn("editor", [r[0] for r in self.db.execute("SELECT role FROM user_roles WHERE user_id=? AND revoked_at IS NULL", (self.contrib.id,))])
        self.assertTrue(self.db.execute("SELECT 1 FROM audit_logs WHERE action='role.granted' AND actor_id=?", (self.admin.id,)).fetchone())
        a.post(f"/admin/users/{self.admin.id}/roles", {"role": "administrator", "action": "revoke"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM user_roles WHERE role='administrator' AND revoked_at IS NULL").fetchone()[0], 1)


class SessionsAndSecurity(Base):
    def test_csrf_required_on_every_post(self):
        c = self.client("contrib")
        self.assertEqual(c.post("/contribute/family", {"display_name": "X", "action": "draft"}, csrf=False).status_code, 400)
        self.assertEqual(c.post("/auth/logout", csrf=False).status_code, 400)
        self.assertEqual(c.post("/contribute/family", {"display_name": "X", "action": "draft", "csrf_token": "wrong"}).status_code, 400)

    def test_logout_revokes_session_server_side(self):
        c = self.client("contrib")
        with c.c.session_transaction() as s:
            stolen = s["sid"]
        c.post("/auth/logout")
        thief = self.client()
        with thief.c.session_transaction() as s:
            s["sid"] = stolen
        self.assertEqual(thief.get("/dashboard").status_code, 302)

    def test_deactivation_ends_sessions(self):
        c = self.client("contrib")
        self.assertEqual(c.get("/dashboard").status_code, 200)
        self.client("admin1").post(f"/admin/users/{self.contrib.id}/deactivate")
        self.assertEqual(c.get("/dashboard").status_code, 302)
        self.assertEqual(self.client().post("/auth/login", {"identifier": "contrib", "password": PASSWORD}).status_code, 400)

    def test_login_lockout_after_repeated_failures(self):
        c = self.client()
        for _ in range(5):
            c.post("/auth/login", {"identifier": "contrib", "password": "wrong-password"})
        r = c.post("/auth/login", {"identifier": "contrib", "password": PASSWORD})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Too many failed attempts", r.get_data(as_text=True))

    def test_open_redirect_blocked(self):
        for nxt in ("//evil.test/", "https://evil.test/", "/\\evil.test"):
            r = self.client().post("/auth/login", {"identifier": "contrib", "password": PASSWORD, "next": nxt})
            self.assertEqual(r.headers["Location"], "/dashboard", nxt)

    def test_headers_and_cache_policy(self):
        c = self.client()
        r = c.get("/people")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("must-revalidate", r.headers["Cache-Control"])
        self.assertIn("no-store", self.client("contrib").get("/people").headers["Cache-Control"])
        self.assertIn("no-store", c.get("/auth/login").headers["Cache-Control"])

    def test_registration_verification_and_reset_flow(self):
        c = self.client()
        r = c.post("/auth/register", {"email": "new@example.test", "username": "newuser", "display_name": "New",
                                      "password": "a long enough phrase", "password2": "a long enough phrase"})
        self.assertEqual(r.status_code, 302)
        body = self.db.execute("SELECT body FROM outbox WHERE to_email='new@example.test'").fetchone()[0]
        token = re.search(r"/auth/verify/(\S+)", body).group(1)
        self.assertEqual(c.get(f"/auth/verify/{token}").status_code, 302)
        self.assertIsNotNone(self.db.execute("SELECT email_verified_at FROM users WHERE username='newuser'").fetchone()[0])
        self.assertEqual(c.get(f"/auth/verify/{token}").status_code, 302)          # reuse is harmless
        # reset: same response for unknown address (no enumeration)
        anon = self.client()
        r1 = anon.post("/auth/forgot", {"email": "new@example.test"})
        r2 = anon.post("/auth/forgot", {"email": "nobody@example.test"})
        self.assertEqual((r1.status_code, r1.headers["Location"]), (r2.status_code, r2.headers["Location"]))
        body = self.db.execute("SELECT body FROM outbox WHERE subject='Reset your password'").fetchone()[0]
        rt = re.search(r"/auth/reset/(\S+)", body).group(1)
        self.assertEqual(anon.post(f"/auth/reset/{rt}", {"password": "another long phrase", "password2": "another long phrase"}).status_code, 302)
        self.assertEqual(anon.post(f"/auth/reset/{rt}", {"password": "third long phrase!", "password2": "third long phrase!"}).status_code, 400)
        self.assertEqual(c.get("/dashboard").status_code, 302)               # reset signed out the old session
        self.assertEqual(anon.post("/auth/login", {"identifier": "newuser", "password": "another long phrase"}).status_code, 302)

    def test_no_secrets_in_audit_log(self):
        self.client().post("/auth/login", {"identifier": "contrib", "password": "my-secret-guess"})
        self.client("contrib")
        dump = json.dumps([dict(r) for r in self.db.execute("SELECT * FROM audit_logs")])
        self.assertNotIn("my-secret-guess", dump)
        self.assertNotIn(PASSWORD, dump)

    def test_contact_form_honeypot_and_storage(self):
        c = self.client()
        c.post("/contact", {"message": "Bot message here", "website": "http://spam.test"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM contact_messages").fetchone()[0], 0)
        c.post("/contact", {"message": "A genuine correction request (FICTIONAL).", "about": self.place["public_id"]})
        self.assertEqual(self.db.execute("SELECT related_public_id FROM contact_messages").fetchone()[0], self.place["public_id"])


class Production(unittest.TestCase):
    def test_production_refuses_insecure_config_and_hides_dev_routes(self):
        with self.assertRaises(RuntimeError):
            create_app({"ENV": "production", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": make_db()})
        app = create_app({"ENV": "production", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": make_db(),
                          "SECRET_KEY": "s" * 48, "BASE_URL": "https://archive.example"})
        self.assertEqual(app.test_client().get("/dev/outbox").status_code, 404)
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])


if __name__ == "__main__":
    unittest.main()
