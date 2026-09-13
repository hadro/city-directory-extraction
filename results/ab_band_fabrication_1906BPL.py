#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Result: the band separates fabrication 98:1, and 1906BPL's real rate is 5.6%, not 10.4%.

    python3 results/ab_band_fabrication_1906BPL.py \
        --out results/ab_band_fabrication_1906BPL.json

Pre-registered in ab_band_fabrication_1906BPL_PREREGISTRATION.md, written before the sample was
drawn. 600 lines, 150 per band, seed 20260913, adapter 2b-100k, predictions persisted in
ab_band_fabrication_1906BPL_preds/ before this file was written. Throughput held at 0.42 rows/s
against the 0.38-0.6 baseline, so the MPS run was genuinely computing.

THE NUMBERS
-----------
    band        n   not-real    rate    95% CI          volume share
    body      150          1    0.7%   [ 0.1%,  3.7%]        93.70%
    head      150        114   76.0%   [68.6%, 82.1%]         0.71%
    foot      150         83   55.3%   [47.3%, 63.1%]         0.77%
    unbanded  150        126   84.0%   [77.3%, 89.0%]         4.83%

    strip (head+foot) 65.7%  vs  body 0.7%   ->  98.5x
    stratified volume estimate: 5.6%

All three pre-registered decision rules fire:

1. **strip >= 3x body -> confirmed.** At 98.5x it is not close. `context.band` is a fabrication
   filter, not only a geometric one, and the 17.7x seen on the top-of-page sample understated it
   because that sample's "body" lines were themselves top-of-page.
2. **unbanded >= 50% -> unbanded leaves earn their own treatment.** At 84.0% they are the single
   worst stratum and they are 4.83% of the volume, so they carry more absolute fabrication than
   head and foot combined. Phase 3 of PAGE_TYPE_CLASSIFIER.md becomes load-bearing.
3. **the volume estimate differs from 10.4% by more than 2 points -> the published figure is
   replaced.** 5.6% stratified against 10.4% top-of-page.

WHAT CUTTING WOULD BUY, AT WHAT PRICE
--------------------------------------
Body alone is 93.70% of lines at 0.7% not-real. Cutting strip and unbanded lines therefore takes
fabrication from **5.6% to 0.66%** -- an 88% reduction -- at a cost of the real entries inside those
strata: 0.71%x24% + 0.77%x45% + 4.83%x16% = **~1.3% of all kept lines**. That trade is now measured
rather than assumed, which is what the band was built to make possible.

It is still not licence to cut at ingest. `alpha_run_filter --apply` is off because a ditto whose
parent surname was cut has nothing to point at, and the same applies here.

THE POSITIONAL EFFECT IS REAL, AND LARGER THAN EXPECTED
--------------------------------------------------------
Secondary observation 1, pre-registered. The same `body` band measures **4.7% not-real on
top-of-page lines** (band_vs_fabrication_1906BPL.py, n=464) against **0.7% here** (n=150, uniform).
A 6.7x difference *within one band*, which is why the old 10.4% was inflated twice over: it
over-sampled head lines AND sampled the worst part of the body band. Body lines adjacent to the
band's top edge sit next to advertising and are sometimes still advertising.

NOT ALL "NOT-REAL" IS FABRICATION, AND THE UNBANDED STRATUM SHOWS IT
---------------------------------------------------------------------
Secondary observation 2. The head and foot misses are unambiguous ad copy -- `GEORGE H. WILLERS,
Proprietor`, `French and American, all flavors.`, `Allows Interest on Depos-`. The single body miss
is OCR wreckage: `Evkrslkt Childs`.

But the unbanded misses are different in kind:

    Abraham & Straus, dry goods
    Federal Audit Co., public accountants

Those are **genuine business-directory entries**, scored not-real only because `is_entry` requires
an address-shaped string. So part of the unbanded stratum's 84% is real directory content of a
different type, not fabricated people. Before treating unbanded leaves as junk, read them --
a business directory is data this project may want, and PIPELINE.md's catalog already distinguishes
residential from business sections.

WHAT THIS DOES NOT SETTLE
-------------------------
- **Proxy, not gold.** `is_entry` cannot see field-boundary quality; `name='44 Wm elk'` with an
  empty occupation scores as a perfect entry. This is fabrication, never record quality (#10).
- **One volume, one engine, one adapter.** The thin tesseract tier has no bands at all, and its
  20.7% was measured on all 2,889 lines, so it is NOT subject to this sampling bias -- meaning the
  old "clean tier is 2x better" comparison was not like-for-like in the direction assumed. Against
  5.6% the real gap is ~3.7x, and re-measuring the microfilm volume the same way is the check.
- **150 per stratum** resolves roughly +/-8 points at 50%. Head vs foot (76.0% vs 55.3%) is outside
  that and looks real; smaller differences would not be.
"""

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

from entry_rate import fields, is_entry        # noqa: E402

PREDS = ROOT / "results" / "ab_band_fabrication_1906BPL_preds"


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preds", default=str(PREDS))
    ap.add_argument("--lines", default="data/1906BPL_lines.jsonl")
    ap.add_argument("--out", default="results/ab_band_fabrication_1906BPL.json")
    args = ap.parse_args(argv)

    p = Path(args.preds)
    rows = [json.loads(l) for l in (p / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    blocks = [b for b in re.split(r"\n\s*\n", (p / "preds.txt").read_text(encoding="utf-8"))
              if b.strip()]
    if len(blocks) != len(rows):
        raise SystemExit(f"{len(blocks)} predictions vs {len(rows)} inputs — refusing to score")

    mix = Counter(json.loads(l)["context"].get("band")
                  for l in Path(args.lines).read_text(encoding="utf-8").splitlines() if l.strip())
    n_vol = sum(mix.values())

    tot, bad, examples = Counter(), Counter(), defaultdict(list)
    for blk, r in zip(blocks, rows):
        s = r["context"]["_stratum"]
        tot[s] += 1
        if not is_entry(fields(blk)):
            bad[s] += 1
            if len(examples[s]) < 5:
                examples[s].append(r["raw_line"][:70])

    by_band, estimate, real_lost = {}, 0.0, 0.0
    for s, key in (("body", "body"), ("head", "head"), ("foot", "foot"), ("None", None)):
        n, k = tot[s], bad[s]
        share = mix[key] / n_vol
        rate = k / n
        estimate += share * rate
        if s != "body":
            real_lost += share * (1 - rate)
        by_band[s] = {"n": n, "not_real": k, "rate": round(rate, 4),
                      "ci95": wilson(k, n), "volume_share": round(share, 6)}

    strip_n = tot["head"] + tot["foot"]
    strip_k = bad["head"] + bad["foot"]
    body_rate = by_band["body"]["rate"]
    res = {
        "preregistration": "results/ab_band_fabrication_1906BPL_PREREGISTRATION.md",
        "adapter": "2b-100k", "seed": 20260913, "n": sum(tot.values()),
        "by_band": by_band,
        "strip_rate": round(strip_k / strip_n, 4),
        "strip_vs_body_ratio": round((strip_k / strip_n) / max(body_rate, 1e-9), 1),
        "stratified_volume_estimate": round(estimate, 4),
        "published_top_of_page_rate": 0.104,
        "if_strip_and_unbanded_cut": {
            "remaining_fabrication": round(by_band["body"]["volume_share"] * body_rate, 4),
            "real_lines_lost": round(real_lost, 4)},
        "examples_not_real": dict(examples),
    }
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    e = sys.stderr
    print(f"{'band':10}{'n':>5}{'not-real':>10}{'rate':>8}   {'95% CI':<17}{'vol share':>10}",
          file=e)
    for s in ("body", "head", "foot", "None"):
        v = by_band[s]
        ci = f"[{v['ci95'][0]:.1%}, {v['ci95'][1]:.1%}]"
        print(f"{s:10}{v['n']:>5}{v['not_real']:>10}{v['rate']:>8.1%}   {ci:<17}"
              f"{v['volume_share']:>10.2%}", file=e)
    print(f"\nstrip {res['strip_rate']:.1%} vs body {body_rate:.1%} "
          f"-> {res['strip_vs_body_ratio']}x", file=e)
    print(f"STRATIFIED VOLUME ESTIMATE: {res['stratified_volume_estimate']:.1%}  "
          f"(published top-of-page figure: {res['published_top_of_page_rate']:.1%})", file=e)
    c = res["if_strip_and_unbanded_cut"]
    print(f"cutting strip+unbanded: fabrication -> {c['remaining_fabrication']:.2%}, "
          f"real lines lost {c['real_lines_lost']:.2%}", file=e)
    print(f"wrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
