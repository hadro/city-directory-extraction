# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Build the model x eval-set comparison table from the metrics log that eval/evaluate.py --save
appends to.

eval/evaluate.py --save results/scores.jsonl  writes one JSON line per scored run
({label, gold, macro_f1, row_exact_pct, per_field, ...}); this pivots them into a Markdown
table (rows = eval set, columns = model label) so the Phase-2 comparison assembles itself.
The latest run wins for any repeated (eval set, label) pair.

    python3 eval/results_table.py                                   # macro-F1 table to stdout
    python3 eval/results_table.py --metric row_exact_pct
    python3 eval/results_table.py --out results/eval_table.md       # tracked, publishable

Note: results/scores.jsonl is git-ignored (*.jsonl) -- it's a regenerable log. Commit the
generated results/eval_table.md (a .md, not ignored) as the publishable artifact.

    python3 eval/results_table.py --self-test                       # stdlib, no files needed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

METRICS = {"macro_f1": "macro-F1 (avg over present fields)",
           "micro_f1": "micro-F1 (frequency-weighted)",
           "row_exact_pct": "whole-row EM%"}


def eval_name(gold: str) -> str:
    base = os.path.basename(gold or "")
    for suf in ("_eval.jsonl", ".jsonl"):
        if base.endswith(suf):
            return base[: -len(suf)]
    return base or "?"


def build_table(records, metric: str) -> str:
    cells: dict = {}                       # (eval, label) -> value ; later run overwrites
    evals, labels = [], []
    for r in records:
        e, lab = eval_name(r.get("gold")), r.get("label") or "?"
        if e not in evals:
            evals.append(e)
        if lab not in labels:
            labels.append(lab)
        cells[(e, lab)] = r.get(metric)
    evals.sort()

    def fmt(v):
        if v is None:
            return "—"
        return f"{v:.1f}" if metric == "row_exact_pct" else f"{v:.3f}"

    head = "| eval set | " + " | ".join(labels) + " |"
    sep = "|" + "---|" * (len(labels) + 1)
    rows = ["| " + e + " | " + " | ".join(fmt(cells.get((e, lab))) for lab in labels) + " |"
            for e in evals]
    title = f"### Eval comparison — {METRICS.get(metric, metric)} (higher is better)\n"
    return title + "\n".join([head, sep, *rows]) + "\n"


def load(path: str):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def _self_test() -> int:
    recs = [
        {"gold": "data/nyu_eval.jsonl", "label": "gliner-medium", "macro_f1": 0.333, "row_exact_pct": 8.0},
        {"gold": "data/nyu_eval.jsonl", "label": "gemini-3.1-flash-lite", "macro_f1": 0.71, "row_exact_pct": 40.0},
        {"gold": "data/ftd_eval.jsonl", "label": "gliner-multi", "macro_f1": 0.25, "row_exact_pct": 5.0},
        {"gold": "data/nyu_eval.jsonl", "label": "gliner-medium", "macro_f1": 0.41, "row_exact_pct": 11.0},  # rerun wins
    ]
    md = build_table(recs, "macro_f1")
    print(md, file=sys.stderr)
    assert "| nyu |" in md and "| ftd |" in md
    assert "0.410" in md and "0.710" in md and "0.333" not in md      # latest nyu/gliner wins
    assert "—" in md                                                   # ftd x gemini/gliner-medium empty
    assert build_table(recs, "row_exact_pct").count("40.0") == 1
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", default="results/scores.jsonl", help="metrics log from evaluate.py --save")
    ap.add_argument("--out", default=None, help="write Markdown here (default: stdout)")
    ap.add_argument("--metric", choices=[*METRICS, "all"], default="all",
                    help="'all' (default) stacks macro-F1, micro-F1 and whole-row exact-match")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not os.path.exists(args.inp):
        sys.exit(f"no metrics log at {args.inp} (run eval/evaluate.py --save {args.inp} first)")

    recs = load(args.inp)
    if args.metric == "all":
        md = "\n".join(build_table(recs, m) for m in METRICS)
    else:
        md = build_table(recs, args.metric)
    if args.out:
        if os.path.dirname(args.out):
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"wrote table -> {args.out}", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
