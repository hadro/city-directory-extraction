#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Column crops of the re-OCR'd pages for Churro-3B on Torch, and Churro's answers back as page
lines for the hybrid (docs/PIPELINE.md #27).

    python3 data_prep/reocr_columns.py stage [--per-shard 150] [--workers 6]  # -> data/reocr_columns/
    python3 data_prep/reocr_columns.py stage --tiles halves [--max-side N]  # -> data/reocr_halves/
    python3 data_prep/reocr_columns.py stage --tiles halves --sample 2 --out data/reocr_screen
    python3 data_prep/reocr_columns.py bench-tasks      # the first Torch task: bench + screen pages
    tar cf cde-churro-columns.tar data/reocr_columns             # ship (JPEGs: no gzip); hpc/38_churro.sbatch
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
HALVES = REPO / "data" / "reocr_halves"
sys.path.insert(0, str(HERE))

from reocr_bench import body_lines  # noqa: E402
from reocr_volumes import page_columns  # noqa: E402

PAD = 0.01              # of the page width, around each crop
MAX_DIM = 2500          # churro-ocr's MAX_INLINE_IMAGE_DIM: it shrinks a larger image to fit
SLUG = "churro-3b"


BALANCE = 0.3           # a half holding less of its column's rows than this is re-cut by ink


def ink_cut(gray, x0: int, x1: int, a: int, b: int) -> int:
    """The whitest pixel row (5-row smoothing) between rows a and b of a column (upright image):
    the gap between printed lines, wherever tesseract's boxes put the rows."""
    import numpy as np
    a, b = max(0, a), min(gray.shape[0], b)
    region = gray[a:b, max(0, x0):x1].astype(float)
    if region.size == 0 or b - a < 5:
        return (a + b) // 2
    lo, hi = np.percentile(region, 5), np.percentile(region, 95)
    ink = (region < (lo + hi) / 2).sum(axis=1).astype(float)
    smooth = np.convolve(ink, np.ones(5) / 5, mode="same")
    return a + int(np.argmin(smooth))


def tile_boxes(rec: dict, tiles: str = "columns", gray=None) -> tuple:
    """(angle, [(name, (x0, y0, x1, y1))]) for a cached page: the degrees its image is turned
    upright by (Image.rotate; 0.0 for a page tilted under reocr_volumes.SKEW_MIN), and each tile
    in the turned image's pixels, in reading order. "columns": each column over the text's
    vertical extent (c0, c1, ...). "halves": each column cut in two at the gap between text rows
    nearest its middle (c0_h0, c0_h1, c1_h0, ...), so no printed line is split, or, given the
    upright page as `gray` and a cut that leaves a half with under BALANCE of the column's rows,
    at the whitest pixel row near the middle of the column's text (ink_cut); LightOnOCR-3 reads
    these (2026-10-14: 91.5% of gold entries exact on half tiles at native resolution, where
    Churro read worse on halves than on columns). The columns are the current rule's, not the
    cache's."""
    from reocr_volumes import segments
    W, H = rec["page_size"]
    if not rec["lines"]:
        return 0.0, []
    angle, upright, cols = page_columns(rec["lines"], (W, H))
    y0 = min(w[1] for ws in upright for w in ws)
    y1 = max(w[3] for ws in upright for w in ws)
    pad = int(PAD * W)
    segs = [s for s in segments(upright, W) if max(w[2] for w in s) - min(w[0] for w in s) > 0.04 * W]
    hs = sorted(w[3] - w[1] for ws in upright for w in ws)
    word_h = hs[len(hs) // 2]
    out = []
    for k, (x0, x1) in enumerate(cols):
        box = (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad))
        if tiles == "columns":
            out.append((f"c{k}", box))
            continue
        bands = []                                  # the column's text rows, top to bottom
        for a, b in sorted((min(w[1] for w in s), max(w[3] for w in s))
                           for s in segs if x0 <= min(w[0] for w in s) < x1):
            if bands and a < bands[-1][1]:
                bands[-1][1] = max(bands[-1][1], b)
            else:
                bands.append([a, b])
        mid = (box[1] + box[3]) / 2
        gaps = [(abs((a[1] + b[0]) / 2 - mid), (a[1] + b[0]) / 2)
                for a, b in zip(bands, bands[1:]) if b[0] > a[1]]
        cut = int(min(gaps)[1]) if gaps else int(mid)
        # The cut is then made by ink, on the upright page. Where tesseract's boxes span two rows
        # (micro_IABROOKLYN_0039 and others) the rows merge into one band and the only gaps are
        # near the ends: one half held 1 line and the other 83, so the model read nearly the
        # whole column at the resolution meant for half of it (12% of a 390-column sample had a
        # half under 15% of the rows). Such a column is cut at the whitest row within 12% of the
        # middle of its text; any other cut snaps to the whitest row within 0.6 of a word's
        # height, since a line tesseract missed leaves a "gap" in its rows where the page has
        # print (micro_IABROOKLYN_0033 leaf 300).
        centres = sorted((min(w[1] for w in s) + max(w[3] for w in s)) / 2
                         for s in segs if x0 <= min(w[0] for w in s) < x1)
        if gray is not None and centres:
            above = sum(c < cut for c in centres)
            if min(above, len(centres) - above) < BALANCE * len(centres):
                t, h = centres[0], centres[-1] - centres[0]
                cut = ink_cut(gray, x0, x1, int(t + 0.38 * h), int(t + 0.62 * h))
            else:
                cut = ink_cut(gray, x0, x1, int(cut - 0.6 * word_h), int(cut + 0.6 * word_h))
        out += [(f"c{k}_h0", (box[0], box[1], box[2], cut)), (f"c{k}_h1", (box[0], cut, box[2], box[3]))]
    return angle, out


def crop_boxes(rec: dict) -> tuple:
    """(angle, [(k, box)]): tile_boxes' columns, numbered."""
    angle, tiles = tile_boxes(rec, "columns")
    return angle, [(int(name[1:]), box) for name, box in tiles]


def readings(crop: Path) -> list:
    return [crop.with_name(f"{crop.stem}_{SLUG}.{ext}") for ext in ("raw.txt", "meta.json")]


def fit(img, max_dim: int | None = MAX_DIM):
    """The crop as Churro will see it: churro-ocr's prepare_ocr_image fits every image within
    MAX_DIM x MAX_DIM (Lanczos) before the model does, so a full-size crop ships pixels it never
    reads (15 GB of crops at full size, 2026-10-06). Same arithmetic, so its resize is a no-op."""
    from PIL import Image
    w, h = img.size
    if not max_dim or max(w, h) <= max_dim:
        return img
    scale = min(max_dim / w, max_dim / h)
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                      resample=Image.Resampling.LANCZOS)


def stage_page(job) -> tuple:
    """One page's crops, cut where the page's manifest entries changed: (entries, crops, cut)."""
    from PIL import Image
    page, old, out, tiles, max_dim = job
    rec = json.loads(page.read_text(encoding="utf-8"))
    img = None
    if tiles == "halves" and rec["lines"]:
        import numpy as np
        img = Image.open(page.with_suffix(".jpg"))
        angle = page_columns(rec["lines"], rec["page_size"])[0]
        if angle:
            img = img.rotate(angle, resample=Image.BICUBIC, fillcolor="white")
        angle, page_boxes = tile_boxes(rec, tiles, gray=np.asarray(img.convert("L")))
    else:
        angle, page_boxes = tile_boxes(rec, tiles)
    entries, crops, cut = {}, [], 0
    for name, box in page_boxes:
        dst = out / page.parent.name / f"{page.stem}_{name}.jpg"
        key = str(dst.relative_to(out))
        entries[key] = list(box) + ([angle] if angle else [])
        if not dst.exists() or old.get(key) != entries[key]:
            if img is None:
                img = Image.open(page.with_suffix(".jpg"))
                if angle:
                    img = img.rotate(angle, resample=Image.BICUBIC, fillcolor="white")
            dst.parent.mkdir(parents=True, exist_ok=True)
            fit(img.crop(box).convert("RGB"), max_dim).save(dst, quality=92)
            for r in readings(dst):
                r.unlink(missing_ok=True)
            cut += 1
        else:
            with Image.open(dst) as c:
                big = bool(max_dim) and max(c.size) > max_dim
            if big:                          # cut before crops were fitted: same pixels to Churro
                fit(Image.open(dst), max_dim).save(dst, quality=92)
        crops.append(dst)
    return entries, crops, cut


def stage(args) -> int:
    """Each crop's box (page pixels; then the angle, for a page turned upright) is kept in
    boxes.json. A page whose columns changed (the rule did, 2026-10-06) gets new crops and loses
    Churro's readings of the old ones, and a column that no longer exists loses its crop; an
    unchanged entry keeps both. (Comparing the JPEG bytes does not work: Pillow encodes the same
    crop to a few bytes' difference from one call to the next.) Pages run in --workers
    processes, and the manifest is saved every 500 pages, so a killed run resumes: one pass
    over all 7,947 pages took longer than half an hour in a single process."""
    import multiprocessing
    import random
    out = Path(args.out).resolve() if args.out else (OUT if args.tiles == "columns" else HALVES)
    max_dim = args.max_side if args.max_side is not None else (MAX_DIM if args.tiles == "columns" else 0)
    manifest = out / "boxes.json"
    old = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    by_page = collections.defaultdict(dict)
    for key, entry in old.items():
        by_page[key.rsplit("_c", 1)[0]][key] = entry
    pages = sorted(WORK.glob("*/*.json"))
    if args.sample:                         # a seeded sample of pages with text, per volume
        rng, by_vol = random.Random(args.seed), collections.defaultdict(list)
        for p in pages:
            if json.loads(p.read_text(encoding="utf-8"))["lines"]:
                by_vol[p.parent.name].append(p)
        pages = sorted(q for v in sorted(by_vol) for q in rng.sample(by_vol[v], min(args.sample, len(by_vol[v]))))
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(p, by_page.get(f"{p.parent.name}/{p.stem}", {}), out, args.tiles, max_dim) for p in pages]
    boxes, crops, changed = {}, [], 0
    with multiprocessing.Pool(args.workers) as pool:
        for n, (entries, page_crops, cut) in enumerate(pool.imap(stage_page, jobs, chunksize=8), 1):
            boxes.update(entries)
            crops += page_crops
            changed += cut
            if n % 500 == 0:
                manifest.write_text(json.dumps({**old, **boxes}, indent=0, sort_keys=True),
                                    encoding="utf-8")
                print(f"  {n}/{len(jobs)} pages, {changed} crops cut", file=sys.stderr, flush=True)
    staged = set(crops)
    gone = [c for c in out.glob("*/*_c*.jpg") if c not in staged]
    for c in gone:
        for r in [c] + readings(c):
            r.unlink(missing_ok=True)
    manifest.write_text(json.dumps(boxes, indent=0, sort_keys=True), encoding="utf-8")
    print(f"{changed} crops cut or re-cut, {len(gone)} stale ones removed", file=sys.stderr)
    shards = out / "shards"
    shards.mkdir(parents=True, exist_ok=True)
    for old in shards.glob("shard_*.txt"):
        old.unlink()
    tasks = []
    for n in range(0, len(crops), args.per_shard):
        path = shards / f"shard_{n // args.per_shard:03d}.txt"
        path.write_text("\n".join(str(c.relative_to(REPO)) for c in crops[n:n + args.per_shard])
                        + "\n", encoding="utf-8")
        tasks.append(str(path.relative_to(REPO)))
    (out / "tasks.txt").write_text("\n".join(tasks) + "\n", encoding="utf-8")
    print(f"{len(crops)} {args.tiles} tiles from {len(pages)} pages in "
          f"{len(set(c.parent for c in crops))} volumes, {len(tasks)} shards of <= {args.per_shard} "
          f"-> {out.relative_to(REPO)}", file=sys.stderr)
    job = "hpc/38_churro.sbatch" if args.tiles == "columns" else "hpc/39_lightonocr.sbatch"
    print(f"submit with: sbatch $(slurm_gpu_args) --array=0-{len(tasks) - 1} {job}", file=sys.stderr)
    return 0


def bench_tasks(args) -> int:
    """The first Torch task's tile list, data/reocr_halves/bench_tasks.txt -> shards/bench_000.txt:
    the 138 bench half tiles (data/reocr_benchcols/halves, scored against gold and the book scans)
    and the production half tiles of the screen's 78 pages (data/reocr_screen/boxes.json: 2 pages
    of each of the 39 deferred volumes, none on the bench). Read under the deployed setup, they
    re-score the bench on CUDA and check greedy's loops and table mode on unseen typography
    before the whole run; the full run then skips the screen pages' tiles, already read."""
    bench = sorted(p for p in (REPO / "data" / "reocr_benchcols" / "halves").glob("*/*_c*_h*.jpg"))
    screen = json.loads((REPO / "data" / "reocr_screen" / "boxes.json").read_text(encoding="utf-8"))
    pages = {key.rsplit("_c", 1)[0] for key in screen}
    prod = sorted(p for page in pages for p in (HALVES / page.split("/")[0]).glob(
        f"{page.split('/')[1]}_c*_h*.jpg"))
    tiles = bench + prod
    shard = HALVES / "shards" / "bench_000.txt"
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.write_text("\n".join(str(t.relative_to(REPO)) for t in tiles) + "\n", encoding="utf-8")
    (HALVES / "bench_tasks.txt").write_text(str(shard.relative_to(REPO)) + "\n", encoding="utf-8")
    print(f"{len(bench)} bench tiles + {len(prod)} screen-page tiles ({len(pages)} pages) -> "
          f"{shard.relative_to(REPO)}", file=sys.stderr)
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
    angle, boxes = crop_boxes({"page_size": [2000, 3000], "lines": lines})
    assert angle == 0.0
    assert [k for k, _ in boxes] == [0, 1]
    assert boxes[0][1] == (80, 180, 1020, 1010) and boxes[1][1] == (980, 180, 1920, 1010)
    assert CROP_RX.match("micro_IABROOKLYN_0039_0012_c1_churro-3b.raw.txt")["k"] == "1"
    angle, halves = tile_boxes({"page_size": [2000, 3000], "lines": lines}, "halves")
    assert [n for n, _ in halves] == ["c0_h0", "c0_h1", "c1_h0", "c1_h1"]
    assert halves[0][1] == (80, 180, 1020, 595) and halves[1][1] == (80, 595, 1020, 1010), \
        "cut in the gap between rows nearest the middle"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["stage", "import", "bench-tasks"])
    ap.add_argument("--per-shard", type=int, default=150)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--tiles", default="columns", choices=["columns", "halves"])
    ap.add_argument("--out", help="default data/reocr_columns (columns), data/reocr_halves (halves)")
    ap.add_argument("--max-side", type=int, help="fit tiles to this many pixels (0: native); "
                    "default 2500 for columns (Churro), native for halves")
    ap.add_argument("--sample", type=int, default=0, help="only this many pages per volume")
    ap.add_argument("--seed", type=int, default=20261014)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "stage":
        return stage(args)
    if args.cmd == "import":
        return import_run(args)
    if args.cmd == "bench-tasks":
        return bench_tasks(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
