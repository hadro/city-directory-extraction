"""A street's eras, and an address carried from one to another (RENUMBERING_PLAN Phase 4).

    python3 addresses/chain.py --self-test
    uv run --with duckdb==2.0.0 python addresses/chain.py            # writes tables/eras.csv

A street id's events (events.csv) cut its years into eras: the numbering held from the last event's
first new year to the next one's last old year. `convert` carries a number from one era to any other
by composing the events' chains, fit.graded step by step: an interval of numbers goes in as its two
ends and comes out as the span they reach, the grade is the worst of the steps (A, B; C when a step
has no answer: past a chain's end, an event with no chain, a side no chain is for), and where a
step has several chains (runs of old numbers; the old keys of a street renamed into one) each
answers as a form of its own. Going back, a form that came out on another printed key than the
street's id (old "Fulton av" numbers) stops there: its earlier eras are another id's events.

The question the plan asks: is the last directory's numbering today's? Measured for Brooklyn per
street id, from the people listed in the last directories (LAST_YEARS: 1908-10; the 1912 directory
abbreviates its streets, "laf av", and they meet no name of today's). Two things are measured.
The 1855 atlas (atlas_1855.parquet: each 1855 house number paired with today's number at that
spot): each is carried across every later event of its street to the last era and compared with
today's number (+-TOL; check c of atlas.py, through all the street's events). `atlas_agree` is the
share of the `atlas_points` that could be carried and agree, and decides: today = yes (at least
AGREE of them, with MIN_POINTS or more), no, or unchecked (fewer points: the atlas covers 159
streets of downtown Brooklyn and Williamsburg). And `exist`, the share of the street's people
whose number is one of today's address points on it (atlas.load: data/city/uf93-f8nk.csv). It
decides nothing: a dense street has most numbers whatever its numbering (63% of these numbers
exist today, 52% of the same numbers moved two along), what it has over the numbers moved two
along is the same on the 40 streets the atlas says yes and the 19 it says no (median 0.04 and
0.05), and a street pulled down fails it with the atlas agreeing (Pearl 0.05, High 0).

Writes tables/eras.csv: place, street (id), era, from_year, to_year (blank: no event before it /
none after it), event (the one that ends the era), kind, weak, chains, and, on the last era of a
Brooklyn street, those measures and `today`.
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TABLE = HERE / "tables/eras.csv"
sys.path.insert(0, str(HERE))
import fit  # noqa: E402
import registry  # noqa: E402

LAST_YEARS = (1908, 1909, 1910)   # Brooklyn's last directories with spelled-out street names
MIN_ROWS = 50     # people in them for a street to be measured
AGREE = 0.6       # of the atlas points carried, within TOL of today's number
MIN_POINTS = 5    # atlas points carried for the atlas to count
TOL = 2
ATLAS_YEAR = 1855


def load(events_csv: Path, anchors) -> dict:
    """{(place, street): [event, ...]} in year order, an event {y0, y1, kind, weak, chains}, its
    chains [(old_street, [(old, new, weight), ...]), ...] (anchors on a chain only)."""
    import duckdb
    book = {}
    for r in csv.DictReader(open(events_csv)):
        book.setdefault((r["place"], r["street"]), []).append(
            {"y0": int(r["last_old_year"]), "y1": int(r["first_new_year"]), "kind": r["kind"],
             "weak": r["weak"], "chains": {}})
    for events in book.values():
        events.sort(key=lambda e: e["y0"])
    rows = duckdb.sql(f"SELECT place, street, y0, y1, chain, old_street, old, new, weight "
                      f"FROM '{anchors}' WHERE chain >= 0 ORDER BY ALL").fetchall()
    for place, street, y0, y1, chain, old_street, old, new, w in rows:
        event = next(e for e in book[(place, street)] if (e["y0"], e["y1"]) == (y0, y1))
        event["chains"].setdefault((chain, old_street), []).append((old, new, w))
    for events in book.values():
        for e in events:
            e["chains"] = [(k, c) for (_, k), c in sorted(e["chains"].items())]
    return book


def eras(events: list) -> list:
    """[(from_year, to_year, ending event or None), ...]: one more era than events."""
    return [(events[i - 1]["y1"] if i else None, events[i]["y0"] if i < len(events) else None,
             events[i] if i < len(events) else None) for i in range(len(events) + 1)]


def era_at(events: list, year: int) -> int:
    """The era a year is in; a year after an event's last old year is past it."""
    return sum(e["y0"] < year for e in events)


def up(event: dict, forms: list, street: str) -> list:
    """Forms (lo, hi, grade, key) of the era before `event` -> those of the era after it."""
    out = set()
    for lo, hi, grade, key in forms:
        mine = [c for k, c in event["chains"] if k == key] or [c for _, c in event["chains"]]
        for chain in mine:
            side = chain[0][0] % 2
            a, b = lo + (lo % 2 != side), hi - (hi % 2 != side)   # a chain is one old side
            got = [fit.graded(chain, n) for n in {a, b}] if a <= b else [(None, None, "C")]
            if all(g[2] != "C" for g in got):
                out.add((min(g[0] for g in got), max(g[1] for g in got),
                         max(grade, *(g[2] for g in got)), street))
    return sorted(out)


def down(event: dict, forms: list, street: str) -> list:
    """Forms of the era after `event` -> those of the era before it, on the old key of each chain."""
    out = set()
    for lo, hi, grade, key in forms:
        if key not in (None, street):        # another id's earlier eras
            continue
        for old_street, chain in event["chains"]:
            got = [fit.graded(chain, n, 1) for n in {lo, hi}]
            if all(g and g[2] != "C" for g in got):
                out.add((min(g[0] for g in got), max(g[1] for g in got),
                         max(grade, *(g[2] for g in got)), old_street))
    return sorted(out)


def convert(events: list, street: str, number: int, era: int, to: int, key=None) -> list:
    """The forms (lo, hi, grade, key) in era `to` of `number` as printed in era `era` (under
    `key`, if given); [(None, None, "C", None)] when a step has no answer."""
    forms = [(number, number, "A", key)]
    for i in (range(era, to) if to > era else range(era - 1, to - 1, -1)):
        forms = (up if to > era else down)(events[i], forms, street)
    return forms or [(None, None, "C", None)]


def today(con, book: dict) -> dict:
    """{street id: (people in the last directories, exist, atlas points carried, share agreeing)}
    for Brooklyn: see the docstring. Needs atlas.load's `new` (today's points) in `con`."""
    con.execute(f"""CREATE TABLE last AS SELECT street, number, count(*) AS n
        FROM '{REPO}/data/addresses/people.parquet' WHERE place = 'Brooklyn' AND year IN {LAST_YEARS}
        GROUP BY ALL""")
    have = {}
    for street, n, hit in con.execute("""
            SELECT l.street, sum(n), sum(n) FILTER (WHERE t.number IS NOT NULL) FROM last l LEFT JOIN
            (SELECT DISTINCT street, number FROM new) t USING (street, number) GROUP BY 1""").fetchall():
        i = registry.lookup("Brooklyn", street, 9999, registry.USED)
        have[i] = [a + b for a, b in zip(have.get(i, [0, 0]), (n, hit or 0))]
    carried = {}
    for s1855, street, n55, n_now in con.execute(f"""
            SELECT street, street_today, number_1855, number_today FROM '{REPO}/data/addresses/atlas_1855.parquet'
            QUALIFY row_number() OVER (PARTITION BY id ORDER BY distance_m, number_today) = 1""").fetchall():
        i = registry.lookup("Brooklyn", street, 9999, registry.USED)
        events = book.get(("Brooklyn", i), [])
        got = [f for f in convert(events, i, int(n55), era_at(events, ATLAS_YEAR), len(events), s1855)
               if f[2] != "C"]
        if got:
            c = carried.setdefault(i, [0, 0])
            c[0] += 1
            c[1] += any(lo - TOL <= n_now <= hi + TOL for lo, hi, _, _ in got)
    return {i: (n, hit / n, *(carried.get(i, [0, 0]))) for i, (n, hit) in have.items() if n >= MIN_ROWS}


def verdict(points: int, agree: int) -> str:
    return "unchecked" if points < MIN_POINTS else "yes" if agree >= AGREE * points else "no"


def main():
    import atlas
    import duckdb
    book = load(HERE / "tables/events.csv", REPO / "data/addresses/anchors.parquet")
    con = duckdb.connect(config={"memory_limit": "2GB", "threads": 2})
    atlas.load(con)
    measured = today(con, book)
    rows = []
    for place, street in sorted(set(book) | {("Brooklyn", i) for i in measured}):
        events = book.get((place, street), [])
        for k, (y0, y1, e) in enumerate(eras(events)):
            row = {"place": place, "street": street, "era": k, "from_year": y0 or "", "to_year": y1 or "",
                   "event": f"{e['y0']}-{str(e['y1'])[2:]}" if e else "", "kind": e["kind"] if e else "",
                   "weak": e["weak"] if e else "", "chains": len(e["chains"]) if e else "",
                   "last_rows": "", "exist": "", "atlas_points": "", "atlas_agree": "", "today": ""}
            if e is None and (street in measured) and place == "Brooklyn":
                n, exist, points, agree = measured[street]
                row.update(last_rows=n, exist=round(exist, 2), atlas_points=points,
                           atlas_agree=round(agree / points, 2) if points else "",
                           today=verdict(points, agree))
            rows.append(row)
    with open(TABLE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    per = [r for r in rows if r["today"]]
    total = sum(r["last_rows"] for r in per)
    print(f"{len(rows)} eras on {len({(r['place'], r['street']) for r in rows})} streets -> addresses/tables/eras.csv")
    for v in ("yes", "no", "unchecked"):
        got = [r for r in per if r["today"] == v]
        print(f" today = {v:<9}{len(got):>4} of {len(per)} Brooklyn streets ({len(got) / len(per):.0%}), "
              f"{sum(r['last_rows'] for r in got):>7} of {total} people in the last directories "
              f"({sum(r['last_rows'] for r in got) / total:.0%})")
    no = sorted((r for r in per if r["today"] == "no"), key=lambda r: -r["last_rows"])
    print(" not today's, by people: " + ", ".join(f"{r['street']} {r['atlas_agree']:.0%} of {r['atlas_points']}" for r in no))


def self_test():
    # a street with two events: 1850/51 (old odd numbers 11-61 become 111-161) and 1900/01
    # (reversed: new = 500 - old); a second key "bar" printed in the first era is a run of its own
    one = [(n, n + 100, 1) for n in range(11, 62, 4)]
    two = [(n, 500 - n, 1) for n in range(103, 204, 4)]
    bar = [(n, n + 300, 1) for n in range(11, 62, 4)]
    events = [{"y0": 1850, "y1": 1851, "kind": "renumbered", "weak": "0",
               "chains": [("bar", bar), ("foo", one)]},
              {"y0": 1900, "y1": 1901, "kind": "reversed", "weak": "0", "chains": [("foo", two)]}]
    assert eras(events) == [(None, 1850, events[0]), (1851, 1900, events[1]), (1901, None, None)]
    assert [era_at(events, y) for y in (1800, 1850, 1851, 1900, 1901, 1912)] == [0, 0, 1, 1, 2, 2]
    # forward, across both events: 23 -> 123 -> 377
    assert convert(events, "foo", 23, 0, 1, key="foo") == [(123, 123, "A", "foo")]
    assert convert(events, "foo", 23, 0, 2, key="foo") == [(377, 377, "A", "foo")]
    assert convert(events, "foo", 23, 0, 1) == [(123, 123, "A", "foo"), (323, 323, "A", "foo")]
    # between anchors a bracket (grade B beyond NEAR), whose two ends go on through the next event
    # and the worst grade stays
    events[0]["chains"] = [("foo", [(n, n + 100, 1) for n in range(11, 200, 20)])]
    assert convert(events, "foo", 25, 0, 1) == [(111, 131, "B", "foo")]
    assert convert(events, "foo", 25, 0, 2) == [(369, 389, "B", "foo")]
    events[0]["chains"] = [("bar", bar), ("foo", one)]
    # backward: 377 -> 123 -> 23, and the second key's run is where the old number comes out
    assert convert(events, "foo", 377, 2, 1) == [(123, 123, "A", "foo")]
    assert convert(events, "foo", 377, 2, 0) == [(23, 23, "A", "foo")]
    assert convert(events, "foo", 323, 1, 0) == [(23, 23, "A", "bar")]
    assert convert(events, "foo", 323, 2, 0) == [(None, None, "C", None)]   # 1851-1900's 175-179: no chain reaches it
    # past a chain's end, the wrong side, and a step with no chain: C, no numbers
    assert convert(events, "foo", 999, 0, 1) == [(None, None, "C", None)]
    assert convert(events, "foo", 24, 0, 1) == [(None, None, "C", None)]
    events[1]["chains"] = []
    assert convert(events, "foo", 23, 0, 2, key="foo") == [(None, None, "C", None)]
    print("chain self-test passes")


if __name__ == "__main__":
    self_test() if sys.argv[1:] == ["--self-test"] else main()
