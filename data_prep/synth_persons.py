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

Context tag (2026-07-19 migration): `context` carries `publisher` + `directory_year`
(`dialect` retired) — the prompt tag is `[publisher=trow; year=1913/14]`. NYC rows draw
an era-consistent publisher (`_nyc_publisher`); the tulsa profile tags `publisher=polk`
(it IS a Polk directory), sharing the tag with late-NYC Polk volumes so the old
"dialects" dissolve into publisher×era. Gold sets tag the volume's real publisher.

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
         addresses -- most list one; the marker is stripped from home_address). A SOLE
         address sometimes KEEPS its residency marker in the record ("h 449 Clason av",
         gold conv #8). race_designation "col'd"/"colored"/"col"/"(co'd)" (rare),
         widow forms vary by era ("widow of John" early -> "wid. John" late; "widow Ann"
         with no "of" = her OWN name -> name, bare marker -> spouse_name); employer
         empty (NYC lumps employer into the occupation list).

NYC era gating (features measured from the 18-volume gold panel + style cards)
------------------------------------------------------------------------------
  Era drawn per-entry: early 1790-1849 / mid 1850-1890 / late 1891-1933 (the panel
  spans 1786-1933; the model conditions on context.directory_year). Era-gated:
  * ditto continuation rows -- Trow "-Michl" (mid), Polk '" Jno H' (late); name keeps
    the mark VERBATIM (conv #12; the #1 measured whole-row-EM killer when absent).
  * ALL-CAPS notable PERSONS (mid, is_business stays False -- conv #14; breaks the
    caps==business correlation the old generator taught).
  * abbreviation periods ("Jno.", "W.", "clk.") + jr/sr/jun./senr. name suffixes,
    kept verbatim in the record (conv #1).
  * raw-line surname comma "Graves, Benjamin, ..." (early-heavy); record drops it (conv #3).
  * early: "corner of X and Y" spelled out, "71 Dey-street" hyphenated suffixes,
    "27 Ann do." street dittos. late: hyphenated outer-borough house nos ("24-12") +
    neighborhood codes (LIC/JH/WNB/...), "clk (Mhn)" commuter tags kept in
    occupation_role (conv #17), Upington space-delimited rendering, "Edw'd" contractions.
  * NO '*' race marker yet -- it flips meaning per volume (Ogden=colored vs
    Hope&Henderson=Eastern District); needs the publisher context tag first.

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
    python3 synth_persons.py --n 100000 --out ../data/synth_train.jsonl --seed 13 --stats  # mix
    python3 synth_persons.py --n 8 --preview --profile nyc
    python3 synth_persons.py --n 8 --preview --profile tulsa --target yaml --noise 0
    # --stats prints a feature-frequency table (stderr, pre-noise) -- the regression
    # check that every gated style feature is present at its intended rate
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
    "Nicholas": "Nichs", "Augustus": "Augs", "Christopher": "Chris", "Michael": "Michl",
}
# late-era Brooklyn (Upington 1900s) apostrophe contractions -- distinct from GIVEN_ABBREV
GIVEN_CONTRACT = {
    "Edward": "Edw'd", "Daniel": "Dan'l", "Andrew": "And'w", "Henry": "H'y",
    "Samuel": "Sam'l", "Margaret": "Marg't", "Catherine": "Cath",
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
    return _finish(rng, rec, "tulsa", "polk", "1921")


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
    return _finish(rng, rec, "tulsa", "polk", "1921")


def render_tulsa(rng, rec, hints=None) -> str:
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
# late-era (Lain/Trow/Upington) compressed occupation forms; record stays verbatim
NYC_OCC_ABBREV = {
    "clerk": "clk", "laborer": "lab", "carpenter": "carp", "machinist": "mach",
    "merchant": "mer", "bookkeeper": "bkpr", "engineer": "eng",
}
# 1920s/30s outer-borough neighborhood codes (Polk Queens/SI; kept verbatim in address)
NYC_NBHD = ["LIC", "JH", "RH", "Rdgwd", "Flush", "WNB", "Stap", "Tomp", "NB"]


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


def _nyc_address(rng, era: str = "mid", ynum: int = 0) -> str:
    # forms + abbreviations confirmed against real Hearne's Brooklyn 1852 OCR + style cards
    roll = rng.random()
    if roll < 0.05:                                   # rear / foot qualifier
        return f"{rng.choice(['rear', 'ft'])} {rng.randint(1, 600)} {_nyc_street(rng)}"
    if roll < 0.08:                                   # corner ("cor" or single-letter "c")
        if era == "early" and rng.random() < 0.5:     # 1790s-1830s spell relations out
            return f"corner of {rng.choice(NYC_STREETS)} and {rng.choice(NYC_STREETS)}"
        return f"{rng.choice(['cor', 'c'])} {rng.choice(NYC_STREETS)} and {rng.choice(NYC_STREETS)}"
    if roll < 0.10:                                   # near ("nr"/"n"), no number
        return f"{rng.choice(['nr', 'n'])} {rng.choice(NYC_STREETS)}"
    if roll < 0.115:                                  # between two streets
        return f"bet {rng.choice(NYC_STREETS)} and {rng.choice(NYC_STREETS)}"
    if roll < 0.15:                                   # bare street relation ("Jay c Myrtle")
        return f"{rng.choice(NYC_STREETS)} {rng.choice(['c', 'n'])} {rng.choice(NYC_STREETS)}"
    num = rng.randint(1, 600)
    if era == "early":
        if rng.random() < 0.20:                       # hyphenated suffix: "71 Dey-street"
            return f"{num} {rng.choice(NYC_STREETS)}-{rng.choice(['street', 'lane'])}"
        if rng.random() < 0.07:                       # street ditto off the row above: "27 Ann do."
            return f"{num} {rng.choice(NYC_STREETS)} do."
        return f"{num} {_nyc_street(rng)}"
    if era == "late" and ynum >= 1915:                # hyphenated nos + nbhd codes are 1920s/30s
        addr_num = f"{num}-{rng.randint(1, 40)}" if rng.random() < 0.28 else str(num)
        addr = f"{addr_num} {_nyc_street(rng)}"       # outer-borough hyphenated house nos
        if rng.random() < 0.30:
            addr += f" {rng.choice(NYC_NBHD)}"
        return addr
    return f"{num} {_nyc_street(rng)}"


def _nyc_given(rng, female: bool, era: str) -> str:
    g = rng.choice(GIVEN_F if female else GIVEN_M)
    if era == "late" and g in GIVEN_CONTRACT and rng.random() < 0.12:
        return GIVEN_CONTRACT[g]                      # Upington-style "Edw'd"
    abbrev_p = {"early": 0.15, "mid": 0.25, "late": 0.35}[era]
    if rng.random() < abbrev_p and g in GIVEN_ABBREV:
        g = GIVEN_ABBREV[g]
        if rng.random() < 0.35:                       # verbatim period stays in the record too
            g += "."
    return g


def _nyc_name(rng, female: bool, era: str) -> str:
    surname = _surname(rng)
    mid = ""
    if rng.random() < 0.30:
        mid = f" {rng.choice('ABCDEFGHJLMRSTW')}"
        if rng.random() < 0.35:
            mid += "."
    suffix = ""
    if not female and rng.random() < 0.035:
        suffix = " " + rng.choice(["jr", "jr.", "Jr", "jun.", "sen.", "senr."])
    return f"{surname} {_nyc_given(rng, female, era)}{mid}{suffix}"


def _nyc_ditto_name(rng, female: bool, era: str) -> str:
    """Surname-repeat continuation row: Trow leading '-' (no space), Polk '\" ' (with space)."""
    given = _nyc_given(rng, female, era)
    mid = f" {rng.choice('ABCDEFGHJLMRSTW')}" if rng.random() < 0.45 else ""
    mark = "-" if (era == "mid" or rng.random() < 0.4) else '" '
    return f"{mark}{given}{mid}"


def _nyc_year_era(rng):
    roll = rng.random()
    if roll < 0.18:
        y, era = rng.randint(1790, 1849), "early"
    elif roll < 0.68:
        y, era = rng.randint(1850, 1890), "mid"
    else:
        y, era = rng.randint(1891, 1933), "late"
    if era == "mid" or (era == "late" and rng.random() < 0.4):
        year = f"{y}/{str(y + 1)[-2:]}"                # slash form matches the gold panel tags
    else:
        year = str(y)
    return year, era, y


def _nyc_publisher(rng, ynum: int) -> str:
    """Era-consistent publisher for the context tag, truthful to the master catalog
    (each gold volume's (publisher, year) pair is reachable). Wave 1 will differentiate
    per-publisher STYLE; this cycle the tag conditions the new publisher-keyed features
    (fused address tokens) and teaches the tag vocabulary itself."""
    if ynum <= 1787:
        return "franks" if rng.random() < 0.5 else "duncan"
    if ynum <= 1796:
        return "duncan"
    if ynum <= 1817:
        return "longworth"
    if ynum <= 1841:                                  # Longworth-era Manhattan + Brooklyn starts
        return _wchoice(rng, [("longworth", 6), ("mercein", 2 if 1818 <= ynum <= 1826 else 0),
                              ("ogden", 2 if ynum >= 1839 else 0)])
    if ynum <= 1851:
        return _wchoice(rng, [("doggett", 7), ("rode", 3 if ynum >= 1850 else 0)])
    if ynum <= 1861:                                  # Trow begins 1852; Brooklyn trio
        return _wchoice(rng, [("trow", 6), ("hearne", 1 if ynum <= 1855 else 0),
                              ("hopehenderson", 1 if ynum >= 1855 else 0), ("smith", 1)])
    if ynum <= 1897:
        return _wchoice(rng, [("trow", 6), ("lain", 3),
                              ("boyd", 1 if 1885 <= ynum <= 1895 else 0)])
    if ynum <= 1914:
        return _wchoice(rng, [("trow", 8), ("upington", 2)])
    if ynum <= 1930:
        return _wchoice(rng, [("polk", 8), ("trow", 2 if ynum <= 1922 else 0)])
    return _wchoice(rng, [("polk", 7), ("mb", 3)])


def make_nyc(rng) -> dict:
    year, era, ynum = _nyc_year_era(rng)
    publisher = _nyc_publisher(rng, ynum)

    if rng.random() < 0.03:                           # occasional business listing
        n = _surname(rng)
        roll = rng.random()
        if roll < 0.4:
            name = f"{n} & {_surname(rng)}"
        elif roll < 0.7:
            name = f"{n} & Co"
        elif roll < 0.85:
            name = f"{n} Bros"
        else:
            name = f"{n} & Son"
        if era == "late" and rng.random() < 0.10:     # Polk-style firm continuation row
            name = f'" {rng.choice("ABCDEFGHJLMRSTW")} {rng.choice("ABCEFHJLMW")} & Co'
        elif rng.random() < 0.30:                     # Doggett/Lain print firms in caps
            name = name.upper()
        rec = {
            "name": name, "is_business": True, "spouse_name": "",
            "race_designation": "", "occupation_role": rng.choice(["merchants", "grocers",
            "tailors", "segars", "liquors", "druggists"]), "employer": "",
            "address": _nyc_address(rng, era, ynum), "home_address": "",
        }
        return _finish(rng, rec, "nyc", publisher, year, arange=n)

    female = rng.random() < 0.28
    widow = female and rng.random() < 0.30            # ~8% of all entries
    # textual race markers only; the ambiguous '*' waits on the publisher context tag
    race = ""
    race_p = 0.015 if (era in ("early", "mid") and ynum >= 1839) else 0.004
    if rng.random() < race_p:
        race = _wchoice(rng, [("col'd", 4), ("colored", 2), ("col", 2), ("(co'd)", 2)])

    ditto = era != "early" and rng.random() < (0.05 if era == "mid" else 0.14)
    parent_surname = _surname(rng)                    # anchors alphabetical_range for dittos
    widow_own_name = widow and not ditto and rng.random() < 0.15

    spouse = ""
    if widow:
        h = rng.choice(GIVEN_M)
        if widow_own_name:                            # "Gray, widow Abigail" -- her OWN name
            spouse = rng.choice(["widow", "wid."])    # bare marker -> spouse_name (conv #9)
        elif era == "early":
            spouse = _wchoice(rng, [(f"widow of {h}", 5), (f"widow {h}", 2),
                                    (f"wid. {h}", 2), (f"w. of {h}", 1)])
        elif era == "mid":
            spouse = _wchoice(rng, [(f"wid {h}", 4), (f"wid. {h}", 3),
                                    (f"widow of {h}", 2), (f"widow {h}", 1)])
        else:
            spouse = _wchoice(rng, [(f"wid {h}", 5), (f"wid. {h}", 4), (f"Wid. {h}", 1)])
        occ = "" if rng.random() < 0.6 else rng.choice(["dressmaker", "washer", "nurse",
              "milliner", "seamstress", "laundress", "boarding"])
    else:
        if rng.random() < 0.15:
            occ = ""
        elif female and rng.random() < 0.75:
            occ = rng.choice(NYC_FEMALE_OCC)
        else:
            occ = _wchoice(rng, NYC_OCC)
        if occ and era == "late" and occ in NYC_OCC_ABBREV and rng.random() < 0.5:
            occ = NYC_OCC_ABBREV[occ] + ("." if rng.random() < 0.6 else "")
    if occ and era == "late" and rng.random() < 0.06:
        occ += " (Mhn)"                               # commuter work-borough tag (conv #17)

    if ditto:
        name = _nyc_ditto_name(rng, female, era)
    elif widow_own_name:
        name = f"{parent_surname} {_nyc_given(rng, True, era)}"
    else:
        name = _nyc_name(rng, female, era)
        parent_surname = name.split()[0]
    caps = not ditto and rng.random() < {"early": 0.02, "mid": 0.03, "late": 0.01}[era]
    if caps:
        name = name.upper()                           # notable PERSON in caps (conv #14: caps != business)

    # most NYC entries list ONE address (combined work+home); a minority add an "h." home
    primary = _nyc_address(rng, era, ynum)
    home = ""
    if rng.random() < (0.15 if era == "early" else 0.35):
        home = "do" if rng.random() < 0.03 else _nyc_address(rng, era, ynum)
    if rng.random() < 0.03:                           # works across the river ("merchant NY h ...")
        primary = "NY" if era == "early" else rng.choice(["NY", "N Y", "N. Y."])
        home = home or _nyc_address(rng, era, ynum)
    if not home and rng.random() < (0.10 if era == "early" else 0.30):
        # sole address KEEPS its residency marker in the record (conv #8: "h 449 Clason av")
        marker = _wchoice(rng, [("h", 55), ("h.", 15), ("bds", 15), ("r", 8), ("b", 7)])
        primary = f"{marker} {primary}"

    rec = {
        "name": name, "is_business": False, "spouse_name": spouse,
        "race_designation": race, "occupation_role": occ, "employer": "",
        "address": primary, "home_address": home,
    }
    hints = {
        "surname_comma": (not ditto and not caps and
                          rng.random() < {"early": 0.5, "mid": 0.15, "late": 0.04}[era]),
        "widow_own_name": widow_own_name,
        "space_delim": era == "late" and rng.random() < 0.15,
    }
    return _finish(rng, rec, "nyc", publisher, year, arange=parent_surname, hints=hints)


def render_nyc(rng, rec, hints=None) -> str:
    hints = hints or {}
    head = rec["name"]
    if hints.get("surname_comma") and " " in head and head[0] not in '-"':
        s, rest = head.split(" ", 1)                  # raw shows "Graves, Benjamin"; record drops
        head = f"{s}, {rest}"                         # the comma (conv #3)
    if hints.get("widow_own_name") and rec["spouse_name"] and " " in rec["name"]:
        s, given = rec["name"].split(" ", 1)          # raw: "Gray, widow Abigail"
        head = f"{s}{', ' if rng.random() < 0.6 else ' '}{rec['spouse_name']} {given}"
    race = rec["race_designation"]
    if race and not race.startswith("("):
        head += f" {race}"
    parts = [head]
    if rec["spouse_name"] and not hints.get("widow_own_name"):
        parts.append(rec["spouse_name"])              # "wid John" / "widow of John"
    occ = rec["occupation_role"]
    if race.startswith("("):
        occ = f"{race} {occ}".strip()                 # Doggett: "Fox Charles, (co'd) seamn, ..."
    if occ:
        parts.append(occ)
    sep = " " if hints.get("space_delim") else ", "   # Upington 1900s: space-delimited fields
    line = sep.join(parts)
    # real directories drop the comma before the address ~40% of the time
    if rec["address"]:
        line += (" " if (hints.get("space_delim") or rng.random() >= 0.6) else ", ") + rec["address"]
    if rec["home_address"]:                           # home marker varies: h / h. / b / r / bds
        marker = _wchoice(rng, [("h", 40), ("h.", 28), ("b", 12), ("r", 8), ("bds", 12)])
        line += (" " if (hints.get("space_delim") or rng.random() >= 0.5) else ", ") + \
                f"{marker} {rec['home_address']}"
    if rng.random() < 0.55 and not line.endswith("."):
        line += "."
    return line

# ======================================================================================
# Shared finish / dispatch
# ======================================================================================

def _finish(rng, record: dict, profile: str, publisher: str, year: str,
            arange: Optional[str] = None, hints: Optional[dict] = None) -> dict:
    """profile picks the renderer (tulsa|nyc); publisher goes into the context tag.
    They differ: the tulsa profile is a Polk directory, so it tags publisher=polk —
    same tag as late-NYC Polk volumes (one publisher, two cities)."""
    if arange is None:                                # ditto rows pass the parent surname instead
        m = re.search(r"[A-Za-z]{3}", record["name"])
        arange = (m.group(0).upper() if m else record["name"][:3].upper())
    else:
        arange = arange[:3].upper()
    render = render_tulsa if profile == "tulsa" else render_nyc
    return {
        "raw_line": render(rng, record, hints),
        "context": {"publisher": publisher, "alphabetical_range": arange, "directory_year": year},
        "record": record,
        "_profile": profile,                          # stats grouping only; stripped before output
    }


def make_record(rng, profile: str, nyc_weight: float = 0.5) -> dict:
    if profile == "tulsa":
        return make_tulsa(rng)
    if profile == "nyc":
        return make_nyc(rng)
    # mix: branch on (1 - nyc_weight) so the default 0.5 keeps the historical RNG
    # stream byte-identical (tulsa on roll < 0.5)
    return make_tulsa(rng) if rng.random() < (1.0 - nyc_weight) else make_nyc(rng)

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
# Feature stats (--stats): the eyeball roll-call; doubles as a generator regression check
# ======================================================================================

_NBHD_RE = re.compile(r" (" + "|".join(NYC_NBHD) + r")\b")
_HOUSE_HYPHEN_RE = re.compile(r"\b\d+-\d+ ")
_SURNAME_COMMA_RE = re.compile(r"^[A-Z][A-Za-z'-]+,")


def _stats_new() -> dict:
    return {"n": 0, "profiles": {}, "examples": {}}


def _stats_update(stats: dict, ex: dict) -> None:
    """Tally style features for one PRE-NOISE example (noise would eat commas etc.).
    Grouped by generator PROFILE (feature rates stay comparable across runs); the
    publisher tag mix is tallied as pub= rows within each profile."""
    stats["n"] += 1
    d = ex.get("_profile", "?")
    c = stats["profiles"].setdefault(d, {"_rows": 0})
    c["_rows"] += 1
    c["pub=" + ex["context"]["publisher"]] = c.get("pub=" + ex["context"]["publisher"], 0) + 1
    rec, raw = ex["record"], ex["raw_line"]

    def hit(key, example=True):
        c[key] = c.get(key, 0) + 1
        if example:
            stats["examples"].setdefault((d, key), raw)

    if d == "tulsa":                       # regression watch: measured-1921 distributions
        if rec["is_business"]: hit("business", example=False)
        if rec["spouse_name"]: hit("spouse", example=False)
        if rec["employer"]: hit("employer", example=False)
        if rec["race_designation"]: hit("race (c)", example=False)
        return

    name, addr = rec["name"], rec["address"]
    year = int(ex["context"]["directory_year"][:4])
    hit("era " + ("early" if year < 1850 else "mid" if year <= 1890 else "late"),
        example=False)
    if name.startswith("-"): hit("ditto row (Trow -)")
    if name.startswith('"'): hit('ditto row (Polk ")')
    letters = [ch for ch in name if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        hit("ALL-CAPS business" if rec["is_business"] else "ALL-CAPS person")
    if _SURNAME_COMMA_RE.match(raw): hit("surname comma in raw")
    s = rec["spouse_name"]
    if s in ("widow", "wid."): hit("widow-own-name (bare marker)")
    elif s.startswith(("widow of", "w. of")): hit("widow of X")
    elif s: hit("wid/widow X", example=False)
    if addr.split() and addr.split()[0].rstrip(".") in ("h", "bds", "r", "b"):
        hit("marker kept in sole address")
    if rec["home_address"]: hit("two addresses", example=False)
    if rec["home_address"] == "do": hit("home ditto 'do'")
    if _HOUSE_HYPHEN_RE.search(addr): hit("hyphenated house no", example=False)
    if _NBHD_RE.search(addr): hit("neighborhood code")
    if "-street" in addr or "-lane" in addr: hit("hyphenated -street/-lane")
    if addr.endswith(" do."): hit("street ditto 'do.'")
    if "(Mhn)" in rec["occupation_role"]: hit("(Mhn) commuter tag")
    if rec["race_designation"]: hit("race marker")
    if "." in name: hit("period in name", example=False)
    if "." in rec["occupation_role"]: hit("period in occupation", example=False)
    if addr in ("NY", "N Y", "N. Y."): hit("commuter NY address")


def _stats_print(stats: dict, fh=None) -> None:
    fh = fh or sys.stderr
    print(f"\n--stats over {stats['n']} generated entries (pre-noise)", file=fh)
    for d in sorted(stats["profiles"]):
        counts = dict(stats["profiles"][d])
        rows = counts.pop("_rows")
        pubs = {k[4:]: counts.pop(k) for k in [k for k in counts if k.startswith("pub=")]}
        pub_mix = "  ".join(f"{p}:{100 * n / rows:.0f}%"
                            for p, n in sorted(pubs.items(), key=lambda kv: -kv[1]))
        print(f"[{d}] {rows} rows   publishers: {pub_mix}", file=fh)
        for key, cnt in sorted(counts.items(), key=lambda kv: -kv[1]):
            example = stats["examples"].get((d, key), "")
            tail = f"   e.g. {example[:58]}" if example else ""
            print(f"  {cnt:7d}  {100 * cnt / rows:5.2f}%  {key:30s}{tail}", file=fh)

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
    ap.add_argument("--stats", action="store_true",
                    help="print a feature-frequency table to stderr after generating")
    ap.add_argument("--mix-weight", type=float, default=0.5, metavar="P",
                    help="NYC share when --profile mix (default 0.5; e.g. 0.75 = 75/25 "
                         "NYC/Tulsa). Tulsa still carries the Polk-style employer/spouse-"
                         "paren signal the late-NYC gold needs -- rebalance, don't zero it.")
    args = ap.parse_args(argv)
    if not 0.0 <= args.mix_weight <= 1.0:
        ap.error("--mix-weight must be between 0 and 1")

    rng = random.Random(args.seed)
    stats = _stats_new() if args.stats else None

    if args.preview:
        ser = to_pipe if args.target == "pipe" else to_yaml
        for _ in range(args.n):
            ex = make_record(rng, args.profile, args.mix_weight)
            if stats:
                _stats_update(stats, ex)
            noisy = add_noise(rng, ex["raw_line"], args.noise)
            print("─" * 78)
            print(f"  INPUT  [{ex['context']['publisher']} {ex['context']['directory_year']} "
                  f"{ex['context']['alphabetical_range']}]: {noisy}")
            for ln in ser(ex["record"]).splitlines():
                print(f"      {ln}")
        if stats:
            _stats_print(stats)
        return 0

    fh = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        for _ in range(args.n):
            ex = make_record(rng, args.profile, args.mix_weight)
            if stats:
                _stats_update(stats, ex)                # pre-noise: the generator's true rates
            ex.pop("_profile", None)                    # internal stats key, not training data
            ex["raw_line"] = add_noise(rng, ex["raw_line"], args.noise)
            fh.write(json.dumps(ex, ensure_ascii=False) + "\n")
    finally:
        if args.out:
            fh.close()
            print(f"wrote {args.n} {args.profile} entries -> {args.out}", file=sys.stderr)
    if stats:
        _stats_print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
