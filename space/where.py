"""
Where an address searched for is today: NYC GeoSearch's point for it in each borough the lines
put it in, for an OpenStreetMap embed, and a Google Street View link where Google has a panorama
of it.

    uv run --with duckdb==2.0.0 python space/where.py "155 Franklin av" Brooklyn

A point only where GeoSearch has ONE street today with the number, the borough and the street's
name and type: the type asked, or with none asked, the one the lines found there print most
("155 Franklin" is Franklin av in Brooklyn's lines, and Brooklyn has a Franklin st too).
GeoSearch's own match_type is not trusted: it says "fallback" of exact answers, and asked for
"45 Fulton Street, Brooklyn" it answers 45 Fulton in Manhattan and 415 Fulton in Brooklyn. A
numbered street asked without a direction is asked both ways, so 131 110th is no pin while
Manhattan has both an East and a West one.

Street View: the metadata request, which costs nothing, says whether Google has an outdoor
panorama of its own within RADIUS m of the point; the link opens it turned toward the address.
Only with GOOGLE_MAPS_API_KEY set (on the Space, a secret: the key never reaches the page).
Linked, not embedded: Google's Maps Platform terms restrict its content beside a non-Google map.
"""
from __future__ import annotations

import collections
import functools
import json
import math
import os
import sys
import urllib.parse
import urllib.request

from search import fa

GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
STREET_VIEW = "https://maps.googleapis.com/maps/api/streetview/metadata"
KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
RADIUS = 50            # metres from the point to the panorama's camera
HEADERS = {"User-Agent": "city-directory-address-finder"}
# fa.street_type's types, spelled out for GeoSearch ("road" and "court" come back as ro, co)
KINDS = {"st": "Street", "av": "Avenue", "pl": "Place", "rd": "Road", "ro": "Road", "ct": "Court",
         "co": "Court", "sq": "Square", "te": "Terrace", "al": "Alley", "la": "Lane", "dr": "Drive",
         "bl": "Boulevard"}
DIRS = {"w": "West", "e": "East", "n": "North", "s": "South"}
MAPPED = ("Manhattan", "Brooklyn")       # "Elsewhere" is anywhere from Jersey City to London


def fetch(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=8) as r:
        return json.load(r)


@functools.lru_cache(maxsize=4096)
def geosearch(text: str) -> tuple:
    """GeoSearch's answers as (borough, housenumber, street, label, lat, lon). A failure raises,
    so it is not cached."""
    d = fetch(GEOSEARCH + "?" + urllib.parse.urlencode({"text": text, "size": 10}))
    return tuple((p.get("borough"), p.get("housenumber"), p.get("street") or "", p.get("label"),
                  f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])
                 for f in d.get("features", []) for p in [f["properties"]])


def street_of(name: str) -> tuple:
    """(direction, name, type) of a street as GeoSearch spells it: 'WEST 110 STREET' ->
    ('w', '110', 'st'); 'DEKALB AVENUE' -> ('', 'dekalb', 'av')."""
    words = name.lower().split()
    kind = fa.street_type(words[-1]) if len(words) > 1 else ""
    if kind:
        words = words[:-1]
    direction = ""
    if len(words) > 1 and words[0] in fa.DIRECTIONS:
        direction, words = fa.DIRECTIONS[words[0]], words[1:]
    return direction, "".join(c for c in "".join(words) if c.isalnum()), kind


def same_name(asked: str, today: str) -> bool:
    """110th is 110; any other street by its letters, joined: De Kalb is DEKALB."""
    return fa.ordinal(asked) == fa.ordinal(today) if fa.ordinal(asked) else asked == today


def today(number: str, words: list, kind: str, place: str) -> dict:
    """The address in `place` today: {"label", "lat", "lon"} for a pin, else {"streets"}: the
    streets that might be it (none, or several). Raises if GeoSearch does not answer."""
    direction, street = fa.split_direction(words)
    asked = "".join(street)
    both_ways = not direction and fa.ordinal(asked) and place == "Manhattan"
    queries = [" ".join(x for x in (number, DIRS.get(d, ""), *street, KINDS.get(kind, "")) if x)
               + f", {place}" for d in (("e", "w") if both_ways else (direction,))]
    found = {}
    for q in queries:
        for borough, n, name, label, lat, lon in geosearch(q):
            d, s, k = street_of(name)
            if (borough == place and n == number and same_name(asked, s)
                    and (not direction or d == direction) and (not kind or k == kind)):
                found.setdefault((d, s, k), dict(label=label, lat=lat, lon=lon))
    if len(found) == 1:
        return next(iter(found.values()))
    return {"streets": [f["label"] for f in found.values()]}


def metres(lat1, lon1, lat2, lon2) -> float:
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6371000 * math.hypot(x, math.radians(lat2 - lat1))


def bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2)
                                   - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360


@functools.lru_cache(maxsize=4096)
def street_view(lat: float, lon: float) -> dict | None:
    """{"url", "date", "metres"} of Google's own outdoor panorama within RADIUS m, turned toward
    the point; None without one, or without a key. A user's photosphere is not Google's and its
    camera may be anywhere, so it doesn't count."""
    if not KEY:
        return None
    m = fetch(STREET_VIEW + "?" + urllib.parse.urlencode(
        {"location": f"{lat},{lon}", "radius": RADIUS, "source": "outdoor", "key": KEY}))
    if m.get("status") != "OK" or "Google" not in m.get("copyright", ""):
        return None
    plat, plon = m["location"]["lat"], m["location"]["lng"]
    d = metres(plat, plon, lat, lon)
    if d > RADIUS:
        return None
    url = "https://www.google.com/maps/@?" + urllib.parse.urlencode(
        {"api": 1, "map_action": "pano", "pano": m["pano_id"], "viewpoint": f"{plat},{plon}",
         "heading": round(bearing(plat, plon, lat, lon))})
    return {"url": url, "date": m.get("date", ""), "metres": round(d)}


def line_kind(h: dict) -> str:
    """The street type a hit's line prints after the street it matched: 'av' of
    '155 Franklin av'; '' for none. `how` is the number and the street as the line has them."""
    street = h["how"].split()[1:]
    for f in fa.FIELDS:
        toks = (h.get(f) or "").split()
        for i in range(len(toks) - len(street)):
            if toks[i:i + len(street)] == street:
                return fa.street_type(toks[i + len(street)])
    return ""


def locate(res: dict, places: list) -> list:
    """For each borough the address is found in (and shown): {"place", "query", ...today()'s
    answer, "street_view"}, or {"place", "query", "error"} when GeoSearch did not answer. The
    street type is the one asked, else the commonest the lines print, else any."""
    number, words, kind = fa.parse(res["address"])
    out = []
    for place in MAPPED:
        hits = [h for h in res["hits"] if h["place"] == place and place in places
                and h["grade"] in ("exact", "street", "number")
                and not h["flag"].startswith("OTHER STREET")]
        if not hits:
            continue
        k = kind
        if not k:
            seen = collections.Counter(filter(None, map(line_kind, hits))).most_common(2)
            if seen and (len(seen) == 1 or seen[0][1] > seen[1][1]):
                k = seen[0][0]
        direction, street = fa.split_direction(words)
        query = " ".join(x[:1].upper() + x[1:] for x in (
            number, DIRS.get(direction, ""), *street, KINDS.get(k, "")) if x)
        try:
            spot = today(number, words, k, place)
        except (OSError, ValueError, KeyError) as err:
            out.append({"place": place, "query": query, "error": str(err)})
            continue
        if "lat" in spot:
            try:
                spot["street_view"] = street_view(spot["lat"], spot["lon"])
            except (OSError, ValueError, KeyError):
                spot["street_view"] = None
        out.append(dict(spot, place=place, query=query))
    return out


if __name__ == "__main__":
    number, words, kind = fa.parse(sys.argv[1])
    spot = today(number, words, kind, sys.argv[2])
    print(spot)
    if "lat" in spot:
        print(street_view(spot["lat"], spot["lon"]) if KEY else "no GOOGLE_MAPS_API_KEY")
