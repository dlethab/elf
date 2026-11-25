"""Production settings: refusal to start insecurely, HSTS, secure cookies, and reverse-proxy handling."""
import unittest

from flask import request

from elf_archive import create_app
from tests.helpers import make_db

PROD = {"ENV": "production", "DATABASE_PATH": ":memory:", "SECRET_KEY": "p" * 40, "BASE_URL": "https://archive.example"}


class Production(unittest.TestCase):
    def app(self, **kw):
        return create_app({**PROD, "_SHARED_CONNECTION": make_db(), **kw})

    def test_refuses_weak_secret_or_plain_http(self):
        with self.assertRaises(RuntimeError):
            self.app(SECRET_KEY="short")
        with self.assertRaises(RuntimeError):
            self.app(BASE_URL="http://archive.example")

    def test_hsts_and_secure_cookie(self):
        app = self.app()
        r = app.test_client().get("/", base_url="https://archive.example")
        self.assertIn("max-age=31536000", r.headers["Strict-Transport-Security"])
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])

    def test_no_hsts_in_development(self):
        app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": make_db(), "SECRET_KEY": "x" * 40})
        self.assertNotIn("Strict-Transport-Security", app.test_client().get("/").headers)


class ReverseProxy(unittest.TestCase):
    def make(self, proxies):
        app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": make_db(), "SECRET_KEY": "x" * 40,
                          "TRUSTED_PROXIES": proxies})
        app.add_url_rule("/_whoami", "whoami", lambda: f"{request.remote_addr} {request.scheme}")
        return app.test_client()

    def test_visitor_address_comes_from_the_proxy_when_configured(self):
        c = self.make(1)
        r = c.get("/_whoami", headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"},
                  environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertEqual(r.get_data(as_text=True), "203.0.113.9 https")

    def test_forwarded_headers_are_ignored_without_a_proxy(self):
        c = self.make(0)                                   # otherwise anyone could fake their address to dodge rate limits
        r = c.get("/_whoami", headers={"X-Forwarded-For": "203.0.113.9"}, environ_base={"REMOTE_ADDR": "198.51.100.4"})
        self.assertTrue(r.get_data(as_text=True).startswith("198.51.100.4"))

    def test_only_the_configured_number_of_hops_is_trusted(self):
        c = self.make(1)
        r = c.get("/_whoami", headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
        self.assertTrue(r.get_data(as_text=True).startswith("203.0.113.9"))   # a spoofed first entry is ignored


class EmailDelivery(unittest.TestCase):
    """Queued email through a fake SMTP client (no network)."""

    class FakeSMTP:
        def __init__(self, box, fail):
            self.box, self.fail = box, fail

        def __enter__(self):
            if self.fail:
                raise ConnectionRefusedError("mail server down")
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            self.box.append(msg)

    def setUp(self):
        from elf_archive.services import accounts
        self.accounts = accounts
        self.db = make_db()
        self.db.execute("INSERT INTO outbox(to_email, subject, body) VALUES ('a@example.test', 'Verify (TEST)', 'Body text (TEST)')")
        self.box = []

    def run_once(self, fail=False):
        return self.accounts.deliver_outbox(self.db, lambda: self.FakeSMTP(self.box, fail), "Archive <no-reply@example.test>")

    def row(self):
        return self.db.execute("SELECT sent_at, error, attempts FROM outbox").fetchone()

    def test_sends_once(self):
        self.assertEqual(self.run_once(), 1)
        self.assertEqual(self.box[0]["To"], "a@example.test")
        self.assertIsNotNone(self.row()["sent_at"])
        self.assertEqual(self.run_once(), 0)                     # never sent twice
        self.assertEqual(len(self.box), 1)

    def test_temporary_failure_is_retried(self):
        self.assertEqual(self.run_once(fail=True), 0)
        self.assertEqual((self.row()["error"], self.row()["attempts"]), ("ConnectionRefusedError", 1))
        self.assertEqual(self.run_once(), 1)
        self.assertIsNotNone(self.row()["sent_at"])

    def test_gives_up_after_the_limit(self):
        for _ in range(self.accounts.MAX_EMAIL_ATTEMPTS + 2):
            self.run_once(fail=True)
        self.assertEqual(self.row()["attempts"], self.accounts.MAX_EMAIL_ATTEMPTS)
        self.assertEqual(self.run_once(), 0)
        self.assertEqual(self.box, [])


if __name__ == "__main__":
    unittest.main()
