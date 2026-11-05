#!/usr/bin/env python3
"""
Where the address finder's time goes (PIPELINE #39), on the Parquet the Space reads.

    uv run --with-requirements space/requirements.txt python results/finder_timing.py
    uv run --with-requirements space/requirements.txt python results/finder_timing.py --threads 2 \
        data/space/records.parquet "155 Franklin" "45 Fulton"

Start-up (records into memory, the word index), then per query: the word lookup (`terms`), the
candidates from the word index, the search without the resident trace, and with it, with how
many candidates passed the address shape and were graded. Every query runs on the same warm
connection. --threads 2 is the free CPU tier's count.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "space"), str(REPO / "browse")]
import find_address as fa  # noqa: E402
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
        number, words, kind = fa.parse(q)
        anchor = fa.anchor_of(words)
        t = time.time()
        streets, numbers = recs.terms(number, anchor, 2)
        t_terms = time.time() - t
        streets, _ = fa.other_streets(streets, anchor)
        t = time.time()
        rows = recs.candidates(number, streets, numbers)
        t_cand = time.time() - t
        plain = recs.find(q)
        traced = recs.find(q, people=True)
        print(f"{q!r}: terms {t_terms:.2f} s ({len(streets)} street + {len(numbers)} number "
              f"terms) | candidates {t_cand:.2f} s -> {len(rows):,}, {plain['graded']:,} graded, "
              f"{plain['wrap']:,} wrap | find {plain['seconds']:.2f} s ({len(plain['hits']):,} "
              f"hits) | with the trace {traced['seconds']:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
