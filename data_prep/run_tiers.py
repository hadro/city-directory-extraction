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
    check   ABBYY-8 (Allen County: Trow 1903-1917, Brooklyn 1909-1912, Trow 1922/23) and the
            Allen County Trow scans that predate the `ocr` field. Their lines are near-right,
            87-99% close to their ABBYY-9/11 twins, but 30-58% exact (reocr_bench.py, PIPELINE
            #27), and in run 2 Trow 1907 scored 7.4 row EM on IA's lines against 77.9 on clean
            text. The real-OCR panel's trow1907 and Polk 1917 sets decide: move the tier to
            `first` if this week's fixes closed the gap.
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
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIDECARS = HERE / "survey"
OUT = HERE / "run_tiers.json"
sys.path.insert(0, str(REPO / "hpc"))

from prep_volumes import corpus_ids, planned_lines  # noqa: E402

H200_ROWS_S = 11.88
OVERRIDES = {
    "flushingnewyorkc00boyd": ("first", "Boyd 1890: IA lines 61 of 74 identical to gold after #26"),
    "flushingnewyork188586boyd": ("first", "Boyd's Flushing series, as Boyd 1890"),
    "flushingnewyork189192boyd": ("first", "Boyd's Flushing series, as Boyd 1890"),
    "brooklynnewyorkc19123broo": ("defer", "typical listing page 0.04 entry-shaped (ABBYY-8 "
                                           "median 0.60); 186 pages failed OCR: re-OCR whole"),
}


def tier_of(ident: str, doc: dict):
    """(tier, why) from the volume's OCR family, before overrides."""
    ia = (doc.get("catalog_says") or {}).get("ia") or {}
    ocr = ia.get("ocr") or ""
    source = str(ia.get("contributor") or "")
    if ident.startswith("micro_IABROOKLYN_"):
        return "defer", "BPL microfilm, tesseract: 54% of a book scan's lines (reocr_bench)"
    if ocr.startswith("ABBYY FineReader 8"):
        return "check", "ABBYY-8: near-right lines, digit errors; decided by the panel's ABBYY-8 sets"
    if not ocr and source.startswith("Allen County"):
        return "check", "Allen County scan predating the `ocr` field: with the ABBYY-8 Trows"
    return "first", f"book scan, {ocr or 'pre-`ocr`-field OCR'} ({source or 'BPL'})"


def build() -> dict:
    vols, totals = {}, collections.defaultdict(lambda: {"volumes": 0, "lines": 0})
    for ident in corpus_ids():
        doc = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
        tier, why = OVERRIDES.get(ident) or tier_of(ident, doc)
        lines = planned_lines(ident, False)
        vols[ident] = {"tier": tier, "why": why, "lines": lines,
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
    assert tier_of("x", {"catalog_says": {"ia": {"ocr": "ABBYY FineReader 8.0"}}})[0] == "check"
    assert tier_of("x", {"catalog_says": {"ia": {"contributor": "Allen County Public Library"}}}
                   )[0] == "check"
    assert tier_of("x", {"catalog_says": {"ia": {"ocr": "ABBYY FineReader 9.0"}}})[0] == "first"
    assert tier_of("x", {"catalog_says": {"ia": {"contributor": "Columbia University Libraries"}}}
                   )[0] == "first"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    doc = build()
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    for tier in ("first", "check", "defer"):
        t = doc["totals"].get(tier, {})
        print(f"{tier:6s} {t.get('volumes', 0):4d} volumes {t.get('lines', 0):11,d} lines "
              f"~{t.get('h200_hours', 0):4d} H200-hours")
    print(f"-> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
