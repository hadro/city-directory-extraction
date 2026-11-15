"""The mapping through the anchors: chains (RENUMBERING_PLAN Phase 3).

    uv run --with duckdb==2.0.0 python addresses/fit.py            # every event in events.csv
    python3 addresses/fit.py --self-test

For each event (a street renumbered between two directory years) the anchors are the stayers'
(old number, new number) pairs from data/addresses/stayers.parquet. A **chain** is a set of
anchors in one order from end to end (rising, or falling on a street numbered from the other end)
in which neighbours are plausibly neighbours: the new numbers between two anchors span no more
than SLOPE times the old ones plus SLACK, and the other way round, and no two neighbours are
more than GAP apart. The heaviest chain is taken out, then the next from what is left, while a
chain has MIN_POINTS anchors; one averaging fewer than an anchor per SPARSE old numbers is a few
movers lined up by chance, and is left out.

Why more than one chain: before a renumbering a street's numbers were often not one run. On
Court St in 1871 the main run has 168 -> 240 and 216 -> 294, while people at 166-272 near
Gowanus have new numbers 437-556 and people at 621-645 have 433-465; Myrtle av has a second run
(167-198 -> 623-682) beside its main one. So an old number can mean two houses, and each chain
answers separately. Why not an offset per side: on Bridge st the old even numbers became odd.
A chain is only an order, with the new side read off its nearest anchors.

Anchors off every chain (people who moved along the street, namesakes, misread numbers) are kept,
with chain -1.

Writes data/addresses/anchors.parquet (place, street, y0, y1, old, new, weight, chain) and
addresses/tables/chains.csv (one row per chain: its direction, the old and new numbers it spans,
its anchors). `across(chain_points, number)` gives the new numbers an old one falls between;
`back` the other way. Prints the held-back check: fit on four fifths of a street's anchors, and
see whether each of the rest falls where its chain says (within TOLERANCE).
"""
import bisect
import csv
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLOPE, SLACK = 2, 12   # settings barely matter: 3/12 to 1.5/10 give 79-82% right on Brooklyn 1871-75
MIN_POINTS = 5
GAP = 100          # neighbours in a chain are no further apart than this, in either numbering
SPARSE = 20        # a chain averages an anchor at least every so many old numbers
TOLERANCE = 2


def heaviest_chain(points: list) -> tuple:
    """(direction, indices) of the heaviest chain in [(old, new, weight), ...] sorted by old."""
    best = (0, 1, [])
    for sign in (1, -1):
        score, prev = [], []
        for i, (old, new, weight) in enumerate(points):
            top, at = 0, -1
            for j in range(i):
                d_old, d_new = old - points[j][0], sign * (new - points[j][1])
                if 0 < d_old <= GAP and 0 < d_new <= GAP and d_new <= SLOPE * d_old + SLACK \
                        and d_old <= SLOPE * d_new + SLACK and score[j] > top:
                    top, at = score[j], j
            score.append(top + weight)
            prev.append(at)
        if score and max(score) > best[0]:
            i = score.index(max(score))
            chain = []
            while i != -1:
                chain.append(i)
                i = prev[i]
            best = (max(score), sign, chain[::-1])
    return best[1], best[2]


def chains(points: list) -> list:
    """[(direction, [(old, new, weight), ...]), ...], heaviest first, and the anchors left over."""
    left = sorted(points)
    out, thin = [], []
    while True:
        sign, idx = heaviest_chain(left)
        if len(idx) < MIN_POINTS:
            return out, left + thin
        chain = [left[i] for i in idx]
        if (chain[-1][0] - chain[0][0]) / len(chain) <= SPARSE:
            out.append((sign, chain))
        else:                          # a few movers that happen to line up: not a numbering
            thin += chain
        taken = set(idx)
        left = [p for i, p in enumerate(left) if i not in taken]


def across(chain: list, number: int, col: int = 0) -> tuple | None:
    """The other era's (low, high) for a number, from the two anchors it lies between in a
    chain; an anchor's own number gives (n, n). None outside the chain. col 0: old to new."""
    pts = sorted(chain, key=lambda p: p[col])
    keys = [p[col] for p in pts]
    i = bisect.bisect_left(keys, number)
    if i < len(keys) and keys[i] == number:
        hits = [p[1 - col] for p in pts if p[col] == number]
        return min(hits), max(hits)
    if i == 0 or i == len(keys):
        return None
    a, b = pts[i - 1][1 - col], pts[i][1 - col]
    return min(a, b), max(a, b)


def back(chain: list, number: int) -> tuple | None:
    return across(chain, number, col=1)


def held_back(points: list, folds: int = 5) -> tuple:
    """(asked, placed, right): anchors held back, those a chain fitted on the rest reaches, and
    those whose new number is where that chain says. An anchor is counted weight times."""
    asked = placed = right = 0
    for fold in range(folds):
        test = [p for p in points if zlib.crc32(repr(p[:2]).encode()) % folds == fold]
        fitted, _ = chains([p for p in points if p not in test])
        for old, new, weight in test:
            asked += weight
            spans = [s for _, c in fitted if (s := across(c, old))]
            placed += weight * bool(spans)
            right += weight * any(lo - TOLERANCE <= new <= hi + TOLERANCE for lo, hi in spans)
    return asked, placed, right


def self_test():
    main = [(n, n + 78, 1) for n in range(150, 260, 6)]
    second = [(n, n + 300, 1) for n in range(160, 200, 6)]
    assert not chains([(10, 50, 1), (90, 120, 1), (170, 200, 1), (250, 290, 1), (330, 380, 1)])[0]
    movers = [(170, 30, 1), (240, 900, 1)]
    found, left = chains(main + second + movers)
    assert [len(c) for _, c in found] == [len(main), len(second)] and len(left) == 2
    assert across(found[0][1], 153) == (228, 234) and across(found[0][1], 156) == (234, 234)
    assert back(found[0][1], 230) == (150, 156) and across(found[0][1], 100) is None
    reverse = [(n, 400 - n, 1) for n in range(10, 120, 8)]
    (sign, chain), = chains(reverse)[0]
    assert sign == -1 and across(chain, 14) == (382, 390)
    print("fit self-test passes")


def main():
    import duckdb
    events = list(csv.DictReader(open(HERE / "tables/events.csv")))
    con = duckdb.connect()
    con.execute(f"CREATE VIEW s AS SELECT * FROM '{HERE.parent}/data/addresses/stayers.parquet'")
    anchors, summary, totals = [], [], {}
    for e in events:
        key = (e["place"], e["street"], int(e["last_old_year"]), int(e["first_new_year"]))
        points = con.execute("""SELECT n0, n1, count(*) FROM s WHERE place = ? AND street = ?
                                AND y0 = ? AND n0 <> n1 GROUP BY ALL""", list(key[:3])).fetchall()
        found, left = chains(points)
        for k, (sign, chain) in enumerate(found):
            anchors += [(*key, old, new, w, k) for old, new, w in chain]
            olds, news = [p[0] for p in chain], [p[1] for p in chain]
            summary.append({"place": key[0], "street": key[1], "last_old_year": key[2],
                            "first_new_year": key[3], "chain": k,
                            "direction": sign, "old_from": min(olds), "old_to": max(olds),
                            "new_from": min(news), "new_to": max(news), "anchors": len(chain),
                            "stayers": sum(p[2] for p in chain)})
        anchors += [(*key, old, new, w, -1) for old, new, w in left]
        t = totals.setdefault(key[:1] + key[2:], [0] * 7)
        on = sum(p[2] for _, c in found for p in c)
        for i, v in enumerate((1, len(found), on, *held_back(points), sum(p[2] for p in points))):
            t[i] += v
    con.execute("""CREATE TABLE a (place VARCHAR, street VARCHAR, y0 INT, y1 INT, old INT,
                                   new INT, weight INT, chain INT)""")
    con.executemany("INSERT INTO a VALUES (?, ?, ?, ?, ?, ?, ?, ?)", anchors)
    con.execute(f"COPY a TO '{HERE.parent}/data/addresses/anchors.parquet' (FORMAT parquet)")
    with open(HERE / "tables/chains.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    print(f"{len(summary)} chains on {len(events)} events -> addresses/tables/chains.csv")
    print(" event                 streets chains  stayers on a chain   held back: placed   right of placed")
    for (place, y0, y1), (n, c, on, asked, placed, right, total) in sorted(totals.items()):
        if n >= 5:
            print(f" {place:<10} {y0}-{y1} {n:>7} {c:>6}  {on:>6} of {total:<6} {on / total:>4.0%}"
                  f"   {placed / max(1, asked):>6.0%}   {right / max(1, placed):>8.0%}")


if __name__ == "__main__":
    self_test() if sys.argv[1:] == ["--self-test"] else main()
