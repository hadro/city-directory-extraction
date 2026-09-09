#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Turn an ENTIRE Internet Archive volume into the `{raw_line, context, record}` JSONL that
`eval/qwen_predict.py` consumes -- the missing first stage of a whole-volume extraction run.

Every `data/*_eval.jsonl` in this repo is hand-built gold from *sampled* pages
(directory-pipeline -> Surya -> make_gold_tool.py). That path is right for an eval panel and
wrong for a volume: it is human-paced and it covers ~50 lines per book. This reads IA's own
hOCR for all ~1,250 leaves and emits ~200k candidate lines with no OCR spend and no GPU.

    # 1. build the lines (CPU + network only; fine on a laptop)
    python3 data_prep/ia_volume_to_jsonl.py --ident 1906BPL --out data/1906BPL_lines.jsonl

    # 2. look at what the filter threw away BEFORE you trust it
    python3 data_prep/ia_volume_to_jsonl.py --ident 1906BPL --dump-dropped /tmp/dropped.txt

    # 3. run the model (this is the part that wants a GPU)
    python3 eval/qwen_predict.py --base-model Qwen/Qwen3.5-4B \
        --model ~/Downloads/scale-runs/adapters/4b-100k \
        --gold data/1906BPL_lines.jsonl --target yaml --batch-size 128 \
        --out data/preds_4b_1906BPL.txt

    python3 data_prep/ia_volume_to_jsonl.py --self-test    # offline; no network, no model

There is no `--gold` to score against and that is expected: a volume sweep is a production
run, not a measurement. The measurement is the frozen 21-volume panel. `record` is emitted as
an empty stub because `qwen_predict.py` reads only `raw_line` and `context`; the stub exists
so the file is shape-compatible with everything else in `data/`.

Why hOCR and not `_djvu.txt`
---------------------------
Measured in historical-ocr-eval: `_djvu.txt` flattens multi-column pages -- several directory
entries merge onto one text line -- and scores CER-all 0.723 against 0.159 for the same page
rebuilt from `_hocr.html` `ocr_line` elements. Same words, 4.5x the error, purely from line
segmentation. Never read the djvu derivative for this corpus.

The filters, and what they are worth
------------------------------------
Two stages, and the honest summary is that only the first one is calibrated.

**Text** (ported from `harvest_occupations.py:gather_lines`): drops page numbers, ALL-CAPS
running heads, sub-8-char fragments, and non-ASCII garbage. Measured on 14 seeded-random
leaves of 1906BPL: keeps **76%**. That is a deliberately permissive filter -- it was built to
feed Gemini, which then discarded non-entries by returning an empty occupation. It is NOT an
entry detector, and it happily passes advertising copy ("Seventh Ave. and Union St.,").

**Geometry** (new here): the hOCR carries boxes, and historical-ocr-eval established they are
trustworthy for this corpus (`under% 0.0`, IoU 0.724). Display ads and section headings are set
in larger type and run wider than body entries, so per page we drop lines taller than 2x the
page's own median line height (`bigtype`) or wider than 2.5x its median line width (`banner`).
Both are judged against the page's own medians, so no column count is needed and the same
thresholds work on an 1786 single-column folio and a 1933 six-column Polk.

Measured on six 1906BPL leaves: 32 drops, every one inspected a running head, an ad headline, or
OCR garbage. No false positives found.

**Wrapped entries are joined first** (see `join_wraps`) -- 199 joins in those 1,557 lines. End to
end: 1,557 hOCR lines -> 1,358 candidate entries -> **1,035 kept (76.2%)**.

Checked on a deliberately opposite volume, `micro_IABROOKLYN_0013` (1836/37 Brooklyn, SINGLE
column, tesseract-on-microfilm rather than ABBYY-on-scan -- the thin tier). Whole volume, 100
content leaves: 3,676 lines -> 3,460 candidates -> **2,889 kept (83.5%)**, in under a minute.
`banner` there caught the volume's display advertising ("IMPORTER of CHINA, GLASS & ...",
"SHEFFIELD & BIRMINGHAM SILVER PLATED"); `bigtype` and `short` caught tesseract noise. The
thresholds are ratios against each page's own medians, which is why one setting spans a
single-column 1836 microfilm and a two-column 1906 scan without tuning.

**Two things this deliberately does NOT do.** It does not detect columns -- see `page_geometry`
for the measured reason that failed. And `--drop-off-margin` is opt-in rather than default,
because the three extra points it buys come partly out of real entries; see `margin_reject`.

Neither stage is validated against gold, because no box-level gold exists for this task. So
`--dump-dropped` writes every rejected line with its reason, and you should **read it before
running a model over the survivors**. Selecting only on what a filter kept, and never looking
at what it cut, is the recurring trap this project has already paid for three times.

Boxes are recorded in the hOCR's own pixel space (the jp2's), NOT the space of any JPEG you
may later download -- IA's derivative images are often resized. `context.page_size` is stored
alongside so a later `#xywh=` can be scaled correctly. An unscaled box is a silent, plausible
looking lie.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import html as _html
import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MASTER = REPO / "data_prep" / "master_directories.csv"
DL = "https://archive.org/download"

WORD_RE = re.compile(
    r'<span class="ocrx_word"[^>]*title="bbox (\d+) (\d+) (\d+) (\d+); x_wconf (\d+)[^"]*"[^>]*>(.*?)</span>',
    re.S,
)
PAGE_BBOX_RE = re.compile(r'<div class="ocr_page"[^>]*title="bbox (\d+) (\d+) (\d+) (\d+)')
TAG_RE = re.compile(r"<[^>]+>")

# --- text filter (harvest_occupations.py:gather_lines) ----------------------------------------
_PAGE_NUM = re.compile(r"^\W*\d{1,4}\W*$")
_HAS_LOWER = re.compile(r"[a-z]")

# --- geometry thresholds (find_ad_pages.py) ---------------------------------------------------
BIG_RATIO = 2.0          # a line this many times the median height reads as display type
WIDE_RATIO = 1.5         # a line this many times the COLUMN width crosses columns
MIN_CHARS_LEAF = 200     # below this a leaf is a blank verso or a plate, not a listing page


# ==============================================================================================
# IA derivative access
# ==============================================================================================
class Item:
    """One IA item's hOCR, fetched once and cached on disk.

    Vendored from historical-ocr-eval `engines/run_ia_derivatives.py` (branch
    `ia-derivatives-engine`) rather than imported: that repo is owned by another working
    session, and this is ~60 stdlib lines. If the two ever diverge, that file is the original.

    The volume-scale difference from the original: a page-at-a-time Range sweep costs ~10 s per
    leaf against IA, which is 3+ hours for a 1,250-leaf book. So by default we pull the whole
    `_hocr.html` ONCE and seek locally with the pageindex byte offsets, which is the same bytes
    for one request instead of 1,250.
    """

    def __init__(self, ident: str, cache: Path, retries: int = 3):
        self.ident, self.cache, self.retries = ident, cache, retries
        self._index = None

    def _url(self, suffix: str) -> str:
        return f"{DL}/{self.ident}/{self.ident}{suffix}"

    def _get(self, suffix: str) -> Path:
        p = self.cache / f"{self.ident}{suffix}"
        if not p.exists() or p.stat().st_size == 0:
            self.cache.mkdir(parents=True, exist_ok=True)
            _download(self._url(suffix), p, self.retries)
        return p

    @property
    def index(self):
        """Per-leaf [searchtext_start, searchtext_end, hocr_byte_start, hocr_byte_end]."""
        if self._index is None:
            with gzip.open(self._get("_hocr_pageindex.json.gz"), "rt") as f:
                self._index = json.load(f)
        return self._index

    def remote_hocr_size(self):
        req = urllib.request.Request(self._url("_hocr.html"), method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return int(r.headers.get("Content-Length") or 0)
        except Exception:                                  # noqa: BLE001 - advisory only
            return 0

    def prefetch_hocr(self) -> Path:
        """Pull the entire `_hocr.html` so every page read is a local seek."""
        return self._get("_hocr.html")

    def hocr_page(self, leaf: int):
        if leaf >= len(self.index):
            return None
        a, b = self.index[leaf][2], self.index[leaf][3]
        full = self.cache / f"{self.ident}_hocr.html"
        if full.exists() and full.stat().st_size > b:
            with open(full, "rb") as f:
                f.seek(a)
                return f.read(b - a).decode("utf-8", "replace")
        raw, whole = _range_get(self._url("_hocr.html"), a, b, self.retries)
        if whole is not None:                              # node ignored Range; keep the bytes
            self.cache.mkdir(parents=True, exist_ok=True)
            full.write_bytes(whole)
        return raw.decode("utf-8", "replace")


def _download(url: str, dest: Path, retries: int):
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=1800) as r:
                dest.write_bytes(r.read())
            return
        except Exception as e:                             # noqa: BLE001 - network, then surfaced
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed after {retries}: {url} ({last})")


def _range_get(url: str, a: int, b: int, retries: int):
    """Bytes [a, b) as (slice, whole_file_or_None).

    IA honours Range on archive.org but its redirect to a storage node sometimes does not and
    returns the whole file with a 200. Both outcomes yield identical bytes; the caller is told
    which happened so it can cache the full download instead of repeating it per page.
    """
    req = urllib.request.Request(url, headers={"Range": f"bytes={a}-{b - 1}"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                status, data = r.status, r.read()
            if status == 200 and len(data) > (b - a) * 2:
                return data[a:b], data
            return data, None
        except Exception as e:                             # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"range fetch failed after {retries}: {url} ({last})")


def hocr_lines(markup: str):
    """[((x0, y0, x1, y1), text)] from the hOCR's own ocr_line grouping."""
    out = []
    for seg in re.split(r'(?=<span class="ocr_line")', markup)[1:]:
        seg = seg.split("</p>")[0]
        words, box = [], None
        for m in WORD_RE.finditer(seg):
            x0, y0, x1, y1 = (int(m.group(i)) for i in range(1, 5))
            t = _html.unescape(TAG_RE.sub("", m.group(6))).strip()
            if not t:
                continue
            words.append(t)
            box = (min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1)) \
                if box else (x0, y0, x1, y1)
        if words and box:
            out.append((box, " ".join(words)))
    return out


def page_dims(markup: str):
    m = PAGE_BBOX_RE.search(markup)
    return (int(m.group(3)), int(m.group(4))) if m else None


# ==============================================================================================
# Filters
# ==============================================================================================
def text_reject(line: str):
    """Reason this line is not a directory entry, or None to keep it."""
    if len(line) < 8:
        return "short"
    if _PAGE_NUM.match(line):
        return "pagenum"
    if not _HAS_LOWER.search(line):
        return "allcaps"
    if sum(c.isascii() for c in line) / len(line) < 0.85:
        return "nonascii"
    return None


INDENT_RATIO = 3.0       # a next line starting this many median-heights right = a continuation
VGAP_RATIO = 2.5         # ...and no further than this below the line it continues
OVERLAP_FRAC = 0.3       # ...and horizontally overlapping it, i.e. the same column


def join_wraps(lines, med_h):
    """Join wrapped entries into one line. Returns ([(box, text, height)], n_joins).

    GROUND_TRUTH_HANDOFF conventions 9a and 15: a printed entry that overflows its column
    continues on an INDENTED next line, and gold joins the two into a single `raw_line` -- with
    a space, except that a hyphenated word-break closes up (`Bar-` + `clay` -> `Barclay`). The
    model was trained and scored on joined entries, so emitting the fragments separately is a
    train/serve mismatch, not a cosmetic difference.

    The indent is the whole signal and hOCR carries it. Measured on six 1906BPL leaves: 199
    joins in 1,557 lines (12.8%). This also recovers lines the text filter was throwing away --
    a continuation like "259 Himrod" is short enough to look like page furniture on its own,
    which is why joining has to happen BEFORE filtering.

    Deliberately local: it compares each line only with the one before it, so it needs no
    column model. That is what makes it survive the multi-modal left edges that defeated column
    detection (see page_geometry).

    `height` is carried separately because the joined box spans two printed lines and would
    otherwise trip the `bigtype` rule. Geometry tests use the first segment's height; the union
    box is kept for provenance.
    """
    out, joins = [], 0
    for box, text in lines:
        if out:
            pb, pt, ph = out[-1]
            if (box[0] - pb[0] > INDENT_RATIO * med_h
                    and 0 < box[1] - pb[1] < VGAP_RATIO * med_h
                    and min(box[2], pb[2]) - max(box[0], pb[0]) > OVERLAP_FRAC * (box[2] - box[0])):
                sep = "" if pt.endswith("-") else " "
                out[-1] = ((min(pb[0], box[0]), pb[1], max(pb[2], box[2]), box[3]),
                           (pt[:-1] if pt.endswith("-") else pt) + sep + text, ph)
                joins += 1
                continue
        out.append((box, text, box[3] - box[1]))
    return out, joins


def page_geometry(lines):
    """(median_height, median_width, ad_score) for one page's [(box, text, height)].

    Everything is judged against the PAGE'S OWN medians, so the rules are self-calibrating
    across a 1786 single-column folio and a 1933 six-column Polk without a column count.

    Column detection was tried here first and removed. `detection_recall.py:columns_from_boxes`
    clusters left edges and works well on Surya REGION boxes -- a handful of big blocks per
    page. hOCR gives ~260 LINE boxes whose left edges are legitimately multi-modal: on 1906BPL
    leaf 606 the two body columns sit at x=428 (78 lines) and x=1049 (53), but wrapped-line
    indents at 516 and 1018 are dense enough to read as column starts too. Every indent became
    a spurious boundary, the real margins fell outside the derived spans, and the filter
    inverted -- dropping 64% of the page including clean entries ("Kramer Aaron furs 56 Bond")
    while keeping ad copy ("Telephone, 4036 Williamsburgh."). Do not reintroduce it without
    box-level gold to check it against.
    """
    if not lines:
        return 1.0, 1.0, 0.0
    heights = [h for _, _, h in lines]                     # printed line height, not union height
    widths = [b[2] - b[0] for b, _, _ in lines]
    med_h = statistics.median(heights) or 1.0
    med_w = statistics.median(widths) or 1.0
    areas = [w * h for w, h in zip(widths, heights)]
    total = sum(areas) or 1
    big = sum(a for a, h in zip(areas, heights) if h > med_h * BIG_RATIO) / total
    wide = sum(1 for w in widths if w > med_w * WIDE_RATIO) / len(lines)
    return med_h, med_w, big + wide


def geom_reject(box, height, med_h, med_w):
    """Reason this line's geometry says it is not a body entry, or None to keep it.

    Measured on six 1906BPL leaves: 28 drops in 1,557 lines, and every one inspected was a
    running head, an ad headline, or OCR garbage -- no false positives found. Combined with the
    text filter this keeps 73.1% (text alone keeps 76.0%).
    """
    if height > med_h * BIG_RATIO:
        return "bigtype"
    if (box[2] - box[0]) > med_w * WIDE_RATIO:
        return "banner"
    return None


def left_margins(boxes, tol=18, min_share=0.04):
    """Left-edge clusters holding a real share of the page -- entries share margins, junk does not."""
    xs = sorted(b[0] for b in boxes)
    if not xs:
        return []
    groups, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= tol:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    groups.append(cur)
    need = max(6, int(min_share * len(boxes)))
    return [(g[0], g[-1]) for g in groups if len(g) >= need]


def margin_reject(box, margins, tol):
    """OFF BY DEFAULT -- opt in with --drop-off-margin, and read the trade-off first.

    Buys roughly 3 extra points of cut (73.1% -> 71.7% on the six-leaf sample) and does cut
    real advertising and OCR noise. But it also cuts real entries, because the FIRST entry of a
    column is often outdented past its own margin: "Kramer Aaron furs 56 Bond" starts at x=397
    against a 428 margin, "Petersen Andreas foreman h 294 Hem-" at 403 against 433. Widening
    the tolerance recovers those and simultaneously recovers the ad text sharing the same
    margin, so the two classes are not separable by left edge alone. Three points of cut is not
    worth silently deleting entries, which is why this is opt-in and the default is off.
    """
    if not margins:
        return None
    return None if any(lo - tol <= box[0] <= hi + tol for lo, hi in margins) else "off-margin"


# ==============================================================================================
# Volume sweep
# ==============================================================================================
# The `[publisher=X]` tokens actually present in the SFT data (data/synth_train_250k.jsonl).
# Source of truth for the whole repo -- data_prep/backfill_publisher.py imports this set to audit
# the catalog column against it, so the list lives in one place.
TRAINED_VOCAB = {
    "trow", "polk-tulsa", "lain", "polk", "longworth", "doggett", "upington",
    "duncan", "hopehenderson", "smith", "boyd", "hearne", "rode", "mb",
    "mercein", "franks", "ogden",
}

# Catalog spellings that are a trained token wearing a possessive or an extra "s".
_TAG_ALIASES = {"hearnes": "hearne", "doggetts": "doggett",
                "hope & henderson": "hopehenderson", "hope&henderson": "hopehenderson"}


def tag_publisher(publisher: str):
    """(tag, why) -- the trained token to put in the [publisher=X] tag for a catalog publisher.

    `publisher` is catalog truth and is often out of vocabulary: `spooner` is a real Brooklyn
    publisher the model has simply never seen, and `trow/wilson` is a partnership recorded under
    both names. Emitting either verbatim tags the volume with a token that was never trained,
    which is a *different* failure from a wrong-but-trained tag rather than a lesser one -- and
    since the tag is interpolated as free text, both pass silently.

        exact trained token                      -> itself
        possessive or spelling variant           -> the trained token   ("hearnes"     -> hearne)
        partnership with a trained partner       -> that partner        ("trow/wilson" -> trow)
        anything else                            -> "trow", and say so

    The last case is a fallback, not an answer: picking a trained stand-in for a genuinely unseen
    publisher (spooner, reynolds, donnelley) needs an A/B, not an assumption.
    """
    raw = (publisher or "").strip().lower()
    if not raw:
        return "trow", "no publisher in the catalog"
    if raw in TRAINED_VOCAB:
        return raw, ""

    alias = _TAG_ALIASES.get(raw) or re.sub(r"['’]s$|s['’]$|['’]$", "", raw)
    alias = _TAG_ALIASES.get(alias, alias)
    if alias in TRAINED_VOCAB:
        return alias, f"{raw!r} normalised to the trained token {alias!r}"

    for atom in re.split(r"[/&]", raw):
        atom = _TAG_ALIASES.get(atom.strip(), atom.strip())
        if atom in TRAINED_VOCAB:
            return atom, f"{raw!r} tagged as its trained partner {atom!r}"

    return "trow", f"{raw!r} is not in the trained vocabulary -- falling back to 'trow'"


def lookup_master(ident: str):
    """(publisher, year) from master_directories.csv, or ('', '') if the volume is not listed."""
    if not MASTER.exists():
        return "", ""
    with open(MASTER, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("id") == ident:
                return (row.get("publisher") or "").strip().lower(), (row.get("year") or "").strip()
    return "", ""


EMPTY_RECORD = {"name": "", "is_business": False, "spouse_name": "", "race_designation": "",
                "occupation_role": "", "employer": "", "address": "", "home_address": ""}


def sweep(item, publisher, year, leaves, use_geometry, margin_tol, join, dropped_fh, out_fh):
    """Walk leaves, emit kept lines, return (stats, reasons, ad_scores)."""
    stats = {"leaves": 0, "raw": 0, "joins": 0, "kept": 0}
    reasons, ad_scores = {}, []
    for n, leaf in enumerate(leaves, 1):
        markup = item.hocr_page(leaf)
        if not markup:
            continue
        raw = hocr_lines(markup)
        if not raw:
            continue
        stats["leaves"] += 1
        stats["raw"] += len(raw)
        dims = page_dims(markup)

        # Join BEFORE filtering: a continuation like "259 Himrod" is short enough that the text
        # filter would discard it, and the entry it belongs to would silently lose its address.
        med_h_raw = statistics.median([b[3] - b[1] for b, _ in raw]) or 1.0
        if join:
            lines, joins = join_wraps(raw, med_h_raw)
            stats["joins"] += joins
        else:
            lines = [(b, t, b[3] - b[1]) for b, t in raw]

        med_h, med_w, ad = page_geometry(lines)
        ad_scores.append((leaf, round(ad, 3)))
        margins = left_margins([b for b, _, _ in lines]) if margin_tol is not None else []

        for box, text, height in lines:
            why = text_reject(text)
            if why is None and use_geometry:
                why = geom_reject(box, height, med_h, med_w)
            if why is None and margin_tol is not None:
                why = margin_reject(box, margins, margin_tol)
            if why is not None:
                reasons[why] = reasons.get(why, 0) + 1
                if dropped_fh:
                    dropped_fh.write(f"{leaf}\t{why}\t{box}\t{text}\n")
                continue
            out_fh.write(json.dumps({
                "raw_line": text,
                "context": {
                    "publisher": publisher,          # already a trained token (tag_publisher)
                    "directory_year": year or "",
                    "ia_id": item.ident,
                    "leaf": leaf,
                    # hOCR/jp2 pixel space -- scale to any JPEG you download before using as #xywh=
                    "bbox": list(box),
                    "page_size": list(dims) if dims else None,
                },
                "record": EMPTY_RECORD,
            }, ensure_ascii=False) + "\n")
            stats["kept"] += 1
        if n % 50 == 0:
            print(f"  ... {n}/{len(leaves)} leaves, {stats['kept']:,} lines kept", file=sys.stderr)
    return stats, reasons, ad_scores


# ==============================================================================================
def _self_test() -> int:
    assert text_reject("Koebel And'w gilder h 346 Ashford") is None
    # note the ORDER: the length test fires first, so a bare "42" is "short", not "pagenum".
    # _PAGE_NUM only earns its keep on decorated running numbers long enough to survive that.
    assert text_reject("42") == "short"
    assert text_reject("[ 1234 ]") == "pagenum"
    assert text_reject("BROOKLYN DIRECTORY") == "allcaps"
    assert text_reject("ab c") == "short"
    # ...and the ALL-CAPS test fires before the ASCII one, so a purely CJK run reads as
    # "allcaps". Reaching "nonascii" needs lowercase latin mixed with the garbage.
    assert text_reject("九万主九万主九万主") == "allcaps"
    assert text_reject("abc九万主九万主九万主def") == "nonascii"

    # three tidy columns of ten body lines each
    boxes = [(x, 100 + 20 * i, x + 300, 118 + 20 * i) for x in (100, 500, 900) for i in range(10)]
    lines = [(b, "Smith John clk 12 Pine", b[3] - b[1]) for b in boxes]
    med_h, med_w, ad = page_geometry(lines)
    assert (med_h, med_w, ad) == (18, 300, 0.0), (med_h, med_w, ad)
    assert all(geom_reject(b, b[3] - b[1], med_h, med_w) is None for b in boxes)

    # a display-ad headline: tall type
    assert geom_reject((100, 50, 400, 140), 90, med_h, med_w) == "bigtype"
    # a normal-height line running far wider than the page's own body lines
    assert geom_reject((100, 50, 1180, 68), 18, med_h, med_w) == "banner"

    # --- wrapped entries (GROUND_TRUTH_HANDOFF 9a/15) -----------------------------------------
    wrapped = [((100, 100, 400, 118), "Kramer Aaron furs 56 Bond Mihtn h"),
               ((190, 122, 380, 140), "1653 St Mark's av"),      # indented -> continuation
               ((100, 144, 390, 162), "Aaron realestate h 272 S 1st")]  # back at margin -> new
    joined, n = join_wraps(wrapped, 18)
    assert n == 1 and len(joined) == 2, (n, joined)
    assert joined[0][1] == "Kramer Aaron furs 56 Bond Mihtn h 1653 St Mark's av", joined[0][1]
    # the union box spans both printed lines, but the height carried forward is ONE line's, so
    # a joined entry is not mistaken for display type
    assert joined[0][0] == (100, 100, 400, 140) and joined[0][2] == 18, joined[0]
    assert geom_reject(joined[0][0], joined[0][2], 18, 300) is None

    # a hyphenated word-break closes up instead of taking a space
    hyph = [((100, 100, 400, 118), "Petersen Andreas foreman h 294 Hem-"),
            ((190, 122, 300, 140), "street")]
    assert join_wraps(hyph, 18)[0][0][1] == "Petersen Andreas foreman h 294 Hemstreet"

    # a line that is indented but too far below is a new entry, not a continuation
    far = [((100, 100, 400, 118), "Kramer Aaron furs 56 Bond"),
           ((190, 300, 380, 318), "Smith John clk 12 Pine")]
    assert join_wraps(far, 18)[1] == 0

    # margins: three dense clusters; junk in the gutter matches none of them
    ms = left_margins(boxes)
    assert ms == [(100, 100), (500, 500), (900, 900)], ms
    assert margin_reject((100, 200, 400, 218), ms, 40) is None
    assert margin_reject((10, 200, 60, 218), ms, 40) == "off-margin"
    # the outdented first-entry case this rule gets WRONG at a tight tolerance, right at 40
    assert margin_reject((69, 200, 369, 218), ms, 18) == "off-margin"
    assert margin_reject((69, 200, 369, 218), ms, 40) is None
    # with no margins found (a sparse page) the rule abstains rather than rejecting everything
    assert margin_reject((10, 200, 60, 218), [], 40) is None

    markup = ('<div class="ocr_page" title="bbox 0 0 2000 3000">'
              '<p><span class="ocr_line" title="bbox 100 100 400 118">'
              '<span class="ocrx_word" title="bbox 100 100 200 118; x_wconf 90">Smith</span> '
              '<span class="ocrx_word" title="bbox 210 100 400 118; x_wconf 90">John</span>'
              '</span></p>')
    got = hocr_lines(markup)
    assert got == [((100, 100, 400, 118), "Smith John")], got
    assert page_dims(markup) == (2000, 3000)
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ident", help="Internet Archive identifier, e.g. 1906BPL")
    ap.add_argument("--out", default=None, help="output JSONL (default data/<ident>_lines.jsonl)")
    ap.add_argument("--cache", default=str(REPO / "data" / "ia_cache"),
                    help="where derivatives are cached (data/ is git-ignored)")
    ap.add_argument("--publisher", default=None, help="override; else looked up in the master CSV")
    ap.add_argument("--year", default=None, help="override; else looked up in the master CSV")
    ap.add_argument("--leaves", default=None,
                    help="leaf range 'A-B' or a comma list; default every content leaf")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS_LEAF,
                    help="skip leaves whose pageindex census is below this (blank versos, plates)")
    ap.add_argument("--no-geometry", action="store_true",
                    help="text filter only (76%% keep on 1906BPL); default adds bigtype+banner "
                         "for 73.1%%")
    ap.add_argument("--no-join", action="store_true",
                    help="do NOT join wrapped entries. The gold convention joins them and the "
                         "model was trained that way, so this is for diagnosis only.")
    ap.add_argument("--drop-off-margin", nargs="?", const=40, type=int, default=None,
                    metavar="TOL",
                    help="ALSO drop lines that do not start at a common left margin (~3 extra "
                         "points of cut). OFF by default because it also cuts outdented "
                         "column-leading entries -- see margin_reject(). Optional px tolerance, "
                         "default 40.")
    ap.add_argument("--dump-dropped", default=None,
                    help="write every rejected line with its reason. READ THIS before trusting a run.")
    ap.add_argument("--range-only", action="store_true",
                    help="Range-request each page instead of pulling the whole hOCR first. "
                         "Fine for a handful of leaves; ~10 s/leaf, so hours for a volume.")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.ident:
        ap.error("--ident is required (or use --self-test)")

    out_path = Path(args.out) if args.out else REPO / "data" / f"{args.ident}_lines.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    item = Item(args.ident, Path(args.cache))

    pub, yr = lookup_master(args.ident)
    catalog_publisher = args.publisher if args.publisher is not None else pub
    year = args.year if args.year is not None else yr

    # The catalog records who actually published the volume; the tag has to be one of the 17
    # tokens the model was trained on. They are usually but not always the same string.
    publisher, why = tag_publisher(catalog_publisher)
    if why:
        print(f"  ! {args.ident}: tagging [publisher={publisher}] -- {why}.", file=sys.stderr)
    if not catalog_publisher or not year:
        missing = ", ".join(k for k, v in (("publisher", catalog_publisher), ("year", year)) if not v)
        print(f"  ! {args.ident}: no {missing} in master_directories.csv "
              f"(publisher={catalog_publisher or 'BLANK'}, year={year or 'BLANK'}). "
              f"The model was trained with a [publisher=X; year=Y] tag, so pass --publisher/--year "
              f"if you know them -- a wrong tag is a silent quality loss, not an error. The 'trow' "
              f"default matches harvest_occupations.py, but on an 1830s Brooklyn volume it is "
              f"simply the wrong publisher. `python3 data_prep/backfill_publisher.py` fills many "
              f"blanks from the catalog's own title/notes.", file=sys.stderr)

    idx = item.index
    if args.leaves:
        if "-" in args.leaves and "," not in args.leaves:
            a, b = args.leaves.split("-")
            leaves = list(range(int(a), int(b) + 1))
        else:
            leaves = [int(x) for x in args.leaves.split(",")]
    else:
        leaves = [i for i, e in enumerate(idx) if e[1] - e[0] > args.min_chars]
    print(f"{args.ident}: {len(idx)} leaves, {len(leaves)} with text "
          f"(>{args.min_chars} chars) | publisher={publisher} year={year or '?'}",
          file=sys.stderr)

    if not args.range_only:
        size = item.remote_hocr_size()
        cached = Path(args.cache) / f"{args.ident}_hocr.html"
        if not cached.exists():
            print(f"  fetching {args.ident}_hocr.html ({size / 1e6:.0f} MB) once, "
                  f"then seeking locally -- Range-per-page would be ~{len(leaves) * 10 / 3600:.1f} h",
                  file=sys.stderr)
        item.prefetch_hocr()

    dropped_fh = open(args.dump_dropped, "w", encoding="utf-8") if args.dump_dropped else None
    with open(out_path, "w", encoding="utf-8") as out_fh:
        stats, reasons, ad_scores = sweep(item, publisher, year, leaves,
                                          not args.no_geometry, args.drop_off_margin,
                                          not args.no_join, dropped_fh, out_fh)
    if dropped_fh:
        dropped_fh.close()

    entries = stats["raw"] - stats["joins"]                # lines after wrapped ones are merged
    pct = 100 * stats["kept"] / entries if entries else 0
    print(f"\n{stats['leaves']} leaves | {stats['raw']:,} hOCR lines "
          f"- {stats['joins']:,} wrap-joins = {entries:,} candidate entries "
          f"-> {stats['kept']:,} kept ({pct:.1f}% of candidates)", file=sys.stderr)
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    dropped {n:>7,}  {why}", file=sys.stderr)
    if ad_scores:
        worst = sorted(ad_scores, key=lambda kv: -kv[1])[:8]
        print(f"  highest ad-scores (leaf, big%+wide%): {worst}", file=sys.stderr)
        print("    -- spot-check those leaves; a high score is display advertising or a "
              "section-heading page, both of which produce fake entries.", file=sys.stderr)
    print(f"\nwrote {out_path}", file=sys.stderr)
    if dropped_fh:
        print(f"rejected lines -> {args.dump_dropped}  (READ THIS: the geometry stage is "
              f"uncalibrated and can cut real entries)", file=sys.stderr)
    print(f"\nnext: python3 eval/qwen_predict.py --base-model Qwen/Qwen3.5-4B \\\n"
          f"        --model ~/Downloads/scale-runs/adapters/4b-100k \\\n"
          f"        --gold {out_path} --target yaml --batch-size 128", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
