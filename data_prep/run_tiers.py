#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Which run-set volumes the H200 reads first, which wait on a measurement, and which wait on a
re-OCR: the tiers hpc/prep_volumes.py --corpus --tier stages from.

    python3 data_prep/run_tiers.py            # -> data_prep/run_tiers.json, and the totals
    python3 data_prep/run_tiers.py --self-test

WHY (2026-10-05, hadro: "use the H200 only for those volumes that are likely to produce the
highest quality output, and not waste H200 hours on lines that we'll end up re-OCRing"). The
tier is a property of the scan, so it is set per volume from its OCR family, and a measured
exception overrides it:

    first   ABBYY-9/11 book scans (BPL, Columbia, Harvard) and the older Columbia/NYPL book
            scans. The corpus's best OCR: the Smith book scans read 81-83% of their gold lines
            exactly (survey_twins.py gold). 44% of the run's lines.
    abbyy8-clean / abbyy8-damaged
            ABBYY-8 (Allen County: Trow 1903-1917, Brooklyn 1905-1912, Trow 1922/23) and the
            Allen County Trow scans that predate the `ocr` field, split by their own numbers.
            Their lines are 87-99% close to their ABBYY-9/11 twins but 30-58% exact, and the
            errors are digits: ABBYY-8 reads 6 (Brooklyn's font) or 9 (Trow's) as 0. A leading
            0 is impossible in a house number or street ordinal, so its rate is a gold-free
            measure of a volume's digit damage (DAMAGE_RX; on the Brooklyn twins it ranks with
            the measured disagreement). The book scans' median is 0.08% and their worst tenth
            sits above 0.43%, so a volume at or below CLEAN (0.5%) is as clean as a book scan.
            Trow 1910-1917 sit at ~0.01%, the Trow 1903-1909 parts at 1.6-4.9%, Trow 1907 p2
            (run 2: 7.4 row EM on IA's lines) at the worst. The real-OCR panel's Polk 1917
            (clean) and trow1907 (damaged) sets test the split.
    defer   BPL microfilm with no book scan: IA's tesseract reproduces 54% of the book scan's
            lines on the 8 microfilm volumes that have one. The re-OCR targets (#27).

Overrides (OVERRIDES), each a measurement:
    Boyd's Flushing volumes are Allen County scans with no `ocr` field, but #26 brought Boyd
    1890's IA lines to 61 of 74 identical to the gold: first.
    Brooklyn 1912 p3 is ABBYY-8, but its typical listing page is 0.04 entry-shaped (the ABBYY-8
    median is 0.60) and 186 of its pages failed OCR: defer, for a re-OCR whole.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import gzip
import json
import multiprocessing
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIDECARS = HERE / "survey"
OUT = HERE / "run_tiers.json"
sys.path.insert(0, str(REPO / "hpc"))

from prep_volumes import corpus_ids, planned_lines  # noqa: E402

H200_ROWS_S = 11.88
CLEAN = 0.005
DAMAGE = REPO / "results" / "number_damage.json"
ORD = r"(?:st|nd|rd|th|d)"
DAMAGE_RX = re.compile(rf"^0\d+{ORD}?$|^0{ORD}$")
OVERRIDES = {
    "flushingnewyorkc00boyd": ("first", "Boyd 1890: IA lines 61 of 74 identical to gold after #26"),
    "flushingnewyork188586boyd": ("first", "Boyd's Flushing series, as Boyd 1890"),
    "flushingnewyork189192boyd": ("first", "Boyd's Flushing series, as Boyd 1890"),
    "brooklynnewyorkc19123broo": ("defer", "typical listing page 0.04 entry-shaped (ABBYY-8 "
                                           "median 0.60); 186 pages failed OCR: re-OCR whole"),
}


def damage(ident: str):
    """(number tokens, leading-zero tokens) over the volume's listing-scoped lines, the first
    token of each line excepted (a ditto reading may be a digit)."""
    nums = bad = 0
    with gzip.open(REPO / "data" / "survey_ocr" / f"{ident}_listing.jsonl.gz", "rt",
                   encoding="utf-8") as fh:
        for line in fh:
            for tok in json.loads(line)["raw_line"].split()[1:]:
                t = tok.strip(",.;:")
                if any(c.isdigit() for c in t):
                    nums += 1
                    bad += bool(DAMAGE_RX.match(t))
    return ident, nums, bad


def damages(ids: list, rescan: bool) -> dict:
    """ident -> leading-zero rate, cached in results/number_damage.json (--rescan refreshes)."""
    cached = json.loads(DAMAGE.read_text(encoding="utf-8"))["volumes"] if DAMAGE.exists() else {}
    if rescan or set(ids) - set(cached):
        with multiprocessing.Pool(7) as pool:
            res = pool.map(damage, ids)
        cached = {i: {"numbers": n, "leading_zero": b, "rate": round(b / max(1, n), 5)}
                  for i, n, b in res}
        DAMAGE.write_text(json.dumps({
            "derived": _dt.date.today().isoformat(),
            "method": "number tokens (any digit) after the first token of each listing-scoped "
                      "line; leading_zero: a house number or ordinal opening with 0 (DAMAGE_RX)",
            "volumes": cached}, indent=1) + "\n", encoding="utf-8")
    return {i: cached[i]["rate"] for i in ids}


def tier_of(ident: str, doc: dict, rate: float = 0.0):
    """(tier, why) from the volume's OCR family and digit damage, before overrides."""
    ia = (doc.get("catalog_says") or {}).get("ia") or {}
    ocr = ia.get("ocr") or ""
    source = str(ia.get("contributor") or "")
    if ident.startswith("micro_IABROOKLYN_"):
        return "defer", "BPL microfilm, tesseract: 54% of a book scan's lines (reocr_bench)"
    if ocr.startswith("ABBYY FineReader 8") or (not ocr and source.startswith("Allen County")):
        if rate <= CLEAN:
            return "abbyy8-clean", f"ABBYY-8, leading-zero numbers {rate:.2%}: as clean as a book scan"
        return "abbyy8-damaged", f"ABBYY-8, leading-zero numbers {rate:.2%}: digits damaged"
    return "first", f"book scan, {ocr or 'pre-`ocr`-field OCR'} ({source or 'BPL'})"


def build(rescan: bool = False) -> dict:
    vols, totals = {}, collections.defaultdict(lambda: {"volumes": 0, "lines": 0})
    ids = corpus_ids()
    rates = damages(ids, rescan)
    for ident in ids:
        doc = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
        tier, why = OVERRIDES.get(ident) or tier_of(ident, doc, rates[ident])
        lines = planned_lines(ident, False)
        vols[ident] = {"tier": tier, "why": why, "lines": lines, "leading_zero": rates[ident],
                       "overridden": ident in OVERRIDES}
        totals[tier]["volumes"] += 1
        totals[tier]["lines"] += lines
    for t in totals.values():
        t["h200_hours"] = round(t["lines"] / H200_ROWS_S / 3600)
    return {"_doc": "Tiers for the corpus run: data_prep/run_tiers.py builds this; "
                    "hpc/prep_volumes.py --corpus --tier <tier> stages one. See the script.",
            "built": _dt.date.today().isoformat(), "totals": dict(totals), "volumes": vols}


def _self_test() -> int:
    assert tier_of("micro_IABROOKLYN_0039", {})[0] == "defer"
    a8 = {"catalog_says": {"ia": {"ocr": "ABBYY FineReader 8.0"}}}
    assert tier_of("x", a8, 0.0001)[0] == "abbyy8-clean", "Trow 1915: 0.00%"
    assert tier_of("x", a8, 0.0487)[0] == "abbyy8-damaged", "Trow 1907 p2: 4.87%"
    assert tier_of("x", {"catalog_says": {"ia": {"contributor": "Allen County Public Library"}}},
                   0.0167)[0] == "abbyy8-damaged", "Trow 1903 p2, no ocr field: 1.67%"
    assert DAMAGE_RX.match("08th") and DAMAGE_RX.match("05") and DAMAGE_RX.match("0th")
    assert not DAMAGE_RX.match("0") and not DAMAGE_RX.match("10th") and not DAMAGE_RX.match("205")
    assert tier_of("x", {"catalog_says": {"ia": {"ocr": "ABBYY FineReader 9.0"}}})[0] == "first"
    assert tier_of("x", {"catalog_says": {"ia": {"contributor": "Columbia University Libraries"}}}
                   )[0] == "first"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rescan", action="store_true", help="recompute results/number_damage.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    doc = build(args.rescan)
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for tier in ("first", "abbyy8-clean", "abbyy8-damaged", "defer"):
        t = doc["totals"].get(tier, {})
        print(f"{tier:15s} {t.get('volumes', 0):4d} volumes {t.get('lines', 0):11,d} lines "
              f"~{t.get('h200_hours', 0):4d} H200-hours")
    print(f"-> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
