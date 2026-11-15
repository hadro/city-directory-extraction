"""RENUMBERING_PLAN Phase 0, the two tasks that are queries: the printed pairs (0.3) and the street
spellings (0.4).

    uv run --with duckdb==2.0.0 python results/renumbering_phase0.py data/space/records.parquet

0.3 -> results/printed_pairs.json: lines whose printed text states a second number ("old No.",
"new No.", "new number", "now 56 Bedford av", "formerly 12", "late 12"), counted by form and
volume, with the street of the line's address and five sample lines per form and volume.
0.4 -> data/addresses/street_strings.parquet: every distinct street string in an address that
reads as number + street (renumbering.ADDRESS, the type kept), by place and decade, with its
line count.
"""
import json
import sys

import duckdb

from renumbering import ADDRESS_SQL, CITY

# form -> regex over the lowercased raw line
FORMS = {
    "old no": r"\bold\s+nos?\b\.?",
    "new no": r"\bnew\s+nos?\b\.?",
    "new number": r"\bnew\s+number",
    "old number": r"\bold\s+number",
    "now + number": r"\bnow\s+[0-9]+\s+[a-z]",
    "formerly + number": r"\bformerly\s+[0-9]+",
    "late + number": r"\blate\s+[0-9]+\s+[a-z]",
}
ADDR = "lower(trim(coalesce(nullif(home_address_resolved, ''), address_resolved)))"


def printed_pairs(con) -> dict:
    out = {}
    for form, rx in FORMS.items():
        con.execute(f"""CREATE OR REPLACE TEMP TABLE hit AS
            SELECT volume, year, city, record_id, raw_line,
                   trim(regexp_extract({ADDR}, '{ADDRESS_SQL}', 2)) AS street
            FROM r WHERE regexp_matches(lower(raw_line), '{rx}')""")
        by_volume = con.execute("""SELECT volume, any_value(year), any_value(city), count(*)
                                   FROM hit GROUP BY volume ORDER BY 4 DESC""").fetchall()
        out[form] = {
            "regex": rx, "lines": sum(v[3] for v in by_volume),
            "volumes": [
                {"volume": v, "year": y, "city": c, "lines": n,
                 "streets": dict(con.execute(
                     """SELECT street, count(*) FROM hit WHERE volume = ? AND street <> ''
                        GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", [v]).fetchall()),
                 "samples": [list(s) for s in con.execute(
                     "SELECT record_id, raw_line FROM hit WHERE volume = ? ORDER BY hash(record_id) LIMIT 5",
                     [v]).fetchall()]}
                for v, y, c, n in by_volume],
        }
    return out


def street_strings(con, path: str) -> int:
    places = " ".join(f"WHEN {sql} THEN '{place}'" for place, sql in CITY.items())
    con.execute(f"""COPY (
        SELECT CASE {places} ELSE city END AS place, (year // 10) * 10 AS decade,
               trim(regexp_extract({ADDR}, '{ADDRESS_SQL}', 2)) AS street, count(*) AS lines,
               min(year) AS first_year, max(year) AS last_year
        FROM r WHERE regexp_matches({ADDR}, '{ADDRESS_SQL}')
        GROUP BY ALL ORDER BY place, decade, lines DESC) TO '{path}' (FORMAT parquet)""")
    return con.execute(f"SELECT count(*) FROM '{path}'").fetchone()[0]


if __name__ == "__main__":
    con = duckdb.connect()
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{sys.argv[1]}')")
    pairs = printed_pairs(con)
    json.dump(pairs, open("results/printed_pairs.json", "w"), indent=1)
    for form, d in pairs.items():
        print(f"{form:<18} {d['lines']:>6} lines in {len(d['volumes'])} volumes; most: "
              + ", ".join(f"{v['volume']} {v['lines']}" for v in d["volumes"][:4]))
    print(street_strings(con, "data/addresses/street_strings.parquet"), "street-string rows")
