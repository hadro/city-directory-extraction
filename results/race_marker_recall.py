"""PIPELINE #37: does the 4B set race_designation on lines that print a textual "colored" form?

    python3 -I results/race_marker_recall.py

Over usable rows whose raw_line contains (col'd) / (col.) / (col) / (colored) / (co'd) / colored.
Run 2026-11-04 on round 13's records: Doggett 1845 955/955, Trow 1857 1,484/1,488, Lain 1866 610/610,
Smith 1857 596/596, Longworth 1835 139/139, micro 0040 545/549. The few misses are not people
("Colored Orphan's Asylum", an abbreviations-key line). So textual markers need no repair; the
problem is the bare `*`, whose meaning is the volume's, not the line's (RACE_MARKERS_HANDOFF.md).
"""
import gzip
import glob
import json
import re

PAT = re.compile(r"\((?:col'd|col\.|col|colored|co'd|col d)\.?\)|\bcolored\b", re.I)
VOLS = ["doggettsnewyorkc1845dogg", "trowsnewyorkcity1857trow", "1866BPL", "1857BPL",
        "longworthsameric6018long", "micro_IABROOKLYN_0040"]

for v in VOLS:
    path = glob.glob(f"data/records*/4b-100k+guard/{v}.jsonl.gz")[0]
    on = got = 0
    for line in gzip.open(path, "rt"):
        r = json.loads(line)
        if r["usable"] and PAT.search(r["raw_line"]):
            on += 1
            got += bool((r.get("race_designation") or "").strip())
    print(f"{v:28} printed={on:5} model_set={got:5} ({100 * got / max(on, 1):.1f}%)")
