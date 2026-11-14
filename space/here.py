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

PLUTO (NYC Planning's tax lot data, on NYC Open Data, no key) gives the lot's year built, floors,
landmark and historic district. The year is the lot's (the main building's where a lot has
several), and for an old building it is often approximate. A condominium's lot is filed under
another number in PLUTO, so it has none here.

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
import urllib.parse

import where
from search import fa

REVERSE = "https://geosearch.planninglabs.nyc/v2/reverse"
PLUTO = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
BUILDINGS = 6          # buildings offered, nearest first
OFFSET = 35            # metres from the point to the four more points asked, when one is short
COVERED = ("Manhattan", "Brooklyn")
# Words of names given to streets after 1922, which no line prints: Avenue of the Americas (6th
# av), Malcolm X Blvd (Lenox av; Brooklyn's Reid av), Adam Clayton Powell Jr Blvd (7th av),
# Frederick Douglass Blvd (8th av), Marcus Garvey Blvd (Sumner av), Duke Ellington Blvd (W 106th),
# Little Brazil St (W 46th), Fashion av (7th av), Martin Luther King Jr Blvd (W 125th). Only
# dropped where the address has another name.
# Canyon of Heroes (lower Broadway).
CO_NAMES = {"americas", "malcolm", "malcom", "clayton", "douglass", "garvey", "ellington", "brazil",
            "fashion", "luther", "canyon", "heroes"}
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


def names(addresses: list, count=None) -> list:
    """A building's addresses as the finder takes them: [(number, street), ...] in, ['106 W 76th
    st', ...] out. CO_NAMES dropped (unless nothing else is left); spellings of one street are
    one, the one `count` (an address -> lines) finds most; other names at a number kept, the
    commonest first. Numbers in the order they first come."""
    forms = list(dict.fromkeys(f for n, s in addresses if (f := directory_form(n, s))))
    plain = [f for f in forms if not CO_NAMES & {w.lower() for w in f.split()}] or forms
    score = {f: (count(f) if count else 0, -i) for i, f in enumerate(plain)}
    spelling = {}                                 # a street's key -> its commonest spelling
    for f in sorted(plain, key=score.get, reverse=True):
        k = street_key(f)
        if not any(fa.lev(k, s, 1) <= 1 for s in spelling):
            spelling[k] = f.split(" ", 1)[1]

    def respelled(f: str) -> str:
        k = street_key(f)
        return f.split()[0] + " " + next(v for s, v in spelling.items() if fa.lev(k, s, 1) <= 1)
    return list(dict.fromkeys(map(respelled, plain)))


def nearby(lat: float, lon: float, count=None) -> dict:
    """The buildings nearest the point, nearest first: {"borough": the nearest address's,
    "buildings": [{"key", "bin", "bbl", "borough", "metres", "addresses", "first", "pluto"}]},
    up to BUILDINGS of them, in the boroughs the directories cover. `addresses` is every address
    of the building as the finder takes it, `first` the one to search first: PLUTO's address
    for the lot where it is one of them, else the nearest. `count`: see names()."""
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
    shown = [g for g in ranked if g["borough"] in COVERED][:BUILDINGS]
    try:
        lots = pluto([g["bbl"] for g in shown])
    except (OSError, ValueError, KeyError):
        lots = {}
    out, seen = [], set()
    for g in shown:
        addresses = names(g.pop("raw"), count)
        # a lot's front and rear buildings can share their one address: offered once
        if not addresses or tuple(addresses) in seen:
            continue
        seen.add(tuple(addresses))
        lot = lots.get(g["bbl"])
        primary = directory_form(*lot["address"].split(" ", 1)) if lot and \
            " " in lot["address"] else None
        first = primary if primary in addresses else addresses[0]
        # the first address's street first, then the others; numbers in order along each
        streets = list(dict.fromkeys(street_key(a) for a in [first, *addresses]))
        addresses.sort(key=lambda a: (a != first, streets.index(street_key(a)), int(a.split()[0])))
        out.append(dict(g, metres=round(g["metres"]), addresses=addresses, first=first,
                        pluto=lot))
    return {"borough": borough, "buildings": out}


if __name__ == "__main__":
    near = nearby(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(near, indent=1))
