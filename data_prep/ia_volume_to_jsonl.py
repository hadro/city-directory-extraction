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
page's own median line height (`bigtype`) or wider than 1.5x its median line width (`banner`).
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
# `bbox` need not be the FIRST property of the title. ABBYY writes title="bbox 0 0 2550 3301",
# but tesseract writes title="image &quot;/tmp/x.jp2&quot;; bbox 0 0 2572 4507; ppageno 0; ...".
# Anchoring on title="bbox silently returned None for every leaf of every tesseract volume, so
# `context.page_size` was null on all 2,889 lines of micro_IABROOKLYN_0013 -- and page_size is
# what makes a stored box scalable to a downloaded JPEG. An unscaled box is a plausible-looking
# lie, so this was that lie across a whole OCR tier. The geometry filter was unaffected: it uses
# per-page medians of the line boxes themselves and never reads page dims.
PAGE_BBOX_RE = re.compile(
    r'<div class="ocr_page"[^>]*?title="[^"]*?\bbbox (\d+) (\d+) (\d+) (\d+)')
TAG_RE = re.compile(r"<[^>]+>")

# --- text filter (harvest_occupations.py:gather_lines) ----------------------------------------
_PAGE_NUM = re.compile(r"^\W*\d{1,4}\W*$")
_HAS_LOWER = re.compile(r"[a-z]")

# --- geometry thresholds (find_ad_pages.py) ---------------------------------------------------
BIG_RATIO = 2.0          # a line this many times the page's median line HEIGHT is display type
# ...and this many times the page's median line WIDTH is a banner. Not a column width -- no column
# width is computed anywhere here, and page_geometry() explains at length why column detection was
# tried and removed. On a listing page a body line spans one column, so the median line width IS
# about one column wide in practice, which is what makes the threshold mean "crosses columns"
# without ever needing to find one.
WIDE_RATIO = 1.5
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


# ---------------------------------------------------------------------------------------------
# DITTO-LEAD NORMALIZATION -- measured, not assumed (2026-09-10)
#
# A surname-repeat ditto is printed as `"` and ABBYY reads it as `44`. The generator never emits
# `44` (trained forms are `-` and `" `), so it is out of distribution for every adapter here, and
# it is not cosmetic: it makes the model run the `name` field too far and swallow the occupation.
#
#     44 Wm elk h 86 Laf av   ->  name='44 Wm elk'   occupation=''
#      " Wm elk h 86 Laf av   ->  name='" Wm'        occupation='clk'
#
# n=500 paired rows on 2b-100k, pre-registered: 14 rows where the raw form swallows the occupation
# and the substituted form does not, against 1 the other way. McNemar exact p=0.0010. Non-name
# fields move on 8.2% of rows. Full record: results/ab_ditto44_1906BPL_2b100k*.
#
# WHY A FREQUENCY GATE RATHER THAN A HARD-CODED `44`. `44` is a real house number, so substituting
# it blind would corrupt any line that legitimately starts with one. What proves it is a ditto in
# 1906BPL is the DISTRIBUTION: it leads 84,053 of 199,012 lines (42%). No volume has 42% of its
# entries at house number 44. So a digit form is treated as a ditto only when its share of leading
# tokens is implausibly high for a real address, and the threshold is reported so the call is
# visible rather than buried. On micro_IABROOKLYN_0013 (tesseract) `44` never leads a line at all
# and the gate correctly fires on nothing.
#
# ⚠️ AN EARLIER VERSION ADMITTED PUNCTUATION ON SHAPE ALONE, arguing that a directory line never
# legitimately begins with `**` or `“`. **That was wrong in BOTH directions and the gold panel
# proves it.** Corrected 2026-09-10 after the tail was actually looked at.
#
# WRONG DIRECTION 1 -- over-firing. Shape says nothing about whether a mark introduces an ENTRY.
# On 1906BPL, `“` is followed by a name on 98% of its lines; `—` on 27% (`— ■ Telephone Call:`,
# `— Bay Ridge` are headings) and `*` on 43%. Shape-only rewrote ~430 heading/junk lines as dittos.
#
# WRONG DIRECTION 2 -- and this is the dangerous one. **The same glyph is a ditto in one volume and
# an OCR speck on a COMPLETE entry in another.** From the gold panel, which is a different OCR
# engine across 1786-1933:
#
#     1906BPL   `«* Peter ironwkr h 1355 St Mark s av`      ditto  (given name follows)
#     nyu       `« Douglas Charles. mer. 80 Elm`            SPECK  (surname follows)
#     nyu       `| Devlin Jeremiah, clothier, 33 John`      SPECK
#     nyu       `'Clark Bernard, liquors, 183 Varick`       SPECK
#     polk1917  `" Jno H r205 W141st`                       ditto
#
# Rewriting `'Clark Bernard` to `" Clark Bernard` marks a complete entry as a ditto, and then the
# cross-line pass in postprocess/resolve_dittos.py OVERWRITES `Clark` with the previous line's
# surname. A correct record becomes a confidently wrong one, silently, at scale.
#
# The obvious repair -- look the follower up in the repo's name vocabularies -- does not work
# either: on the panel's 380 non-letter-leading gold rows it is AMBIGUOUS on 188 (52%), because
# `Clark`, `Dick`, `Thomas`, `Henry` are both surnames and given names.
#
# SO THE RULE IS DELIBERATELY CONSERVATIVE, and rests on the one property that IS volume-general:
# **a ditto convention is high-frequency by construction.** It exists to save column inches, so a
# volume that uses one uses it on a large share of lines. A mark leading 0.02% of lines is not that
# volume's convention -- it is OCR noise or a speck. That single threshold rejects the NYU-style
# specks and the ambiguous long tail at once, without needing to classify either.
#
# Measured separation on 1906BPL (share of lines / fraction followed by a name-shaped token):
#
#     44  42.24% 98%  ADMIT      *    0.21% 43%  review      —   0.13% 27%  review
#     “   22.22% 98%  ADMIT      '*   0.16% 99%  review      ‘   0.10% 84%  review
#     "    1.25% 97%  ADMIT      *'   0.14% 98%  review      ”   0.05% 92%  review
#     **   0.61% 98%  ADMIT      4    0.70% 62%  review      .   0.04% 14%  review
#
# THE TRADE IS REAL AND IS NOT PURE GAIN: tightening avoids ~430 wrong rewrites and also gives up
# ~900 correct ones (`'*`, `*'`, `4‘`, `”` are genuine dittos that miss on frequency). That is the
# right side of an asymmetric bet -- a missed ditto leaves the line exactly as the model saw it
# before, while a wrong rewrite corrupts a record AND propagates through the surname carry -- but
# it is a bet, not a free lunch. The near-misses go to the review queue rather than being lost.
DITTO_SHAPE = re.compile(r"^(?:[^\w\s]+|\d{1,3}[^\w\s]?|[^\w\s]?\d{1,3})$")
NAME_FOLLOWER = re.compile(r"^(?:[A-Z][a-z’'.]*|[A-Z])$")
DITTO_FREQ_GATE = 0.05        # digit forms: a leading token on >5% of lines is not a house number
DITTO_MIN_SHARE = 0.005       # punctuation forms: below this it is not a volume's convention
DITTO_MIN_FOLLOWER = 0.70     # and it must actually introduce entries, not headings


def ditto_lead_candidates(texts, gate=DITTO_FREQ_GATE, min_share=DITTO_MIN_SHARE,
                          min_follower=DITTO_MIN_FOLLOWER, confirmed=()):
    """Which leading tokens in THIS volume are ditto marks.

    Returns `(admitted, review, stats, n)`. `review` is every token that looks like a mark but
    missed a threshold -- the queue for later refinement, so a near-miss is deferred rather than
    silently dropped. `stats[token] = (count, share, follower_ratio)`.

    ⚠️ CALIBRATE ON THE WHOLE VOLUME. The gates are shares, so a `--leaves` subset calibrates on
    its own sample and admits a different set. Measured: on the full 1906BPL `"` is 1.25% and is
    admitted; on a 21-leaf slice it is 0.42% and falls to review. Neither answer is a bug -- the
    slice genuinely has less evidence -- but only the whole-volume run is the one to ship. A
    subset run is for inspection.
    """
    counts, follow, n = {}, {}, 0
    for t in texts:
        toks = t.split()
        if not toks:
            continue
        n += 1
        w = toks[0]
        counts[w] = counts.get(w, 0) + 1
        if len(toks) > 1 and NAME_FOLLOWER.match(toks[1]):
            follow[w] = follow.get(w, 0) + 1
    admitted, review, stats = set(), {}, {}
    for w, c in counts.items():
        if not DITTO_SHAPE.match(w):
            continue
        share, ratio = c / max(n, 1), follow.get(w, 0) / c
        stats[w] = (c, share, ratio)
        floor = gate if any(ch.isdigit() for ch in w) else min_share
        # `confirmed` is a human's verdict from a previous run's review queue. It bypasses the
        # SHARE floor (the protection against rare specks, which a person has now ruled out for
        # this volume) but NOT the follower ratio, because that is a property of the data rather
        # than a judgement call -- nobody should be able to promote `—` at 27% by hand.
        if (share > floor or w in confirmed) and ratio >= min_follower:
            admitted.add(w)
        else:
            review[w] = (c, share, ratio)
    return admitted, review, stats, n


def strip_ditto_speck(text, marks):
    """Drop a leading OCR speck when the REAL ditto mark sits right behind it.

        `! 44 Philip meat Wallabout mkt h 687 Quincy`  ->  `44 Philip meat ...`
        `| 44 Sam'l pictures 1092 Bedford av`          ->  `44 Sam'l pictures ...`

    1,021 lines of 1906BPL (0.51%) look like this, and the leading-token rule cannot see any of
    them: position 1 is the speck, position 2 is the mark. They were previously the worst case in
    the file -- no normalization AND two junk tokens into the model.

    This is the SAFE half of the tail, and only because it needs no judgement about the speck
    itself: the mark behind it is one the volume has already proven, so the speck is whatever is
    in front of a known ditto. That is exactly the inference the ambiguous tail does not support.
    """
    toks = text.split(None, 2)
    if len(toks) >= 2 and toks[1] in marks and DITTO_SHAPE.match(toks[0]) \
            and toks[0] not in marks and len(toks[0]) <= 2:
        return " ".join(toks[1:])
    return text


def normalize_ditto_lead(text, marks):
    """Replace a LEADING ditto mark with `"`, the trained form. Leading token only.

    `44` anywhere else in a line is a house number and is never touched. Returns the text
    unchanged when nothing applies, so the caller can test identity to know whether to record
    the original.

    KNOWN GAP, stated rather than guessed at: Trow prints its ditto GLUED to the given name
    (`-Michl`, no space), so it is not a separate leading token and nothing here fires on it.
    That is safe -- the line passes through untouched -- but a Trow volume gets no benefit from
    this. Splitting `-Michl` would need a rule that does not also split real hyphenated surnames,
    which is a different measurement than the one that justified this function.
    """
    toks = text.split(None, 1)
    if not toks or toks[0] not in marks:
        return text
    return '" ' + toks[1] if len(toks) > 1 else '"'


def sweep(item, publisher, year, leaves, use_geometry, margin_tol, join, dropped_fh, out_fh,
          normalize_dittos=True, confirmed_marks=()):
    """Walk leaves, emit kept lines, return (stats, reasons, ad_scores, ditto_report).

    Kept lines are buffered rather than streamed so the ditto-lead frequency gate can see the
    whole volume before deciding which leading tokens are dittos (~50 MB for a 200k-line book).
    Normalization is applied at EMISSION, after every filter has run on the original text, so the
    text/geometry keep-rates documented above stay exactly as measured.
    """
    stats = {"leaves": 0, "raw": 0, "joins": 0, "kept": 0}
    reasons, ad_scores, buffered = {}, [], []
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
            buffered.append((text, leaf, list(box), list(dims) if dims else None))
            stats["kept"] += 1
        if n % 50 == 0:
            print(f"  ... {n}/{len(leaves)} leaves, {stats['kept']:,} lines kept", file=sys.stderr)

    marks, ditto_report = set(), None
    if normalize_dittos:
        marks, review, mark_stats, _total = ditto_lead_candidates(
            (t for t, _, _, _ in buffered), confirmed=confirmed_marks)
        ditto_report = {"marks": sorted(marks), "applied": 0, "despecked": 0,
                        "stats": {w: mark_stats[w] for w in sorted(marks)},
                        "review": dict(sorted(review.items(), key=lambda kv: -kv[1][0])[:40])}
        # one real sample per review token, so a human can judge ditto-vs-speck by reading
        samples = {}
        for text, _, _, _ in buffered:
            tok = text.split()[0] if text.split() else ""
            if tok in ditto_report["review"] and tok not in samples:
                samples[tok] = text[:90]
        ditto_report["samples"] = samples

    for text, leaf, box, dims in buffered:
        out = text
        if marks:
            # De-speck FIRST: `! 44 Philip ...` only becomes normalizable once the speck is gone.
            out = strip_ditto_speck(out, marks)
            despecked = out != text
            out = normalize_ditto_lead(out, marks)
            if despecked:
                ditto_report["despecked"] += 1
        ctx = {
            "publisher": publisher,                  # already a trained token (tag_publisher)
            "directory_year": year or "",
            "ia_id": item.ident,
            "leaf": leaf,
            # hOCR/jp2 pixel space -- scale to any JPEG you download before using as #xywh=
            "bbox": box,
            "page_size": dims,
        }
        if out != text:
            # The audit trail against the page image. Stored only when something changed, so an
            # unnormalized volume costs nothing, and `raw_line` still means "what we fed the model".
            ctx["raw_line_original"] = text
            ditto_report["applied"] += 1
        out_fh.write(json.dumps({"raw_line": out, "context": ctx, "record": EMPTY_RECORD},
                                ensure_ascii=False) + "\n")
    return stats, reasons, ad_scores, ditto_report


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

    # Both hOCR dialects this corpus actually contains. The tesseract form is verbatim from
    # micro_IABROOKLYN_0013 leaf 20; reading it as None left page_size null on that whole volume.
    tess = ('<div class="ocr_page" id="page_000020" title="image '
            '&quot;/tmp/micro_IABROOKLYN_0013_jp2/micro_IABROOKLYN_0013_0020.jp2&quot;; '
            'bbox 0 0 2572 4507; ppageno 0; scan_res 400 400">')
    assert page_dims(tess) == (2572, 4507), page_dims(tess)

    # ---- ditto-lead normalization. Cases are REAL LINES from 1906BPL and micro13, not invented;
    # the apostrophe post-mortem in HANDOFF is about exactly this (a test written from
    # imagination confirms the imagined case).
    #
    # A volume where `44` leads 40% of lines: it is the ditto, and the gate says so.
    dense = (["44 Wm elk h 86 Laf av"] * 40 + ["** Louis clothing 288 Atlantic ay"] * 5
             + [f"Ackerman{i} lab h 1 Main" for i in range(55)])
    marks, review, _, _ = ditto_lead_candidates(dense)
    assert marks == {"44", "**"}, marks
    assert normalize_ditto_lead("44 Wm elk h 86 Laf av", marks) == '" Wm elk h 86 Laf av'
    assert normalize_ditto_lead("** Louis clothing 288 Atlantic ay", marks) == \
        '" Louis clothing 288 Atlantic ay'
    # A volume where 44 is a house number: it is RARE, so the gate must not fire. Without the
    # frequency test this line would silently become a ditto and lose its address.
    sparse = ["44 Broadway grocer"] + [f"Ackerman{i} lab h 1 Main" for i in range(99)]
    marks_sparse, _, _, _ = ditto_lead_candidates(sparse)
    assert marks_sparse == set(), marks_sparse
    assert normalize_ditto_lead("44 Broadway grocer", set()) == "44 Broadway grocer"
    # LEADING token only -- a 44 inside the line is a house number in every volume
    assert normalize_ditto_lead("Ackerman Jos lab h 44 Main", {"44"}) == "Ackerman Jos lab h 44 Main"
    # a real surname is never a mark, whatever the gate decided
    assert normalize_ditto_lead("Ackerman Jos lab h 1 Main", {"44"}) == "Ackerman Jos lab h 1 Main"
    # micro13 (tesseract) has NO 44-lead lines at all; the gate must fire on nothing
    marks_micro, _, _, _ = ditto_lead_candidates([f"Brady John{i}, tavern Jackson" for i in range(50)])
    assert marks_micro == set(), marks_micro
    # a bare mark with nothing after it does not crash
    assert normalize_ditto_lead('44', {"44"}) == '"'

    # ---- the NAME-FOLLOWER test, which is what stops a heading mark being read as a ditto.
    # `—` leads 254 lines of 1906BPL and only 27% introduce an entry (`— Bay Ridge` is a section
    # heading). Shape alone admitted it; the ratio must not.
    headings = ["— Bay Ridge"] * 3 + ["— ■ Telephone Call:"] * 12 + \
               [f"Ackerman{i} lab h 1 Main" for i in range(85)]
    m_h, rev_h, _, _ = ditto_lead_candidates(headings)
    assert "—" not in m_h, "a mark that mostly introduces headings is not a ditto"
    assert "—" in rev_h, "and it belongs in the review queue, not silently dropped"

    # ---- THE CASE THE GOLD PANEL TAUGHT: the same glyph is a ditto in one volume and an OCR
    # speck on a COMPLETE entry in another. These are real nyu_eval lines. Rewriting them would
    # mark a full entry as a ditto and the surname carry would then overwrite `Clark`/`Devlin`.
    nyu = (["'Clark Bernard, liquors, 183 Varick, h. 183 Varick",
            "| Devlin Jeremiah, clothier, 33 John",
            "« Douglas Charles. mer. 80 Elm"]
           + [f"Ackerman{i} lab h 1 Main" for i in range(300)])
    m_nyu, _, _, _ = ditto_lead_candidates(nyu)
    assert m_nyu == set(), f"rare specks must never be admitted as marks: {m_nyu}"

    # ---- speck stripping: safe ONLY because the mark behind it is already proven for the volume
    assert strip_ditto_speck("! 44 Philip meat Wallabout mkt", {"44"}) == "44 Philip meat Wallabout mkt"
    assert strip_ditto_speck("| 44 Sam'l pictures 1092 Bedford av", {"44"}) == \
        "44 Sam'l pictures 1092 Bedford av"
    # nothing behind the speck that is a known mark -> untouched
    assert strip_ditto_speck("| Devlin Jeremiah, clothier", {"44"}) == "| Devlin Jeremiah, clothier"
    # the speck must be short and mark-shaped; a real leading word is never stripped
    assert strip_ditto_speck("No. 44 Philip meat", {"44"}) == "No. 44 Philip meat"
    # and de-specking then normalizing composes to the intended end state
    assert normalize_ditto_lead(strip_ditto_speck("! 44 Philip meat", {"44"}), {"44"}) == \
        '" Philip meat'

    # ---- --ditto-marks: a human promoting a mark from the review queue. `'*` is 0.16% of
    # 1906BPL (below the share floor) but 99% name-followed, so it is a real ditto the gate
    # gives up. Confirming it must work...
    rare = (["'* Peroxide & Chemical Co 356 13th"]                    # 1 of 401 = 0.25%
            + [f"Ackerman{i} lab h 1 Main" for i in range(400)])
    assert "'*" not in ditto_lead_candidates(rare)[0], "rare mark is not admitted by default"
    assert "'*" in ditto_lead_candidates(rare, confirmed=("'*",))[0], "a human can confirm it"
    # ...but confirming must NOT be able to override the follower ratio, which is a property of
    # the data rather than a judgement. `—` introduces headings 73% of the time on 1906BPL.
    heads = ["— ■ Telephone Call:"] * 30 + [f"Ackerman{i} lab h 1 Main" for i in range(70)]
    assert "—" not in ditto_lead_candidates(heads, confirmed=("—",))[0], \
        "a heading mark must not be promotable by hand"

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
    ap.add_argument("--no-ditto-normalize", action="store_true",
                    help="do NOT rewrite a leading ditto mark to '\"'. Default is to rewrite it: "
                         "measured p=0.0010 that the OCR'd form makes the model swallow the "
                         "occupation into the name (results/ab_ditto44_1906BPL_2b100k*). Digit "
                         "forms must clear a >5%% leading-token frequency gate, so a real house "
                         "number is never touched. Originals go to context.raw_line_original.")
    ap.add_argument("--ditto-marks", default=None,
                    help="comma-separated marks a HUMAN confirmed from a previous run's "
                         "--ditto-review queue. Bypasses the share floor for those tokens only; "
                         "the name-follower ratio still applies, so a heading mark cannot be "
                         "promoted by hand. Record the volume it was decided for.")
    ap.add_argument("--ditto-review", default=None,
                    help="write the mark-shaped tokens that were NOT rewritten, with counts, "
                         "share, name-follower ratio and a sample line each. The queue for "
                         "refining coverage later without guessing at glyphs.")
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
        stats, reasons, ad_scores, ditto_report = sweep(
            item, publisher, year, leaves, not args.no_geometry, args.drop_off_margin,
            not args.no_join, dropped_fh, out_fh, not args.no_ditto_normalize,
            confirmed_marks=tuple(args.ditto_marks.split(",")) if args.ditto_marks else ())
    if dropped_fh:
        dropped_fh.close()

    entries = stats["raw"] - stats["joins"]                # lines after wrapped ones are merged
    pct = 100 * stats["kept"] / entries if entries else 0
    print(f"\n{stats['leaves']} leaves | {stats['raw']:,} hOCR lines "
          f"- {stats['joins']:,} wrap-joins = {entries:,} candidate entries "
          f"-> {stats['kept']:,} kept ({pct:.1f}% of candidates)", file=sys.stderr)
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"    dropped {n:>7,}  {why}", file=sys.stderr)
    if ditto_report is not None:
        if ditto_report["marks"]:
            adm = ", ".join(f"{w!r} {ditto_report['stats'][w][1]:.1%}/{ditto_report['stats'][w][2]:.0%}"
                            for w in ditto_report["marks"])
            print(f"  ditto-lead normalized -> '\"' on {ditto_report['applied']:,} lines "
                  f"({ditto_report['applied']/max(stats['kept'],1):.1%}), of which "
                  f"{ditto_report['despecked']:,} needed a leading speck stripped first",
                  file=sys.stderr)
            print(f"    admitted (share/name-follower): {adm}", file=sys.stderr)
            print(f"    originals kept in context.raw_line_original", file=sys.stderr)
        else:
            print("  ditto-lead normalization: no mark cleared the gates (nothing changed)",
                  file=sys.stderr)
        if args.ditto_review and ditto_report["review"]:
            with open(args.ditto_review, "w", encoding="utf-8") as fh:
                fh.write("token\tlines\tshare\tname_follower\tsample_line\n")
                for w, (c, s, r) in ditto_report["review"].items():
                    fh.write(f"{w}\t{c}\t{s:.4f}\t{r:.2f}\t"
                             f"{ditto_report['samples'].get(w,'')}\n")
            print(f"  ditto review queue -> {args.ditto_review}", file=sys.stderr)
        if ditto_report["review"]:
            top = list(ditto_report["review"].items())[:6]
            shown = ", ".join(f"{w!r} {c:,} ({s:.2%}/{r:.0%})" for w, (c, s, r) in top)
            print(f"  ⚠ REVIEW QUEUE — {len(ditto_report['review'])} mark-shaped tokens missed a "
                  f"threshold and were NOT rewritten:\n      {shown}", file=sys.stderr)
            print(f"      Deliberate: a ditto convention is high-frequency, so a rare mark is more "
                  f"likely an OCR speck on a complete entry (see the module comment). "
                  f"--ditto-review PATH dumps all of them with samples.", file=sys.stderr)
    if ad_scores:
        worst = sorted(ad_scores, key=lambda kv: -kv[1])[:8]
        print(f"  highest ad-scores (leaf, big%+wide%): {worst}", file=sys.stderr)
        print("    -- spot-check those leaves; a high score is display advertising or a "
              "section-heading page, both of which produce fake entries.", file=sys.stderr)
    print(f"\nwrote {out_path}", file=sys.stderr)
    if dropped_fh:
        print(f"rejected lines -> {args.dump_dropped}  (READ THIS: the geometry stage is "
              f"uncalibrated and can cut real entries)", file=sys.stderr)
    # 4b-100k is the release candidate (SCALE_RUNS.md), so it is what the hint recommends -- but
    # say what it costs. Only the 0.8B and 2B bases are cached locally; the 4B directory in the HF
    # cache is a 24 KB stub with no safetensors, so this line starts an ~8 GB download, and on a
    # 16 GB machine the 4B then has almost no headroom. 2b-100k is the cheap comparable.
    print(f"\nnext: python3 eval/qwen_predict.py --base-model Qwen/Qwen3.5-4B \\\n"
          f"        --model ~/Downloads/scale-runs/adapters/4b-100k \\\n"
          f"        --gold {out_path} --target yaml --batch-size 128\n"
          f"      (4B base is NOT cached -- ~8 GB download. For a quick look swap in\n"
          f"       Qwen/Qwen3.5-2B + adapters/2b-100k, which is cached and ~1 point behind.)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
