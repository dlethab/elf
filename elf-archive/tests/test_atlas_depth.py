"""Editorial and archival depth in the historical atlas: the location picker on the contribution forms, captioned
archival images, location disputes, place and period context, the reviewers' proposals layer and curated
explorations. All records are synthetic and labelled fictional; coordinates are test values, not historical claims."""
import itertools
import json
import unittest

from tests.helpers import make_user, publish_new
from tests.test_http import Base

_ITEM_NO = itertools.count(1)


class Fixtures(Base):
    def setUp(self):
        super().setUp()
        pub = lambda kind, raw: publish_new(self.db, self.contrib, self.editor, kind, raw)  # noqa: E731
        self.pub = pub
        self.mapped = pub("place", {"primary_name": "Testmark (FICTIONAL)", "latitude": "0.25", "longitude": "0.75",
                                    "coord_precision": "approximate"})

    def item(self, subject, title="Test photograph (FICTIONAL)", access="public", rights="public_domain"):
        """A public archive item about a record, with a thumbnail (inserted directly: the upload path is tested elsewhere)."""
        n = [next(_ITEM_NO)]
        eid = self.db.execute("INSERT INTO entities(kind, public_id, slug, publication_status, visibility) VALUES "
                              "('archive_item', ?, ?, 'published', 'public')", (f"itm-dep{n[0]:05d}", f"test-item-{n[0]}-fictional")).lastrowid
        self.db.execute("INSERT INTO archive_items(entity_id, title, item_type, access_level, rights_status, creator, rights_holder, "
                        "created_start, created_precision) VALUES (?,?,?,?,?,?,?,?,?)",
                        (eid, title, "photograph", access, rights, "Test Photographer (FICTIONAL)", None, "2090", "year"))
        orig = self.db.execute("INSERT INTO media_files(owner_id, storage_key, mime_type, size_bytes, sha256, file_role, access_level) "
                               "VALUES (?,?,?,?,?,?,?)", (eid, f"orig-{n[0]}", "image/jpeg", 1, "x", "original", access)).lastrowid
        self.db.execute("INSERT INTO media_files(owner_id, storage_key, mime_type, size_bytes, sha256, file_role, derived_from_id, access_level) "
                        "VALUES (?,?,?,?,?,?,?,?)", (eid, f"thumb-{n[0]}", "image/jpeg", 1, "x", "thumbnail", orig, access))
        self.db.execute("INSERT INTO archive_item_subjects(item_id, subject_id) VALUES (?,?)", (eid, subject["id"]))
        return eid


class LocationPicker(Fixtures):
    def test_place_form_has_the_map_and_keeps_the_fields(self):
        html = self.client("contrib").get("/contribute/place").get_data(as_text=True)
        self.assertIn('data-locpick="point"', html)
        self.assertIn('id="locpick-config"', html)
        self.assertIn("js/locpick.js", html)
        self.assertIn('id="f-latitude"', html)                   # typing coordinates still works without the map
        self.assertLess(html.index('data-locpick="point"'), html.index('id="f-latitude"'))

    def test_every_place_field_can_be_chosen_on_the_map(self):
        c = self.client("contrib")
        self.assertIn('data-locpick="ref" data-input="f-place"', c.get("/contribute/event").get_data(as_text=True))
        person = c.get("/contribute/person").get_data(as_text=True)
        self.assertIn('data-input="f-birth_place"', person)
        self.assertIn('data-input="f-death_place"', person)
        self.assertNotIn("locpick", c.get("/contribute/source").get_data(as_text=True))   # nothing to locate

    def test_editors_and_corrections_get_it_too(self):
        html = self.client("editor1").get(f"/editor/records/{self.mapped['public_id']}/edit").get_data(as_text=True)
        self.assertIn('data-locpick="point"', html)
        self.assertIn(f'data-self="{self.mapped["public_id"]}"', html)        # not reported as "already nearby" itself
        html = self.client("contrib").get(f"/contribute/correction/{self.mapped['public_id']}").get_data(as_text=True)
        self.assertIn('data-locpick="point"', html)

    def test_a_point_from_the_map_prefills_coordinates_but_never_precision(self):
        c = self.client("contrib")
        html = c.get("/contribute/place?latitude=15.3333333&longitude=38.9").get_data(as_text=True)
        self.assertIn('value="15.33333"', html)
        self.assertIn('value="38.90000"', html)
        self.assertNotIn('<option value="exact" selected', html)
        for bad in ("latitude=abc&longitude=1", "latitude=95&longitude=1", "latitude=nan&longitude=1", "latitude=1"):
            self.assertNotIn('id="f-latitude" name="latitude" type="text" value="1', c.get("/contribute/place?" + bad).get_data(as_text=True))
        r = c.post("/contribute/place", {"primary_name": "Testpick (FICTIONAL)", "latitude": "15.33333", "longitude": "38.90000",
                                         "coord_precision": "", "action": "draft"})
        self.assertEqual(r.status_code, 400)                       # a clicked point still needs its precision stated
        self.assertIn("Say how precise these coordinates are.", r.get_data(as_text=True))

    def test_places_json_lists_only_public_located_places(self):
        hidden = self.pub("place", {"primary_name": "Testhidden (FICTIONAL)", "latitude": "1", "longitude": "1", "coord_precision": "exact"})
        self.db.execute("UPDATE entities SET visibility='restricted' WHERE id=?", (hidden["id"],))
        self.pub("place", {"primary_name": "Testnowhere (FICTIONAL)"})
        data = self.client().get("/map/places.json").get_json()["places"]
        self.assertEqual([p["name"] for p in data], ["Testmark (FICTIONAL)"])
        self.assertEqual(data[0]["label"], f"Testmark (FICTIONAL) [{self.mapped['public_id']}]")
        self.assertEqual((data[0]["lat"], data[0]["lon"], data[0]["precision"]), (0.25, 0.75, "approximate"))


class ArchivalImagery(Fixtures):
    def test_place_panel_has_a_captioned_image_linking_to_the_record(self):
        self.item(self.mapped)
        p = self.client().get(f"/map/place/{self.mapped['public_id']}.json").get_json()
        lead = p["lead"]
        self.assertEqual(lead["title"], "Test photograph (FICTIONAL)")
        self.assertEqual(lead["creator"], "Test Photographer (FICTIONAL)")
        self.assertEqual(lead["date"], "2090")
        self.assertTrue(lead["url"].startswith("/archive/"))
        self.assertTrue(lead["thumb"].startswith("/media/"))
        self.assertIn("Public domain", lead["rights_label"])

    def test_images_the_public_may_not_see_are_never_shown(self):
        self.item(self.mapped, "Test restricted photo (FICTIONAL)", access="restricted")
        self.item(self.mapped, "Test unknown rights (FICTIONAL)", rights="rights_unknown")
        p = self.client().get(f"/map/place/{self.mapped['public_id']}.json").get_json()
        self.assertIsNone(p["lead"])
        self.assertEqual(p["photos"], [])

    def test_event_preview_has_image_and_shortcut_counts(self):
        ev = self.pub("event", {"title": "Test imaged event (FICTIONAL)", "date": "2090", "place": self.mapped["public_id"],
                                "sources": "Test Source Book (FICTIONAL) | p. 4"})
        self.item(ev)
        r = self.client().get(f"/map/record/{ev['public_id']}.json").get_json()
        self.assertEqual(r["lead"]["title"], "Test photograph (FICTIONAL)")
        self.assertEqual(r["photos_total"], 1)
        self.assertEqual(r["sources_total"], 1)


class EvidenceAndContext(Fixtures):
    def account(self, entity, location=1, public=1):
        self.db.execute("INSERT INTO conflicting_accounts(entity_id, topic, account_text, attributed_to, is_public, concerns_location) "
                        "VALUES (?,?,?,?,?,?)", (entity["id"], "Location of the site (FICTIONAL)",
                                                 "A second fictional account places it further east.", "Test witness (FICTIONAL)", public, location))

    def test_disputed_locations_are_marked_with_the_accounts(self):
        c = self.client()
        self.assertNotIn("disputed", c.get("/map/data.json").get_json()["places"][0])
        self.account(self.mapped, public=0)                        # a non-public account changes nothing
        self.assertNotIn("disputed", c.get("/map/data.json").get_json()["places"][0])
        self.account(self.mapped)
        self.assertTrue(c.get("/map/data.json").get_json()["places"][0]["disputed"])
        d = c.get(f"/map/place/{self.mapped['public_id']}.json").get_json()["location_disputes"]
        self.assertEqual(d, [{"topic": "Location of the site (FICTIONAL)", "text": "A second fictional account places it further east.",
                              "by": "Test witness (FICTIONAL)"}])

    def test_editors_can_mark_an_account_as_about_the_location(self):
        ed = self.client("editor1")
        self.assertIn('name="concerns_location"', ed.get(f"/editor/records/{self.mapped['public_id']}").get_data(as_text=True))
        ed.post(f"/editor/records/{self.mapped['public_id']}/accounts",
                {"topic": "Where it stood (FICTIONAL)", "account_text": "Fictional.", "is_public": "1", "concerns_location": "1"})
        self.assertEqual(self.db.execute("SELECT concerns_location FROM conflicting_accounts").fetchone()[0], 1)

    def test_families_connected_to_a_place_come_from_member_records(self):
        p = self.pub("person", {"preferred_name": "Testperson Born (FICTIONAL)", "birth_place": self.mapped["public_id"]})
        f = self.pub("family", {"display_name": "Testfamily Place (FICTIONAL)"})
        hidden = self.pub("family", {"display_name": "Testfamily Hidden (FICTIONAL)"})
        self.db.execute("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility) VALUES (?,?,'published','public')", (f["id"], p["id"]))
        self.db.execute("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility) VALUES (?,?,'published','restricted')", (hidden["id"], p["id"]))
        fams = self.client().get(f"/map/place/{self.mapped['public_id']}.json").get_json()["families"]
        self.assertEqual([(x["title"], x["n"]) for x in fams], [("Testfamily Place (FICTIONAL)", 1)])

    def test_period_context_counts_records_and_never_includes_private_ones(self):
        a = self.pub("event", {"title": "Test early event (FICTIONAL)", "date": "c. 2061", "place": self.mapped["public_id"],
                               "sources": "Test Period Source (FICTIONAL) | p. 1"})
        self.pub("event", {"title": "Test later event (FICTIONAL)", "date": "2064-02", "place": self.mapped["public_id"]})
        private = self.pub("event", {"title": "Test private event (FICTIONAL)", "date": "2062"})
        self.db.execute("UPDATE entities SET visibility='restricted' WHERE id=?", (private["id"],))
        self.pub("event", {"title": "Test outside event (FICTIONAL)", "date": "2099"})
        per = self.pub("person", {"preferred_name": "Testperson Period (FICTIONAL)"})
        self.db.execute("INSERT INTO event_participants(event_id, person_id, publication_status) VALUES (?,?,'published')", (a["id"], per["id"]))
        c = self.client().get("/explore/context.json?from=2060&to=2069").get_json()
        self.assertEqual((c["n"], c["uncertain"]), (2, 1))
        self.assertEqual([e["title"] for e in c["events"]], ["Test early event (FICTIONAL)"])    # only events with cited sources
        self.assertEqual(c["places"][0]["title"], "Testmark (FICTIONAL)")
        self.assertEqual(c["places"][0]["n"], 2)
        self.assertEqual([p["title"] for p in c["people"]], ["Testperson Period (FICTIONAL)"])
        self.assertEqual([s["title"] for s in c["sources"]], ["Test Period Source (FICTIONAL)"])
        self.assertNotIn("private", json.dumps(c))
        self.assertEqual(self.client().get("/explore/context.json").get_json(), {"n": 0})        # no period, no summary
        self.assertEqual(self.client().get("/explore/context.json?from=1500&to=1501").get_json()["n"], 0)

    def test_interface_labels_are_never_defined_twice(self):
        """Each view reads its labels from one JSON attribute; a repeated key silently replaces a label
        (this once turned the timeline's count into "9 matching events · Date unknown")."""
        import html as htmlmod
        import re

        def no_dupes(pairs):
            keys = [k for k, _ in pairs]
            self.assertEqual(len(keys), len(set(keys)), sorted(k for k in keys if keys.count(k) > 1))
            return dict(pairs)
        page = self.client("editor1").get("/explore").get_data(as_text=True)
        blobs = re.findall(r"data-i18n='([^']*)'", page)
        self.assertGreaterEqual(len(blobs), 4)
        for b in blobs:
            json.loads(htmlmod.unescape(b), object_pairs_hook=no_dupes)

    def test_explore_page_layers_and_legend(self):
        html = self.client().get("/explore").get_data(as_text=True)
        for s in ('data-layer="evplaces"', 'data-layer="otherplaces"', "Historical routes and boundaries are not shown",
                  "Sources disagree about the location"):
            self.assertIn(s, html)
        self.assertNotIn('data-layer="proposals"', html)              # reviewers only
        self.assertNotIn("data-review", html)
        self.assertIn('data-layer="proposals"', self.client("editor1").get("/explore").get_data(as_text=True))


class ReviewLayer(Fixtures):
    def test_only_reviewers_see_proposed_places_and_never_in_public_data(self):
        c = self.client("contrib")
        c.post("/contribute/place", {"primary_name": "Testproposed (FICTIONAL)", "latitude": "1.5", "longitude": "2.5",
                                     "coord_precision": "approximate", "action": "submit"})
        c.post("/contribute/place", {"primary_name": "Testdraft (FICTIONAL)", "latitude": "1.6", "longitude": "2.6",
                                     "coord_precision": "approximate", "action": "draft"})
        c.post(f"/contribute/correction/{self.mapped['public_id']}", {"primary_name": "Testmark (FICTIONAL)", "latitude": "0.3",
                                                                     "longitude": "0.8", "coord_precision": "approximate",
                                                                     "contributor_note": "Fictional correction.", "action": "submit"})
        self.assertEqual(self.client().get("/map/review.json").status_code, 404)
        self.assertEqual(c.get("/map/review.json").status_code, 404)
        r = self.client("editor1").get("/map/review.json")
        self.assertIn("no-store", r.headers["Cache-Control"])
        got = {(p["title"], p["change"]) for p in r.get_json()["proposals"]}
        self.assertEqual(got, {("Testproposed (FICTIONAL)", False), ("Testmark (FICTIONAL)", True)})   # drafts are not proposals yet
        self.assertTrue(all(p["url"].startswith("/editor/submissions/") for p in r.get_json()["proposals"]))
        public = json.dumps(self.client().get("/map/data.json").get_json())
        self.assertNotIn("Testproposed", public)


class CuratedExplorations(Fixtures):
    def form(self, items, **kw):
        return {"title": "Test exploration of the 2060s (FICTIONAL)", "description": "A fictional selection for the tests.",
                "sources_note": "Test Source Book (FICTIONAL)", "period_from": "2060", "period_to": "2069", "items": items,
                "is_published": "1", **kw}

    def test_editor_curates_and_visitors_see_only_public_records(self):
        ev = self.pub("event", {"title": "Test curated event (FICTIONAL)", "date": "2063", "place": self.mapped["public_id"]})
        ed = self.client("editor1")
        r = ed.post("/editor/explorations", self.form(f"Testmark (FICTIONAL) [{self.mapped['public_id']}]\n"
                                                      f"Test curated event [{ev['public_id']}] | The first fictional meeting."))
        self.assertEqual(r.status_code, 302)
        x = self.db.execute("SELECT * FROM explorations").fetchone()
        self.assertEqual((x["slug"], x["created_by"]), ("test-exploration-of-the-2060s-fictional", self.editor.id))
        self.assertTrue(self.db.execute("SELECT 1 FROM audit_logs WHERE action='exploration.created'").fetchone())
        v = self.client()
        listing = v.get("/explore/curated").get_data(as_text=True)
        self.assertIn("Test exploration of the 2060s (FICTIONAL)", listing)
        page = v.get(f"/explore/curated/{x['slug']}").get_data(as_text=True)
        self.assertIn("Curated by Editor1", page)
        self.assertIn("The first fictional meeting.", page)
        self.assertIn("Test Source Book (FICTIONAL)", page)
        self.assertIn("/explore?mode=both&amp;from=2060&amp;to=2069", page)
        self.assertIn(f"event={ev['public_id']}", page)                # "on the map": the event has a located place
        self.assertIn("/explore/curated", v.get("/explore").get_data(as_text=True))
        # a record that becomes private drops out; with nothing public left, the exploration is not shown at all
        self.db.execute("UPDATE entities SET visibility='restricted' WHERE id=?", (ev["id"],))
        self.assertNotIn("Test curated event", v.get(f"/explore/curated/{x['slug']}").get_data(as_text=True))
        self.db.execute("UPDATE entities SET visibility='restricted' WHERE id=?", (self.mapped["id"],))
        self.assertEqual(v.get(f"/explore/curated/{x['slug']}").status_code, 404)
        self.assertNotIn(x["slug"], v.get("/explore/curated").get_data(as_text=True))

    def test_only_public_records_can_be_added_and_drafts_stay_hidden(self):
        secret = self.pub("person", {"preferred_name": "Testperson Secret (FICTIONAL)"})
        self.db.execute("UPDATE entities SET visibility='restricted' WHERE id=?", (secret["id"],))
        ed = self.client("editor1")
        r = ed.post("/editor/explorations", self.form(f"Testperson Secret [{secret['public_id']}]"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("is not a published, public record", r.get_data(as_text=True))
        self.assertIsNone(self.db.execute("SELECT 1 FROM explorations").fetchone())
        self.assertIn("Add at least one record", ed.post("/editor/explorations", self.form("")).get_data(as_text=True))
        ed.post("/editor/explorations", self.form(f"[{self.mapped['public_id']}]", is_published=""))
        slug = self.db.execute("SELECT slug FROM explorations").fetchone()[0]
        self.assertEqual(self.client().get(f"/explore/curated/{slug}").status_code, 404)    # a draft is not public

    def test_contributors_cannot_curate(self):
        c = self.client("contrib")
        self.assertEqual(c.get("/editor/explorations").status_code, 403)
        self.assertEqual(c.post("/editor/explorations", self.form(f"[{self.mapped['public_id']}]")).status_code, 403)

    def test_editing_and_deleting_are_audited(self):
        ed = self.client("editor1")
        ed.post("/editor/explorations", self.form(f"[{self.mapped['public_id']}]"))
        xid = self.db.execute("SELECT id FROM explorations").fetchone()[0]
        self.assertIn(f"Testmark (FICTIONAL) [{self.mapped['public_id']}]", ed.get(f"/editor/explorations/{xid}").get_data(as_text=True))
        other = make_user(self.db, "editor3", ["editor"])
        ed3 = self.client("editor3")
        ed3.post(f"/editor/explorations/{xid}", self.form(f"[{self.mapped['public_id']}]", title="Test renamed (FICTIONAL)"))
        x = self.db.execute("SELECT title, updated_by FROM explorations").fetchone()
        self.assertEqual((x["title"], x["updated_by"]), ("Test renamed (FICTIONAL)", other.id))
        ed3.post(f"/editor/explorations/{xid}", {"op": "delete"})
        self.assertIsNone(self.db.execute("SELECT 1 FROM explorations").fetchone())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM audit_logs WHERE action LIKE 'exploration.%'").fetchone()[0], 3)

    def test_bad_years_are_refused(self):
        ed = self.client("editor1")
        self.assertIn("four digits", ed.post("/editor/explorations", self.form(f"[{self.mapped['public_id']}]", period_from="60s")).get_data(as_text=True))
        self.assertIn("must start before", ed.post("/editor/explorations", self.form(f"[{self.mapped['public_id']}]", period_from="2070")).get_data(as_text=True))


class RecordPages(Fixtures):
    def test_a_located_place_page_has_its_map(self):
        html = self.client().get(f"/places/{self.mapped['slug']}").get_data(as_text=True)
        self.assertIn('id="place-map"', html)
        self.assertIn('data-lat="0.25" data-lon="0.75" data-precision="approximate"', html)
        self.assertIn("js/placemap.js", html)
        self.assertIn(f'href="/map?place={self.mapped["public_id"]}"', html)
        self.assertIn("Approximate location: this is not an established exact point.", html)
        other = self.pub("place", {"primary_name": "Testnowhere (FICTIONAL)"})
        html = self.client().get(f"/places/{other['slug']}").get_data(as_text=True)
        self.assertNotIn('id="place-map"', html)                    # no coordinates: no map, nothing invented
        self.assertNotIn("placemap.js", html)

    def test_person_profile_shows_their_archive_photograph(self):
        person = self.pub("person", {"preferred_name": "Testperson Portrait (FICTIONAL)", "living_status": "deceased"})
        html = self.client().get(f"/people/{person['slug']}").get_data(as_text=True)
        self.assertIn("No photograph of this person is in the archive yet.", html)
        self.assertIn(f'href="/contribute/correction/{person["public_id"]}">Add a photograph', html)
        self.item(person, "Test restricted portrait (FICTIONAL)", access="restricted")
        self.assertIn("No photograph of this person", self.client().get(f"/people/{person['slug']}").get_data(as_text=True))
        self.item(person, "Test portrait (FICTIONAL)")
        html = self.client().get(f"/people/{person['slug']}").get_data(as_text=True)
        profile = html.split('class="profile"', 1)[1].split('class="profile__facts"', 1)[0]
        self.assertIn('alt="Test portrait (FICTIONAL)"', profile)
        self.assertIn("By Test Photographer (FICTIONAL)", profile)
        self.assertIn("Open the archive record", profile)
        self.assertNotIn("Test restricted portrait", html)
        self.assertNotIn("No photograph of this person", html)


class Embedding(unittest.TestCase):
    """The map and timeline can be shown inside the organization's own website (e.g. a WordPress page), and only there."""
    def app(self, origins):
        from elf_archive import create_app
        from tests.helpers import make_db
        return create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": make_db(), "SECRET_KEY": "x" * 40,
                           "EMBED_ORIGINS": origins})

    def test_nothing_may_frame_the_archive_by_default(self):
        c = self.app("").test_client()
        r = c.get("/explore?embed=1")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])

    def test_listed_sites_may_frame_only_the_embedded_map_and_timeline(self):
        c = self.app("https://elfveterans.org, https://www.elfveterans.org").test_client()
        for url in ("/explore?embed=1", "/map?embed=1", "/timeline?embed=1&from=1960"):
            r = c.get(url)
            self.assertIn("frame-ancestors https://elfveterans.org https://www.elfveterans.org", r.headers["Content-Security-Policy"], url)
            self.assertNotIn("X-Frame-Options", r.headers, url)
        for url in ("/explore", "/auth/login?embed=1", "/contribute/place?embed=1", "/people?embed=1", "/editor?embed=1"):
            r = c.get(url)
            self.assertEqual(r.headers.get("X-Frame-Options"), "DENY", url)
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"], url)

    def test_embedded_layout_keeps_its_mode_and_opens_the_full_archive_outside(self):
        c = self.app("https://elfveterans.org").test_client()
        html = c.get("/map?embed=1&from=1960").get_data(as_text=True)
        self.assertNotIn('class="site-header"', html)
        self.assertNotIn('class="site-footer"', html)
        self.assertIn("data-embed", html)
        self.assertIn('href="/explore?mode=timeline&amp;from=1960&amp;embed=1"', html)        # switching view stays embedded
        self.assertIn('href="/explore?mode=map&amp;from=1960" target="_blank"', html)          # the full archive opens outside
        full = c.get("/map").get_data(as_text=True)
        self.assertIn('class="site-header"', full)

    def test_only_real_site_addresses_are_accepted(self):
        from elf_archive.config import load_config
        for bad in ("elfveterans.org", "https://elfveterans.org/wp/", "*", "javascript:alert(1)"):
            with self.assertRaises(RuntimeError, msg=bad):
                load_config({"ENV": "testing", "EMBED_ORIGINS": bad})
        with self.assertRaises(RuntimeError):
            load_config({"ENV": "production", "SECRET_KEY": "x" * 40, "BASE_URL": "https://a.test", "EMBED_ORIGINS": "http://elfveterans.org"})


class PendingMigrations(unittest.TestCase):
    """New code must never meet an old database silently (this is what broke the map and timeline once)."""
    def setUp(self):
        import os
        import sqlite3
        import tempfile
        self.path = os.path.join(tempfile.mkdtemp(), "old.db")
        sqlite3.connect(self.path).close()           # an empty database: every migration is pending

    def test_development_applies_them_at_start_up(self):
        from elf_archive import create_app, db as dbm
        create_app({"ENV": "development", "DATABASE_PATH": self.path, "SECRET_KEY": "x" * 40})
        self.assertEqual(dbm.pending_migrations(self.path), [])

    def test_production_reports_them_and_leaves_the_database_alone(self):
        from elf_archive import create_app, db as dbm
        with self.assertLogs("elf_archive", level="ERROR") as log:
            create_app({"ENV": "production", "DATABASE_PATH": self.path, "SECRET_KEY": "x" * 40, "BASE_URL": "https://archive.test"})
        self.assertIn("flask --app elf_archive migrate", log.output[0])
        self.assertIn("0011_atlas_depth", dbm.pending_migrations(self.path))


if __name__ == "__main__":
    unittest.main()
