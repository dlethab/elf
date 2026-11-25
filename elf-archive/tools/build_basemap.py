"""Build the archive's own base map of Eritrea from Natural Earth (public domain).

    python -I tools/build_basemap.py <folder with Natural Earth 10m GeoJSON files> elf_archive/static/map/eritrea-basemap.json

Inputs (Natural Earth v5.1.2, https://www.naturalearthdata.com — public domain, no permission needed):
    ne_10m_admin_0_countries.geojson, ne_10m_admin_1_states_provinces.geojson,
    ne_10m_populated_places_simple.geojson, ne_10m_rivers_lake_centerlines.geojson

The output is clipped to the region around Eritrea and simplified so it is small enough to send
to a phone. It contains MODERN geography only (country borders, current administrative regions,
present-day towns, rivers). No historical boundaries are drawn: none from a licensed, sourced
dataset are available, and the archive never invents geography. Standard library only.
"""
import json
import math
import sys
from pathlib import Path

BBOX = (31.5, 9.5, 47.5, 21.5)           # lon_min, lat_min, lon_max, lat_max: Eritrea and its surroundings
NEIGHBOURS = {"ERI", "ETH", "SDN", "DJI", "YEM", "SAU", "SOL", "SOM"}


def clip_ring(ring, box):
    """Sutherland–Hodgman clipping of one polygon ring against the rectangle."""
    x0, y0, x1, y1 = box

    def clip(points, inside, cross):
        out = []
        for i, cur in enumerate(points):
            prev = points[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
        return out

    def at_x(x):
        return lambda a, b: [x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])]

    def at_y(y):
        return lambda a, b: [a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y]

    pts = ring[:-1] if ring and ring[0] == ring[-1] else ring
    for inside, cross in ((lambda p: p[0] >= x0, at_x(x0)), (lambda p: p[0] <= x1, at_x(x1)),
                          (lambda p: p[1] >= y0, at_y(y0)), (lambda p: p[1] <= y1, at_y(y1))):
        if not pts:
            break
        pts = clip(pts, inside, cross)
    return pts + pts[:1] if len(pts) >= 3 else None


def simplify(points, tol):
    """Douglas–Peucker line simplification (degrees)."""
    if len(points) < 4:
        return points

    def dist(p, a, b):
        if a == b:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)
        t = max(0, min(1, t))
        return math.hypot(p[0] - (a[0] + t * (b[0] - a[0])), p[1] - (a[1] + t * (b[1] - a[1])))

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        s, e = stack.pop()
        best, idx = 0, None
        for i in range(s + 1, e):
            d = dist(points[i], points[s], points[e])
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(s, idx), (idx, e)]
    return [p for p, k in zip(points, keep, strict=True) if k]


def point_in_ring(pt, ring):
    x, y, inside_ = pt[0], pt[1], False
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i - 1][:2], ring[i][:2]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside_ = not inside_
    return inside_


def rnd(points):
    return [[round(x, 4), round(y, 4)] for x, y in points]


def polygons(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def clip_polygon_feature(f, tol, props):
    out = []
    for poly in polygons(f["geometry"]):
        rings = []
        for ring in poly:
            c = clip_ring(ring, BBOX)
            if c:
                s = simplify(c, tol)
                if len(s) >= 4:
                    rings.append(rnd(s))
        if rings:
            out.append(rings)
    if not out:
        return None
    return {"type": "Feature", "properties": props, "geometry": {"type": "MultiPolygon", "coordinates": out}}


def inside(p):
    return BBOX[0] <= p[0] <= BBOX[2] and BBOX[1] <= p[1] <= BBOX[3]


def lines(geom):
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []


def main(src, dest):
    src = Path(src)
    load = lambda n: json.loads((src / n).read_text(encoding="utf-8"))  # noqa: E731

    countries = []
    for f in load("ne_10m_admin_0_countries.geojson")["features"]:
        p = f["properties"]
        if p.get("ADM0_A3") in NEIGHBOURS:
            feat = clip_polygon_feature(f, 0.002 if p["ADM0_A3"] == "ERI" else 0.01,
                                        {"name": p.get("NAME_EN") or p.get("NAME"), "code": p["ADM0_A3"],
                                         "name_ti": p.get("NAME_TI") or None, "name_ar": p.get("NAME_AR") or None})
            if feat:
                countries.append(feat)

    # Natural Earth v5.1.2 attaches four of Eritrea's six region NAMES to the wrong polygons (for
    # example it puts Asmara inside "Anseba"). The outlines are used as they are, but each region is
    # named by the regional capital that lies inside it, and the build stops if that is ambiguous.
    places_src = load("ne_10m_populated_places_simple.geojson")["features"]
    town_xy = {f["properties"]["name"]: f["geometry"]["coordinates"] for f in places_src if f["properties"].get("adm0_a3") == "ERI"}
    capitals = {"Maekel": "Asmara", "Anseba": "Keren", "Northern Red Sea": "Massawa", "Debub": "Mendefera",
                "Gash-Barka": "Agordat", "Southern Red Sea": "Assab"}   # Agordat is in Gash-Barka (its capital, Barentu, is not in the dataset)
    regions = []
    for f in load("ne_10m_admin_1_states_provinces.geojson")["features"]:
        p = f["properties"]
        if p.get("adm0_a3") == "ERI":
            polys = polygons(f["geometry"])
            hits = [r for r, town in capitals.items() if town in town_xy and any(point_in_ring(town_xy[town], poly[0]) for poly in polys)]
            if len(hits) != 1:
                raise SystemExit(f"Cannot name the region Natural Earth calls {p.get('name_en')!r}: capitals inside = {hits}")
            if hits[0] != (p.get("name_en") or p.get("name")):
                print(f"  corrected region name: Natural Earth {p.get('name_en')!r} -> {hits[0]!r} (contains {capitals[hits[0]]})")
            feat = clip_polygon_feature(f, 0.003, {"name": hits[0], "capital": capitals[hits[0]]})
            if feat:
                regions.append(feat)
    if sorted(r["properties"]["name"] for r in regions) != sorted(capitals):
        raise SystemExit("Region naming check failed.")

    towns = []
    for f in load("ne_10m_populated_places_simple.geojson")["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"]
        if p.get("adm0_a3") == "ERI" or (p.get("adm0_a3") in NEIGHBOURS and inside((lon, lat)) and p.get("scalerank", 10) <= 4):
            towns.append({"type": "Feature", "properties": {"name": p.get("name"), "capital": int(p.get("featurecla", "").startswith("Admin-0 capital")),
                                                            "rank": p.get("scalerank"), "eri": int(p.get("adm0_a3") == "ERI")},
                          "geometry": {"type": "Point", "coordinates": [round(lon, 4), round(lat, 4)]}})

    rivers = []
    for f in load("ne_10m_rivers_lake_centerlines.geojson")["features"]:
        parts = []
        for line in lines(f["geometry"]):
            seg = []
            for pt in line:
                if inside(pt):
                    seg.append(pt)
                elif seg:
                    parts.append(seg)
                    seg = []
            if seg:
                parts.append(seg)
        parts = [rnd(simplify(p, 0.003)) for p in parts if len(p) >= 2]
        if parts:
            rivers.append({"type": "Feature", "properties": {"name": f["properties"].get("name")},
                           "geometry": {"type": "MultiLineString", "coordinates": parts}})

    out = {
        "source": "Natural Earth v5.1.2 (public domain), https://www.naturalearthdata.com",
        "note": "Modern geography only: present-day borders, current administrative regions, present-day towns and rivers. "
                "No historical boundaries are shown.",
        "bbox": BBOX,
        "countries": {"type": "FeatureCollection", "features": countries},
        "regions": {"type": "FeatureCollection", "features": regions},
        "towns": {"type": "FeatureCollection", "features": towns},
        "rivers": {"type": "FeatureCollection", "features": rivers},
    }
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{dest}: {len(countries)} countries, {len(regions)} regions, {len(towns)} towns, {len(rivers)} rivers, "
          f"{Path(dest).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
