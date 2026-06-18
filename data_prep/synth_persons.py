# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Synthetic city-directory PERSON entries for two real "dialects" of US directory:

  * tulsa : 1921 Polk-Hoffhine Tulsa City Directory  (eval: ../tulsa-city-directories)
  * nyc   : Doggett/Trow New York City directories 1850-1890
            (eval: NYU "NYC Directories Extracted Persons", archive.nyu.edu/handle/2451/61521)

Generates (raw_line -> structured_record) training pairs. `--profile {tulsa,nyc,mix}`
selects which dialect(s) to emit; `mix` (default) interleaves both so one fine-tune
generalises and BOTH gold benchmarks are in-distribution.

Union schema (one fixed column set covering both dialects; empty where a dialect
doesn't use a field):
    name, is_business, spouse_name, race_designation, occupation_role,
    employer, address, home_address

Per-dialect field use
---------------------
  tulsa: name, is_business, spouse_name "(Mary S)"/"(wid John)", race_designation "(c)",
         occupation_role (abbrev), employer (oil-town cos), address = the single
         residency-coded address ("r/b/rms/rear/h ..."); home_address empty.
  nyc:   name (surname-first), occupation_role, address = the primary/printed address;
         home_address = a SEPARATE "h."-marked home (only when the entry lists two
         addresses -- most list one). race_designation "col'd"/"colored"/"col" (rare),
         widow as spouse_name "wid John"; employer empty (NYC lumps employer into
         the occupation list).

Why grounded this way (sources):
  * Tulsa residency codes + grid + employer + "(c)": the directory's ABBREVIATIONS page
    (tulsa-city-directories/1921.html) and ~48k rows of 1921.csv. Distributions measured:
    address-prefix r/b/rms ~39/20/18%, spouse ~36%, employer ~31%, "(c)" ~8%, business ~6%.
  * NYC format/markers: NYU "Detailed Guide" -- entries alphabetical by surname; "in many,
    if most cases, the single address listed encompassed both place of work and home";
    home flagged "h."; "colored" as col'd/colored/col (10,277 of 7.9M ~ 0.13%); "widow"
    as wid/widow (651,158 ~ 8.2%). Example raw line:
    "Chandler Job . Foster, varieties, 81 Maiden lane, h. 81 Avy."

Design notes
------------
* One entry == one line. OCR noise is applied to the INPUT line only; target stays clean.
* Addresses are stored AS PRINTED (verbatim) per the NER-prompt convention: Tulsa keeps its
  r/b/rms prefix in the value; NYC strips the "h." label (it's a marker, not part of the
  address) -- matching how each gold set stores them, so eval comparisons line up.
* Zero third-party deps; runs anywhere (incl. `uv run <url>` and HF Jobs).

Usage
-----
    python3 synth_persons.py --n 100000 --out ../data/synth_train.jsonl --seed 13   # mix
    python3 synth_persons.py --n 8 --preview --profile nyc
    python3 synth_persons.py --n 8 --preview --profile tulsa --target yaml --noise 0
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import re
import sys
from typing import Optional

# ======================================================================================
# Shared name pools
# ======================================================================================

SURNAMES = [
    "Smith", "Brown", "Williams", "Johnson", "Jones", "Miller", "Davis", "Wilson",
    "Moore", "Taylor", "Clark", "Hall", "Allen", "Young", "King", "Wright", "Adams",
    "Murphy", "Kelly", "O'Brien", "Ryan", "Walsh", "Sullivan", "Doyle", "Reilly",
    "Gallagher", "Byrne", "McMahon", "Donnelly", "McCarthy", "Fitzgerald",
    "Schmidt", "Meyer", "Weber", "Hoffman", "Wagner", "Klein", "Becker", "Bauer",
    "Cohen", "Levy", "Campbell", "Robinson", "Jackson", "Washington", "Carver",
    "Stradford", "Gurley", "Goodwin", "Franklin", "Holloway", "Aaronson", "Carter",
]
GIVEN_M = [
    "John", "William", "James", "Charles", "George", "Henry", "Patrick", "Michael",
    "Thomas", "Edward", "Frederick", "Joseph", "Samuel", "Frank", "Jacob", "Peter",
    "Daniel", "Robert", "Cornelius", "Dennis", "Bernard", "Hugh", "Owen", "Walter",
    "Earl", "Lester", "Leonard", "Otis", "Clarence", "Roy", "Ernest",
]
GIVEN_F = [
    "Mary", "Margaret", "Catherine", "Anna", "Elizabeth", "Bridget", "Sarah", "Ellen",
    "Hannah", "Julia", "Emma", "Jane", "Honora", "Catharine", "Faye", "Carrie", "Ada",
    "Fannie", "Vivian", "Katie", "Pearl", "Hattie", "Bessie", "Nettie", "Lula",
]
GIVEN_ABBREV = {
    "William": "Wm", "Charles": "Chas", "James": "Jas", "John": "Jno", "George": "Geo",
    "Samuel": "Saml", "Joseph": "Jos", "Robert": "Robt", "Thomas": "Thos",
    "Frederick": "Fredk", "Daniel": "Danl", "Patrick": "Patk", "Cornelius": "Cornls",
    "Margaret": "Margt", "Catherine": "Cath", "Elizabeth": "Eliza", "Benjamin": "Benj",
    "Richard": "Richd", "Edward": "Edwd", "Alexander": "Alexr", "Theodore": "Theo",
    "Nicholas": "Nichs", "Augustus": "Augs", "Christopher": "Chris",
}

# Surname pool = census variety (data_prep/fetch_names.py) + real names harvested from the target
# directories (data_prep/harvest_names.py), merged:
#   * census `surnames.tsv` is TEMPERED (count**0.3) so common names stay common but the long tail
#     is well represented -> the model learns to COPY arbitrary surnames, not regularise them to the
#     handful it saw (the biggest measured error).
#   * `surnames_harvested.tsv` (authentic era/place names) is BOOSTED so the synthetic distribution
#     leans real (fixes census anachronisms like "Woldemariam" in 1855) while keeping census variety.
# Falls back to the small inline SURNAMES if neither file is present.
_NAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "names")
HARVEST_BOOST = 8.0


def _load_surname_pool():
    weight: dict = {}
    census = os.path.join(_NAMES_DIR, "surnames.tsv")
    try:
        with open(census, encoding="utf-8") as fh:
            for ln in fh:
                n, w = ln.rstrip("\n").split("\t")
                weight[n] = int(w) ** 0.3                  # temper toward variety
    except (FileNotFoundError, ValueError):
        pass
    harvested = os.path.join(_NAMES_DIR, "surnames_harvested.tsv")
    if os.path.exists(harvested):
        for ln in open(harvested, encoding="utf-8"):
            n, w = ln.rstrip("\n").split("\t")
            weight[n] = weight.get(n, 0.0) + HARVEST_BOOST * int(w) ** 0.5   # lean real
    if not weight:
        return None, None
    names = list(weight)
    return names, list(itertools.accumulate(weight[n] for n in names))


_SUR_POOL, _SUR_CUM = _load_surname_pool()


def _surname(rng) -> str:
    if _SUR_POOL:
        return rng.choices(_SUR_POOL, cum_weights=_SUR_CUM, k=1)[0]
    return rng.choice(SURNAMES)                     # fallback: small inline pool


def _wchoice(rng, items):
    vals = [v for v, _ in items]
    wts = [w for _, w in items]
    return rng.choices(vals, weights=wts, k=1)[0]


def _ordinal(n: int) -> str:
    """19th/20th-c. print style: 1st, 2d, 3d, 4th ... 22d, 23d (NOT 2nd/3rd)."""
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "d", 3: "d"}.get(n % 10, "th")
    return f"{n}{suf}"


def _given(rng, female: bool, abbrev_p: float = 0.25) -> str:
    g = rng.choice(GIVEN_F if female else GIVEN_M)
    if rng.random() < abbrev_p and g in GIVEN_ABBREV:
        g = GIVEN_ABBREV[g]
    return g

# ======================================================================================
# Tulsa 1921 dialect
# ======================================================================================

TUL_OCC = [
    ("clk", 34), ("lab", 27), ("carp", 11), ("stenogr", 10), ("salsn", 9), ("mech", 7),
    ("helper", 7), ("maid", 6), ("bkpr", 6), ("student", 6), ("tchr", 6), ("driller", 5),
    ("mngr", 5), ("porter", 4), ("chauffeur", 4), ("oils", 4), ("opr", 4), ("driver", 4),
    ("contr", 3), ("foreman", 3), ("painter", 3), ("waiter", 3), ("mach", 3), ("grocer", 3),
    ("barber", 3), ("cook", 3), ("acct", 2), ("eng", 2), ("tmstr", 2), ("janitor", 2),
    ("electr", 2), ("supt", 2), ("cashr", 2), ("nurse", 2), ("agt", 2), ("messr", 1),
    ("propr", 2), ("vet", 1), ("plmbr", 1), ("dom", 1), ("real est", 1), ("ins agt", 1),
]
TUL_EMP_LIKELY = {
    "clk", "lab", "salsn", "stenogr", "bkpr", "mech", "driller", "opr", "chauffeur",
    "foreman", "mach", "acct", "eng", "electr", "supt", "cashr", "tchr", "nurse",
    "porter", "waiter", "cook", "maid", "janitor", "tmstr", "helper", "driver", "agt",
    "mngr", "messr", "oils", "dom",
}
TUL_SERVICE_OCC = ["lab", "maid", "porter", "waiter", "cook", "janitor", "chauffeur",
                   "barber", "helper", "dom", "driver", "tmstr"]
TUL_EMPLOYERS = [
    "S W Bell Tel Co", "Cosden & Co", "Carter Oil Co", "Sinclair Oil & G Co", "Texas Co",
    "Pierce Oil Corp", "Gypsy Oil Co", "Halliburton-Abbott Co", "Hotel Tulsa",
    "Sinclair P L Co", "Kerr Glass Mnfg Co", "Frisco Ry", "Gulf P L Co", "Oil Well Sup Co",
    "Exch Natl Bank", "Mid-Co Pet Co", "Tulsa St Ry Co", "Uni of Tulsa", "St L & S F Ry",
    "Prairie Pipe Line Co", "Pure Oil Co", "Longfellow School", "P O",
]
TUL_STREETS = [
    "Boston", "Cheyenne", "Frisco", "Baltimore", "Carson", "Owasso", "Gillette", "Birch",
    "Haskell", "Brady", "Boulder", "Quanah", "Peoria", "Utica", "Main", "Denver", "Elgin",
    "Cincinnati", "Detroit", "Kenosha", "Lansing", "Norfolk", "Madison", "Trenton",
    "Cameron", "Easton", "Pine", "Oak", "Xanthus", "Yorktown", "Atlanta",
]
TUL_GREENWOOD = ["Greenwood", "Detroit", "Cincinnati", "Hartford", "Frankfort", "Elgin",
                 "Archer", "Latimer", "Marshall", "Independence", "King", "Easton",
                 "Cameron", "Boston"]
TUL_DIRECTIONS = ["N", "S", "E", "W"]
TUL_STYPES = [("av", 60), ("", 28), ("boul", 4), ("pl", 4), ("ter", 2), ("ct", 2)]
TUL_BUILDINGS = ["Kennedy Bldg", "Mayo Bldg", "Hayward Bldg", "Cosden Bldg", "Daniel Bldg",
                 "Wright Bldg", "Unity Bldg", "McBirney Bldg", "Hunt Bldg", "Atlas Bldg"]
TUL_HOTELS = ["Drexel Hotel", "Hotel Tulsa", "Alvin Hotel", "Bliss Hotel", "St James Hotel"]
TUL_SUBURBS = ["Sand Spgs", "Red Fork", "Dawson", "Garden City", "W Tulsa"]
TUL_BIZ_CATEGORY = ["lawyers", "physicians", "druggists", "grocers", "real est",
                    "contractors", "oil well supplies", "dry goods", "undertakers",
                    "barbers", "tailors", "confectionery", "printers", "blacksmiths"]
TUL_BIZ_SUFFIX = ["& Co", "Bros", "& Son", "Co", "& Sons"]


def _tul_street(rng, greenwood=False) -> str:
    direction = (rng.choice(TUL_DIRECTIONS) + " ") if rng.random() < 0.74 else ""
    if rng.random() < 0.20:
        return f"{direction}{_ordinal(rng.randint(1, 31))}"
    name = rng.choice(TUL_GREENWOOD if greenwood else TUL_STREETS)
    stype = _wchoice(rng, TUL_STYPES)
    return f"{direction}{name}{(' ' + stype) if stype else ''}".strip()


def _tul_address(rng, greenwood=False, rear_boost=False) -> str:
    prefix = _wchoice(rng, [("r", 39), ("b", 20), ("rms", 18), ("", 13), ("h", 4),
                            ("rear", 12 if rear_boost else 3)])
    roll = rng.random()
    if roll < 0.05 and prefix in ("rms", "b", ""):
        body = rng.choice(TUL_HOTELS)
    elif roll < 0.09:
        body = f"{rng.randint(1, 900)} {rng.choice(TUL_BUILDINGS)}"
    elif roll < 0.11:
        body = f"{_tul_street(rng, greenwood)}, {rng.choice('ns')} {rng.choice('ew')} cor {_ordinal(rng.randint(1, 12))}"
    else:
        body = f"{rng.randint(1, 1900)} {_tul_street(rng, greenwood)}"
    addr = f"{prefix} {body}".strip()
    if rng.random() < 0.045:
        addr += f", {rng.choice(TUL_SUBURBS)}"
    return addr


def _tul_name(rng, female: bool) -> str:
    surname = _surname(rng)
    title = ""
    if female and rng.random() < 0.20:
        title = rng.choice(["Mrs", "Miss"]) + " "
    elif not female and rng.random() < 0.04:
        title = rng.choice(["Rev", "Dr", "Capt"]) + " "
    mid = f" {rng.choice('ABCDEFGHJLMRSTW')}" if rng.random() < 0.45 else ""
    return f"{surname} {title}{_given(rng, female)}{mid}"


def make_tulsa(rng) -> dict:
    if rng.random() < 0.06:
        return _tul_business(rng)
    female = rng.random() < 0.30
    race = "(c)" if rng.random() < 0.085 else ""
    greenwood = race == "(c)" and rng.random() < 0.6
    if rng.random() < 0.27:
        occ = ""
    elif race == "(c)" and rng.random() < 0.7:
        occ = rng.choice(TUL_SERVICE_OCC)
    else:
        occ = _wchoice(rng, TUL_OCC)
    emp = ""
    if occ:
        p = 0.55 if occ in TUL_EMP_LIKELY else 0.10
        if rng.random() < p:
            emp = rng.choice(TUL_EMPLOYERS) if rng.random() < 0.75 else \
                f"{_surname(rng)} {rng.choice(['Oil Co', '& Co', 'Drug Co', 'Bros'])}"
    spouse = ""
    if not female and rng.random() < 0.45:
        spouse = _given(rng, True, abbrev_p=0) + (f" {rng.choice('ABEHJLMRS')}" if rng.random() < 0.25 else "")
    elif female and rng.random() < 0.30:
        spouse = "wid " + rng.choice(GIVEN_M)
    rec = {
        "name": _tul_name(rng, female), "is_business": False, "spouse_name": spouse,
        "race_designation": race, "occupation_role": occ, "employer": emp,
        "address": _tul_address(rng, greenwood, rear_boost=greenwood), "home_address": "",
    }
    return _finish(rng, rec, "tulsa", "1921")


def _tul_business(rng) -> dict:
    n = _surname(rng).upper()
    roll = rng.random()
    if roll < 0.4:
        name = f"{n} {_surname(rng).upper()} {rng.choice(TUL_BIZ_SUFFIX).upper()}"
    elif roll < 0.7:
        name = f"{n} {rng.choice(TUL_BIZ_SUFFIX).upper()}"
    else:
        name = f"{n} {rng.choice(['DRUG', 'OIL', 'GROCERY', 'MOTOR', 'REALTY']).upper()} CO"
    race = "(c)" if rng.random() < 0.05 else ""
    rec = {
        "name": name, "is_business": True, "spouse_name": "", "race_designation": race,
        "occupation_role": rng.choice(TUL_BIZ_CATEGORY) if rng.random() < 0.7 else "",
        "employer": "", "address": _tul_address(rng, greenwood=(race == "(c)")),
        "home_address": "",
    }
    return _finish(rng, rec, "tulsa", "1921")


def render_tulsa(rng, rec) -> str:
    head = rec["name"]
    if rec["race_designation"]:
        head += f" {rec['race_designation']}"
    if rec["spouse_name"]:
        head += f" ({rec['spouse_name']})"
    segs = [head]
    mid = rec["occupation_role"]
    if rec["employer"]:
        mid = f"{mid} {rec['employer']}".strip()
    if mid:
        segs.append(mid)
    if rec["address"]:
        segs.append(rec["address"])
    line = ", ".join(segs)
    return line + ("." if rng.random() < 0.5 else "")

# ======================================================================================
# NYC (Doggett/Trow) dialect, 1850-1890
# ======================================================================================

NYC_OCC = [
    ("clerk", 30), ("laborer", 26), ("carpenter", 10), ("mason", 7), ("tailor", 6),
    ("shoemaker", 6), ("grocer", 6), ("painter", 5), ("cartman", 5), ("porter", 5),
    ("mariner", 4), ("baker", 4), ("butcher", 4), ("machinist", 4), ("printer", 3),
    ("blacksmith", 3), ("smith", 3), ("merchant", 3), ("segars", 3), ("liquors", 3),
    ("milliner", 3), ("dressmaker", 3), ("seamstress", 3), ("washer", 3), ("nurse", 2),
    ("cooper", 2), ("plumber", 2), ("varnisher", 2), ("gilder", 2), ("hatter", 2),
    ("jeweler", 2), ("cabinetmaker", 2), ("weaver", 2), ("peddler", 2), ("waiter", 2),
    ("driver", 2), ("watchman", 2), ("moulder", 2), ("stonecutter", 1), ("upholsterer", 1),
    ("physician", 1), ("lawyer", 1), ("broker", 1), ("bookkeeper", 1), ("engineer", 1),
    ("saloon", 1), ("laundress", 1), ("domestic", 1), ("sexton", 1),
]
# occupations women were typically listed under in mid/late-19th-c. NYC directories
NYC_FEMALE_OCC = ["dressmaker", "milliner", "seamstress", "washer", "nurse", "domestic",
                  "laundress", "tailoress", "boarding", "teacher", "cook", "fancygoods"]
NYC_STREETS = [
    "Broadway", "Bowery", "Wall", "Pearl", "Water", "Cherry", "Mott", "Mulberry",
    "Hester", "Bleecker", "Hudson", "Greenwich", "Canal", "Grand", "Houston", "Spring",
    "Prince", "Chambers", "Fulton", "Nassau", "William", "Gold", "Front", "South",
    "Rivington", "Delancey", "Madison", "Henry", "Monroe", "Division", "Forsyth", "Allen",
    "Orchard", "Ludlow", "Essex", "Norfolk", "Suffolk", "Clinton", "Attorney", "Cortlandt",
    "Dey", "Liberty", "Cedar", "Pine", "Beaver", "Vesey", "Barclay", "Murray", "Warren",
    "Reade", "Duane", "Worth", "Leonard", "Franklin", "Walker", "Lispenard", "Catharine",
    "Market", "Pike", "Rutgers", "Jefferson", "Montgomery", "Gouverneur", "Roosevelt",
]
NYC_STYPES = [("st", 30), ("", 40), ("av", 14), ("lane", 5), ("pl", 4), ("slip", 3),
              ("sq", 2), ("ter", 2)]
NYC_YEARS = list(range(1850, 1890))


def _nyc_street(rng) -> str:
    roll = rng.random()
    if roll < 0.16:                                   # numbered avenue
        return f"{_ordinal(rng.randint(1, 12))} av" if rng.random() < 0.6 else f"av {rng.choice('ABCD')}"
    if roll < 0.34:                                   # numbered street
        return f"{_ordinal(rng.randint(1, 50))} st"
    name = rng.choice(NYC_STREETS)
    stype = _wchoice(rng, NYC_STYPES)
    # "Avy." abbreviation occasionally stands in for avenue
    if stype == "av" and rng.random() < 0.3:
        stype = "Avy."
    return f"{name}{(' ' + stype) if stype else ''}".strip()


def _nyc_address(rng) -> str:
    # forms + abbreviations confirmed against real Hearne's Brooklyn 1852 OCR
    roll = rng.random()
    if roll < 0.05:                                   # rear / foot qualifier
        return f"{rng.choice(['rear', 'ft'])} {rng.randint(1, 600)} {_nyc_street(rng)}"
    if roll < 0.08:                                   # corner ("cor" or single-letter "c")
        return f"{rng.choice(['cor', 'c'])} {rng.choice(NYC_STREETS)} and {rng.choice(NYC_STREETS)}"
    if roll < 0.10:                                   # near ("nr"/"n"), no number
        return f"{rng.choice(['nr', 'n'])} {rng.choice(NYC_STREETS)}"
    if roll < 0.115:                                  # between two streets
        return f"bet {rng.choice(NYC_STREETS)} and {rng.choice(NYC_STREETS)}"
    return f"{rng.randint(1, 600)} {_nyc_street(rng)}"


def _nyc_name(rng, female: bool) -> str:
    surname = _surname(rng)
    mid = f" {rng.choice('ABCDEFGHJLMRSTW')}" if rng.random() < 0.30 else ""
    return f"{surname} {_given(rng, female)}{mid}"


def make_nyc(rng) -> dict:
    if rng.random() < 0.03:                           # occasional business listing
        n = _surname(rng)
        rec = {
            "name": f"{n} & {_surname(rng)}", "is_business": True, "spouse_name": "",
            "race_designation": "", "occupation_role": rng.choice(["merchants", "grocers",
            "tailors", "segars", "liquors", "druggists"]), "employer": "",
            "address": _nyc_address(rng), "home_address": "",
        }
        return _finish(rng, rec, "nyc", _nyc_year(rng))

    female = rng.random() < 0.28
    widow = female and rng.random() < 0.30            # ~8% of all entries
    # "colored" marker is rare in NYC directories (~0.13% in NYU); keep low but learnable
    race = rng.choice(["col'd", "colored", "col"]) if rng.random() < 0.006 else ""

    if widow:
        spouse = "wid " + rng.choice(GIVEN_M)
        occ = "" if rng.random() < 0.6 else rng.choice(["dressmaker", "washer", "nurse",
              "milliner", "seamstress", "laundress", "boarding"])
    else:
        spouse = ""
        if rng.random() < 0.15:
            occ = ""
        elif female and rng.random() < 0.75:
            occ = rng.choice(NYC_FEMALE_OCC)
        else:
            occ = _wchoice(rng, NYC_OCC)

    # most NYC entries list ONE address (combined work+home); a minority add an "h." home
    primary = _nyc_address(rng)
    home = _nyc_address(rng) if rng.random() < 0.24 else ""
    if rng.random() < 0.03:                           # works across the river ("merchant NY h ...")
        primary = "NY"
        home = home or _nyc_address(rng)
    rec = {
        "name": _nyc_name(rng, female), "is_business": False, "spouse_name": spouse,
        "race_designation": race, "occupation_role": occ, "employer": "",
        "address": primary, "home_address": home,
    }
    return _finish(rng, rec, "nyc", _nyc_year(rng))


def _nyc_year(rng) -> str:
    y = rng.choice(NYC_YEARS)
    return f"{y}-{str(y + 1)[-2:]}"


def render_nyc(rng, rec) -> str:
    head = rec["name"]
    if rec["race_designation"]:
        head += f" {rec['race_designation']}"
    parts = [head]
    if rec["spouse_name"]:                            # "wid John"
        parts.append(rec["spouse_name"])
    if rec["occupation_role"]:
        parts.append(rec["occupation_role"])
    line = ", ".join(parts)
    # real directories drop the comma before the address ~40% of the time
    if rec["address"]:
        line += (", " if rng.random() < 0.6 else " ") + rec["address"]
    if rec["home_address"]:                           # home marker varies: h / h. / b / r
        marker = _wchoice(rng, [("h", 40), ("h.", 38), ("b", 14), ("r", 8)])
        line += (", " if rng.random() < 0.5 else " ") + f"{marker} {rec['home_address']}"
    return line + ("." if rng.random() < 0.55 else "")

# ======================================================================================
# Shared finish / dispatch
# ======================================================================================

def _finish(rng, record: dict, dialect: str, year: str) -> dict:
    m = re.search(r"[A-Za-z]{3}", record["name"])
    arange = (m.group(0).upper() if m else record["name"][:3].upper())
    render = render_tulsa if dialect == "tulsa" else render_nyc
    return {
        "raw_line": render(rng, record),
        "context": {"dialect": dialect, "alphabetical_range": arange, "directory_year": year},
        "record": record,
    }


def make_record(rng, profile: str) -> dict:
    if profile == "tulsa":
        return make_tulsa(rng)
    if profile == "nyc":
        return make_nyc(rng)
    return make_tulsa(rng) if rng.random() < 0.5 else make_nyc(rng)   # mix

# ======================================================================================
# OCR noise (INPUT line only)
# ======================================================================================

_NOISE_SUBS = [
    ("m", "rn"), ("rn", "m"), ("l", "1"), ("1", "l"), ("O", "0"), ("0", "O"),
    ("S", "5"), ("B", "8"), ("cl", "d"), ("ii", "n"), ("u", "ii"),
]


def add_noise(rng, line: str, p: float) -> str:
    if p <= 0 or rng.random() > p:
        return line
    out = line
    for _ in range(rng.randint(1, 2)):
        roll = rng.random()
        if roll < 0.5:
            frm, to = rng.choice(_NOISE_SUBS)
            idx = out.find(frm)
            if idx != -1:
                out = out[:idx] + to + out[idx + len(frm):]
        elif roll < 0.7 and "," in out:
            out = out.replace(",", "", 1)
        elif roll < 0.85 and len(out) > 4:
            i = rng.randint(0, len(out) - 2)
            out = out[:i] + out[i + 1] + out[i] + out[i + 2:]
        else:
            i = rng.randint(0, len(out) - 1)
            out = out[:i] + "." + out[i:]
    return out

# ======================================================================================
# Target serialisers (pipe vs YAML -- JSON deliberately avoided for small models)
# ======================================================================================

FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]


def _cell(record, f) -> str:
    v = record.get(f, "")
    if isinstance(v, bool):
        return "True" if v else "False"
    return v


def to_pipe(record) -> str:
    return "|".join(_cell(record, f) for f in FIELDS)


def to_yaml(record) -> str:
    def q(v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "\n".join(f"{f}: {q(_cell(record, f))}" for f in FIELDS)

# ======================================================================================
# CLI
# ======================================================================================

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--out", type=str, default=None, help="output .jsonl (default: stdout)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--noise", type=float, default=0.35, help="per-line OCR-noise probability")
    ap.add_argument("--profile", choices=["tulsa", "nyc", "mix"], default="mix")
    ap.add_argument("--target", choices=["pipe", "yaml"], default="pipe", help="--preview format")
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)

    if args.preview:
        ser = to_pipe if args.target == "pipe" else to_yaml
        for _ in range(args.n):
            ex = make_record(rng, args.profile)
            noisy = add_noise(rng, ex["raw_line"], args.noise)
            print("─" * 78)
            print(f"  INPUT  [{ex['context']['dialect']} {ex['context']['directory_year']} "
                  f"{ex['context']['alphabetical_range']}]: {noisy}")
            for ln in ser(ex["record"]).splitlines():
                print(f"      {ln}")
        return 0

    fh = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        for _ in range(args.n):
            ex = make_record(rng, args.profile)
            ex["raw_line"] = add_noise(rng, ex["raw_line"], args.noise)
            fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    finally:
        if args.out:
            fh.close()
            print(f"wrote {args.n} {args.profile} entries -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
