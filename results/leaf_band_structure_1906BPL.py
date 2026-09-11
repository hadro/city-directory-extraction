#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Where on a leaf do listing entries actually live? (1906BPL, 150-leaf sample)

    python3 results/leaf_band_structure_1906BPL.py --out results/leaf_band_structure_1906BPL.json

Run 2026-09-10 as phase 0 of docs/PAGE_TYPE_CLASSIFIER.md. It was meant as a sanity check on six
hand-identified leaves and instead invalidated that plan's unit of analysis, so it is persisted
with its numbers rather than summarised.

THE FINDING
-----------
Display advertising in this volume is not sold by the page. It is sold as a STRIP across the head
and foot of ordinary listing pages, and the listing body between the strips is clean.

Measured by the vertical position of ditto-lead lines -- `44`, `"`, `“` -- which are 42% of this
volume's lines, are near-impossible in ad copy, and therefore mark "inside a listing run" about as
unambiguously as anything available without labels:

    decile of page height   ditto-lead / all lines
    0.0-0.1                      6 /   816   0.7%     <- head strip: NO listing entries
    0.1-0.9                 16,356 / 36,049   45%     <- body: uniformly listing, flat
    0.9-1.0                      0 /   708   0.0%     <- foot strip: NO listing entries

141 of 150 sampled listing-span leaves carry >= 20 ditto lines, so **~94% of the listing span is
a MIXED leaf** -- ad strip, listing body, ad strip. The six leaves the earlier tools cite by hand
are all of this shape, including both of the ones called "genuine listing":

    leaf 13  (cited genuine listing)  lines 0-6 are a detective-agency ad; body from line 7
    leaf 200 (cited genuine listing)  lines 0-11 an Upington ad; body from 12; 214-217 a foot ad
    leaf 26  (cited ad leaf)          ad head and foot, but lines ~150-170 are real entries

WHAT IT INVALIDATES
-------------------
A leaf-level page-type classifier, which is what PAGE_TYPE_CLASSIFIER.md phase 1 proposed. Its
`mixed` escape hatch would swallow 94% of the listing span, leaving a headline number computed on
an unrepresentative remainder. The unit has to be a BAND WITHIN a leaf, not the leaf.

It also reframes `detect_listing_bounds.py --interior drop`, whose cost was recorded as "~172
genuine listing leaves lost". Those leaves are mixed, so the cut does not trade junk for junk --
it discards ~172 clean listing bodies in order to remove their strips. A band-level instrument
dominates any leaf-level decision here by construction.

WHAT IT DOES NOT SETTLE
-----------------------
- One volume, one engine, one publisher. Upington 1906 sells strip ads; franks1786 is a single
  column folio with no display advertising at all. Nothing here transfers unmeasured.
- The ditto-lead proxy marks listing runs, NOT non-listing text. A head strip containing zero
  ditto lines is consistent with "ad" and equally with "running head the text filter already
  kills", and this measurement cannot tell those apart. It bounds where the body IS; it does not
  prove what the bands contain. Reading the bands is phase 1's job.
- The 166 full-page ad leaves in the letter-block gaps are a genuinely separate population and
  are not sampled here -- the sample is drawn across the whole listing span, so they are present
  only in proportion.
"""

import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_prep"))

from ia_volume_to_jsonl import Item, hocr_lines, page_dims     # noqa: E402

# Leading ditto marks admitted on 1906BPL by ia_volume_to_jsonl.py's per-volume gate, plus « from
# the review queue. Per-volume by construction -- do NOT reuse this literal on another book.
DITTO = re.compile(r'^\s*(44|"|“|”|\*\*|«)\s')

SEED = 20260910
LISTING_SPAN = (9, 1216)      # detect_listing_bounds.py on 1906BPL
N_SAMPLE = 150
N_BANDS = 10


def measure(ident, cache, span, n_sample, seed):
    item = Item(ident, cache)
    item.prefetch_hocr()
    random.seed(seed)
    sample = sorted(random.sample(range(*span), n_sample))

    bands = [[0, 0] for _ in range(N_BANDS)]
    per_leaf = []
    for leaf in sample:
        markup = item.hocr_page(leaf)
        if not markup:
            continue
        pairs, dims = hocr_lines(markup), page_dims(markup)
        if not pairs or not dims:
            continue
        height = dims[1]
        ys = []
        for (_, y0, _, _), text in pairs:
            band = min(N_BANDS - 1, max(0, int((y0 / height) * N_BANDS)))
            bands[band][1] += 1
            if DITTO.match(text):
                bands[band][0] += 1
                ys.append(y0 / height)
        if len(ys) >= 20:
            per_leaf.append({"leaf": leaf, "first_y": min(ys), "last_y": max(ys),
                             "ditto_share": len(ys) / len(pairs)})

    return {
        "ident": ident, "seed": seed, "span": list(span), "n_sampled": len(sample),
        "bands": [{"lo": i / N_BANDS, "hi": (i + 1) / N_BANDS, "ditto": d, "all": a,
                   "share": round(d / a, 4) if a else None}
                  for i, (d, a) in enumerate(bands)],
        "n_leaves_with_body": len(per_leaf),
        "share_leaves_mixed": round(len(per_leaf) / len(sample), 4),
        "median_first_ditto_y": round(statistics.median(r["first_y"] for r in per_leaf), 4),
        "median_last_ditto_y": round(statistics.median(r["last_y"] for r in per_leaf), 4),
        "median_ditto_share": round(statistics.median(r["ditto_share"] for r in per_leaf), 4),
        "per_leaf": per_leaf,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ident", default="1906BPL")
    ap.add_argument("--cache", default="data/ia_cache")
    ap.add_argument("--out", default="results/leaf_band_structure_1906BPL.json")
    ap.add_argument("--n", type=int, default=N_SAMPLE)
    args = ap.parse_args(argv)

    res = measure(args.ident, Path(args.cache), LISTING_SPAN, args.n, SEED)
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    print(f"{res['ident']}  {res['n_sampled']} leaves sampled, seed {res['seed']}", file=sys.stderr)
    for b in res["bands"]:
        bar = "#" * int(60 * (b["share"] or 0))
        print(f"  {b['lo']:.1f}-{b['hi']:.1f}  {b['ditto']:6d}/{b['all']:6d}  "
              f"{b['share']:.3f}  {bar}", file=sys.stderr)
    print(f"\n  mixed leaves: {res['n_leaves_with_body']}/{res['n_sampled']} "
          f"({res['share_leaves_mixed']:.1%})", file=sys.stderr)
    print(f"  body spans y {res['median_first_ditto_y']:.3f} .. "
          f"{res['median_last_ditto_y']:.3f} (medians)", file=sys.stderr)
    print(f"  wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
