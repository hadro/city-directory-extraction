# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Measure how much of the gold panel's REAL surname vocabulary the generator's name pool contains.

This is the number `docs/NAME_HARVEST_PLAN.md` is trying to move. Baseline, measured
2026-09-02: **221 of 449 distinct gold surnames (49.2%) are absent** from the 2010-census
pool in `names/surnames.tsv`. Run this before and after a `harvest_names.py` run.

Two numbers come out, and the SECOND is the one worth trusting:

  1. gold-surname coverage — how many panel surnames the pool now contains. Beware: directory
     surnames are ~99% page-unique (measured), so this barely moves unless you harvest the
     gold page itself, which leakage policy forbids. A big jump here is a leak, not a win.
  2. net-new vocabulary — how many harvested surnames the census pool lacks. This is the real
     signal that the pool gained era/place-authentic names.

Only person rows count: `is_business` rows are skipped, and so are ditto-continuation rows
whose `name` starts with punctuation ("-Adolph A", '" Nettie') — their first token is not a
surname, and counting them inflates the panel to 513 names / 55.6% missing.

Usage
-----
    python3 data_prep/measure_name_coverage.py
    python3 data_prep/measure_name_coverage.py --show-missing 80
    python3 data_prep/measure_name_coverage.py --self-test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA_DIR = os.path.join(REPO, "data")
NAMES_DIR = os.path.join(HERE, "names")

# The 21-volume gold panel (1583 rows). Deliberately excludes the large silver / held-out
# sets (nyu, lain-1897, ftd, minneapolis, tulsa) so this tracks the same panel as evaluate.py.
PANEL = [
    "boyd1890", "doggett1846", "duncan1794", "franks1786", "hearne1852",
    "hopehenderson1856", "lain1876", "longworth1818", "mb1931", "mercein1820",
    "ogden1839", "polk1917", "polk1925", "polk1933bk", "polk1933si", "queens1933",
    "rode1851", "trow1884", "trow1907", "trow1913", "trowwilson1865",
]


def surname_of(record: dict) -> Optional[str]:
    """First token of `name`, or None if this row carries no surname evidence."""
    if record.get("is_business"):
        return None
    parts = (record.get("name") or "").split()
    if not parts or not parts[0][:1].isalpha():
        return None                       # ditto continuation, not a surname
    return parts[0]


def gold_surnames() -> "tuple[dict, int]":
    sur: dict = {}
    rows = 0
    for slug in PANEL:
        path = os.path.join(DATA_DIR, f"{slug}_eval.jsonl")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                rows += 1
                s = surname_of(json.loads(line)["record"])
                if s:
                    sur.setdefault(s, set()).add(slug)
    return sur, rows


def pool(fname: str) -> set:
    path = os.path.join(NAMES_DIR, fname)
    if not os.path.exists(path):
        return set()
    out = set()
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            n = ln.rstrip("\n").split("\t")[0]
            if n:
                out.add(n)
    return out


def _self_test() -> int:
    assert surname_of({"name": "Juar Isaac", "is_business": False}) == "Juar"
    assert surname_of({"name": "-Adolph A", "is_business": False}) is None
    assert surname_of({"name": '" Nettie', "is_business": False}) is None
    assert surname_of({"name": "Acme Laundry", "is_business": True}) is None
    assert surname_of({"name": "", "is_business": False}) is None
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show-missing", type=int, default=40,
                    help="how many still-missing surnames to print (default 40)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    sur, rows = gold_surnames()
    census = pool("surnames.tsv")
    harvested = pool("surnames_harvested.tsv")

    print(f"gold panel : {len(PANEL)} volumes, {rows} rows, {len(sur)} distinct person surnames")
    print(f"pools      : census {len(census)}, harvested {len(harvested)}")
    print()

    def miss(p: set) -> list:
        return sorted(s for s in sur if s not in p)

    miss_c = miss(census)
    pct_c = 100.0 * len(miss_c) / len(sur)
    print(f"{'census only (baseline)':<30} missing {len(miss_c):3d}/{len(sur)} = {pct_c:5.1f}%")

    if harvested:
        miss_h = miss(census | harvested)
        pct_h = 100.0 * len(miss_h) / len(sur)
        print(f"{'census + harvested':<30} missing {len(miss_h):3d}/{len(sur)} = {pct_h:5.1f}%")
        recovered = sorted(set(miss_c) - set(miss_h))
        print()
        print(f"(1) gold-surname coverage : {pct_c:.1f}% -> {pct_h:.1f}% "
              f"({pct_c - pct_h:+.1f} pts, {len(recovered)} recovered)")
        if recovered:
            print("    recovered: " + ", ".join(recovered[:60]))
        new = [n for n in harvested if n not in census]
        print(f"(2) net-new vocabulary    : {len(new)}/{len(harvested)} harvested surnames "
              f"({100.0 * len(new) / len(harvested):.0f}%) are absent from the census pool")
        print()
        print(f"still missing (first {args.show_missing}):")
        print("  " + ", ".join(miss_h[:args.show_missing]))
    else:
        print()
        print("no names/surnames_harvested.tsv — baseline only. Run harvest_names.py first.")
        print(f"missing (first {args.show_missing}):")
        print("  " + ", ".join(miss_c[:args.show_missing]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
