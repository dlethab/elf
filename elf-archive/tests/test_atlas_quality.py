"""Quality checks for the historical atlas: geography, data integrity, error handling and caching.
Records used here are synthetic and labelled fictional; the geography checked is the base map and terrain
shipped with the site (Natural Earth and Terrain Tiles), not any historical claim."""
import json
import math
import re
import unittest
from pathlib import Path

from PIL import Image

from elf_archive import create_app
from tests.helpers import make_db, make_user, publish_new
from tests.test_explore import page_state
from tests.test_http import Client

STATIC = Path(__file__).resolve().parent.parent / "elf_archive" / "static"


def bbox(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    xs = [c[0] for poly in polys for ring in poly for c in ring]
    ys = [c[1] for poly in polys for ring in poly for c in ring]
    return min(xs), min(ys), max(xs), max(ys)


def contains(geom, lon, lat):
    """Point in polygon (ray casting), outer rings only."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    for poly in polys:
        ring, inside = poly[0], False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                inside = not inside
        if inside:
            return True
    return False


def elevation(lon, lat, z=9):
    """Metres at a point, read from the shipped terrarium tiles (Web Mercator tiling, WGS 84 input)."""
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    img = Image.open(STATIC / "map" / "terrain" / str(z) / str(int(x)) / f"{int(y)}.png").convert("RGB")
    r, g, b = img.getpixel((int((x - int(x)) * 256), int((y - int(y)) * 256)))
    return r * 256 + g + b / 256 - 32768


class Geography(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = json.loads((STATIC / "map" / "eritrea-basemap.json").read_text(encoding="utf-8"))
        cls.eri = next(f for f in cls.base["countries"]["features"] if f["properties"]["code"] == "ERI")

    def test_outline_is_eritrea_in_lon_lat_order(self):
        x0, y0, x1, y1 = bbox(self.eri["geometry"])
        # Eritrea lies between about 36.4°E–43.1°E and 12.4°N–18.0°N; GeoJSON order is [longitude, latitude] (WGS 84)
        self.assertAlmostEqual(x0, 36.43, delta=0.15); self.assertAlmostEqual(x1, 43.13, delta=0.15)
        self.assertAlmostEqual(y0, 12.36, delta=0.15); self.assertAlmostEqual(y1, 18.0, delta=0.15)
        self.assertTrue(contains(self.eri["geometry"], 38.93, 15.33))         # Asmara is inside
        self.assertFalse(contains(self.eri["geometry"], 40.2, 16.8))          # the Red Sea is not

    def test_initial_view_frames_the_same_outline(self):
        js = (STATIC / "js" / "map.js").read_text(encoding="utf-8")
        m = re.search(r"var ERITREA = \[\[([\d.]+), ([\d.]+)\], \[([\d.]+), ([\d.]+)\]\]", js)
        frame = [float(v) for v in m.groups()]
        x0, y0, x1, y1 = bbox(self.eri["geometry"])
        for a, b in zip(frame, (x0, y0, x1, y1), strict=True):
            self.assertAlmostEqual(a, b, delta=0.1)

    def test_regions_are_named_by_the_capital_they_contain(self):
        towns = {f["properties"]["name"]: f["geometry"]["coordinates"] for f in self.base["towns"]["features"]}
        for f in self.base["regions"]["features"]:
            cap = f["properties"]["capital"]
            if cap in towns:
                self.assertTrue(contains(f["geometry"], *towns[cap]), f["properties"]["name"])

    def test_no_historical_boundaries_are_drawn(self):
        self.assertEqual(set(self.base) - {"source", "note", "bbox"}, {"countries", "regions", "towns", "rivers"})
        self.assertIn("No historical boundaries", self.base["note"])

    def test_terrain_elevations_are_credible(self):
        self.assertAlmostEqual(elevation(38.93, 15.33), 2330, delta=120)      # Asmara, about 2,325 m
        self.assertAlmostEqual(elevation(38.45, 15.78), 1400, delta=150)      # Keren, about 1,400 m
        self.assertEqual(elevation(40.0, 17.8), -150)                          # deep Red Sea: flattened at the documented floor
        self.assertTrue(-150 <= elevation(40.2, 16.8) < 0)                     # Dahlak Bank: shallow water, kept as it is


class DataAndErrors(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        self.app = create_app({"ENV": "testing", "DATABASE_PATH": ":memory:", "_SHARED_CONNECTION": self.db,
                               "SECRET_KEY": "x" * 40, "BASE_URL": "http://archive.test"})
        c, e = make_user(self.db, "contrib"), make_user(self.db, "editor1", ["editor"])
        self.place = publish_new(self.db, c, e, "place", {"primary_name": "Testmark (FICTIONAL)", "latitude": "0.25", "longitude": "0.75",
                                                          "coord_precision": "approximate"})
        self.c = Client(self.app)

    def test_markers_carry_the_record_coordinates_exactly(self):
        p = self.c.get("/map/data.json").get_json()["places"][0]
        row = self.db.execute("SELECT latitude, longitude, coord_precision FROM places WHERE entity_id=?", (self.place["id"],)).fetchone()
        self.assertEqual((p["lat"], p["lon"], p["precision"]), (row["latitude"], row["longitude"], "approximate"))
        self.assertEqual(p["precision_label"], "Approximate")

    def test_invalid_filters_are_ignored_not_errors(self):
        for qs in ("from=abc&to=99999", "mode=nonsense", "type=<script>", "region=Nowhere", "ptype=cat:invalid",
                   "place=not-an-id", "event=evt-00000000", "lpage=-4", "lpage=abc"):
            r = self.c.get("/explore?" + qs)
            self.assertEqual(r.status_code, 200, qs)
            st = page_state(r)
            self.assertIsNone(st["from"]); self.assertIsNone(st["to"])
            self.assertIn(st["mode"], ("map", "timeline", "both"))
            self.assertNotIn("<script>", r.get_data(as_text=True).split("data-state")[1][:400])
        self.assertEqual(self.c.get("/map/search.json?q=").get_json(), {"results": []})
        self.assertEqual(self.c.get("/map/search.json?q=zzqqxx").get_json(), {"results": []})
        self.assertEqual(self.c.get("/map/place/plc-00000000.json").status_code, 404)
        self.assertEqual(self.c.get("/map/record/evt-00000000.json").status_code, 404)

    def test_no_technical_details_reach_visitors(self):
        r = self.c.get("/map/record/%3Cscript%3E.json")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("Traceback", r.get_data(as_text=True))

    def test_static_caching(self):
        html = self.c.get("/explore").get_data(as_text=True)
        js = re.search(r'src="(/static/js/map\.js\?v=[0-9a-f]+)"', html).group(1)       # versioned address
        r = self.c.get(js)
        self.assertIn("immutable", r.headers["Cache-Control"]); r.close()
        r = self.c.get("/static/map/terrain/5/19/14.png")
        self.assertEqual(r.headers["Cache-Control"], "public, max-age=2592000"); r.close()
        self.assertIn('data-terrain="/static/map/terrain"', html)                     # a folder gets no version
        self.assertIn("maplibre-gl-csp.js?v=", html)                                   # loaded only when the map is shown
        self.assertNotIn('<script src="/static/vendor/maplibre', html)

    def test_map_mode_page_does_not_carry_the_event_list(self):
        publish_new(self.db, make_user(self.db, "c2"), make_user(self.db, "e2", ["editor"]), "event",
                    {"title": "Test Listed Event (FICTIONAL)", "date": "2090"})
        self.assertNotIn("Test Listed Event (FICTIONAL)", self.c.get("/explore?mode=map").get_data(as_text=True))
        self.assertIn("Test Listed Event (FICTIONAL)", self.c.get("/explore?mode=timeline").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
