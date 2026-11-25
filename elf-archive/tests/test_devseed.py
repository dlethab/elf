"""The development seed: everything it adds is flagged fictional, living people stay private,
and every public section has something to show. Runs twice safely."""
import unittest

from elf_archive import create_app
from elf_archive.devseed import seed
from tests.helpers import make_db
from tests.test_http import Client


class DevSeed(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.msg = seed(self.db)
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test"})

    def test_all_records_are_fictional_and_labelled(self):
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities WHERE is_fictional_test=0").fetchone()[0], 0)
        for table, col in (("people", "preferred_name"), ("places", "primary_name"), ("organizations", "name"),
                           ("oral_histories", "title"), ("forum_topics", "title")):
            for (v,) in self.db.execute(f"SELECT {col} FROM {table}"):
                self.assertIn("FICTIONAL", v, table)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM places WHERE latitude IS NOT NULL").fetchone()[0], 0)

    def test_living_person_and_their_links_stay_private(self):
        self.assertEqual(self.db.execute("SELECT e.visibility FROM entities e JOIN people p ON p.entity_id=e.id "
                                         "WHERE p.living_status='living'").fetchone()[0], "restricted")

    def test_sections_have_content(self):
        c = Client(self.app)
        for path, text in (("/organizations", "Test Front (FICTIONAL)"), ("/oral-histories", "Test interview about Testville"),
                           ("/community/c/hometowns", "memories of Testville"), ("/people", "Testperson Alpha")):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(text, r.get_data(as_text=True), path)
        oh = self.db.execute("SELECT slug FROM entities WHERE kind='oral_history'").fetchone()[0]
        html = c.get(f"/oral-histories/{oh}").get_data(as_text=True)
        self.assertIn("FICTIONAL test transcript", html)                      # consent to publish the transcript is on record
        self.assertIn("The recording is not available to the public.", html)

    def test_running_again_adds_nothing(self):
        n = self.db.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        self.assertIn("already present", seed(self.db))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM entities").fetchone()[0], n)


if __name__ == "__main__":
    unittest.main()
