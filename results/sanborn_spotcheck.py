"""Spot check of mapsnap's v2.0 Sanborn placements in NYC (docs/SANBORN_MAPSNAP_PLAN.md).

    uv run --with duckdb==2.0.0 --with pillow==11.3.0 python results/sanborn_spotcheck.py fetch
    uv run --with duckdb==2.0.0 --with pillow==11.3.0 python results/sanborn_spotcheck.py sample
    python3 results/sanborn_spotcheck.py summary
    python3 results/sanborn_spotcheck.py --self-test

fetch: mapsnap's item list and the annotation file of every placed Brooklyn and "New York"
(Manhattan and the Bronx) volume, into data/sanborn/mapsnap_v2.0/ (kept; fetched once).

sample: for each stratum, sheets in a seeded random order; a sheet joins with one of today's address
points inside its placed outline, where today's number should be the one printed on the sheet:
Brooklyn, only the 40 streets chain.py says kept their numbering since 1875 (eras.csv today=yes);
Manhattan, any street (an assumption the readings test: "renumbered"). For each, an 1000 px crop
of the Library of Congress scan around the pixel mapsnap's fit gives that point, a red ring on it
(data/sanborn/spotcheck/: sample.csv, crops/, loc_info/). Re-running fetches nothing it has.

The readings (results/sanborn_spotcheck_readings.csv, by eye from the crops) say where the
expected number is printed relative to the ring: at (the ring is on its lot or lot line), near (1-2
lots off), block (further, same crop), off (the crop shows another place), renumbered (the right
street and place, another run of numbers), missing (the right place, the number not printed),
unread. summary: those by stratum and mapsnap confidence, into results/sanborn_spotcheck.json.
"""
import csv
import json
import math
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN = "v2.0"
BASE = f"https://data.mapsnap.org/runs/{RUN}"
LOC = "https://tile.loc.gov/image-services/iiif/"
DATA = REPO / "data/sanborn"
MAPSNAP = DATA / f"mapsnap_{RUN}"
SPOT = DATA / "spotcheck"
CITY = REPO / "data/city/uf93-f8nk.csv"
ERAS = REPO / "addresses/tables/eras.csv"
READINGS = REPO / "results/sanborn_spotcheck_readings.csv"
OUT = REPO / "results/sanborn_spotcheck.json"

# stratum: (mapsnap city, first year, last year, the city file's borough code)
STRATA = {"bk1886": ("Brooklyn", 1886, 1888, "3"),
          "bk1904": ("Brooklyn", 1904, 1909, "3"),
          "mn": ("New York", 1890, 1922, "1")}
PER = 30
SEED = 20261116
CROP = 1000          # px of the full scan, square
UA = "Mozilla/5.0"   # loc.gov's Cloudflare refused urllib's default agent
PAUSE = 1.0          # seconds between requests to one host
OUTCOMES = ("at", "near", "block", "off", "renumbered", "missing", "unread")


def get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                data = r.read()
            time.sleep(PAUSE)
            return data
        except Exception as e:  # noqa: BLE001 - loc.gov times out and 5xx's; retry, then give up loudly
            if i == tries - 1:
                raise RuntimeError(f"{url}: {e}") from e
            time.sleep(5 * 3 ** i)


def fetch() -> None:
    MAPSNAP.joinpath("iiif").mkdir(parents=True, exist_ok=True)
    items = MAPSNAP / "items.tsv"
    if not items.exists():
        items.write_bytes(get(f"{BASE}/items.tsv"))
    rows = [r for r in csv.DictReader(items.open(), delimiter="\t")
            if r["state"] == "NY" and r["city"] in ("Brooklyn", "New York")
            and r["status"].startswith("published") and r["main"]]
    for r in rows:
        f = MAPSNAP / "iiif" / r["main"]
        if not f.exists():
            f.write_bytes(get(f"{BASE}/iiif/chronoscope/{r['main']}"))
    print(f"{len(rows)} volumes in {MAPSNAP / 'iiif'}")


def solve(A, b):
    """Least squares through the normal equations (systems of 3 or 4 unknowns)."""
    n = len(A[0])
    M = [[sum(r[i] * r[j] for r in A) for j in range(n)] for i in range(n)]
    v = [sum(r[i] * x for r, x in zip(A, b)) for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p], v[c], v[p] = M[p], M[c], v[p], v[c]
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * x for a, x in zip(M[r], M[c])]
                v[r] -= f * v[c]
    return [v[i] / M[i][i] for i in range(n)]


def fit(pairs, kind):
    """A map from the first of each pair to the second. helmert: a similarity with the reflection
    that turns image y (down) into north (up); else an affine (the order-1 polynomial)."""
    if kind == "helmert":
        A, B = [], []
        for (x, y), (X, Y) in pairs:
            A += [[x, -y, 1, 0], [y, x, 0, 1]]
            B += [X, -Y]
        a, b, c, e = solve(A, B)
        return lambda x, y: (a * x - b * y + c, -(b * x + a * y + e))
    A = [[x, y, 1] for (x, y), _ in pairs]
    px = solve(A, [X for _, (X, _Y) in pairs])
    py = solve(A, [Y for _, (_X, Y) in pairs])
    return lambda x, y: (px[0] * x + px[1] * y + px[2], py[0] * x + py[1] * y + py[2])


def inside(x, y, poly) -> bool:
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


class Sheet:
    """One placed annotation: its outline on the ground in metres around its first control point."""

    def __init__(self, item: dict, a: dict):
        body = a["body"]
        self.kind = body.get("transformation", {}).get("type", "polynomial")
        gcps = [(tuple(g["properties"]["resourceCoords"]), tuple(g["geometry"]["coordinates"]))
                for g in body["features"]]
        self.lon0, self.lat0 = gcps[0][1]
        self.k = math.cos(math.radians(self.lat0)) * 111320.0
        pairs = [(p, self.metres(*w)) for p, w in gcps]
        self.to_ground = fit(pairs, self.kind)
        self.to_image = fit([(w, p) for p, w in pairs], self.kind)  # a reflected similarity inverts to one
        svg = a["target"]["selector"]["value"]
        mask = [tuple(map(float, p.split(","))) for p in re.search(r'points="([^"]+)"', svg).group(1).split()]
        self.outline = [self.to_ground(*p) for p in mask]
        lons = [self.lon0 + x / self.k for x, _ in self.outline]
        lats = [self.lat0 + y / 110540.0 for _, y in self.outline]
        self.bbox = (min(lons), max(lons), min(lats), max(lats))
        src = a["target"]["source"]
        self.service, self.width = src["id"].split("/mapsnap/", 1)[1], src["width"]
        md = {m["label"]: m["value"] for m in a.get("metadata", [])}
        self.confidence = float(md.get("confidence", "nan"))
        self.item, self.year, self.volume = item["item"], int(item["year"]), item["volume"]
        self.sheet = a["label"].rsplit(" ", 1)[-1]

    def metres(self, lon, lat):
        return ((lon - self.lon0) * self.k, (lat - self.lat0) * 110540.0)

    def covers(self, lon, lat) -> bool:
        w, e, s, n = self.bbox
        return w <= lon <= e and s <= lat <= n and inside(*self.metres(lon, lat), self.outline)

    def pixel(self, lon, lat):
        return self.to_image(*self.metres(lon, lat))


def sheets() -> list:
    items = {r["main"]: r for r in csv.DictReader((MAPSNAP / "items.tsv").open(), delimiter="\t") if r["main"]}
    out = []
    for f in sorted((MAPSNAP / "iiif").glob("*.json")):
        for a in json.loads(f.read_text())["items"]:
            if len(a["body"]["features"]) >= 2:
                out.append(Sheet(items[f.name], a))
    return out


def stable_brooklyn() -> set:
    return {r["street"] for r in csv.DictReader(ERAS.open()) if r["place"] == "Brooklyn" and r["today"] == "yes"}


def truth_points() -> dict:
    """{borough code: [(lon, lat, number, full street name)]}: today's address points whose number
    should be the one on the sheets (see the docstring)."""
    sys.path.insert(0, str(REPO / "addresses"))
    import atlas  # noqa: E402 - addresses/ is not a package
    keep, keyed, out = stable_brooklyn(), {}, {"1": [], "3": []}
    for r in csv.DictReader(CITY.open()):
        b, num = r["Borough Code"], r["House Number"]
        if b not in out or r["House Number Suffix"] or not num.isdigit():
            continue
        full = r["Full Street Name"]
        if b == "3":
            if full not in keyed:
                keyed[full] = atlas.key_today(full)
            if keyed[full] not in keep:
                continue
        lon, lat = map(float, re.match(r"POINT \(([-0-9.]+) ([-0-9.]+)\)", r["the_geom"]).groups())
        out[b].append((lon, lat, int(num), full))
    return out


def sample() -> None:
    from PIL import Image, ImageDraw
    SPOT.joinpath("crops").mkdir(parents=True, exist_ok=True)
    SPOT.joinpath("loc_info").mkdir(parents=True, exist_ok=True)
    every, points, rows = sheets(), truth_points(), []
    for name, (city, y0, y1, boro) in STRATA.items():
        rng = random.Random(f"{SEED}-{name}")
        pool = [s for s in every if y0 <= s.year <= y1 and (s.item.startswith("sanborn05791") == (city == "Brooklyn"))]
        rng.shuffle(pool)
        got = 0
        for s in pool:
            cands = [p for p in points[boro] if s.covers(p[0], p[1])]
            if not cands:
                continue
            lon, lat, num, full = rng.choice(sorted(cands))
            got += 1
            rows.append({"id": f"{name}-{got:02d}", "stratum": name, "item": s.item, "year": s.year,
                         "volume": s.volume, "sheet": s.sheet, "confidence": s.confidence,
                         "number": num, "street": full, "lon": lon, "lat": lat, "service": s.service,
                         "ann_width": s.width, "px": s.pixel(lon, lat)})
            if got == PER:
                break
        print(f"{name}: {got} of {PER} ({len(pool)} sheets in the stratum)")
    with (SPOT / "sample.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, ["id", "stratum", "item", "year", "volume", "sheet", "confidence", "number",
                               "street", "lon", "lat", "x", "y", "url", "crop"])
        w.writeheader()
        for r in rows:
            info_f = SPOT / "loc_info" / (re.sub(r"[^A-Za-z0-9_.-]", "_", r["service"]) + ".json")
            if not info_f.exists():
                info_f.write_bytes(get(LOC + r["service"] + "/info.json"))
            info = json.loads(info_f.read_text())
            scale = info["width"] / r["ann_width"]
            fx, fy = r["px"][0] * scale, r["px"][1] * scale
            x0 = int(min(max(fx - CROP / 2, 0), info["width"] - CROP))
            y0 = int(min(max(fy - CROP / 2, 0), info["height"] - CROP))
            url = f"{LOC}{r['service']}/{x0},{y0},{CROP},{CROP}/full/0/default.jpg"
            crop = SPOT / "crops" / f"{r['id']}.jpg"
            if not crop.exists():
                raw = SPOT / "crops" / f"{r['id']}.raw.jpg"
                raw.write_bytes(get(url))
                im = Image.open(raw).convert("RGB")
                d, cx, cy = ImageDraw.Draw(im), fx - x0, fy - y0
                for rad in range(30, 34):
                    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), outline=(214, 39, 40))
                im.save(crop, quality=90)
                raw.unlink()
            w.writerow({k: r[k] for k in ("id", "stratum", "item", "year", "volume", "sheet", "confidence",
                                          "number", "street", "lon", "lat")}
                       | {"x": round(fx), "y": round(fy), "url": url, "crop": str(crop.relative_to(REPO))})
    print(f"{len(rows)} rows in {SPOT / 'sample.csv'}")


def band(c: float) -> str:
    return "conf >= 0.9" if c >= 0.9 else "conf < 0.9"


def summary() -> None:
    sample_rows = {r["id"]: r for r in csv.DictReader((SPOT / "sample.csv").open())}
    readings = list(csv.DictReader(READINGS.open()))
    assert all(r["outcome"] in OUTCOMES for r in readings), "an outcome outside OUTCOMES"
    table = {}
    for r in readings:
        s = sample_rows[r["id"]]
        b = band(float(s["confidence"]))
        for key in (s["stratum"], f"{s['stratum']} {b}", "all", f"all {b}"):
            t = table.setdefault(key, dict.fromkeys(OUTCOMES, 0))
            t[r["outcome"]] += 1
    for key, t in table.items():
        placed = t["at"] + t["near"] + t["block"] + t["off"]  # the readings that test the placement
        t["n"] = sum(t[o] for o in OUTCOMES)
        t["within_2_lots"] = round((t["at"] + t["near"]) / placed, 2) if placed else None
        t["wrong_place"] = round(t["off"] / placed, 2) if placed else None
    OUT.write_text(json.dumps({"run": RUN, "seed": SEED, "per_stratum": PER, "table": table}, indent=1) + "\n")
    for key in sorted(table):
        t = table[key]
        print(f"{key:<24} n={t['n']:<3} " + " ".join(f"{o}={t[o]}" for o in OUTCOMES)
              + f"  within 2 lots {t['within_2_lots']}  off {t['wrong_place']}")


def self_test() -> None:
    pairs = [((10.0, 20.0), (0.0, 0.0)), ((110.0, 20.0), (50.0, 0.0))]  # 2 px to the metre, north up
    g = fit(pairs, "helmert")
    assert all(math.dist(g(*p), w) < 1e-6 for p, w in pairs)
    assert math.dist(g(10.0, 120.0), (0.0, -50.0)) < 1e-6, "image down must be ground south"
    back = fit([(w, p) for p, w in pairs], "helmert")
    assert math.dist(back(*g(37.0, 81.0)), (37.0, 81.0)) < 1e-6
    corners = [((0.0, 0.0), (0.0, 0.0)), ((4.0, 0.0), (8.0, 0.0)), ((0.0, 4.0), (0.0, -8.0)), ((4.0, 4.0), (8.0, -8.0))]
    assert math.dist(fit(corners, "polynomial")(2.0, 2.0), (4.0, -4.0)) < 1e-6
    square = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert inside(0.5, 0.5, square) and not inside(1.5, 0.5, square)
    print("self-test ok")


if __name__ == "__main__":
    {"fetch": fetch, "sample": sample, "summary": summary, "--self-test": self_test}[sys.argv[1]]()
