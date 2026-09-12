#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Every surname block header is dropped at ingest, and each one is a ditto antecedent.

    python3 results/surname_headers_dropped_1906BPL.py \
        --out results/surname_headers_dropped_1906BPL.json

Found 2026-09-12 while answering a labelling question -- "do the ALL-CAPS surnames at the top of a
column belong inside the listing body?" -- which turned out to have a pipeline consequence.

THE FINDING
-----------
A dense directory prints a shared surname ONCE as an ALL-CAPS header and dittos every entry under
it:

    ACME                                <- the antecedent
    " Hall 828 7th av                   <- means ACME Hall
    " Iron Foundry Co 280 N Henry       <- means ACME Iron Foundry Co

Measured on the same 150-leaf seeded sample as leaf_band_structure_1906BPL.py, counting ALL-CAPS
single-word lines that are immediately followed by a ditto-lead line:

    surname block headers found          156
    ... dropped by ia_volume_to_jsonl    156   (100%)
        as `short`  (under 8 chars)      123
        as `allcaps`                      33

Extrapolated to the 1,207-leaf listing span: **~1,255 headers per volume, none of which reach the
model or the post-processor.**

WHY IT MATTERS, AND WHAT IS NOT YET ESTABLISHED
-----------------------------------------------
`postprocess/resolve_dittos.py::cross_line_report` reads the kept-line JSONL, so it never sees a
header. At a block boundary the nearest preceding kept line belongs to the PREVIOUS surname, so
the carry does not merely lack an antecedent -- it has a confidently wrong one.

That is the mechanism. **The magnitude is NOT measured here**, and this file does not claim it.
PIPELINE.md next-step #6 records a 23.5% cross-line dispute rate "concentrated at leaf/column
boundaries"; whether surname-block boundaries are a material share of that is a separate
measurement that has not been run. Do not cite this as the cause of the dispute rate.

Both drop rules are doing what they were written to do -- `short` kills sub-8-char OCR fragments,
`allcaps` kills running heads -- and the headers are genuine casualties of both. The fix is
therefore not to loosen either rule but to recognise a header for what it is: an ALL-CAPS
alphabetic line followed by a ditto-lead line, which is the same follower test the per-volume
ditto glyph gate already uses.
"""

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_prep"))

from ia_volume_to_jsonl import Item, hocr_lines, text_reject      # noqa: E402

# Per-volume by construction, same caveat as the band measurement: these are 1906BPL's marks.
DITTO = re.compile(r'^\s*(44|"|“|”|\*\*|«)\s')
# A single ALL-CAPS word. Deliberately loose on length -- ABBYY mangles these (APPGEGATE for
# APPLEGATE), and a header stays a header when misread.
HEADER = re.compile(r"^[A-Z][A-Z'’]{2,14}$")

SEED = 20260910
LISTING_SPAN = (9, 1216)
N_SAMPLE = 150


def measure(ident, cache, span, n_sample, seed):
    item = Item(ident, cache)
    item.prefetch_hocr()
    random.seed(seed)
    sample = sorted(random.sample(range(*span), n_sample))

    n_caps = n_headers = 0
    reasons = Counter()
    examples = []
    for leaf in sample:
        markup = item.hocr_page(leaf)
        if not markup:
            continue
        pairs = hocr_lines(markup)
        for k, (_, text) in enumerate(pairs):
            text = text.strip()
            if not HEADER.match(text):
                continue
            n_caps += 1
            nxt = pairs[k + 1][1].strip() if k + 1 < len(pairs) else ""
            if not DITTO.match(nxt):
                continue
            n_headers += 1
            reason = text_reject(text)
            reasons[reason or "KEPT"] += 1
            if reason and len(examples) < 12:
                examples.append({"leaf": leaf, "header": text,
                                 "drop_reason": reason, "antecedent_for": nxt[:60]})

    span_leaves = span[1] - span[0]
    dropped = sum(n for r, n in reasons.items() if r != "KEPT")
    return {
        "ident": ident, "seed": seed, "span": list(span), "n_sampled": len(sample),
        "n_allcaps_single_word": n_caps,
        "n_surname_headers": n_headers,
        "n_dropped_at_ingest": dropped,
        "share_dropped": round(dropped / n_headers, 4) if n_headers else None,
        "drop_reasons": dict(reasons),
        "extrapolated_headers_in_span": round(n_headers * span_leaves / len(sample)),
        "examples": examples,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ident", default="1906BPL")
    ap.add_argument("--cache", default="data/ia_cache")
    ap.add_argument("--out", default="results/surname_headers_dropped_1906BPL.json")
    ap.add_argument("--n", type=int, default=N_SAMPLE)
    args = ap.parse_args(argv)

    res = measure(args.ident, Path(args.cache), LISTING_SPAN, args.n, SEED)
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    print(f"{res['ident']}  {res['n_sampled']} leaves, seed {res['seed']}", file=sys.stderr)
    print(f"  ALL-CAPS single-word lines        {res['n_allcaps_single_word']:5d}", file=sys.stderr)
    print(f"  ... followed by a ditto line      {res['n_surname_headers']:5d}"
          "   <- surname block headers", file=sys.stderr)
    print(f"  ... dropped at ingest             {res['n_dropped_at_ingest']:5d}"
          f"   ({res['share_dropped']:.0%})", file=sys.stderr)
    print(f"  reasons: {res['drop_reasons']}", file=sys.stderr)
    print(f"  extrapolated across the span: ~{res['extrapolated_headers_in_span']:,}",
          file=sys.stderr)
    for e in res["examples"][:5]:
        print(f"    leaf {e['leaf']:4d}  {e['header']:<12} {e['drop_reason']:<8} -> "
              f"{e['antecedent_for']}", file=sys.stderr)
    print(f"  wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
