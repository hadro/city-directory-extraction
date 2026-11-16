"""The street registry: one id for one street (RENUMBERING_PLAN 1.2).

    python3 addresses/registry.py --self-test
    uv run --with duckdb==2.0.0 python addresses/registry.py      # rebuilds tables/streets.csv

`canon(place, key, year)` -> the street's id, a street key (the preferred one, so an unknown key
is its own id). streets.read keys a street as printed, so one street under two spellings, or two
names, is two streets, and everyone who lived on it across the change is lost. The ids merge
keys, from the most to the least trusted evidence (each row of tables/streets.csv says which):

  override   tables/street_overrides.csv, a human decision with its `why`, read by this script:
             what the data cannot decide (the East and West halves of Baltic and Warren became
             one street; spellings the evidence below wrongly merges would go here too).
  renaming   a name the directories print as changed: tables/renamings.csv (1871BPL leaves
             934-935, "changes made in the street directory", read off the page images) and the
             "(late X)" in the guides' headings (`late` on data/addresses/guides rows). Kept only
             when the old key is RETIRED: the directories use it five times less from four years
             after the change than before it. Otherwise the key is still another street (Smith
             is Smith st AND, east of Flushing av, Humboldt; Hudson av, Henry, Union av ...) and
             no merge by key can say which.
  spelling   a rarer key of the same place and type within two letters of a commoner one (5x
             the records, no digits) whose people (name and house number) turn up on the
             commoner key in another directory: SHARE of its records, and 3 at least. Never when
             one guide lists both. The same test merges "k (e.d.)" into "k" (that mark is printed
             only in 1875-89).

A renaming where the new key was already a street of its own beside the old one (Fulton av into
Fulton: two number runs until 1871, and the guides list both) is a merge, not a rename: the old
key is its own street until `since`, the first directory that retires it, and the new street from
then on. The overrides' halves of Baltic and Warren are merges too. To follow people across one
ask for the OLD key's id in the NEW year: canon(place, key0, year1) == canon(place, key1, year1).

Writes tables/streets.csv: street_id, place, key, first_seen and last_seen (years in the records),
since, name (as the guides print it), why (itself, spelling, renaming, override). Keys seen fewer
than MIN_LISTED times and in no merge are not listed: canon gives them back as they are. Then
prints what using the registry would change (the measures asked for in the plan's step 1.2).
"""
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import streets  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TABLES = Path(__file__).resolve().parent / "tables"
PEOPLE = REPO / "data/addresses/people.parquet"
MIN_LISTED = 20     # records; a key seen less, and in no merge, is not a row
SHARE = 0.25        # of a rare spelling's records found on the commoner key in another year
RETIRED = 0.2       # an old name's records per directory after the change, of before it
KIND = r" (av|pl|rd|ct|sq|te|al|la|dr|bl|ro|co)$"   # streets.read's type tokens, "st" left off
FIELDS = ["street_id", "place", "key", "first_seen", "last_seen", "since", "name", "why"]
_table = {}


def key(name: str):
    """A printed name ("Union pl.") as the records' key ("union pl")."""
    r = streets.read("1 " + name)
    return r and r["street"]


def lookup(place: str, k: str, year: int, kinds=None) -> str:
    """canon, but only through the merges whose `why` is in `kinds` (all when None)."""
    if not _table:
        for r in csv.DictReader(open(TABLES / "streets.csv")):
            _table.setdefault((r["place"], r["key"]), []).append((int(r["since"] or 0), r["street_id"], r["why"]))
    ok = [(s, i) for s, i, w in _table.get((place, k), []) if s <= year and (kinds is None or w in kinds or w == "itself")]
    return max(ok)[1] if ok else k


def canon(place: str, k: str, year: int) -> str:
    """The id of street key `k` in `year`; `k` itself when the registry does not know it."""
    return lookup(place, k, year)


def guide_rows() -> list:
    return [json.loads(l) for f in sorted((REPO / "data/addresses/guides").glob("*.jsonl")) for l in open(f)]


def late_pairs(guides: list) -> dict:
    """(new key, old key) -> the first guide year that prints "(late old)" on the new name."""
    out = {}
    for r in guides:
        if r.get("late") and (old := key(r["late"])) and old != r["street"]:
            pair, year = (r["street"], old), int(r["volume"][:4])
            out[pair] = min(year, out.get(pair, year))
    return out


def level(con, place, k, lo, hi) -> float:
    """Records a directory on key `k` over the directories of years lo..hi."""
    n = con.execute("SELECT coalesce(sum(n), 0) FROM c WHERE place = ? AND street = ? AND year BETWEEN ? AND ?",
                    [place, k, lo, hi]).fetchone()[0]
    d = con.execute("SELECT count(DISTINCT year) FROM c WHERE place = ? AND year BETWEEN ? AND ?",
                    [place, lo, hi]).fetchone()[0]
    return n / d if d else 0


def renaming(con, place, old, new, y) -> dict:
    """What the records say of a renaming at year y: the old key's records a directory before
    and from y+4 on, whether that retires it, the new key's before, and the first directory
    year >= y that has the old key retired (`since`)."""
    before, after = level(con, place, old, y - 10, y - 1), level(con, place, old, y + 4, y + 15)
    low = max(RETIRED * before, 1)
    n = dict(con.execute("SELECT year, n FROM c WHERE place = ? AND street = ?", [place, old]).fetchall())
    years = [yr for yr, in con.execute("SELECT DISTINCT year FROM c WHERE place = ? AND year >= ? ORDER BY year", [place, y]).fetchall()]
    since = next((yr for yr in years if n.get(yr, 0) <= low), None)
    return {"before": before, "after": after, "retired": after <= low, "since": since,
            "new_before": level(con, place, new, y - 10, y - 1), "new_after": level(con, place, new, y + 4, y + 15)}


def spellings(con, guides: list) -> list:
    """(place, rare, common) for every spelling the evidence accepts."""
    con.execute("CREATE TABLE g (vol VARCHAR, key VARCHAR)")
    con.executemany("INSERT INTO g VALUES (?, ?)", sorted({(r["volume"], r["street"]) for r in guides if r["street"]}))
    return con.execute(f"""
        WITH cand AS (
            SELECT r.place, r.key AS r, c.key AS c, r.n AS rn FROM k r JOIN k c
              ON r.place = c.place AND r.key <> c.key AND r.n >= 12 AND c.n >= 5 * r.n
             AND left(r.key, 1) = left(c.key, 1) AND abs(length(r.key) - length(c.key)) <= 2
             AND NOT regexp_matches(r.key || c.key, '[0-9]')
             AND coalesce(regexp_extract(r.key, '{KIND}', 1), '') = coalesce(regexp_extract(c.key, '{KIND}', 1), '')
             AND damerau_levenshtein(r.key, c.key) <= 2
            UNION
            SELECT r.place, r.key, c.key, r.n FROM k r JOIN k c
              ON r.place = c.place AND r.key = c.key || ' (e.d.)' AND r.n >= 12),
        ev AS (
            SELECT x.place, x.r, x.c, x.rn, count(DISTINCT (a.name, a.number)) AS shared
            FROM cand x JOIN p a ON a.place = x.place AND a.street = x.r
                        JOIN p b ON b.place = x.place AND b.street = x.c AND b.name = a.name
                                AND b.number = a.number AND b.year <> a.year
            GROUP BY ALL)
        SELECT place, r, c FROM ev
        WHERE shared >= 3 AND shared >= {SHARE} * rn
          AND NOT EXISTS (SELECT 1 FROM g a JOIN g b USING (vol) WHERE a.key = ev.r AND b.key = ev.c)
        QUALIFY row_number() OVER (PARTITION BY place, r ORDER BY shared DESC, rn) = 1""").fetchall()


def build(con) -> tuple:
    """(the rows of streets.csv, every renaming with what the records say of it)."""
    guides = guide_rows()
    seen = {(p, s): n for p, s, n in con.execute("SELECT place, key, n FROM k").fetchall()}
    ren = {(r["place"], key(r["new"]), key(r["old"])): int(r["year"])
           for r in csv.DictReader(open(TABLES / "renamings.csv"))}
    assert all(None not in k for k in ren)
    for (new, old), y in late_pairs(guides).items():      # OCR-garbled names are not keys the records hold
        if seen.get(("Brooklyn", new), 0) >= MIN_LISTED and seen.get(("Brooklyn", old), 0) >= MIN_LISTED:
            ren.setdefault(("Brooklyn", new, old), y)
    news = {}
    for place, new, old in ren:
        news.setdefault((place, old), set()).add(new)
    edges, why, merges, found = {}, {}, [], []
    for (place, new, old), y in sorted(ren.items(), key=lambda x: x[1]):
        r = dict(renaming(con, place, old, new, y), place=place, old=old, new=new, year=y, use="")
        if len(news[(place, old)]) > 1:
            r["use"] = "not merged: two new names"
        elif not r["retired"]:
            r["use"] = "not merged: old key still used"
        elif old != new and r["new_before"] > RETIRED * r["before"] and r["before"] >= 1:
            r["use"] = f"merged from {r['since']}"            # the new key was a street beside the old one
            merges.append((place, old, new, r["since"], "renaming"))
        elif old != new:
            r["use"] = "merged"
            edges[(place, old)], why[(place, old)] = new, "renaming"
        found.append(r)
    for place, rare, common in spellings(con, guides):
        if (place, rare) not in edges:
            edges[(place, rare)], why[(place, rare)] = common, "spelling"
    for o in csv.DictReader(open(TABLES / "street_overrides.csv")):
        if o["since"]:
            merges.append((o["place"], o["key"], o["street_id"], int(o["since"]), "override"))
        else:
            edges.pop((o["place"], o["key"]), None)
            if o["street_id"] != o["key"]:
                edges[(o["place"], o["key"])], why[(o["place"], o["key"])] = o["street_id"], "override"

    def root(place, k):
        for _ in range(10):
            if (place, k) not in edges:
                return k
            k = edges[(place, k)]
        raise ValueError(f"renaming loop at {place} {k}")
    printed = {r["street"]: r["street_printed"] for r in guides if r["street"]}
    span = {(p, s): (y0, y1) for p, s, y0, y1 in con.execute("SELECT place, key, y0, y1 FROM k").fetchall()}
    listed = {pk for pk, n in seen.items() if n >= MIN_LISTED} | set(edges) | {(p, root(p, k)) for p, k in edges} \
        | {(p, old) for p, old, _, _, _ in merges} | {(p, root(p, new)) for p, _, new, _, _ in merges}

    def row(p, k, street_id, since, how):
        return dict(street_id=street_id, place=p, key=k, first_seen=span.get((p, k), ("", ""))[0],
                    last_seen=span.get((p, k), ("", ""))[1], since=since,
                    name=nm if re.sub("[^a-z]", "", (nm := printed.get(street_id, "")).lower()) == re.sub("[^a-z]", "", street_id) else street_id,
                    why=how)
    rows = [row(p, k, root(p, k), "", why.get((p, k), "itself")) for p, k in listed]
    rows += [row(p, old, root(p, new), since, how) for p, old, new, since, how in merges]
    return sorted(rows, key=lambda r: (r["place"], r["street_id"], r["key"], r["since"] or 0)), found


def measure(con, found):
    """What using the registry would change: the renamings against the records, Brooklyn 1871-75's
    stayers, the events that are one street under two keys."""
    _table.clear()
    print("\n(a) renamings (1871 table, then the guides' '(late X)'): the old key's records a directory before and "
          "from four years after, the new key's after; followed = names once on the old key in one directory and "
          "once on the new key in the next (directories within four years of it), same = at the same number")
    con.execute("CREATE TABLE steps AS SELECT place, year AS y0, lead(year) OVER (PARTITION BY place ORDER BY year) AS y1 "
                "FROM (SELECT DISTINCT place, year FROM c) QUALIFY y1 IS NOT NULL")
    total = [0, 0]
    for r in sorted(found, key=lambda r: (r["year"], r["old"], r["new"])):
        n, same = con.execute("""SELECT count(*), coalesce(sum((a.number = b.number)::INT), 0) FROM steps s
            JOIN p a ON a.place = s.place AND a.year = s.y0 AND a.street = ?
            JOIN p b ON b.place = s.place AND b.year = s.y1 AND b.name = a.name AND b.street = ?
            WHERE s.place = ? AND s.y0 >= ? AND s.y1 <= ?""", [r["old"], r["new"], r["place"], r["year"] - 4, r["year"] + 4]).fetchone()
        r["followed"], r["same"] = n, same
        total[0] += n
        total[1] += same
        flag = "NEW NAME NOT USED" if r["new_after"] < RETIRED * r["before"] and r["before"] >= 1 else ""
        print(f"  {r['year']} {r['old']:<14} -> {r['new']:<16} old {r['before']:>4.0f} -> {r['after']:>4.0f}  new {r['new_after']:>4.0f}  "
              f"followed {n:>3}, same {same:>3}   {r['use']} {flag}")
    print(f"  {total[0]} followed in all, {total[1]} at the same number")

    print("\n(b) Brooklyn 1871 -> 1875: stayers (a name once on one street in each year, the same street), and the events")
    a, b = 1871, 1875
    keys = [s for s, in con.execute("SELECT DISTINCT street FROM p WHERE place = 'Brooklyn' AND year IN (?, ?)", [a, b]).fetchall()]
    evs = [e for e in csv.DictReader(open(TABLES / "events.csv")) if e["place"] == "Brooklyn" and int(e["last_old_year"]) == a]
    q = f"""SELECT k, count(*) FROM (SELECT a.name, {{s}} AS k FROM p a {{j}} WHERE a.place = 'Brooklyn' AND a.year = {a}
             GROUP BY ALL HAVING count(*) = 1) x JOIN (SELECT a.name, {{s}} AS k FROM p a {{j}}
             WHERE a.place = 'Brooklyn' AND a.year = {b} GROUP BY ALL HAVING count(*) = 1) y USING (name, k) GROUP BY 1"""
    now = dict(con.execute(q.format(s="a.street", j="")).fetchall())
    print(f"  now: {sum(now.values())} stayers on {len(now)} streets; the {len(evs)} events have {sum(int(e['stayers']) for e in evs)}")
    for kinds in (("spelling",), ("renaming",), ("override",), None):
        con.execute("DROP TABLE IF EXISTS m")
        con.execute("CREATE TABLE m (street VARCHAR, id VARCHAR)")
        con.executemany("INSERT INTO m VALUES (?, ?)", [(s, lookup("Brooklyn", s, b, kinds)) for s in keys])
        new = dict(con.execute(q.format(s="m.id", j="JOIN m ON m.street = a.street")).fetchall())
        gain = {e["street"]: new.get(lookup("Brooklyn", e["street"], b, kinds), 0) - int(e["stayers"]) for e in evs}
        print(f"  {'+'.join(kinds) if kinds else 'all merges':<10}: {sum(new.values()) - sum(now.values()):+d} stayers over Brooklyn, "
              f"{sum(g for g in gain.values() if g > 0):+d} in {sum(g > 0 for g in gain.values())} events: "
              + ", ".join(f"{s} {g:+d}" for s, g in sorted(gain.items(), key=lambda x: -x[1])[:8] if g > 0))
    for label, year in (("as of each event's new year", None), ("the key's last id, whatever the year", 9999)):
        groups = {}
        for e in csv.DictReader(open(TABLES / "events.csv")):
            groups.setdefault((e["place"], e["last_old_year"], e["first_new_year"],
                               canon(e["place"], e["street"], year or int(e["first_new_year"]))), []).append(e["street"])
        two = {g: s for g, s in groups.items() if len(s) > 1}
        print(f"  events.csv {label}: {sum(len(s) for s in two.values())} events are {len(two)} streets under two keys: "
              + "; ".join(f"{g[0]} {g[1]}-{g[2]} {s}" for g, s in two.items()))


def main():
    import duckdb
    con = duckdb.connect()
    con.execute(f"CREATE VIEW p AS SELECT * FROM read_parquet('{PEOPLE}')")
    con.execute("CREATE TABLE c AS SELECT place, street, year, count(*) AS n FROM p GROUP BY ALL")
    con.execute("CREATE TABLE k AS SELECT place, street AS key, sum(n) AS n, min(year) AS y0, max(year) AS y1 FROM c GROUP BY ALL")
    rows, found = build(con)
    with open(TABLES / "streets.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    by = {}
    for r in rows:
        by[r["why"]] = by.get(r["why"], 0) + 1
    print(f"{len({(r['place'], r['street_id']) for r in rows})} ids over {len({(r['place'], r['key']) for r in rows})} keys "
          f"-> addresses/tables/streets.csv; rows by why: {by}")
    measure(con, found)


def self_test():
    assert canon("Brooklyn", "marshall", 1869) == canon("Brooklyn", "seigel", 1880) == "seigel"   # a renaming
    assert canon("Brooklyn", "stanton", 1860) == "stanton" and canon("Brooklyn", "stanton", 1871) == "duffield"
    assert canon("Brooklyn", "siegel", 1880) == "seigel"                                           # a spelling
    assert canon("Brooklyn", "fulton av", 1871) == "fulton av" and canon("Brooklyn", "fulton av", 1875) == "fulton"
    assert canon("Brooklyn", "w baltic", 1871) == "w baltic" and canon("Brooklyn", "w baltic", 1875) == "baltic"
    assert canon("Brooklyn", "franklin", 1880) != canon("Brooklyn", "franklin av", 1880)
    assert canon("Brooklyn", "zzz nonesuch", 1880) == "zzz nonesuch"
    print("registry self-test passes")


if __name__ == "__main__":
    self_test() if sys.argv[1:] == ["--self-test"] else main()
