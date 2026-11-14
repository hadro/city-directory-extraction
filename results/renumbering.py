"""
Was a street renumbered? The directories say so themselves: a renumbering moves everyone who
stayed put to a new number at once. Between two consecutive directories of a city, take each
name found on the street in both (once on it in each, so not a namesake) and compare its numbers:
most people who stay keep their number, and a few change it by moving along the street or by
an OCR misreading; in the year a street is renumbered most of them change, and in the same order
(the house that was further along still is).

    uv run --with duckdb==2.0.0 python results/renumbering.py data/space/records.parquet Court Brooklyn
    uv run --with duckdb==2.0.0 python results/renumbering.py data/space/records.parquet --scan Brooklyn

With a street, every pair of consecutive years: names on it in both, how many kept their number,
and of those that changed, how many keep their order (a renumbering keeps it, people moving and
misreadings don't). With --scan, the same for every street with 20+ names in both years, the pairs
where over half changed, in order: a list of likely renumberings to check against the scans.

`home_address_resolved`, or `address_resolved` where there is no home, read as a number and the
street's words ("h 462 Court" -> 462, "court"), the street type dropped (st, street, av, avenue...
folded to the bare name, so Court and Court st are one, but Court and Court pl are not).

Found, 2026-11-14 (renumbering_court_brooklyn.txt, renumbering_brooklyn.txt,
renumbering_manhattan.txt), over the Space's records (15,497,151 lines):
- Court st, Brooklyn: renumbered between the 1871 and 1875 directories (none for 1872-74 here):
  of 118 names on it in both, 3 kept their number; every other pair of years, 70-98% kept it. Not
  one shift: 216 -> 294 and 224 -> 302 near the north end, 643 -> 459, 645 -> 465, 651 -> 467
  further south (people followed across it), so today's 462 was in the old 640s. Everyone
  followed there is on the odd side, so which even number is for a scan or an atlas to say.
- Brooklyn, 1871-1875: 103 streets, the city-wide renumbering local histories date to 1870-71.
  Williamsburg, 1887-1889: Berry, Driggs, Havemeyer and Roebling reversed (in order 0.02-0.06),
  Bedford, Wythe, Keap, Hewes and Clymer renumbered in order. Also 1824-25 (Fulton, Front, Main,
  Sands), 1858-59 (Columbia, Pacific, Cumberland).
- Trow's (New York), 1907-1908: the Bronx's streets (Westchester av, Jennings, Wendover, Simpson,
  Longwood, Home...) and Convent av, in order. 1865-1876, the avenues (Third, Eighth, Ninth, First,
  Second, A): no directory here in between.
Caveats: over a long gap between directories (1865-76, 1889-99, 1848-54) people moving along a
street change their numbers too, so a flag there is weaker; Atlantic and Fulton flagged twice
running (1865-66 and 1866-67) may be the 1866 volume's reading rather than the streets; a
common name can still be two people on one street, and a misread number is a change.
"""
from __future__ import annotations

import sys

import duckdb

CITY = {"Brooklyn": "(city IN ('Brooklyn', 'Williamsburgh') OR borough = 'Brooklyn')",
        "Manhattan": "(city = 'New York' AND coalesce(borough, 'Manhattan') = 'Manhattan')"}
# the number and the street after it; a "h"/"r" (home, rooms) may lead
ADDRESS = r"^(?:[hr]\.? )?([0-9]+)\s+([a-z][a-z .']*?)\.?$"
TYPE = r"\s+(st|street|av|ave|avenue)$"     # folded away: Court st is Court
ADDRESS_SQL = ADDRESS.replace("'", "''")       # inlined in SQL


def stayers(con, place: str):
    """(year, name, number, street) of every line in the city whose address reads as one, the
    years in order. A name on a street twice in a year (namesakes, a business and a home) is
    left out of that year for that street."""
    con.execute(f"""
        CREATE OR REPLACE TABLE a AS
        WITH x AS (
            SELECT year, lower(trim(name_resolved)) AS name,
                   lower(trim(coalesce(nullif(home_address_resolved, ''), address_resolved))) AS addr
            FROM r WHERE {CITY[place]} AND name_resolved IS NOT NULL AND length(name_resolved) > 3),
        y AS (
            SELECT year, name, CAST(regexp_extract(addr, '{ADDRESS_SQL}', 1) AS INTEGER) AS number,
                   regexp_replace(trim(regexp_extract(addr, '{ADDRESS_SQL}', 2)), '{TYPE}', '') AS street
            FROM x WHERE regexp_matches(addr, '{ADDRESS_SQL}'))
        SELECT year, name, any_value(number) AS number, street FROM y
        WHERE street <> '' AND number BETWEEN 1 AND 3000
        GROUP BY year, name, street HAVING count(*) = 1""")
    years = [y for y, in con.execute("SELECT DISTINCT year FROM a ORDER BY year").fetchall()]
    con.execute("CREATE OR REPLACE TABLE steps AS SELECT unnest(?) AS y0, unnest(?) AS y1",
                [years[:-1], years[1:]])
    con.execute("""
        CREATE OR REPLACE TABLE pairs AS
        SELECT s.y0, s.y1, a0.street, a0.name, a0.number AS n0, a1.number AS n1
        FROM steps s JOIN a a0 ON a0.year = s.y0 JOIN a a1 ON a1.year = s.y1
             AND a1.name = a0.name AND a1.street = a0.street""")


def in_order(pairs: list) -> float:
    """Of the changed pairs, the share of pairs of them whose old and new numbers are in the same
    order (1.0: a renumbering's mapping; ~0.5: unrelated changes)."""
    agree = total = 0
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            (a0, a1), (b0, b1) = pairs[i], pairs[j]
            if a0 != b0 and a1 != b1:
                total += 1
                agree += (a0 < b0) == (a1 < b1)
    return agree / total if total else float("nan")


def street_report(con, street: str):
    rows = con.execute("SELECT y0, y1, n0, n1 FROM pairs WHERE street = ? ORDER BY y0, n0",
                       [street.lower()]).fetchall()
    by = {}
    for y0, y1, n0, n1 in rows:
        by.setdefault((y0, y1), []).append((n0, n1))
    print(f"{street}: names on it in both of two consecutive directories")
    print(" years       both  kept  changed  in order  examples (old -> new)")
    for (y0, y1), ps in by.items():
        changed = [p for p in ps if p[0] != p[1]]
        eg = ", ".join(f"{a}->{b}" for a, b in sorted(changed)[:: max(1, len(changed) // 5)][:5])
        print(f" {y0}-{y1}  {len(ps):>5} {len(ps) - len(changed):>5} {len(changed):>8}"
              f"  {in_order(changed):>8.2f}  {eg}")


def scan(con, least: int = 20):
    rows = con.execute(f"""
        SELECT y0, y1, street, count(*) AS both, sum((n0 <> n1)::INT) AS changed
        FROM pairs GROUP BY y0, y1, street HAVING count(*) >= {least}
           AND sum((n0 <> n1)::INT) > count(*) / 2
        ORDER BY y0, street""").fetchall()
    print(" years       street                     both  changed  in order")
    for y0, y1, street, both, changed in rows:
        ps = con.execute("SELECT n0, n1 FROM pairs WHERE y0 = ? AND street = ? AND n0 <> n1",
                         [y0, street]).fetchall()
        print(f" {y0}-{y1}  {street[:24]:<24} {both:>6} {changed:>8}  {in_order(ps):>8.2f}")


if __name__ == "__main__":
    con = duckdb.connect()
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{sys.argv[1]}')")
    if sys.argv[2] == "--scan":
        stayers(con, sys.argv[3])
        scan(con)
    else:
        stayers(con, sys.argv[3])
        street_report(con, sys.argv[2])
