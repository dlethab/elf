"""Public data export: only public records and fields; confidential data never appears.
All data is synthetic and labelled fictional."""
import csv
import io
import json
import unittest
import zipfile

from elf_archive.services import export
from tests.helpers import make_db, make_user, publish, publish_new, submit_new
from tests.test_http import Base as HttpBase

SECRET = "CONFIDENTIAL-MARKER-7f3a"           # planted in every confidential field; must never be exported


class Build(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.contrib = make_user(self.db, "contrib")
        self.editor = make_user(self.db, "editor1", ["editor"])
        pub = lambda kind, raw: publish_new(self.db, self.contrib, self.editor, kind, raw)  # noqa: E731
        self.place = pub("place", {"primary_name": "Testville (FICTIONAL)"})
        self.org = pub("organization", {"name": "Test Front (FICTIONAL)"})
        self.dead = pub("person", {"preferred_name": "Testperson Past (FICTIONAL)", "living_status": "deceased",
                                   "birth": "c. 2099", "birth_place": self.place["public_id"]})
        self.living = pub("person", {"preferred_name": "Testperson Living (FICTIONAL)", "living_status": "living"})
        publish(self.db, self.editor, submit_new(self.db, self.contrib, "affiliation",
                                                 {"person": self.dead["public_id"], "organization": self.org["public_id"], "role": "Member (FICTIONAL)"}))
        # a living person's link cannot be proposed through the workflow (they are not public); insert one directly
        self.db.execute("INSERT INTO affiliations(person_id, organization_id, role, publication_status, visibility) "
                        "VALUES (?,?,?,'published','restricted')", (self.living["id"], self.org["id"], "Member (FICTIONAL)"))
        self.db.execute("UPDATE people SET research_notes=?", (SECRET,))
        self.db.execute("UPDATE affiliations SET editor_notes=?", (SECRET,))
        self.db.execute("UPDATE citations SET editor_note=?", (SECRET,))

    def data(self, **kw):
        return export.build(self.db, "http://archive.test", include_fictional=True, **kw)

    def test_every_column_is_classified(self):
        for _kind, (table, cols) in export.RECORD_COLUMNS.items():
            actual = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            classified = set(cols) | set(export.NOT_EXPORTED[table])
            self.assertEqual(actual, classified, f"{table}: classify new columns in services/export.py")
            self.assertFalse(set(cols) & set(export.NOT_EXPORTED[table]), table)

    def test_only_public_records_and_links(self):
        t = self.data()["tables"]
        names = [p["preferred_name"] for p in t["people"]]
        self.assertIn("Testperson Past (FICTIONAL)", names)
        self.assertNotIn("Testperson Living (FICTIONAL)", names)           # living people are restricted without consent
        self.assertEqual([a["person_id"] for a in t["affiliations"]], [self.dead["public_id"]])
        past = next(p for p in t["people"] if p["public_id"] == self.dead["public_id"])
        self.assertEqual(past["birth_place_id"], self.place["public_id"])  # references use permanent public ids
        self.assertEqual(past["birth_precision"], "approximate")                 # uncertainty is kept, not rounded to a date
        self.assertTrue(past["url"].startswith("http://archive.test/people/"))

    def test_confidential_fields_never_appear(self):
        blob, _ = export.export_zip(self.db, self.editor.id, include_fictional=True)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                text = z.read(name).decode("utf-8-sig")
                self.assertNotIn(SECRET, text, name)
                self.assertNotIn("example.test", text, name)              # no account email addresses
                self.assertNotIn("password", text, name)

    def test_zip_has_json_and_csv_and_is_audited(self):
        blob, manifest = export.export_zip(self.db, self.editor.id, include_fictional=True)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            self.assertIn("manifest.json", z.namelist())
            tables = json.loads(z.read("archive.json"))
            rows = list(csv.DictReader(io.StringIO(z.read("csv/people.csv").decode("utf-8-sig"))))
        self.assertEqual(len(rows), len(tables["people"]))
        self.assertEqual(manifest["counts"]["people"], len(tables["people"]))
        a = self.db.execute("SELECT actor_id, detail_json FROM audit_logs WHERE action='export.public'").fetchone()
        self.assertEqual(a["actor_id"], self.editor.id)
        self.assertIn('"people"', a["detail_json"])

    def test_fictional_records_are_excluded_by_default(self):
        self.db.execute("UPDATE entities SET is_fictional_test=1 WHERE id=?", (self.dead["id"],))
        self.assertNotIn(self.dead["public_id"], [p["public_id"] for p in export.build(self.db)["tables"]["people"]])
        self.assertEqual(export.build(self.db)["tables"]["affiliations"], [])  # a link to an excluded record goes too

    def test_link_with_non_public_optional_end_keeps_the_link(self):
        hidden = self.db.execute("INSERT INTO entities(kind, public_id, slug) VALUES ('place','EXP-PL-1','hidden-fictional')").lastrowid
        self.db.execute("INSERT INTO places(entity_id, primary_name) VALUES (?,?)", (hidden, "Hidden place (FICTIONAL)"))   # private by default
        self.db.execute("UPDATE affiliations SET place_id=? WHERE person_id=?", (hidden, self.dead["id"]))
        affs = self.data()["tables"]["affiliations"]
        self.assertEqual(len(affs), 1)
        self.assertIsNone(affs[0]["place_id"])

    def oral_history(self, transcript="Transcript text (FICTIONAL)"):
        cur = self.db.execute("INSERT INTO entities(kind, public_id, slug, publication_status, visibility) "
                              "VALUES ('oral_history','EXP-OH-1','test-oh-fictional','published','public')")
        self.db.execute("INSERT INTO oral_histories(entity_id, title, interview_code, transcript_text, transcript_kind, redaction_notes) "
                        "VALUES (?,?,?,?,?,?)", (cur.lastrowid, "Test interview (FICTIONAL)", SECRET, transcript, "verbatim", SECRET))
        return cur.lastrowid

    def consent(self, oh, t):
        self.db.execute("INSERT INTO consent_records(oral_history_id, consent_type, granted) VALUES (?,?,1)", (oh, t))

    def test_transcripts_follow_consent_and_embargo(self):
        oh = self.oral_history()
        get = lambda: self.data()["tables"]["oral_histories"][0]  # noqa: E731
        self.assertIsNone(get()["transcript_text"])                         # no consent to publish it
        self.consent(oh, "publish_transcript")
        self.assertEqual(get()["transcript_text"], "Transcript text (FICTIONAL)")
        self.db.execute("UPDATE oral_histories SET embargo_until='2999-01-01' WHERE entity_id=?", (oh,))
        self.assertIsNone(get()["transcript_text"])
        self.assertNotIn("interview_code", get())


class AdminDownload(HttpBase):
    def test_admin_can_download_others_cannot(self):
        self.assertEqual(self.client("editor1").get("/admin/export").status_code, 403)
        self.assertEqual(self.client("contrib").post("/admin/export").status_code, 403)
        a = self.client("admin1")
        self.assertEqual(a.get("/admin/export").status_code, 200)
        r = a.post("/admin/export", {"include_fictional": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/zip")
        self.assertIn("attachment;", r.headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(r.data)) as z:
            places = json.loads(z.read("archive.json"))["places"]
        self.assertIn("Testville (FICTIONAL)", [p["primary_name"] for p in places])

    def test_overview_shows_operational_counts(self):
        html = self.client("admin1").get("/admin").get_data(as_text=True)
        for label in ("Open forum reports", "Archive items with unknown rights", "Staff accounts without two-step sign-in",
                      "No backup has been recorded"):
            self.assertIn(label, html)


if __name__ == "__main__":
    unittest.main()
