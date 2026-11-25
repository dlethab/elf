"""Map, timeline filters, family tree and connections explorer. Every view must lead only to real,
public records and never reveal a restricted person. Test places use coordinates in the open sea
(0.5, 0.5), which are obviously not Eritrean geography; all records are labelled fictional."""
import json
import unittest

from elf_archive import create_app, queries, security
from elf_archive.services import graph
from tests.helpers import make_db, make_user, publish, publish_new, submit_new
from tests.test_http import Client


def page_state(response):
    """The exploration state the explore page starts from (already checked by the server)."""
    import html as h
    import re
    m = re.search(r"data-state='([^']*)'", response.get_data(as_text=True))
    return json.loads(h.unescape(m.group(1)))


class Base(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test"})
        self.contrib = make_user(self.db, "contrib")
        self.editor = make_user(self.db, "editor1", ["editor"])
        self.c = Client(self.app)

    def new(self, kind, **raw):
        return publish_new(self.db, self.contrib, self.editor, kind, raw)

    def link(self, kind, **raw):
        return publish(self.db, self.editor, submit_new(self.db, self.contrib, kind, raw))

    def rel(self, a, b, t="parent_of", **kw):
        sid = submit_new(self.db, self.editor, "relationship", {"person_a": a["public_id"], "person_b": b["public_id"],
                                                               "relationship_type": t, **kw})
        editor2 = self.db.execute("SELECT id FROM users WHERE username='editor2'").fetchone()
        from tests.helpers import cu
        return publish(self.db, cu(self.db, editor2[0]) if editor2 else make_user(self.db, "editor2", ["editor"]), sid)


class MapAndTimeline(Base):
    def setUp(self):
        super().setUp()
        self.exact = self.new("place", primary_name="Testport (FICTIONAL)", latitude="0.5", longitude="0.5",
                              coord_precision="exact", place_type="town_city", aliases="Testporto")
        self.approx = self.new("place", primary_name="Testhill (FICTIONAL)", latitude="0.6", longitude="0.4",
                               coord_precision="approximate", coord_note="Location estimated from a test memoir (FICTIONAL)")
        self.nowhere = self.new("place", primary_name="Testvale (FICTIONAL)")
        self.ev1 = self.new("event", title="Test Battle Drill (FICTIONAL)", date="2098 to 2099", event_type="battle_conflict",
                            place=self.exact["public_id"])
        self.ev2 = self.new("event", title="Test Meeting (FICTIONAL)", date="c. 2097", event_type="meeting_conference",
                            place=self.approx["public_id"])
        self.ev3 = self.new("event", title="Test Undated Gathering (FICTIONAL)", place=self.exact["public_id"])
        self.person = self.new("person", preferred_name="Testperson Mapped (FICTIONAL)", birth_place=self.approx["public_id"])
        self.org = self.new("organization", name="Test Front (FICTIONAL)")
        self.link("participation", event=self.ev1["public_id"], person=self.person["public_id"])
        self.link("participation", event=self.ev2["public_id"], organization=self.org["public_id"])
        self.living = publish_new(self.db, self.contrib, self.editor, "person",
                                  {"preferred_name": "Testperson Living Map (FICTIONAL)", "living_status": "living",
                                   "birth_place": self.exact["public_id"]})

    def test_map_data_uses_only_documented_public_places(self):
        data = self.c.get("/map/data.json").get_json()["places"]
        by_name = {p["name"]: p for p in data}
        self.assertEqual(set(by_name), {"Testport (FICTIONAL)", "Testhill (FICTIONAL)"})     # no coordinates → not mapped
        port, hill = by_name["Testport (FICTIONAL)"], by_name["Testhill (FICTIONAL)"]
        self.assertEqual((port["precision"], hill["precision"]), ("exact", "approximate"))
        self.assertIn("estimated", hill["note"])
        self.assertIn("testporto", port["names"])
        evs = {e["id"]: e for e in port["events"]}
        self.assertEqual(set(evs), {self.ev1["public_id"], self.ev3["public_id"]})
        drill = evs[self.ev1["public_id"]]
        self.assertEqual((drill["from"], drill["to"], drill["type"], drill["precision"]), (2098, 2099, "battle_conflict", "range"))
        self.assertIsNone(evs[self.ev3["public_id"]]["from"])            # never given a false year
        self.assertEqual(set(drill), {"id", "type", "from", "to", "precision"})   # only what the map uses; the panel loads the rest
        self.assertEqual(port["people"], 0)                  # the living person is not counted
        self.assertEqual(hill["people"], 1)
        self.assertNotIn("Living Map", json.dumps(data))

    def test_basemap_is_served_from_this_server(self):
        r = self.c.get("/map/basemap.json")
        base = json.loads(r.get_data(as_text=True))
        self.assertEqual(len(base["regions"]["features"]), 6)
        self.assertIn("Natural Earth", base["source"])
        self.assertIn("No historical boundaries", base["note"])
        html = self.c.get("/map").get_data(as_text=True)
        self.assertIn("/static/vendor/maplibre/maplibre-gl-csp.js", html)   # the CSP-compatible build (no eval, worker from this server)
        self.assertIn("/static/vendor/maplibre/maplibre-gl-csp-worker.js", html)
        self.assertIn("Testvale (FICTIONAL)", html)          # listed, not placed

    def test_terrain_is_served_from_this_server(self):
        html = self.c.get("/map").get_data(as_text=True)
        self.assertIn('data-terrain="/static/map/terrain"', html)
        r = self.c.get("/static/map/terrain/7/77/57.png")        # a tile over the Eritrean highlands
        self.assertEqual((r.status_code, r.mimetype), (200, "image/png"))
        r.close()
        self.assertNotIn("amazonaws", html)                       # the source is credited, never contacted by visitors

    def test_map_focus_and_event_precision(self):
        st = page_state(self.c.get(f"/map?place={self.exact['public_id']}"))
        self.assertEqual((st["mode"], st["place"]), ("map", self.exact["public_id"]))
        st = page_state(self.c.get(f"/map?place={self.nowhere['public_id']}x"))
        self.assertEqual(st["place"], "")                                          # unknown record: no selection
        port = next(p for p in self.c.get("/map/data.json").get_json()["places"] if p["name"].startswith("Testport"))
        self.assertEqual({e["precision"] for e in port["events"]}, {"range", "unknown"})

    def test_person_filter_shows_their_documented_places(self):
        ids = queries.person_place_ids(self.db, self.person["public_id"])
        self.assertEqual(set(ids), {self.exact["public_id"], self.approx["public_id"]})
        html = self.c.get(f"/map?person={self.person['public_id']}").get_data(as_text=True)
        self.assertIn("Testperson Mapped (FICTIONAL)", html)
        self.assertIsNone(queries.person_place_ids(self.db, self.living["public_id"]))

    def test_timeline_filters(self):
        def titles(qs):
            html = self.c.get("/timeline?" + qs).get_data(as_text=True)
            return {t for t in ("Test Battle Drill", "Test Meeting", "Test Undated Gathering") if t in html}
        self.assertEqual(titles(""), {"Test Battle Drill", "Test Meeting", "Test Undated Gathering"})
        self.assertEqual(titles("type=battle_conflict"), {"Test Battle Drill"})
        self.assertEqual(titles(f"place={self.exact['public_id']}"), {"Test Battle Drill", "Test Undated Gathering"})
        self.assertEqual(titles(f"person={self.person['public_id']}"), {"Test Battle Drill"})
        self.assertEqual(titles("organization=Test Front (FICTIONAL)"), {"Test Meeting"})
        self.assertEqual(titles("from=2099"), {"Test Battle Drill"})               # range 2098–2099 overlaps 2099
        self.assertEqual(titles("to=2097"), {"Test Meeting"})                      # undated events are never in a period
        self.assertEqual(titles("q=meeting"), {"Test Meeting"})
        # a private record in a link is dropped (with the same notice as for a record that does not exist) and never filters
        r = self.c.get(f"/timeline?person={self.living['public_id']}")
        self.assertEqual(page_state(r)["person"], "")
        self.assertIn("not public or no longer exists", r.get_data(as_text=True))
        self.assertIn("not public or no longer exists", self.c.get("/timeline?person=per-zzzzzzzz").get_data(as_text=True))
        html = self.c.get("/timeline?type=battle_conflict").get_data(as_text=True)
        self.assertIn("/explore?mode=map&amp;type=battle_conflict", html)            # switching to the map keeps the filter
        self.assertIn(f"place={self.exact['public_id']}&amp;event={self.ev1['public_id']}", html)        # event → its mapped place, on the map   # event → its mapped place
        html = self.c.get("/timeline?from=2098&to=2099").get_data(as_text=True)
        self.assertIn(f"/explore?mode=map&amp;from=2098&amp;to=2099&amp;place={self.exact['public_id']}", html)   # …keeping the chosen period           # …keeping the chosen period
        self.assertIn('name="robots" content="noindex"', html)

    def test_map_data_categories_and_relations(self):
        data = {p["name"]: p for p in self.c.get("/map/data.json").get_json()["places"]}
        port, hill = data["Testport (FICTIONAL)"], data["Testhill (FICTIONAL)"]
        self.assertEqual((port["category"], hill["category"]), ("settlement", "site"))
        self.assertEqual(port["persons"], [self.person["public_id"]])          # took part in the drill there
        self.assertEqual(hill["persons"], [self.person["public_id"]])          # born there
        self.assertEqual(hill["orgs"], [self.org["public_id"]])                # took part in the meeting there
        self.assertNotIn(self.living["public_id"], json.dumps(list(data.values())))
        self.assertEqual(port["items"], 0)

    def test_invalid_coordinates_are_never_mapped(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):                          # the database refuses them outright
            self.db.execute("UPDATE places SET latitude=95 WHERE entity_id=?", (self.approx["id"],))
        with self.assertRaises(sqlite3.IntegrityError):                          # and never stores half a coordinate
            self.db.execute("UPDATE places SET longitude=NULL WHERE entity_id=?", (self.approx["id"],))

    def test_place_preview(self):
        d = self.c.get(f"/map/place/{self.approx['public_id']}.json").get_json()
        self.assertEqual((d["title"], d["precision"]), ("Testhill (FICTIONAL)", "approximate"))
        self.assertIn("estimated", d["note"])
        self.assertEqual([e["title"] for e in d["events"]], ["Test Meeting (FICTIONAL)"])
        self.assertEqual(d["events"][0]["date"], "c. 2097")
        self.assertEqual([(x["title"], x["role"]) for x in d["people"]], [("Testperson Mapped (FICTIONAL)", "Born here")])
        self.assertEqual([o["title"] for o in d["orgs"]], ["Test Front (FICTIONAL)"])
        self.assertEqual(d["location_sources"], [])
        port = self.c.get(f"/map/place/{self.exact['public_id']}.json").get_json()
        self.assertIn("Testporto", [n["name"] for n in port["names"]])           # other spellings are shown
        self.assertNotIn("Living Map", json.dumps(port))                         # the living person is never listed
        self.assertEqual(self.c.get(f"/map/place/{self.living['public_id']}.json").status_code, 404)
        self.assertEqual(self.c.get(f"/map/place/{self.ev1['public_id']}.json").status_code, 404)

    def test_record_preview_lists_only_mapped_public_places(self):
        r = self.c.get(f"/map/record/{self.person['public_id']}.json").get_json()
        self.assertEqual(r["kind"], "person")
        self.assertEqual({p["name"] for p in r["places"]}, {"Testport (FICTIONAL)", "Testhill (FICTIONAL)"})
        ev = self.c.get(f"/map/record/{self.ev3['public_id']}.json").get_json()
        self.assertEqual(ev["date"], None)                                      # undated stays undated
        self.assertEqual([p["name"] for p in ev["places"]], ["Testport (FICTIONAL)"])
        org = self.c.get(f"/map/record/{self.org['public_id']}.json").get_json()
        self.assertEqual([p["name"] for p in org["places"]], ["Testhill (FICTIONAL)"])
        lone = self.new("event", title="Test Event Nowhere (FICTIONAL)", place=self.nowhere["public_id"])
        r = self.c.get(f"/map/record/{lone['public_id']}.json").get_json()
        self.assertEqual((r["places"], r["unmapped"]), ([], 1))                  # linked, but no coordinates: not placed
        self.assertEqual(self.c.get(f"/map/record/{self.living['public_id']}.json").status_code, 404)

    def test_atlas_search_finds_every_kind_with_its_type(self):
        def kinds(q):
            return {(r["kind"], r["title"]) for r in self.c.get("/map/search.json?q=" + q).get_json()["results"]}
        self.assertIn(("place", "Testport (FICTIONAL)"), kinds("testporto"))          # another spelling
        self.assertIn(("person", "Testperson Mapped (FICTIONAL)"), kinds("testperson"))
        self.assertIn(("event", "Test Battle Drill (FICTIONAL)"), kinds("drill"))
        self.assertIn(("organization", "Test Front (FICTIONAL)"), kinds("front"))
        self.assertNotIn("Living Map", json.dumps(self.c.get("/map/search.json?q=testperson").get_json()))
        self.assertEqual(self.c.get("/map/search.json?q=a").get_json()["results"], [])
        r = self.c.get("/map/search.json?q=drill").get_json()["results"][0]
        self.assertEqual(r["kind_label"], "Event")

    def test_map_page_filters_and_focus(self):
        r = self.c.get(f"/map?event={self.ev1['public_id']}&person={self.person['public_id']}")
        st, html = page_state(r), r.get_data(as_text=True)
        self.assertEqual((st["event"], st["person"]), (self.ev1["public_id"], self.person["public_id"]))
        self.assertIn(f'value="Testperson Mapped (FICTIONAL) [{self.person["public_id"]}]"', html)
        self.assertIn('value="cat:settlement"', html)
        r = self.c.get(f"/map?person={self.living['public_id']}")
        self.assertEqual(page_state(r)["person"], "")                              # a private person never enters the state
        self.assertIn("not public or no longer exists", r.get_data(as_text=True))
        self.assertNotIn("Living Map", r.get_data(as_text=True))
    def test_csp_allows_a_configured_tile_host_only(self):
        self.assertNotIn("tile", security.build_csp({}))
        csp = security.build_csp({"MAP_TILE_URL": "https://tile.openstreetmap.org/{z}/{x}/{y}.png"})
        self.assertIn("img-src 'self' data: blob: https://tile.openstreetmap.org", csp)
        self.assertEqual(security.build_csp({"MAP_TILE_URL": "http://insecure.test/{z}"}), security.CSP)


class TreesAndConnections(Base):
    def setUp(self):
        super().setUp()
        p = lambda n, **kw: self.new("person", preferred_name=f"Testperson {n} (FICTIONAL)", **kw)  # noqa: E731
        self.gp, self.parent, self.spouse, self.child, self.adopted = p("Grand"), p("Parent", birth="c. 2060"), p("Spouse"), p("Child"), p("Adopted")
        self.secret = publish_new(self.db, self.contrib, self.editor, "person",
                                  {"preferred_name": "Testperson Secret (FICTIONAL)", "living_status": "living"})
        self.rel(self.gp, self.parent)
        self.rel(self.parent, self.spouse, "spouse_of")
        self.rel(self.parent, self.child)
        self.rel(self.spouse, self.child)
        self.rel(self.parent, self.adopted, "adoptive_parent_of", status="disputed")
        # a restricted (living) child, recorded by staff: the workflow itself refuses links to non-public people
        self.db.execute("INSERT INTO relationships(person_a_id, person_b_id, relationship_type, publication_status, visibility) "
                        "VALUES (?,?, 'parent_of', 'published', 'restricted')", (self.parent["id"], self.secret["id"]))

    def test_tree_has_generations_and_hides_restricted_people(self):
        t = graph.person_tree(self.db, self.parent["id"])
        gens = [[n["name"] for n in row] for row in t["generations"]]
        self.assertEqual(len(gens), 3)
        self.assertIn("Testperson Grand (FICTIONAL)", gens[0])
        self.assertEqual(set(gens[1]), {"Testperson Parent (FICTIONAL)", "Testperson Spouse (FICTIONAL)"})
        self.assertEqual(set(gens[2]), {"Testperson Child (FICTIONAL)", "Testperson Adopted (FICTIONAL)"})
        self.assertNotIn("Secret", json.dumps([n["name"] for n in t["nodes"]]))
        html = self.c.get(f"/people/{self.parent['slug']}/tree").get_data(as_text=True)
        for n in (self.gp, self.child, self.adopted):
            self.assertIn(f'href="/people/{n["slug"]}"', html)
        self.assertIn("edge--adoptive_parent_of edge--disputed", html)
        self.assertIn("Disputed", html)
        self.assertNotIn("Secret", html)
        self.assertIn("<svg", html)

    def test_family_tree_marks_members(self):
        fam = self.new("family", display_name="Testfamily Tree (FICTIONAL)")
        for who in (self.parent, self.child):
            self.db.execute("INSERT INTO family_memberships(family_id, person_id, publication_status, visibility) VALUES (?,?, 'published','public')",
                            (fam["id"], who["id"]))
        html = self.c.get(f"/families/{fam['slug']}/tree").get_data(as_text=True)
        self.assertEqual(html.count("tree-node--member"), 2)
        self.assertIn("Testperson Spouse (FICTIONAL)", html)                  # one step beyond the members
        empty = self.new("family", display_name="Testfamily Empty (FICTIONAL)")
        self.assertIn("No family tree can be drawn yet", self.c.get(f"/families/{empty['slug']}/tree").get_data(as_text=True))

    def test_connections_explain_every_link_and_never_infer_acquaintance(self):
        org = self.new("organization", name="Test Union (FICTIONAL)")
        colleague = self.new("person", preferred_name="Testperson Colleague (FICTIONAL)")
        for who in (self.parent, colleague):
            self.link("affiliation", person=who["public_id"], organization=org["public_id"])
        self.db.execute("INSERT INTO affiliations(person_id, organization_id, publication_status, visibility) VALUES (?,?, 'published', 'public')",
                        (self.secret["id"], org["id"]))      # even a wrongly public link to a restricted person must not leak
        html = self.c.get(f"/people/{self.parent['slug']}/connections").get_data(as_text=True)
        self.assertIn("Testperson Colleague (FICTIONAL)", html)
        self.assertIn("This does not mean they knew each other.", html)
        self.assertIn(f"/organizations/{org['slug']}", html)
        self.assertIn("Spouse of", html)
        self.assertNotIn("Secret", html)
        self.assertEqual(self.c.get(f"/people/{self.secret['slug']}/connections").status_code, 404)


if __name__ == "__main__":
    unittest.main()


class TimelineRuler(unittest.TestCase):
    """The time ruler counts each event across its documented span and keeps uncertain dates apart."""
    def ev(self, start, end, precision):
        return {"date_start": start, "date_end": end, "date_precision": precision}

    def test_counts_by_certainty(self):
        r = queries.timeline_ruler([self.ev("2061-04-12", None, "exact"), self.ev("2064", None, "approximate"),
                                    self.ev("2066", "2068", "range"), self.ev("2070", "2079", "decade")])
        self.assertEqual((r["lo"], r["hi"], r["n"]), (2060, 2079, 4))
        bars = {b["year"]: b for b in r["bars"]}
        self.assertEqual(bars[2061]["precise"], 1)
        self.assertEqual(bars[2064]["uncertain"], 1)
        self.assertEqual([bars[y]["range"] for y in (2065, 2066, 2068, 2069)], [0, 1, 1, 0])
        self.assertEqual(sum(bars[y]["uncertain"] for y in range(2070, 2080)), 10)   # a decade-only date spans its decade
        self.assertEqual([d["count"] for d in r["decades"]], [3, 1])

    def test_no_dated_events(self):
        self.assertIsNone(queries.timeline_ruler([]))


class TimelineData(Base):
    """The interactive timeline's data: real public events, drawn over exactly the span their record allows."""
    def test_date_intervals_never_narrow_a_date(self):
        from elf_archive.atlas import date_interval
        self.assertEqual(date_interval("2061-04-12", None, "exact"), (2061.2767, 2061.2795, True))     # 12 April = day 102: a point
        self.assertEqual(date_interval("2072-09", None, "month"), (2072.6667, 2072.75, False))         # the whole month
        self.assertEqual(date_interval("2075", None, "year"), (2075.0, 2076.0, False))                 # the whole year, never a day
        self.assertEqual(date_interval("2064", None, "approximate"), (2064.0, 2065.0, False))
        self.assertEqual(date_interval("2070", "2079", "decade"), (2070.0, 2080.0, False))
        self.assertEqual(date_interval("2066", "2068", "range"), (2066.0, 2069.0, False))
        self.assertIsNone(date_interval(None, None, "unknown"))

    def setUp(self):
        super().setUp()
        self.place = self.new("place", primary_name="Testbay (FICTIONAL)", latitude="0.5", longitude="0.5", coord_precision="exact",
                              admin_region="Test Region (FICTIONAL)")
        self.ev = self.new("event", title="Test Crossing (FICTIONAL)", date="2097-05", event_type="battle_conflict",
                           place=self.place["public_id"], summary="A fictional crossing.")
        self.other = self.new("event", title="Test Elsewhere (FICTIONAL)", date="2090")
        self.undated = self.new("event", title="Test Sometime (FICTIONAL)")

    def test_data_endpoint(self):
        evs = {e["title"]: e for e in self.c.get("/timeline/data.json").get_json()["events"]}
        x = evs["Test Crossing (FICTIONAL)"]
        self.assertEqual((x["precision"], x["category"], x["from"], x["to"], x["point"]), ("month", "conflict", 2097, 2097, False))
        self.assertEqual(x["date"], "May 2097")
        self.assertEqual(x["places"][0]["region"], "Test Region (FICTIONAL)")
        self.assertTrue(x["places"][0]["mapped"])
        self.assertIsNone(evs["Test Sometime (FICTIONAL)"]["t0"])                 # listed, never placed
        self.assertFalse(x["date_disputed"])

    def test_date_disagreement_is_shown(self):
        self.db.execute("INSERT INTO conflicting_accounts(entity_id, topic, account_text, is_public, concerns_date) VALUES (?,?,?,1,1)",
                        (self.ev["id"], "Date (FICTIONAL)", "Another account (FICTIONAL)."))
        evs = {e["title"]: e for e in self.c.get("/timeline/data.json").get_json()["events"]}
        self.assertTrue(evs["Test Crossing (FICTIONAL)"]["date_disputed"])
        html = self.c.get(f"/events/{self.ev['slug']}").get_data(as_text=True)
        self.assertIn("Sources disagree about the date", html)
        r = self.c.get(f"/map/record/{self.ev['public_id']}.json").get_json()
        self.assertEqual(r["date_disputes"][0]["text"], "Another account (FICTIONAL).")
        # a private account is never shown
        self.db.execute("UPDATE conflicting_accounts SET is_public=0")
        self.assertFalse({e["title"]: e for e in self.c.get("/timeline/data.json").get_json()["events"]}["Test Crossing (FICTIONAL)"]["date_disputed"])

    def test_region_and_media_filters_on_the_list(self):
        html = self.c.get("/timeline?region=Test+Region+(FICTIONAL)").get_data(as_text=True)
        self.assertIn("Test Crossing (FICTIONAL)", html)
        self.assertNotIn("Test Elsewhere (FICTIONAL)", html)
        self.assertIn("Test Region (FICTIONAL)", self.c.get("/timeline").get_data(as_text=True))   # the option comes from the data
        self.assertNotIn("Test Crossing (FICTIONAL)</a>", self.c.get("/timeline?media=1").get_data(as_text=True))   # no public material yet

    def test_place_context_and_focus(self):
        r = self.c.get(f"/timeline?place={self.place['public_id']}&from=2090&to=2099&event={self.ev['public_id']}")
        html, st = r.get_data(as_text=True), page_state(r)
        self.assertIn('class="tl-context"', html)
        self.assertIn("Show this place on the map", html)
        # the old timeline's ?place= meant "events at this place": on the explore page that is the `at` filter
        self.assertEqual((st["mode"], st["at"], st["place"], st["event"], st["from"]), ("timeline", self.place["public_id"], "", self.ev["public_id"], 2090))
        self.assertNotIn("Test Elsewhere (FICTIONAL)</a>", html)                  # not at this place

    def test_event_page_links_and_related(self):
        self.new("event", title="Test Return (FICTIONAL)", date="2098", place=self.place["public_id"])
        html = self.c.get(f"/events/{self.ev['slug']}").get_data(as_text=True)
        self.assertIn(f"/map?event={self.ev['public_id']}&amp;place={self.place['public_id']}", html)
        self.assertIn(f"/timeline?event={self.ev['public_id']}&amp;from=2097&amp;to=2097", html)
        self.assertIn("Test Return (FICTIONAL)", html)                             # related through the same place
        self.assertIn("same place", html)
        self.assertIn("Documented location", html)
