"""Everything in addresses/, in order, from the records file: run it again whenever the records
gain volumes.

    uv run --with duckdb==2.0.0 python addresses/build.py data/space/records.parquet

1. events.py people   the people (a name once on a street in a year) from the records
2. guides.py    the street guides of addresses/tables/guide_pairs.csv as rows (from the OCR words)
3. registry.py  one id per street across renamings and overrides (and spellings, not used), from 1
4. events.py    the renumbering events and the stayers, on those ids (from 1 and 3)
5. anchors_guides.py   the corners each pair of guides shares
6. fit.py       the chains, one run of old numbers per printed key
7. atlas.py     the 1855 Perris atlas against today's address points, and against the chains
8. chain.py     the eras of each street, and whether the last directory's numbering is today's
9. export_crosswalk.py   the chains as data/space/crosswalk.csv, for the finder

The order is what keeps it acyclic: the registry reads only the people, the events read the
registry, so a run gives the same on the first time as on the second.

guide_pairs.csv names, for an event's place and last old year, the guide before and the guide
after; add a row when a volume with a street guide comes in. Nothing else is kept by hand.
"""
import csv
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, *args):
    print(f"--- {script} {' '.join(args)}", flush=True)
    subprocess.run([sys.executable, str(HERE / script), *args], check=True, cwd=HERE.parent)


if __name__ == "__main__":
    for script in ("streets.py", "guides.py", "fit.py", "registry.py", "atlas.py", "chain.py"):
        run(script, "--self-test")
    run("events.py", "people", sys.argv[1])
    pairs = list(csv.DictReader(open(HERE / "tables/guide_pairs.csv")))
    run("guides.py", *sorted({p[k] for p in pairs for k in ("guide_before", "guide_after")}))
    run("registry.py")
    run("events.py")
    for p in pairs:
        run("anchors_guides.py", p["guide_before"], p["guide_after"], p["place"], p["last_old_year"])
    run("fit.py")
    run("atlas.py")
    run("chain.py")
    run("export_crosswalk.py")
