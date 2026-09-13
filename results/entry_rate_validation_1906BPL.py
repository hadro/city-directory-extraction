#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Re-validation of `entry_rate.py` against 140 committed hand labels.

    python3 results/entry_rate_validation_1906BPL.py \
        --labels data/entry_labels_1906BPL.jsonl \
        --out results/entry_rate_validation_1906BPL.json

Replaces the docstring claim "40 lines ... 97.5%", whose labels were never committed
(docs/FIGURE_AUDIT.md finding 2). Labels collected with `eval/label_entries.py`, which withholds
both `is_entry`'s verdict and the line's band from the labeller; the band is attached server-side
at save time. 140 rows, 35 per band, 3 marked `unsure` and excluded from scoring.

THE HEADLINE IS TWO NUMBERS, AND BOTH MATTER
---------------------------------------------
    balanced across bands (35 each)   84.7%   116/137
    re-weighted by volume band mix    96.6%

**The published 97.5% is approximately confirmed volume-wide.** It was not wrong; it was
uninformative, because a volume-weighted sample is 94% body and body is the easy class. The
balanced view is what shows the failure.

EVERY ERROR RUNS IN ONE DIRECTION
----------------------------------
    junk called a real entry    21
    real entry called junk       0

    precision on "not an entry"  100.0%
    recall on "not an entry"      78.4%

**`is_entry` never destroys a real entry, and misses about a fifth of the junk.** That asymmetry
was not previously recorded and it changes how the metric should be read: a fabrication rate from
`entry_rate` is a FLOOR, never an over-estimate.

    band       agreement
    body          97.1%
    unbanded      94.3%
    head          85.3%
    foot          60.6%

WHAT IT ACTUALLY GETS WRONG: TELEPHONE NUMBERS
-----------------------------------------------
Ten of the 21 misses contain a phone number:

    Telephone 3004 Main            Telephone 3418 Vain
    Telephone 3004 Main 264        Telephome Call, 269 Bedford Brooklyn, N.Y, 58S
    -Telephone Call: Store, 924 Bedford-

`is_entry` asks for a non-empty `name` and an address containing a digit or a street word. A phone
number is digits, so an advertisement's telephone line satisfies it exactly. This also explains a
figure that always looked odd: the docstring's comparator "raw line contains a digit" scored 95.0%
because **the proxy is largely a digit test**.

The rest are business-directory tails (`Aurora Grata Club 1160 Bedford av`, `New York, 21-27 New
Chambers St.`) and officer lists from bank advertisements (`GATES D. FAHNESTOCK, 2d-Vice-Pres.`).

A CANDIDATE FIX, AND IT IS FITTED
----------------------------------
Rejecting lines whose raw text matches `telephone|telephome|phone|call`:

    is_entry (shipped)                84.7%   junk->entry 21   entry->junk 0
    is_entry + reject telephone       93.4%   junk->entry  9   entry->junk 0

**This was derived ON these 137 rows and is therefore fitted to them.** It is a hypothesis this
label set generated, not a result it validated. Do not ship it on this evidence — it needs a fresh
labelled sample, and the failure mode it targets is exactly the kind that could be an artefact of
one publisher's advertising conventions.

THE COMPARATORS, RESTATED
-------------------------
Both figures in `entry_rate.py`'s docstring were unverifiable — no labels, and no surviving
implementations. Rebuilt here and measured on the balanced set:

    proxy                          published   here (balanced)
    this one (name + street-y)         97.5%            84.7%
    raw line contains a digit          95.0%            66.4%
    name non-empty only                    -            53.3%
    surname-shape                      67.5%     NOT REBUILT

The published and balanced columns are **not comparable** — balancing by band deliberately enriches
hard cases, so every proxy scores lower here by construction. The like-for-like comparison to 97.5%
is the volume-weighted 96.6%.

**`surname-shape` at 67.5% remains unverifiable**: its definition was never written down and its
implementation is gone. Either define and rebuild it, or delete the claim.

WHAT THIS DOES NOT SETTLE
-------------------------
- One volume, one publisher, one adapter, one labeller. The telephone failure is a property of
  Upington's advertising as OCR'd by ABBYY.
- The category field is coarser than intended. 79 of 97 not-entries were tagged `ocr-garbage`,
  including garbled advertising like `Telephone 3418 Vain` and `GATES D. FAHNESTOCK, 2d-Vice-Pret.`
  — a mangled advertisement is both an advertisement and wreckage, and the labelling scheme forced
  a choice. Do not read "79 are OCR garbage" as "only 8 are advertising". The
  `business-directory` tag is clean and is the one to trust.
- `is_entry` sees only the predicted record, so this measures the metric, never the model.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

from entry_rate import fields, is_entry           # noqa: E402

PREDS = ROOT / "results" / "ab_band_fabrication_1906BPL_preds"
# Candidate only. Fitted to this label set; see the docstring before shipping it.
PHONE = re.compile(r"\btele(phone|phome)\b|\bphone\b|\bcall\b", re.I)


def load(labels_path, preds_dir):
    d = Path(preds_dir)
    inp = [json.loads(l) for l in (d / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
           if l.strip()]
    blocks = [b for b in re.split(r"\n\s*\n", (d / "preds.txt").read_text(encoding="utf-8"))
              if b.strip()]
    lab = {r["row"]: r for r in
           (json.loads(l) for l in Path(labels_path).read_text(encoding="utf-8").splitlines()
            if l.strip())}
    out = []
    for i, (blk, src) in enumerate(zip(blocks, inp)):
        if i in lab:
            out.append((lab[i], fields(blk), src["raw_line"]))
    return out, lab


def score(items, predicate):
    tp = tn = fp = fn = 0
    wrong = []
    for l, f, raw in items:
        p = predicate(f, raw)
        real = l["label"] == "entry"
        tp += real and p
        tn += (not real) and (not p)
        fp += (not real) and p
        fn += real and (not p)
        if real != p:
            wrong.append({"band": l["band"], "human": l["label"],
                          "category": l["category"], "raw": raw[:70]})
    n = len(items)
    return {"n": n, "agreement": round((tp + tn) / n, 4),
            "junk_called_entry": fp, "entry_called_junk": fn,
            "precision_not_entry": round(tn / (tn + fn), 4) if (tn + fn) else None,
            "recall_not_entry": round(tn / (tn + fp), 4) if (tn + fp) else None,
            "wrong": wrong}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default="data/entry_labels_1906BPL.jsonl")
    ap.add_argument("--preds", default=str(PREDS))
    ap.add_argument("--lines", default="data/1906BPL_lines.jsonl")
    ap.add_argument("--out", default="results/entry_rate_validation_1906BPL.json")
    args = ap.parse_args(argv)

    all_items, lab = load(args.labels, args.preds)
    items = [t for t in all_items if t[0]["label"] != "unsure"]

    shipped = score(items, lambda f, raw: is_entry(f))
    proxies = {
        "is_entry (shipped)": shipped,
        "raw line contains a digit": score(items, lambda f, raw: bool(re.search(r"\d", raw))),
        "name non-empty only": score(items, lambda f, raw: bool(f.get("name"))),
        "is_entry + reject telephone (FITTED)":
            score(items, lambda f, raw: False if PHONE.search(raw) else is_entry(f)),
    }

    per_band = defaultdict(lambda: [0, 0])
    for l, f, raw in items:
        per_band[l["band"]][0] += (l["label"] == "entry") == is_entry(f)
        per_band[l["band"]][1] += 1
    mix = Counter(json.loads(l)["context"].get("band")
                  for l in Path(args.lines).read_text(encoding="utf-8").splitlines() if l.strip())
    n_vol = sum(mix.values())
    weighted = sum((mix[None if b == "None" else b] / n_vol) * (k / m)
                   for b, (k, m) in per_band.items())

    res = {
        "labels": args.labels, "n_labels": len(lab),
        "n_scored": len(items), "n_unsure": len(all_items) - len(items),
        "label_mix": dict(Counter(r["label"] for r in lab.values())),
        "category_mix": dict(Counter(r["category"] for r in lab.values()
                                     if r["label"] == "not-entry")),
        "balanced_agreement": shipped["agreement"],
        "volume_weighted_agreement": round(weighted, 4),
        "published_claim": 0.975,
        "per_band": {b: {"agree": k, "n": m, "rate": round(k / m, 4)}
                     for b, (k, m) in sorted(per_band.items())},
        "proxies": {k: {kk: vv for kk, vv in v.items() if kk != "wrong"}
                    for k, v in proxies.items()},
        "errors": shipped["wrong"],
    }
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    e = sys.stderr
    print(f"{res['n_scored']} scored ({res['n_unsure']} unsure excluded), "
          f"{res['label_mix']}", file=e)
    print(f"\nbalanced agreement        {res['balanced_agreement']:.1%}", file=e)
    print(f"volume-weighted agreement {res['volume_weighted_agreement']:.1%}   "
          f"(published claim {res['published_claim']:.1%})", file=e)
    print(f"\njunk called an entry {shipped['junk_called_entry']}   "
          f"real entry called junk {shipped['entry_called_junk']}", file=e)
    print(f"precision on not-entry {shipped['precision_not_entry']:.1%}   "
          f"recall {shipped['recall_not_entry']:.1%}", file=e)
    print("\nper band:", file=e)
    for b, v in res["per_band"].items():
        print(f"  {b:9}{v['agree']:3}/{v['n']:<3} {v['rate']:>7.1%}", file=e)
    print(f"\n{'proxy':40}{'agreement':>11}{'junk→entry':>12}{'entry→junk':>12}", file=e)
    for k, v in res["proxies"].items():
        print(f"{k:40}{v['agreement']:>11.1%}{v['junk_called_entry']:>12}"
              f"{v['entry_called_junk']:>12}", file=e)
    print(f"\nwrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
