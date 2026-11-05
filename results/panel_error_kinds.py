#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What kind of wrong are the 4B's wrong rows on the 21-volume panel? Model alone, and guarded.

    python3 results/panel_error_kinds.py                       # print the tables
    python3 results/panel_error_kinds.py --out results/panel_error_kinds.json
    python3 results/panel_error_kinds.py --examples 10         # show what landed in each bucket
    python3 results/panel_error_kinds.py --self-test           # offline

WHY THIS EXISTS. Whole-row EM marks a row wrong over one misplaced comma, and the public write-up
wanted to say how wrong the wrong rows are. A claim like that needs a measurement, not an
impression. Written 2026-11-01 for the second blog post (docs/drafts/blog-post-2-other-cities.md).

FOOTING. Scored like `evaluate.py --report-normalized`: internal abbreviation periods stripped
from both sides, then evaluate.norm (whitespace, case, a trailing period). The model's own
predictions are results/runs/scale-runs/preds/preds_4b-100k_<vol>.txt, the board's 4b-100k run.
"Guarded" is postprocess/copy_guard.py applied in-process exactly as its `--lines/--preds` CLI
does it, with the vocabulary built from the panel set's own lines. Reproduced on 2026-11-01:
78.4 verbatim EM (the board's figure) and 81.9 normalized (the board's 82.0, presumably moved
by the 2026-10-14 gold corrections). Gold is gitignored and gets corrected, so the JSON records
each gold file's sha256: a later run that disagrees should compare those first.

A WRONG ROW GOES TO ONE BUCKET, the first that fits:

    same words      every word of the non-boolean fields is present on both sides, as a
                    multiset, and is_business agrees. Sub-split into punctuation only (the
                    differing fields agree once reduced to letters and digits), a ditto mark
                    dropped or added (that, plus a leading `-` or `"` on one side only), and
                    words moved between fields (`(Rev.)` filed under occupation, not name).
    small letters   every differing field differs by at most 2 characters, or only in
                    punctuation, and no field's digits change. Mixed by inspection: mostly the
                    model fixing a misprint the gold kept (`franlin` -> `franklin`), sometimes a
                    change of meaning (`msngr` -> `mngr`, `h r 247` losing the rear marker).
    content         anything else: a wrong or missing word, a changed number, is_business
                    flipped, an address in the wrong slot with its marker changed.

`digit_transpositions` counts content rows where some field's digits are the same multiset in
a different order (`618` -> `168`). The guard restores every one of the 22 the model makes.

TWO CAVEATS THAT TRAVEL WITH EVERY NUMBER HERE.
  * This is the CLEAN-TEXT panel: hand-checked lines. On IA's own OCR (eval/ia_panel.py) every
    figure is lower.
  * The guard was developed with this panel in view, so the guarded column is in-sample. Its
    first unseen test, the real-OCR panel, failed its pre-registered bar (docs/PIPELINE.md
    stage 5). Lead with the model-alone column.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "postprocess"))

from evaluate import FIELDS, _INNER_DOT, _cell, load_gold, load_pred, norm   # noqa: E402
from copy_guard import build_vocab, guard_file                               # noqa: E402

PANEL = ("boyd1890 doggett1846 duncan1794 franks1786 hearne1852 hopehenderson1856 lain1876 "
         "longworth1818 mb1931 mercein1820 ogden1839 polk1917 polk1925 polk1933bk polk1933si "
         "queens1933 rode1851 trow1884 trow1907 trow1913 trowwilson1865").split()
PREDS = REPO / "results" / "runs" / "scale-runs" / "preds" / "preds_4b-100k_{}.txt"
GOLD = REPO / "data" / "{}_eval.jsonl"

SAME, SMALL, CONTENT = "same words", "small letters", "content"
DITTO_LEAD = re.compile(r'^[-"“”\']')


def normed(rec: dict) -> dict:
    return {f: norm(_INNER_DOT.sub("", str(_cell(rec, f))), False) for f in FIELDS}


def lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s)


def _words(d: dict) -> list:
    return sorted(t for f in FIELDS if f != "is_business" for t in re.findall(r"[a-z0-9]+", d[f]))


def _digits(s: str) -> list:
    return re.findall(r"\d", s)


def classify(g: dict, p: dict):
    """(bucket, sub-bucket or None, digit transposition?) for one wrong row of normed records."""
    wrong = [f for f in FIELDS if g[f] != p[f]]
    if _words(g) == _words(p) and "is_business" not in wrong:
        if all(_alnum(g[f]) == _alnum(p[f]) for f in wrong):
            one_sided = any(bool(DITTO_LEAD.match(g[f])) != bool(DITTO_LEAD.match(p[f]))
                            for f in wrong)
            return SAME, "ditto mark dropped or added" if one_sided else "punctuation only", False
        return SAME, "words moved between fields", False

    def small(f):
        a, b = g[f], p[f]
        if f == "is_business" or not a or not b or _digits(a) != _digits(b):
            return False
        return lev(a, b) <= 2 or _alnum(a) == _alnum(b)

    if all(small(f) for f in wrong):
        return SMALL, None, False
    transposed = any(_digits(g[f]) and _digits(g[f]) != _digits(p[f])
                     and sorted(_digits(g[f])) == sorted(_digits(p[f])) for f in wrong)
    return CONTENT, None, transposed


def tally(pairs: list, n_examples: int = 3) -> dict:
    """pairs: [(volume, raw_line, gold record, predicted record)] -> one prediction set's summary."""
    rows = exact = 0
    cells, cells_ok = collections.Counter(), collections.Counter()
    filled, filled_ok = collections.Counter(), collections.Counter()
    kinds, subs, content_fields = collections.Counter(), collections.Counter(), collections.Counter()
    transposed = 0
    examples = collections.defaultdict(list)
    for vol, raw, gold, pred in pairs:
        rows += 1
        g, p = normed(gold), normed(pred)
        for f in FIELDS:
            cells[f] += 1
            cells_ok[f] += g[f] == p[f]
            if g[f] not in ("", "false") or p[f] not in ("", "false"):
                filled[f] += 1
                filled_ok[f] += g[f] == p[f]
        wrong = [f for f in FIELDS if g[f] != p[f]]
        if not wrong:
            exact += 1
            continue
        kind, sub, tr = classify(g, p)
        kinds[kind] += 1
        if sub:
            subs[sub] += 1
        if kind == CONTENT:
            content_fields.update(wrong)
            transposed += tr
        if len(examples[kind]) < n_examples:
            examples[kind].append({"volume": vol, "raw_line": raw,
                                   "diff": {f: [g[f], p[f]] for f in wrong}})
    n_wrong = rows - exact
    pct = lambda a, b: round(100 * a / b, 1) if b else None
    return {
        "rows": rows, "exact_normalized": exact, "exact_normalized_pct": pct(exact, rows),
        "field_accuracy_pct": {f: pct(cells_ok[f], cells[f]) for f in FIELDS}
                              | {"ALL": pct(sum(cells_ok.values()), sum(cells.values()))},
        "field_accuracy_filled_pct": {f: pct(filled_ok[f], filled[f]) for f in FIELDS}
                                     | {"ALL": pct(sum(filled_ok.values()), sum(filled.values()))},
        "filled_cells": dict(filled) | {"ALL": sum(filled.values())},
        "wrong_rows": n_wrong,
        "wrong_by_kind": {k: {"rows": kinds[k], "pct_of_wrong": pct(kinds[k], n_wrong),
                              "pct_of_all": pct(kinds[k], rows)} for k in (SAME, SMALL, CONTENT)},
        "same_words_split": dict(subs),
        "content_fields": dict(content_fields.most_common()),
        "digit_transpositions": transposed,
        "examples": dict(examples),
    }


def load(vol: str) -> tuple:
    """(gold rows, gold records, predicted records): the guard needs each row's raw_line."""
    path = str(GOLD).format(vol)
    with open(path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    gold = load_gold(path)
    pred = load_pred(str(PREDS).format(vol), "yaml")
    if not len(rows) == len(gold) == len(pred):
        raise SystemExit(f"{vol}: {len(pred)} predictions for {len(gold)} gold rows")
    return rows, gold, pred


def run(n_examples: int) -> dict:
    plain, guarded, shas = [], [], {}
    for vol in PANEL:
        rows, gold, pred = load(vol)
        shas[vol] = hashlib.sha256(Path(str(GOLD).format(vol)).read_bytes()).hexdigest()[:16]
        safe, _audit = guard_file(rows, pred, build_vocab(r["raw_line"] for r in rows))
        plain += [(vol, r["raw_line"], g, p) for r, g, p in zip(rows, gold, pred)]
        guarded += [(vol, r["raw_line"], g, p) for r, g, p in zip(rows, gold, safe)]
    return {"run": "4b-100k", "panel": PANEL, "gold_sha256_16": shas,
            "model": tally(plain, n_examples), "model+guard": tally(guarded, n_examples)}


def show(res: dict) -> None:
    a, b = res["model"], res["model+guard"]
    print(f"{a['rows']} panel rows, 4b-100k            model    +guard")
    print(f"  exact (normalized)              {a['exact_normalized_pct']:6.1f}   {b['exact_normalized_pct']:6.1f}")
    print(f"  field values right              {a['field_accuracy_pct']['ALL']:6.1f}   {b['field_accuracy_pct']['ALL']:6.1f}")
    print(f"  ...of the non-blank ones        {a['field_accuracy_filled_pct']['ALL']:6.1f}   {b['field_accuracy_filled_pct']['ALL']:6.1f}")
    for f in FIELDS:
        print(f"    {f:28s}  {a['field_accuracy_filled_pct'][f]:6.1f}   "
              f"{b['field_accuracy_filled_pct'][f]:6.1f}   (n={a['filled_cells'][f]})")
    print(f"  wrong rows                      {a['wrong_rows']:6d}   {b['wrong_rows']:6d}")
    for k in (SAME, SMALL, CONTENT):
        ka, kb = a["wrong_by_kind"][k], b["wrong_by_kind"][k]
        print(f"    {k:13s} % of wrong       {ka['pct_of_wrong']:6.1f}   {kb['pct_of_wrong']:6.1f}"
              f"   (% of all rows {ka['pct_of_all']} / {kb['pct_of_all']})")
    print(f"  same-words split   model {a['same_words_split']}")
    print(f"                     guard {b['same_words_split']}")
    print(f"  digit transpositions            {a['digit_transpositions']:6d}   {b['digit_transpositions']:6d}")


def _self_test() -> int:
    blank = {f: "" for f in FIELDS} | {"is_business": False}
    rec = lambda **kw: normed(blank | kw)
    assert classify(rec(name="Smith John", address="12 Pine, N Y"),
                    rec(name="Smith John", address="12 Pine N Y"))[:2] == (SAME, "punctuation only")
    assert classify(rec(name="-Anna"), rec(name="Anna"))[:2] == (SAME, "ditto mark dropped or added")
    assert classify(rec(name="Quinn Edward (Rev.)"), rec(name="Quinn Edward",
                    occupation_role="(Rev.)"))[:2] == (SAME, "words moved between fields")
    assert classify(rec(address="170 Franlin"), rec(address="170 Franklin"))[0] == SMALL
    assert classify(rec(address="h 618 Lorimer"), rec(address="h 168 Lorimer")) == \
        (CONTENT, None, True), "a digit change is never small, and this one is a transposition"
    assert classify(rec(address="4 Bancker"), rec(address="5 Bancker")) == (CONTENT, None, False)
    assert classify(rec(occupation_role="gdnr"), rec(occupation_role="mngr"))[0] == CONTENT
    assert classify(rec(name="Wetmore & Co", is_business=True),
                    rec(name="Wetmore & Co"))[0] == CONTENT, "is_business flipped"
    t = tally([("v", "A b", blank | {"name": "A b"}, blank | {"name": "A b"}),
               ("v", "C d h 618 X", blank | {"name": "C d", "address": "h 618 X"},
                blank | {"name": "C d", "address": "h 168 X"})])
    assert t["exact_normalized"] == 1 and t["digit_transpositions"] == 1
    assert t["wrong_by_kind"][CONTENT]["pct_of_all"] == 50.0
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="write the result as JSON")
    ap.add_argument("--examples", type=int, default=3, help="examples kept per bucket")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    res = run(args.examples)
    show(res)
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
