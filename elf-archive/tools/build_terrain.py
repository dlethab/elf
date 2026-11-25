"""Build the archive's own elevation tiles for the 3D map of Eritrea.

    python -I tools/build_terrain.py elf_archive/static/map/terrain

Source: Terrain Tiles (Mapzen / AWS Open Data, "terrarium" encoding), https://registry.opendata.aws/terrain-tiles/
Underlying data: SRTM (NASA), GMTED2010 (USGS), ETOPO1 (NOAA) and others; attribution is shown on the map.
Elevation in a terrarium tile: (red * 256 + green + blue / 256) - 32768 metres.

The tiles are downloaded ONCE, checked, and then served from this server, so visitors' browsers never
contact a third party. Two changes are made to each tile:
  * the sea floor is flattened at SEA_FLOOR metres, so the Red Sea reads as a calm surface in the tilted
    view rather than a deep trench (land below sea level, such as the Danakil depression at about
    -125 m, is above SEA_FLOOR and therefore kept as it is);
  * the PNG is re-saved with maximum lossless compression.
No elevation on land is altered. Re-running the script skips tiles that already exist.
"""
import io
import math
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

SOURCE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
BBOX = (35.0, 11.0, 44.5, 19.5)       # lon_min, lat_min, lon_max, lat_max: Eritrea, its neighbours' edges and the Red Sea
ZOOMS = range(5, 10)                   # z9 is about 300 m per pixel at this latitude; the map interpolates beyond it
SEA_FLOOR = -150                       # metres


def tile_range(z):
    n = 2 ** z

    def x(lon):
        return int((lon + 180) / 360 * n)

    def y(lat):
        return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return range(x(BBOX[0]), x(BBOX[2]) + 1), range(y(BBOX[3]), y(BBOX[1]) + 1)


def flatten_sea(img):
    img = img.convert("RGB")
    px = img.load()
    floor = SEA_FLOOR + 32768
    r0, g0 = divmod(floor, 256)
    for j in range(img.height):
        for i in range(img.width):
            r, g, b = px[i, j]
            if r * 256 + g < floor:
                px[i, j] = (r0, g0, 0)
    return img


def main(out):
    out = Path(out)
    total = done = 0
    for z in ZOOMS:
        xs, ys = tile_range(z)
        for x in xs:
            for y in ys:
                total += 1
                dest = out / str(z) / str(x) / f"{y}.png"
                if dest.exists():
                    continue
                with urllib.request.urlopen(SOURCE.format(z=z, x=x, y=y), timeout=60) as r:
                    data = r.read()
                img = Image.open(io.BytesIO(data))
                img.verify()                                   # refuse anything that is not a valid PNG
                img = Image.open(io.BytesIO(data))
                if img.size != (256, 256):
                    raise SystemExit(f"unexpected tile size {img.size} for {z}/{x}/{y}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                flatten_sea(img).save(dest, "PNG", optimize=True)
                done += 1
                time.sleep(0.05)
    size = sum(f.stat().st_size for f in out.rglob("*.png"))
    print(f"{total} tiles ({done} downloaded now), {size / 1e6:.1f} MB in {out}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
