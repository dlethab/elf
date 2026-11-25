"""Photo uploads on contributions: file validation, metadata stripping, per-request access control
(including guessed URLs), editorial decisions, rights, and publication. Every image is generated
here (plain colour blocks) and every record is labelled fictional."""
import hashlib
import io
import shutil
import tempfile
import unittest

from PIL import Image

from elf_archive import create_app
from elf_archive.services import entities
from tests.helpers import make_db, make_user, publish_new
from tests.test_http import Client

GPS_IFD = 0x8825


def jpeg(color=(120, 80, 40), size=(900, 600), gps=True):
    im = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[0x010F] = "TestCameraMaker"
    if gps:
        exif[GPS_IFD] = {1: "N", 2: (15.0, 20.0, 0.0), 3: "E", 4: (38.0, 55.0, 0.0)}
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def png(size=(300, 200)):
    buf = io.BytesIO()
    Image.new("RGBA", size, (10, 120, 200, 128)).save(buf, "PNG")
    return buf.getvalue()


class PhotoBase(unittest.TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="elf-media-test-")
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test", "MEDIA_ROOT": self.media,
                               "MAX_PHOTO_BYTES": 2 * 1024 * 1024, "MAX_PHOTOS_PER_SUBMISSION": 3})
        self.contrib = make_user(self.db, "contrib")
        self.other = make_user(self.db, "other")
        self.unverified = make_user(self.db, "newbie", verified=False)
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.mod = make_user(self.db, "mod1", ["moderator"])

    def tearDown(self):
        shutil.rmtree(self.media, ignore_errors=True)

    def client(self, username=None):
        c = Client(self.app)
        if username:
            c.login(username)
        return c

    def draft(self, c, name="Testperson Photo (FICTIONAL)", **extra):
        r = c.post("/contribute/person", {"preferred_name": name, "living_status": "unknown", "action": "draft", **extra})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:300])
        return self.db.execute("SELECT MAX(id) FROM submissions").fetchone()[0]

    def upload(self, c, sid, data=None, filename="photo.jpg", headers=None, **meta):
        form = {"caption": "Test caption (FICTIONAL)", "rights_status": "copyrighted_permission_granted",
                "rights_declared": "1", "rights_holder": "Test Holder (FICTIONAL)", **meta}
        form["photo"] = (io.BytesIO(jpeg() if data is None else data), filename)
        return c.post(f"/dashboard/submissions/{sid}/photos", form, headers=headers or {})

    def keys(self, sid):
        rows = self.db.execute("SELECT file_role, storage_key FROM media_files WHERE submission_id=? ORDER BY id DESC", (sid,))
        return {r["file_role"]: r["storage_key"] for r in rows}

    def photo_id(self, sid):
        return self.db.execute("SELECT MAX(id) FROM submission_photos WHERE submission_id=?", (sid,)).fetchone()[0]

    def review_and(self, ed, sid, *steps, decision=None):
        """Drive the editor side: start review, decide on the photo, approve, publish."""
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        if decision:
            ed.post(f"/editor/submissions/{sid}/photos/{self.photo_id(sid)}", decision)
        for to in steps:
            ed.post(f"/editor/submissions/{sid}/transition", {"to": to, "message": "ok"})
        return self.db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()

    def submit_with_photo(self, name="Testperson Photo (FICTIONAL)", **extra):
        c = self.client("contrib")
        sid = self.draft(c, name, **extra)
        self.assertEqual(self.upload(c, sid).status_code, 302)
        c.post(f"/dashboard/submissions/{sid}/submit")
        return c, sid


class Uploading(PhotoBase):
    def test_original_is_preserved_and_public_copies_carry_no_metadata(self):
        c = self.client("contrib")
        sid = self.draft(c)
        data = jpeg()
        self.assertEqual(self.upload(c, sid, data).status_code, 302)
        k = self.keys(sid)
        self.assertEqual(set(k), {"original", "access_derivative", "thumbnail"})
        orig = self.db.execute("SELECT * FROM media_files WHERE storage_key=?", (k["original"],)).fetchone()
        self.assertEqual(orig["sha256"], hashlib.sha256(data).hexdigest())     # untouched original
        self.assertEqual(c.get(f"/media/{k['original']}").data, data)
        self.assertTrue(Image.open(io.BytesIO(data)).getexif().get_ifd(GPS_IFD))  # the test file really has GPS
        for role in ("access_derivative", "thumbnail"):
            body = c.get(f"/media/{k[role]}").data
            im = Image.open(io.BytesIO(body))
            self.assertEqual(im.format, "JPEG")
            self.assertFalse(im.getexif().get_ifd(GPS_IFD), role)
            self.assertNotIn(b"TestCameraMaker", body, role)
        self.assertLessEqual(max(Image.open(io.BytesIO(c.get(f"/media/{k['thumbnail']}").data)).size), 480)
        self.assertEqual(self.db.execute("SELECT owner_id FROM media_files WHERE storage_key=?", (k["original"],)).fetchone()[0], None)

    def test_png_with_transparency_is_accepted(self):
        c = self.client("contrib")
        sid = self.draft(c)
        self.assertEqual(self.upload(c, sid, png(), "x.png").status_code, 302)
        self.assertEqual(self.db.execute("SELECT mime_type FROM media_files WHERE file_role='original'").fetchone()[0], "image/png")

    def test_file_type_is_checked_from_content_not_name(self):
        c = self.client("contrib")
        sid = self.draft(c)
        # a real PDF named .jpg is filed as a document (its content decides), never shown as an image
        self.assertEqual(self.upload(c, sid, b"%PDF-1.4 test document (FICTIONAL)\n%%EOF", "evil.jpg").status_code, 302)
        self.assertEqual(self.db.execute("SELECT media_kind FROM submission_photos").fetchone()[0], "document")
        c.post(f"/dashboard/submissions/{sid}/photos/{self.photo_id(sid)}/remove")
        for data, name in ((b"MZ\x90\x00 an executable", "evil.jpg"), (b"<script>alert(1)</script>", "x.png"),
                           (b"GIF89a" + b"\x00" * 50, "x.gif"), (b"", "empty.jpg"), (jpeg()[:200], "truncated.jpg")):
            r = self.upload(c, sid, data, name)
            self.assertEqual(r.status_code, 400, name)
        gif = io.BytesIO()
        Image.new("RGB", (20, 20)).save(gif, "GIF")
        self.assertEqual(self.upload(c, sid, gif.getvalue(), "real.gif").status_code, 400)   # format not accepted
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_files").fetchone()[0], 0)
        self.assertEqual([f for f in __import__("pathlib").Path(self.media).rglob("*") if f.is_file()], [])   # nothing stored

    def test_size_limit(self):
        c = self.client("contrib")
        sid = self.draft(c)
        big = jpeg() + b"\x00" * (2 * 1024 * 1024)
        r = self.upload(c, sid, big)
        self.assertEqual(r.status_code, 400)
        self.assertIn("too large", r.get_data(as_text=True))

    def test_caption_rights_and_declaration_are_required(self):
        c = self.client("contrib")
        sid = self.draft(c)
        r = self.upload(c, sid, caption="", rights_status="not_a_status", rights_declared="")
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 400)
        for msg in ("Describe what the photo shows.", "Choose one of the listed options.", "Please confirm this statement"):
            self.assertIn(msg, html)
        self.assertEqual(self.upload(c, sid, taken="sometime").status_code, 400)
        self.assertEqual(self.upload(c, sid, rights_status="public_domain", taken="c. 2099").status_code, 302)
        self.assertEqual(self.db.execute("SELECT taken_precision FROM submission_photos").fetchone()[0], "approximate")

    def test_contributors_cannot_choose_editor_only_rights(self):
        c = self.client("contrib")
        sid = self.draft(c)
        self.assertEqual(self.upload(c, sid, rights_status="not_approved_public").status_code, 400)

    def test_limit_and_duplicates(self):
        c = self.client("contrib")
        sid = self.draft(c)
        self.assertEqual(self.upload(c, sid, jpeg((1, 1, 1))).status_code, 302)
        self.assertIn("already attached", self.upload(c, sid, jpeg((1, 1, 1))).get_data(as_text=True))
        self.assertEqual(self.upload(c, sid, jpeg((2, 2, 2))).status_code, 302)
        self.assertEqual(self.upload(c, sid, jpeg((3, 3, 3))).status_code, 302)
        self.assertIn("maximum number of photos", self.upload(c, sid, jpeg((4, 4, 4))).get_data(as_text=True))

    def test_unverified_accounts_cannot_upload(self):
        c = self.client("newbie")
        sid = self.draft(c)
        self.upload(c, sid)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_files").fetchone()[0], 0)

    def test_progress_protocol_returns_json(self):
        c = self.client("contrib")
        sid = self.draft(c)
        r = self.upload(c, sid, headers={"X-Upload-Progress": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["redirect"], f"/dashboard/submissions/{sid}#photos")
        r = self.upload(c, sid, b"nope", headers={"X-Upload-Progress": "1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("photo", r.get_json()["errors"])

    def test_remove_deletes_the_files(self):
        c = self.client("contrib")
        sid = self.draft(c)
        self.upload(c, sid)
        k = self.keys(sid)
        c.post(f"/dashboard/submissions/{sid}/photos/{self.photo_id(sid) or 1}/remove")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_files").fetchone()[0], 0)
        self.assertEqual(c.get(f"/media/{k['thumbnail']}").status_code, 404)
        self.assertEqual([p for p in __import__("pathlib").Path(self.media).rglob("*") if p.is_file()], [])

    def test_photos_are_frozen_once_submitted(self):
        c, sid = self.submit_with_photo()
        self.upload(c, sid, jpeg((9, 9, 9)))
        pid = self.photo_id(sid)
        c.post(f"/dashboard/submissions/{sid}/photos/{pid}/remove")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM submission_photos").fetchone()[0], 1)


class AccessControl(PhotoBase):
    def test_pending_photo_is_seen_only_by_its_contributor_and_editors(self):
        c, sid = self.submit_with_photo()
        k = self.keys(sid)
        for key in k.values():
            self.assertEqual(self.client().get(f"/media/{key}").status_code, 404)           # anonymous
            self.assertEqual(self.client("other").get(f"/media/{key}").status_code, 404)    # another contributor
            self.assertEqual(self.client("mod1").get(f"/media/{key}").status_code, 404)     # moderators: no archive access
            self.assertEqual(self.client("editor1").get(f"/media/{key}").status_code, 200)
            self.assertEqual(c.get(f"/media/{key}").status_code, 200)
        r = c.get(f"/media/{k['thumbnail']}")
        self.assertIn("no-store", r.headers["Cache-Control"])
        self.assertEqual(self.client().get("/media/" + "A" * 32).status_code, 404)          # guessed key
        self.assertEqual(self.client().get("/media/../../etc/passwd").status_code, 404)

    def test_other_users_cannot_add_to_or_remove_from_someone_elses_submission(self):
        c = self.client("contrib")
        sid = self.draft(c)
        self.upload(c, sid)
        o = self.client("other")
        self.assertEqual(self.upload(o, sid, jpeg((5, 5, 5))).status_code, 404)
        self.assertEqual(o.post(f"/dashboard/submissions/{sid}/photos/{self.photo_id(sid)}/remove").status_code, 404)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM submission_photos").fetchone()[0], 1)

    def test_contributors_cannot_decide_on_photos(self):
        c, sid = self.submit_with_photo()
        r = c.post(f"/editor/submissions/{sid}/photos/{self.photo_id(sid)}",
                   {"decision": "accept", "access": "public", "rights_status": "public_domain"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.db.execute("SELECT editor_decision FROM submission_photos").fetchone()[0], "pending")

    def test_upload_requires_csrf(self):
        c = self.client("contrib")
        sid = self.draft(c)
        r = c.post(f"/dashboard/submissions/{sid}/photos", {"photo": (io.BytesIO(jpeg()), "x.jpg")}, csrf=False)
        self.assertEqual(r.status_code, 400)


class Publication(PhotoBase):
    PUBLIC = {"decision": "accept", "access": "public", "rights_status": "copyrighted_permission_granted"}

    def test_publishing_waits_for_every_photo_decision(self):
        _, sid = self.submit_with_photo()
        ed = self.client("editor1")
        s = self.review_and(ed, sid, "approved", "published")
        self.assertEqual(s["status"], "approved")                     # blocked: photo still pending
        self.assertIsNone(s["result_entity_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities WHERE kind='person'").fetchone()[0], 0)

    def test_public_needs_rights_that_allow_it(self):
        _, sid = self.submit_with_photo()
        ed = self.client("editor1")
        self.review_and(ed, sid, decision={"decision": "accept", "access": "public", "rights_status": "rights_unknown"})
        self.assertEqual(self.db.execute("SELECT editor_decision FROM submission_photos").fetchone()[0], "pending")

    def test_approved_public_photo_appears_everywhere_but_the_original_never_does(self):     # spec scenario 10
        _, sid = self.submit_with_photo("Testperson Gallery (FICTIONAL)")
        k = self.keys(sid)
        s = self.review_and(self.client("editor1"), sid, "approved", "published", decision=self.PUBLIC)
        self.assertEqual(s["status"], "published")
        person = entities.get(self.db, s["result_entity_id"])
        item = self.db.execute("SELECT e.*, a.access_level FROM entities e JOIN archive_items a ON a.entity_id=e.id").fetchone()
        self.assertEqual((item["visibility"], item["access_level"], item["is_fictional_test"]), ("public", "public", 0))
        anon = self.client()
        page = anon.get(f"/people/{person['slug']}").get_data(as_text=True)
        self.assertIn(f"/media/{k['access_derivative']}", page)       # the profile photograph, at display size
        self.assertNotIn(k["original"], page)
        self.assertIn(f"/archive/{item['slug']}", page)
        item_page = anon.get(f"/archive/{item['slug']}").get_data(as_text=True)
        self.assertIn(f"/media/{k['access_derivative']}", item_page)
        self.assertIn(f"/people/{person['slug']}", item_page)
        self.assertNotIn(k["original"], item_page)
        self.assertIn(f"/archive/{item['slug']}", anon.get("/archive").get_data(as_text=True))
        self.assertEqual(anon.get(f"/media/{k['thumbnail']}").status_code, 200)
        self.assertEqual(anon.get(f"/media/{k['original']}").status_code, 404)                  # originals are staff-only
        self.assertEqual(self.client("contrib").get(f"/media/{k['original']}").status_code, 404)
        r = self.client("editor1").get(f"/media/{k['original']}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["Content-Disposition"].startswith("attachment"))
        self.assertIn(f"/archive/{item['slug']}", anon.get("/search?q=caption").get_data(as_text=True))
        self.assertIn(f"/archive/{item['slug']}", anon.get("/sitemap.xml").get_data(as_text=True))
        etag = anon.get(f"/media/{k['thumbnail']}").headers["ETag"]
        self.assertEqual(anon.get(f"/media/{k['thumbnail']}", headers={"If-None-Match": etag}).status_code, 304)

    def test_restricted_and_declined_photos_never_become_public(self):
        for decision in ({"decision": "accept", "access": "restricted", "rights_status": "rights_unknown"},
                         {"decision": "decline", "access": "public", "rights_status": "public_domain"}):
            with self.subTest(decision=decision["decision"]):
                _, sid = self.submit_with_photo(f"Testperson {decision['decision']} (FICTIONAL)")
                k = self.keys(sid)
                s = self.review_and(self.client("editor1"), sid, "approved", "published", decision=decision)
                self.assertEqual(s["status"], "published")
                anon = self.client()
                person = entities.get(self.db, s["result_entity_id"])
                self.assertNotIn("/media/", anon.get(f"/people/{person['slug']}").get_data(as_text=True))
                for key in k.values():
                    self.assertEqual(anon.get(f"/media/{key}").status_code, 404)
                self.assertNotIn("Test caption", anon.get("/search?q=caption").get_data(as_text=True))
                self.assertNotIn("/media/", anon.get("/archive").get_data(as_text=True))
        items = self.db.execute("SELECT e.slug FROM entities e WHERE e.kind='archive_item'").fetchall()
        self.assertEqual(len(items), 1)                             # the declined photo created no item
        self.assertEqual(self.client().get(f"/archive/{items[0]['slug']}").status_code, 404)

    def test_photo_of_a_restricted_living_person_stays_restricted(self):
        _, sid = self.submit_with_photo("Testperson Living (FICTIONAL)", living_status="living")
        k = self.keys(sid)
        s = self.review_and(self.client("editor1"), sid, "approved", "published", decision=self.PUBLIC)
        self.assertEqual(entities.get(self.db, s["result_entity_id"])["visibility"], "restricted")
        self.assertEqual(self.db.execute("SELECT visibility FROM entities WHERE kind='archive_item'").fetchone()[0], "restricted")
        self.assertEqual(self.client().get(f"/media/{k['thumbnail']}").status_code, 404)

    def test_a_correction_can_simply_add_a_photo(self):
        editor2 = make_user(self.db, "editor2", ["editor"])
        p = publish_new(self.db, self.other, editor2, "person", {"preferred_name": "Testperson Existing (FICTIONAL)"})
        c = self.client("contrib")
        r = c.post(f"/contribute/correction/{p['public_id']}",
                   {"preferred_name": "Testperson Existing (FICTIONAL)", "living_status": "unknown", "action": "draft"})
        self.assertEqual(r.status_code, 302)
        sid = self.db.execute("SELECT MAX(id) FROM submissions").fetchone()[0]
        self.assertEqual(self.upload(c, sid).status_code, 302)
        c.post(f"/dashboard/submissions/{sid}/submit")
        self.assertEqual(self.db.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0], "submitted")
        s = self.review_and(self.client("editor1"), sid, "approved", "published", decision=self.PUBLIC)
        self.assertEqual(s["status"], "published")
        self.assertIn("/media/", self.client().get(f"/people/{p['slug']}").get_data(as_text=True))
        summaries = [r[0] for r in self.db.execute("SELECT change_summary FROM revisions WHERE entity_id=?", (p["id"],))]
        self.assertIn("1 photograph added", summaries)

    def test_staff_can_later_restrict_a_photo_or_change_its_rights(self):
        _, sid = self.submit_with_photo()
        k = self.keys(sid)
        self.review_and(self.client("editor1"), sid, "approved", "published", decision=self.PUBLIC)
        item = self.db.execute("SELECT * FROM entities WHERE kind='archive_item'").fetchone()
        ed = self.client("editor1")
        anon = self.client()
        self.assertEqual(anon.get(f"/media/{k['thumbnail']}").status_code, 200)
        ed.post(f"/editor/records/{item['public_id']}/state", {"visibility": "restricted", "reason": "Rights holder asked (FICTIONAL)"})
        self.assertEqual(anon.get(f"/media/{k['thumbnail']}").status_code, 404)
        self.assertEqual(anon.get(f"/archive/{item['slug']}").status_code, 404)
        ed.post(f"/editor/records/{item['public_id']}/state", {"visibility": "public", "reason": "Resolved (FICTIONAL)"})
        self.assertEqual(anon.get(f"/media/{k['thumbnail']}").status_code, 200)
        ed.post(f"/editor/records/{item['public_id']}/rights", {"rights_status": "rights_unknown", "reason": "Claim disputed (FICTIONAL)"})
        self.assertEqual(anon.get(f"/media/{k['thumbnail']}").status_code, 404)
        self.assertEqual(entities.get(self.db, item["id"])["visibility"], "restricted")
        # cannot make it public again while its rights forbid that
        ed.post(f"/editor/records/{item['public_id']}/state", {"visibility": "public", "reason": "try (FICTIONAL)"})
        self.assertEqual(entities.get(self.db, item["id"])["visibility"], "restricted")
        actions = [r[0] for r in self.db.execute("SELECT action FROM audit_logs")]
        for a in ("photo.uploaded", "photo.decided", "archive_item.published", "archive_item.rights_changed"):
            self.assertIn(a, actions)

    def test_editors_cannot_decide_on_their_own_photos(self):
        ed = self.client("editor1")
        sid = self.draft(ed)
        self.upload(ed, sid)
        ed.post(f"/dashboard/submissions/{sid}/submit")
        editor2 = make_user(self.db, "editor2", ["editor"])  # noqa: F841 — exists so the queue is realistic
        ed.post(f"/editor/submissions/{sid}/photos/{self.photo_id(sid)}", self.PUBLIC)
        self.assertEqual(self.db.execute("SELECT editor_decision FROM submission_photos").fetchone()[0], "pending")


if __name__ == "__main__":
    unittest.main()
