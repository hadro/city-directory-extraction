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
import math
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
COLUMN_CROSS = 0.35     # a boundary with no gap freer of words than this is not one
COLUMN_WORDS = 2        # a column's lines hold at least this many words (median)
GUTTER_W = 0.02         # a gap in a tesseract line wider than this share of the page splits it
SKEW_MIN = 0.5          # degrees: a page tilted less is read as it lies...
SKEW_AGREE = 0.75       # ...as is one whose lines and left margin disagree on its tilt by this


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
    """Each tesseract line cut at its gaps wider than GUTTER_W of the page. Tesseract reads
    straight across a narrow gutter wherever two columns' baselines line up (Brooklyn 1912 p3
    leaf 113: half its "lines" are a left-column entry and a right-column one), so the right
    column's entries start at the left column's margin and leave no peak of their own. A first
    rule also required 2.5 word heights, which is ~2% on a clean page but not on film, where
    tesseract's boxes can span two rows (micro_IABROOKLYN_0039 leaf 94: median word 115 px
    against 60) and the gutter stayed shut: 90 of 0039's 454 pages read as one column, 34 now
    (the rest mostly full-page advertisements)."""
    gap = GUTTER_W * width
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
    the page (banner crumbs) do not vote. Two peaks are not columns:
      - one with no gutter before it: somewhere from 5% of the page left of the peak to 1% right
        of it, a gutter has a position few words lie over. A smudge down a column breaks half
        its lines at one x, and the other half's words cover every position near it (Brooklyn
        1912 p3 leaf 201: at least 51% of the column's lines; real gutters 3-21%, skewed film
        included). Counting the previous column's segments that run past the peak instead
        rejected real gutters on film, where tesseract joins an entry ending near the rule to
        the next column's line (0039 leaf 41: 61%);
      - one whose segments hold a median of under COLUMN_WORDS words: a rotated side banner,
        which tesseract reads as a stack of one-word lines (leaf 413).
    A column runs to where the next begins; the last to the right end of the segments starting
    at its margin, which leaves out a banner beside it that made no peak (leaf 113). A filmed
    two-page spread comes out as each page's columns, left page first."""
    words_all = [w for ws in lines for w in ws]
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
            n = sum(1 for s in segs if x0s[-1] <= s[0] < x)
            step = max(1, int(0.0025 * width))
            fewest = min(sum(1 for w in words_all if w[0] < g < w[2])
                         for g in range(int(x - 0.05 * width), int(x + bin_w) + 1, step))
            if fewest > COLUMN_CROSS * n:
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


GUTTER_TOL = 0.15       # gutters: a valley whose deepest point is crossed by under this share
GUTTER_REGION = 0.35    # ...of a column's density, in a stretch under this share of it
GUTTER_SNAP = 0.2       # with a known count: a gutter within this share of a column's width
GUTTER_BODY = 0.84      # ...counted on the middle of the text's height, off the top and bottom ads
GUTTER_MIN = 0.8        # ...at least this many median character widths wide
GUTTER_LOOK = 12        # the words ending this many character widths left of it are its left side
GUTTER_STRAIGHT = 2.0   # a left side whose words start AND end within this many characters is a
                        # stripe (repeated surname, `"` dittos), and the band after it no gutter
OUTER_REACH = 0.25      # the outer columns reach the ends of their lines, at most this share of a
                        # column's width past the text's 1st/99th-percentile edges...
OUTER_SLACK = (1, 6)    # ...and this many characters past them, left and right: OCR misses faint
                        # ends (ABBYY boxed Longworth 1826's "Whitehall" as "Whit*", 90 px short)
OUTER_LEFT = 3          # on the left, at most this many characters past the 1st percentile: a
                        # hanging mark is 1-2, and further out is the verso's show-through


def gutter_columns(lines: list, width: int, n: int = 0) -> list:
    """[[x0, x1]] of a book-scan page's text columns, from its gutters (2026-10-15). With n,
    n columns: each gutter where the fewest words cross within GUTTER_SNAP of a column's width of
    its equal-width place, so long as each is as clear as a gutter; a page laid out otherwise
    keeps its own. A directory keeps one column count on its listing pages, so staging takes n
    as the volume's most common detected count (reocr_columns.py).

    `columns` finds a column where many line segments start, and drops a peak whose segments
    are mostly one word. On dense book scans both misfire. Manhattan & Bronx 1931 prints the
    surname on every line, so a column of "Fitzgerald" is one word per line, dropped as a
    banner, and the given names after it read as the column's start: the tiles cut the surnames
    off. Polk 1933 splits at its column of `"` dittos the same way.

    Without n, a gutter is a valley in how many words cross each x, counted on the body of the
    page (GUTTER_BODY of the text's height: an advertisement across the top or bottom crosses
    every gutter). It is a stretch under GUTTER_REGION of the columns' density, at least
    GUTTER_MIN characters wide, whose clearest point is under GUTTER_TOL of it: a narrow gutter
    is never empty, since long entries reach into it and tesseract reads its printed rule as "|"
    (Trow 1913: 4-11 crossings over 70 px, against 53 in a column). A gutter beside a sparse
    column can run on into the page's edge (Polk 1925's last, an advertisement and short
    entries) and be lost with the margin; the volume's count catches it. The white strip
    after a stripe of identical words is such a valley too, but its left side is that stripe:
    words that start and end at the same x on every line (GUTTER_STRAIGHT). A gutter's left side
    is the ends of entries, which end at different x (or, justified, at least start at different
    x). On the pilot's 63 book-scan pages this found the right count on 60."""
    words = [w for ws in lines for w in ws if w[2] > w[0]]
    if not words:
        return [[0, width]]
    hs = sorted(w[3] - w[1] for w in words)
    wh = hs[len(hs) // 2]
    body = [w for w in words if w[3] - w[1] < 3 * wh]
    cws = sorted((w[2] - w[0]) / len(w[5]) for w in body if len(w[5]) >= 3)
    if not cws:
        return [[0, width]]
    cw = cws[len(cws) // 2]
    xs0, xs1 = sorted(w[0] for w in body), sorted(w[2] for w in body)
    left, right = int(xs0[len(xs0) // 100]), int(xs1[-1 - len(xs1) // 100])
    ys = sorted((w[1] + w[3]) / 2 for w in body)
    top, bot = ys[len(ys) // 100], ys[-1 - len(ys) // 100]
    margin = (1 - GUTTER_BODY) / 2 * (bot - top)
    mid = [w for w in body if top + margin <= (w[1] + w[3]) / 2 <= bot - margin]
    diff = [0] * (width + 2)
    for w in mid:
        a, b = max(0, int(w[0]) + 1), min(width + 1, int(w[2]))
        if b > a:
            diff[a] += 1
            diff[b] -= 1
    cross, running = [], 0
    for x in range(width + 1):
        running += diff[x]
        cross.append(running)
    if right <= left:
        return [[0, width]]

    def clearest(a, b):
        least = min(cross[a:b])
        plateau = [x for x in range(a, b) if cross[x] == least]
        return plateau[len(plateau) // 2]

    def outer(cols):
        """The outer columns out to the ends of their lines. `left` and `right` are the text's
        1st and 99th percentiles, which hold against specks and side-banner scraps but cut the
        longest entries short: on Longworth 1826, one column to the page, "h. 26 Whitehall" lost
        "tehall" to the tile's edge, as did 0.14-0.35% of the canary volumes' words. A line that
        starts inside the text area counts to its last body word, plus OUTER_SLACK characters
        (the OCR's own box can stop short of faint print), within OUTER_REACH of a column's width;
        a word wholly outside the text (a scrap, a speck) does not count. The slack is margin on
        most pages; beside a side-banner advertisement (Boyd) it can take in a sliver of it."""
        reach = OUTER_REACH * (right - left) / len(cols)
        ends, starts = [right], [left]
        for ws in lines:
            ws = [w for w in ws if w[2] > w[0] and w[3] - w[1] < 3 * wh]
            if ws and left <= min(w[0] for w in ws) <= right:
                ends.append(max(w[2] for w in ws))
            if ws and left <= max(w[2] for w in ws) <= right:
                starts.append(min(w[0] for w in ws))
        cols[-1][1] = int(min(max(ends) + OUTER_SLACK[1] * cw, right + reach, width))
        cols[0][0] = int(max(min(starts) - OUTER_SLACK[0] * cw, left - OUTER_LEFT * cw, 0))
        return cols
    dense = sorted(cross[left:right + 1])[3 * (right - left + 1) // 4]
    if n:
        colw = (right - left) / n
        gutters = []
        for i in range(1, n):
            c = left + i * colw
            a, b = max(left, int(c - GUTTER_SNAP * colw)), min(right, int(c + GUTTER_SNAP * colw))
            gutters.append(clearest(a, b) if b > a else int(c))
        # the volume's count, unless the page is laid out otherwise (an advertisement, a one-column
        # opening page): a forced gutter through text is crossed like a column, and the page keeps
        # its own gutters
        if all(cross[g] <= max(1, GUTTER_TOL * dense) for g in gutters):
            edges = [left] + gutters + [right]
            return outer([[a, b] for a, b in zip(edges, edges[1:])])

    runs, start = [], None
    for x in range(left, right + 2):
        low = x <= right and cross[x] <= GUTTER_REGION * dense
        if low and start is None:
            start = x
        elif not low and start is not None:
            if x - start >= GUTTER_MIN * cw and min(cross[start:x]) <= max(1, GUTTER_TOL * dense):
                runs.append((start, x))
            start = None
    gutters = []
    for g0, g1 in runs:
        side = []
        for ws in lines:
            near = [w for w in ws if g0 - GUTTER_LOOK * cw <= w[2] <= g0 + 1 and w[3] - w[1] < 3 * wh]
            if near:
                side.append(max(near, key=lambda w: w[2]))
        if len(side) < max(5, 0.1 * len(lines)):
            continue                                  # little text left of it: a margin, not a gutter
        x0s, x1s = sorted(w[0] for w in side), sorted(w[2] for w in side)
        lo, hi = len(side) // 10, -1 - len(side) // 10
        if x1s[hi] - x1s[lo] < GUTTER_STRAIGHT * cw and x0s[hi] - x0s[lo] < GUTTER_STRAIGHT * cw:
            continue                                  # a stripe's white strip
        gutters.append(clearest(g0, g1))
    edges = [left] + gutters + [right]
    cols = [[a, b] for a, b in zip(edges, edges[1:])]
    # a narrow piece at the page's edge is a side banner; one between two columns is a column
    # split at a false gutter, and goes back into its narrower neighbour
    while len(cols) > 1:
        narrow = [i for i, c in enumerate(cols) if c[1] - c[0] < COLUMN_WIDTH * width]
        if not narrow:
            break
        i = narrow[0]
        if i in (0, len(cols) - 1):
            cols.pop(i)
        else:
            j = i - 1 if cols[i - 1][1] - cols[i - 1][0] <= cols[i + 1][1] - cols[i + 1][0] else i + 1
            a, b = min(i, j), max(i, j)
            cols[a:b + 1] = [[cols[a][0], cols[b][1]]]
    return outer(cols)


def column_method(ident: str) -> str:
    """Which column rule a volume's pages are cut and paired by. The 39 microfilm volumes of the
    first re-OCR were staged, read and imported by `columns` (peaks), so they keep it; every
    other volume, a book scan, is cut by `gutter_columns`."""
    return "peaks" if ident.startswith("micro_IABROOKLYN_") or ident == "brooklynnewyorkc19123broo" else "gutters"


def skew(lines: list, width: int) -> float:
    """The page's tilt in degrees, positive where its lines run downhill to the right: the median
    slope of word bottoms along tesseract lines of 4+ words spanning 15% of the page; 0.0 with
    fewer than 10 such lines. Filmed pages lie a median 0.4 degrees off; at 1 degree a column's
    margin drifts ~3% of the page from top to bottom, over three bins of `columns`, and half the
    dense two-column pages read as one column were tilted 0.9-2.2 degrees (0039, 0040, 0042)."""
    slopes = []
    for ws in lines:
        xs = [(w[0] + w[2]) / 2 for w in ws]
        if len(ws) < 4 or max(xs) - min(xs) < 0.15 * width:
            continue
        ys = [w[3] for w in ws]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        slopes.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                      / sum((x - mx) ** 2 for x in xs))
    if len(slopes) < 10:
        return 0.0
    return math.degrees(math.atan(sorted(slopes)[len(slopes) // 2]))


def margin_skew(lines: list, width: int):
    """The tilt of the page's left margin in degrees, signed as `skew`: the median slope over
    pairs (Theil-Sen) of the line segments starting within 4% of the page of the leftmost margin,
    against their heights. None with under 10 such segments. A filmed page curved at the binding
    bows its lines while its columns stand straight (micro_IABROOKLYN_0040 leaf 117: lines
    +2.46, margin +0.44), and turning it by its lines tilts the columns instead."""
    segs = [(min(w[0] for w in s), (min(w[1] for w in s) + max(w[3] for w in s)) / 2)
            for s in segments(lines, width) if max(w[2] for w in s) - min(w[0] for w in s)
            > 0.04 * width]
    if len(segs) < 20:
        return None
    x0 = sorted(s[0] for s in segs)[len(segs) // 20]
    band = [s for s in segs if s[0] < x0 + 0.04 * width]
    slopes = sorted((b[0] - a[0]) / (b[1] - a[1]) for i, a in enumerate(band)
                    for b in band[i + 1:] if abs(b[1] - a[1]) > 0.1 * width)
    if len(band) < 10 or not slopes:
        return None
    return math.degrees(math.atan(-slopes[len(slopes) // 2]))


def turn(lines: list, angle: float, size) -> list:
    """The words with their boxes turned `angle` degrees about the page centre, as PIL's
    Image.rotate(angle) turns the image (counter-clockwise on screen), each box the bounds of its
    turned corners: a page tilted by its skew comes upright."""
    if not angle:
        return lines
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    cx, cy = size[0] / 2, size[1] / 2

    def box(w):
        pts = [(cx + (x - cx) * c + (y - cy) * s, cy - (x - cx) * s + (y - cy) * c)
               for x in (w[0], w[2]) for y in (w[1], w[3])]
        return [round(min(p[0] for p in pts)), round(min(p[1] for p in pts)),
                round(max(p[0] for p in pts)), round(max(p[1] for p in pts))] + list(w[4:])
    return [[box(w) for w in ws] for ws in lines]


def page_columns(lines: list, size, method: str = "peaks", n: int = 0) -> tuple:
    """(angle, upright lines, columns) of a cached page: one tilted SKEW_MIN or more, its lines
    and its left margin agreeing within SKEW_AGREE, is turned upright by its lines' skew before
    its columns are found, and its crops are cut from the image turned the same way
    (reocr_columns.py). Tesseract read the tilted page well enough; only the geometry needs it
    upright. On the 7,917 cached pages (2026-10-06) this turns 3,547 and finds the second column
    on 7 dense pages read as one, losing none; by lines alone it lost 0040 leaf 117, by margins
    alone two more (0039 leaf 181, 0042 leaf 303)."""
    angle = round(skew(lines, size[0]), 2)
    margin = margin_skew(lines, size[0])
    if abs(angle) < SKEW_MIN or margin is None or abs(angle - margin) >= SKEW_AGREE:
        angle = 0.0
    upright = turn(lines, angle, size)
    cols = gutter_columns(upright, size[0], n) if method == "gutters" else columns(upright, size[0])
    return angle, upright, cols


def column_lines(lines: list, size, keyed: bool = False, method: str = "peaks", n: int = 0) -> list:
    """The page's lines in reading order, a line tesseract read across a gutter cut in two: each
    word to the column its middle falls in on the upright page (one outside every column goes to
    the nearest), then column by column, top to bottom. Words keep the image's coordinates. The
    word dump written from the cache, and the hybrid's line boxes, need one entry per line.
    keyed=True gives (column, upright top, words) per line instead, which places each line in its
    column crop or half tile (reocr_pair.py)."""
    _angle, upright, cols = page_columns(lines, size, method, n)

    def col(u):
        mid = (u[0] + u[2]) / 2
        return min(range(len(cols)), key=lambda k: 0 if cols[k][0] <= mid < cols[k][1]
                   else min(abs(mid - cols[k][0]), abs(mid - cols[k][1])))
    out = []
    for ws, us in zip(lines, upright):
        parts = collections.defaultdict(list)
        for w, u in zip(ws, us):
            parts[col(u)].append((w, u))
        out += [(k, min(u[1] for _w, u in wu), [w for w, _u in wu]) for k, wu in parts.items()]
    out.sort(key=lambda kyw: kyw[:2])
    return out if keyed else [ws for _k, _y, ws in out]


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
            # Trow 1915/1917's IIIF images are camera frames, a page turned +-90 degrees with the
            # facing page's edge: stage the page IA's OCR read (iiif_frame.upright)
            from iiif_frame import mismatched, upright
            if ident in mismatched():
                upright(ident, leaf, Image.open(img_path)).convert("RGB").save(img_path, quality=95)
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
    def staggered(y):                        # an unbroken line, its word breaks not aligned
        e = 1240 + (y * 7) % 230
        return [[1100, y, e, y + 30, 90, "w"], [e + 10, y, 1700, y + 30, 90, "w"],
                [1710, y, 1900, y + 30, 90, "w"]]
    smudge = one + [ln(1100, 1300, y, 2) + ln(1400, 1900, y) if y % 80 == 0 else staggered(y)
                    for y in range(0, 900, 40)]
    assert len(columns(smudge, w)) == 2, "a column broken at one x is still one column"
    left = [ln(100, 900, y) for y in range(0, 900, 40)]
    mid = [ln(1000, 1600, y) for y in range(0, 900, 40)]
    banner = [[[1700, y, 1800, y + 60, 40, "X"]] for y in range(0, 900, 70)]
    assert columns(left + mid + banner, w) == [[100, 1000], [1000, 1590]], "a banner is no column"
    assert columns(left + mid + banner[:3], w) == [[100, 1000], [1000, 1590]], "nor runs to one"
    split = column_lines(merged, (2000, 3000))
    assert len(split) == 46 and [split[k][0][0] for k in (0, 1, 23, 24)] == [100, 100, 1100, 1100], \
        "cut, then column by column"
    tall = [ln(100, 900, y) for y in range(0, 2800, 40)] + [ln(1100, 1900, y) for y in range(0, 2800, 40)]
    tilted = turn(tall, -1.5, (2000, 3000))  # clockwise on screen: downhill to the right
    assert abs(skew(tilted, 2000) - 1.5) < 0.1 and abs(skew(tall, 2000)) < 0.01
    angle, upright, cols = page_columns(tilted, (2000, 3000))
    assert angle == round(skew(tilted, 2000), 2) and len(cols) == 2, "turned upright, two columns"
    assert page_columns(tall, (2000, 3000))[0] == 0.0, "an upright page is read as it lies"
    assert abs(margin_skew(tilted, 2000) - 1.5) < 0.1
    bowed = [[[w[0], w[1] + (w[0] - 100) // 30, w[2], w[3] + (w[2] - 100) // 30] + w[4:] for w in ws]
             for ws in tall]                 # lines sloping ~2 degrees, margins upright
    assert skew(bowed, 2000) > 1.5 and abs(margin_skew(bowed, 2000)) < 0.1
    assert page_columns(bowed, (2000, 3000))[0] == 0.0, "a curved page is not turned"
    assert [w[0] for w in column_lines(tilted, (2000, 3000))[0]] == [w[0] for w in tilted[0]], \
        "the dump keeps the image's coordinates"
    def entry(x1, y, n=4):                   # gutter_columns measures letters on 3+ letter words
        return [w[:5] + ["word"] for w in ln(100, x1, y, n)]
    long_tail = [entry(900, y) for y in range(0, 4000, 40)]
    long_tail[10] = entry(1020, 400, 5)      # two entries run a word past the 99th percentile
    long_tail[60] = entry(1020, 2400, 5)
    long_tail.append([[1700, 3000, 1720, 3020, 1, "."]])     # a speck right of the text
    (x0, x1), = gutter_columns(long_tail, 2000, 1)
    assert 1010 < x1 < 1700 and 40 <= x0 < 100, "the longest entries are not cut, nor is a speck taken"
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
