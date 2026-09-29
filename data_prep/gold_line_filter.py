#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Drop every line whose text IS a gold line: the holdout that page tags cannot give.

    python3 data_prep/gold_line_filter.py --in data/survey_ocr/X_lines.jsonl.gz --out Y.jsonl.gz
    python3 data_prep/gold_line_filter.py --report data/survey_ocr/*_lines.jsonl.gz
    python3 data_prep/gold_line_filter.py --self-test

WHY (docs/SURVEY_PLAN.md, "Twins"; PIPELINE.md stage 6). The harvest tags gold PAGES as eval
holdout, in the gold's own volume and, since GOLD_TWINS, in every other scan of the same
edition. That cannot reach the gold's TEXT printed elsewhere. Neighbouring editions reprint
entries verbatim: Doggett 1845 and 1847 carry 22-27% of the doggett1846 gold lines word for word,
Trow 1905/06 about 10-12% of trow1907's, Lain 1875 9.7% of lain1876's. A training set drawn from
harvested lines would hold those lines, untagged, and every panel number would then be measured
partly on training data.

So this is the complete guard: a line whose normalised text equals any gold line's is removed.
Normalised the way the twin scan matched them (survey_twins.norm: lower-case, punctuation to
spaces), so `Smith John, 12 Pine.` and `smith john 12 pine` are the same line. Short lines are
not matched (survey_twins.eligible): `do 12 main` is in every book and proves nothing.

The gold is every data/*_eval.jsonl except the derived files (survey_twins.SKIP and the
`iapanel_*` sets), NYPL-sourced sets included. They are the ones no page tag can reach.
Nothing reads this yet: training is synthetic today. It is the gate any harvest-drawn training
set must pass.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from survey_twins import DERIVED_PREFIX, SKIP, eligible, norm  # noqa: E402


def gold_lines() -> dict:
    """{normalised gold line: [gold set files]} over every gold set."""
    out = {}
    for path in sorted((REPO / "data").glob("*_eval.jsonl")):
        if path.name.startswith(DERIVED_PREFIX) or path.name in SKIP:
            continue
        for line in path.open(encoding="utf-8"):
            if line.strip():
                t = norm(json.loads(line).get("raw_line") or "")
                if eligible(t):
                    out.setdefault(t, []).append(path.name)
    return out


def _open(path: Path, mode: str):
    return gzip.open(path, mode + "t", encoding="utf-8") if path.suffix == ".gz" \
        else open(path, mode, encoding="utf-8")


def filter_file(src: Path, dst, gold: dict) -> dict:
    """Copy src to dst without gold lines; -> {kept, dropped, by_set}."""
    kept = dropped = 0
    by_set = {}
    out = _open(Path(dst), "w") if dst else None
    with _open(src, "r") as fh:
        for line in fh:
            if not line.strip():
                continue
            t = norm(json.loads(line).get("raw_line") or "")
            sets = gold.get(t) if eligible(t) else None
            if sets:
                dropped += 1
                for s in set(sets):
                    by_set[s] = by_set.get(s, 0) + 1
                continue
            kept += 1
            if out:
                out.write(line if line.endswith("\n") else line + "\n")
    if out:
        out.close()
    return {"kept": kept, "dropped": dropped, "by_set": by_set}


def _self_test() -> int:
    gold = {norm("Holmes Isaac, policeman, 53 Butler"): ["smith1856_eval.jsonl"]}
    assert norm("holmes isaac policeman 53 butler") in gold
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.jsonl"
        src.write_text("\n".join(json.dumps({"raw_line": t}) for t in (
            "Holmes Isaac, policeman, 53 Butler.",       # the gold line, punctuated differently
            "Holmes Isaac, policeman, 58 Butler",        # an OCR digit apart: not the same line
            "do 12 main")) + "\n", encoding="utf-8")
        r = filter_file(src, Path(d) / "out.jsonl", gold)
        assert (r["kept"], r["dropped"]) == (2, 1), r
        assert r["by_set"] == {"smith1856_eval.jsonl": 1}
    assert len(gold_lines()) > 5000, "the real gold loads"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", help="a JSONL (or .jsonl.gz) of {raw_line, ...} lines")
    ap.add_argument("--out", help="where the kept lines go")
    ap.add_argument("--report", nargs="*", help="count gold lines in these files, write nothing")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    gold = gold_lines()
    print(f"{len(gold):,} distinct gold lines", file=sys.stderr)
    if args.report:
        total = 0
        for p in args.report:
            r = filter_file(Path(p), None, gold)
            total += r["dropped"]
            if r["dropped"]:
                top = sorted(r["by_set"].items(), key=lambda kv: -kv[1])[:3]
                print(f"{Path(p).name:48s} {r['dropped']:6,d} gold lines of "
                      f"{r['kept'] + r['dropped']:9,d}  {top}")
        print(f"{total:,} gold lines in {len(args.report)} files")
        return 0
    if not (args.src and args.out):
        ap.error("--in and --out, or --report")
    r = filter_file(Path(args.src), Path(args.out), gold)
    print(f"kept {r['kept']:,}, dropped {r['dropped']:,} gold lines {r['by_set']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
