"""The sample archive (flask sample-db): built in its own database, entirely fictional, with every kind of record
and every step of the workflow represented, and never written into the real archive."""
import os
import shutil
import sqlite3
import tempfile
import unittest

from elf_archive import sampledata


class SampleArchive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="elf-sample-test-")
        cls.path = os.path.join(cls.tmp, "sample.db")
        cls.password, cls.report = sampledata.build(cls.path, os.path.join(cls.tmp, "media"), os.path.join(cls.tmp, "real.db"))
        cls.db = sqlite3.connect(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def q(self, sql):
        return self.db.execute(sql).fetchall()

    def test_refuses_the_real_database(self):
        real = os.path.join(self.tmp, "archive.db")
        with self.assertRaises(RuntimeError):
            sampledata.build(real, os.path.join(self.tmp, "m2"), real)

    def test_every_kind_of_record_exists_and_everything_is_fictional(self):
        kinds = dict(self.q("SELECT kind, COUNT(*) FROM entities GROUP BY kind"))
        for k in ("place", "event", "person", "family", "organization", "source", "archive_item", "oral_history", "collection"):
            self.assertGreater(kinds.get(k, 0), 0, k)
        self.assertEqual(self.q("SELECT COUNT(*) FROM entities WHERE is_fictional_test=0")[0][0], 0)
        self.assertEqual(self.q("SELECT COUNT(*) FROM events WHERE CAST(substr(date_start,1,4) AS INTEGER) < 2040")[0][0], 0)
        names = [r[0] for r in self.q("SELECT name FROM entity_names WHERE name_type='preferred'")]
        self.assertTrue(all("FICTIONAL" in n for n in names), [n for n in names if "FICTIONAL" not in n][:5])

    def test_workflow_states_and_community_are_represented(self):
        states = {r[0] for r in self.q("SELECT status FROM submissions")}
        self.assertTrue({"draft", "submitted", "under_review", "needs_revision", "published"} <= states, states)
        self.assertGreater(self.q("SELECT COUNT(*) FROM archive_items WHERE access_level='public'")[0][0], 5)
        self.assertGreater(self.q("SELECT COUNT(*) FROM media_files WHERE file_role='thumbnail'")[0][0], 5)
        self.assertEqual(self.q("SELECT COUNT(*) FROM explorations WHERE is_published=1")[0][0], 2)
        self.assertGreater(self.q("SELECT COUNT(*) FROM forum_posts")[0][0], 4)
        self.assertEqual(self.q("SELECT COUNT(*) FROM reports")[0][0], 1)
        self.assertEqual(self.q("SELECT COUNT(*) FROM contact_messages")[0][0], 1)

    def test_evidence_and_uncertainty_are_varied(self):
        self.assertEqual({r[0] for r in self.q("SELECT DISTINCT coord_precision FROM places WHERE coord_precision IS NOT NULL")},
                         {"exact", "approximate", "region_centroid"})
        self.assertGreater(self.q("SELECT COUNT(*) FROM places WHERE latitude IS NULL")[0][0], 0)
        precisions = {r[0] for r in self.q("SELECT DISTINCT date_precision FROM events")}
        self.assertTrue({"exact", "month", "year", "range", "approximate", "decade", "unknown"} <= precisions, precisions)
        self.assertEqual(self.q("SELECT SUM(concerns_date), SUM(concerns_location) FROM conflicting_accounts")[0], (1, 1))
        self.assertEqual(self.q("SELECT COUNT(*) FROM entities WHERE kind='person' AND visibility<>'public'")[0][0], 1)  # the living person

    def test_every_staff_record_page_opens(self):
        """Regression: the staff page of an archive item or a collection failed (no record form to cite fields of)."""
        from elf_archive import create_app
        from elf_archive.db import connect
        from elf_archive.services import accounts
        app = create_app({"DATABASE_PATH": self.path, "MEDIA_ROOT": os.path.join(self.tmp, "media"), "ENV": "testing", "AUTO_MIGRATE": False})
        conn = connect(self.path)
        uid = conn.execute("SELECT id FROM users WHERE username='sample_editor'").fetchone()[0]
        raw = accounts.create_session(conn, uid, "127.0.0.1", "test", 3600)
        conn.commit()
        conn.close()
        c = app.test_client()
        with c.session_transaction() as s:
            s["sid"] = raw
        for kind, pid in self.q("SELECT kind, public_id FROM entities WHERE merged_into IS NULL AND deleted_at IS NULL ORDER BY kind, id"):
            self.assertEqual(c.get(f"/editor/records/{pid}").status_code, 200, (kind, pid))


if __name__ == "__main__":
    unittest.main()
