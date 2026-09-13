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

⚠️ WHAT THIS NUMBER IS NOT (measured 2026-09-10, and it surprised me)

**This metric cannot see field-boundary quality, and the 1906 figure proves it.** Ditto
normalization landed in `ia_volume_to_jsonl.py` (a leading OCR'd `44` makes the model swallow the
occupation into the name -- n=500 paired, McNemar p=0.0010). Re-running this scorer paired on the
SAME 500 lines, 299 of which had different input:

    un-normalized  448/500 real = 89.6%      normalized  448/500 real = 89.6%
    became an entry 0 · stopped being 0 · unchanged 500

**Zero rows changed classification**, while 18/500 records really did change and 3 recovered an
occupation (0 lost). The reason is `is_entry` itself: `name` non-empty AND an address-shaped
string. `44 Wm` and `" Wm` are both non-empty, so a record reading `name='44 Wm elk'` with an EMPTY
occupation scores as a perfectly good entry.

So the 10.4% is confirmed robust to that change -- and it is narrower than it looks. **Cite it as a
fabrication / page-type proxy, which is what it was built for. Do NOT cite it as record quality:**
a volume could have every occupation swallowed into the name and still score 89.6% real. Field
quality needs gold, or a boundary-sensitive proxy that does not exist yet.

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

Accuracy, re-validated 2026-09-14 against **140 committed hand labels** --
`data/entry_labels_1906BPL.jsonl`, 35 per band, collected with `eval/label_entries.py`, which
withholds both this function's verdict and the line's band from the labeller. Full analysis in
`results/entry_rate_validation_1906BPL.py`. 3 rows marked `unsure` are excluded.

    balanced across bands (35 each)   84.7%   (116/137)
    re-weighted by volume band mix    96.6%

The second is the like-for-like figure and it **approximately confirms the 97.5% this docstring
used to claim**. That older number was not wrong, it was uninformative: a volume-weighted sample is
94% body, and body is the easy class (97.1%). The balanced view is what shows the failure.

**EVERY ERROR RUNS ONE WAY, and this is the property to rely on:**

    junk called a real entry   21        precision on "not an entry"  100.0%
    real entry called junk      0        recall    on "not an entry"   78.3%

This function **never destroys a real entry** and misses about a fifth of the junk. So a
fabrication rate from `entry_rate` is a **FLOOR, never an over-estimate**. By band: body 97.1%,
unbanded 94.3%, head 85.3%, **foot 60.6%**.

**What it gets wrong is telephone numbers.** Ten of the 21 misses are lines like
`Telephone 3004 Main` or `Telephome Call, 269 Bedford`. `is_entry` wants a name plus an address
containing a digit -- and a phone number is digits, so an advertisement's telephone line satisfies
it exactly. Rejecting `telephone|phone|call` lifts the balanced figure to 93.4% with no new false
negatives, but **that was fitted on the same 137 rows and must not ship without a fresh sample.**

Comparators, rebuilt (the previously published ones had neither labels nor surviving code):

    raw line contains a digit     66.4%    <- docstring claimed 95.0%
    name non-empty only           53.3%
    surname-shape                 NOT REBUILT -- definition never recorded; the old 67.5% is
                                  unverifiable and should be deleted rather than re-quoted

Cross-checked on the 1836 tesseract volume, whose conventions differ: leaf 3 (a druggist's
advertisement) scores 0.0% entries, body leaves 60-62 score 88.7%.

**It is a proxy, not gold.** Validated on two volumes of the ~291 in the catalog, one publisher and
one labeller. The telephone failure is a property of Upington's advertising as ABBYY read it.
Re-validate by hand before trusting it on a new publisher or era -- the 1836 clause exists
precisely because one era's conventions broke it.
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
