"""Interface languages: switching, right-to-left layout, catalogue completeness, and the rule that
historical content is never translated. All records are synthetic and labelled fictional."""
import json
import string
import unittest

from elf_archive import create_app, i18n
from tests.helpers import make_db, make_user, publish_new
from tests.i18n_keys import required
from tests.test_http import Client


def placeholders(s):
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


class Catalogues(unittest.TestCase):
    def test_every_interface_string_is_translated(self):
        need = required(make_db())
        for lang in ("ti", "ar"):
            missing = sorted(need - set(i18n.catalog(lang)))
            self.assertEqual(missing, [], f"{lang} is missing {len(missing)} strings; run: python -m tests.i18n_keys {lang}")

    def test_translations_keep_the_same_placeholders(self):
        for lang in ("ti", "ar"):
            for src, dst in i18n.catalog(lang).items():
                self.assertEqual(placeholders(src), placeholders(dst), f"{lang}: {src!r}")
                self.assertTrue(dst.strip(), f"{lang}: empty translation for {src!r}")

    def test_catalogues_are_marked_as_drafts(self):
        for lang in ("ti", "ar"):
            meta = json.loads((i18n.CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))["_meta"]
            self.assertEqual(meta["status"], "draft")


class Switching(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test"})
        self.contrib = make_user(self.db, "contrib")
        self.editor = make_user(self.db, "editor1", ["editor"])

    def visit(self, lang):
        c = Client(self.app)
        if lang:
            r = c.get(f"/language/{lang}?next=/people")
            self.assertEqual((r.status_code, r.headers["Location"]), (302, "/people"))
            self.assertIn(f"{i18n.COOKIE}={lang}", r.headers["Set-Cookie"])
            self.assertIn("no-store", r.headers["Cache-Control"])
        return c

    def test_english_is_the_default(self):
        html = self.visit(None).get("/").get_data(as_text=True)
        self.assertIn('<html lang="en" dir="ltr">', html)
        self.assertIn(">People<", html)
        self.assertNotIn("lang-note", html)

    def test_arabic_is_right_to_left(self):
        html = self.visit("ar").get("/").get_data(as_text=True)
        self.assertIn('<html lang="ar" dir="rtl">', html)
        self.assertIn("الأشخاص", html)
        self.assertIn("ابحث في الأرشيف", html)
        self.assertIn("lang-note", html)                       # the draft-translation notice is shown

    def test_tigrinya(self):
        html = self.visit("ti").get("/").get_data(as_text=True)
        self.assertIn('<html lang="ti" dir="ltr">', html)
        self.assertIn("ሰባት", html)
        self.assertIn('aria-current="true">ትግርኛ', html.replace("\n", "").replace("               ", ""))

    def test_switcher_links_return_to_the_current_page(self):
        html = self.visit(None).get("/people?letter=T").get_data(as_text=True)
        self.assertIn('href="/language/ar?next=/people%3Fletter%3DT"', html)

    def test_unknown_language_and_open_redirect_are_refused(self):
        c = Client(self.app)
        self.assertEqual(c.get("/language/xx").status_code, 404)
        for bad in ("//evil.test/", "https://evil.test/", "/\\evil.test"):
            self.assertEqual(c.get(f"/language/ar?next={bad}").headers["Location"], "/")

    def test_historical_content_is_shown_as_recorded(self):
        p = publish_new(self.db, self.contrib, self.editor, "person",
                        {"preferred_name": "Testperson Lingua (FICTIONAL)", "biography": "Written in English (FICTIONAL).",
                         "birth": "2099-03"})
        html = self.visit("ar").get(f"/people/{p['slug']}").get_data(as_text=True)
        self.assertIn("Testperson Lingua (FICTIONAL)", html)
        self.assertIn("Written in English (FICTIONAL).", html)
        self.assertIn("مارس 2099", html)                       # month names are interface text, so localised
        self.assertIn("السيرة", html)

    def test_uncertain_dates_stay_uncertain_in_every_language(self):
        ev = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Approx Lingua (FICTIONAL)", "date": "c. 2099"})
        u = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Undated Lingua (FICTIONAL)"})
        ti = self.visit("ti")
        self.assertIn("ኣስታት 2099", ti.get(f"/events/{ev['slug']}").get_data(as_text=True))
        self.assertIn("ዘይፍለጥ", ti.get(f"/events/{u['slug']}").get_data(as_text=True))

    def test_staff_pages_are_marked_english(self):
        c = self.visit("ar")
        c.login("editor1")
        html = c.get("/editor").get_data(as_text=True)
        self.assertIn('<main id="main" tabindex="-1" lang="en" dir="ltr">', html)
        self.assertIn("هذه الصفحة متاحة حاليًا باللغة الإنجليزية فقط", html)

    def test_draft_notice_disappears_once_a_review_is_recorded(self):
        i18n.catalog("ar")
        try:
            i18n._reviewed["ar"] = True
            html = self.visit("ar").get("/people").get_data(as_text=True)
            self.assertNotIn("lang-note", html)
            html = self.visit("ar").get("/privacy").get_data(as_text=True)    # English-only pages still say so
            self.assertIn("lang-note", html)
            self.assertNotIn("مسودة", html.split("lang-note", 1)[1].split("</div>", 1)[0])
        finally:
            i18n._reviewed["ar"] = False

    def test_info_pages_are_translated_but_legal_drafts_stay_english(self):
        c = self.visit("ar")
        about = c.get("/about").get_data(as_text=True)
        self.assertIn("عن الأرشيف", about)
        self.assertNotIn('<main id="main" tabindex="-1" lang="en" dir="ltr">', about)
        for page in ("privacy", "terms", "copyright", "data-policy"):
            html = c.get(f"/{page}").get_data(as_text=True)
            self.assertIn('<main id="main" tabindex="-1" lang="en" dir="ltr">', html, page)

    def test_form_errors_are_translated(self):
        c = self.visit("ar")
        c.login("contrib")
        html = c.post("/contribute/person", {"preferred_name": "", "action": "draft"}).get_data(as_text=True)
        self.assertIn("هذا الحقل مطلوب.", html)

    def test_public_pages_vary_by_cookie(self):
        r = self.visit("ar").get("/")
        self.assertIn("Cookie", r.headers.get("Vary", ""))


class Gettext(unittest.TestCase):
    def test_fallback_and_broken_translations_never_break_a_page(self):
        app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": make_db(), "SECRET_KEY": "x" * 40})
        with app.test_request_context("/"):
            from flask import g
            g.lang = "ar"
            self.assertEqual(i18n.gettext("A string nobody translated"), "A string nobody translated")
            i18n.catalog("ar")["Broken {n}"] = "مكسور {m}"
            try:
                self.assertEqual(i18n.gettext("Broken {n}", n=3), "Broken 3")
            finally:
                del i18n.catalog("ar")["Broken {n}"]


if __name__ == "__main__":
    unittest.main()
