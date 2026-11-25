"""Records and curation: organizations and affiliations, family memberships, event participation,
reference fields, merging duplicates (spec scenario 11), direct edits, citations, differing
accounts, link management, CSV import and batch review. All data is synthetic and labelled fictional."""
import io
import json
import unittest

from elf_archive import create_app
from elf_archive.services import entities, families, merging, records
from tests.helpers import make_db, make_user, publish, publish_new, submit_new
from tests.test_http import Client


class Base(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test"})
        self.contrib = make_user(self.db, "contrib")
        self.rep = make_user(self.db, "rep")
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.editor2 = make_user(self.db, "editor2", ["editor"])
        self.place = publish_new(self.db, self.contrib, self.editor, "place", {"primary_name": "Testville (FICTIONAL)"})

    def client(self, username=None):
        c = Client(self.app)
        if username:
            c.login(username)
        return c

    def person(self, name, **kw):
        return publish_new(self.db, self.contrib, self.editor, "person", {"preferred_name": name, **kw},
                           consent=False)

    def link(self, kind, raw, by=None, auth=None):
        sid = submit_new(self.db, by or self.contrib, kind, raw, **({"auth": auth} if auth else {}))
        return publish(self.db, self.editor, sid)

    def page(self, url, c=None):
        r = (c or self.client()).get(url)
        return r.status_code, r.get_data(as_text=True)


class OrganizationsAndLinks(Base):
    def test_organization_affiliation_appears_on_both_pages_and_in_search(self):
        org = publish_new(self.db, self.contrib, self.editor, "organization",
                          {"name": "Test Movement (FICTIONAL)", "aliases": "TM-F", "active": "2098 to 2099"})
        p = self.person("Testperson Member (FICTIONAL)")
        self.link("affiliation", {"person": p["public_id"], "organization": f"Test Movement (FICTIONAL) [{org['public_id']}]",
                                  "role": "Test role (FICTIONAL)", "period": "c. 2099", "sources": "Test Register (FICTIONAL) | p. 4"})
        _, html = self.page(f"/people/{p['slug']}")
        self.assertIn(f"/organizations/{org['slug']}", html)
        self.assertIn("Test role (FICTIONAL)", html)
        self.assertIn("c. 2099", html)
        self.assertIn("Test Register (FICTIONAL)", html)                 # the source is cited for the affiliation claim
        self.assertIn("affiliation", html)
        _, html = self.page(f"/organizations/{org['slug']}")
        self.assertIn(f"/people/{p['slug']}", html)
        self.assertIn("2098–2099", html)
        _, html = self.page("/search?q=tm-f")
        self.assertIn(f"/organizations/{org['slug']}", html)
        self.assertEqual(self.page("/organizations")[0], 200)

    def test_affiliation_of_a_living_person_is_not_public(self):
        org = publish_new(self.db, self.contrib, self.editor, "organization", {"name": "Test Org Two (FICTIONAL)"})
        p = publish_new(self.db, self.contrib, self.editor, "person",
                        {"preferred_name": "Testperson Alive (FICTIONAL)", "living_status": "living"}, consent=True)
        self.link("affiliation", {"person": p["public_id"], "organization": org["public_id"]})
        self.assertEqual(self.db.execute("SELECT visibility FROM affiliations").fetchone()[0], "restricted")
        # neither the member list nor the PUBLIC change history may name the person
        self.assertNotIn("Testperson Alive", self.page(f"/organizations/{org['slug']}")[1])

    def test_participation_needs_exactly_one_participant_and_shows_organizations(self):
        org = publish_new(self.db, self.contrib, self.editor, "organization", {"name": "Test Org Three (FICTIONAL)"})
        ev = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Test Gathering (FICTIONAL)"})
        p = self.person("Testperson Both (FICTIONAL)")
        _, errors = records.validate(self.db, "participation", {"event": ev["public_id"]})
        self.assertIn("person", errors)
        _, errors = records.validate(self.db, "participation", {"event": ev["public_id"], "person": p["public_id"],
                                                                "organization": org["public_id"]})
        self.assertIn("person", errors)
        self.link("participation", {"event": ev["public_id"], "organization": org["public_id"], "role": "Organiser (FICTIONAL)"})
        html = self.page(f"/events/{ev['slug']}")[1]
        self.assertIn(f"/organizations/{org['slug']}", html)
        self.assertIn("Organiser (FICTIONAL)", html)
        _, errors = records.validate(self.db, "participation", {"event": ev["public_id"], "organization": org["public_id"]})
        self.assertIn("organization", errors)                            # already recorded

    def test_family_members_are_proposed_only_by_representatives_of_that_family(self):
        fam = publish_new(self.db, self.contrib, self.editor, "family", {"display_name": "Testfamily One (FICTIONAL)"})
        other = publish_new(self.db, self.contrib, self.editor, "family", {"display_name": "Testfamily Two (FICTIONAL)"})
        p = self.person("Testperson Kin (FICTIONAL)")
        c = self.client("rep")
        self.assertEqual(c.get("/contribute/membership").status_code, 403)       # no grant yet
        families.grant(self.db, self.editor.id, "rep", fam["id"])
        self.assertEqual(c.get(f"/contribute/membership?family={fam['public_id']}").status_code, 200)
        r = c.post("/contribute/membership", {"family": other["public_id"], "person": p["public_id"], "action": "submit"})
        self.assertEqual(r.status_code, 400)                                        # not their family
        self.assertIn("not authorised", r.get_data(as_text=True))
        r = c.post("/contribute/membership", {"family": fam["public_id"], "person": p["public_id"], "role_note": "Test (FICTIONAL)",
                                              "action": "submit"})
        self.assertEqual(r.status_code, 302)
        sid = self.db.execute("SELECT MAX(id) FROM submissions").fetchone()[0]
        s = self.db.execute("SELECT * FROM submissions WHERE id=?", (sid,)).fetchone()
        self.assertEqual((s["status"], s["family_scope_id"]), ("submitted", fam["id"]))
        self.assertEqual(c.post(f"/editor/submissions/{sid}/transition", {"to": "under_review"}).status_code, 403)
        publish(self.db, self.editor, sid)
        self.assertIn(f"/people/{p['slug']}", self.page(f"/families/{fam['slug']}")[1])


class References(Base):
    def test_reference_fields_accept_labels_ids_and_unique_names_only(self):
        p = self.person("Testperson Unique (FICTIONAL)")
        self.person("Testperson Twin (FICTIONAL)")
        self.person("Testperson Twin (FICTIONAL)")
        living = publish_new(self.db, self.contrib, self.editor, "person",
                             {"preferred_name": "Testperson Hidden (FICTIONAL)", "living_status": "living"})
        ok = lambda v: records.parse_ref(self.db, v, "person")  # noqa: E731
        self.assertEqual(ok(f"Anything at all [{p['public_id']}]")[0], p["public_id"])
        self.assertEqual(ok(p["public_id"])[0], p["public_id"])
        self.assertEqual(ok("testperson unique (fictional)")[0], p["public_id"])
        self.assertIn("More than one", ok("Testperson Twin (FICTIONAL)")[1])
        self.assertEqual(ok(living["public_id"])[1], "That record was not found.")      # never confirms private records
        self.assertEqual(ok("Testperson Hidden (FICTIONAL)")[1], "That record was not found.")
        self.assertEqual(ok(self.place["public_id"])[1], "That record was not found.")  # wrong kind

    def test_lookup_returns_public_records_only(self):
        self.person("Testperson Lookup (FICTIONAL)")
        publish_new(self.db, self.contrib, self.editor, "person",
                    {"preferred_name": "Testperson Lookalive (FICTIONAL)", "living_status": "living"})
        data = self.client().get("/lookup/person?q=testperson look").get_json()
        labels = [d["label"] for d in data]
        self.assertEqual(len(labels), 1)
        self.assertTrue(labels[0].startswith("Testperson Lookup (FICTIONAL) ["))
        self.assertEqual(self.client().get("/lookup/user?q=a").status_code, 404)

    def test_form_prefill_from_the_address(self):
        p = self.person("Testperson Prefill (FICTIONAL)")
        html = self.client("contrib").get(f"/contribute/affiliation?person={p['public_id']}").get_data(as_text=True)
        self.assertIn(f'value="Testperson Prefill (FICTIONAL) [{p["public_id"]}]"', html)


class Merging(Base):
    """Spec scenario 11: an editor merges duplicate records without losing relationships or citations."""

    def setUp(self):
        super().setUp()
        self.keep = self.person("Testperson Kept (FICTIONAL)", sources="Test Book A (FICTIONAL) | p. 1")
        self.dup = self.person("Testperson Kept (FICTIONAL)", aliases="T. Kept-F", birth="c. 2099",
                               birth_place=self.place["public_id"], sources="Test Book B (FICTIONAL) | p. 2")
        self.child = self.person("Testperson Child (FICTIONAL)")
        self.fam = publish_new(self.db, self.contrib, self.editor, "family", {"display_name": "Testfamily Merge (FICTIONAL)"})
        self.ev = publish_new(self.db, self.contrib, self.editor, "event", {"title": "Test Merge Event (FICTIONAL)"})
        self.link("relationship", {"person_a": self.dup["public_id"], "person_b": self.child["public_id"],
                                   "relationship_type": "parent_of"}, by=self.editor2)
        for who in (self.keep, self.dup):        # both in the same family: the duplicate link must be dropped, not doubled
            self.db.execute("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility) VALUES (?,?, 'published','public')",
                            (self.fam["id"], who["id"]))
        self.link("participation", {"event": self.ev["public_id"], "person": self.dup["public_id"]})

    def test_merge_moves_everything_and_keeps_the_old_address_working(self):
        ed = self.client("editor1")
        r = ed.get(f"/editor/merge?keep={self.keep['public_id']}&retire=Anything [{self.dup['public_id']}]")
        self.assertEqual(r.status_code, 200)
        self.assertIn("relationships (1)", r.get_data(as_text=True))
        r = ed.post("/editor/merge", {"keep": self.keep["public_id"], "retire": self.dup["public_id"], "fill_gaps": "1",
                                      "reason": "Same birth record in two registers (FICTIONAL)"})
        self.assertEqual(r.status_code, 302)
        retired = entities.get(self.db, self.dup["id"])
        self.assertEqual(retired["merged_into"], self.keep["id"])
        anon = self.client()
        r = anon.get(f"/people/{self.dup['slug']}")
        self.assertEqual((r.status_code, r.headers["Location"]), (301, f"/people/{self.keep['slug']}"))
        self.assertEqual(anon.get(f"/id/{self.dup['public_id']}").headers["Location"], f"/people/{self.keep['slug']}")
        html = anon.get(f"/people/{self.keep['slug']}").get_data(as_text=True)
        for expected in ("Test Book A (FICTIONAL)", "Test Book B (FICTIONAL)",       # both citations kept
                         f"/people/{self.child['slug']}",                            # relationship moved
                         f"/families/{self.fam['slug']}", f"/events/{self.ev['slug']}",
                         "T. Kept-F", "c. 2099", f"/places/{self.place['slug']}"):  # names and filled gaps
            self.assertIn(expected, html)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM family_memberships WHERE family_id=?", (self.fam["id"],)).fetchone()[0], 1)
        search_html = anon.get("/search?q=kept").get_data(as_text=True)
        self.assertEqual(search_html.count('class="result"'), 1)
        m = self.db.execute("SELECT * FROM merges").fetchone()
        self.assertEqual((m["performed_by"], m["reason"]), (self.editor.id, "Same birth record in two registers (FICTIONAL)"))
        log = json.loads(self.db.execute("SELECT detail_json FROM audit_logs WHERE action='record.merged'").fetchone()[0])
        self.assertEqual(len(log["dropped"]), 1)                                     # the duplicate family membership
        self.assertTrue(self.db.execute("SELECT COUNT(*) FROM revisions WHERE entity_id=?", (self.dup["id"],)).fetchone()[0] >= 2)

    def test_merge_rules(self):
        ed = self.client("editor1")
        for keep, retire in ((self.keep, self.keep), (self.keep, self.place)):
            with self.assertRaises(merging.MergeError):
                merging.merge(self.db, self.editor, keep["public_id"], retire["public_id"], "x")
        with self.assertRaises(merging.MergeError):
            merging.merge(self.db, self.editor, self.keep["public_id"], self.dup["public_id"], "  ")
        ed.post("/editor/merge", {"keep": self.keep["public_id"], "retire": self.dup["public_id"], "reason": ""})
        self.assertIsNone(entities.get(self.db, self.dup["id"])["merged_into"])
        self.assertEqual(self.client("contrib").post("/editor/merge", {"keep": self.keep["public_id"], "retire": self.dup["public_id"],
                                                                         "reason": "x"}).status_code, 403)
        merging.merge(self.db, self.editor, self.keep["public_id"], self.dup["public_id"], "Test (FICTIONAL)")
        with self.assertRaises(merging.MergeError):            # already merged
            merging.merge(self.db, self.editor, self.keep["public_id"], self.dup["public_id"], "again")

    def test_duplicate_report_lists_the_pair(self):
        html = self.client("editor1").get("/editor/duplicates").get_data(as_text=True)
        self.assertIn(self.dup["public_id"], html)
        self.assertIn("same name or spelling", html)


class Curation(Base):
    def setUp(self):
        super().setUp()
        self.p = self.person("Testperson Curated (FICTIONAL)", sources="Test Diary (FICTIONAL) | p. 7")
        self.src = self.db.execute("SELECT e.* FROM entities e WHERE kind='source'").fetchone()
        self.ed = self.client("editor1")

    def test_direct_edit_needs_a_reason_and_is_recorded(self):
        url = f"/editor/records/{self.p['public_id']}/edit"
        form = {"preferred_name": "Testperson Curated Renamed (FICTIONAL)", "living_status": "unknown", "occupation": "Teacher (FICTIONAL)"}
        r = self.ed.post(url, form)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client("contrib").post(url, {**form, "reason": "x"}).status_code, 403)
        self.assertEqual(self.ed.post(url, {**form, "reason": "Spelling confirmed in register (FICTIONAL)"}).status_code, 302)
        rev = self.db.execute("SELECT * FROM revisions WHERE entity_id=? ORDER BY revision_number DESC", (self.p["id"],)).fetchone()
        self.assertIn("Edited by an editor", rev["change_summary"])
        self.assertEqual(rev["reason"], "Spelling confirmed in register (FICTIONAL)")
        html = self.page(f"/people/{self.p['slug']}")[1]
        self.assertIn("Teacher (FICTIONAL)", html)
        self.assertIn("Testperson Curated (FICTIONAL)", html)          # the old name stays as an alternate

    def test_citations_are_rated_per_claim_and_removal_is_audited(self):
        base = f"/editor/records/{self.p['public_id']}/citations"
        self.ed.post(base, {"source": f"x [{self.src['public_id']}]", "field_name": "birth", "evidence_status": "well_supported",
                            "claim_text": "Born c. 2099 (FICTIONAL)", "locator": "p. 9"})
        cid = self.db.execute("SELECT MAX(id) FROM citations").fetchone()[0]
        html = self.page(f"/people/{self.p['slug']}")[1]
        self.assertIn("Well supported", html)
        self.assertIn("Born c. 2099 (FICTIONAL)", html)
        self.ed.post(f"{base}/{cid}", {"op": "update", "field_name": "birth", "evidence_status": "disputed",
                                       "claim_text": "Born c. 2099 (FICTIONAL)", "locator": "p. 9"})
        self.assertEqual(self.db.execute("SELECT evidence_status FROM citations WHERE id=?", (cid,)).fetchone()[0], "disputed")
        self.ed.post(f"{base}/{cid}", {"op": "remove", "field_name": "birth", "evidence_status": "disputed"})
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM citations WHERE id=?", (cid,)).fetchone())   # reason required
        self.ed.post(f"{base}/{cid}", {"op": "remove", "field_name": "birth", "evidence_status": "disputed", "reason": "Wrong page (FICTIONAL)"})
        self.assertIsNone(self.db.execute("SELECT 1 FROM citations WHERE id=?", (cid,)).fetchone())
        removed = json.loads(self.db.execute("SELECT detail_json FROM audit_logs WHERE action='citation.removed'").fetchone()[0])
        self.assertEqual(removed["removed"]["claim_text"], "Born c. 2099 (FICTIONAL)")
        self.assertEqual(self.client("contrib").post(base, {"source": self.src["public_id"]}).status_code, 403)

    def test_differing_accounts(self):
        base = f"/editor/records/{self.p['public_id']}/accounts"
        self.ed.post(base, {"topic": "Year of birth (FICTIONAL)", "account_text": "One register says 2098 (FICTIONAL).",
                            "attributed_to": "Register A (FICTIONAL)", "is_public": "1", "needs_research": "1"})
        self.ed.post(base, {"topic": "Staff-only topic (FICTIONAL)", "account_text": "Not yet public (FICTIONAL)."})
        html = self.page(f"/people/{self.p['slug']}")[1]
        self.assertIn("One register says 2098 (FICTIONAL).", html)
        self.assertIn("Further research needed", html)
        self.assertNotIn("Not yet public", html)
        aid = self.db.execute("SELECT MIN(id) FROM conflicting_accounts").fetchone()[0]
        self.ed.post(f"{base}/{aid}", {"topic": "Year of birth (FICTIONAL)", "account_text": "Changed (FICTIONAL).", "is_public": "1"})
        self.assertEqual(self.db.execute("SELECT account_text FROM conflicting_accounts WHERE id=?", (aid,)).fetchone()[0],
                         "One register says 2098 (FICTIONAL).")           # no reason → unchanged
        self.ed.post(f"{base}/{aid}", {"topic": "Year of birth (FICTIONAL)", "account_text": "Changed (FICTIONAL).", "is_public": "1",
                                       "reason": "Transcription fixed (FICTIONAL)"})
        before = json.loads(self.db.execute("SELECT detail_json FROM audit_logs WHERE action='account.updated'").fetchone()[0])["before"]
        self.assertEqual(before["account_text"], "One register says 2098 (FICTIONAL).")

    def test_links_can_be_corrected_but_living_people_need_consent(self):
        other = self.person("Testperson Spouse (FICTIONAL)")
        self.link("relationship", {"person_a": self.p["public_id"], "person_b": other["public_id"], "relationship_type": "spouse_of"},
                  by=self.editor2)
        rid = self.db.execute("SELECT id FROM relationships").fetchone()[0]
        url = f"/editor/records/{self.p['public_id']}/links/relationships/{rid}"
        self.ed.post(url, {"status": "disputed", "visibility": "public", "period": "c. 2099", "reason": "Second witness disagrees (FICTIONAL)"})
        r = self.db.execute("SELECT * FROM relationships WHERE id=?", (rid,)).fetchone()
        self.assertEqual((r["status"], r["period_precision"]), ("disputed", "approximate"))
        self.assertIn("Disputed", self.page(f"/people/{self.p['slug']}")[1])
        self.db.execute("UPDATE people SET living_status='living' WHERE entity_id=?", (other["id"],))
        self.ed.post(url, {"status": "disputed", "visibility": "restricted", "reason": "Living (FICTIONAL)"})
        self.ed.post(url, {"status": "disputed", "visibility": "public", "reason": "try (FICTIONAL)"})
        self.assertEqual(self.db.execute("SELECT visibility FROM relationships WHERE id=?", (rid,)).fetchone()[0], "restricted")
        self.ed.post(url, {"op": "remove", "reason": "Entered on the wrong person (FICTIONAL)"})
        self.assertIsNone(self.db.execute("SELECT 1 FROM relationships WHERE id=?", (rid,)).fetchone())
        self.assertEqual(self.client("contrib").post(url, {"op": "remove", "reason": "x"}).status_code, 403)

    def test_quality_page(self):
        html = self.ed.get("/editor/quality").get_data(as_text=True)
        self.assertIn("Citations still marked unverified", html)
        self.assertIn(self.p["public_id"], html)


class Import(Base):
    CSV = ("preferred_name,aliases,birth,birth_place,sources,contributor_note\n"
           "Testimport One (FICTIONAL),Alias One-F;Alias Uno-F,c. 2099,{place},Test Ledger (FICTIONAL) | p. 3,from ledger\n"
           "Testimport Bad (FICTIONAL),,2099-02-30,,,\n"
           "ተስት ኣሕመድ (FICTIONAL),,,,,\n"
           "Testimport One (FICTIONAL),,,,,\n")

    def upload(self, c, data, kind="person", name="people.csv"):
        return c.post("/editor/import", {"kind": kind, "file": (io.BytesIO(data.encode("utf-8-sig")), name)})

    def test_preview_then_review_then_batch_publish(self):
        ed = self.client("editor1")
        self.assertIn("preferred_name", ed.get("/editor/import/template/person.csv").get_data(as_text=True))
        r = self.upload(ed, self.CSV.format(place=self.place["public_id"]))
        self.assertEqual(r.status_code, 302)
        iid = int(r.headers["Location"].rsplit("/", 1)[1])
        html = ed.get(f"/editor/import/{iid}").get_data(as_text=True)
        self.assertIn("3</strong> of 4 rows are valid", html)
        self.assertIn("does not exist", html)                       # the impossible date on line 3
        self.assertIn("Same name as line 2", html)                    # repeated within the file
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0], 1)   # only the place so far
        self.assertEqual(self.client("editor2").post(f"/editor/import/{iid}", {"op": "confirm"}).status_code, 200)
        self.assertEqual(self.db.execute("SELECT status FROM imports").fetchone()[0], "preview")  # only the uploader confirms
        ed.post(f"/editor/import/{iid}", {"op": "confirm"})
        subs = self.db.execute("SELECT * FROM submissions WHERE import_batch_id=?", (iid,)).fetchall()
        self.assertEqual(len(subs), 3)
        self.assertTrue(all(s["status"] == "submitted" for s in subs))
        self.assertIn("line 2", subs[0]["contributor_note"])
        self.assertNotIn("Testimport", self.client().get("/search?q=testimport").get_data(as_text=True))  # nothing public yet
        # the uploader cannot publish their own batch; another editor can, in one step
        ed.post("/editor/bulk", {"action": "publish", "sid": [str(s["id"]) for s in subs]})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM submissions WHERE import_batch_id=? AND status='published'", (iid,)).fetchone()[0], 0)
        self.client("editor2").post("/editor/bulk", {"action": "publish", "sid": [str(s["id"]) for s in subs]})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM submissions WHERE import_batch_id=? AND status='published'", (iid,)).fetchone()[0], 3)
        anon = self.client()
        html = anon.get("/search?q=alias uno").get_data(as_text=True)
        self.assertIn("Testimport One (FICTIONAL)", html)
        self.assertIn("ተስት ኣሕመድ (FICTIONAL)", anon.get("/search?q=ተስት").get_data(as_text=True))  # Ge'ez survives the round trip

    def test_bad_files_are_refused(self):
        ed = self.client("editor1")
        for data, msg in (("name,whatever\nx,y\n", "Unknown columns"), ("aliases\nx\n", "Missing required columns"),
                          ("preferred_name\n", "no data rows")):
            r = self.upload(ed, data)
            self.assertIn(msg, ed.get("/editor/import").get_data(as_text=True) if r.status_code == 302 else r.get_data(as_text=True))
        r = ed.post("/editor/import", {"kind": "person", "file": (io.BytesIO("preferred_name\nTést\n".encode("latin-1")), "x.csv")})
        self.assertIn("CSV UTF-8", r.get_data(as_text=True))
        self.assertEqual(self.client("contrib").get("/editor/import").status_code, 403)

    def test_link_kinds_can_be_imported_by_reference(self):
        publish_new(self.db, self.contrib, self.editor, "organization", {"name": "Test Org Import (FICTIONAL)"})
        p = self.person("Testperson Importlink (FICTIONAL)")
        ed = self.client("editor1")
        r = self.upload(ed, f"person,organization,role\n{p['public_id']},Test Org Import (FICTIONAL),Test role (FICTIONAL)\n", kind="affiliation")
        iid = int(r.headers["Location"].rsplit("/", 1)[1])
        ed.post(f"/editor/import/{iid}", {"op": "confirm"})
        sid = self.db.execute("SELECT id FROM submissions WHERE import_batch_id=?", (iid,)).fetchone()[0]
        self.client("editor2").post("/editor/bulk", {"action": "publish", "sid": [str(sid)]})
        self.assertIn("Test role (FICTIONAL)", self.page(f"/people/{p['slug']}")[1])


if __name__ == "__main__":
    unittest.main()
