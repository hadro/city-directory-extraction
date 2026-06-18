# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Harvest REAL surname/given-name frequencies from directory-pipeline entries CSVs and merge them
into the synthetic generator's name pool.

Why: the census pool (data_prep/names/surnames.tsv) gives variety but a *2010* distribution — it
lets anachronisms through ("Woldemariam" in 1855) and misses names common-then/rare-now. Names
harvested from the actual target directories give the authentic era/place distribution and the exact
rare surnames the model fails on. We weight them UP vs census when sampling.

Input: one or more `entries_*.csv` from the pipeline (handles both name schemas — a single `name`
column, or separate `surname`/`given_name`). Businesses (is_business) are skipped.

    python3 data_prep/harvest_names.py ../directory-pipeline/output/<slug>/**/entries_*.csv
    python3 data_prep/harvest_names.py path/to/entries_a.csv path/to/entries_b.csv
    python3 data_prep/harvest_names.py --self-test

Output (appends/merges across runs so you can harvest volume-by-volume):
    data_prep/names/surnames_harvested.tsv   ("Surname<TAB>count")
    data_prep/names/given_harvested.tsv      ("Given<TAB>count")

Leakage note: harvest from volumes NOT in the eval panel (keep NYU's Trow-1850 and Lain-1897 out)
so those stay honest held-out tests.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys
from collections import Counter
from typing import Optional

NAMES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "names")
SUR_OUT = os.path.join(NAMES_DIR, "surnames_harvested.tsv")
GIV_OUT = os.path.join(NAMES_DIR, "given_harvested.tsv")

_JUNK = re.compile(r"[0-9]")                              # OCR digits in a name -> drop
_INITIAL = re.compile(r"^[A-Z]\.?$")                     # bare middle initials -> not a given name


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes", "t"}


def _split_name(row: dict) -> "tuple[str, list[str]]":
    """Return (surname, [given tokens]) from either schema."""
    if (row.get("surname") or "").strip():
        sur = row["surname"].strip()
        giv = (row.get("given_name") or "").strip().split()
        return sur, giv
    name = (row.get("name") or "").strip()
    parts = name.split()
    return (parts[0] if parts else ""), parts[1:]


def harvest(paths: "list[str]") -> "tuple[Counter, Counter]":
    sur, giv = Counter(), Counter()
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if _truthy(row.get("is_business", "")):
                    continue
                s, gtoks = _split_name(row)
                if s and len(s) >= 2 and not _JUNK.search(s):
                    sur[s] += 1
                for g in gtoks:
                    g = g.strip(".,")
                    if g and len(g) >= 2 and not _INITIAL.match(g) and not _JUNK.search(g):
                        giv[g] += 1
    return sur, giv


def _merge_write(path: str, counts: Counter) -> int:
    prev = Counter()
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            n, c = ln.rstrip("\n").split("\t")
            prev[n] += int(c)
    prev.update(counts)
    with open(path, "w", encoding="utf-8") as fh:
        for n, c in prev.most_common():
            fh.write(f"{n}\t{c}\n")
    return len(prev)


def _self_test() -> int:
    rows = [{"surname": "Bemmert", "given_name": "Bernard", "is_business": "False"},
            {"surname": "Alling", "given_name": "Louis W.", "is_business": "False"},
            {"surname": "Acme", "given_name": "Laundry", "is_business": "True"},   # skip
            {"name": "Huelsberg F. D.", "is_business": "false"}]
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        w = csv.DictWriter(f, fieldnames=["surname", "given_name", "name", "is_business"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in ["surname", "given_name", "name", "is_business"]})
        tmp = f.name
    sur, giv = harvest([tmp])
    assert set(sur) == {"Bemmert", "Alling", "Huelsberg"}, dict(sur)
    assert "Laundry" not in giv and "Acme" not in sur, "business not skipped"
    assert "Louis" in giv and "W" not in giv, dict(giv)        # bare initial dropped
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entries", nargs="*", help="entries_*.csv paths (globs ok)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    paths = [p for pat in args.entries for p in glob.glob(pat, recursive=True)]
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        ap.error("no entries CSVs matched")
    os.makedirs(NAMES_DIR, exist_ok=True)
    sur, giv = harvest(paths)
    ns = _merge_write(SUR_OUT, sur)
    ng = _merge_write(GIV_OUT, giv)
    print(f"harvested from {len(paths)} file(s): +{len(sur)} surnames, +{len(giv)} given names",
          file=sys.stderr)
    print(f"  totals now: {ns} surnames -> {SUR_OUT}", file=sys.stderr)
    print(f"              {ng} given   -> {GIV_OUT}", file=sys.stderr)
    print(f"  top surnames: {', '.join(n for n, _ in sur.most_common(8))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
