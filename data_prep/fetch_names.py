# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Build a large, era-appropriate SURNAME pool for synth_persons.py from the public-domain
US Census 2010 surname-frequency list.

Why: synth_persons.py historically drew from a fixed ~54-surname pool, so the fine-tuned model
learned to *regularise* unseen surnames to common ones ("Bemmert" -> "Becker") instead of copying
them verbatim — the single biggest measured error on real directories. Training on thousands of
real surnames (with realistic frequencies) teaches the model that the surname token is to be
COPIED, not guessed.

Source: https://www2.census.gov/topics/genealogy/2010surnames/names.zip  (public domain)
  columns: name, rank, count, prop100k, cum_prop100k, pctwhite, pctblack, pctapi, pctaian,
           pct2prace, pcthispanic

Era skew for the 1786-1925 US-directory corpus: the raw 2010 frequencies over-weight post-1965
immigration (Garcia, Nguyen, Wong dominate the top). We drop names that are predominantly Hispanic
or Asian/Pacific-Islander (clearly anachronistic for this corpus) but KEEP the long tail, which is
overwhelmingly European — exactly the Irish/German/English/Jewish/Italian variety NYC needs.

Output: data_prep/names/surnames.tsv  ("Name<TAB>weight", weight = census count, desc by weight).
Run once locally; the .tsv is committed so synth_persons.py works without re-fetching.

    python3 data_prep/fetch_names.py                 # download + build (default top 40000)
    python3 data_prep/fetch_names.py --top 20000
    python3 data_prep/fetch_names.py --self-test     # recasing logic only, no network
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import urllib.request
import zipfile
from typing import Optional

CENSUS_URL = "https://www2.census.gov/topics/genealogy/2010surnames/names.zip"
CSV_IN_ZIP = "Names_2010Census.csv"
OUT = os.path.join(os.path.dirname(__file__), "names", "surnames.tsv")

# Common Irish/Scottish O'- surnames whose apostrophe the census strips — restore it for these only
# (blindly turning every O* into O'* would wreck Owens/Olson/Ortiz).
O_APOST = {
    "OBRIEN", "OCONNOR", "ONEILL", "ONEIL", "OSULLIVAN", "ODONNELL", "OREILLY", "OHARA",
    "OCONNELL", "OKEEFE", "OKEEFFE", "OROURKE", "OMALLEY", "OLEARY", "OSHEA", "ODOHERTY",
    "OBOYLE", "ODONOGHUE", "OGRADY", "ODWYER", "OBYRNE", "OCALLAGHAN", "OFARRELL", "ODAY",
    "OLOUGHLIN", "OMARA", "OTOOLE", "OFLAHERTY", "ORIORDAN", "OGORMAN", "OKANE",
}


def recase(upper: str) -> str:
    """Census names are ALL-CAPS with apostrophes stripped. Restore the common print forms:
    MCCARTHY->McCarthy, OBRIEN->O'Brien (known set), otherwise Title Case."""
    u = upper.strip().upper()
    if u in O_APOST:
        return "O'" + u[1].upper() + u[2:].lower()
    if u.startswith("MC") and len(u) > 2:
        return "Mc" + u[2].upper() + u[3:].lower()
    # Mac- is ambiguous (MacDonald vs Macey) and unsolvable by rule, so just title-case it.
    return "-".join(p.capitalize() for p in u.split("-"))  # handle hyphenated


def _f(v: str) -> float:
    try:
        return float(v)
    except ValueError:                                     # census uses "(S)" for suppressed
        return 0.0


def build(top: int) -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print(f"downloading {CENSUS_URL} ...", file=sys.stderr)
    raw = urllib.request.urlopen(CENSUS_URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        text = z.read(CSV_IN_ZIP).decode("utf-8", "replace")
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        name = (r.get("name") or "").strip()
        if not name or name == "ALL OTHER NAMES":
            continue
        count = int(_f(r.get("count", "0")))
        if count <= 0:
            continue
        if _f(r.get("pcthispanic")) >= 50 or _f(r.get("pctapi")) >= 50:   # era skew
            continue
        rows.append((recase(name), count))
    rows.sort(key=lambda t: -t[1])
    rows = rows[:top]
    with open(OUT, "w", encoding="utf-8") as fh:
        for name, w in rows:
            fh.write(f"{name}\t{w}\n")
    print(f"wrote {len(rows)} surnames -> {OUT}", file=sys.stderr)
    print(f"  sample: {', '.join(n for n, _ in rows[:8])} ... "
          f"{', '.join(n for n, _ in rows[top - 4:])}", file=sys.stderr)
    return 0


def _self_test() -> int:
    cases = {"MCCARTHY": "McCarthy", "OBRIEN": "O'Brien", "OWENS": "Owens",
             "MACDONALD": "Macdonald", "SMITH": "Smith", "VON-TRAPP": "Von-Trapp",
             "OCONNOR": "O'Connor", "MACEY": "Macey"}
    for u, want in cases.items():
        got = recase(u)
        assert got == want, f"{u} -> {got!r} (want {want!r})"
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", type=int, default=40000, help="keep the top-N surnames by frequency")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    return build(args.top)


if __name__ == "__main__":
    raise SystemExit(main())
