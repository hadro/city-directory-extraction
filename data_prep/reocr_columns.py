#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Column crops of the re-OCR'd pages for Churro-3B on Torch, and Churro's answers back as page
lines for the hybrid (docs/PIPELINE.md #27).

    python3 data_prep/reocr_columns.py stage [--per-shard 150]   # -> data/reocr_columns/
    tar czf cde-churro-columns.tar.gz data/reocr_columns         # ship; hpc/38_churro.sbatch
    python3 data_prep/reocr_columns.py import                    # -> data/reocr/<id>.churro.jsonl
    python3 data_prep/reocr_columns.py --self-test

WHY. On the M2, Churro-3B read the bench pages far better than tesseract (63.6% of lines exact
against 34.5%; 77% of gold lines), but took 5 minutes on a 50-line page, 10-29 on a 140-line
one, and gave up at the 15-minute cap on every dense Brooklyn 1857-58 page. Its answer grows
with the text on the page, so a column at a time halves or thirds each answer: fewer runaway
generations and shorter calls. The columns are reocr_volumes.columns over each cached page's
words, computed afresh (the `columns` stored in the cache are the rule's when the page ran).

`stage` crops each page's columns (the text's vertical extent, a margin around) to
data/reocr_columns/<id>/<id>_<leaf>_c<k>.jpg, records each crop's box in page pixels in
boxes.json, and writes shards of --per-shard crops (shards/shard_NNN.txt, paths relative to the
repo root) and tasks.txt (one shard per array task). Re-staging re-cuts only crops whose box
changed, dropping Churro's readings of the old ones. `import` reads each crop's
`_churro-3b.raw.txt` with reocr_bench.body_lines and joins a page's columns in order: one JSONL
per volume, {volume, leaf, lines}, the text run for reocr_bench.hybrid_page, whose boxed run is
the cached lines cut at the same columns (reocr_volumes.column_lines).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WORK = REPO / "data" / "reocr"
OUT = REPO / "data" / "reocr_columns"
sys.path.insert(0, str(HERE))

from reocr_bench import body_lines  # noqa: E402
from reocr_volumes import columns  # noqa: E402

PAD = 0.01              # of the page width, around each crop
SLUG = "churro-3b"


def crop_boxes(rec: dict) -> list:
    """[(k, (x0, y0, x1, y1))] for a cached page: each column, over the text's vertical extent."""
    W, H = rec["page_size"]
    if not rec["lines"]:
        return []
    y0 = min(w[1] for ws in rec["lines"] for w in ws)
    y1 = max(w[3] for ws in rec["lines"] for w in ws)
    pad = int(PAD * W)
    return [(k, (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)))
            for k, (x0, x1) in enumerate(columns(rec["lines"], W))]   # current rule, not the cache


def readings(crop: Path) -> list:
    return [crop.with_name(f"{crop.stem}_{SLUG}.{ext}") for ext in ("raw.txt", "meta.json")]


def stage(args) -> int:
    """Each crop's box (page pixels) is kept in boxes.json. A page whose columns changed (the rule
    did, 2026-10-06) gets new crops and loses Churro's readings of the old ones, and a column that
    no longer exists loses its crop; an unchanged box keeps both. (Comparing the JPEG bytes does
    not work: Pillow encodes the same crop to a few bytes' difference from one call to the next.)"""
    from PIL import Image
    manifest = OUT / "boxes.json"
    old = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    boxes, crops, changed = {}, [], 0
    for page in sorted(WORK.glob("*/*.json")):
        rec = json.loads(page.read_text(encoding="utf-8"))
        ident = page.parent.name
        img = None
        for k, box in crop_boxes(rec):
            dst = OUT / ident / f"{page.stem}_c{k}.jpg"
            key = str(dst.relative_to(OUT))
            boxes[key] = list(box)
            if not dst.exists() or old.get(key) != list(box):
                img = img or Image.open(page.with_suffix(".jpg"))
                dst.parent.mkdir(parents=True, exist_ok=True)
                img.crop(box).convert("RGB").save(dst, quality=92)
                for r in readings(dst):
                    r.unlink(missing_ok=True)
                changed += 1
            crops.append(dst)
    staged = set(crops)
    gone = [c for c in OUT.glob("*/*_c*.jpg") if c not in staged]
    for c in gone:
        for r in [c] + readings(c):
            r.unlink(missing_ok=True)
    manifest.write_text(json.dumps(boxes, indent=0, sort_keys=True), encoding="utf-8")
    print(f"{changed} crops cut or re-cut, {len(gone)} stale ones removed", file=sys.stderr)
    shards = OUT / "shards"
    shards.mkdir(parents=True, exist_ok=True)
    for old in shards.glob("shard_*.txt"):
        old.unlink()
    tasks = []
    for n in range(0, len(crops), args.per_shard):
        path = shards / f"shard_{n // args.per_shard:03d}.txt"
        path.write_text("\n".join(str(c.relative_to(REPO)) for c in crops[n:n + args.per_shard])
                        + "\n", encoding="utf-8")
        tasks.append(str(path.relative_to(REPO)))
    (OUT / "tasks.txt").write_text("\n".join(tasks) + "\n", encoding="utf-8")
    print(f"{len(crops)} crops from {len(set(c.parent for c in crops))} volumes, "
          f"{len(tasks)} shards of <= {args.per_shard} -> {OUT.relative_to(REPO)}",
          file=sys.stderr)
    print(f"submit with: sbatch $(slurm_gpu_args) --array=0-{len(tasks) - 1} hpc/38_churro.sbatch",
          file=sys.stderr)
    return 0


CROP_RX = re.compile(r"^(?P<vol>.+)_(?P<leaf>\d{4})_c(?P<k>\d+)_" + SLUG + r"\.raw\.txt$")


def import_run(args) -> int:
    pages = collections.defaultdict(dict)
    for raw in OUT.rglob(f"*_{SLUG}.raw.txt"):
        m = CROP_RX.match(raw.name)
        if m:
            pages[(m["vol"], int(m["leaf"]))][int(m["k"])] = body_lines(
                raw.read_text(encoding="utf-8"))
    by_vol = collections.defaultdict(list)
    for (vol, leaf), cols in sorted(pages.items()):
        by_vol[vol].append({"volume": vol, "leaf": leaf,
                            "lines": [t for k in sorted(cols) for t in cols[k]],
                            "columns_read": sorted(cols)})
    for vol, rows in by_vol.items():
        (WORK / f"{vol}.churro.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows),
                                                 encoding="utf-8")
    print(f"{sum(len(r) for r in by_vol.values())} pages in {len(by_vol)} volumes -> "
          f"data/reocr/<id>.churro.jsonl", file=sys.stderr)
    return 0


def _self_test() -> int:
    lines = ([[[100, 200 + 40 * i, 480, 230 + 40 * i, 90, "Smith"],
               [500, 200 + 40 * i, 900, 230 + 40 * i, 90, "John"]] for i in range(20)]
             + [[[1000, 200 + 40 * i, 1480, 230 + 40 * i, 90, "Jones"],
                 [1500, 200 + 40 * i, 1900, 230 + 40 * i, 90, "Wm"]] for i in range(20)])
    boxes = crop_boxes({"page_size": [2000, 3000], "lines": lines})
    assert [k for k, _ in boxes] == [0, 1]
    assert boxes[0][1] == (80, 180, 1020, 1010) and boxes[1][1] == (980, 180, 1920, 1010)
    assert CROP_RX.match("micro_IABROOKLYN_0039_0012_c1_churro-3b.raw.txt")["k"] == "1"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["stage", "import"])
    ap.add_argument("--per-shard", type=int, default=150)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "stage":
        return stage(args)
    if args.cmd == "import":
        return import_run(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
