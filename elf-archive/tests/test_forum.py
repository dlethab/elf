"""Community forum and moderation, including spec scenario 12 (a member reports a post and a moderator
processes it). All posts are synthetic and labelled fictional."""
import sqlite3
import unittest

from elf_archive import create_app
from elf_archive.services import forum
from tests.helpers import make_db, make_user
from tests.test_http import Client


class Base(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test"})
        self.alice = make_user(self.db, "alice")
        self.bob = make_user(self.db, "bob")
        self.newbie = make_user(self.db, "newbie", verified=False)
        self.mod = make_user(self.db, "mod1", ["moderator"])
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.admin = make_user(self.db, "admin1", ["administrator"])

    def client(self, username=None):
        c = Client(self.app)
        if username:
            c.login(username)
        return c

    def topic(self, c=None, title="Test topic about a village (FICTIONAL)", body="First post (FICTIONAL)."):
        c = c or self.client("alice")
        r = c.post("/community/c/hometowns/new", {"title": title, "body": body})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        return r.headers["Location"].rsplit("/", 1)[1]

    def post_id(self):
        return self.db.execute("SELECT MAX(id) FROM forum_posts").fetchone()[0]


class Posting(Base):
    def test_reading_is_public_posting_needs_a_verified_account(self):
        slug = self.topic()
        anon = self.client()
        self.assertEqual(anon.get("/community").status_code, 200)
        self.assertIn("First post (FICTIONAL).", anon.get(f"/community/topics/{slug}").get_data(as_text=True))
        self.assertEqual(anon.post(f"/community/topics/{slug}/reply", {"body": "x"}).status_code, 302)   # to sign-in
        nb = self.client("newbie")
        nb.post(f"/community/topics/{slug}/reply", {"body": "Unverified reply (FICTIONAL)"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0], 1)

    def test_reply_notifies_the_author_and_content_is_escaped(self):
        slug = self.topic()
        bob = self.client("bob")
        bob.post(f"/community/topics/{slug}/reply", {"body": "<script>alert(1)</script> see https://example.test/page."})
        html = self.client().get(f"/community/topics/{slug}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn('<a href="https://example.test/page" rel="nofollow ugc noopener noreferrer">', html)
        n = self.db.execute("SELECT * FROM notifications WHERE user_id=?", (self.alice.id,)).fetchone()
        self.assertEqual(n["kind"], "forum.reply")
        bob.post(f"/community/topics/{slug}/reply", {"body": "https://a.test https://b.test https://c.test https://d.test"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0], 2)           # too many links

    def test_editing_own_posts_within_24_hours_keeps_the_previous_text(self):
        slug = self.topic()
        pid = self.post_id()
        self.assertEqual(self.client("bob").post(f"/community/posts/{pid}/edit", {"body": "Hijack"}).status_code, 404)
        a = self.client("alice")
        a.post(f"/community/posts/{pid}/edit", {"body": "Corrected first post (FICTIONAL)."})
        self.assertEqual(self.db.execute("SELECT previous_body FROM forum_post_edits").fetchone()[0], "First post (FICTIONAL).")
        self.assertIn("Corrected first post", self.client().get(f"/community/topics/{slug}").get_data(as_text=True))
        self.db.execute("UPDATE forum_posts SET created_at='2000-01-01T00:00:00Z' WHERE id=?", (pid,))
        r = a.post(f"/community/posts/{pid}/edit", {"body": "Too late (FICTIONAL)."})
        self.assertEqual(r.status_code, 400)
        self.assertIn("24 hours", r.get_data(as_text=True))
        self.assertNotIn("Too late", self.db.execute("SELECT body FROM forum_posts WHERE id=?", (pid,)).fetchone()[0])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM forum_post_edits")                     # append-only

    def test_topic_rate_limit(self):
        a = self.client("alice")
        for i in range(5):
            self.topic(a, title=f"Test topic number {i} (FICTIONAL)")
        r = a.post("/community/c/hometowns/new", {"title": "One too many (FICTIONAL)", "body": "x" * 10})
        self.assertEqual(r.status_code, 400)

    def test_forum_search_and_profiles(self):
        self.topic(title="Test question about registers (FICTIONAL)")
        self.assertIn("Test question about registers", self.client().get("/community/search?q=registers").get_data(as_text=True))
        self.assertIn("Test question about registers", self.client().get("/community/users/alice").get_data(as_text=True))
        self.db.execute("UPDATE users SET anonymized_at='2000-01-01T00:00:00Z' WHERE id=?", (self.alice.id,))
        self.assertEqual(self.client().get("/community/users/alice").status_code, 404)


class Moderation(Base):
    def test_report_and_moderate(self):                                          # spec scenario 12
        slug = self.topic()
        self.client("bob").post(f"/community/topics/{slug}/reply", {"body": "Offensive reply (FICTIONAL)."})
        pid = self.post_id()
        alice = self.client("alice")
        alice.post("/community/report", {"post_id": pid, "category": "harassment", "reason": "Insulting (FICTIONAL)"})
        m = self.client("mod1")
        html = m.get("/moderation").get_data(as_text=True)
        self.assertIn("Offensive reply (FICTIONAL).", html)
        self.assertIn("Harassment or abuse", html)
        m.post(f"/moderation/posts/{pid}", {"action": "remove"})                  # a reason is required
        self.assertEqual(self.db.execute("SELECT status FROM forum_posts WHERE id=?", (pid,)).fetchone()[0], "visible")
        m.post(f"/moderation/posts/{pid}", {"action": "remove", "reason": "Breaks rule 1 (FICTIONAL)"})
        html = self.client().get(f"/community/topics/{slug}").get_data(as_text=True)
        self.assertNotIn("Offensive reply", html)
        self.assertIn("This post was removed by a moderator.", html)
        rid = self.db.execute("SELECT id FROM reports").fetchone()[0]
        m.post(f"/moderation/reports/{rid}", {"status": "actioned", "note": "Removed (FICTIONAL)"})
        self.assertEqual(self.db.execute("SELECT status FROM reports").fetchone()[0], "actioned")
        actions = [r[0] for r in self.db.execute("SELECT action FROM moderation_actions")]
        self.assertEqual(actions, ["post_remove", "report_actioned"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE moderation_actions SET reason='x'")          # the moderation log is append-only

    def test_restrictions_warnings_locks_and_escalation(self):
        slug = self.topic()
        m = self.client("mod1")
        m.post(f"/moderation/users/{self.bob.id}", {"days": "7", "reason": "Repeated insults (FICTIONAL)"})
        bob = self.client("bob")
        bob.post(f"/community/topics/{slug}/reply", {"body": "Still posting (FICTIONAL)"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0], 1)
        note = self.db.execute("SELECT message FROM notifications WHERE user_id=?", (self.bob.id,)).fetchone()[0]
        self.assertIn("Repeated insults (FICTIONAL)", note)
        tid = self.db.execute("SELECT id FROM forum_topics").fetchone()[0]
        m.post(f"/moderation/topics/{tid}", {"action": "lock", "reason": "Cooling off (FICTIONAL)"})
        self.client("alice").post(f"/community/topics/{slug}/reply", {"body": "After lock (FICTIONAL)"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0], 1)
        m.post(f"/moderation/topics/{tid}", {"action": "hide", "reason": "Private information (FICTIONAL)"})
        self.assertEqual(self.client().get(f"/community/topics/{slug}").status_code, 404)
        self.assertEqual(m.get(f"/community/topics/{slug}").status_code, 200)
        self.client("alice").post("/community/report", {"topic_id": tid, "category": "threat", "reason": "Threat (FICTIONAL)"})
        rid = self.db.execute("SELECT id FROM reports").fetchone()[0]
        m.post(f"/moderation/reports/{rid}", {"status": "escalated", "note": "Needs an administrator (FICTIONAL)"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND kind='forum.escalated'",
                                         (self.admin.id,)).fetchone()[0], 1)

    def test_least_privilege(self):
        self.assertEqual(self.client("alice").get("/moderation").status_code, 403)
        self.assertEqual(self.client("editor1").get("/moderation").status_code, 403)   # editors are not moderators
        self.assertEqual(self.client("admin1").get("/moderation").status_code, 200)
        self.assertEqual(self.client("mod1").get("/editor").status_code, 403)          # moderators see no archive queue
        self.topic()
        pid = self.post_id()
        self.assertEqual(self.client("alice").post(f"/moderation/posts/{pid}", {"action": "hide", "reason": "x"}).status_code, 403)

    def test_render_never_produces_script_links(self):
        html = str(forum.render("javascript:alert(1) and http://ok.test/\"onmouseover=x"))
        self.assertNotIn('href="javascript', html)
        self.assertNotIn('" onmouseover', html)


if __name__ == "__main__":
    unittest.main()
