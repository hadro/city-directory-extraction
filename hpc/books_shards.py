#!/usr/bin/env python3
"""
The LightOn tasks for a tier's cut volumes: shards of --per-shard tiles across volumes
(docs/PIPELINE.md #27). Standard library only; run on a login node after hpc/42_books_tiles.sbatch.

    python3 hpc/books_shards.py data/reocr_books_records/volumes_abbyy8-damaged.tsv [--per-shard 2000]

Writes data/reocr_tiers/shards_<label>/shard_NNN.txt (tile paths, one per line, relative to the
checkout) and data/reocr_tiers/tasks_<label>.txt (one shard per array task), for

    sbatch $(slurm_gpu_args) --export=ALL,ENGINE=vllm,TASKS=data/reocr_tiers/tasks_<label>.txt \
        --array=0-<N-1> hpc/39_lightonocr.sbatch

Shards mix volumes: vLLM's engine start is a fixed ~80 s a task, so ~2,000 tiles a shard keeps
it under a tenth of the task (the canary read 2,000 tiles in 13-24 minutes). Tiles that already
have an answer are left out, so after a partial run this lists only what is missing. Volumes not
yet cut (no STAGED) are reported and left out; run it again once they are.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TIERS = REPO / "data" / "reocr_tiers"
SLUG = "lightonocr-3-1b-greedy-vllm"


def tiles_of(ident: str, slug: str = SLUG) -> tuple:
    """(all tiles, unanswered tiles) of a cut volume, as paths relative to the checkout."""
    root = TIERS / ident
    keys = sorted(json.loads((root / "boxes.json").read_text(encoding="utf-8")))
    tiles = [root / k for k in keys]
    todo = [t for t in tiles if not t.with_name(f"{t.stem}_{slug}.meta.json").exists()]
    return [str(t.relative_to(REPO)) for t in tiles], [str(t.relative_to(REPO)) for t in todo]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vols", help="the volumes TSV (data_prep/reocr_books.py records)")
    ap.add_argument("--per-shard", type=int, default=2000)
    args = ap.parse_args(argv)
    vols = Path(args.vols)
    label = vols.stem.removeprefix("volumes_")
    idents = [line.split("\t")[0] for line in vols.read_text(encoding="utf-8").splitlines()[1:] if line]
    todo, cut, missing, n_all = [], 0, [], 0
    for ident in idents:
        if not (TIERS / ident / "STAGED").exists():
            missing.append(ident)
            continue
        everything, left = tiles_of(ident)
        cut += 1
        n_all += len(everything)
        todo += left
    shards = TIERS / f"shards_{label}"
    shards.mkdir(parents=True, exist_ok=True)
    for old in shards.glob("shard_*.txt"):
        old.unlink()
    tasks = []
    for k in range(0, len(todo), args.per_shard):
        path = shards / f"shard_{k // args.per_shard:03d}.txt"
        path.write_text("\n".join(todo[k:k + args.per_shard]) + "\n", encoding="utf-8")
        tasks.append(str(path.relative_to(REPO)))
    task_file = TIERS / f"tasks_{label}.txt"
    task_file.write_text("".join(t + "\n" for t in tasks), encoding="utf-8")
    print(f"{cut} of {len(idents)} volumes cut: {n_all:,} tiles, {len(todo):,} without an answer "
          f"-> {len(tasks)} shards of <= {args.per_shard} in {task_file.relative_to(REPO)}")
    if missing:
        print(f"not cut yet ({len(missing)}): {', '.join(missing)}")
    if tasks:
        print(f"submit with: sbatch $(slurm_gpu_args) --export=ALL,ENGINE=vllm,"
              f"TASKS={task_file.relative_to(REPO)} --array=0-{len(tasks) - 1} hpc/39_lightonocr.sbatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
