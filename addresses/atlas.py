"""Brooklyn's 1855 Perris atlas against today's address points (RENUMBERING_PLAN 2D, evidence D).

    uv run --with duckdb==2.0.0 python addresses/atlas.py
    python3 addresses/atlas.py --self-test      (needs duckdb too)

The NYC Space/Time Directory's `addresses` dataset holds 6,068 house numbers read off the 1855
atlas (Map Warper layer 860), each with a street and a point. Today's address points are
data/city/uf93-f8nk.csv. Each 1855 point is paired with every point of today's on the same
street within REACH metres; a pair is a number in 1855 and the number now at that spot, an
anchor that skips every renumbering in between. "Same street" is the key streets.read gives,
which today's names ("COURT ST", "E  28 ST") are brought to by reading them as an address.
That fails for a street renamed since 1855, and for the atlas's own spellings ("caroll",
"willougby", "dekalb av"): those match nothing and are listed in
addresses/tables/atlas_unmatched_streets.csv, with whether today has any street of that key.

Writes data/addresses/atlas_1855.parquet: id, place, street, street_today, how (key, alias, type), number_1855, number_today,
distance_m, lon, lat (the 1855 point), lon_today, lat_today, n_near (today's points in reach of
this 1855 point), nearest (this is the closest of them). Prints the summary and three checks:

  a. the pairing is sane: per street, how much of 1855 against today's number rises together
     (the longest run, rising or falling, as a share of the pairs) and how often the parity
     relation (same parity, or opposite) is the usual one;
  b. was 1855's numbering the directories' up to 1871: the events between 1854 and 1871 on these
     streets, and, by directory year, how many of the people on an atlas street have an atlas point
     with exactly their number, against the same with 30 added (chance);
  c. the mapping against the atlas: for streets with a Brooklyn 1871-75 event and no later one,
     carry the 1855 number across the street's chains (anchors.parquet) and compare with today's
     number. Nothing is tuned: the 1855 number is taken to be the 1871 numbering, and that
     may be wrong (an event between, a street renumbered again), which is part of the answer.
"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import fit  # noqa: E402
import streets  # noqa: E402

ATLAS = REPO / "data/spacetime/x_addresses/addresses.csv"
CITY = REPO / "data/city/uf93-f8nk.csv"
OUT = REPO / "data/addresses/atlas_1855.parquet"
UNMATCHED = HERE / "tables/atlas_unmatched_streets.csv"
EVENTS, ANCHORS = HERE / "tables/events.csv", REPO / "data/addresses/anchors.parquet"
REACH = 15.0          # metres
BROOKLYN = "3"        # the city file's borough code
TYPES = {"av", "pl", "st", "la", "ct", "co", "al", "aly", "ro", "rd", "dr", "blvd", "pkwy", "hwy",
         "sq", "ter", "walk", "wk", "row", "ln"}
ALIASES = {"willougby": "willoughby", "caroll": "carroll", "tillery": "tillary", "wykoff": "wyckoff",
           "rapelyea": "rapelye", "thompkins pl": "tompkins pl", "clarke": "clark",
           "vanbrunt": "van brunt"}   # the atlas's own spellings; each checked against today's names


def key_1855(name: str, number: float) -> str | None:
    """The street key of "94.5 Garden Street" (streets.read refuses the fraction)."""
    r = streets.read(f"{int(number)} {name.split(' ', 1)[1]}")
    return r["street"] if r else None


def key_today(full: str) -> str | None:
    """The street key of the city file's "Full Street Name" ("E  28 ST", "5 AVE")."""
    r = streets.read("1 " + full.lower())
    return r["street"] if r else None


def base(key: str) -> str:
    """The key without its type: "atlantic av" -> "atlantic" (a street's type changed: Atlantic st)."""
    words = key.split()
    return " ".join(words[:-1]) if len(words) > 1 and words[-1] in TYPES else key


def alternatives(old_keys, new_keys) -> list:
    """[(1855 key, today's key, how, rank)]: the same key (0), the atlas's spelling mended (1), the
    same name with another type (2). A later rank is used for a street only if no earlier one pairs."""
    out = []
    for k in old_keys:
        a = ALIASES.get(k, k)
        out += [(k, k, "key", 0)] * (k in new_keys) + [(k, a, "alias", 1)] * (a != k and a in new_keys)
        out += [(k, n, "type", 2) for n in new_keys if n not in (k, a) and base(n) == base(a)]
    return out


def pair(con, reach: float = REACH) -> None:
    """Table `pairs` from tables old(id, street, number, lon, lat) and new(street, number, lon, lat):
    every old point with each new one on its street (alternatives) within `reach` metres
    (flat-earth metres, fine at 15)."""
    alts = alternatives({r[0] for r in con.execute("SELECT DISTINCT street FROM old").fetchall()},
                        {r[0] for r in con.execute("SELECT DISTINCT street FROM new").fetchall()})
    con.execute("CREATE OR REPLACE TABLE alt(street VARCHAR, street_today VARCHAR, how VARCHAR, rank INT)")
    con.executemany("INSERT INTO alt VALUES (?, ?, ?, ?)", alts)
    con.execute(f"""CREATE OR REPLACE TABLE pairs AS
        SELECT * EXCLUDE (rank) FROM (
          SELECT o.id, o.street, a.street_today, a.how, a.rank, o.number AS number_1855,
                 n.number AS number_today,
                 sqrt(power((o.lon - n.lon) * cos(radians(o.lat)) * 111320, 2)
                      + power((o.lat - n.lat) * 110574, 2)) AS distance_m,
                 o.lon, o.lat, n.lon AS lon_today, n.lat AS lat_today
          FROM old o JOIN alt a ON o.street = a.street
                     JOIN new n ON a.street_today = n.street AND abs(o.lat - n.lat) < 0.0003)
        WHERE distance_m <= {reach}
        QUALIFY rank = min(rank) OVER (PARTITION BY street)""")


def load(con) -> None:
    rows = con.execute(f"""SELECT id, name, "$.data.number", json_extract(geometry, '$.coordinates[0]')::DOUBLE,
        json_extract(geometry, '$.coordinates[1]')::DOUBLE FROM read_csv('{ATLAS}')
        WHERE "$.data.layerId" = 860""").fetchall()
    con.execute("CREATE OR REPLACE TABLE old(id VARCHAR, street VARCHAR, number DOUBLE, lon DOUBLE, lat DOUBLE, name VARCHAR)")
    con.executemany("INSERT INTO old VALUES (?, ?, ?, ?, ?, ?)",
                    [(i, key_1855(n, num), num, lo, la, n) for i, n, num, lo, la in rows])
    names = [r[0] for r in con.execute(f"""SELECT DISTINCT "Full Street Name" FROM
        read_csv('{CITY}', all_varchar=true) WHERE "Borough Code" = '{BROOKLYN}'""").fetchall()]
    con.execute("CREATE OR REPLACE TABLE names(fullname VARCHAR, street VARCHAR)")
    con.executemany("INSERT INTO names VALUES (?, ?)", [(n, key_today(n)) for n in names if n])
    # a house number with a suffix or hyphen is another thing (a rear house, Queens style): left out
    con.execute(f"""CREATE OR REPLACE TABLE new AS
        SELECT names.street, try_cast(c."House Number" AS INT) AS number,
               regexp_extract(c.the_geom, 'POINT \\(([-0-9.]+) ([-0-9.]+)\\)', 1)::DOUBLE AS lon,
               regexp_extract(c.the_geom, 'POINT \\(([-0-9.]+) ([-0-9.]+)\\)', 2)::DOUBLE AS lat
        FROM read_csv('{CITY}', all_varchar=true) c JOIN names ON c."Full Street Name" = names.fullname
        WHERE c."Borough Code" = '{BROOKLYN}' AND c."House Number Suffix" IS NULL
          AND try_cast(c."House Number" AS INT) IS NOT NULL AND names.street IS NOT NULL""")


def write(con) -> None:
    con.execute(f"""COPY (SELECT id, 'Brooklyn' AS place, street, street_today, how, number_1855, number_today,
        round(distance_m, 1) AS distance_m, lon, lat, lon_today, lat_today,
        count(*) OVER (PARTITION BY id) AS n_near,
        distance_m = min(distance_m) OVER (PARTITION BY id) AS nearest
        FROM pairs ORDER BY street, number_1855, distance_m) TO '{OUT}' (FORMAT parquet)""")


def summary(con) -> None:
    per = con.execute("""SELECT o.street, count(DISTINCT o.id), count(DISTINCT p.id), any_value(p.how),
        string_agg(DISTINCT p.street_today, ' / '), any_value(o.street IN (SELECT street FROM new)),
        regexp_replace(any_value(o.name), '^[0-9.]+ ', '') FROM old o LEFT JOIN pairs p USING (id)
        GROUP BY o.street ORDER BY 2 DESC""").fetchall()
    matched = con.execute("SELECT count(DISTINCT id) FROM pairs").fetchone()[0]
    total = sum(r[1] for r in per)
    print(f"{total} points of 1855 on {len(per)} street keys; {matched} ({matched / total:.0%}) have a "
          f"point of today's within {REACH:g} m on the same street (or its mended spelling or other "
          f"type); {con.execute('SELECT count(*) FROM pairs').fetchone()[0]} pairings")
    print(f"{'street':<22}{'points':>7}{'matched':>8}  via")
    for street, n, got, how, today, _, _ in per:
        print(f"{str(street):<22}{n:>7}{got:>8}  {how or ''} {today if how and how != 'key' else ''}")
    odd = [r for r in per if r[3] != "key"]      # not paired on the same key
    with open(UNMATCHED, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["street_1855", "printed_as", "points", "exact_key_in_today_brooklyn", "matched_via",
                    "today_key", "matched_points"])
        for s, n, got, how, today, has, printed in sorted(odd, key=lambda r: str(r[0])):
            w.writerow([s, printed, n, bool(has), how or "none", today or "", got])
    nothing = [r for r in odd if not r[2]]
    print(f"{len(odd)} street keys do not pair on the same key ({sum(r[1] for r in odd)} points); "
          f"{len(nothing)} match nothing at all ({sum(r[1] for r in nothing)} points): {UNMATCHED.name}")


def longest_run(seq: list) -> int:
    """Length of the longest run of seq that only rises (non-decreasing) or only falls."""
    best = 0
    for sign in (1, -1):
        run = []
        for i, x in enumerate(seq):
            run.append(1 + max((run[j] for j in range(i) if sign * seq[j] <= sign * x), default=0))
        best = max([best, *run])
    return best


def nearest(con) -> dict:
    """{street: [(number_1855, number_today), ...]} sorted, the nearest pairing of each point
    (the lower number today when two are equally near)."""
    out = defaultdict(list)
    for s, a, b in con.execute("""SELECT street, number_1855, number_today FROM pairs QUALIFY
            row_number() OVER (PARTITION BY id ORDER BY distance_m, number_today) = 1""").fetchall():
        out[s].append((a, b))
    return {s: sorted(v) for s, v in out.items()}


def check_a(near: dict) -> None:
    print("\ncheck a: 1855 number against today's, nearest pairing, streets with 10+ points")
    print(f"{'street':<20}{'pairs':>6}{'run share':>10}{'parity':>9}{'usual':>8}{'same':>6}")
    allrun = allpar = n_all = 0
    for s, v in sorted(near.items(), key=lambda kv: -len(kv[1])):
        n, run = len(v), longest_run([b for _, b in v])
        same = sum((a - b) % 2 == 0 for a, b in v)
        par = max(same, n - same)
        n_all, allrun, allpar = n_all + n, allrun + run, allpar + par
        if n >= 10:
            print(f"{s:<20}{n:>6}{run / n:>10.0%}{par / n:>9.0%}{'same' if same * 2 >= n else 'opposite':>8}"
                  f"{sum(abs(a - b) <= 2 for a, b in v) / n:>6.0%}")
    print(f"all streets: {n_all} pairs, {allrun / n_all:.0%} on a rising or falling run, "
          f"{allpar / n_all:.0%} with the street's usual parity relation")


def check_b(con) -> None:
    keys = {r[0] for r in con.execute("SELECT street FROM old UNION SELECT street_today FROM pairs").fetchall()}
    between = [r for r in csv.DictReader(open(EVENTS)) if r["place"] == "Brooklyn" and r["street"] in keys
               and int(r["last_old_year"]) >= 1854 and int(r["first_new_year"]) <= 1871]
    print("\ncheck b: events between 1854 and 1871 on streets the atlas covers (last old year-first new year)")
    print("  " + "; ".join(f"{r['street']} {r['last_old_year']}-{r['first_new_year']}" for r in between))
    con.execute("""CREATE OR REPLACE TABLE atl AS SELECT DISTINCT street, number AS n FROM (
        SELECT street, number FROM old UNION ALL SELECT p.street_today, o.number FROM old o
        JOIN (SELECT DISTINCT street, street_today FROM pairs) p USING (street)) WHERE number = floor(number)""")
    con.execute(f"""CREATE OR REPLACE TABLE ppl AS SELECT DISTINCT p.street, year, number
        FROM '{REPO}/data/addresses/people.parquet' p JOIN (SELECT street, max(n) mx FROM atl GROUP BY 1) m
        USING (street) WHERE place = 'Brooklyn' AND year BETWEEN 1854 AND 1876 AND number BETWEEN 1 AND mx - 30""")
    print("people at a number on an atlas street (numbers up to the atlas's highest less 30): the share with an "
          "atlas point of exactly that number, and of the same number +30 (chance)")
    print(f"{'year':<6}{'people':>8}{'exact':>8}{'+30':>8}")
    for y, n, a, b in con.execute("""SELECT year, count(*), avg(exists(SELECT 1 FROM atl WHERE atl.street = ppl.street AND atl.n = number)::INT),
            avg(exists(SELECT 1 FROM atl WHERE atl.street = ppl.street AND atl.n = number + 30)::INT)
            FROM ppl GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"{y:<6}{n:>8}{a:>8.0%}{b:>8.0%}")


def events_by_street() -> tuple:
    """(streets with a Brooklyn 1871-75 event and no later one, those with one between 1854 and 1871)."""
    ev = [r for r in csv.DictReader(open(EVENTS)) if r["place"] == "Brooklyn"]
    sets = lambda f: {r["street"] for r in ev if f(int(r["last_old_year"]), int(r["first_new_year"]))}
    event = sets(lambda a, b: (a, b) == (1871, 1875))
    return event - sets(lambda a, b: a >= 1875), sets(lambda a, b: a >= 1854 and b <= 1871)


def carry(chains: dict, number: float) -> list:
    """The (low, high) new numbers an 1855 number falls between in each chain of its parity."""
    n = int(number)
    return [r for sign_chain in chains.values() if sign_chain[0][0] % 2 == n % 2
            for r in [fit.across(sign_chain, n)] if r]


def check_c(con, near: dict) -> None:
    once, between = events_by_street()
    rows = con.execute(f"SELECT street, chain, old, new, weight FROM '{ANCHORS}' WHERE place = 'Brooklyn' "
                       f"AND y0 = 1871 AND y1 = 1875 AND chain >= 0").fetchall()
    by = defaultdict(lambda: defaultdict(list))
    for s, c, o, nw, w in rows:
        by[s][c].append((o, nw, w))
    print("\ncheck c: the 1855 number carried across the 1871-75 chains against today's number")
    print(f"streets with a 1871-75 event and none later: {len(once)}; of those with an event between "
          f"1855 and 1871 as well: {len(once & between)}")
    today = dict(con.execute("SELECT DISTINCT street, street_today FROM pairs").fetchall())
    totals = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    per = []
    for s in sorted(near):
        e = s if s in once else today.get(s)      # the directories' key: the atlas's, else today's
        if e not in once:
            continue
        t = [0, 0, 0, 0, 0, 0]
        for a, b in near[s]:
            got = carry(by.get(e, {}), a)
            t[0] += 1
            t[1] += bool(got)
            t[2] += any(lo - 2 <= b <= hi + 2 for lo, hi in got)
            t[3] += any(lo - 10 <= b <= hi + 10 for lo, hi in got)
            t[4] += abs(a - b) <= 2      # the 1855 number is today's: no renumbering at all
            t[5] += abs(a - b) <= 10
        per.append((e, t, e in between))
        for name in ("all", "event between" if e in between else "no event between"):
            totals[name] = [a + b for a, b in zip(totals[name], t)]
    for name, t in totals.items():
        n, got = t[0], max(1, t[1])
        print(f"{name:<19}: {n} points; carried {t[1]} ({t[1] / n:.0%}); of those within 2 {t[2] / got:.0%}, "
              f"within 10 {t[3] / got:.0%}; (1855 number = today's within 2: {t[4] / n:.0%}, within 10: {t[5] / n:.0%})")
    print(f"{'street':<20}{'pts':>5}{'carried':>8}{'in 2':>6}{'in 10':>6}{'1855=now':>9}  between")
    for s, t, b in sorted(per, key=lambda r: -r[1][0]):
        if t[0] >= 8:
            g = max(1, t[1])
            print(f"{s:<20}{t[0]:>5}{t[1]:>8}{t[2] / g:>6.0%}{t[3] / g:>6.0%}{t[4] / t[0]:>9.0%}  {'yes' if b else ''}")


def main() -> None:
    import duckdb
    con = duckdb.connect()
    load(con)
    pair(con)
    write(con)
    summary(con)
    near = nearest(con)
    check_a(near)
    check_b(con)
    check_c(con, near)


def self_test() -> None:
    import duckdb
    assert key_today("COURT ST") == "court" and key_today("E  28 ST") == "e 28"
    assert key_today("5 AVE") == "5 av" and key_today("FLATBUSH AVE") == "flatbush av"
    assert key_today("DE KALB AVE") == "de kalb av" and key_today("STERLING PL") == "sterling pl"
    assert key_1855("94.5 Garden Street", 94.5) == "garden" and key_1855("98 Boerum Street", 98) == "boerum"
    assert key_1855("10 Atlantic Avenue", 10) == "atlantic av" and key_1855("5 Dekalb Avenue", 5) == "dekalb av"
    assert base("atlantic av") == "atlantic" and base("van brunt") == "van brunt" and base("court") == "court"
    assert set(alternatives({"atlantic", "caroll", "court"}, {"atlantic av", "carroll", "court"})) == {
        ("atlantic", "atlantic av", "type", 2), ("caroll", "carroll", "alias", 1), ("court", "court", "key", 0)}
    assert longest_run([1, 3, 2, 4, 9, 5]) == 4 and longest_run([9, 7, 8, 3]) == 3
    con = duckdb.connect()
    con.execute("CREATE TABLE old(id VARCHAR, street VARCHAR, number DOUBLE, lon DOUBLE, lat DOUBLE)")
    con.execute("CREATE TABLE new(street VARCHAR, number INT, lon DOUBLE, lat DOUBLE)")
    # 0.0001 deg of latitude is 11.06 m; 0.00015 is 16.6 m
    con.execute("INSERT INTO old VALUES ('a', 'court', 10, -73.99, 40.68), ('b', 'court', 12, -73.99, 40.69), "
                "('c', 'dean', 5, -73.98, 40.67)")
    con.execute("INSERT INTO new VALUES ('court', 100, -73.99, 40.6801), ('court', 102, -73.99, 40.68015), "
                "('court', 104, -73.99, 40.6799), ('dean', 7, -73.98, 40.67), ('court', 9, -73.99, 40.70)")
    pair(con)
    got = con.execute("SELECT id, number_today, round(distance_m, 1) FROM pairs ORDER BY 1, 2").fetchall()
    assert got == [("a", 100, 11.1), ("a", 104, 11.1), ("c", 7, 0.0)], got   # 102 is 16.6 m away; b has none on its street
    print("atlas self-test passes")


if __name__ == "__main__":
    self_test() if sys.argv[1:] == ["--self-test"] else main()
