#!/usr/bin/env python3
"""
Stage book-scan volumes for the LightOn re-OCR over IA's own words: no tesseract (PIPELINE #27).

    python3 data_prep/reocr_books.py download --ids a,b        # each volume's _jp2.zip, whole
    python3 data_prep/reocr_books.py pages --ids a,b [--workers 6]   # -> data/reocr_books/<id>/
    python3 data_prep/reocr_books.py tesseract --ids a,b         # -> data/reocr_books_tess/<id>/
    python3 data_prep/reocr_books.py records --tier abbyy8-damaged  # -> data/reocr_books_records/ (Torch)
    python3 data_prep/reocr_books.py coverage --tier abbyy8-damaged   # whose IA OCR failed, page by page
    python3 data_prep/reocr_books.py import --ids a,b [--root data/reocr_tiers/{id}]  # answers -> survey
    python3 data_prep/reocr_books.py facts --ids a,b --against HEAD  # what an import moved
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


def volumes_of(args) -> list:
    if args.ids:
        return args.ids.split(",")
    tiers = json.loads(TIERS.read_text(encoding="utf-8"))["volumes"]
    return sorted(i for i, v in tiers.items() if v["tier"] in args.tier.split(","))


def column_count(ident: str) -> int:
    side = json.loads((HERE / "survey" / f"ia_{ident}.json").read_text(encoding="utf-8"))
    try:
        return int(((side.get("catalog_says") or {}).get("csv") or {}).get("column_count") or 2)
    except ValueError:
        return 2


def page_coverage(rec: dict, ncol: int) -> float:
    """How much of a page IA's OCR read: its lines (cut at the columns) over what the text area
    holds, columns x text height / (1.3 x the median word height). ~1.0 on a page IA read whole
    (Doggett 1845 1.04, 1876BPL 1.10, Longworth 1826 1.05); Trow 1907 p3, whose OCR failed page by
    page, 0.42. 0.0 for a page with under 20 words."""
    lines = rv.column_lines(rec["lines"], rec["page_size"], method="gutters", n=ncol) if rec["lines"] else []
    words = [w for ws in lines for w in ws]
    if len(words) < 20:
        return 0.0
    hs = sorted(w[3] - w[1] for w in words)
    ys = sorted((w[1] + w[3]) / 2 for w in words)
    height = ys[-1 - len(ys) // 50] - ys[len(ys) // 50]
    cap = ncol * height / (1.3 * hs[len(hs) // 2])
    return min(2.0, len(lines) / cap) if cap > 0 else 0.0


def _coverage_one(ident: str) -> tuple:
    want, ncol, out = set(rv.pages(ident)), column_count(ident), {}
    with gzip.open(ia_dump(ident), "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["leaf"] in want:
                out[rec["leaf"]] = round(page_coverage(rec, ncol), 3)
    return ident, out


def coverage(args) -> int:
    """Which volumes' IA OCR failed page by page, before any GPU time is spent: per volume, the
    median page coverage, its 10th percentile, and the pages under 0.5. A volume with a median
    under 0.8 or a tenth of its pages under 0.5 will want the tesseract layer at import (Trow 1907
    p3: model-only lines 69,270 -> 2,621 with it). Measured 2026-10-21 over the three tiers: 3,028
    of 73,826 pages under 0.5, most in six Trow parts of 1907-1914 (PIPELINE #27)."""
    ids, result = volumes_of(args), {}
    with multiprocessing.Pool(args.workers) as pool:
        for ident, cov in pool.imap_unordered(_coverage_one, ids):
            result[ident] = cov
    print(f"{'volume':32s} {'pages':>6} {'median':>6} {'p10':>5} {'<0.5':>5}")
    for ident in sorted(result):
        c = sorted(result[ident].values())
        if not c:
            print(f"{ident:32s} {0:6d}")
            continue
        low = sum(x < 0.5 for x in c)
        flag = "  <- tesseract layer" if c[len(c) // 2] < 0.8 or low > 0.1 * len(c) else ""
        print(f"{ident:32s} {len(c):6d} {c[len(c) // 2]:6.2f} {c[len(c) // 10]:5.2f} {low:5d}{flag}")
    if args.json:
        Path(args.json).write_text(json.dumps(result), encoding="utf-8")
    return 0


def facts_of(doc: dict) -> dict:
    """The survey facts a re-OCR moves, from a volume's sidecar."""
    h = ((doc.get("harvest") or {}).get("filtered")) or {}
    listing, bs, ro = doc.get("listing") or {}, doc.get("book_says") or {}, doc.get("reocr") or {}
    snc = bs.get("stated_name_count")
    snc = snc.get("value") if isinstance(snc, dict) else snc
    scoped = ((doc.get("scope") or {}).get("kept_by_section") or {}).get("listing")
    model, only = ro.get("lines_model", 0), ro.get("lines_model-only", 0)
    return {"kept": h.get("candidates"), "joins": h.get("wrap_joins"),
            "indent": (h.get("wrap_calibration") or {}).get("indent_ratio"),
            "listing": f"{listing.get('start_leaf')}-{listing.get('end_leaf')}",
            "scoped": scoped, "non_entry": len((doc.get("non_entry_pages") or {}).get("leaves", [])),
            "printed": snc, "per_name": round(scoped / snc, 3) if scoped and snc else None,
            "layer": ro.get("engine", "IA OCR").split(" + ")[0],
            "model_only": round(only / (model + only), 3) if model + only else None}


def facts(args) -> int:
    """Per volume, the survey facts now and, with --against REV, at that git revision (the
    sidecars before an import: commit them first). The numbers to read after an import: scoped
    lines and per printed name, the share of the model's lines with no OCR words under them
    (model_only: over ~0.1 the page layer failed, see `coverage`), and listing bounds, which a
    re-OCR should not move."""
    import subprocess
    for ident in volumes_of(args):
        rel = f"data_prep/survey/ia_{ident}.json"
        now = facts_of(json.loads((REPO / rel).read_text(encoding="utf-8")))
        if args.against:
            got = subprocess.run(["git", "show", f"{args.against}:{rel}"], cwd=REPO,
                                 capture_output=True, text=True)
            was = facts_of(json.loads(got.stdout)) if got.returncode == 0 else {}
            moved = {k: f"{was.get(k)} -> {v}" for k, v in now.items() if was.get(k) != v}
            print(f"{ident:32s} " + ("; ".join(f"{k} {m}" for k, m in moved.items()) or "unchanged"))
        else:
            print(f"{ident:32s} " + "; ".join(f"{k} {v}" for k, v in now.items()))
    return 0


def import_volumes(args) -> int:
    """The whole import of re-OCR'd book scans, as done for the canary (PIPELINE #27): per volume
    `reocr_pair.py dump` from its answers (--root, `{id}` filled in; the page layer from --page-dir,
    the tesseract layer from --alt-page-dir where it has the page), then `survey_harvest.py
    --rederive`, `survey_derive.py` bounds/pages/sections/scope, and the non-entry pages
    (`survey_adleaves.py features --merge`, `inventory --write`). Then `facts --against HEAD`, and
    the volumes whose model-only share says they want the tesseract layer. Commit the sidecars
    before running it, so HEAD is the before.

    The dumps run --workers at a time (PIPELINE #31: one process on one core took the damaged
    tier's import 4.5 h). Each writes only its own volume's dump and sidecar `reocr` block, so they
    cannot collide; each one's output is printed whole when it finishes. Everything after the dumps
    runs once over all the volumes, as before: `features --merge` and `inventory --write` write
    corpus-wide files and must never run side by side."""
    import subprocess
    from concurrent.futures import ThreadPoolExecutor, as_completed
    py, ids = sys.executable, []
    for ident in volumes_of(args):
        if (REPO / args.root.format(id=ident) / "boxes.json").exists():
            ids.append(ident)
        else:
            print(f"{ident}: no answers under {args.root.format(id=ident)} -- left out", file=sys.stderr)
    if not ids:
        return 1

    def run(*cmd):
        print("$ " + " ".join(cmd[1:]), file=sys.stderr, flush=True)
        subprocess.run(list(cmd), cwd=REPO, check=True)
    def dump_one(ident):
        root = args.root.format(id=ident)
        cmd = [py, "data_prep/reocr_pair.py", "dump", args.slug, "--root", root,
               "--page-dir", args.page_dir, "--ids", ident]
        if (REPO / args.alt_page_dir / ident).exists():
            cmd += ["--alt-page-dir", args.alt_page_dir]
        if args.prefer:
            cmd += ["--prefer", args.prefer]
        return cmd, subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    failed = []
    with ThreadPoolExecutor(max(1, args.workers)) as pool:
        for fut in as_completed([pool.submit(dump_one, ident) for ident in ids]):
            cmd, done = fut.result()
            print("$ " + " ".join(cmd[1:]), file=sys.stderr)
            sys.stderr.write(done.stdout + done.stderr)
            sys.stderr.flush()
            if done.returncode:
                failed.append(cmd[cmd.index("--ids") + 1])
    if failed:
        raise SystemExit(f"dump failed for {', '.join(failed)}: nothing after the dumps was run")
    joined = ",".join(ids)
    run(py, "data_prep/survey_harvest.py", "--rederive", "--ids", joined)
    for step in ("bounds", "pages", "sections", "scope"):
        run(py, "data_prep/survey_derive.py", step, "--ids", joined)
    run(py, "data_prep/survey_adleaves.py", "features", "--ids", joined, "--merge")
    run(py, "data_prep/survey_adleaves.py", "inventory", "--write")
    print("\n--- facts against HEAD (before the import, if the sidecars were committed)")
    facts(argparse.Namespace(ids=joined, tier=None, against="HEAD"))
    want = []
    for ident in ids:
        mo = facts_of(json.loads((HERE / "survey" / f"ia_{ident}.json").read_text(encoding="utf-8")))["model_only"]
        if mo is not None and mo > MODEL_ONLY_FLAG:
            want.append((ident, mo))
    if want:
        print(f"\nmodel-only over {MODEL_ONLY_FLAG:.0%} -- these want the tesseract layer "
              "(download, pages, tesseract, then import them again):")
        for ident, mo in want:
            print(f"  {ident:32s} {mo:.1%}")
    return 0


MODEL_ONLY_FLAG = 0.10      # the canary's good volumes ran 1-3%; Trow 1907 p3 over IA's words 56%


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["download", "pages", "tesseract", "records", "coverage",
                                               "import", "facts", "status"])
    ap.add_argument("--ids")
    ap.add_argument("--tier", help="records: every volume of these tiers (data_prep/run_tiers.json)")
    ap.add_argument("--label", help="records: the volumes TSV's name (default: the tier)")
    ap.add_argument("--redo", action="store_true", help="records: include volumes re-OCR'd already")
    ap.add_argument("--json", help="coverage: also write {volume: {leaf: coverage}} here")
    ap.add_argument("--against", help="facts: compare with the sidecars at this git revision")
    ap.add_argument("--root", default="data/reocr_tiers/{id}",
                    help="import: each volume's answers ({id} filled in; the canary's: data/reocr_books_halves)")
    ap.add_argument("--page-dir", default="data/reocr_books_records", help="import: the page layer")
    ap.add_argument("--alt-page-dir", default="data/reocr_books_tess",
                    help="import: the tesseract layer, used for a volume that has it")
    ap.add_argument("--slug", default="lightonocr-3-1b-greedy-vllm", help="import: the answers' slug")
    ap.add_argument("--prefer", help="import: a second slug a tile takes where it has an answer "
                                     "(the table re-read, PIPELINE #32 (b) 5c: lightonocr-3-1b-greedy-vllm-notables)")
    ap.add_argument("--workers", type=int, default=6,
                    help="pages/tesseract: processes; import: volumes dumped at a time")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.cmd or not (args.ids or (args.cmd in ("records", "coverage", "facts", "import") and args.tier)):
        ap.error("a command and --ids (or, for records/coverage/facts/import, --tier) are required")
    if args.cmd == "coverage":
        return coverage(args)
    if args.cmd == "facts":
        return facts(args)
    if args.cmd == "import":
        return import_volumes(args)
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
