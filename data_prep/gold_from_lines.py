#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""
Build the gold editor (make_gold_tool.py) from an ingested volume's own lines. No Surya.

    uv run data_prep/gold_from_lines.py --lines data/1856BPL_lines.jsonl \
        --pages 3 --per-page 40 -o gold_1856BPL.html
    uv run data_prep/gold_from_lines.py --lines data/1856BPL_lines.jsonl --leaves 168,391 -o ...
    uv run data_prep/gold_from_lines.py --ocr-input gold.jsonl --out data/<set>_ocr_eval.jsonl
    uv run data_prep/gold_from_lines.py --self-test          # offline

WHY
---
make_gold_tool.py read only Surya OCR, made by the page sampler in ../directory-pipeline, so a
gold set needed a second repo and Surya's GPU environment. It also seeded the gold from a
different OCR than the pipeline reads. The 21-volume panel's Surya lines hold zero lines opening
with `44`, ABBYY's reading of `"` and the commonest leading token in 1906BPL. The panel on the
model's real input (eval/ia_panel.py) had to be built afterwards, by aligning the gold back onto
IA's lines.

This seeds the editor from the `_lines.jsonl` that ia_volume_to_jsonl.py writes: the model's own
input, wraps joined and ditto marks normalized. The page image comes from IIIF. A gold set then
needs only this repo and an IA identifier.

**What this gold cannot see: loss before the model.** A printed entry that IA's OCR missed, or
that an ingest filter dropped, is not a line here, so it never reaches the editor. ia_panel.py
found that loss because its gold came from the page: 1,608 of 1,902 rows (84.5%) reached the
model as a line at all, and on microfilm far fewer (smith1856 140/229). Gold built with this
tool measures extraction on the lines the pipeline delivers. Measure delivery separately, by
reading `--dump-dropped` and comparing a page image with its kept lines.

WHAT GOES IN THE EXPORT
-----------------------
The contract is unchanged: `raw_line` is the verbatim PAGE, OCR misreads fixed by the labeller
(GROUND_TRUTH_HANDOFF.md). The line as the pipeline produced it stays beside it in
`context.ocr_line`, so one labelling pass gives both panels: the clean-text gold, and the
real-input pair that ia_panel.py had to recover by alignment. `--ocr-input` writes the second
(raw_line <- ocr_line). Also carried: `ia_id`, `leaf`, `bbox` (hOCR pixel space, unscaled),
`page_size`, and `band` / `raw_line_original` where the ingest set them.

SAMPLING
--------
Leaves are drawn, seeded, from the listing's VOTING leaves (detect_listing_bounds.detect,
interior="drop"), so the ad pages inside the listing's span are not drawn. Each leaf gives one
contiguous window of `--per-page` lines at a seeded offset: contiguous, because a ditto line
cannot be labelled without the line it repeats. `--leaves` replaces the draw. Lines keep their
emission order, which is reading order on this corpus (resolve_dittos.py: 93.6% of within-leaf
surname steps are alphabetically non-decreasing on 1906BPL), so make_gold_tool's column
bucketing is bypassed for these pages.

IMAGES
------
IIIF, the one image scheme that tracks the hOCR leaf (survey_frontmatter.page_image). Boxes are
scaled from hOCR pixel space to the image IIIF actually returns. Trow 1915/1917, whose IIIF
images are two-page camera frames, are turned and cut to the upright page first
(iiif_frame.upright). Images are cached in the stage dir, so a re-run downloads nothing.
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import tempfile
import time
import urllib.request
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import iiif_frame                                                    # noqa: E402
import make_gold_tool                                                # noqa: E402  (needs pillow)
from detect_listing_bounds import detect, leaf_letters_from_jsonl   # noqa: E402
from PIL import Image                                                # noqa: E402

IIIF = "https://iiif.archive.org/iiif"
CARRY = ("ia_id", "leaf", "bbox", "page_size", "band", "raw_line_original")
MIN_LEAF_LINES = 10      # a voting leaf with fewer kept lines than this is not worth a page
ASPECT_TOL = 0.02        # x and y scales further apart than this: the image is not the hOCR's page


def read_leaves(path: Path) -> "OrderedDict[int, list]":
    """leaf -> its rows, in the file's (emission) order."""
    by_leaf: OrderedDict = OrderedDict()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                by_leaf.setdefault(row["context"]["leaf"], []).append(row)
    return by_leaf


def choose_leaves(path: Path, by_leaf: dict, n: int, seed: int) -> list:
    letters = leaf_letters_from_jsonl(path, 5)
    result, _blocks, kept = detect(letters, (max(letters) + 1) if letters else 0, str(path),
                                   interior="drop")
    if result is None:
        sys.exit(f"{path}: no alphabetical listing found -- pass --leaves")
    pool = [leaf for leaf in kept if len(by_leaf.get(leaf, ())) >= MIN_LEAF_LINES]
    print(f"  listing leaves {result['start_leaf']}-{result['end_leaf']}: drawing {n} of "
          f"{len(pool)} voting leaves (seed {seed})", file=sys.stderr)
    return sorted(random.Random(seed).sample(pool, min(n, len(pool))))


def window(rows: list, per_page: int, seed: int, leaf: int) -> list:
    """One contiguous run of `per_page` rows at a seeded offset; seeded per leaf, so a leaf's
    window does not move when other leaves are added to the draw."""
    if not per_page or per_page >= len(rows):
        return rows
    a = random.Random(f"{seed}:{leaf}").randrange(len(rows) - per_page + 1)
    return rows[a:a + per_page]


def _get(url: str, retries: int = 3) -> Image.Image:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=iiif_frame.UA)
            return Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=120).read()))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_page(ident: str, leaf: int, page_size, dest: Path) -> Image.Image:
    """The leaf's image, upright as IA's OCR saw it, cached at `dest`."""
    if dest.exists():
        return Image.open(dest)
    if ident in iiif_frame.mismatched():
        _cx, _cy, _rot, cam_w, cam_h = iiif_frame.pages(ident)[leaf]
        img = _get(f"{IIIF}/{ident}${leaf}/full/!{cam_w},{cam_h}/0/default.jpg")
        img = iiif_frame.upright(ident, leaf, img, tuple(page_size))
    else:
        # `!w,h` never upscales; asking for the hOCR's own size gets the scan at full resolution
        img = _get(f"{IIIF}/{ident}${leaf}/full/!{page_size[0]},{page_size[1]}/0/default.jpg")
    img = img.convert("RGB")
    img.save(dest, quality=90)
    return img


def stage(by_leaf: dict, leaves: list, per_page: int, seed: int, stage_dir: Path,
          fetch=fetch_page) -> int:
    """Write {stem}.jpg + {stem}_ocr.json per leaf and a _sample_manifest.json: make_gold_tool's
    input layout. Returns the number of lines staged."""
    stage_dir.mkdir(parents=True, exist_ok=True)
    for old in stage_dir.glob("*_ocr.json"):       # a previous draw's pages; images stay cached
        old.unlink()
    first = by_leaf[leaves[0]][0]["context"]
    ident, year = first["ia_id"], str(first.get("directory_year", ""))
    (stage_dir / "_sample_manifest.json").write_text(json.dumps({
        "id": f"{IIIF}/{ident}/manifest.json", "label": ident,
        "metadata": [{"label": "identifier", "value": ident}, {"label": "date", "value": year}],
    }), encoding="utf-8")
    total = 0
    for leaf in leaves:
        rows = window(by_leaf[leaf], per_page, seed, leaf)
        page_size = rows[0]["context"]["page_size"]
        stem = f"{ident}_{leaf:04d}"
        img = fetch(ident, leaf, page_size, stage_dir / f"{stem}.jpg")
        sx, sy = img.width / page_size[0], img.height / page_size[1]
        if abs(sx - sy) > ASPECT_TOL * max(sx, sy):
            print(f"  ! {stem}: image {img.width}x{img.height} is not the shape of the hOCR page "
                  f"{page_size[0]}x{page_size[1]} -- check its crops before labelling (a camera "
                  f"frame missing from results/iiif_frames.json?)", file=sys.stderr)
        lines = []
        for r in rows:
            c = r["context"]
            x0, y0, x1, y1 = c["bbox"]
            ctx = {k: c[k] for k in CARRY if k in c}
            ctx["ocr_line"] = r["raw_line"]
            lines.append({"text": r["raw_line"], "confidence": None, "context": ctx,
                          "bbox": [round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy)]})
        (stage_dir / f"{stem}_ocr.json").write_text(json.dumps(
            {"image_width": img.width, "reading_order": True, "lines": lines}), encoding="utf-8")
        total += len(lines)
        print(f"  + leaf {leaf}: {len(lines)} lines", file=sys.stderr)
    return total


def ocr_input(gold: Path, out: Path) -> int:
    """Gold rows with raw_line set to the line the pipeline produced: the model's real input."""
    n = missing = 0
    with open(gold, encoding="utf-8") as fh, open(out, "w", encoding="utf-8") as fo:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if "ocr_line" not in row.get("context", {}):
                missing += 1
                continue
            fo.write(json.dumps(dict(row, raw_line=row["context"]["ocr_line"]),
                                ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {out}: {n} rows" + (f", {missing} without context.ocr_line skipped" if missing
                                      else ""), file=sys.stderr)
    return 0


def _self_test() -> int:
    rows = [{"raw_line": f"line {i}", "context": {"leaf": 7}} for i in range(30)]
    w = window(rows, 10, 1, 7)
    assert len(w) == 10 and w == rows[rows.index(w[0]):rows.index(w[0]) + 10], "contiguous"
    assert window(rows, 10, 1, 7) == w, "seeded"
    assert window(rows, 0, 1, 7) == rows and window(rows, 99, 1, 7) == rows

    # a two-column page emitted left column first: a y-sort would interleave the columns
    ctx = {"ia_id": "testvol", "directory_year": "1856", "page_size": [1000, 1400], "band": "body"}
    lines = [("Abel John, carman, 12 Pine", [60, 100, 460, 130]),
             ('" Wm, clk, h 3 Ann', [60, 900, 460, 930]),
             ("Baker Jas, mason, 4 Gold", [540, 100, 940, 130])]
    by_leaf = {12: [{"raw_line": t, "context": dict(ctx, leaf=12, bbox=b)} for t, b in lines]}

    def fake_fetch(ident, leaf, page_size, dest):    # IIIF at half the hOCR's resolution
        img = Image.new("RGB", (500, 700), "white")
        img.paste((0, 0, 0), (0, 0, 250, 700))         # contrast, or make_gold_tool skips it as blank
        img.save(dest)
        return img

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "stale_ocr.json").write_text("{}")
        assert stage(by_leaf, [12], 0, 1, d, fetch=fake_fetch) == 3
        assert not (d / "stale_ocr.json").exists(), "a previous draw is cleared"
        staged = json.loads((d / "testvol_0012_ocr.json").read_text())
        assert staged["lines"][1]["bbox"] == [30, 450, 230, 465], "scaled to the image"
        assert staged["lines"][1]["context"]["bbox"] == [60, 900, 460, 930], "hOCR box kept"
        assert staged["lines"][1]["context"]["ocr_line"] == '" Wm, clk, h 3 Ann'
        pages = make_gold_tool._collect([d], 2, 0.0, {}, 0)
        assert [r["raw"] for r in pages[0]["rows"]] == [t for t, _ in lines], "emission order"
        assert pages[0]["year"] == "1856" and pages[0]["rows"][0]["conf"] is None
        assert pages[0]["rows"][0]["ctx"]["band"] == "body"
        assert "ocr_line" in make_gold_tool.build_html(pages, "smith")

        gold = d / "gold.jsonl"
        gold.write_text(json.dumps({"raw_line": '" Wm, clk, h 3 Ann st',
                                    "context": {"ocr_line": '" Wm, clk, h 3 Ann'}, "record": {}})
                        + "\n" + json.dumps({"raw_line": "x", "context": {}, "record": {}}) + "\n")
        ocr_input(gold, d / "ocr.jsonl")
        out = [json.loads(x) for x in (d / "ocr.jsonl").read_text().splitlines()]
        assert len(out) == 1 and out[0]["raw_line"] == '" Wm, clk, h 3 Ann'
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", help="a *_lines.jsonl from ia_volume_to_jsonl.py")
    ap.add_argument("-o", "--out", help="output HTML (with --lines) or JSONL (with --ocr-input)")
    ap.add_argument("--pages", type=int, default=3, help="leaves to draw from the listing")
    ap.add_argument("--per-page", type=int, default=40,
                    help="contiguous lines per leaf (0 = the whole leaf)")
    ap.add_argument("--leaves", help="comma list of leaves, instead of a draw")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--publisher", default="",
                    help="context.publisher tag (default: the lines' own)")
    ap.add_argument("--stage", help="staging dir (default data/gold_stage/<ident>)")
    ap.add_argument("--ocr-input", metavar="GOLD",
                    help="exported gold.jsonl -> the same rows on the model's real input")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if args.ocr_input:
        if not args.out:
            ap.error("--ocr-input needs --out")
        return ocr_input(Path(args.ocr_input), Path(args.out))
    if not args.lines:
        ap.error("--lines is required (or --ocr-input / --self-test)")

    path = Path(args.lines)
    by_leaf = read_leaves(path)
    first = next(iter(by_leaf.values()))[0]["context"]
    ident = first["ia_id"]
    if args.leaves:
        leaves = sorted(int(x) for x in args.leaves.split(","))
        absent = [x for x in leaves if x not in by_leaf]
        if absent:
            ap.error(f"no kept lines on leaves {absent} in {path}")
    else:
        leaves = choose_leaves(path, by_leaf, args.pages, args.seed)
    stage_dir = Path(args.stage) if args.stage else REPO / "data" / "gold_stage" / ident
    n = stage(by_leaf, leaves, args.per_page, args.seed, stage_dir)
    print(f"staged {n} lines from leaves {','.join(map(str, leaves))} in {stage_dir}",
          file=sys.stderr)
    out = args.out or f"gold_{ident}.html"
    return make_gold_tool.main([str(stage_dir), "-o", out,
                                "--publisher", args.publisher or first.get("publisher", "")])


if __name__ == "__main__":
    raise SystemExit(main())
