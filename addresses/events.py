"""Renumbering events, from the directories themselves (RENUMBERING_PLAN 1.3).

    uv run --with duckdb==2.0.0 python addresses/events.py data/space/records.parquet

results/renumbering.py grown up. For each place, each street (streets.read's key, with the
district a line prints) and each pair of consecutive directory years: the names on the street
once in both years, how many kept their number, and whether those who changed kept their order.
A pair of years is an event when at least MIN_BOTH names are followed, at least half changed
number, and that is CLEAR above the street's own usual share (its median over its other pairs:
people moving along a street and misread numbers).

Writes addresses/tables/events.csv (every event, both places) and
data/addresses/stayers.parquet (every followed name: place, street, y0, y1, name, n0, n1), which
the anchors are built from. Everything is recomputed from the records file, so a re-run on a
records file with more volumes redoes the lot; a new directory year inside a gap narrows the
event's dates by itself.

kind: renumbered (order kept), reversed (order turned: numbered from the other end), mixed
(neither: look at it). weak: the two directories are more than 3 years apart, so ordinary moves
add up.
"""
import csv
import statistics
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "results"))
import streets  # noqa: E402
from renumbering import CITY, in_order  # noqa: E402

MIN_BOTH = 15
CLEAR = 0.3
ORDERED = 0.7     # of the changed pairs; movers and misreadings break order (Court 1871-75: 0.77)
HERE = Path(__file__).resolve().parent
ADDR = "coalesce(nullif(home_address_resolved, ''), address_resolved)"


def load(con, parquet: str):
    """`a`: (place, year, name, street, number), a name once on a street in a year."""
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{parquet}')")
    strings = [a for a, in con.execute(
        f"SELECT DISTINCT {ADDR} FROM r WHERE {ADDR} IS NOT NULL").fetchall()]
    read = [(a, r["number"], r["street"] + (" (e.d.)" if r["district"] == "e" else ""))
            for a in strings if (r := streets.read(a)) and not r["half"]]
    con.execute("CREATE TABLE s (a VARCHAR, number INTEGER, street VARCHAR)")
    con.executemany("INSERT INTO s VALUES (?, ?, ?)", read) if len(read) < 1000 else \
        con.execute("INSERT INTO s SELECT * FROM read_json(?)", [_dump(read)])
    places = " ".join(f"WHEN {sql} THEN '{place}'" for place, sql in CITY.items())
    con.execute(f"""
        CREATE TABLE a AS
        SELECT place, year, name, street, any_value(number) AS number FROM (
            SELECT CASE {places} END AS place, year, lower(trim(name_resolved)) AS name,
                   s.street, s.number
            FROM r JOIN s ON s.a = {ADDR}
            WHERE name_resolved IS NOT NULL AND length(name_resolved) > 3)
        WHERE place IS NOT NULL GROUP BY ALL HAVING count(*) = 1""")
    con.execute("""
        CREATE TABLE steps AS
        SELECT place, year AS y0, lead(year) OVER (PARTITION BY place ORDER BY year) AS y1
        FROM (SELECT DISTINCT place, year FROM a) QUALIFY y1 IS NOT NULL""")
    con.execute("""
        CREATE TABLE pairs AS
        SELECT s.place, a0.street, s.y0, s.y1, a0.name, a0.number AS n0, a1.number AS n1
        FROM steps s JOIN a a0 ON a0.place = s.place AND a0.year = s.y0
             JOIN a a1 ON a1.place = s.place AND a1.year = s.y1
                      AND a1.name = a0.name AND a1.street = a0.street""")


def _dump(rows) -> str:
    """Rows as a JSON file DuckDB reads in one go (executemany is slow for a million)."""
    import json
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump([{"a": a, "number": n, "street": s} for a, n, s in rows], f)
    f.close()
    return f.name


def events(con) -> list:
    stats = con.execute("""
        SELECT place, street, y0, y1, count(*) AS both, sum((n0 <> n1)::INT) AS changed
        FROM pairs GROUP BY ALL HAVING count(*) >= 10 ORDER BY place, street, y0""").fetchall()
    by_street = {}
    for place, street, y0, y1, both, changed in stats:
        by_street.setdefault((place, street), []).append((y0, y1, both, changed / both))
    out = []
    for (place, street), rows in by_street.items():
        for y0, y1, both, share in rows:
            others = [s for a, _, _, s in rows if a != y0]
            usual = statistics.median(others) if others else 0.0
            if both < MIN_BOTH or share < 0.5 or share < usual + CLEAR:
                continue
            moved = con.execute("""SELECT n0, n1 FROM pairs WHERE place = ? AND street = ?
                                   AND y0 = ? AND n0 <> n1""", [place, street, y0]).fetchall()
            order = in_order(moved)
            out.append({"place": place, "street": street, "last_old_year": y0,
                        "first_new_year": y1, "stayers": both, "kept": both - len(moved),
                        "in_order": round(order, 2), "usual_changed": round(usual, 2),
                        "kind": "renumbered" if order >= ORDERED else
                                "reversed" if order <= 1 - ORDERED else "mixed",
                        "weak": int(y1 - y0 > 3)})
    return sorted(out, key=lambda e: (e["place"], e["last_old_year"], -e["stayers"]))


def main(parquet: str):
    con = duckdb.connect()
    load(con, parquet)
    (HERE.parent / "data/addresses").mkdir(parents=True, exist_ok=True)
    con.execute("COPY pairs TO 'data/addresses/stayers.parquet' (FORMAT parquet)")
    found = events(con)
    (HERE / "tables").mkdir(exist_ok=True)
    with open(HERE / "tables/events.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(found[0]))
        w.writeheader()
        w.writerows(found)
    key = {(e["place"], e["street"], e["last_old_year"]): e for e in found}
    # the cases measured by hand before this was written (results/renumbering.py)
    assert key[("Brooklyn", "court", 1871)]["kind"] == "renumbered"
    assert ("Brooklyn", "court", 1907) not in key
    assert key[("Brooklyn", "berry", 1887)]["kind"] == "reversed"
    by = {}
    for e in found:
        by.setdefault((e["place"], e["last_old_year"], e["first_new_year"]), []).append(e)
    print(f"{len(found)} events -> addresses/tables/events.csv")
    for (place, y0, y1), es in sorted(by.items()):
        kinds = {k: sum(e["kind"] == k for e in es) for k in ("renumbered", "reversed", "mixed")}
        print(f" {place:<10} {y0}-{y1}  {len(es):>4} streets  {kinds}  "
              + ", ".join(e["street"] for e in es[:6]))


if __name__ == "__main__":
    main(sys.argv[1])
