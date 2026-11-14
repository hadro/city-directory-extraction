"""
Where the person is standing: the buildings nearest a point, each with every address it has, from
NYC GeoSearch's reverse lookup, and when each went up, from PLUTO. For the address finder's
"Search where I'm standing" button (app.py).

    uv run --with duckdb==2.0.0 python space/here.py 40.78002 -73.97748

GeoSearch's reverse lookup answers the address points nearest a point, at most 40, each with its
building (BIN) and tax lot (BBL) from the city's Property Address Directory, which lists every
address of a building: 9-21 Wall st, 2-6 Broad st and 6 New st are one. A big building can take
all 40 (a Bedford-Stuyvesant block of Macon st took them all), so when an answer holds fewer than
BUILDINGS buildings, four more points OFFSET m away are asked too. A placeholder BIN (1000000 for
Manhattan, 3000000 for Brooklyn) is no building: those addresses group by lot.

The directory also lists other names for an address: an old one (340 Lenox av beside 340 Malcolm
X Blvd, 836 6 Avenue beside Avenue of the Americas), a spelling (Mac Donough, Mc Donough,
Macdonough), a short form (B'way). A name given after the directories' years (CO_NAMES) is
dropped, since no line prints it. Spellings of one street (its words joined, one letter apart)
are one, under the spelling whose street word the directories print most (`count`, which app.py
takes from the finder's word index). Other names at the same number are kept, the commonest first:
649 Classon av is also 649 Union pl, and which one a line used is the lines' to say.

The buildings are ranked by how far the point is from each one's nearest wall, from the city's
building footprints (NYC Open Data, no key): an address point can be far from where a big
building's wall is (at Wall and Broad, 11 Wall st's is 31 m off and 23 New st's 56 m, while
their walls are 8 m and 6 m away). A building with no footprint (a placeholder BIN, a new one)
keeps its address point's distance. The footprints are asked by BIN: their `within_circle` leaves
out a building that reaches past the circle (none within 80 m of Times Square).

PLUTO (NYC Planning's tax lot data, on NYC Open Data, no key) gives the lot's year built, floors,
landmark and historic district. The year is the lot's (the main building's where a lot has
several), and for an old building it is often approximate. A condominium's lot is filed under
another number in PLUTO, so it has none here; the footprint's year (`footprint_year`) is there
for that case. Elsewhere the two agree but for a few (the Stock Exchange: 1901 in PLUTO, 1904
in the footprints), and PLUTO's is the one shown.

The point goes from the page to this server, and from here to GeoSearch; nothing keeps it. A
failure raises (OSError, ValueError, KeyError), so it is not cached.
"""
from __future__ import annotations

import concurrent.futures
import functools
import json
import math
import re
import sys
import time
import urllib.parse

import where
from search import fa

REVERSE = "https://geosearch.planninglabs.nyc/v2/reverse"
PLUTO = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
FOOTPRINTS = "https://data.cityofnewyork.us/resource/5zhs-2jue.json"
BUILDINGS = 6          # buildings offered, nearest first
OFFSET = 35            # metres from the point to the four more points asked, when one is short
# NYC Open Data answers a query it has not seen in ~0.3 s, but about one in three took 3-6 s
# (2026-11-14, any form of the query), and one it has seen in ~0.25 s. So the search does not wait
# long: without footprints by FOOT_WAIT the buildings rank by address point; without PLUTO by
# LOTS_WAIT the lines come first, and app.py asks PLUTO the same query again after (`lots_pending`,
# `lot_bbls`), by then usually answered and cached.
FOOT_WAIT = 2.5       # seconds from asking, both
LOTS_WAIT = 1.5
# Years built that PLUTO fills in where the real one isn't recorded: {year: (Manhattan and
# Brooklyn lots with it, the median of the three years either side)}, every year with 1,000+
# lots and over 4 times its neighbours (PLUTO 26v2, 2026-11-14: `$select=yearbuilt, count(*)`
# `$where=borough in('BK','MN')`, `$group=yearbuilt`). 462 Court st, an older-looking rowhouse
# with no alteration on record, is "1931", like the five beside it; the side-street houses
# behind it are "1899". Only 8,103 lots carry a year before 1880, so 1899 reads as "1899 or
# earlier". The footprints' years are the same as PLUTO's nearly everywhere.
ESTIMATED = {1899: (16745, 595), 1900: (5922, 512), 1901: (13659, 429), 1905: (5104, 448),
             1910: (27048, 586), 1915: (6302, 368), 1920: (33195, 472), 1925: (28786, 1356),
             1930: (29366, 1136), 1931: (17996, 692), 1935: (5926, 239), 1940: (8348, 179),
             1945: (3777, 68), 1950: (5714, 140), 1955: (5285, 202), 1960: (11053, 274),
             1965: (4128, 214), 1970: (2513, 164)}
COVERED = ("Manhattan", "Brooklyn")
# Words of names given to streets after 1922, which no line prints: Avenue of the Americas (6th
# av), Malcolm X Blvd (Lenox av; Brooklyn's Reid av), Adam Clayton Powell Jr Blvd (7th av),
# Frederick Douglass Blvd (8th av), Marcus Garvey Blvd (Sumner av), Duke Ellington Blvd (W 106th),
# Little Brazil St (W 46th), Fashion av (7th av), Martin Luther King Jr Blvd (W 125th). Only
# dropped where the address has another name.
# Canyon of Heroes (lower Broadway), G Abbott Way (W 44th). A name ending in the word "Way" is
# one of these too: the directories' streets were st, av, pl and the like.
CO_NAMES = {"americas", "malcolm", "malcom", "clayton", "douglass", "garvey", "ellington", "brazil",
            "fashion", "luther", "canyon", "heroes", "abbott"}
SPELLED = {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
           "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "eleventh": "11",
           "twelfth": "12"}
TYPES = {"street": "st", "avenue": "av", "place": "pl", "road": "rd", "court": "ct",
         "square": "sq", "terrace": "ter", "alley": "al", "lane": "la", "drive": "dr",
         "boulevard": "blvd"}
DIRS = {"west": "W", "east": "E", "north": "N", "south": "S"}
PLACEHOLDER_BIN = re.compile(r"[1-5]000000")


def nth(n: str) -> str:
    """'76' -> '76th', '1' -> '1st', '112' -> '112th'."""
    k = int(n)
    return n + ("th" if k % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th"))


def directory_form(number: str, street: str) -> str | None:
    """An address as the finder takes it: ('106', 'WEST 76 STREET') -> '106 W 76th st'; ('340A',
    'LENOX AVENUE') -> '340 Lenox av'. None for one it can't: a Queens-style number (106-02) or
    a park's placeholder ('CENTRAL PARK-NEAR FIFTH AVENUE')."""
    m = re.fullmatch(r"(\d+)[A-Z]?", (number or "").strip().upper())
    words = (street or "").replace("-", " ").split()
    if not m or not words or "NEAR" in (w.upper() for w in words):
        return None
    words = ["Broadway" if w.upper() == "B'WAY" else SPELLED.get(w.lower(), w) for w in words]
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i == len(words) - 1 and i > 0 and lw in TYPES:
            out.append(TYPES[lw])
        elif i == 0 and lw in DIRS and len(words) > 1 and words[1].isdigit():
            out.append(DIRS[lw])
        elif lw.isdigit():
            out.append(nth(lw))
        elif lw == "saint":
            out.append("St")
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join([m.group(1), *out])


@functools.lru_cache(maxsize=1024)
def reverse(lat: float, lon: float) -> tuple:
    """GeoSearch's address points nearest (lat, lon), as (borough, housenumber, street, bin, bbl,
    lat, lon). Points with no house number (a street, a neighbourhood) are left out."""
    d = where.fetch(REVERSE + "?" + urllib.parse.urlencode(
        {"point.lat": f"{lat:.6f}", "point.lon": f"{lon:.6f}", "size": 40}))
    out = []
    for f in d.get("features", []):
        p = f["properties"]
        pad = (p.get("addendum") or {}).get("pad") or {}
        if p.get("housenumber") and p.get("street"):
            out.append((p.get("borough"), p["housenumber"], p["street"], pad.get("bin") or "",
                        pad.get("bbl") or "", f["geometry"]["coordinates"][1],
                        f["geometry"]["coordinates"][0]))
    return tuple(out)


def around(lat: float, lon: float) -> list:
    """The address points of `reverse` at the point, and at four points OFFSET m from it when
    that holds fewer than BUILDINGS buildings. The four are asked at once."""
    first = list(reverse(round(lat, 5), round(lon, 5)))
    if len({p[3] or p[4] for p in first}) >= BUILDINGS:
        return first
    dlat = OFFSET / 111_320
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    spots = [(lat + dlat, lon), (lat - dlat, lon), (lat, lon + dlon), (lat, lon - dlon)]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        more = list(pool.map(lambda s: reverse(round(s[0], 5), round(s[1], 5)), spots))
    seen, out = set(), []
    for p in first + [p for answer in more for p in answer]:
        if p[:5] not in seen:
            seen.add(p[:5])
            out.append(p)
    return out


def pluto(bbls: list) -> dict:
    """{bbl: {"year", "floors", "buildings", "landmark", "district", "address"}} for the lots
    PLUTO has, in one request."""
    bbls = [b for b in dict.fromkeys(bbls) if re.fullmatch(r"\d{10}", b)]
    if not bbls:
        return {}
    rows = where.fetch(PLUTO + "?" + urllib.parse.urlencode({
        "$select": "bbl,address,yearbuilt,numfloors,numbldgs,landmark,histdist",
        "$where": f"bbl in({','.join(bbls)})"}))
    out = {}
    for r in rows:
        num = lambda k: int(float(r[k])) if r.get(k) else 0        # noqa: E731
        out[str(int(float(r["bbl"])))] = {
            "year": num("yearbuilt"), "floors": num("numfloors"), "buildings": num("numbldgs"),
            "landmark": r.get("landmark") or "", "district": r.get("histdist") or "",
            "address": r.get("address") or ""}
    return out


def street_key(form: str) -> str:
    """The street of an address, its words joined: '387 Mac Donough st' -> 'macdonough'."""
    return "".join(fa.parse(form)[1])


def same_street(a: str, b: str) -> bool:
    """Two keys spelling one street: a letter apart (mcdonough, macdonough), but a numbered
    street only as itself (w45th is not w46th)."""
    if any(c.isdigit() for c in a + b):
        return a == b
    return fa.lev(a, b, 1) <= 1


def footprints(bins: list) -> dict:
    """{bin: {"year", "geom"}}: each building's footprint (a GeoJSON MultiPolygon) and the year
    the footprints give it (0 for none), in one request."""
    bins = [b for b in dict.fromkeys(bins)
            if re.fullmatch(r"\d{7}", b or "") and not PLACEHOLDER_BIN.fullmatch(b)]
    if not bins:
        return {}
    rows = where.fetch(FOOTPRINTS + "?" + urllib.parse.urlencode({
        "$select": "bin,construction_year,the_geom", "$where": f"bin in({','.join(bins)})",
        "$limit": 1000}))
    out = {}
    for r in rows:
        if r.get("the_geom") and r["bin"] not in out:
            out[r["bin"]] = {"geom": r["the_geom"],
                             "year": int(float(r["construction_year"]))
                             if r.get("construction_year") else 0}
    return out


def wall_metres(lat: float, lon: float, geom: dict) -> float:
    """Metres from the point to a footprint's nearest wall, 0 inside it. Flat over a block's
    distances: x east and y north of the point, in metres."""
    ky = math.radians(1) * 6371000
    kx = ky * math.cos(math.radians(lat))
    coords = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    polys = [[[((x - lon) * kx, (y - lat) * ky) for x, y in ring] for ring in poly]
             for poly in coords]
    edges = lambda rings: (e for r in rings for e in zip(r, r[1:] + r[:1]))   # noqa: E731
    for rings in polys:               # inside: an odd number of edges crossed going east
        if sum((y1 > 0) != (y2 > 0) and x1 + (x2 - x1) * -y1 / (y2 - y1) > 0
               for (x1, y1), (x2, y2) in edges(rings)) % 2:
            return 0.0

    def to_edge(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, -(a[0] * dx + a[1] * dy) / (dx * dx + dy * dy or 1)))
        return math.hypot(a[0] + t * dx, a[1] + t * dy)
    return min(to_edge(a, b) for rings in polys for a, b in edges(rings))


def names(addresses: list, count=None) -> list:
    """A building's addresses as the finder takes them: [(number, street), ...] in, ['106 W 76th
    st', ...] out. CO_NAMES dropped (unless nothing else is left); spellings of one street are
    one, the one `count` (an address -> lines) finds most; other names at a number kept, the
    commonest first. Numbers in the order they first come."""
    forms = list(dict.fromkeys(f for n, s in addresses if (f := directory_form(n, s))))
    plain = [f for f in forms if not CO_NAMES & {w.lower() for w in f.split()}
             and f.split()[-1] != "Way"] or forms
    score = {f: (count(f) if count else 0, -i) for i, f in enumerate(plain)}
    spelling = {}                                 # a street's key -> its commonest spelling
    for f in sorted(plain, key=score.get, reverse=True):
        k = street_key(f)
        if not any(same_street(k, s) for s in spelling):
            spelling[k] = f.split(" ", 1)[1]

    def respelled(f: str) -> str:
        k = street_key(f)
        return f.split()[0] + " " + next(v for s, v in spelling.items() if same_street(k, s))
    return list(dict.fromkeys(map(respelled, plain)))


def nearby(lat: float, lon: float, count=None) -> dict:
    """The buildings nearest the point, nearest first: {"borough": the nearest address's,
    "buildings": [{"key", "bin", "bbl", "borough", "metres", "walls", "addresses", "first",
    "pluto", "footprint_year"}]}, up to BUILDINGS of them, in the boroughs the directories
    cover. `metres` is to the nearest wall where `walls` (there is a footprint), else to the
    nearest address point. `addresses` is every address of the building as the finder takes it,
    `first` the one to search first: PLUTO's address for the lot where it is one of them, else
    the nearest. `count`: see names(). The footprints and PLUTO are asked at once, and either
    failing leaves its part out; PLUTO not answering by LOTS_WAIT sets "lots_pending", with the
    lots asked in "lot_bbls" for app.py to ask again (with_lots)."""
    points = around(lat, lon)
    groups = {}
    for borough, number, street, bin_, bbl, plat, plon in points:
        key = bbl if not bin_ or PLACEHOLDER_BIN.fullmatch(bin_) else bin_
        g = groups.setdefault(key, {"key": key, "bin": bin_, "bbl": bbl, "borough": borough,
                                    "metres": math.inf, "raw": []})
        g["metres"] = min(g["metres"], where.metres(lat, lon, plat, plon))
        g["raw"].append((number, street))
    ranked = sorted(groups.values(), key=lambda g: g["metres"])
    borough = ranked[0]["borough"] if ranked else None
    near = [g for g in ranked if g["borough"] in COVERED]
    lot_bbls = [g["bbl"] for g in near]
    pool = concurrent.futures.ThreadPoolExecutor(2)
    asked = time.monotonic()
    asked_feet = pool.submit(footprints, [g["bin"] for g in near])
    asked_lots = pool.submit(pluto, lot_bbls)
    pool.shutdown(wait=False)                     # a slow answer is left to finish on its own
    feet = answer(asked_feet, FOOT_WAIT) or {}
    lots = answer(asked_lots, max(0.0, asked + LOTS_WAIT - time.monotonic()))
    for g in near:
        foot = feet.get(g["bin"])
        g["walls"] = bool(foot)
        g["footprint_year"] = foot["year"] if foot else 0
        if foot:
            g["metres"] = wall_metres(lat, lon, foot["geom"])
    shown = sorted(near, key=lambda g: g["metres"])[:BUILDINGS]
    out, seen = [], set()
    for g in shown:
        addresses = names(g.pop("raw"), count)
        # a lot's front and rear buildings can share their one address: offered once
        if not addresses or tuple(addresses) in seen:
            continue
        seen.add(tuple(addresses))
        lot = (lots or {}).get(g["bbl"])
        primary = directory_form(*lot["address"].split(" ", 1)) if lot and \
            " " in lot["address"] else None
        first = primary if primary in addresses else addresses[0]
        # the first address's street first, then the others; numbers in order along each
        streets = list(dict.fromkeys(street_key(a) for a in [first, *addresses]))
        addresses.sort(key=lambda a: (a != first, streets.index(street_key(a)), int(a.split()[0])))
        out.append(dict(g, metres=round(g["metres"]), addresses=addresses, first=first,
                        pluto=lot))
    return {"borough": borough, "buildings": out, "lots_pending": lots is None and bool(out),
            "lot_bbls": lot_bbls}


def answer(asked: concurrent.futures.Future, wait: float):
    """A request's answer within `wait` seconds; None if it failed or is still out."""
    try:
        return asked.result(timeout=wait)
    except (concurrent.futures.TimeoutError, OSError, ValueError, KeyError):
        return None


def with_lots(near: dict) -> dict:
    """`near` with PLUTO's answer filled in, where it was still out (lots_pending): the same
    query again, which NYC Open Data has usually answered and cached by then. Changed in place."""
    if near.get("lots_pending"):
        try:
            lots = pluto(near["lot_bbls"])
        except (OSError, ValueError, KeyError):
            lots = {}
        for b in near["buildings"]:
            b["pluto"] = lots.get(b["bbl"])
        near["lots_pending"] = False
    return near


if __name__ == "__main__":
    near = nearby(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(near, indent=1))
    print("\n".join(f'{b["metres"]:>4} m {"to its wall" if b["walls"] else "to its address"}: '
                    f'{b["first"]} (+{len(b["addresses"]) - 1}), PLUTO '
                    f'{(b["pluto"] or {}).get("year")}, footprint {b["footprint_year"]}'
                    for b in near["buildings"]), file=sys.stderr)
