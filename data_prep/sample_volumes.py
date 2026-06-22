# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Pick a REPRESENTATIVE subset of volumes from master_directories.csv to build gold
eval lines from, and emit a worklist that drives the gold pipeline over them.

Why stratify: the eval panel should mirror the corpus's variety, not its raw counts
(85 Trow volumes shouldn't drown out 1 Franks). The lever the README names is
**publisher × era × column_count × institution** — that variety is what proves the
model generalizes across styles. So we stratify by (publisher, column_count) and
spread picks across the year range within each stratum (catching the 1→2→3-column
transitions, which are publisher- and era-specific).

Excluded automatically: PHONEBOOK / BIZ rows (separate track), eval holdouts
(notes mention eval/holdout/"keep OUT"), and rows with no usable id.

Outputs (under data_prep/gold_sample/ by default):
  - worklist.csv  — a master-format subset of ONLY the chosen volumes. Feed it
                    straight to the sampler: it samples exactly this set.
  - WORKLIST.md   — a human checklist: the 3 commands (sample → surya → build),
                    plus one ☐ line per volume with why-it-was-picked.

Usage
-----
    python3 data_prep/sample_volumes.py                  # default: ~1 per (publisher,col)
    python3 data_prep/sample_volumes.py --per 2 --max 40 # 2 per stratum, cap 40
    python3 data_prep/sample_volumes.py --by publisher,column_count,decade
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MASTER = REPO / "data_prep" / "master_directories.csv"

EXCLUDE_NOTE = re.compile(r"phonebook|\bbiz\b|eval|holdout|held[- ]out|keep out", re.I)


def _year(r) -> int:
    m = re.search(r"(\d{4})", r.get("year") or "")
    return int(m.group(1)) if m else 0


def _decade(r) -> str:
    y = _year(r)
    return f"{y // 10 * 10}s" if y else "∅"


def in_scope(r) -> bool:
    if not (r.get("id") or "").strip():
        return False
    if EXCLUDE_NOTE.search(r.get("notes") or ""):
        return False
    return True


def stratum_key(r, by) -> tuple:
    parts = []
    for k in by:
        if k == "decade":
            parts.append(_decade(r))
        elif k == "publisher":
            parts.append((r.get("publisher") or "unknown").strip() or "unknown")
        else:
            parts.append((r.get(k) or "∅").strip() or "∅")
    return tuple(parts)


def spread(members, per) -> list:
    """Pick `per` rows spread evenly across the year-sorted stratum (first & last incl.)."""
    ms = sorted(members, key=_year)
    n = len(ms)
    if per >= n:
        return ms
    if per == 1:
        return [ms[n // 2]]              # median year
    idx = [round(i * (n - 1) / (per - 1)) for i in range(per)]
    return [ms[i] for i in sorted(set(idx))]


def select(rows, by, per, max_total):
    strata = defaultdict(list)
    for r in rows:
        strata[stratum_key(r, by)] = strata[stratum_key(r, by)] + [r]
    picked, why = [], {}
    for key in sorted(strata, key=lambda k: (-len(strata[k]), k)):
        reps = spread(strata[key], per)
        for r in reps:
            rid = (r["source"], r["id"])
            if rid in why:
                continue
            why[rid] = " · ".join(f"{b}={v}" for b, v in zip(by, key))
            picked.append(r)
    # cap: round-robin keep so we don't truncate whole tail strata
    if max_total and len(picked) > max_total:
        picked = _roundrobin_cap(picked, strata, by, per, max_total)
    picked.sort(key=lambda r: ((r.get("publisher") or "~").lower(), _year(r)))
    return picked, why


def _roundrobin_cap(picked, strata, by, per, max_total):
    by_key = defaultdict(list)
    for r in picked:
        by_key[stratum_key(r, by)].append(r)
    out, keys = [], sorted(by_key, key=lambda k: (-len(strata[k]), k))
    i = 0
    while len(out) < max_total and any(by_key[k] for k in keys):
        k = keys[i % len(keys)]
        if by_key[k]:
            out.append(by_key[k].pop(0))
        i += 1
    return out


def write_subset(picked, fieldnames, out_csv):
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in picked:
            w.writerow(r)


DEEP_TARGET = 100   # high-value volumes: aim ~100 gold lines
STD_TARGET = 40     # everything else: ~40 is enough to catch style failures


def depth_map(picked, all_rows):
    """Recommend which volumes to label deeper. Rule (see VISUAL_SAMPLING_HANDOFF):
    deepen Lain (known synth->real gap) and any publisher whose run spans a
    column-count transition (layout change is where the model breaks)."""
    pub_cols = defaultdict(set)
    for r in all_rows:
        p = (r.get("publisher") or "unknown").strip() or "unknown"
        c = (r.get("column_count") or "").strip()
        if c.isdigit():
            pub_cols[p].add(int(c))
    out = {}
    for r in picked:
        p = (r.get("publisher") or "unknown").strip() or "unknown"
        cols = sorted(pub_cols.get(p, set()))
        if "lain" in p.lower():
            out[(r["source"], r["id"])] = ("deep", DEEP_TARGET, "synth→real gap (Lain)")
        elif p.lower() != "unknown" and len(cols) > 1:   # skip the spurious catch-all bucket
            out[(r["source"], r["id"])] = ("deep", DEEP_TARGET,
                                           f"col-transition ({'→'.join(map(str, cols))})")
        else:
            out[(r["source"], r["id"])] = ("std", STD_TARGET, "")
    return out


def write_worklist(picked, why, depth, out_md, out_csv):
    rel_csv = out_csv.relative_to(REPO)
    deep = [r for r in picked if depth[(r["source"], r["id"])][0] == "deep"]
    lines = [
        "# Gold-creation worklist",
        "",
        f"{len(picked)} representative volumes selected from `master_directories.csv`.",
        "Work top-to-bottom; check each off as its `gold.jsonl` lands in `data/`.",
        "",
        f"**Depth:** aim ~{STD_TARGET} gold lines per volume; go deeper (~{DEEP_TARGET}) on the "
        f"**{len(deep)} `deep`-flagged** rows below (Lain's synth→real gap + column-transition "
        "publishers, where layout change breaks the model). Pass the target to the editor with "
        "`--max-lines`.",
        "",
        "## Run once — sample pages for the whole set",
        "```bash",
        "PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python",
        "cd /Users/joshhadro/github/directory-pipeline",
        f'$PY sources/sample_directories.py "{REPO / rel_csv}" --front 20 -k 2 --width 1800',
        "```",
        "",
        "## Then per volume — OCR + build the editor",
        "```bash",
        "# surya needs the gpu env (uv sync --extra gpu); see VISUAL_SAMPLING_HANDOFF.md",
        "$PY pipeline/run_surya_ocr.py output/<slug>            # 1) line OCR + bboxes",
        "$PY ../city-directory-extraction/data_prep/make_gold_tool.py \\",
        "      output/<slug> -o gold_<slug>.html --max-lines 40   # use the row's target below",
        "# 3) open gold_<slug>.html, correct fields, Export -> drop in city-directory-extraction/data/",
        "# 4) validate:  python3 data_prep/validate_gold.py data/gold_<slug>.jsonl",
        "```",
        "",
        "## Volumes",
        "",
        "| ☐ | depth | target | source/id | publisher | year | col | borough | stratum / why |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in picked:
        rid = (r["source"], r["id"])
        dlevel, target, dwhy = depth[rid]
        note = dwhy or why.get(rid, "")
        lines.append(
            f"| ☐ | {'**deep**' if dlevel == 'deep' else 'std'} | ~{target} | "
            f"`{r['source']}/{r['id']}` | {r.get('publisher','')} | "
            f"{r.get('year','')} | {r.get('column_count','')} | {r.get('borough','')} | {note} |"
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", default=str(MASTER))
    ap.add_argument("--by", default="publisher,column_count",
                    help="comma strata keys: publisher,column_count,decade,source,borough,city")
    ap.add_argument("--per", type=int, default=1, help="representatives per stratum")
    ap.add_argument("--max", type=int, default=0, help="overall cap (0 = no cap)")
    ap.add_argument("--out-dir", default=str(REPO / "data_prep" / "gold_sample"))
    args = ap.parse_args(argv)

    by = [k.strip() for k in args.by.split(",") if k.strip()]
    with open(args.master, newline="") as f:
        rd = csv.DictReader(f)
        fieldnames = rd.fieldnames
        rows = [r for r in rd if in_scope(r)]

    picked, why = select(rows, by, args.per, args.max)
    depth = depth_map(picked, rows)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "worklist.csv"
    out_md = out_dir / "WORKLIST.md"
    write_subset(picked, fieldnames, out_csv)
    write_worklist(picked, why, depth, out_md, out_csv)

    n_deep = sum(1 for v in depth.values() if v[0] == "deep")
    print(f"in-scope volumes: {len(rows)} | strata by {by} | selected: {len(picked)} "
          f"({n_deep} deep, {len(picked) - n_deep} std)", file=sys.stderr)
    print(f"  -> {out_csv}\n  -> {out_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
