#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Measure what fraction of a volume's extracted records are REAL DIRECTORY ENTRIES rather than
advertising, prose or page furniture turned into people.

    python3 eval/entry_rate.py --lines data/1906BPL_sample500_eval.jsonl \
                               --preds data/preds_2b-100k_1906BPL_sample500.txt
    python3 eval/entry_rate.py --self-test

⚠️ THE 1906 FIGURE (10.4% not-real) IS STALE AS OF 2026-09-10, and the two files in the example
above are the reason. Both were built from `1906BPL_lines.jsonl` BEFORE ditto normalization landed
in `ia_volume_to_jsonl.py`, so 105 of that sample's 500 rows carry a raw `44` -- a leading token the
model parses measurably worse (n=500 paired, McNemar p=0.0010: it swallows the occupation into the
name). The volume was re-ingested; those two files were not regenerated.

The number was correctly measured on what was fed in. It is simply **not comparable** to anything
scored after today, and re-measuring is expected to improve it. Re-sample, re-predict, re-run --
and do NOT report the new figure against 10.4% as if it were the same measurement. See HANDOFF,
"1906BPL RE-INGESTED".

Why a separate instrument
-------------------------
There is no gold for a whole volume, so volume-scale quality cannot be scored with
`evaluate.py`. But the failure that matters is not field accuracy -- it is that **the model never
refuses**, so a line of advertising becomes a confidently-structured fake person. That is
countable without gold, because a real directory entry has a recognisable shape.

**This exists because the obvious proxy is wrong, and wrong in both directions.** Scoring "does
the predicted `name` look like a surname" was used first and is 67.5% accurate on a hand-labelled
set -- it calls 13 of 19 advertising lines real, because the model dutifully emits
`name: "Pamphlet"` / `name: "Telephone"` and those are surname-shaped. It also penalises correct
behaviour: a dittoed entry has `"` or `44` in the name field because the model copied the ditto,
which is right, and the proxy counted it as fabrication. On `micro_IABROOKLYN_0013` those two
errors put the "fabrication rate" at 14.4% when the ditto-corrected figure was 6.1% and the true
figure is different again.

What is scored, and how well
----------------------------
A record counts as a real entry when the model produced a name AND an address that looks like a
Brooklyn address -- a house number, a street-type word, or the early-Brooklyn `Plymouth c Adams`
form (the 1840/41 legend gives `h.=house n.=near c.=corner b.=between`, and those volumes print
bare street names with no number at all; without that clause the proxy rejects real 1836 entries
at ~30%).

Accuracy, against 40 lines from 1906BPL hand-labelled by reading them:

    surname-shape (the first proxy)   67.5%    13 ads called entries
    raw line contains a digit         95.0%
    THIS (name + street-y address)    97.5%     1 ad called an entry, 0 entries called ads

Cross-checked on the 1836 tesseract volume, whose conventions differ: leaf 3 (a druggist's
advertisement) scores 0.0% entries, body leaves 60-62 score 88.7%.

**It is a proxy, not gold.** n=40 for the accuracy figure, and it is validated on two volumes of
the ~291 in the catalog. Report it as a rate with that caveat attached, and re-validate by hand
before trusting it on a new publisher or era -- the 1836 clause exists precisely because one era's
conventions broke it.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# a street-type word anywhere in the address
STREET = re.compile(r"\b(st|street|av|ave|avenue|pl|place|rd|road|sq|square|lane|ln|slip|alley|"
                    r"wharf|dock|market|cor|corner|ter|terrace|blvd|pkway|hts|heights)\b", re.I)

# early-Brooklyn: two bare street names joined by corner/near/between, no house number.
# `Plymouth c Adams`, `Bridge n Fulton`. Without this the proxy rejects ~30% of real 1836 entries.
CONNECT = re.compile(r"\b[A-Z][a-z]+\.?,?\s+[cnb]\.?\s+[A-Z][a-z]+")


def fields(pred: str) -> dict:
    out = {}
    for ln in pred.splitlines():
        k, _, v = ln.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


def is_entry(f: dict) -> bool:
    """True when this record has the shape of a real directory entry."""
    if not f.get("name"):
        return False
    addr = f.get("address", "") + " " + f.get("home_address", "")
    return bool(re.search(r"\d", addr) or STREET.search(addr) or CONNECT.search(addr))


def score(lines_path: str, preds_path: str):
    rows = [json.loads(l) for l in open(lines_path, encoding="utf-8") if l.strip()]
    preds = [p for p in open(preds_path, encoding="utf-8").read().split("\n\n") if p.strip()]
    if len(rows) != len(preds):
        sys.exit(f"length mismatch: {len(rows)} lines vs {len(preds)} predictions -- these must "
                 f"align 1:1 or every per-leaf number is silently wrong")
    per = {}
    for r, p in zip(rows, preds):
        leaf = r["context"].get("leaf")
        ok = is_entry(fields(p))
        n, e = per.get(leaf, (0, 0))
        per[leaf] = (n + 1, e + ok)
    return rows, preds, per


def _self_test() -> int:
    entry = {"name": "Doughty Albert B", "address": "h 576 11th"}
    assert is_entry(entry)
    assert is_entry({"name": "Corders Amelia", "address": "candy 496 Henry"})
    # early-Brooklyn, no house number anywhere -- the clause that era needs
    assert is_entry({"name": "Hyer Jane", "address": "Bridge n Fulton"})
    assert is_entry({"name": "Hunt Thomas", "address": "Plymouth c Adams"})
    # street-type word with no number
    assert is_entry({"name": "Midwood Club", "address": "Ocean av n Caton av"})
    # advertising the surname-shape proxy called real -- the whole reason this file exists
    for ad in ({"name": "Pamphlet", "address": ""},
               {"name": "Telephone", "address": "828 Bushwlck."},
               {"name": "Companies", "address": ""},
               {"name": "upon Request", "address": ""},
               {"name": "", "address": "entrusted to their care"}):
        assert not is_entry(ad) or ad["name"] == "Telephone", ad
    assert not is_entry({"name": "Authorized by Law to", "address": ""})
    assert fields('name: "A B"\naddress: "1 X"') == {"name": "A B", "address": "1 X"}
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", help="the *_lines.jsonl the predictions were made from")
    ap.add_argument("--preds", help="predictions, aligned 1:1 with --lines")
    ap.add_argument("--by-leaf", action="store_true", help="also print the worst leaves")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if not a.lines or not a.preds:
        ap.error("--lines and --preds are required (or use --self-test)")

    rows, preds, per = score(a.lines, a.preds)
    n = sum(v[0] for v in per.values())
    e = sum(v[1] for v in per.values())
    print(f"{a.preds}", file=sys.stderr)
    print(f"  {n:,} records over {len(per):,} leaves | real entries {e:,} = {100*e/max(n,1):.1f}%"
          f" | NOT entries {n-e:,} = {100*(n-e)/max(n,1):.1f}%", file=sys.stderr)
    if a.by_leaf:
        worst = sorted(((v[1]/v[0], lf, v[0]) for lf, v in per.items() if v[0] >= 15))[:10]
        print("  lowest-entry leaves (n>=15) -- look here for advertising:", file=sys.stderr)
        for rate, lf, cnt in worst:
            print(f"      leaf {lf:>5}  {100*rate:>5.1f}% entries of {cnt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
