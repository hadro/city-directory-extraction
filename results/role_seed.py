#!/usr/bin/env python3
"""
What the surname seed in eval/volume_run_report.layout_roles changes: each volume's line roles
with and without it, over every root the records are assembled from. No predictions needed.

    python3 results/role_seed.py                   # -> results/role_seed.json
    python3 results/role_seed.py --sample 60       # + a uniform sample of changed lines to read

Found 2026-11-04 on Trow 1909 p1 (round 13 lost 206 usable rows there): most boxes in a column
started ~45 px left of their ink, the column's modal edge took them as the margin, and the lines
at the ink came out `runover`.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "eval"), str(REPO / "data_prep")]
from volume_run_report import layout_roles  # noqa: E402

ROOTS = ["data/volumes_books_first_clean_v2", "data/volumes_books_damaged_v6",
         "data/volumes_reocr_v2", "data/volumes_run1"]


def one(args):
    root, ident = args
    lines = []
    for p in sorted((REPO / root / ident).glob("chunk_*.jsonl")):
        lines += [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines() if s.strip()]
    if not lines or not all((ln.get("context") or {}).get("page_size") for ln in lines):
        return root, ident, len(lines), Counter(), []
    old, new = layout_roles(lines, names=False), layout_roles(lines)
    per_leaf, flips, changed = Counter(), Counter(), []
    for ln, a, b in zip(lines, old, new):
        leaf = ln["context"]["leaf"]
        rid = f"{ident}:{leaf}:{per_leaf[leaf]}"
        per_leaf[leaf] += 1
        if a != b:
            flips[f"{a}->{b}"] += 1
            changed.append((rid, a, b, ln["context"]["bbox"], ln["raw_line"]))
    return root, ident, len(lines), flips, changed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, default=0, help="changed lines to sample, uniformly")
    ap.add_argument("--out", default=str(REPO / "results" / "role_seed.json"))
    a = ap.parse_args(argv)
    jobs = [(r, d.name) for r in ROOTS for d in sorted((REPO / r).iterdir())
            if d.is_dir() and any(d.glob("chunk_*.jsonl"))]
    out = {"roots": {}, "volumes": {}}
    pool_changed = []
    with ProcessPoolExecutor() as ex:
        for root, ident, n, flips, changed in ex.map(one, jobs):
            t = out["roots"].setdefault(root, {"lines": 0, "changed": 0, "flips": Counter()})
            t["lines"] += n
            t["changed"] += sum(flips.values())
            t["flips"].update(flips)
            if flips:
                out["volumes"][f"{root}:{ident}"] = {"lines": n, "flips": dict(flips)}
            pool_changed += [(root, *c) for c in changed]
    for root, t in out["roots"].items():
        t["flips"] = dict(t["flips"].most_common())
        print(f"{root}: {t['changed']:,} of {t['lines']:,} lines change role  {t['flips']}")
    top = sorted(out["volumes"].items(), key=lambda kv: -sum(kv[1]["flips"].values()))[:15]
    for k, v in top:
        print(f"  {k:60s} {sum(v['flips'].values()):>7,}  {v['flips']}")
    if a.sample:
        rnd = random.Random(20261104)
        out["sample"] = [dict(zip(("root", "record_id", "old", "new", "bbox", "raw_line"), c))
                         for c in rnd.sample(pool_changed, min(a.sample, len(pool_changed)))]
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
