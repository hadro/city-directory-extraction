#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Split `ocr_delta.py`'s pairs into OCR fix vs labelling convention vs wrap completion.

    python3 results/ocr_edit_types.py                      # read data/ocr_pairs.jsonl
    python3 results/ocr_edit_types.py --out results/ocr_edit_types.json
    python3 results/ocr_edit_types.py --examples 10        # show what landed in each bucket
    python3 results/ocr_edit_types.py --self-test          # offline

WHY THIS EXISTS. `ocr_delta.py` reports that labellers changed 45.0% of gold rows at CER 0.1829,
and docs/POST_OCR_CORRECTION.md §5 says that number cannot be used, because a gold edit is one of
three unrelated things and only one of them is OCR quality:

    OCR fix          `Eliabeth` -> `Elizabeth`          the scanner misread the page
    convention       `285½` -> `285 1/2`                conv #4; the page is not wrong
    wrap completion  `h. 75 Mul-` -> `h. 75 Mulberry`   conv 9a/15; the OCR line was truncated

Only the first says anything about OCR. Every downstream decision -- whether to correct at all,
whether to re-aim the generator's noise model, where the §7 gate sits -- is blocked on separating
them, so this does that and nothing else.

THE PART THAT IS EASY TO GET WRONG: ROWS ARE MIXED. A first pass bucketed whole rows and put any
row that was BOTH a wrap and a misread into the OCR bucket, carrying the wrap's edit distance with
it -- `Barnett Eliabeth E (wid George W), r` -> `Barnett Elizabeth E (wid George W), r 111 E
Cameron.` is one substitution and one 15-character tail insertion, and counting the tail inflates
OCR CER by an order of magnitude on exactly the volumes that wrap most.

So attribution is per EDIT, not per row, over `SequenceMatcher` opcodes:

  * an insert/replace touching the START or END of the line is segmentation -- a truncated OCR
    line, a joined continuation, a column break. Excluded.
  * everything interior is an OCR edit, after convention normalisation has been applied to both
    sides so a `½` does not read as two substitutions.

This is deliberately conservative in the direction that matters: a real misread in the first or
last token is charged to segmentation and the reported CER is therefore a FLOOR. The previous
whole-row number (0.0190) is the matching ceiling, and both are reported.

WHAT IT CANNOT DO. It cannot separate a labeller's OCR fix from a labeller's slip -- both are
edits -- and it cannot tell a misread from an alignment failure when the two lines simply are not
the same line. Rows whose edit distance exceeds 40% of their length are counted as alignment
failures rather than silently averaged in; that bucket is 3.1% and is concentrated in `tulsa`.

AND THE CAVEAT THAT OUTRANKS THE RESULT: this is SURYA output, because that is what the gold tool
pre-filled from. Production ingests IA hOCR. A CER measured here does not transfer to the engine
the pipeline actually runs on, and no amount of bucketing fixes that.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

# conv #4 (fractions), conv #5 (long-s), plus the typographic folds the contract implies.
_CONV = (("½", " 1/2"), ("¼", " 1/4"), ("¾", " 3/4"), ("ſ", "s"),
         ("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
         ("—", "-"), ("–", "-"))

ALIGN_FAIL_RATIO = 0.40


def conv(s: str) -> str:
    for a, b in _CONV:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def wrap_class(o: str, g: str):
    """Whole-row segmentation signatures, for the bucket counts. None = not obviously a wrap."""
    os_, gs = o.strip(), g.strip()
    if "\n" in o:
        return "newline"
    if os_.endswith("-"):
        return "trailing hyphen"
    if gs.startswith(os_) and len(gs) > len(os_):
        return "gold appends"
    if gs.endswith(os_) and len(gs) > len(os_):
        return "gold prepends"
    if re.sub(r"-\s+", "", os_) == re.sub(r"-\s+", "", gs) and os_ != gs:
        return "internal hyphen join"
    return None


def attribute(co: str, cg: str):
    """(interior_edits, boundary_edits) over convention-normalised strings.

    Boundary = an opcode touching position 0 of either side, or the end of either side. Those are
    truncations and joins. Interior edits are the OCR signal.
    """
    sm = SequenceMatcher(None, co, cg, autojunk=False)
    interior = boundary = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        size = max(i2 - i1, j2 - j1)
        at_start = i1 == 0 or j1 == 0
        at_end = i2 == len(co) or j2 == len(cg)
        if at_start or at_end:
            boundary += size
        else:
            interior += size
    return interior, boundary


def analyse(rows):
    buckets = Counter()
    per = defaultdict(lambda: {"interior": 0, "whole": 0, "chars": 0})
    examples = defaultdict(list)

    for r in rows:
        o, g, v = r["ocr"], r["gold"], r.get("volume", "?")
        if o == g:
            buckets["A pass-through"] += 1
            per[v]["chars"] += len(g)
            continue

        co, cg = conv(o), conv(g)
        if co == cg:
            buckets["C convention-only"] += 1
            per[v]["chars"] += len(cg)
            examples["C"].append((o, g))
            continue

        interior, boundary = attribute(co, cg)
        w = wrap_class(o, g)

        # Pure boundary edits are segmentation at ANY size -- a 35-character tail on a truncated
        # line is still a truncation. Checking the size guard first mis-filed 391 of these as
        # alignment failures, which is how this ordering bug was found.
        if interior == 0:
            buckets["B wrap / segmentation"] += 1
            buckets["  ." + (w or "boundary edit only")] += 1
            examples["B"].append((o, g))
            continue

        # Only INTERIOR damage can indict the alignment: boundary edits are already excused.
        if interior > ALIGN_FAIL_RATIO * max(len(co), len(cg)):
            buckets["E alignment failure"] += 1
            examples["E"].append((o, g))
            continue

        buckets["D OCR fix"] += 1
        if w:
            buckets["  .D also carries a wrap"] += 1
        per[v]["interior"] += interior
        per[v]["whole"] += interior + boundary
        per[v]["chars"] += len(cg)
        examples["D"].append((o, g))

    return buckets, per, examples


def report(buckets, per, examples, n_examples, w=sys.stdout):
    tot = sum(v for k, v in buckets.items() if not k.startswith("  ."))
    print(f"{'bucket':<28}{'n':>7} {'share':>8}", file=w)
    for k in sorted(buckets):
        if k.startswith("  ."):
            print(f"{k:<28}{buckets[k]:>7}", file=w)
        else:
            print(f"{k:<28}{buckets[k]:>7} {100 * buckets[k] / tot:>7.1f}%", file=w)
    print(f"{'TOTAL':<28}{tot:>7}", file=w)

    I = sum(p["interior"] for p in per.values())
    W = sum(p["whole"] for p in per.values())
    C = sum(p["chars"] for p in per.values())
    if C:
        print(f"\nOCR CER, interior edits only (FLOOR)   {I:,} / {C:,} = {I / C:.4f}", file=w)
        print(f"OCR CER, whole changed rows (CEILING)  {W:,} / {C:,} = {W / C:.4f}", file=w)
        print("ocr_delta.py whole-corpus figure                       0.1829", file=w)
        print("Huynh/Hamdi/Doucet net-harm floor                      0.03", file=w)

    rank = sorted(((p["interior"] / p["chars"], v, p) for v, p in per.items() if p["chars"] > 400),
                  reverse=True)
    print(f"\nper volume, interior-edit CER (n={len(rank)} with >400 gold chars):", file=w)
    for cer, v, p in rank:
        flag = "  <- above the 0.03 floor" if cer >= 0.03 else ""
        print(f"  {v:<20}{cer:>8.4f}  {p['interior']:>5,}/{p['chars']:<7,}{flag}", file=w)

    for key, label in (("D", "OCR fixes"), ("B", "wrap / segmentation"),
                       ("C", "convention-only"), ("E", "alignment failures")):
        if not examples[key] or not n_examples:
            continue
        print(f"\n{label}:", file=w)
        for o, g in examples[key][:n_examples]:
            print(f"    ocr : {o[:88]}\n    page: {g[:88]}", file=w)


def _self_test():
    rows = [
        {"ocr": "Smith John clerk 12 Pine", "gold": "Smith John clerk 12 Pine", "volume": "t"},
        # convention only
        {"ocr": "Jones Amy h 285½ 14th", "gold": "Jones Amy h 285 1/2 14th", "volume": "t"},
        # pure wrap: gold appends a tail
        {"ocr": "Foster Sam porterhouse, h. 75 Mul-",
         "gold": "Foster Sam porterhouse, h. 75 Mulberry", "volume": "t"},
        # MIXED: interior misread + tail insertion. Only the misread may be charged.
        {"ocr": "Barnett Eliabeth E (wid Geo W), r",
         "gold": "Barnett Elizabeth E (wid Geo W), r 111 E Cameron.", "volume": "t"},
    ]
    b, per, _ = analyse(rows)
    assert b["A pass-through"] == 1, b
    assert b["C convention-only"] == 1, b
    assert b["B wrap / segmentation"] == 1, b
    assert b["D OCR fix"] == 1, b
    # the mixed row contributes ONE interior edit (b->z), not the 16-char tail
    assert per["t"]["interior"] == 1, per["t"]
    assert per["t"]["whole"] > per["t"]["interior"], per["t"]
    # boundary attribution: a leading truncation is never an OCR edit
    i, bd = attribute("son Payne & Henry", "ADKISON Payne & Henry")
    assert i == 0 and bd > 0, (i, bd)
    print("ocr_edit_types self-test OK")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", default="data/ocr_pairs.jsonl",
                    help="ocr_delta.py --out file (default data/ocr_pairs.jsonl)")
    ap.add_argument("--out", help="write the summary as JSON")
    ap.add_argument("--examples", type=int, default=0, help="rows to print per bucket")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()
    p = Path(a.pairs)
    if not p.exists():
        ap.error(f"{p} not found -- regenerate with the ocr_delta.py command in its docstring")

    rows = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    buckets, per, examples = analyse(rows)
    report(buckets, per, examples, a.examples)

    if a.out:
        I = sum(x["interior"] for x in per.values())
        W = sum(x["whole"] for x in per.values())
        C = sum(x["chars"] for x in per.values())
        Path(a.out).write_text(json.dumps({
            "pairs": len(rows),
            "buckets": {k: v for k, v in sorted(buckets.items())},
            "cer_interior_floor": round(I / C, 6) if C else None,
            "cer_whole_row_ceiling": round(W / C, 6) if C else None,
            "ocr_delta_reported_cer": 0.1829,
            "net_harm_floor": 0.03,
            "per_volume": {v: {"cer_interior": round(x["interior"] / x["chars"], 6),
                               "interior_edits": x["interior"], "gold_chars": x["chars"]}
                           for v, x in sorted(per.items()) if x["chars"] > 400},
            "engine": "surya (NOT the IA hOCR production ingests)",
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
