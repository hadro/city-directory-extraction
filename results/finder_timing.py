#!/usr/bin/env python3
"""
Where the address finder's time goes (PIPELINE #39), on the Parquet the Space reads.

    uv run --with-requirements space/requirements.txt python results/finder_timing.py
    uv run --with-requirements space/requirements.txt python results/finder_timing.py \
        data/space/records.parquet "155 Franklin" "45 Fulton"

Per query: the vocabulary lookup (`terms`), the candidate scan (one regexp over every row), the
search without the resident trace, and with it. Every query runs on the same warm connection.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "space"), str(REPO / "browse")]
import find_address as fa  # noqa: E402
import search  # noqa: E402

QUERIES = ["155 Franklin", "166 Lefferts pl", "45 Fulton", "62 Euclid av"]


def main(argv: list) -> int:
    parquet = argv[0] if argv else str(REPO / "data" / "space" / "records.parquet")
    recs = search.Records(parquet)
    print(f"{recs.rows:,} rows, {recs.words:,} words, loaded in {recs.load_s:.1f} s")
    for q in argv[1:] or QUERIES:
        number, words, kind = fa.parse(q)
        anchor = fa.anchor_of(words)
        t = time.time()
        streets, numbers = recs.terms(number, anchor, 2)
        t_terms = time.time() - t
        streets, _ = fa.other_streets(streets, anchor)
        pat = r"\b(" + "|".join(x for x, _ in streets + numbers) + r")\b"
        t = time.time()
        rows = recs._dicts(f"SELECT {', '.join(search.COLS)} FROM r "
                           f"WHERE regexp_matches({search.TEXT}, ?)", [pat])
        t_scan = time.time() - t
        plain = recs.find(q)
        traced = recs.find(q, people=True)
        print(f"{q!r}: terms {t_terms:.2f} s ({len(streets)} street + {len(numbers)} number "
              f"terms) | scan {t_scan:.2f} s -> {len(rows):,} candidates | find "
              f"{plain['seconds']:.2f} s ({len(plain['hits']):,} hits) | with the trace "
              f"{traced['seconds']:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
