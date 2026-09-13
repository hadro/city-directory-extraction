#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Phase 1 result: the band needs no model, and the one failure closes with the existing filter.

    python3 results/band_labels_vs_ditto_rule_1906BPL.py \
        --train data/bands_1906BPL_train.jsonl \
        --eval  data/bands_1906BPL_eval.jsonl \
        --out   results/band_labels_vs_ditto_rule_1906BPL.json

239 hand-labelled leaves of 1906BPL: 190 labelled with the ditto prefill visible (`train`) and 49
labelled **blind** -- no prefill, no overlay, edges starting at a neutral 0.10/0.90 -- drawn from a
disjoint sample. docs/PAGE_TYPE_CLASSIFIER.md phase 1, 2026-09-13.

1. THE RULE
-----------
Take the vertical extent of ditto-lead lines on a leaf and expand it by 0.015 of page height at
each end. That is the whole instrument. Scored against the labels, counting LINES:

    label set   extent over                     no ad admitted   exact    lost   admitted
    train       all ditto lines                    183/190      150/190    131         80
    train       ditto lines the text filter keeps  190/190      155/190    137          0
    blind       all ditto lines                      49/49       40/49      28          0
    blind       ditto lines the text filter keeps    49/49       40/49      28          0

**Zero advertising lines admitted across all 239 leaves**, at a cost of 137 listing lines lost out
of ~63,000 (0.2%) -- the harmless direction, since a lost line is a lost record while an admitted
ad line is a fabricated person.

2. THE ANCHORING CHECK, WHICH IS WHY THE BLIND SET EXISTED
----------------------------------------------------------
The `train` labels were made with the prefill drawn on screen, so their agreement with a
prefill-derived rule is partly circular. The blind set is what breaks that.

**A retracted argument, kept because it was wrong in an instructive way.** The first version of
this file argued that the offsets agreed despite the two sets quantising differently -- 68% of
`train` offsets landing exactly on +/-0.0150 against 0% of `blind` ones -- and read that as two
processes with different artefacts converging. That statistic is an artefact of the starting
points and is evidence of nothing. `train` edges begin at the prefill, a continuous value, so the
OFFSET is a whole number of 0.005 keypresses while the value is continuous (5/193 edges are
multiples of 0.005). `blind` edges begin at a round 0.100/0.900, so the VALUE is quantised (49/49)
and the offset is continuous. The 0% was guaranteed before anyone labelled anything. The labeller
used the keyboard for both sets; the claim that blind labels were mouse drags was never checked.

**The test that actually settles it** is whether a blind label tracks that leaf's ditto extent
across leaves, which the labeller could not see:

                label sd   extent sd        r
    top edge      0.0508      0.0505    +0.998      <- extent ranges 0.116-0.387
    bottom edge   0.0030      0.0071    +0.406      <- extent ranges 0.841-0.876

**The top edge is independently confirmed.** Its true position varies over a quarter of the page
across these 49 leaves, and the blind labels follow it at r = +0.998 with matching spread. That is
not something anchoring on a fixed 0.100 default can produce, and the top edge is the one that
matters, being where advertising intrudes.

**The bottom edge is NOT confirmed.** The blind labels there are nearly constant (sd 0.0030)
against a true spread of sd 0.0071, so they do not track per-leaf variation and r is weak. The
saving grace is that the true variation is small -- the whole range is 0.035 of page height -- so a
constant is close to right and the measured cost below is real. But the +0.015 bottom offset rests
on the anchored set, and only the top offset survives the blind check.

3. THE FAILURE, AND WHY IT NEEDED NO NEW CODE
----------------------------------------------
`44` is ABBYY's reading of the ditto mark AND a literal street number. The recurring Temple Bar
advertisement carries `44 COURT ST.`, the ditto regex matches it, and the extent's top edge lands
inside the advertisement -- admitting 22 lines of ad copy on leaf 904, 10 apiece on four others.
Those six leaves produced 71 of the 80 admitted lines (89%).

The fix is to compute the extent over the lines that `text_reject` keeps, because it already
classifies `44 COURT ST.` as `allcaps` and drops it. No new rule, no threshold, no model.

**The distinction that makes this safe is case, and it took looking to find.** Two of the nine
`44 <Street>`-shaped lines in the training leaves are NOT advertising:

    leaf 251   44 Montauk av    x=510, indented under `Dascheff Morris mfr 17 Elizabeth Mhtn h`
    leaf 574   44 Crooke av     x=1119, indented under `" Arthur L lawyer 220 B'way Mhtn h`

Both are wrapped continuations whose leading `44` is a house number, i.e. real listing lines, and
`text_reject` correctly keeps both (they are mixed case). A regex on `44 <Word> <StreetType>`
would have excluded them and been wrong. They also cause no damage, sitting inside the body
already. In the pipeline proper they never arise as standalone lines at all, because stage 1 joins
wrapped continuations before filtering.

4. WHAT THIS DOES NOT SETTLE
-----------------------------
- **The blind set contains no ad-intrusion case at all** (0 of 49 leaves carry a `44 <Street>`
  line, against 9 of 190 in train; P(zero in 49) = 0.09, so chance, not evidence of absence). It
  independently validates the OFFSET; it does not validate the FIX. The fix is measured on the
  training leaves, which is where the failures are, and that is the weaker of the two designs.
- **One volume, one engine, one publisher, one labeller.** `44` is 1906BPL's mark, admitted by a
  per-volume gate; a Polk or Trow volume with a different dominant glyph needs this re-run, and
  whether the 0.015 offset transfers is untested.
- **Strip contents are unusable in both batches** -- `head_touched`/`foot_touched` false
  throughout, every value the untouched default. Do not count or train on those fields.
- 4 train leaves (39, 129, 134, 165) are `has_body: false` with `page_type: null`.
"""

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_prep"))

from ia_volume_to_jsonl import Item, hocr_lines, page_dims, text_reject   # noqa: E402

# 1906BPL's admitted marks. Per-volume by construction -- do not reuse this literal elsewhere.
DITTO = re.compile(r'^\s*(44|"|“|”|\*\*|«)\s')
OFFSETS = [0.0, 0.010, 0.015, 0.020, 0.025]
MIN_DITTO_LINES = 20


def leaf_geometry(item, leaf):
    """(all line y-fractions, ditto y-fractions unfiltered, ditto y-fractions filter-surviving)."""
    markup = item.hocr_page(leaf)
    if not markup:
        return None
    pairs, dims = hocr_lines(markup), page_dims(markup)
    if not pairs or not dims:
        return None
    h = dims[1]
    ys = [b[1] / h for b, _ in pairs]
    raw = [b[1] / h for b, t in pairs if DITTO.match(t)]
    kept = [b[1] / h for b, t in pairs if DITTO.match(t) and text_reject(t) is None]
    return ys, raw, kept


def score(rows, item, filtered, offset):
    lost = admitted = clean = exact = n = 0
    worst = []
    for r in rows:
        geo = leaf_geometry(item, r["leaf"])
        if geo is None:
            continue
        ys, raw, kept = geo
        dy = kept if filtered else raw
        if len(dy) < MIN_DITTO_LINES:
            continue
        top, bot = min(dy) - offset, max(dy) + offset
        truth = {i for i, y in enumerate(ys) if r["body_top"] <= y <= r["body_bottom"]}
        got = {i for i, y in enumerate(ys) if top <= y <= bot}
        a, b = len(truth - got), len(got - truth)
        lost += a
        admitted += b
        clean += (b == 0)
        exact += (a == 0 and b == 0)
        n += 1
        if b:
            worst.append({"leaf": r["leaf"], "admitted": b})
    worst.sort(key=lambda d: -d["admitted"])
    return {"n": n, "clean_leaves": clean, "exact_leaves": exact,
            "listing_lost": lost, "ad_admitted": admitted, "worst": worst[:6]}


def _pearson(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return round(num / den, 4) if den else None


def offsets_used(rows, item):
    """How each label relates to that leaf's ditto extent.

    The decision-bearing number here is `r`, NOT the offset median: it asks whether the label
    follows the extent as the extent moves across leaves. A labeller who never saw the extent and
    still tracks it at r~1 is agreeing independently. The offset median alone cannot distinguish
    that from a labeller who applied one constant to every page -- which is exactly the mistake
    the first version of this analysis made.

    `quantised` records what fraction of raw edge VALUES are multiples of the 0.005 keyboard
    step, which is how each batch was produced. It is bookkeeping, not evidence.
    """
    top, bot, etop, ebot, vals = [], [], [], [], []
    for r in rows:
        geo = leaf_geometry(item, r["leaf"])
        if geo is None:
            continue
        _, raw, _ = geo
        if len(raw) < MIN_DITTO_LINES:
            continue
        top.append(round(r["body_top"] - min(raw), 4))
        bot.append(round(r["body_bottom"] - max(raw), 4))
        etop.append(min(raw))
        ebot.append(max(raw))
        vals += [r["body_top"], r["body_bottom"]]

    def summary(offs, labels, extents):
        q = sorted(offs)
        return {"n": len(offs), "median": round(statistics.median(offs), 4),
                "q1": q[len(q) // 4], "q3": q[3 * len(q) // 4],
                "label_sd": round(statistics.pstdev(labels), 4),
                "extent_sd": round(statistics.pstdev(extents), 4),
                "extent_range": [round(min(extents), 4), round(max(extents), 4)],
                "tracks_extent_r": _pearson(labels, extents)}

    return {
        "top": summary(top, [o + e for o, e in zip(top, etop)], etop),
        "bottom": summary(bot, [o + e for o, e in zip(bot, ebot)], ebot),
        "quantised_to_keystep": round(
            sum(abs(round(v / 0.005) - v / 0.005) < 1e-6 for v in vals) / len(vals), 4),
    }


def load(path):
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    return rows, [r for r in rows if r["has_body"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", default="data/bands_1906BPL_train.jsonl")
    ap.add_argument("--eval", default="data/bands_1906BPL_eval.jsonl")
    ap.add_argument("--ident", default="1906BPL")
    ap.add_argument("--cache", default="data/ia_cache")
    ap.add_argument("--out", default="results/band_labels_vs_ditto_rule_1906BPL.json")
    args = ap.parse_args(argv)

    item = Item(args.ident, Path(args.cache))
    item.prefetch_hocr()
    e = sys.stderr
    res = {"ident": args.ident, "sets": {}, "offsets": {}, "headline_offset": 0.015}

    for name, path in (("train", args.train), ("blind", args.eval)):
        if not Path(path).exists():
            print(f"  (no {name} labels at {path}, skipped)", file=e)
            continue
        rows, body = load(path)
        res["sets"][name] = {
            "path": path, "n_rows": len(rows), "n_body": len(body),
            "n_irregular": sum(r["irregular"] for r in rows),
            "no_body_missing_page_type": [r["leaf"] for r in rows
                                          if not r["has_body"] and not r.get("page_type")],
            "strip_touched": {"head": sum(bool(r.get("head_touched")) for r in body),
                              "foot": sum(bool(r.get("foot_touched")) for r in body)},
            "rules": {f"{'kept' if f else 'all'}/{o:.3f}": score(body, item, f, o)
                      for f in (False, True) for o in OFFSETS},
        }
        res["offsets"][name] = offsets_used(body, item)

    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    print(f"\n{'set':<7}{'extent over':<32}{'no ad':>11}{'exact':>11}{'lost':>8}{'admitted':>10}",
          file=e)
    for name, s in res["sets"].items():
        for f, lab in ((False, "all ditto lines"), (True, "ditto lines the text filter keeps")):
            v = s["rules"][f"{'kept' if f else 'all'}/{res['headline_offset']:.3f}"]
            print(f"{name:<7}{lab:<32}{v['clean_leaves']:>7}/{v['n']:<3}"
                  f"{v['exact_leaves']:>8}/{v['n']:<3}{v['listing_lost']:>8,}"
                  f"{v['ad_admitted']:>10,}", file=e)
            if v["worst"]:
                print(f"       worst: "
                      + ", ".join(f"{d['leaf']}({d['admitted']})" for d in v["worst"]), file=e)

    print(f"\ndoes the label track that leaf's ditto extent, which blind labelling cannot see?",
          file=e)
    print(f"{'':16}{'offset median':>15}{'label sd':>11}{'extent sd':>11}{'r':>9}"
          f"{'extent range':>18}", file=e)
    for name in res["offsets"]:
        for edge in ("top", "bottom"):
            v = res["offsets"][name][edge]
            print(f"{name + ' ' + edge:<16}{v['median']:>+15.4f}{v['label_sd']:>11.4f}"
                  f"{v['extent_sd']:>11.4f}{v['tracks_extent_r']:>+9.3f}"
                  f"{str(v['extent_range']):>18}", file=e)
    for name in res["offsets"]:
        print(f"  {name}: {res['offsets'][name]['quantised_to_keystep']:.0%} of edge values sit on "
              f"the 0.005 keyboard step (bookkeeping, not evidence)", file=e)

    for name, s in res["sets"].items():
        t = s["strip_touched"]
        if not (t["head"] or t["foot"]):
            print(f"\n{name}: strip labels all default ({s['n_body']} leaves) — UNUSABLE", file=e)
        if s["no_body_missing_page_type"]:
            print(f"{name}: no-body leaves lacking page_type: {s['no_body_missing_page_type']}",
                  file=e)
    print(f"\nwrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
