#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Re-OCR the deferred volumes' listing pages: tesseract 5.5, two image preparations merged line
by line (reocr_bench.py's winning recipe), cached per page, then written as a word dump the
survey harvest can derive from.

    python3 data_prep/reocr_volumes.py run [--tier defer] [--ids a,b] [--workers 6] [--limit N]
    python3 data_prep/reocr_volumes.py download [--tier defer] [--ids a,b]  # whole jp2 zips first
    python3 data_prep/reocr_volumes.py status
    python3 data_prep/reocr_volumes.py --self-test

WHY (2026-10-06, docs/PIPELINE.md #27). On 48 microfilm pages with a book-scan twin, IA's
tesseract reproduces 54% of the book scan's lines; tesseract 5.5 on a Sauvola-binarized image
merged with a contrast-enhanced one (the higher-confidence reading of each line) reproduces 92%,
reads 44% of gold lines exactly against IA's 24%, keeps 80% of abbreviations, and keeps word
boxes. The 39 `defer` volumes of data_prep/run_tiers.json (38 BPL microfilm and Brooklyn 1912
p3) hold 7,947 pages with text in residential runs.

`run`, per page (resumable: a page with a cache file is skipped):
    data/reocr/<id>/<id>_<leaf>.jpg    the IIIF image (kept: Churro's column crops read it)
    data/reocr/<id>/<id>_<leaf>.json   {"leaf", "page_size", "chars", "lines": [[word...]...],
                                        "columns": [[x0, x1], ...]} -- a word-dump record, words
                                        [x0, y0, x1, y1, conf, text], plus the page's columns
                                        by the rule of the day (readers recompute them: the
                                        rule changed 2026-10-06, see `columns`)
Tesseract's lines run across a gutter where two columns' baselines meet; `column_lines` cuts
them at the columns before anything reads them as entries.
Pages are pooled across volumes; tesseract runs single-threaded per process (OMP_THREAD_LIMIT).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import multiprocessing
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIDECARS = HERE / "survey"
OCR = REPO / "data" / "survey_ocr"
WORK = REPO / "data" / "reocr"
ZIPS = REPO / "data" / "reocr_zips"
TIERS = HERE / "run_tiers.json"
sys.path.insert(0, str(HERE))

from reocr_bench import PAIR_OVERLAP, PAIR_TEXT, TESSERACT, _overlap, prepare  # noqa: E402
from survey_twins import norm  # noqa: E402

IIIF = "https://iiif.archive.org/iiif"
MIN_CHARS = 50          # a dump leaf with fewer characters is blank or a film frame
COLUMN_GAP = 0.08       # column starts at least this far apart (share of page width)
COLUMN_SHARE = 0.04     # a column holds at least this share of the page's lines...
COLUMN_MIN = 8          # ...and at least this many
COLUMN_WIDTH = 0.12     # and is at least this wide
COLUMN_CROSS = 0.3      # a boundary the previous column's lines run across this often is not one
COLUMN_WORDS = 2        # a column's lines hold at least this many words (median)
GUTTER_H = 2.5          # a gap in a tesseract line wider than this many word heights...
GUTTER_W = 0.02         # ...and this share of the page width splits the line in two


def pages(ident: str) -> list:
    """The volume's leaves with text inside its residential runs, from the IA word dump."""
    d = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    res = {leaf for r in (d.get("sections") or {}).get("runs", []) if r.get("residential")
           for leaf in range(r["start_leaf"], r["end_leaf"] + 1)}
    out = []
    with gzip.open(OCR / f"{ident}_words.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            m = re.search(r'"leaf":\s*(\d+).*?"chars":\s*(\d+)', line[:200])
            if m and int(m.group(1)) in res and int(m.group(2)) >= MIN_CHARS:
                out.append(int(m.group(1)))
    return out


def zip_path(ident: str) -> Path:
    return ZIPS / f"{ident}_jp2.zip"


def jp2_to_jpeg(data: bytes) -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue()


def fetch(ident: str, leaf: int, dst: Path, tries: int = 3) -> None:
    """The page at full size: from the volume's `_jp2.zip` when `download` has fetched it, else
    IIIF, else that zip's one member over HTTP -- the same pixels each way. IIIF answers 500 or
    504 for some leaves however often it is asked (2026-10-06: brooklynnewyorkc19123broo leaf 121,
    micro_IABROOKLYN_0039 leaf 11, micro_IABROOKLYN_0029 leaf 127 after 62 s), and a worker
    waiting out its retries holds a slot: the run fell from ~670 pages/h to ~50."""
    if zip_path(ident).exists():
        import zipfile
        with zipfile.ZipFile(zip_path(ident)) as zf:
            data = jp2_to_jpeg(zf.read(f"{ident}_jp2/{ident}_{leaf:04d}.jp2"))
        tmp = dst.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.rename(dst)
        return
    urls = [f"{IIIF}/{ident}${leaf}/full/max/0/default.jpg",
            f"https://archive.org/download/{ident}/{ident}_jp2.zip/{ident}_jp2%2F{ident}_{leaf:04d}.jp2"]
    last = None
    for url in urls:
        for k in range(tries):
            try:
                data = urllib.request.urlopen(url, timeout=180).read()
                if url.endswith(".jp2"):          # store as the JPEG the rest of the job reads
                    data = jp2_to_jpeg(data)
                tmp = dst.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.rename(dst)
                return
            except Exception as e:                       # noqa: BLE001 - retried, then next source
                last = e
                time.sleep(5 * (k + 1))
    raise last


def tess_words(img, variant: str):
    """[(words, box, mean conf)] per tesseract line, words [x0, y0, x1, y1, conf, text] in the
    original image's pixels."""
    prepared, scale = prepare(img, variant)
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        prepared.save(tmp.name)
        out = subprocess.run([TESSERACT, tmp.name, "stdout", "--psm", "3", "--dpi", "300",
                              "-l", "eng", "tsv"], capture_output=True, text=True,
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
    lines = collections.OrderedDict()
    for row in out.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        x, y, w, h = (round(int(v) / scale) for v in f[6:10])
        conf = max(0, round(float(f[10])))
        lines.setdefault((int(f[2]), int(f[3]), int(f[4])), []).append([x, y, x + w, y + h, conf,
                                                                         f[11]])
    out_lines = []
    for ws in lines.values():
        box = [min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws),
               max(w[3] for w in ws)]
        out_lines.append((ws, box, sum(w[4] for w in ws) / len(ws)))
    return out_lines


def merge_words(base: list, other: list) -> list:
    """reocr_bench.merge_page at word level: base's lines in order; where `other` read the same
    printed line (boxes overlapping, texts alike), the higher-confidence reading's words."""
    import difflib
    used, out = set(), []
    for ws, box, conf in base:
        text = norm(" ".join(w[5] for w in ws))
        best, best_r = None, PAIR_TEXT
        for j, (ows, obox, _c) in enumerate(other):
            if j in used or _overlap(box, obox) < PAIR_OVERLAP:
                continue
            r = difflib.SequenceMatcher(None, text, norm(" ".join(w[5] for w in ows)),
                                        autojunk=False).ratio()
            if r >= best_r:
                best, best_r = j, r
        if best is not None:
            used.add(best)
            if other[best][2] > conf:
                ws = other[best][0]
        out.append(ws)
    return out


def segments(lines: list, width: int) -> list:
    """Each tesseract line cut at its wide gaps (GUTTER_H word heights and GUTTER_W of the page).
    Tesseract reads straight across a narrow gutter wherever two columns' baselines line up
    (Brooklyn 1912 p3 leaf 113: half its "lines" are a left-column entry and a right-column one),
    so the right column's entries start at the left column's margin and leave no peak of their
    own. Word spaces there are ~1 word height; the gutter gaps 3 to 8+."""
    hs = sorted(w[3] - w[1] for ws in lines for w in ws)
    gap = max(GUTTER_H * (hs[len(hs) // 2] if hs else 0), GUTTER_W * width)
    out = []
    for ws in lines:
        if not ws:
            continue
        ws = sorted(ws, key=lambda w: w[0])
        cur = [ws[0]]
        for w in ws[1:]:
            if w[0] - max(c[2] for c in cur) > gap:
                out.append(cur)
                cur = []
            cur.append(w)
        out.append(cur)
    return out


def columns(lines: list, width: int) -> list:
    """[[x0, x1]] of the page's text columns, from the peaks in where its line segments start.

    A column is a peak (1%-of-width bins) holding at least COLUMN_SHARE of the page's segments
    and COLUMN_MIN of them; peaks closer than COLUMN_GAP of the width are one column (a runover's
    indent is 2-4% of the page, a six-column page's columns ~17% apart). A first draft looked for
    gaps between sorted line starts instead, and a few lines starting mid-page bridged a
    two-column 1858 page into one (micro_IABROOKLYN_0039 leaf 12). Segments narrower than 4% of
    the page (banner crumbs) do not vote. Two peaks are not columns (Brooklyn 1912 p3, measured
    on 171 pages; real columns cross 2-14% and hold 3-7 words):
      - one the previous column's segments run across (> COLUMN_CROSS of them): a smudge down
        the column that breaks half its lines at the same x (leaf 201: 61 of 114);
      - one whose segments hold a median of under COLUMN_WORDS words: a rotated side banner,
        which tesseract reads as a stack of one-word lines (leaf 413).
    A column runs to where the next begins; the last to the right end of the segments starting
    at its margin, which leaves out a banner beside it that made no peak (leaf 113)."""
    segs = [(min(w[0] for w in s), max(w[2] for w in s), len(s)) for s in segments(lines, width)]
    segs = [s for s in segs if s[1] - s[0] > 0.04 * width]
    if not segs:
        return [[0, width]]
    bin_w = 0.01 * width
    hist = collections.Counter(int(s[0] // bin_w) for s in segs)
    floor = max(COLUMN_MIN, COLUMN_SHARE * len(segs))
    clusters = []
    for b in sorted(b for b, c in hist.items() if c >= floor):
        if clusters and (b - clusters[-1][-1]) * bin_w < COLUMN_GAP * width:
            clusters[-1].append(b)
        else:
            clusters.append([b])
    if not clusters:
        return [[min(s[0] for s in segs), max(s[1] for s in segs)]]
    peaks = [min(s[0] for s in segs if int(s[0] // bin_w) == c[0]) for c in clusters]
    x0s = []
    for k, x in enumerate(peaks):
        nxt = peaks[k + 1] if k + 1 < len(peaks) else float("inf")
        words = sorted(s[2] for s in segs if x <= s[0] < nxt)
        if words[len(words) // 2] < COLUMN_WORDS:
            continue
        if x0s:
            prev = [s for s in segs if x0s[-1] <= s[0] < x]
            if sum(1 for s in prev if s[1] > x + bin_w) > COLUMN_CROSS * len(prev):
                continue
        x0s.append(x)
    if not x0s:
        return [[min(s[0] for s in segs), max(s[1] for s in segs)]]
    last = x0s[-1]
    right = max(s[1] for s in segs if last <= s[0] < last + COLUMN_GAP * width)
    cols = [[x, x0s[k + 1] if k + 1 < len(x0s) else right] for k, x in enumerate(x0s)]
    # a side banner set as lines makes a narrow "column" at the page edge (Brooklyn 1912 p3
    # leaf 117: 11% of the width); a real one is ~16% even at six to the page
    return [c for c in cols if c[1] - c[0] >= COLUMN_WIDTH * width] or cols


def column_lines(lines: list, cols: list) -> list:
    """The page's lines in reading order, a line tesseract read across a gutter cut in two: each
    word to the column its middle falls in (one outside every column goes to the nearest), then
    column by column, top to bottom. The word dump written from the cache, and the hybrid's
    line boxes, need one entry per line."""
    def col(w):
        mid = (w[0] + w[2]) / 2
        return min(range(len(cols)), key=lambda k: 0 if cols[k][0] <= mid < cols[k][1]
                   else min(abs(mid - cols[k][0]), abs(mid - cols[k][1])))
    out = []
    for ws in lines:
        parts = collections.defaultdict(list)
        for w in ws:
            parts[col(w)].append(w)
        out += [(k, ws_k) for k, ws_k in parts.items()]
    out.sort(key=lambda kw: (kw[0], min(w[1] for w in kw[1])))
    return [ws for _k, ws in out]


def page_job(job):
    """Download, OCR twice, merge, cache. Returns (ident, leaf, status)."""
    from PIL import Image
    ident, leaf = job
    d = WORK / ident
    d.mkdir(parents=True, exist_ok=True)
    img_path, out_path = d / f"{ident}_{leaf:04d}.jpg", d / f"{ident}_{leaf:04d}.json"
    if out_path.exists():
        return ident, leaf, "cached"
    try:
        if not img_path.exists():
            fetch(ident, leaf, img_path)
        img = Image.open(img_path)
        lines = merge_words(tess_words(img, "sauvola"), tess_words(img, "contrast"))
        rec = {"leaf": leaf, "page_size": list(img.size),
               "chars": sum(len(w[5]) for ws in lines for w in ws), "lines": lines,
               "columns": columns(lines, img.size[0]), "engine": "tesseract-5.5 sauvola+contrast merge"}
        out_path.write_text(json.dumps(rec), encoding="utf-8")
        (d / f"{ident}_{leaf:04d}.error").unlink(missing_ok=True)
        return ident, leaf, "ok"
    except Exception as e:                               # noqa: BLE001 - recorded, run goes on
        (d / f"{ident}_{leaf:04d}.error").write_text(repr(e)[:500], encoding="utf-8")
        return ident, leaf, f"error {type(e).__name__}"


def volumes(args) -> list:
    if args.ids:
        return args.ids.split(",")
    tiers = json.loads(TIERS.read_text(encoding="utf-8"))["volumes"]
    return sorted(i for i, v in tiers.items() if v["tier"] in args.tier.split(","))


def run(args) -> int:
    jobs = [(i, leaf) for i in volumes(args) for leaf in pages(i)]
    todo = [j for j in jobs if not (WORK / j[0] / f"{j[0]}_{j[1]:04d}.json").exists()]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(jobs)} pages, {len(todo)} to do, {args.workers} workers", flush=True)
    t0, counts = time.time(), collections.Counter()
    with multiprocessing.Pool(args.workers) as pool:
        for n, (ident, leaf, status) in enumerate(pool.imap_unordered(page_job, todo), 1):
            counts[status.split()[0]] += 1
            if status.startswith("error"):
                print(f"  {ident} {leaf}: {status}", flush=True)
            if n % 50 == 0 or n == len(todo):
                rate = n / (time.time() - t0)
                print(f"  {n}/{len(todo)} {dict(counts)}  {rate * 3600:.0f} pages/h, "
                      f"~{(len(todo) - n) / rate / 3600:.1f} h left", flush=True)
    return 0


def download(args) -> int:
    """Each volume's `<id>_jp2.zip` (the original JPEG 2000s IIIF renders from) whole, in run
    order, for volumes with pages left: curl resumes a broken transfer (-C -), the size is checked
    against the item's file list, and only a complete zip is renamed into place, so `fetch` never
    reads a partial one. A volume's zip can go once its pages are cached."""
    ZIPS.mkdir(parents=True, exist_ok=True)
    for ident in volumes(args):
        dst = zip_path(ident)
        left = [leaf for leaf in pages(ident)
                if not (WORK / ident / f"{ident}_{leaf:04d}.json").exists()]
        if dst.exists() or not left:
            continue
        name = f"{ident}_jp2.zip"
        files = json.loads(urllib.request.urlopen(f"https://archive.org/metadata/{ident}/files",
                                                  timeout=120).read())["result"]
        size = next(int(f["size"]) for f in files if f["name"] == name)
        part = dst.with_name(name + ".part")
        t0 = time.time()
        r = subprocess.run(["curl", "-sSL", "--retry", "5", "--retry-delay", "10", "-C", "-",
                            "-o", str(part), f"https://archive.org/download/{ident}/{name}"])
        got = part.stat().st_size if part.exists() else 0
        if r.returncode or got != size:
            print(f"{ident}: curl exit {r.returncode}, {got}/{size} bytes; rerun to resume",
                  flush=True)
            continue
        part.rename(dst)
        print(f"{ident}: {size / 1e9:.2f} GB in {time.time() - t0:.0f}s, {len(left)} pages left",
              flush=True)
    return 0


def status(args) -> int:
    for i in volumes(args):
        n = len(pages(i))
        done = len(list((WORK / i).glob("*.json"))) if (WORK / i).exists() else 0
        err = len(list((WORK / i).glob("*.error"))) if (WORK / i).exists() else 0
        print(f"{i:28s} {done:4d}/{n:4d} pages{f'  {err} errors' if err else ''}")
    return 0


def _self_test() -> int:
    w = 2000

    def ln(x0, x1, y, n=4):                  # n words spread over x0..x1, 30 px high
        step = (x1 - x0) / n
        return [[round(x0 + k * step), y, round(x0 + (k + 1) * step) - 10, y + 30, 90, "w"]
                for k in range(n)]
    one = [ln(100, 900, y) for y in range(0, 900, 40)]
    assert columns(one, w) == [[100, 890]]
    right = [ln(1100, 1900, y) for y in range(0, 900, 40)]
    two = one + right
    assert columns(two, w) == [[100, 1100], [1100, 1890]]
    bridged = two + [ln(x, x + 400, 2000) for x in (300, 500, 700, 900)]
    assert len(columns(bridged, w)) == 2, "a few lines starting mid-page do not merge columns"
    indented = one + [ln(160, 900, y + 20) for y in range(0, 900, 80)]
    assert len(columns(indented, w)) == 1, "an indented runover is not a column"
    six = [ln(60 + 330 * c, 60 + 330 * c + 280, y, 2) for c in range(6) for y in range(0, 1200, 40)]
    assert len(columns(six, w)) == 6, "six columns ~17% apart"
    merged = [a + b for a, b in zip(one, right)]
    assert columns(merged, w) == [[100, 1100], [1100, 1890]], "a line read across the gutter"
    smudge = one + [ln(1100, 1300, y, 2) + ln(1400, 1900, y) if y % 80 == 0 else ln(1100, 1900, y)
                    for y in range(0, 900, 40)]
    assert len(columns(smudge, w)) == 2, "a column broken at one x is still one column"
    left = [ln(100, 900, y) for y in range(0, 900, 40)]
    mid = [ln(1000, 1600, y) for y in range(0, 900, 40)]
    banner = [[[1700, y, 1800, y + 60, 40, "X"]] for y in range(0, 900, 70)]
    assert columns(left + mid + banner, w) == [[100, 1000], [1000, 1590]], "a banner is no column"
    assert columns(left + mid + banner[:3], w) == [[100, 1000], [1000, 1590]], "nor runs to one"
    split = column_lines(merged[:2], [[100, 1100], [1100, 1890]])
    assert [ws[0][0] for ws in split] == [100, 100, 1100, 1100], "cut, then column by column"
    base = [([[0, 0, 100, 20, 60, "njohnson"]], [0, 0, 100, 20], 60.0)]
    other = [([[0, 0, 40, 20, 90, "n"], [45, 0, 100, 20, 90, "johnson"]], [0, 0, 100, 20], 90.0)]
    assert merge_words(base, other)[0][0][5] == "n", "the confident reading's words win"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["run", "download", "status"])
    ap.add_argument("--tier", default="defer")
    ap.add_argument("--ids")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "run":
        return run(args)
    if args.cmd == "download":
        return download(args)
    if args.cmd == "status":
        return status(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
