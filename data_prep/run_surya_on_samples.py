# NOTE: deliberately NO PEP 723 (`# /// script`) inline-dependency header.
# Surya must come from the directory-pipeline gpu venv (a pinned version that has
# `surya.foundation`); `uv run script.py` with an inline header would instead build
# a throwaway env with the latest PyPI surya-ocr (different module layout → ImportError).
# Run it with that venv's python — see "Usage" below.
"""
Run Surya OCR across ALL sampled gold volumes in one pass — loads the models ONCE
and processes every selected dir, instead of paying the model-load cost per volume
(which 42 separate `run_surya_ocr.py` calls would).

For each chosen image it writes the SAME schema the gold tool reads (matches
directory-pipeline/pipeline/run_surya_ocr.py):
    {stem}_surya.json  {"image_width","image_height","lines":[{bbox,text,confidence}]}
    {stem}_surya.txt   plain text

By default it OCRs only the LISTING pages of each volume (the entries you want gold
from), detecting them as the pages after the contiguous front-matter block (the
sampler downloads `--front N` front canvases 0..N-1, then `-k` listing pages sampled
from deeper in the book → a big canvas-index gap). Pass --all-pages to OCR everything.

MUST run with the directory-pipeline gpu venv (where the pinned Surya lives).
Do NOT use `uv run <this script>` — the inline-header trap above. Instead:

    cd ../directory-pipeline && uv sync --extra gpu          # one-time install
    # then either of:
    .venv/bin/python ../city-directory-extraction/data_prep/run_surya_on_samples.py
    uv run python ../city-directory-extraction/data_prep/run_surya_on_samples.py

Usage
-----
    # all 42 worklist volumes, listing pages only, resumable (default):
    .venv/bin/python ../city-directory-extraction/data_prep/run_surya_on_samples.py

    # every sampled dir under output/ (ignore the worklist), all pages, re-OCR:
    .venv/bin/python ../city-directory-extraction/data_prep/run_surya_on_samples.py \
        --no-worklist --all-pages --force

    # a few specific dirs:
    .venv/bin/python ../city-directory-extraction/data_prep/run_surya_on_samples.py \
        --dirs output/ia_lain_1884_1884bpl
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO.parent / "directory-pipeline" / "output"
DEFAULT_WORKLIST = REPO / "data_prep" / "gold_sample" / "worklist.csv"

GAP = 10                       # canvas-index jump that marks front-matter -> listing
CANVAS_RE = re.compile(r"(\d+)(?:\.jp2)?\.je?pg$", re.I)


def canvas_idx(p: Path):
    m = CANVAS_RE.search(p.name)
    return int(m.group(1)) if m else None


def _iiif_text(v) -> str:
    """Flatten an IIIF label/value: v2 plain string, or v3 {lang:[str]} / lists."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for vals in v.values():
            if isinstance(vals, list) and vals:
                return str(vals[0])
            if isinstance(vals, str):
                return vals
        return ""
    if isinstance(v, list) and v:
        return _iiif_text(v[0])
    return ""


def manifest_identifier(d: Path) -> str:
    mf = d / "_sample_manifest.json"
    if not mf.exists():
        return ""
    try:
        m = json.load(open(mf, encoding="utf-8"))
    except Exception:
        return ""
    for entry in m.get("metadata", []) or []:
        if _iiif_text(entry.get("label")).lower() == "identifier":
            return _iiif_text(entry.get("value"))
    return ""


def worklist_ids(path: Path) -> set:
    if not path.exists():
        return set()
    return {(r.get("id") or "").strip()
            for r in csv.DictReader(open(path, encoding="utf-8")) if (r.get("id") or "").strip()}


def dir_matches_worklist(d: Path, ids: set) -> bool:
    ident = manifest_identifier(d)
    if ident and ident in ids:
        return True
    return any(rid and rid in d.name for rid in ids)


def page_jpgs(d: Path) -> list:
    """Real source page images in a sample dir (skip viz/split/crop derivatives)."""
    out = []
    for p in sorted(d.glob("*.jpg")):
        if p.stem.endswith(("_viz", "_left", "_right")):
            continue
        out.append(p)
    return out


def listing_pages(jpgs: list) -> list:
    """Pages after the contiguous front-matter block, by canvas-index gap."""
    idx = [(canvas_idx(p), p) for p in jpgs]
    if any(i is None for i, _ in idx):
        return jpgs                      # can't detect safely -> caller decides
    idx.sort(key=lambda t: t[0])
    cut = None
    for j in range(1, len(idx)):
        if idx[j][0] - idx[j - 1][0] > GAP:
            cut = j
            break
    if cut is None:
        return []                        # no gap -> ambiguous (likely all front)
    return [p for _, p in idx[cut:]]


def select_dirs(args) -> list:
    if args.dirs:
        return [Path(d) for d in args.dirs]
    root = Path(args.output_root)
    dirs = [d for d in sorted(root.iterdir())
            if d.is_dir() and (d / "_sample_manifest.json").exists()]
    if not args.no_worklist:
        ids = worklist_ids(Path(args.worklist))
        if not ids:
            print(f"! no worklist ids at {args.worklist}; use --no-worklist to OCR all sampled dirs",
                  file=sys.stderr)
            return []
        dirs = [d for d in dirs if dir_matches_worklist(d, ids)]
    return dirs


def collect_targets(dirs: list, args) -> list:
    targets = []
    for d in dirs:
        jpgs = page_jpgs(d)
        if not jpgs:
            print(f"  {d.name}: no page images", file=sys.stderr)
            continue
        if args.all_pages:
            chosen = jpgs
        else:
            chosen = listing_pages(jpgs)
            if not chosen:
                print(f"  {d.name}: listing pages undetected — OCRing ALL "
                      f"{len(jpgs)} pages (use --all-pages to silence)", file=sys.stderr)
                chosen = jpgs
        todo = [p for p in chosen
                if args.force or not (p.parent / f"{p.stem}_surya.json").exists()]
        done = len(chosen) - len(todo)
        print(f"  {d.name}: {len(todo)} to OCR ({done} done, {len(jpgs)} pages total)",
              file=sys.stderr)
        targets.extend(todo)
    return targets


def write_result(image_path: Path, pil_img, result):
    w, h = pil_img.size
    lines = [
        {"bbox": [int(v) for v in ln.bbox],
         "text": ln.text.replace("<br>", "\n"),
         "confidence": round(float(getattr(ln, "confidence", 1.0)), 4)}
        for ln in result.text_lines
    ]
    out = {"image_width": w, "image_height": h, "lines": lines}
    (image_path.parent / f"{image_path.stem}_surya.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    (image_path.parent / f"{image_path.stem}_surya.txt").write_text(
        "\n".join(l["text"] for l in lines), encoding="utf-8")
    return len(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output-root", default=str(DEFAULT_OUT),
                    help="directory-pipeline/output (scanned for sampled dirs)")
    ap.add_argument("--worklist", default=str(DEFAULT_WORKLIST),
                    help="restrict to ids in this worklist.csv (default: gold_sample/worklist.csv)")
    ap.add_argument("--no-worklist", action="store_true", help="OCR every sampled dir, ignore worklist")
    ap.add_argument("--dirs", nargs="+", help="explicit sample dirs (overrides discovery)")
    ap.add_argument("--all-pages", action="store_true", help="OCR every sampled page, not just listings")
    ap.add_argument("--force", action="store_true", help="re-OCR pages that already have _surya.json")
    ap.add_argument("--batch-size", "-b", type=int, default=4, help="images per inference batch")
    ap.add_argument("--dry-run", action="store_true", help="list targets, do not load models / OCR")
    args = ap.parse_args(argv)

    dirs = select_dirs(args)
    if not dirs:
        print("No sample dirs selected. Have you run the sampler on worklist.csv yet?", file=sys.stderr)
        return 1
    print(f"{len(dirs)} volume(s) selected:", file=sys.stderr)
    targets = collect_targets(dirs, args)
    if not targets:
        print("\nNothing to OCR (all done? use --force to redo).", file=sys.stderr)
        return 0
    print(f"\nTotal images to OCR: {len(targets)}", file=sys.stderr)
    if args.dry_run:
        for p in targets:
            print(f"  {p}", file=sys.stderr)
        return 0

    print("Loading Surya models…", file=sys.stderr)
    try:
        from PIL import Image
        from surya.detection import DetectionPredictor
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
    except ImportError as exc:
        print(f"Error: {exc}\nInstall in the gpu env:  cd ../directory-pipeline && uv sync --extra gpu",
              file=sys.stderr)
        return 2
    det = DetectionPredictor()
    rec = RecognitionPredictor(FoundationPredictor())

    total = len(targets)
    ok = fail = 0
    t0 = time.monotonic()
    for start in range(0, total, args.batch_size):
        batch = targets[start:start + args.batch_size]
        try:
            imgs = [Image.open(p).convert("RGB") for p in batch]
        except Exception as exc:
            print(f"  FAILED loading batch @{start}: {exc}", file=sys.stderr)
            fail += len(batch)
            continue
        try:
            results = rec(imgs, det_predictor=det, sort_lines=True)
        except Exception as exc:
            print(f"  FAILED inference batch @{start}: {exc}", file=sys.stderr)
            fail += len(batch)
            continue
        for p, im, res in zip(batch, imgs, results):
            try:
                n = write_result(p, im, res)
                ok += 1
                done = ok + fail
                rate = done / max(1e-6, time.monotonic() - t0)
                eta = (total - done) / rate if rate else 0
                print(f"[{done:04d}/{total}] {p.parent.name}/{p.name}  "
                      f"({n} lines, ~{eta:.0f}s left)", file=sys.stderr)
            except Exception as exc:
                print(f"  FAILED saving {p.name}: {exc}", file=sys.stderr)
                fail += 1

    dt = time.monotonic() - t0
    print(f"\nDone in {dt:.1f}s — {ok} OCR'd, {fail} failed across {len(dirs)} volume(s).",
          file=sys.stderr)
    print("Next: build editors, e.g.\n"
          "  for d in <dirs>; do python3 data_prep/make_gold_tool.py \"$d\" -o \"gold_$(basename $d).html\"; done",
          file=sys.stderr)
    return 1 if fail and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
