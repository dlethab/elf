"""Two-step sign-in (TOTP + recovery codes), the admin reset and the optional staff requirement.
All accounts are synthetic test users."""
import base64
import re
import time
import unittest

from elf_archive import create_app
from elf_archive.services import mfa
from tests.helpers import PASSWORD, make_db, make_user
from tests.test_http import Client


class Algorithm(unittest.TestCase):
    # RFC 6238 appendix B, SHA-1 vectors (truncated to 6 digits)
    SECRET = base64.b32encode(b"12345678901234567890").decode()

    def test_rfc_6238_vectors(self):
        for t, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
            self.assertEqual(mfa.code_at(self.SECRET, t), code)

    def test_clock_drift_window(self):
        t = 1111111109
        self.assertIsNotNone(mfa.matching_step(self.SECRET, mfa.code_at(self.SECRET, t - 30), t))
        self.assertIsNone(mfa.matching_step(self.SECRET, mfa.code_at(self.SECRET, t - 90), t))
        self.assertIsNone(mfa.matching_step(self.SECRET, "12345", t))

    def test_recovery_codes_are_stored_hashed(self):
        codes, stored = mfa.new_recovery_codes()
        self.assertEqual(len(codes), 10)
        for c in codes:
            self.assertNotIn(c, stored)


class Base(unittest.TestCase):
    CONFIG = {}

    def setUp(self):
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test", **self.CONFIG})
        self.alice = make_user(self.db, "alice")
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.admin = make_user(self.db, "admin1", ["administrator"])

    def turn_on(self, user):
        """Enable two-step sign-in directly, leaving the current step unused so a test can sign in with it."""
        secret = mfa.new_secret()
        codes, stored = mfa.new_recovery_codes()
        self.db.execute("UPDATE users SET totp_secret=?, totp_enabled_at='2000-01-01T00:00:00Z', recovery_codes=? WHERE id=?",
                        (secret, stored, user.id))
        return secret, codes

    def password_step(self, username):
        c = Client(self.app)
        r = c.post("/auth/login", {"identifier": username, "password": PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/auth/two-step"))
        return c

    def signed_in(self, c):
        return c.get("/dashboard").status_code == 200


class Setup(Base):
    def test_enable_from_the_dashboard(self):
        c = Client(self.app)
        c.login("alice")
        c.post("/dashboard/security", {"op": "start"})
        html = c.get("/dashboard/security").get_data(as_text=True)
        secret = re.search(r'class="secret">([A-Z2-7]+)<', html).group(1)
        self.assertIn("data:image/svg+xml;base64,", html)              # QR code rendered inline, nothing sent elsewhere
        self.assertEqual(c.post("/dashboard/security", {"op": "confirm", "code": "000000" if mfa.code_at(secret) != "000000" else "111111"}).status_code, 400)
        r = c.post("/dashboard/security", {"op": "confirm", "code": mfa.code_at(secret)})
        self.assertEqual(r.status_code, 200)
        codes = re.findall(r"\b[0-9a-f]{6}-[0-9a-f]{6}\b", r.get_data(as_text=True))
        self.assertEqual(len(codes), 10)                                # shown once
        u = self.db.execute("SELECT totp_enabled_at, recovery_codes FROM users WHERE id=?", (self.alice.id,)).fetchone()
        self.assertIsNotNone(u["totp_enabled_at"])
        self.assertNotIn(codes[0], u["recovery_codes"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='auth.mfa_enabled'").fetchone()[0], 1)

    def test_disable_needs_the_password(self):
        self.turn_on(self.alice)
        c = self.password_step("alice")
        secret = self.db.execute("SELECT totp_secret FROM users WHERE id=?", (self.alice.id,)).fetchone()[0]
        c.post("/auth/two-step", {"code": mfa.code_at(secret)})
        self.assertEqual(c.post("/dashboard/security", {"op": "disable", "password": "wrong-password-123"}).status_code, 400)
        self.assertIsNotNone(self.db.execute("SELECT totp_enabled_at FROM users WHERE id=?", (self.alice.id,)).fetchone()[0])
        self.assertEqual(c.post("/dashboard/security", {"op": "disable", "password": PASSWORD}).status_code, 302)
        self.assertIsNone(self.db.execute("SELECT totp_secret FROM users WHERE id=?", (self.alice.id,)).fetchone()[0])


class SignIn(Base):
    def test_password_alone_does_not_create_a_session(self):
        self.turn_on(self.alice)
        c = self.password_step("alice")
        self.assertFalse(self.signed_in(c))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM user_sessions").fetchone()[0], 0)

    def test_valid_code_signs_in_and_cannot_be_replayed(self):
        secret, _ = self.turn_on(self.alice)
        code = mfa.code_at(secret)
        c = self.password_step("alice")
        self.assertEqual(c.post("/auth/two-step", {"code": "abc"}).status_code, 400)
        self.assertEqual(c.post("/auth/two-step", {"code": code}).status_code, 302)
        self.assertTrue(self.signed_in(c))
        c2 = self.password_step("alice")                               # same code again, e.g. observed over a shoulder
        self.assertEqual(c2.post("/auth/two-step", {"code": code}).status_code, 400)
        self.assertFalse(self.signed_in(c2))

    def test_recovery_code_works_once(self):
        _, codes = self.turn_on(self.alice)
        c = self.password_step("alice")
        self.assertEqual(c.post("/auth/two-step", {"code": codes[0].upper()}).status_code, 302)
        self.assertEqual(mfa.remaining_codes(self.db, self.alice.id), 9)
        c2 = self.password_step("alice")
        self.assertEqual(c2.post("/auth/two-step", {"code": codes[0]}).status_code, 400)

    def test_failures_are_rate_limited(self):
        secret, _ = self.turn_on(self.alice)
        c = self.password_step("alice")
        for _ in range(6):
            c.post("/auth/two-step", {"code": "999999" if mfa.code_at(secret) != "999999" else "888888"})
        r = c.post("/auth/two-step", {"code": mfa.code_at(secret)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Too many failed attempts", r.get_data(as_text=True))

    def test_pending_step_expires(self):
        secret, _ = self.turn_on(self.alice)
        c = self.password_step("alice")
        with c.c.session_transaction() as s:
            s["mfa_pending"] = {**s["mfa_pending"], "exp": int(time.time()) - 1}
        r = c.post("/auth/two-step", {"code": mfa.code_at(secret)})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/auth/login"))
        self.assertFalse(self.signed_in(c))

    def test_two_step_page_without_a_password_step(self):
        r = Client(self.app).get("/auth/two-step")
        self.assertEqual(r.status_code, 302)


class AdminReset(Base):
    def test_admin_reset_turns_it_off_and_ends_sessions(self):
        secret, _ = self.turn_on(self.alice)
        user = self.password_step("alice")
        user.post("/auth/two-step", {"code": mfa.code_at(secret)})
        self.assertTrue(self.signed_in(user))
        a = Client(self.app)
        a.login("admin1")
        self.assertEqual(a.post(f"/admin/users/{self.alice.id}/reset_mfa").status_code, 302)
        self.assertIsNone(self.db.execute("SELECT totp_enabled_at FROM users WHERE id=?", (self.alice.id,)).fetchone()[0])
        self.assertFalse(self.signed_in(user))
        row = self.db.execute("SELECT actor_id FROM audit_logs WHERE action='auth.mfa_disabled'").fetchone()
        self.assertEqual(row[0], self.admin.id)
        Client(self.app).login("alice")                                # password alone works again

    def test_only_admins_can_reset(self):
        self.turn_on(self.alice)
        e = Client(self.app)
        e.login("editor1")
        self.assertEqual(e.post(f"/admin/users/{self.alice.id}/reset_mfa").status_code, 403)
        self.assertIsNotNone(self.db.execute("SELECT totp_enabled_at FROM users WHERE id=?", (self.alice.id,)).fetchone()[0])


class StaffRequirement(Base):
    CONFIG = {"REQUIRE_STAFF_MFA": True}

    def test_staff_without_two_step_are_sent_to_set_it_up(self):
        e = Client(self.app)
        e.login("editor1")
        r = e.get("/editor")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/dashboard/security"))

    def test_staff_with_two_step_can_work(self):
        secret, _ = self.turn_on(self.editor)
        e = self.password_step("editor1")
        e.post("/auth/two-step", {"code": mfa.code_at(secret)})
        self.assertEqual(e.get("/editor").status_code, 200)

    def test_research_access_also_needs_two_step(self):
        import dataclasses
        from elf_archive.services import photos
        researcher = make_user(self.db, "res1", ["researcher"])
        eid = self.db.execute("INSERT INTO entities(kind, public_id, slug, publication_status, visibility) "
                              "VALUES ('archive_item','MFA-AI-1','mfa-item-fictional','published','restricted')").lastrowid
        self.db.execute("INSERT INTO archive_items(entity_id, title, item_type, access_level) VALUES (?,?,?,?)",
                        (eid, "Restricted item (FICTIONAL)", "photograph", "restricted"))
        with self.app.app_context():
            self.assertFalse(photos.research_access(self.db, researcher, eid))
            self.assertTrue(photos.research_access(self.db, dataclasses.replace(researcher, mfa_enabled=True), eid))

    def test_contributors_are_not_affected(self):
        c = Client(self.app)
        c.login("alice")
        self.assertEqual(c.get("/contribute/person").status_code, 200)


if __name__ == "__main__":
    unittest.main()
