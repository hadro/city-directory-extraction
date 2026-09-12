#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate the implied-surname detector against hand-labelled gold. Mostly a NEGATIVE result.

    python3 results/implied_surname_validation.py \
        --out results/implied_surname_validation.json

Companion to `implied_surname_lines_1906BPL.py`, which found the phenomenon and measured its cost
on 1906BPL. This asks the separate question -- does the detector actually work, and does it
travel? -- against the 21-volume panel gold. The lexicon is harvested from 1906BPL ONLY, so every
number here is cross-volume by construction.

WHAT THIS ESTABLISHES
---------------------
**1. The detector must be gated on whether the volume uses implied surnames at all.**
Applied blind to every panel volume it fires 242 times on rows whose gold surname IS the leading
token. Gated on the volume actually using implied surnames, that falls to 1.

    false positives, applied blind                       242
    false positives, gated                                 1     (0.02% of 4,257 surname-first rows)

The gate is not delicate, because the panel is bimodal with nothing in between:

    doggetts1850, smith1856, boyd1890, lain, tulsa ...   0.0%  of gold names are implied
    trow1907, queens1933, polk1933si ... trow1913       58.8% - 97.8%

Blind application is the error, not the lexicon. `Harvey`, `Dudley`, `Lewis` are given names AND
surnames, and in a volume that prints the surname on every line they are always surnames.

**2. Recall is NOT measurable from the gold we hold, and this file does not report one.**
The panel contains 6 clean instances of the phenomenon, all in trow1913
(`Adolph A salesman h68 Lenox av` -> gold `-Adolph A`). Six is an anecdote. The volume where the
phenomenon is abundant -- 1906BPL, 5,491 lines -- has no labelled gold, and the volumes with
labelled gold mostly do not exhibit it. **Anyone citing a recall number for this detector is
citing something that has not been measured.**

The gold pool's other apparent positives are a DIFFERENT failure: a ditto mark that is present but
glued or misread, so `is_ditto_lead` never sees it --

    '"Thos (Marcella) h26 Sheridan av, Stap'   gold '" Thos'    mark glued to the given name
    'n Dora Mrs h115 Washn pl'                 gold '" Dora Mrs'  ABBYY read " as n

Those belong to next-step #9 (mark detection), not here (mark absent). Conflating them is how a
recall number for this detector gets manufactured, and it is why the two are separated above.

**3. The production gate fails on exactly the volumes with glued marks.** The gate above reads
gold, which production does not have; the production signal is the raw ditto-lead share, and it
agrees with gold on five of seven volumes and inverts on both Trow books:

    volume        gold implied%   raw ditto-lead%
    polk1917           84.7%           83.3%      agree
    polk1925           90.0%           92.5%      agree
    polk1933bk         71.4%           71.4%      agree
    polk1933si         66.1%           55.4%      agree
    queens1933         59.7%           58.1%      agree
    trow1907           58.8%            0.0%      MISSED
    trow1913           97.8%            0.0%      MISSED

Trow glues its dash to the given name (`-Adolph`), so nothing tokenises as a mark. Both the gate
AND the harvest read zero there. **So the detector is blocked on next-step #9 for the Trow family**
-- which is the concrete form of the portability caveat the companion file states in the abstract,
and a better reason to do #9 than the one recorded against it.

HOW GROUND TRUTH IS DEFINED, AND THREE WAYS IT WAS GOT WRONG FIRST
------------------------------------------------------------------
A row is POSITIVE when gold says the surname is not the token the line starts with: the gold
`name` begins with a ditto character, OR its first token differs from the line's first token. Each
clause was wrong on the first attempt and the corrections are worth keeping:

- Comparing raw tokens made `'Harkins, Margaret T'` vs gold `'Harkins Margaret T'` a positive on a
  trailing COMMA. Punctuation and case have to be normalised away.
- Normalising punctuation away then destroyed the signal in the other direction: it turned gold
  `-Adolph A` into `adolph`, matching the line's `Adolph`, and scored every real trow1913 positive
  as a negative. The leading ditto character has to be tested BEFORE normalising.
- `'Otev Wm'` -> gold `'Otey Wm'` is a misread SURNAME, not an implied one, and a bare token
  comparison counts it as a positive.

The first two each inverted the headline. Print the examples per bucket before trusting the counts.
"""

import argparse
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "postprocess"))

from resolve_dittos import is_ditto_lead                          # noqa: E402

NAMEY = re.compile(r"^[A-Z][A-Za-z’'.]*$")
# Glued or standalone. `-Adolph` and `" Thos` both say "same surname as above".
DITTO_CHARS = set("-\"“”'‘’*〃—«")
GATE_SHARE = 0.05
EXCLUDE = ("nyu", "ftd", "minneapolis", "sample500", "micro13")


def norm(s):
    return re.sub(r"[^A-Za-z]", "", s).casefold()


def harvest_lexicon(lines_path, min_count=5, min_ratio=0.90):
    n_given, n_lead = Counter(), Counter()
    with open(lines_path, encoding="utf-8") as fh:
        for ln in fh:
            if not ln.strip():
                continue
            raw = json.loads(ln)["raw_line"]
            toks = raw.split()
            if not toks:
                continue
            if is_ditto_lead(raw):
                if len(toks) >= 2:
                    n_given[toks[1]] += 1
            else:
                n_lead[toks[0]] += 1
    return {t for t, n in n_given.items()
            if n >= min_count and NAMEY.match(t) and len(t) >= 2
            and n / (n + n_lead[t]) >= min_ratio}


def is_positive(nm, lead):
    """Gold says this line's surname is NOT the token the line starts with.

    Order matters: the ditto character must be tested BEFORE normalisation, which would strip it.
    """
    if nm and nm[0] in DITTO_CHARS:
        return True
    g = nm.split()
    return bool(g) and norm(g[0]) != norm(lead)


def measure(gold_glob, given):
    per, buckets = {}, {"TP": [], "FN": [], "FP": []}
    for p in sorted(glob.glob(gold_glob)):
        if any(x in p for x in EXCLUDE):
            continue
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        if not rows:
            continue
        name = Path(p).name.replace("_eval.jsonl", "")
        gold_implied = sum(1 for r in rows
                           if ((r.get("record") or {}).get("name") or "")[:1] in DITTO_CHARS)
        raw_ditto = sum(1 for r in rows if is_ditto_lead(r["raw_line"]))
        tp = fp = tn = fn = 0
        for r in rows:
            raw = r["raw_line"]
            nm = (r.get("record") or {}).get("name") or ""
            toks = raw.split()
            if not toks or not nm or is_ditto_lead(raw):
                continue
            lead = toks[0]
            pos, flag = is_positive(nm, lead), lead in given
            key = "TP" if (pos and flag) else "FN" if pos else "FP" if flag else None
            if key and len(buckets[key]) < 40:
                buckets[key].append({"volume": name, "raw": raw[:60], "gold_name": nm})
            tp += pos and flag
            fn += pos and not flag
            fp += (not pos) and flag
            tn += (not pos) and not flag
        per[name] = {
            "rows": len(rows),
            "gold_implied_share": round(gold_implied / len(rows), 4),
            "raw_ditto_share": round(raw_ditto / len(rows), 4),
            "gate_applies_gold": gold_implied / len(rows) >= GATE_SHARE,
            "gate_applies_production": raw_ditto / len(rows) >= GATE_SHARE,
            "tp": tp, "fn": fn, "fp": fp, "tn": tn,
        }
    return per, buckets


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", default="data/1906BPL_lines.jsonl",
                    help="volume the lexicon is harvested from (1906BPL: the only volume "
                         "where the phenomenon is abundant, and it has no gold)")
    ap.add_argument("--gold", default="data/*_eval.jsonl")
    ap.add_argument("--out", default="results/implied_surname_validation.json")
    args = ap.parse_args(argv)

    given = harvest_lexicon(args.lines)
    per, buckets = measure(args.gold, given)

    blind = sum(v["fp"] for v in per.values())
    gated = sum(v["fp"] for v in per.values() if v["gate_applies_gold"])
    tn_all = sum(v["tn"] for v in per.values())
    tp = sum(v["tp"] for v in per.values())
    fn = sum(v["fn"] for v in per.values())
    disagree = [k for k, v in per.items()
                if v["gate_applies_gold"] != v["gate_applies_production"]]

    res = {
        "lexicon_source": args.lines, "lexicon_size": len(given),
        "fp_blind": blind, "fp_gated": gated,
        "fp_rate_blind": round(blind / (blind + tn_all), 5) if blind + tn_all else None,
        # tp+fn counts every gold row whose surname differs from the leading token. Only 6 are
        # this detector's case (mark ABSENT); the rest are marks present but glued or misread,
        # which is next-step #9. Kept separate so no one divides by the larger number.
        "n_gold_rows_surname_differs": tp + fn,
        "n_mark_absent_instances": tp,
        "recall_measurable": False,
        "recall_note": "6 clean mark-absent instances in the panel, all trow1913; the volume "
                       "where the phenomenon is abundant (1906BPL) has no labelled gold",
        "gate_share": GATE_SHARE,
        "gate_disagreements": disagree,
        "per_volume": per, "examples": buckets,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2), encoding="utf-8")

    e = sys.stderr
    print(f"lexicon from {args.lines}: {len(given)} types", file=e)
    print(f"\nfalse positives applied blind   {blind:>5}", file=e)
    print(f"false positives gated           {gated:>5}"
          f"   ({gated / (blind + tn_all):.2%} of {blind + tn_all:,} surname-first rows)", file=e)
    print(f"\ngold rows where the surname differs from the lead {tp + fn:>4}", file=e)
    print(f"  ... of which this detector's case (mark ABSENT)  {tp:>4}"
          "   -> RECALL IS NOT MEASURABLE", file=e)
    print("  the rest are marks present but glued or misread -- next-step #9, a different fault",
          file=e)
    print(f"\nproduction gate disagrees with gold on: {', '.join(disagree) or 'nothing'}", file=e)
    for k in disagree:
        v = per[k]
        print(f"    {k:<12} gold implied {v['gold_implied_share']:.1%}  "
              f"raw ditto-lead {v['raw_ditto_share']:.1%}  <- glued mark, blocked on next-step #9",
              file=e)
    print(f"  wrote {args.out}", file=e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
