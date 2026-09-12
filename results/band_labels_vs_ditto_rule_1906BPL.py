#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What 197 hand-labelled bands say about whether a model is needed at all.

    python3 results/band_labels_vs_ditto_rule_1906BPL.py \
        --labels data/bands_1906BPL_train.jsonl \
        --out results/band_labels_vs_ditto_rule_1906BPL.json

Phase 1 of docs/PAGE_TYPE_CLASSIFIER.md, first labelled batch, 2026-09-12.

THE HEADLINE, AND IT IS TWO-SIDED
---------------------------------
A one-line deterministic rule -- take the extent of ditto-lead lines and expand it by 0.015 of
page height at each end -- **admits no advertising at all on 183 of 190 leaves (96%)**, and
matches the human label exactly, in both directions, on **150 of 190 (79%)**. The other 33 lose a
line or two of listing, which is the harmless direction. Total disagreement is 0.42% of lines.

On those numbers a trained band model has almost no room to earn its keep, which is what the
pre-registered "beat the first-and-last-ditto rule" bar was there to find out.

**But the aggregate hides the failure that matters, exactly as `entry_rate.py` does.** The rule
wrongly admits 80 non-listing lines in total, and **71 of those 80 (89%) come from 6 leaves**:

    leaf  ad lines admitted
     904               22
     118               10
     416               10
     678               10
    1098               10
      86                9

Every admitted line is advertising, and advertising admitted is a fabricated person -- the single
failure this whole plan exists to prevent. The rule is not 96% right; it is exactly right almost
everywhere and catastrophically wrong on ~4% of leaves.

WHY IT FAILS, AND WHY THAT DECIDES THE INSTRUMENT
--------------------------------------------------
`44` is ABBYY's reading of the ditto mark AND a literal street number. The Temple Bar law-company
advertisement, which recurs through the volume, carries the line:

    44 COURT ST.

The ditto regex matches it, so the "first ditto line" lands *inside the advertisement* and drags
the top edge up with it. On leaf 904 that admits 22 lines of pure ad copy -- `Law of Real
Property`, `Mammoth Storage Warehouses and Moving Vans`, `PETER F. REILLY, Proprietor`.

Measured independently on a fresh 300-leaf sample: a ditto-matching line that is really a bare
street address appears on **3.3% of leaves**, and 8 of the 10 found are the same `44 COURT ST.`
advertisement. That agrees with the 7/190 (3.7%) failure rate seen against the labels.

**So the residual is a text problem, not a geometry problem.** Separating `44 COURT ST.` from
`44 Wm elk h 86 Laf av` requires reading the line; no threshold on position or extent can do it.
That is a much sharper target than the band regressor this plan originally proposed: do not train
a model to predict edges -- 96% of edges need no model -- train or write one that decides whether
a ditto-matching line is a ditto.

(Caution, recorded because it nearly went into the writeup as fact: a first pass at the street
address regex allowed `\\s*` between the name and the street-type word, so `Ernst` matched as
`Ern` + `st` and the rate came out at 59.7% -- about 8x too high. The version here requires the
street word to be its own token.)

WHAT THESE LABELS CANNOT SETTLE
-------------------------------
1. **Anchoring.** They were made with the prefill drawn on screen, so "human agrees with prefill
   plus a constant" is partly circular -- it measures how the labeller adjusted a starting guess,
   not whether either is right. The 7 large deliberate corrections argue against pure anchoring,
   but do not dispose of it. **The --blind evaluation set is now the load-bearing measurement,
   not an optional rigour step**, and until it exists none of the agreement numbers above should
   be quoted as accuracy.
2. **Strip contents carry no information.** `head_touched` and `foot_touched` are false on all
   193 body leaves: every strip label is the untouched default `["advertising"]`. This is what the
   `_touched` bookkeeping was added for. Do not analyse, count, or train on the strip fields from
   this batch.
3. **4 leaves marked `has_body: false` have `page_type: null`** -- recorded as non-listing but not
   classified. All four read as full-page advertising, but that is not what the file says and it
   is not inferred here.
4. One volume, one engine, one publisher, one labeller.
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_prep"))

from ia_volume_to_jsonl import Item, hocr_lines, page_dims       # noqa: E402

OFFSETS = [0.0, 0.010, 0.015, 0.020]


def line_ys(item, leaf):
    markup = item.hocr_page(leaf)
    if not markup:
        return None
    pairs, dims = hocr_lines(markup), page_dims(markup)
    if not pairs or not dims:
        return None
    return [b[1] / dims[1] for b, _ in pairs]


def analyse(labels_path, ident, cache):
    rows = [json.loads(l) for l in Path(labels_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    body = [r for r in rows if r["has_body"]]
    gold = [r for r in body if r["prefill_top"] is not None]
    item = Item(ident, cache)
    item.prefetch_hocr()

    dt = [r["body_top"] - r["prefill_top"] for r in gold]
    db = [r["body_bottom"] - r["prefill_bottom"] for r in gold]

    rules = {f"prefill+/-{o:.3f}": {"lost": 0, "admitted": 0, "exact_leaves": 0,
                                    "clean_leaves": 0, "per_leaf": []}
             for o in OFFSETS}
    n_lines = 0
    for r in gold:
        ys = line_ys(item, r["leaf"])
        if ys is None:
            continue
        n_lines += len(ys)
        truth = {i for i, y in enumerate(ys) if r["body_top"] <= y <= r["body_bottom"]}
        for o in OFFSETS:
            got = {i for i, y in enumerate(ys)
                   if r["prefill_top"] - o <= y <= r["prefill_bottom"] + o}
            k = f"prefill+/-{o:.3f}"
            lost, extra = len(truth - got), len(got - truth)
            rules[k]["lost"] += lost
            rules[k]["admitted"] += extra
            rules[k]["exact_leaves"] += (lost == 0 and extra == 0)
            # Tracked separately because the two errors are not equally bad: admitting an ad line
            # fabricates a person, losing a listing line loses a record. Only the first is a
            # correctness failure.
            rules[k]["clean_leaves"] += (extra == 0)
            rules[k]["per_leaf"].append({"leaf": r["leaf"], "admitted": extra, "lost": lost})

    for k, v in rules.items():
        worst = sorted(v["per_leaf"], key=lambda d: -d["admitted"])
        v["worst_6"] = worst[:6]
        v["admitted_share_from_worst_6"] = (
            round(sum(d["admitted"] for d in worst[:6]) / v["admitted"], 4) if v["admitted"] else 0.0)
        del v["per_leaf"]

    return {
        "ident": ident, "labels": str(labels_path), "n_rows": len(rows),
        "n_body": len(body), "n_no_body": len(rows) - len(body),
        "n_irregular": sum(r["irregular"] for r in rows),
        "n_scored": len(gold), "n_lines": n_lines,
        "no_body_missing_page_type": [r["leaf"] for r in rows
                                      if not r["has_body"] and not r.get("page_type")],
        "strip_labels_touched": {
            "head": sum(bool(r.get("head_touched")) for r in body),
            "foot": sum(bool(r.get("foot_touched")) for r in body),
            "of": len(body),
        },
        "edge_delta": {
            "top": {"median": round(statistics.median(dt), 4), "min": round(min(dt), 4),
                    "max": round(max(dt), 4),
                    "modal": Counter(round(x, 4) for x in dt).most_common(1)[0]},
            "bottom": {"median": round(statistics.median(db), 4), "min": round(min(db), 4),
                       "max": round(max(db), 4),
                       "modal": Counter(round(x, 4) for x in db).most_common(1)[0]},
        },
        "rules": rules,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default="data/bands_1906BPL_train.jsonl")
    ap.add_argument("--ident", default="1906BPL")
    ap.add_argument("--cache", default="data/ia_cache")
    ap.add_argument("--out", default="results/band_labels_vs_ditto_rule_1906BPL.json")
    args = ap.parse_args(argv)

    res = analyse(args.labels, args.ident, Path(args.cache))
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    e = sys.stderr
    print(f"{res['n_rows']} labelled leaves — {res['n_body']} body, {res['n_no_body']} no-body, "
          f"{res['n_irregular']} irregular", file=e)
    t = res["strip_labels_touched"]
    print(f"strip labels actually set: head {t['head']}/{t['of']}, foot {t['foot']}/{t['of']}"
          f"{'   <- UNUSABLE, all default' if not (t['head'] or t['foot']) else ''}", file=e)
    if res["no_body_missing_page_type"]:
        print(f"no-body leaves lacking page_type: {res['no_body_missing_page_type']}", file=e)
    ed = res["edge_delta"]
    print(f"\nedge movement vs prefill: top median {ed['top']['median']:+.4f} "
          f"(modal {ed['top']['modal'][0]:+.4f} x{ed['top']['modal'][1]}), "
          f"bottom {ed['bottom']['median']:+.4f} "
          f"(modal {ed['bottom']['modal'][0]:+.4f} x{ed['bottom']['modal'][1]})", file=e)
    print(f"\n{'rule':<19}{'no ad admitted':>16}{'exact both ways':>17}"
          f"{'listing lost':>14}{'ad admitted':>13}{'worst 6':>9}", file=e)
    for k, v in res["rules"].items():
        print(f"{k:<19}{v['clean_leaves']:>10}/{res['n_scored']:<5}"
              f"{v['exact_leaves']:>11}/{res['n_scored']:<5}{v['lost']:>14,}"
              f"{v['admitted']:>13,}{v['admitted_share_from_worst_6']:>9.0%}", file=e)
    best = res["rules"]["prefill+/-0.015"]
    print("\nworst leaves for prefill+/-0.015: "
          + ", ".join(f"{d['leaf']}({d['admitted']})" for d in best["worst_6"]), file=e)
    print(f"wrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
