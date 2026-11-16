"""The finder's crosswalk (space/eras.py): the chains of the events it searches, from
data/addresses/anchors.parquet, as a small CSV beside the records the finder loads.

    uv run --with duckdb==2.0.0 python addresses/export_crosswalk.py      # data/space/crosswalk.csv

One row per anchor on a chain (place, street, y0, y1, chain, old, new, corner: a street-guide
corner, not a person, old_street, keys). `street` is the registry's id for the new numbers
(events.py); `old_street` is the key the OLD numbers were printed under, which can be another street
("fulton av" numbers before 1875 are today's "fulton" ones): search the old numbers under it. `keys`
is the other printed keys that are `street` in the later year (registry.keys, ";" apart: "e baltic;
w baltic" for baltic, "elliott pl" for s elliott pl), so the finder, which has not the registry's
tables, takes a typed "Elliott pl" to its id. Anchors on no chain are left out: they answer
nothing. Only the events in EVENTS: the finder searches Brooklyn's 1871-75 for now. Add one here
when it is wanted.
"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import registry  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
EVENTS = [("Brooklyn", 1871, 1875)]


if __name__ == "__main__":
    out = Path(sys.argv[1]) if sys.argv[1:] else HERE / "data/space/crosswalk.csv"
    events = ", ".join(f"('{p}', {a}, {b})" for p, a, b in EVENTS)
    anchors = f"'{HERE}/data/addresses/anchors.parquet'"
    where = f"chain >= 0 AND (place, y0, y1) IN ({events})"
    duckdb.execute("CREATE TABLE k (place VARCHAR, street VARCHAR, keys VARCHAR)")
    duckdb.executemany("INSERT INTO k VALUES (?, ?, ?)", [
        (p, s, ";".join(k for k in registry.keys(p, s, y1) if k != s))
        for p, s, y1 in duckdb.execute(f"SELECT DISTINCT place, street, y1 FROM {anchors} "
                                       f"WHERE {where}").fetchall()])
    n = duckdb.execute(f"""
        COPY (SELECT a.place, a.street, y0, y1, chain, old, new, corner, old_street, keys
              FROM {anchors} a JOIN k USING (place, street) WHERE {where}
              ORDER BY a.place, a.street, chain, old, new) TO '{out}' (FORMAT csv, HEADER)""").fetchone()[0]
    print(f"{n:,} anchors -> {out}")
