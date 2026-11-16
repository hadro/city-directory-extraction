"""The finder's crosswalk (space/eras.py): the chains of the events it searches, from
data/addresses/anchors.parquet, as a small CSV beside the records the finder loads.

    uv run --with duckdb==2.0.0 python addresses/export_crosswalk.py      # data/space/crosswalk.csv

One row per anchor on a chain (place, street, y0, y1, chain, old, new, corner: a street-guide
corner, not a person, old_street). `street` is the registry's id for the new numbers (events.py);
`old_street` is the key the OLD numbers were printed under, which can be another street ("fulton av"
numbers before 1875 are today's "fulton" ones): search the old numbers under it. Anchors on no
chain are left out: they answer nothing. Only the events in
EVENTS: the finder searches Brooklyn's 1871-75 for now. Add one here when it is wanted.
"""
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent.parent
EVENTS = [("Brooklyn", 1871, 1875)]


if __name__ == "__main__":
    out = Path(sys.argv[1]) if sys.argv[1:] else HERE / "data/space/crosswalk.csv"
    events = ", ".join(f"('{p}', {a}, {b})" for p, a, b in EVENTS)
    n = duckdb.execute(f"""
        COPY (SELECT place, street, y0, y1, chain, old, new, corner, old_street
              FROM '{HERE}/data/addresses/anchors.parquet'
              WHERE chain >= 0 AND (place, y0, y1) IN ({events})
              ORDER BY place, street, chain, old, new) TO '{out}' (FORMAT csv, HEADER)""").fetchone()[0]
    print(f"{n:,} anchors -> {out}")
