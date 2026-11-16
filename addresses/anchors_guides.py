"""Corners with a house number in the guide before a renumbering and the guide after
(RENUMBERING_PLAN 2C step 4), and how they sit with the stayers (the G2 measure).

    uv run --with duckdb==2.0.0 python addresses/anchors_guides.py 1871BPL 1875BPL Brooklyn 1871

Reads data/addresses/guides/<volume>.jsonl (guides.py) for the two volumes and pairs a street's
crossings on the cross street's name (two letters' slack: "sackctt"). A corner keeps both sides'
numbers together, since sides are not to be trusted across a renumbering: on Bridge st the people
at old odd numbers have new even ones. Writes data/addresses/corners_<old>_<new>.jsonl: street,
cross, old (numbers at the corner), new, and the event's place and last old year, which fit.py reads them by.

The check, against data/addresses/stayers.parquet (events.py) for the place and the event's last
old year: a stayer whose old number lies between two paired corners should have a new number
between the same two corners (TOLERANCE either way). Prints the share that do, and the streets
where fewest do. Stayers who moved along the street, namesakes and misread numbers count against.
"""
import collections
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "browse"))
import find_address as fa  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOLERANCE = 8


def load(volume: str) -> dict:
    by = collections.defaultdict(list)
    for line in open(REPO / f"data/addresses/guides/{volume}.jsonl"):
        r = json.loads(line)
        r["numbers"] = [r[s] for s in ("left", "right") if r[s] is not None and r[s + "_ok"]]
        by[r["street"].replace(" (e.d.)", "")].append(r)   # 1875 drops the district mark
    return by


def corners(old: dict, new: dict) -> list:
    out = []
    for street in sorted(old.keys() & new.keys()):
        for o in old[street]:
            if not o["numbers"]:
                continue
            n = min(new[street], key=lambda r: fa.lev(o["cross"], r["cross"], 3))
            if fa.lev(o["cross"], n["cross"], 3) <= min(2, len(o["cross"]) // 4) and n["numbers"]:
                out.append({"street": street, "cross": n["cross"], "old": o["numbers"],
                            "new": n["numbers"]})
    return out


def check(found: list, place: str, year: int):
    by = collections.defaultdict(list)
    for c in found:
        by[c["street"]].append(c)
    stayers = duckdb.sql(f"""SELECT street, n0, n1 FROM '{REPO}/data/addresses/stayers.parquet'
                             WHERE place = '{place}' AND y0 = {year} AND n0 <> n1""").fetchall()
    asked, agreed = collections.Counter(), collections.Counter()
    for street, n0, n1 in stayers:
        below = [c for c in by.get(street, []) if max(c["old"]) <= n0]
        above = [c for c in by.get(street, []) if min(c["old"]) >= n0]
        if below and above:
            lo = max(below, key=lambda c: max(c["old"]))
            hi = min(above, key=lambda c: min(c["old"]))
            asked[street] += 1
            agreed[street] += min(lo["new"]) - TOLERANCE <= n1 <= max(hi["new"]) + TOLERANCE
    total = sum(asked.values())
    print(f"{total} stayers lie between two paired corners; {sum(agreed.values()) / total:.0%} "
          f"have their new number between the same corners (+-{TOLERANCE}), over {len(asked)} streets")
    worst = sorted((agreed[s] / asked[s], asked[s], s) for s in asked if asked[s] >= 8)[:10]
    print(" fewest agree: " + ", ".join(f"{s} {a:.0%} of {n}" for a, n, s in worst))


if __name__ == "__main__":
    old, new, place, year = sys.argv[1:5]
    found = [dict(c, place=place, y0=int(year)) for c in corners(load(old), load(new))]
    with open(REPO / f"data/addresses/corners_{old}_{new}.jsonl", "w") as f:
        f.writelines(json.dumps(c) + "\n" for c in found)
    print(f"{len(found)} corners with a number in both guides, on "
          f"{len({c['street'] for c in found})} streets")
    check(found, place, int(year))
