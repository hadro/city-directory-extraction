#!/usr/bin/env python3
"""
Stage book-scan volumes for the LightOn re-OCR over IA's own words: no tesseract (PIPELINE #27).

    python3 data_prep/reocr_books.py download --ids a,b        # each volume's _jp2.zip, whole
    python3 data_prep/reocr_books.py pages --ids a,b [--workers 6]   # -> data/reocr_books/<id>/
    python3 data_prep/reocr_books.py tesseract --ids a,b         # -> data/reocr_books_tess/<id>/
    python3 data_prep/reocr_books.py records --tier abbyy8-damaged  # -> data/reocr_books_records/ (Torch)
    python3 data_prep/reocr_books.py status --ids a,b
    python3 data_prep/reocr_columns.py stage --pages data/reocr_books --tiles halves \
        --out data/reocr_books_halves --per-shard 2000      # then LightOn, then reocr_pair.py dump
    python3 data_prep/reocr_books.py --self-test

WHY (2026-10-20). The microfilm re-OCR (reocr_volumes.py) ran tesseract twice per page because IA's
OCR of the film was dead: it needed word boxes to pair LightOn's text with. A book scan's IA OCR
(ABBYY) is damaged in its characters, not its geometry, so its words can be that layer. On the
pilot's book-scan pages, with the same LightOn answers and the same tiles, IA's words as the layer
read 83.6% of gold entries exactly against fresh tesseract's 82.8% (33 rows gained, 11 lost),
once reocr_pair learned the volume's confirmed ditto forms (ABBYY-8 reads Trow 1917's `"` as "ii")
and stopped laying a name over garbled words out leftwards from its first anchor (respell).
Dropping tesseract also drops the step that forced the microfilm through the Mac: ~100k book-scan
pages at ~15 CPU-seconds each.

`pages` writes, per listing page (reocr_volumes.pages: residential runs, 50+ characters):
    data/reocr_books/<id>/<id>_<leaf>.json  {"leaf", "page_size", "chars", "lines", "engine"}:
                                            IA's words, a side banner's scraps stripped as the
                                            ingest strips them (strip_side_bands), since after
                                            pairing they carry the model's text at confidence 90
    data/reocr_books/<id>/<id>_<leaf>.jpg   the page, from the volume's _jp2.zip when `download`
                                            fetched it (reocr_volumes.fetch), else IIIF
The page JPEGs are needed only to cut tiles; once a volume's tiles are staged they can go.
"""
from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OCR = REPO / "data" / "survey_ocr"
BOOKS = REPO / "data" / "reocr_books"
TESS = REPO / "data" / "reocr_books_tess"       # fresh tesseract, the second word layer
RECORDS = REPO / "data" / "reocr_books_records"  # what a Torch-side staging needs from the Mac
TIERS = HERE / "run_tiers.json"
sys.path.insert(0, str(HERE))

import reocr_volumes as rv  # noqa: E402
from ia_volume_to_jsonl import strip_side_bands  # noqa: E402
from reocr_volumes import column_method, fetch  # noqa: E402

rv.WORK = BOOKS          # reocr_volumes.download counts a volume's pages left against this tree


def ia_dump(ident: str) -> Path:
    """IA's word dump: kept as <id>_words.ia.jsonl.gz once reocr_pair.py dump has replaced it."""
    ia = OCR / f"{ident}_words.ia.jsonl.gz"
    return ia if ia.exists() else OCR / f"{ident}_words.jsonl.gz"


def ia_page(rec: dict, engine: str) -> dict:
    lines, _n = strip_side_bands(rec["lines"], rec.get("page_size"))
    return {"leaf": rec["leaf"], "page_size": rec["page_size"],
            "chars": sum(len(w[5]) for ws in lines for w in ws), "lines": lines,
            "engine": f"ia-words ({engine})"}


def page_image(job) -> tuple:
    """(ident, leaf, status): the page's JPEG beside its record, as reocr_volumes.page_job
    fetches it (Trow 1915/1917's camera frames turned upright)."""
    from PIL import Image
    ident, leaf = job
    img = BOOKS / ident / f"{ident}_{leaf:04d}.jpg"
    if img.exists():
        return ident, leaf, "cached"
    try:
        fetch(ident, leaf, img)
        from iiif_frame import mismatched, upright
        if ident in mismatched():
            upright(ident, leaf, Image.open(img)).convert("RGB").save(img, quality=95)
        return ident, leaf, "ok"
    except Exception as e:                       # noqa: BLE001 - recorded, the run goes on
        return ident, leaf, f"error {type(e).__name__}: {e}"[:300]


def write_pages(args) -> int:
    jobs = []
    for ident in args.ids.split(","):
        if column_method(ident) != "gutters":
            print(f"{ident}: a microfilm volume -- stage it with reocr_volumes.py", file=sys.stderr)
            return 2
        side = json.loads((HERE / "survey" / f"ia_{ident}.json").read_text(encoding="utf-8"))
        engine = ((side.get("catalog_says") or {}).get("ia") or {}).get("ocr") or "IA OCR"
        want = set(rv.pages(ident))
        d = BOOKS / ident
        d.mkdir(parents=True, exist_ok=True)
        n = 0
        with gzip.open(ia_dump(ident), "rt", encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line)
                if rec["leaf"] not in want:
                    continue
                (d / f"{ident}_{rec['leaf']:04d}.json").write_text(
                    json.dumps(ia_page(rec, engine)), encoding="utf-8")
                jobs.append((ident, rec["leaf"]))
                n += 1
        print(f"{ident}: {n} page records ({len(want)} listing pages)", file=sys.stderr)
    with multiprocessing.Pool(args.workers) as pool:
        bad = 0
        for k, (ident, leaf, status) in enumerate(pool.imap_unordered(page_image, jobs), 1):
            if status.startswith("error"):
                bad += 1
                print(f"  {ident} {leaf}: {status}", file=sys.stderr)
            if k % 200 == 0 or k == len(jobs):
                print(f"  {k}/{len(jobs)} images", file=sys.stderr, flush=True)
    return 1 if bad else 0


def tess_page(job) -> tuple:
    """(ident, leaf, status): reocr_volumes' recipe (tesseract 5.5 on a Sauvola-binarized and a
    contrast-enhanced image, the more confident reading of each line) over a staged page image,
    as a second word layer in TESS for reocr_pair.py dump --alt-page-dir."""
    from PIL import Image
    ident, leaf = job
    out = TESS / ident / f"{ident}_{leaf:04d}.json"
    if out.exists():
        return ident, leaf, "cached"
    try:
        img = Image.open(BOOKS / ident / f"{ident}_{leaf:04d}.jpg")
        lines = rv.merge_words(rv.tess_words(img, "sauvola"), rv.tess_words(img, "contrast"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"leaf": leaf, "page_size": list(img.size),
                                   "chars": sum(len(w[5]) for ws in lines for w in ws),
                                   "lines": lines, "engine": "tesseract-5.5 sauvola+contrast merge"}),
                       encoding="utf-8")
        return ident, leaf, "ok"
    except Exception as e:                       # noqa: BLE001 - recorded, the run goes on
        return ident, leaf, f"error {type(e).__name__}: {e}"[:300]


def tesseract(args) -> int:
    """Fresh tesseract for the volumes' staged pages: the word layer where IA's OCR failed."""
    jobs = [(ident, json.loads(p.read_text(encoding="utf-8"))["leaf"])
            for ident in args.ids.split(",") for p in sorted((BOOKS / ident).glob("*.json"))]
    bad = 0
    with multiprocessing.Pool(args.workers) as pool:
        for k, (ident, leaf, st) in enumerate(pool.imap_unordered(tess_page, jobs), 1):
            if st.startswith("error"):
                bad += 1
                print(f"  {ident} {leaf}: {st}", file=sys.stderr)
            if k % 50 == 0 or k == len(jobs):
                print(f"  {k}/{len(jobs)} pages", file=sys.stderr, flush=True)
    return 1 if bad else 0


def archive_file(ident: str) -> tuple:
    """(name, bytes) of the volume's page images on IA: <id>_jp2.zip, else <id>_jp2.tar (Trow
    1915 and 1917 have only the tar)."""
    import urllib.request
    files = json.loads(urllib.request.urlopen(f"https://archive.org/metadata/{ident}/files",
                                              timeout=120).read())["result"]
    sizes = {f["name"]: int(f.get("size") or 0) for f in files}
    for name in (f"{ident}_jp2.zip", f"{ident}_jp2.tar"):
        if name in sizes:
            return name, sizes[name]
    raise SystemExit(f"{ident}: IA lists no _jp2.zip or _jp2.tar")


def write_records(args) -> int:
    """What a Torch-side staging needs from the Mac, per volume: RECORDS/<id>.records.jsonl.gz, one
    `ia_page` record per listing page (the same records `pages` writes one file each), and
    RECORDS/volumes_<label>.tsv, the volumes with their image archive's name and size on IA for
    hpc/41_books_download.sh to fetch and hpc/42_books_tiles.sbatch to cut. A volume already
    re-OCR'd (its sidecar has a `reocr` block) is left out unless --redo."""
    tiers = json.loads(TIERS.read_text(encoding="utf-8"))["volumes"]
    ids = (sorted(i for i, v in tiers.items() if v["tier"] in args.tier.split(","))
           if args.tier else args.ids.split(","))
    RECORDS.mkdir(parents=True, exist_ok=True)
    rows = []
    for ident in ids:
        side = json.loads((HERE / "survey" / f"ia_{ident}.json").read_text(encoding="utf-8"))
        if side.get("reocr") and not args.redo:
            print(f"{ident}: re-OCR'd already ({side['reocr'].get('dumped')}) -- left out", file=sys.stderr)
            continue
        if column_method(ident) != "gutters":
            print(f"{ident}: a microfilm volume -- left out", file=sys.stderr)
            continue
        engine = ((side.get("catalog_says") or {}).get("ia") or {}).get("ocr") or "IA OCR"
        want = set(rv.pages(ident))
        out = RECORDS / f"{ident}.records.jsonl.gz"
        tmp = out.with_name(out.name + ".tmp")
        n = 0
        with gzip.open(ia_dump(ident), "rt", encoding="utf-8") as fh, \
                gzip.open(tmp, "wt", encoding="utf-8") as o:
            for line in fh:
                rec = json.loads(line)
                if rec["leaf"] in want:
                    o.write(json.dumps(ia_page(rec, engine), separators=(",", ":")) + "\n")
                    n += 1
        tmp.rename(out)
        name, size = archive_file(ident)
        rows.append((ident, tiers.get(ident, {}).get("tier", "-"), name, size, n))
        print(f"{ident}: {n} pages, {name} {size / 1e9:.2f} GB", file=sys.stderr)
    label = args.label or (args.tier or "ids").replace(",", "+")
    tsv = RECORDS / f"volumes_{label}.tsv"
    tsv.write_text("ident\ttier\tarchive\tbytes\tpages\n"
                   + "".join("\t".join(map(str, r)) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} volumes, {sum(r[4] for r in rows):,} pages, "
          f"{sum(r[3] for r in rows) / 1e9:.1f} GB of images -> {tsv.relative_to(REPO)}", file=sys.stderr)
    return 0


def status(args) -> int:
    for ident in args.ids.split(","):
        d = BOOKS / ident
        n = len(rv.pages(ident))
        recs = len(list(d.glob("*.json"))) if d.exists() else 0
        imgs = len(list(d.glob("*.jpg"))) if d.exists() else 0
        z = rv.zip_path(ident)
        print(f"{ident:32s} {recs:5d}/{n:5d} records  {imgs:5d} images  "
              f"zip {'%.2f GB' % (z.stat().st_size / 1e9) if z.exists() else '-'}")
    return 0


def _self_test() -> int:
    band = [[[20, 100 + 40 * i, 200, 130 + 40 * i, 2, "■^S2_"], [340, 100 + 40 * i, 500, 130 + 40 * i, 80, "Smith"],
             [510, 100 + 40 * i, 600, 130 + 40 * i, 80, "John"]] for i in range(8)]
    page = ia_page({"leaf": 45, "page_size": [2000, 3000], "lines": band}, "ABBYY FineReader 9.0")
    assert all(ws[0][5] == "Smith" for ws in page["lines"]), "a side banner's scraps are stripped"
    assert page["chars"] == 8 * len("SmithJohn") and page["engine"] == "ia-words (ABBYY FineReader 9.0)"
    plain = ia_page({"leaf": 1, "page_size": [2000, 3000], "lines": band[:2]}, "x")
    assert plain["lines"] == band[:2], "two scraps are no band: left as read"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["download", "pages", "tesseract", "records", "status"])
    ap.add_argument("--ids")
    ap.add_argument("--tier", help="records: every volume of these tiers (data_prep/run_tiers.json)")
    ap.add_argument("--label", help="records: the volumes TSV's name (default: the tier)")
    ap.add_argument("--redo", action="store_true", help="records: include volumes re-OCR'd already")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.cmd or not (args.ids or (args.cmd == "records" and args.tier)):
        ap.error("a command and --ids (or, for records, --tier) are required")
    if args.cmd == "download":
        args.tier = None
        return rv.download(args)
    if args.cmd == "pages":
        return write_pages(args)
    if args.cmd == "tesseract":
        return tesseract(args)
    if args.cmd == "records":
        return write_records(args)
    return status(args)


if __name__ == "__main__":
    sys.exit(main())
