#!/usr/bin/env python3
"""
Where the address finder's time goes (PIPELINE #39), on the Parquet the Space reads.

    uv run --with-requirements space/requirements.txt python results/finder_timing.py
    uv run --with-requirements space/requirements.txt python results/finder_timing.py --threads 2 \
        data/space/records.parquet "155 Franklin" "45 Fulton"

Start-up (records into memory, the word index), then per query: the search without the resident
trace, and with it, split into its phases (`find`'s `phases`): the word lookup (`terms`), the
candidates from the word index, fetching and grading the ones in the address's shape (`grade`),
the lines that may wrap it (`wrap`), the hits' whole rows (`hits`), and the trace. Every query runs
on the same warm connection. --threads 2 is the free CPU tier's count.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "space"), str(REPO / "browse")]
import search  # noqa: E402

QUERIES = ["155 Franklin", "166 Lefferts pl", "45 Fulton", "62 Euclid av"]


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parquet", nargs="?", default=str(REPO / "data" / "space" / "records.parquet"))
    ap.add_argument("queries", nargs="*", default=QUERIES)
    ap.add_argument("--threads", type=int, help="DuckDB threads (default: every core)")
    a = ap.parse_args(argv)
    recs = search.Records(a.parquet, threads=a.threads)
    print(f"{recs.rows:,} rows, {recs.words:,} words, loaded in {recs.load_s:.1f} s "
          f"(index: {recs.index})")
    for q in a.queries:
        plain = recs.find(q)
        traced = recs.find(q, people=True)
        print(f"{q!r}: {plain['candidates']:,} candidates, {plain['graded']:,} graded, "
              f"{plain['wrap']:,} wrap, {len(plain['hits']):,} hits | find {plain['seconds']:.2f} s, "
              f"with the trace {traced['seconds']:.2f} s: "
              + ", ".join(f"{k} {v:.2f}" for k, v in traced["phases"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
