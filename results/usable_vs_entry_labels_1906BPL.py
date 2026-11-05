#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""How often does the released `usable` flag keep a line a person judged NOT an entry?

    python3 results/usable_vs_entry_labels_1906BPL.py
    python3 results/usable_vs_entry_labels_1906BPL.py --out results/usable_vs_entry_labels_1906BPL.json

WHY THIS EXISTS. The records card says `usable` "removes most" of the lines that are not entries
(advertising, running heads, tails of wrapped entries). Written 2026-11-05 for the second blog
post (docs/drafts/blog-post-2-other-cities.md) to put a number on "most". No new labelling: it
joins the 140 hand labels of results/entry_rate_validation_1906BPL.py (data/entry_labels_1906BPL.jsonl,
35 lines per part of the page, the labeller blind to `is_entry` and to the band) to the records in
data/browse.db.

TWO COPIES. browse.db holds 1906BPL twice (records_superseded has the run-1 copy since PIPELINE
#41, records the other): the run-1 copy, assembled from IA's own OCR lines (the
lines the labels were drawn from), and the first/clean tier's copy, from LightOnOCR's re-read. The
run-1 copy is the one to read; the re-OCR copy's text differs, so fewer labels join there.

THE JOIN. By leaf and printed text (whitespace collapsed); where that finds nothing, by leaf and
the text after the first token (a leading ditto mark is normalised on the record and not on the
label), kept only if exactly one record matches. 107 of 140 join. The 33 that do not are mostly in
the unbanded stratum, whose lines the banner correction (docs/BANNER_CORRECTION.md) and later
assembly changed. The 3 `unsure` labels are left out.

CAVEATS THAT TRAVEL WITH THE NUMBER.
  * The sample is balanced across the page, not drawn by volume share: it holds far more
    advertising than the volume does (the body is 94% of lines and almost all entries).
    "61 of 65 removed" is the filter's catch rate on that mix, not the share of released records
    that are not entries. That second number needs a stratified audit of `usable` records.
  * One volume (a dense Brooklyn book scan, run 1).
  * Some labelled lines were held out for evaluation, which is itself a reason for `usable` to be
    false; the table counts them as removed.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LABELS = REPO / "data" / "entry_labels_1906BPL.jsonl"
DB = REPO / "data" / "browse.db"
VOLUME = "1906BPL"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def match(rows: list, raw: str):
    hit = [r for r in rows if norm(r[1]) == norm(raw)]
    if hit:
        return hit[0]
    parts = norm(raw).split(" ", 1)
    hit = [r for r in rows if len(parts) > 1 and norm(r[1]).endswith(parts[1])]
    return hit[0] if len(hit) == 1 else None


ROOTS = ("data/volumes_run1", "data/volumes_books_first_clean_v2")
# the run-1 copy is set aside in records_superseded since PIPELINE #41 (browse/sources.toml)
TABLE = {"data/volumes_run1": "records_superseded", "data/volumes_books_first_clean_v2": "records"}


def run(root: str) -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    labels = [json.loads(line) for line in open(LABELS, encoding="utf-8") if line.strip()]
    table, by_band, survivors, unmatched = collections.Counter(), collections.defaultdict(collections.Counter), [], 0
    for lab in labels:
        if lab["label"] == "unsure":
            continue
        rows = con.execute(f"select usable, raw_line, role, entry_shaped from {TABLE[root]} "
                           "where volume=? and leaf=? and root=?", (VOLUME, lab["leaf"], root)).fetchall()
        rec = match(rows, lab["raw_line"])
        if rec is None:
            unmatched += 1
            continue
        table[(lab["label"], bool(rec[0]))] += 1
        by_band[lab["band"]][(lab["label"], bool(rec[0]))] += 1
        if lab["label"] == "not-entry" and rec[0]:
            survivors.append({"raw_line": lab["raw_line"], "category": lab["category"], "band": lab["band"]})
    removed, kept = table[("not-entry", False)], table[("not-entry", True)]
    return {
        "volume": VOLUME, "root": root, "labels": len(labels), "joined": len(labels) - 3 - unmatched, "unmatched": unmatched,
        "not_entry": {"removed_by_usable": removed, "kept_as_usable": kept,
                      "removed_pct": round(100 * removed / (removed + kept), 1)},
        "entry": {"usable": table[("entry", True)], "not_usable": table[("entry", False)]},
        "by_band": {b: {f"{k[0]}:{'usable' if k[1] else 'not_usable'}": v for k, v in c.items()}
                    for b, c in by_band.items()},
        "survivors": survivors,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    args = ap.parse_args()
    results = [run(root) for root in ROOTS]
    for res in results:
        ne, e = res["not_entry"], res["entry"]
        print(f"[{res['root']}] {res['joined']} of {res['labels'] - 3} labelled lines join ({res['unmatched']} do not)")
        print(f"  judged not an entry: {ne['removed_by_usable'] + ne['kept_as_usable']}; "
              f"`usable` removed {ne['removed_by_usable']} ({ne['removed_pct']}%), kept {ne['kept_as_usable']}")
        for s in res["survivors"]:
            print(f"     kept: [{s['category']}, {s['band']}] {s['raw_line']}")
        print(f"  judged real entries: {e['usable'] + e['not_usable']}; usable {e['usable']}, not usable {e['not_usable']}")
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
