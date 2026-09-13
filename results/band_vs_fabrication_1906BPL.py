#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The band separates fabrication 18:1 — and the 10.4% it is measured against is biased upward.

    python3 results/band_vs_fabrication_1906BPL.py \
        --lines data/1906BPL_lines.jsonl \
        --sample data/1906BPL_sample500_eval.jsonl \
        --preds data/preds_2b-100k_1906BPL_sample500.txt \
        --out results/band_vs_fabrication_1906BPL.json

Run 2026-09-13, using predictions that already existed. `context.band` had been validated against
239 hand-labelled leaves but never against the thing it exists to reduce -- fabricated people --
so this crosses it with `entry_rate.py`'s is_entry proxy on the exact 500 rows that produced
PIPELINE.md's 10.4%.

1. THE BAND SEPARATES FABRICATION
----------------------------------
    band    n     not-real    rate
    head     36        30    83.3%
    body    464        22     4.7%
    ALL     500        52    10.4%   <- reproduces PIPELINE.md exactly

**A 17.7x ratio.** On this sample, cutting strip lines takes fabrication from 10.4% to 4.7% --
30 of 52 fabrications removed -- at a cost of 6 real entries in 500 (1.2%). The band is not just
geometrically correct against hand labels; it lands on the lines the model turns into fake people.

2. BUT THE SAMPLE IS THE TOP 12% OF EACH PAGE, AND THAT MATTERS
----------------------------------------------------------------
`1906BPL_sample500_eval.jsonl` is **not** a uniform draw over kept lines. It is 25 leaves x the
**first 20 kept lines of each** (verified: sampled positions are exactly 0..19, on leaves holding
121-181 kept lines, median 166). It therefore reads only the top ~12% of every page.

Head strips live exactly there, and the band mix proves it:

    band        expected in a uniform 500     observed
    head                    3.6                  36     <- 10x over-represented
    foot                    3.8                   0
    unbanded               24.1                   0
    body                  468.5                 464

Head lines are 83.3% not-real, so **a sample drawn from the top of the page is biased upward for
fabrication by construction.** PIPELINE.md's 10.4% -- and the "clean tier is 2x better" comparison
resting on it -- is a top-of-page number, not a volume number.

3. WHAT FOLLOWS, AND WHAT DOES NOT
-----------------------------------
**Survives:** the per-band rates. 83.3% and 4.7% are conditional on band, so the sampling bias
changes the MIX, not the rates, provided each band's sampled lines are representative of that band.
The 17.7x separation stands.

**Does not survive:** any volume-wide claim built on 10.4%, including this file's own "58% of
fabrication is strip". Applying the measured per-band rates to the volume-wide band mix gives a
much lower headline -- 0.0148 x 0.833 + 0.9370 x 0.047 = **5.6%**, before whatever the 4.83% of
unbanded lines contribute, and the sample contains none of those to measure.

**Not measured here:** the unbanded rate, the foot rate (zero rows of each), and whether body-band
lines lower down a page behave like body-band lines at the top. A uniform, band-stratified sample
would settle all three and needs a fresh model run of a few hundred lines.

The not-real body lines that were sampled are not advertising prose but OCR wreckage -- `w* 13 cJ`,
`3 n a >,` -- alongside genuine interior ad copy such as `Near Borough Hall, - BROOKLYN, N. Y.`.
"Not real" is not a synonym for "advertising", and `entry_rate` never claimed it was.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from entry_rate import fields, is_entry        # noqa: E402


def band_index(lines_path):
    idx = {}
    for ln in Path(lines_path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            c = r["context"]
            idx[(c["leaf"], tuple(c["bbox"]))] = c.get("band")
    return idx


def volume_mix(lines_path):
    c = Counter()
    for ln in Path(lines_path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            c[json.loads(ln)["context"].get("band")] += 1
    n = sum(c.values())
    return {str(k): {"n": v, "share": round(v / n, 6)} for k, v in c.items()}, n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", default="data/1906BPL_lines.jsonl")
    ap.add_argument("--sample", default="data/1906BPL_sample500_eval.jsonl")
    ap.add_argument("--preds", default="data/preds_2b-100k_1906BPL_sample500.txt")
    ap.add_argument("--out", default="results/band_vs_fabrication_1906BPL.json")
    args = ap.parse_args(argv)

    idx = band_index(args.lines)
    mix, n_vol = volume_mix(args.lines)
    samp = [json.loads(l) for l in Path(args.sample).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    blocks = [b for b in re.split(r"\n\s*\n", Path(args.preds).read_text(encoding="utf-8"))
              if b.strip()]
    if len(blocks) != len(samp):
        print(f"WARNING: {len(blocks)} predictions vs {len(samp)} sample rows", file=sys.stderr)

    # Where in its leaf does each sampled line sit? This is what exposes the sampling design.
    seq = defaultdict(list)
    for ln in Path(args.lines).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            c = r["context"]
            seq[c["leaf"]].append(tuple(c["bbox"]))

    tot, bad, positions, examples = Counter(), Counter(), [], defaultdict(list)
    for blk, s in zip(blocks, samp):
        c = s["context"]
        key = (c["leaf"], tuple(c["bbox"]))
        b = str(idx.get(key))
        tot[b] += 1
        if key[1] in seq[c["leaf"]]:
            positions.append(seq[c["leaf"]].index(key[1]))
        if not is_entry(fields(blk)):
            bad[b] += 1
            if len(examples[b]) < 4:
                examples[b].append(s["raw_line"][:70])

    n = sum(tot.values())
    nb = sum(bad.values())
    rates = {b: {"n": tot[b], "not_real": bad[b], "rate": round(bad[b] / tot[b], 4)}
             for b in tot}
    # Re-weight the measured per-band rates by the VOLUME's band mix, not the sample's.
    reweighted = sum(mix[b]["share"] * rates[b]["rate"] for b in rates if b in mix)
    covered = sum(mix[b]["share"] for b in rates if b in mix)

    res = {
        "sample": args.sample, "preds": args.preds, "n": n,
        "observed_rate": round(nb / n, 4),
        "by_band": rates,
        "volume_band_mix": mix, "volume_lines": n_vol,
        "sample_position_in_leaf": {"min": min(positions), "max": max(positions),
                                    "n": len(positions)},
        "expected_under_uniform": {b: round(n * mix[b]["share"], 1) for b in mix},
        "reweighted_rate_over_covered_bands": round(reweighted, 4),
        "volume_share_covered_by_measured_bands": round(covered, 4),
        "examples_not_real": dict(examples),
    }
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    e = sys.stderr
    print(f"{'band':10}{'n':>6}{'not-real':>10}{'rate':>9}", file=e)
    for b in ("head", "foot", "body", "None"):
        if b in rates:
            r = rates[b]
            print(f"{b:10}{r['n']:>6}{r['not_real']:>10}{r['rate']:>9.1%}", file=e)
    print(f"{'ALL':10}{n:>6}{nb:>10}{nb/n:>9.1%}   <- PIPELINE.md's figure", file=e)

    print(f"\nsample positions within leaf: {res['sample_position_in_leaf']['min']}.."
          f"{res['sample_position_in_leaf']['max']}  <- the TOP of each page, not a uniform draw",
          file=e)
    print(f"{'band':10}{'expected/500':>14}{'observed':>10}", file=e)
    for b in ("head", "foot", "None", "body"):
        if b in mix:
            print(f"{b:10}{res['expected_under_uniform'][b]:>14.1f}{tot.get(b,0):>10}", file=e)
    print(f"\nper-band rates re-weighted by the VOLUME mix: "
          f"{res['reweighted_rate_over_covered_bands']:.1%} "
          f"(covers {res['volume_share_covered_by_measured_bands']:.1%} of lines; "
          f"unbanded unmeasured)", file=e)
    print(f"wrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
