"""Documents, recordings, oral histories with per-use consent, researcher access, and collections.
Files are synthetic byte strings or generated images; every record is labelled fictional."""
import io
import shutil
import tempfile
import unittest

from elf_archive import create_app
from elf_archive.services import entities
from tests.helpers import make_db, make_user
from tests.test_http import Client
from tests.test_photos import jpeg

FAKE_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 4000
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="elf-media-test-")
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test", "MEDIA_ROOT": self.media})
        self.contrib = make_user(self.db, "contrib")
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.researcher = make_user(self.db, "res1", ["researcher"])
        make_user(self.db, "other")

    def tearDown(self):
        shutil.rmtree(self.media, ignore_errors=True)

    def client(self, username=None):
        c = Client(self.app)
        if username:
            c.login(username)
        return c

    def last_sid(self):
        return self.db.execute("SELECT MAX(id) FROM submissions").fetchone()[0]

    def upload(self, c, sid, data, name, **meta):
        form = {"caption": "Test file (FICTIONAL)", "rights_status": "copyrighted_permission_granted", "rights_declared": "1", **meta}
        form["photo"] = (io.BytesIO(data), name)
        return c.post(f"/dashboard/submissions/{sid}/photos", form)

    def publish(self, sid, decision=None, consent=False):
        ed = self.client("editor1")
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        for (pid,) in self.db.execute("SELECT id FROM submission_photos WHERE submission_id=?", (sid,)).fetchall():
            ed.post(f"/editor/submissions/{sid}/photos/{pid}", decision or {"decision": "accept", "access": "public",
                                                                              "rights_status": "copyrighted_permission_granted"})
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "approved", "message": "ok"})
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "published", **({"consent_confirmed": "1"} if consent else {})})
        return self.db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()


class DocumentsAndRecordings(Base):
    def draft_person(self, c, name):
        c.post("/contribute/person", {"preferred_name": name, "living_status": "unknown", "action": "draft"})
        return self.last_sid()

    def test_pdf_document_is_offered_as_a_download(self):
        c = self.client("contrib")
        sid = self.draft_person(c, "Testperson Papers (FICTIONAL)")
        self.assertEqual(self.upload(c, sid, PDF, "letter.pdf", item_type="letter").status_code, 302)
        c.post(f"/dashboard/submissions/{sid}/submit")
        self.publish(sid)
        item = self.db.execute("SELECT e.slug, a.media_kind, a.item_type FROM entities e JOIN archive_items a ON a.entity_id=e.id").fetchone()
        self.assertEqual((item["media_kind"], item["item_type"]), ("document", "letter"))
        html = self.client().get(f"/archive/{item['slug']}").get_data(as_text=True)
        self.assertIn("Download the document (PDF", html)
        key = self.db.execute("SELECT storage_key FROM media_files WHERE file_role='original'").fetchone()[0]
        r = self.client().get(f"/media/{key}")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["Content-Disposition"].startswith("attachment"))   # never rendered inline
        self.assertEqual(r.data, PDF)

    def test_pdf_with_active_content_is_refused(self):
        c = self.client("contrib")
        sid = self.draft_person(c, "Testperson Script (FICTIONAL)")
        r = self.upload(c, sid, b"%PDF-1.4\n<< /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>\n%%EOF", "x.pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("active content", r.get_data(as_text=True))

    def test_audio_plays_with_range_requests(self):
        c = self.client("contrib")
        sid = self.draft_person(c, "Testperson Voice (FICTIONAL)")
        self.assertEqual(self.upload(c, sid, FAKE_MP3, "song.mp3", transcript="[00:01] Test words (FICTIONAL)").status_code, 302)
        p = self.db.execute("SELECT media_kind, item_type FROM submission_photos").fetchone()
        self.assertEqual((p["media_kind"], p["item_type"]), ("audio", "audio_recording"))
        c.post(f"/dashboard/submissions/{sid}/submit")
        self.publish(sid)
        slug = self.db.execute("SELECT slug FROM entities WHERE kind='archive_item'").fetchone()[0]
        html = self.client().get(f"/archive/{slug}").get_data(as_text=True)
        self.assertIn("<audio", html)
        self.assertIn("Test words (FICTIONAL)", html)
        self.assertIn("not been checked against the recording", html)
        key = self.db.execute("SELECT storage_key FROM media_files WHERE file_role='original'").fetchone()[0]
        r = self.client().get(f"/media/{key}", headers={"Range": "bytes=0-99"})
        self.assertEqual((r.status_code, len(r.data)), (206, 100))

    def test_unsupported_files_are_refused(self):
        c = self.client("contrib")
        sid = self.draft_person(c, "Testperson Gif (FICTIONAL)")
        gif = io.BytesIO()
        __import__("PIL.Image", fromlist=["Image"]).new("RGB", (5, 5)).save(gif, "GIF")
        for data, name in ((gif.getvalue(), "x.gif"), (b"MZ\x90\x00", "x.exe"), (b"PK\x03\x04zip", "x.mp3")):
            r = self.upload(c, sid, data, name)
            self.assertEqual(r.status_code, 400, name)
            self.assertIn("This file type is not accepted", r.get_data(as_text=True))


class OralHistories(Base):
    def submit(self, granted, title="Test Interview (FICTIONAL)", recording=True, **extra):
        c = self.client("contrib")
        form = {"title": title, "interviewee_text": "Test Speaker (FICTIONAL)", "interviewer_text": "Test Interviewer (FICTIONAL)",
                "recorded": "2099", "language": "Tigrinya", "summary": "A fictional interview used only for testing.",
                "transcript_text": "[00:05] Testimony words alphaword (FICTIONAL)\n[1:02:03] Later words (FICTIONAL)",
                "transcript_kind": "verbatim", "translation_text": "Translated words (FICTIONAL)", "translation_kind": "machine_draft",
                "consent_note": "Signed form (FICTIONAL)", "consent_declared": "1", "action": "draft", **extra}
        form.update({f"consent_{t}": "1" for t in granted})
        r = c.post("/contribute/oral_history", form)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:400])
        sid = self.last_sid()
        if recording:
            self.assertEqual(self.upload(c, sid, FAKE_MP3, "interview.mp3", caption="Interview recording (FICTIONAL)").status_code, 302)
        c.post(f"/dashboard/submissions/{sid}/submit")
        return sid

    def oh(self):
        return self.db.execute("SELECT e.*, o.media_item_id FROM entities e JOIN oral_histories o ON o.entity_id=e.id ORDER BY e.id DESC").fetchone()

    def rec_key(self):
        return self.db.execute("SELECT storage_key FROM media_files WHERE file_role='original' ORDER BY id DESC").fetchone()[0]

    def test_consent_must_be_declared(self):
        r = self.client("contrib").post("/contribute/oral_history", {"title": "Test (FICTIONAL)", "action": "draft"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Please confirm how consent was obtained", r.get_data(as_text=True))

    def test_without_editor_confirmation_nothing_is_public(self):
        sid = self.submit(["record", "store", "publish_recording", "publish_transcript"])
        self.publish(sid, consent=False)
        oh = self.oh()
        self.assertEqual(oh["visibility"], "restricted")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM consent_records").fetchone()[0], 0)
        anon = self.client()
        self.assertEqual(anon.get(f"/oral-histories/{oh['slug']}").status_code, 404)
        self.assertEqual(anon.get(f"/media/{self.rec_key()}").status_code, 404)
        self.assertNotIn('class="result"', anon.get("/search?q=alphaword").get_data(as_text=True))

    def test_each_use_follows_its_own_consent(self):
        sid = self.submit(["record", "store", "publish_transcript"])       # transcript yes, recording no
        self.publish(sid, consent=True)
        oh = self.oh()
        anon = self.client()
        html = anon.get(f"/oral-histories/{oh['slug']}").get_data(as_text=True)
        self.assertIn("Testimony words alphaword (FICTIONAL)", html)
        self.assertIn('data-seek="5"', html)
        self.assertIn('data-seek="3723"', html)                               # [1:02:03]
        self.assertIn("The recording is not available to the public.", html)
        self.assertNotIn("Translated words", html)                            # no translation consent
        self.assertEqual(anon.get(f"/media/{self.rec_key()}").status_code, 404)
        self.assertIn(f"/oral-histories/{oh['slug']}", anon.get("/search?q=alphaword").get_data(as_text=True))
        self.assertIn(f"/oral-histories/{oh['slug']}", anon.get("/oral-histories").get_data(as_text=True))
        ed = self.client("editor1")
        # granting recording consent (with evidence) makes the recording playable, but not downloadable
        ed.post(f"/editor/records/{oh['public_id']}/consent/publish_recording", {"granted": "1"})
        self.assertEqual(anon.get(f"/media/{self.rec_key()}").status_code, 404)        # evidence is required
        ed.post(f"/editor/records/{oh['public_id']}/consent/publish_recording", {"granted": "1", "evidence_note": "Form (FICTIONAL)"})
        html = anon.get(f"/oral-histories/{oh['slug']}").get_data(as_text=True)
        self.assertIn("<audio", html)
        self.assertIn("has not agreed to downloads", html)
        self.assertEqual(anon.get(f"/media/{self.rec_key()}").status_code, 200)
        ed.post(f"/editor/records/{oh['public_id']}/consent/publish_translation", {"granted": "1", "evidence_note": "Form (FICTIONAL)"})
        html = anon.get(f"/oral-histories/{oh['slug']}").get_data(as_text=True)
        self.assertIn("Translated words (FICTIONAL)", html)
        self.assertIn("Automatic translation: draft, not checked", html)
        # an embargo hides recording and transcript
        ed.post(f"/editor/records/{oh['public_id']}/oral-controls", {"embargo_until": "2999-01-01", "reason": "Requested (FICTIONAL)"})
        self.assertEqual(anon.get(f"/oral-histories/{oh['slug']}").status_code, 404)
        self.assertEqual(anon.get(f"/media/{self.rec_key()}").status_code, 404)
        self.assertNotIn('class="result"', anon.get("/search?q=alphaword").get_data(as_text=True))
        ed.post(f"/editor/records/{oh['public_id']}/oral-controls", {"embargo_until": "", "reason": "Lifted (FICTIONAL)"})
        # withdrawing all publication consent makes it non-public again, with history kept
        for t in ("publish_recording", "publish_transcript"):
            ed.post(f"/editor/records/{oh['public_id']}/consent/{t}", {"granted": "0", "evidence_note": "Withdrawn by letter (FICTIONAL)"})
        self.assertEqual(anon.get(f"/oral-histories/{oh['slug']}").status_code, 404)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM consent_records WHERE revoked_at IS NOT NULL").fetchone()[0], 4)
        self.assertEqual(self.client("contrib").post(f"/editor/records/{oh['public_id']}/consent/allow_download",
                                                     {"granted": "1", "evidence_note": "x"}).status_code, 403)

    def test_researchers_see_restricted_interviews_only_with_research_consent(self):
        sid = self.submit(["record", "store", "research_access"])
        self.publish(sid, consent=True)
        oh = self.oh()
        self.assertEqual(oh["visibility"], "restricted")
        url = f"/oral-histories/{oh['slug']}"
        self.assertEqual(self.client().get(url).status_code, 404)
        self.assertEqual(self.client("other").get(url).status_code, 404)
        res = self.client("res1")
        r = res.get(url)
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("research access", html)
        self.assertIn("alphaword", html)
        self.assertEqual(res.get(f"/media/{self.rec_key()}").status_code, 200)
        self.assertGreaterEqual(self.db.execute("SELECT COUNT(*) FROM audit_logs WHERE action='restricted.viewed'").fetchone()[0], 2)
        self.assertEqual(res.get("/editor").status_code, 403)                  # researchers are not editors
        sid2 = self.submit(["record", "store"], title="Test Private Interview (FICTIONAL)")
        self.publish(sid2, consent=True)
        self.assertEqual(res.get(f"/oral-histories/{self.oh()['slug']}").status_code, 404)

    def test_interview_request(self):
        r = self.client().post("/oral-histories/request", {"email": "someone@example.test", "interviewee": "Test Elder (FICTIONAL)",
                                                           "message": "My grandmother would like to record her memories (FICTIONAL)."})
        self.assertEqual(r.status_code, 302)
        m = self.db.execute("SELECT * FROM contact_messages").fetchone()
        self.assertEqual(m["related_public_id"], "interview-request")
        self.assertIn("Test Elder (FICTIONAL)", m["message"])


class Collections(Base):
    def test_public_collection_shows_only_public_items(self):
        c = self.client("contrib")
        c.post("/contribute/person", {"preferred_name": "Testperson Album (FICTIONAL)", "living_status": "unknown", "action": "draft"})
        sid = self.last_sid()
        self.upload(c, sid, jpeg((1, 2, 3)), "a.jpg", caption="Public photo (FICTIONAL)")
        self.upload(c, sid, jpeg((4, 5, 6)), "b.jpg", caption="Restricted photo (FICTIONAL)")
        c.post(f"/dashboard/submissions/{sid}/submit")
        ed = self.client("editor1")
        ed.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"})
        p1, p2 = [r[0] for r in self.db.execute("SELECT id FROM submission_photos ORDER BY id")]
        ed.post(f"/editor/submissions/{sid}/photos/{p1}", {"decision": "accept", "access": "public", "rights_status": "public_domain"})
        ed.post(f"/editor/submissions/{sid}/photos/{p2}", {"decision": "accept", "access": "restricted", "rights_status": "rights_unknown"})
        for to in ("approved", "published"):
            ed.post(f"/editor/submissions/{sid}/transition", {"to": to, "message": "ok"})
        self.assertEqual(self.client("contrib").post("/editor/collections", {"title": "x"}).status_code, 403)
        r = ed.post("/editor/collections", {"title": "Test Album (FICTIONAL)", "description": "Fictional test collection.",
                                            "visibility": "public", "is_featured": "1"})
        cpid = r.headers["Location"].rsplit("/", 1)[1]
        for (pid,) in self.db.execute("SELECT public_id FROM entities WHERE kind='archive_item' ORDER BY id").fetchall():
            ed.post(f"/editor/records/{cpid}/collection/items", {"op": "add", "item": pid})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM collection_items").fetchone()[0], 2)
        slug = entities.get_by_public_id(self.db, cpid)["slug"]
        anon = self.client()
        html = anon.get(f"/collections/{slug}").get_data(as_text=True)
        self.assertIn("Public photo (FICTIONAL)", html)
        self.assertNotIn("Restricted photo", html)
        self.assertIn("Test Album (FICTIONAL)", anon.get("/").get_data(as_text=True))       # featured on the home page
        self.assertIn("1 item", anon.get("/collections").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
