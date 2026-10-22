#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["pillow==10.4.0", "numpy==2.0.2"]
# ///
"""
Cut one book-scan volume's half tiles on Torch, for LightOnOCR-3 (docs/PIPELINE.md #27).

    uv run hpc/books_tiles.py <ident> [--workers 8] [--keep-pages]
    uv run hpc/books_tiles.py --self-test

hpc/42_books_tiles.sbatch runs it, one array task per volume. The word layer comes from the Mac,
data/reocr_books_records/<id>.records.jsonl.gz (IA's words per listing page, side-band scraps
stripped: data_prep/reocr_books.py records); the page images from the volume's IA archive,
data/reocr_zips/<id>_jp2.zip or .tar (hpc/41_books_download.sh, on the data-transfer node).

It writes data/reocr_tiers/<id>/: the tiles (<id>/<id>_<leaf>_c<k>_h<j>.jpg), boxes.json (each
tile's box on its page), columns.json (the volume's column count) and STAGED (counts, timings).
The cutting is data_prep/reocr_columns.py `stage`, the code that cut the canary's tiles on the
Mac, and the pinned Pillow and numpy are the Mac's, so a page is cut here as it was there. The
page images (JPEG from the archive's JPEG 2000) live in data/reocr_tiers/<id>/pages/ only while
the tiles are cut. Resumable: a volume with STAGED is skipped, a page image already converted is
kept, and a re-run re-cuts only tiles whose box changed.

Every page image must be in its word record's frame (the record's page_size): `convert` checks
each one and stops the volume if one is not. Trow 1915 and 1917, whose IIIF images are camera
frames, come as a .tar of pages IA has already cropped and turned, in the words' frame, so they
pass as they are; the tar is read in one pass, having no index. A zip whose pages were camera
frames would be turned upright (data_prep/iiif_frame.py: results/iiif_frames.json and the cached
scandata in data/scandata/, shipped with the code; no network here).
"""
from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing
import shutil
import sys
import tarfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "data_prep"))
RECORDS = REPO / "data" / "reocr_books_records"
ZIPS = REPO / "data" / "reocr_zips"
TIERS = REPO / "data" / "reocr_tiers"

_zip = None


def _open_zip(path: str) -> None:
    global _zip
    _zip = zipfile.ZipFile(path)


def convert(ident: str, leaf: int, data: bytes, dst: Path, size: tuple) -> None:
    """One page: JPEG 2000 -> JPEG at full size, in the frame of its word record (`size`, the
    record's page_size). The words and the tiles must share a frame, so a page that does not match
    is turned upright where IA's IIIF frame is a camera's (iiif_frame), and refused if it still
    does not match. Trow 1915/1917's _jp2.tar holds the pages already cropped and turned (leaf
    688: 3273 x 4516, as IA's words, where IIIF serves the 5616 x 3744 camera frame), so they pass
    as they are; turning them again would have cut every tile from the wrong place."""
    from iiif_frame import mismatched, upright
    from PIL import Image
    from reocr_volumes import jp2_to_jpeg
    tmp = dst.with_suffix(".part")
    tmp.write_bytes(jp2_to_jpeg(data))
    with Image.open(tmp) as im:
        got = im.size
    if got != tuple(size) and ident in mismatched():
        turned = upright(ident, leaf, Image.open(tmp)).convert("RGB")
        turned.save(tmp, "JPEG", quality=95)
        got = turned.size
    if got != tuple(size):
        tmp.unlink()
        raise SystemExit(f"{ident} leaf {leaf}: the image is {got[0]} x {got[1]}, its words' page "
                         f"{size[0]} x {size[1]} -- not the same frame, so no tile can be cut")
    tmp.rename(dst)


def _from_zip(job) -> int:
    ident, leaf, dst, size = job
    convert(ident, leaf, _zip.read(f"{ident}_jp2/{ident}_{leaf:04d}.jp2"), Path(dst), size)
    return leaf


def _from_bytes(job) -> int:
    ident, leaf, data, dst, size = job
    convert(ident, leaf, data, Path(dst), size)
    return leaf


def leaf_of(member: str, ident: str):
    """The leaf a tar member holds, by its file name (<id>_NNNN.jp2, in whatever directory)."""
    base = member.rsplit("/", 1)[-1]
    if base.startswith(f"{ident}_") and base.endswith(".jp2") and base[len(ident) + 1:-4].isdigit():
        return int(base[len(ident) + 1:-4])
    return None


def images(ident: str, archive: Path, want: dict, workers: int) -> int:
    """Convert the wanted leaves' images ({leaf: (dst, page_size)}); returns how many were
    converted. A zip is read at random by every worker; a tar has no index, so it is read once,
    in order."""
    todo = {leaf: (dst, size) for leaf, (dst, size) in want.items() if not dst.exists()}
    if not todo:
        return 0
    if archive.suffix == ".zip":
        with multiprocessing.Pool(workers, initializer=_open_zip, initargs=(str(archive),)) as pool:
            jobs = [(ident, leaf, str(dst), size) for leaf, (dst, size) in sorted(todo.items())]
            return sum(1 for _ in pool.imap_unordered(_from_zip, jobs, chunksize=4))
    found = set()

    def stream():
        with tarfile.open(archive) as tf:
            for m in tf:
                leaf = leaf_of(m.name, ident)
                if leaf in todo:
                    found.add(leaf)
                    yield ident, leaf, tf.extractfile(m).read(), str(todo[leaf][0]), todo[leaf][1]
    with multiprocessing.Pool(workers) as pool:
        n = sum(1 for _ in pool.imap_unordered(_from_bytes, stream(), chunksize=1))
    missing = sorted(set(todo) - found)
    if missing:
        raise SystemExit(f"{archive.name}: no image for {len(missing)} leaves, e.g. {missing[:5]}")
    return n


def run(ident: str, workers: int, keep_pages: bool) -> int:
    out = TIERS / ident
    if (out / "STAGED").exists():
        print(f"{ident}: staged already ({out / 'STAGED'}) -- skipping")
        return 0
    archive = next((p for p in (ZIPS / f"{ident}_jp2.zip", ZIPS / f"{ident}_jp2.tar") if p.exists()), None)
    if archive is None:
        raise SystemExit(f"{ident}: no {ident}_jp2.zip or .tar in {ZIPS} -- run hpc/41_books_download.sh")
    t0 = time.time()
    pages = out / "pages" / ident
    pages.mkdir(parents=True, exist_ok=True)
    want = {}
    with gzip.open(RECORDS / f"{ident}.records.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            stem = f"{ident}_{rec['leaf']:04d}"
            (pages / f"{stem}.json").write_text(json.dumps(rec), encoding="utf-8")
            want[rec["leaf"]] = (pages / f"{stem}.jpg", rec["page_size"])
    n_img = images(ident, archive, want, workers)
    t1 = time.time()
    print(f"{ident}: {len(want)} pages, {n_img} images converted from {archive.name} in {t1 - t0:.0f}s",
          flush=True)
    from reocr_columns import stage
    stage(argparse.Namespace(out=str(out), pages=str(out / "pages"), tiles="halves", max_side=None,
                             per_shard=10 ** 9, sample=0, seed=20261014, workers=workers))
    boxes = json.loads((out / "boxes.json").read_text(encoding="utf-8"))
    cols = json.loads((out / "columns.json").read_text(encoding="utf-8")) \
        if (out / "columns.json").exists() else {}
    if not keep_pages:
        shutil.rmtree(out / "pages")
    staged = {"ident": ident, "archive": archive.name, "pages": len(want), "tiles": len(boxes),
              "columns": cols.get(ident), "convert_s": round(t1 - t0), "cut_s": round(time.time() - t1),
              "staged": time.strftime("%Y-%m-%d %H:%M")}
    (out / "STAGED").write_text(json.dumps(staged, indent=1) + "\n", encoding="utf-8")
    print(f"{ident}: {len(boxes)} tiles from {len(want)} pages at {cols.get(ident)} columns, "
          f"{time.time() - t0:.0f}s -> {out.relative_to(REPO)}", flush=True)
    return 0


def _self_test() -> int:
    assert leaf_of("trowsgeneraldire1915trow_jp2/trowsgeneraldire1915trow_0688.jp2",
                   "trowsgeneraldire1915trow") == 688
    assert leaf_of("trowsgeneraldire1915trow_0007.jp2", "trowsgeneraldire1915trow") == 7
    assert leaf_of("x_jp2/x_0007.jpg", "x") is None and leaf_of("x_jp2/x_scandata.jp2", "x") is None
    import io
    import tempfile
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 60), "white").save(buf, "JPEG2000")
    with tempfile.TemporaryDirectory() as d:
        convert("x", 1, buf.getvalue(), Path(d) / "a.jpg", (40, 60))
        assert (Path(d) / "a.jpg").exists(), "a page in its words' frame is kept as it is"
        try:
            convert("x", 2, buf.getvalue(), Path(d) / "b.jpg", (60, 40))
            raise AssertionError("a page in another frame must stop the volume")
        except SystemExit:
            assert not (Path(d) / "b.jpg").exists() and not (Path(d) / "b.part").exists()
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ident", nargs="?")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--keep-pages", action="store_true", help="keep the page images after cutting")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.ident:
        ap.error("an IA identifier is required")
    return run(args.ident, args.workers, args.keep_pages)


if __name__ == "__main__":
    sys.exit(main())
