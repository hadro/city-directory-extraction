"""Everything in addresses/, in order, from the records file: run it again whenever the records
gain volumes.

    uv run --with duckdb==2.0.0 python addresses/build.py data/space/records.parquet

1. events.py    the renumbering events, the stayers and the people (from the records)
2. guides.py    the street guides of addresses/tables/guide_pairs.csv as rows (from the OCR words)
3. anchors_guides.py   the corners each pair of guides shares
4. fit.py       the chains

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
    for script in ("streets.py", "guides.py", "fit.py"):
        run(script, "--self-test")
    run("events.py", sys.argv[1])
    pairs = list(csv.DictReader(open(HERE / "tables/guide_pairs.csv")))
    run("guides.py", *sorted({p[k] for p in pairs for k in ("guide_before", "guide_after")}))
    for p in pairs:
        run("anchors_guides.py", p["guide_before"], p["guide_after"], p["place"], p["last_old_year"])
    run("fit.py")
