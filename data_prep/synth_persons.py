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
         publisher-keyed (polk-late/hearne-mid emit one; most other NYC rows lump the
         employer into the occupation list -> empty).

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
    ABBREVIATED street names ("19 Wm. street", "16 Wat.st.", "36 Han. squ." -- franks1786),
    "27 Ann do." street dittos (dominant for publisher=duncan, incl. bare "Mott do.").
    late: hyphenated outer-borough house nos ("24-12") + neighborhoods coded AND spelled
    (LIC/JH/Ozone Pk/Maspeth), "clk (Mhn)" commuter tags in occupation_role (conv #17,
    polk/mb 1931+ only), Upington space-delimited rendering, "Edw'd" contractions.
  * DENSE volumes (trow/polk 1905+, mb): fused marker+number ("r205 W141st", "h2378
    Bathgate av", cap "H804") in sole addresses AND raw-side home markers ("h502 W149th"
    with the record home BARE, conv #8); fused direction+ordinal ("W141st" ~3/4, spaced
    "E 26th" else); room codes ("309 Bway R801", "R 309", bare "1 Bway 203"); "215, 4th av"
    number-comma quirk; " Bkn" cross-borough tags; out-of-town values ("h Schenectady N Y");
    homes get "apt 35A", never office R-codes. Publisher-keyed per the page-verified
    fusion differences (polk1933bk fuses markers but spaces ordinals).
  * '*' race marker is publisher-keyed (the reason the tag exists): ogden -> race "*"
    (star fused to the name in raw); hopehenderson -> raw-only star, record DROPS it
    (Eastern District, conv #16) and colored prints col'd.
  * employer (conv #7/#13): polk-late "v-p Genl Electric Co" / "tchr P S" + principal
    "(Emmons & Roberts)" paren-firms; hearne-mid "foreman white lead factory" /
    "pastor of 1st Unitarian Church" (raw keeps "of"; employer field drops it).

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
# rare period given names (the census tail): the model must learn to COPY an unfamiliar
# given name verbatim, not regularise it to a common one — the measured error class
# ("Philenah" -> "Philip"). Same fix as the surname pool, inline (given names are a
# closed-ish period vocabulary; no fetch needed).
RARE_GIVEN_M = [
    "Zophar", "Ichabod", "Ezekiel", "Barzillai", "Obadiah", "Zebulon", "Jehiel",
    "Alonzo", "Erastus", "Hezekiah", "Jabez", "Lemuel", "Seymour", "Thaddeus", "Philo",
    "Rensselaer", "Gershom", "Elnathan", "Increase", "Epaphras", "Zenas", "Selah",
    "Uriah", "Asahel", "Eliakim", "Japhet", "Mordecai", "Shadrach", "Cephas", "Lorenzo",
    "Corydon", "Osgood", "Leander", "Adoniram", "Eliphalet", "Simeon", "Abijah",
    "Zadock", "Ephraim", "Amasa", "Elihu", "Josiah", "Nehemiah", "Othniel", "Peleg",
]
RARE_GIVEN_F = [
    "Philenah", "Thankful", "Mehitable", "Keziah", "Zilpah", "Achsah", "Lodema",
    "Experience", "Temperance", "Jerusha", "Huldah", "Tryphena", "Sophronia", "Philura",
    "Roxana", "Lovina", "Almira", "Zeruiah", "Charity", "Mercy", "Patience", "Freelove",
    "Waitstill", "Desire", "Electa", "Orpha", "Vashti", "Drusilla", "Barbary", "Dorcas",
    "Hepzibah", "Lavinia", "Cynthia", "Arletta", "Manerva", "Philinda", "Submit",
    "Deliverance", "Parnel", "Asenath", "Bathsheba", "Content", "Hulda", "Sylvia",
]

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
    if rng.random() < 0.05:                           # census-tail names: copy, don't regularise
        return rng.choice(RARE_GIVEN_F if female else RARE_GIVEN_M)
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
# 1920s/30s outer-borough neighborhoods (Polk Queens/SI; kept verbatim in address):
# coded AND spelled forms both appear on the queens1933 gold pages
NYC_NBHD = ["LIC", "JH", "RH", "Rdgwd", "Flush", "WNB", "Stap", "Tomp", "NB",
            "Maspeth", "Ozone Pk", "S Ozone Pk", "Howard Bch", "Jam", "Cor", "Glen",
            "Whitestone", "Corona", "Woodhaven"]
# dense late Manhattan/Bronx streets (trow1907/13 + polk1917/25 gold pages): heavy
# abbreviation (Bway, Washn pl, Gd blvd, Lex av) is the volume style, kept verbatim
NYC_LATE_STREETS = [
    "Bway", "Amsterdam av", "Madison av", "Park av", "Columbus av", "Lexington av",
    "Lex av", "West End av", "W End av", "Riverside dr", "St Marks pl", "St Marks av",
    "Convent av", "Bathgate av", "Webster av", "Anderson av", "Walton av", "Theriot av",
    "Pinehurst av", "Morningside dr", "Shakespeare av", "Wythe pl", "Washn pl",
    "Gd blvd", "Nassau", "Barclay", "Bowery", "Stanton", "Norfolk", "Simpson",
    "Monterey av", "Halsey", "Union av", "Prospect av", "Tremont av", "Ft Washn av",
]
# commuter home/work places printed as the whole address value ("h Schenectady N Y");
# marker stays SPACED (no house number to fuse with) and is kept in a sole address
NYC_OUT_OF_TOWN = [
    "Schenectady N Y", "New Milford Conn", "E Orange", "Perth Amboy N J", "Newark N J",
    "Yonkers", "Jersey City N J", "Stamford Conn", "White Plains", "Mt Vernon",
    "Nyack N Y", "Tarrytown N Y", "Hoboken N J", "Elizabeth N J", "Greenwich Conn",
]
# 1780s-90s street-name contractions (franks1786 gold: Wat.st., Wm. street, Q. street,
# Han. squ.) — the printer abbreviated NAMES, not just suffixes
NYC_EARLY_ST_ABBREV = {
    "Water": "Wat.", "William": "Wm.", "George": "Geo.", "Queen": "Q.", "Hanover": "Han.",
    "Broad": "Br.", "Cherry": "Cher.", "Greenwich": "Greenw.", "Chatham": "Chat.",
}
NYC_EARLY_STREETS = ["Water", "Wall", "Cherry", "Broad", "Queen", "William", "George",
                     "Hanover", "Pearl", "Dock", "Smith", "King", "Beekman", "Maiden",
                     "Nassau", "John", "Fair", "Ann", "Chatham", "Greenwich"]
# NYC employer signal (conv #7/#13), measured from the gold: polk1917-style late columns
# ("v-p Genl Electric Co", "tchr P S", principal "(Emmons & Roberts)") + hearne1852-style
# mid institutions ("foreman white lead factory", "pastor of 1st Unitarian Church")
NYC_EMPLOYERS_LATE = [
    "Genl Electric Co", "Thos A Edison Inc", "N Y Tel Co", "Con Gas Co",
    "Met Life Ins Co", "N Y Edison Co", "Am Ry Ex Co", "Adams Ex Co", "U S Rubber Co",
    "Standard Oil Co", "Postal Tel Cable Co", "Western Union Tel Co", "Nat City Bank",
    "Corn Ex Bank", "Equitable Life Assur Soc", "P S", "B'way Sav Bank",
    "Interboro R T Co", "N Y C R R", "Erie R R", "Am Sug Ref Co", "Otis Elev Co",
    "Singer Mnfg Co", "Public Library", "Dept Pub Welfare", "Bd of Educ",
]
NYC_EMP_OCC_LATE = ["clk", "tchr", "v-p", "pres", "sec", "treas", "mgr", "supt", "eng",
                    "insp", "bkpr", "com mer", "asst mgr", "slsmn", "recording expert"]
NYC_CHURCHES = ["1st Unitarian Church", "2d Presb Church", "St Anns Church",
                "Plymouth Church", "St Pauls M E Church", "1st Baptist Church"]
NYC_WORKS_MID = ["white lead factory", "sugar refinery", "Atlantic dock", "Navy Yard",
                 "Fulton market", "glass works", "iron foundry", "rope walk",
                 "distillery", "gas works", "Court House", "Custom House"]


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


def _nyc_street_dense(rng) -> str:
    """Dense late Manhattan/Bronx street forms (trow1907/13 + polk1917/25 gold):
    direction+ordinal fused ~3/4 of the time (W141st vs W 141st), lettered avenues
    (Av A / fused AvA), and heavily abbreviated named streets — kept verbatim."""
    roll = rng.random()
    if roll < 0.42:
        d, o = rng.choice("WE"), _ordinal(rng.randint(1, 180))
        return f"{d}{o}" if rng.random() < 0.75 else f"{d} {o}"
    if roll < 0.50:
        return rng.choice(["Av A", "AvA", "Av B", "Av C", "Av D", "1st av", "2d av",
                           "3d av", "4th av", "5th av", "7th av", "8th av", "19th av"])
    return rng.choice(NYC_LATE_STREETS)


def _nyc_address_dense(rng, home: bool = False) -> str:
    num = rng.randint(1, 3600)
    street = _nyc_street_dense(rng)
    # Polk quirk: a comma may separate the house number from a NUMERIC street ("215, 4th av")
    comma = "," if street[0].isdigit() and rng.random() < 0.22 else ""
    addr = f"{num}{comma} {street}"
    if home:
        if rng.random() < 0.06:                        # homes get apartments, not office rooms
            addr += f" apt {rng.randint(1, 40)}{rng.choice('ABCDEFGH')}"
        return addr
    roll = rng.random()
    if roll < 0.09:
        addr += f" R{rng.randint(1, 1400)}"            # office/room code, R fused ("309 Bway R801")
    elif roll < 0.115:
        addr += f" R {rng.randint(1, 40)}"             # occasionally spaced ("R 309")
    elif roll < 0.135:
        addr += f" {rng.randint(2, 1400)}"             # bare room number ("1 Bway 203")
    if rng.random() < 0.04:
        addr += " Bkn"                                 # cross-borough tag on the address itself
    return addr


def _nyc_address_early(rng, num: int, publisher: str = "") -> str:
    """1780s-1810s print forms measured from franks1786/duncan1794 gold: hyphenated
    AND abbreviated street names ('19 Wm. street', '16 Wat.st.', '36 Han. squ.'),
    ' do.' street dittos (dominant on Duncan's run-on pages, incl. bare 'Mott do.'),
    and trailing periods — all verbatim in the record."""
    street = rng.choice(NYC_EARLY_STREETS)
    ditto_p = 0.45 if publisher == "duncan" else 0.10
    roll = rng.random()
    if roll < ditto_p:                                # "27 Ann do." / bare "Mott do."
        head = f"{num} {street}" if rng.random() < 0.8 else street
        return f"{head} do."
    if roll < ditto_p + 0.16:                         # "71 Dey-street" / "63 Cherry-st."
        suf = _wchoice(rng, [("-street", 5), ("-st", 2), ("-st.", 2), ("-lane", 1)])
        tail = "." if not suf.endswith(".") and rng.random() < 0.30 else ""
        return f"{num} {street}{suf}{tail}"
    if roll < ditto_p + 0.28:                         # abbreviated street NAME (franks style)
        ab = NYC_EARLY_ST_ABBREV.get(street, street[:3] + ".")
        if street == "Hanover":
            return f"{num} {ab} {rng.choice(['squ.', 'square'])}"
        form = _wchoice(rng, [(f"{ab} street", 4), (f"{ab}st.", 3), (f"{ab} st.", 2)])
        return f"{num} {form}"
    tail = "." if rng.random() < 0.30 else ""
    return f"{num} {_nyc_street(rng)}{tail}"


def _nyc_address(rng, era: str = "mid", ynum: int = 0, publisher: str = "",
                 home: bool = False) -> str:
    # forms + abbreviations confirmed against real gold pages (Hearne 1852, franks1786,
    # duncan1794, trow1907/13, polk1917/25, queens1933) + style cards
    dense = (publisher in ("trow", "polk") and 1900 <= ynum <= 1930) or publisher == "mb"
    roll = rng.random()
    if dense and roll < 0.88:
        return _nyc_address_dense(rng, home=home)
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
        return _nyc_address_early(rng, num, publisher)
    if era == "late" and ynum >= 1915:                # hyphenated nos + nbhds are 1920s/30s
        # Polk outer-borough volumes (Queens/SI/Bklyn 1931+) run hyphenated + neighborhood
        # heavy (queens1933 style); mid-1910s-20s Manhattan only lightly
        outer_p = 0.65 if (publisher == "polk" and ynum >= 1931) else 0.24
        if rng.random() < outer_p:
            addr_num = f"{num}-{rng.randint(1, 64)}"
            street = (f"{_ordinal(rng.randint(1, 180))}" + (" av" if rng.random() < 0.45 else "")
                      ) if rng.random() < 0.55 else _nyc_street(rng)
            addr = f"{addr_num} {street}"             # bare-ordinal streets: "25-53 47th LIC"
            if rng.random() < 0.75:
                addr += f" {rng.choice(NYC_NBHD)}"
            return addr
        addr = f"{num} {_nyc_street(rng)}"
        if rng.random() < 0.25:
            addr += f" {rng.choice(NYC_NBHD)}"
        return addr
    return f"{num} {_nyc_street(rng)}"


def _nyc_given(rng, female: bool, era: str) -> str:
    rare_p = {"early": 0.12, "mid": 0.08, "late": 0.05}[era]
    if rng.random() < rare_p:                         # heavier early: pre-1850 names are odder
        return rng.choice(RARE_GIVEN_F if female else RARE_GIVEN_M)
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


def _nyc_ditto_name(rng, female: bool, era: str, publisher: str = "") -> str:
    """Surname-repeat continuation row: Trow leading '-' (no space), Polk '\" ' (with
    space) — publisher-keyed now that the tag exists (trow1913 vs polk1917 gold)."""
    given = _nyc_given(rng, female, era)
    mid = f" {rng.choice('ABCDEFGHJLMRSTW')}" if rng.random() < 0.45 else ""
    if publisher == "polk":
        mark = '" '
    elif publisher == "trow":
        mark = "-"
    else:
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
        # ogden boosted: its '*'=colored is a rare publisher-CONDITIONED behavior the
        # model can only learn from enough tagged rows (panel volume: ogden1839)
        return _wchoice(rng, [("longworth", 6), ("mercein", 2 if 1818 <= ynum <= 1826 else 0),
                              ("ogden", 5 if ynum >= 1838 else 0)])
    if ynum <= 1851:
        return _wchoice(rng, [("doggett", 7), ("rode", 3 if ynum >= 1850 else 0)])
    if ynum <= 1861:                                  # Trow begins 1852; Brooklyn trio
        return _wchoice(rng, [("trow", 6), ("hearne", 2 if ynum <= 1855 else 0),
                              ("hopehenderson", 2 if ynum >= 1855 else 0), ("smith", 1)])
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
    dense = publisher in ("trow", "polk") and ynum >= 1905   # fused-print, employer-rich volumes

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
        if era == "late" and rng.random() < 0.10:     # firm continuation row, mark by publisher
            mark = "-" if publisher == "trow" else '" '
            name = f'{mark}{rng.choice("ABCDEFGHJLMRSTW")} {rng.choice("ABCEFHJLMW")} & Co'
        elif rng.random() < 0.30:                     # Doggett/Lain print firms in caps
            name = name.upper()
        rec = {
            "name": name, "is_business": True, "spouse_name": "",
            "race_designation": "", "occupation_role": rng.choice(["merchants", "grocers",
            "tailors", "segars", "liquors", "druggists"]), "employer": "",
            "address": _nyc_address(rng, era, ynum, publisher), "home_address": "",
        }
        return _finish(rng, rec, "nyc", publisher, year, arange=n)

    female = rng.random() < 0.28
    widow = female and rng.random() < 0.30            # ~8% of all entries
    # race marks are volume-specific (conv #10) — the publisher tag disambiguates '*':
    # Ogden 1839 '*' = colored -> race_designation "*" (star stays OFF the name field);
    # Hope & Henderson '*' = Eastern District (geographic — raw-only, DROPPED from the
    # record, conv #16) and colored prints as col'd. Elsewhere textual markers.
    race, star_raw = "", False
    if publisher == "ogden":
        if rng.random() < 0.22:                       # real page rate ~11%; boosted for signal
            race, star_raw = "*", True
    elif publisher == "hopehenderson":
        if rng.random() < 0.12:
            star_raw = True
        elif rng.random() < 0.012:
            race = "col'd"
    else:
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

    # NYC employer signal (conv #7/#13) — publisher-keyed, measured from the gold panel
    employer, paren_firm, emp_of = "", False, False
    if not widow:
        if dense and rng.random() < 0.05:             # principal "(Emmons & Roberts)" (conv #13)
            employer = f"{_surname(rng)} & {rng.choice([_surname(rng), 'Co', 'Bros'])}"
            paren_firm = True
            if rng.random() < 0.7:
                occ = ""                              # usually no trade word on principal rows
        elif occ and dense and rng.random() < 0.20:   # polk1917-style employer-rich column
            occ = rng.choice(NYC_EMP_OCC_LATE)
            employer = (rng.choice(NYC_EMPLOYERS_LATE) if rng.random() < 0.8
                        else f"{_surname(rng)} & Co")
        elif occ and era == "mid" and rng.random() < (0.25 if publisher == "hearne" else 0.04):
            if rng.random() < 0.30:                   # "pastor of 1st Unitarian Church"
                occ, employer, emp_of = "pastor", rng.choice(NYC_CHURCHES), True
            else:                                     # "foreman white lead factory"
                occ = rng.choice(["foreman", "supt", "clk", "eng", "watchman"])
                employer = rng.choice(NYC_WORKS_MID)
    if occ and not employer and publisher in ("polk", "mb") and ynum >= 1931 \
            and rng.random() < 0.18:
        occ += " (Mhn)"                               # commuter work-borough tag (conv #17) —
                                                      # outer-borough/M&B volumes only

    if ditto:
        name = _nyc_ditto_name(rng, female, era, publisher)
    elif widow_own_name:
        name = f"{parent_surname} {_nyc_given(rng, True, era)}"
    else:
        name = _nyc_name(rng, female, era)
        parent_surname = name.split()[0]
    caps = not ditto and rng.random() < {"early": 0.02, "mid": 0.03, "late": 0.01}[era]
    if caps:
        name = name.upper()                           # notable PERSON in caps (conv #14: caps != business)

    # most NYC entries list ONE address (combined work+home); a minority add an "h." home
    primary = _nyc_address(rng, era, ynum, publisher)
    home = ""
    if rng.random() < (0.15 if era == "early" else 0.35):
        home = "do" if rng.random() < 0.03 else _nyc_address(rng, era, ynum, publisher, home=True)
        if dense and home != "do":
            if rng.random() < 0.05:                   # commuter home out of town
                home = rng.choice(NYC_OUT_OF_TOWN)
            elif rng.random() < 0.15 and not home.endswith("Bkn"):
                home += " Bkn"                        # "h318 Senator Bkn" cross-borough home
    if rng.random() < 0.03:                           # works across the river ("merchant NY h ...")
        primary = "NY" if era == "early" else rng.choice(["NY", "N Y", "N. Y."])
        home = home or _nyc_address(rng, era, ynum, publisher, home=True)
    # dense residential volumes mark nearly EVERY sole address (r/h fused); mid-era ~30%
    sole_marker_p = 0.75 if dense else (0.10 if era == "early" else 0.30)
    if not home and publisher != "mb" and rng.random() < sole_marker_p:
        # sole address KEEPS its residency marker in the record (conv #8: "h 449 Clason av");
        # in dense late Trow/Polk print the marker often FUSES to the house number
        # ("r205 W141st", "h2378 Bathgate av", cap "H804 W180th") — record verbatim.
        # (mb1931 prints no residency markers at all — style card.)
        if dense and rng.random() < 0.10:
            primary = rng.choice(NYC_OUT_OF_TOWN)     # "h Schenectady N Y" (no number -> spaced)
        if dense:
            marker = _wchoice(rng, [("h", 55), ("r", 25), ("H", 8), ("b", 5), ("bds", 7)])
        else:
            marker = _wchoice(rng, [("h", 55), ("h.", 15), ("bds", 15), ("r", 8), ("b", 7)])
        fuse = dense and primary[:1].isdigit() and marker in ("h", "r", "H", "b") \
            and rng.random() < 0.72
        primary = f"{marker}{primary}" if fuse else f"{marker} {primary}"

    rec = {
        "name": name, "is_business": False, "spouse_name": spouse,
        "race_designation": race, "occupation_role": occ, "employer": employer,
        "address": primary, "home_address": home,
    }
    hints = {
        "surname_comma": (not ditto and not caps and
                          rng.random() < {"early": 0.5, "mid": 0.15, "late": 0.04}[era]),
        "widow_own_name": widow_own_name,
        "space_delim": era == "late" and rng.random() < 0.15,
        # dense-print raw lines fuse the home marker to the house number ("h502 W149th");
        # the record's home_address stays BARE (conv #8) so the model learns to un-fuse it
        "fuse_home_marker": dense and rng.random() < 0.70,
        "paren_firm": paren_firm,                     # raw shows "(Firm & Co)" after the name
        "emp_of": emp_of,                             # raw keeps the "of" connector (conv #7)
        "star_prefix": star_raw and not ditto,        # raw shows "*Name ..." (conv #10)
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
    if hints.get("star_prefix"):
        head = f"*{head}"                             # star fused to the name ("*Simmons Aaron")
    race = rec["race_designation"]
    if race and race != "*" and not race.startswith("("):
        head += f" {race}"                            # '*' renders as the fused prefix instead
    if hints.get("paren_firm") and rec["employer"]:
        head += f" ({rec['employer']})"               # principal (firm) — conv #13
    parts = [head]
    if rec["spouse_name"] and not hints.get("widow_own_name"):
        parts.append(rec["spouse_name"])              # "wid John" / "widow of John"
    occ = rec["occupation_role"]
    if race.startswith("("):
        occ = f"{race} {occ}".strip()                 # Doggett: "Fox Charles, (co'd) seamn, ..."
    if rec["employer"] and not hints.get("paren_firm"):
        occ = f"{occ}{' of ' if hints.get('emp_of') else ' '}{rec['employer']}".strip()
    if occ:
        parts.append(occ)
    sep = " " if hints.get("space_delim") else ", "   # Upington 1900s: space-delimited fields
    line = sep.join(parts)
    # real directories drop the comma before the address ~40% of the time
    if rec["address"]:
        line += (" " if (hints.get("space_delim") or rng.random() >= 0.6) else ", ") + rec["address"]
    if rec["home_address"]:                           # home marker varies: h / h. / b / r / bds
        if hints.get("fuse_home_marker") and rec["home_address"][:1].isdigit():
            marker = _wchoice(rng, [("h", 75), ("r", 18), ("H", 7)])
            joined = f"{marker}{rec['home_address']}"  # fused: "h502 W149th"
        else:
            marker = _wchoice(rng, [("h", 40), ("h.", 28), ("b", 12), ("r", 8), ("bds", 12)])
            joined = f"{marker} {rec['home_address']}"
        line += (" " if (hints.get("space_delim") or rng.random() >= 0.5) else ", ") + joined
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


def make_record(rng, profile: str, nyc_weight: float = 0.75) -> dict:
    if profile == "tulsa":
        return make_tulsa(rng)
    if profile == "nyc":
        return make_nyc(rng)
    # mix: tulsa on roll < (1 - nyc_weight); default 0.75 NYC-first (cycle three)
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
_FUSED_MARKER_RE = re.compile(r"^[hrbH]\d")
_FUSED_ORD_RE = re.compile(r"\b[WE]\d+(?:st|d|th)\b")
_ROOM_RE = re.compile(r" R ?\d")
_EARLY_ABBREV_RE = re.compile(r"\b[A-Z][a-z]{0,5}\.\s?(?:st\.?|street|squ)")


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
    if addr.split() and addr.split()[0].rstrip(".") in ("h", "bds", "r", "b", "H"):
        hit("marker kept in sole address")
    if _FUSED_MARKER_RE.match(addr):
        hit("fused marker+number (addr)")
    if _FUSED_ORD_RE.search(addr) or _FUSED_ORD_RE.search(rec["home_address"]):
        hit("fused W/E ordinal")
    if _ROOM_RE.search(addr):
        hit("room code R#")
    if addr.endswith(" Bkn") or rec["home_address"].endswith(" Bkn"):
        hit("Bkn cross-borough tag")
    if (rec["home_address"] in NYC_OUT_OF_TOWN
            or any(addr.endswith(p) for p in NYC_OUT_OF_TOWN)):
        hit("out-of-town value")
    if _EARLY_ABBREV_RE.search(addr):
        hit("abbrev early street name")
    if rec["employer"]:
        hit("employer (paren firm)" if f"({rec['employer']})" in raw else "employer (nyc)")
    if raw.startswith("*"):
        hit("race '*' (ogden)" if rec["race_designation"] == "*" else "star dropped (E Dist)")
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
    ap.add_argument("--mix-weight", type=float, default=0.75, metavar="P",
                    help="NYC share when --profile mix (default 0.75 -- NYC-first, cycle three; "
                         "was 0.5 through v2). Tulsa still carries Polk-style spouse-paren + "
                         "grid-address signal -- rebalance, don't zero it.")
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
