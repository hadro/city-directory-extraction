# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Prove that harvested pages do NOT overlap the evaluation sets.

`docs/NAME_HARVEST_PLAN.md` has one hard rule: harvest only from pages that are not in the
eval panel. This checks it mechanically, so the claim is verified rather than assumed.

Every page image under `<pipeline>/output/harvest_*` is compared against every `context.image`
referenced by every `data/*_eval.jsonl`. Matching is on the page's STABLE IDENTITY, not the
download filename — the same page fetched twice gets a different `NNNN_` sequence prefix, so
filename comparison silently misses real leaks:

    Internet Archive : (item id, leaf number)   ('merceinscitydire00merc', '0138')
    NYPL             : the bare image id        '58064839'

This is load-bearing, not a formality. It caught a real leak on 2026-09-02: NYPL image ids are
not perfectly contiguous across a volume, so canvas arithmetic (gold_id - first_id + 1) drifted
by one page and pulled the polk1917 gold page into `harvest_polk1917_post`. That single page was
responsible for 5 of 7 apparently-"recovered" gold surnames. Never trust canvas arithmetic to
exclude a gold page — always verify after downloading.

Usage
-----
    python3 data_prep/verify_harvest_leakage.py
    python3 data_prep/verify_harvest_leakage.py --output-dir ~/github/directory-pipeline/output
    python3 data_prep/verify_harvest_leakage.py --glob 'harvest_*' --self-test

Exit status is 1 if any harvested page appears in an eval set, so it can gate a pipeline run.
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import re
import sys
import urllib.parse
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DATA_DIR = os.path.join(REPO, "data")
DEFAULT_OUTPUT = os.path.join(os.path.dirname(REPO), "directory-pipeline", "output")

# Volumes flagged in master_directories.csv as held-out eval signatures — never harvest these,
# on any page. (README.md "Eval-held-out volumes"; NYU Trow 1850/51 lives outside this catalog.)
BANNED_IA_ITEMS = {"1897bpl"}

_IA_RE = re.compile(r"([A-Za-z0-9_.-]+?)_(\d{4})\.jp2", re.I)
_NYPL_RE = re.compile(r"^\d{4}_(\d{6,})\.jpg$")


def page_id(name: str) -> tuple:
    """Stable identity for a page image, independent of its download sequence prefix."""
    base = os.path.basename(urllib.parse.unquote(name))
    m = _NYPL_RE.match(base)
    if m:
        return ("nypl", m.group(1))
    m = _IA_RE.search(base)
    if m:
        return ("ia", m.group(1).lower(), m.group(2))
    return ("raw", base)


def gold_pages() -> dict:
    """Every page image referenced by any eval set -> the eval files that use it."""
    gold: dict = {}
    for path in sorted(globmod.glob(os.path.join(DATA_DIR, "*_eval.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                img = json.loads(line).get("context", {}).get("image")
                if img and img != "?":
                    gold.setdefault(page_id(img), set()).add(os.path.basename(path))
    return gold


def _self_test() -> int:
    ia = "0021_merceinscitydire00merc%2F...%2Fmerceinscitydire00merc_0138.jp2.jpg"
    assert page_id(ia) == ("ia", "merceinscitydire00merc", "0138"), page_id(ia)
    # Same page, different download prefix -> same identity. This is the whole point.
    assert page_id(ia) == page_id(ia.replace("0021_", "0003_", 1))
    assert page_id("0021_58064839.jpg") == ("nypl", "58064839")
    assert page_id("0001_58064839.jpg") == page_id("0021_58064839.jpg")
    assert page_id("weird.png") == ("raw", "weird.png")
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT,
                    help="directory-pipeline output/ root (default: sibling checkout)")
    ap.add_argument("--glob", default="harvest_*",
                    help="slice directory glob to check (default: harvest_*)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    gold = gold_pages()
    n_eval = len(globmod.glob(os.path.join(DATA_DIR, "*_eval.jsonl")))
    print(f"eval sets scanned  : {n_eval}")
    print(f"distinct gold pages: {len(gold)}")

    by_slug: dict = {}
    harvested: dict = {}
    for d in sorted(globmod.glob(os.path.join(args.output_dir, args.glob))):
        if not os.path.isdir(d):
            continue
        for p in sorted(globmod.glob(os.path.join(d, "*.jpg"))):
            pid = page_id(os.path.basename(p))
            harvested[pid] = os.path.basename(d)
            by_slug.setdefault(os.path.basename(d), []).append(pid)
    print(f"harvested pages    : {len(harvested)} across {len(by_slug)} slices")
    print()

    for slug in sorted(by_slug):
        ids = by_slug[slug]
        bad = [i for i in ids if i in gold]
        src = ids[0][1] if ids else "?"
        print(f"  {slug:30} {len(ids):3} pages  source={src[:32]:32} "
              f"{'*** LEAK ***' if bad else 'clean'}")
    print()

    status = 0
    clash = sorted(set(harvested) & set(gold))
    if clash:
        print("*** LEAKAGE DETECTED — remove these pages and re-extract the slice ***")
        for c in clash:
            print(f"  {c}  harvested in {harvested[c]}, used by gold {sorted(gold[c])}")
        status = 1
    else:
        print("PASS — no harvested page appears in any eval set.")

    hit = [(pid, s) for pid, s in harvested.items()
           if pid[0] == "ia" and pid[1] in BANNED_IA_ITEMS]
    if hit:
        print(f"FAIL — pages from a REVIEW-flagged held-out volume: {hit}")
        status = 1
    else:
        print("PASS — no pages from REVIEW-flagged held-out volumes.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
