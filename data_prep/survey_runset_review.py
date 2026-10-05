#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
The run set's close calls, side by side: for each edition held twice where the choice of copy is
close, the same printed lines as each copy's scan shows them and as its OCR read them.

    python3 data_prep/survey_runset_review.py       # -> results/runset_review.html + .json

WHY (2026-10-02). `survey_twins.py pairs` recommends which copy of each of 17 editions the
corpus run reads: the whole alphabet first, then the most lines per page. Five picks are close.
In four, the copies deliver within 5% of each other's lines per page (Trow 1903 p2, Longworth
1839, Brooklyn 1843-44, Franks 1786). In Ogden 1839, a third of the chosen book scan's lines sit
on pages the ad-leaf inventory flags as non-entry. Lines per page cannot settle these, because
it counts what an OCR emitted, not whether it read the page. `duplicate-of` is stamped only on
hadro's word, so this puts the evidence in front of him:

  per copy   the scan, its OCR engine, what its title page says it is, listing pages, scoped
             lines, entry-shaped OCR lines (survey_adleaves.ENTRY_RX, the inventory's measure),
             scoped lines on flagged non-entry pages, and the gold lines it reads exactly where
             a gold set covers the edition (results/survey_twins_gold.json)
  per pair   pages aligned by survey_twins.leaf_map, and listing pages one copy holds that the
             other does not place
  excerpts   up to EXCERPT_LINES lines of the chosen copy and the same printed lines in each
             other copy: the IIIF crop of each scan beside its OCR, each line marked by whether
             another copy (or the gold) reads it identically. Pages are drawn at random (seeded)
             from the aligned listing pages, plus the pages where the copies' entry-shaped line
             counts differ most, plus each edition's gold page

Offline: reads results/survey_twins_pairs.json, results/survey_twins_gold.json, the sidecars,
data/survey_ocr/ (scoped lines, candidate lines, adleaf_features.jsonl.gz) and the gold sets.
The images are IIIF URLs the browser fetches.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import difflib
import gzip
import html
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
OCR = DATA / "survey_ocr"
SIDECARS = HERE / "survey"
RESULTS = REPO / "results"
sys.path.insert(0, str(HERE))

from survey_adleaves import ENTRY_RX, page_kind  # noqa: E402
from survey_twins import git_rev, hash_volume, leaf_map, norm  # noqa: E402

IIIF = "https://iiif.archive.org/iiif"
SEED = 20261002
CLOSE = [   # (edition, the copy the pairs pass chose); the other copies come from its edition
    ("Trow 1903, part 2 (H-R)", "trowsgeneraldir1903p2trow"),
    ("Longworth 1839-40", "longworthsameric00newy"),
    ("Brooklyn 1843-44 (Hearne)", "micro_IABROOKLYN_0019"),
    ("Franks 1786, New York's first directory: four reprints", "newyorkdirectory00fran"),
    ("Ogden 1839-40, Brooklyn", "brooklyndirector00ogde"),
]
EXCERPT_LINES = 10      # lines of the chosen copy per excerpt
RANDOM_PAGES = 2        # seeded-random aligned listing pages per pair
GAP_MIN = 8             # entry-shaped lines one copy must lead by before its page is shown
COL_TOL = 0.12          # a line is in the anchor's column when its left edge is this near (page widths)
MATCH_FLOOR = 0.5       # two OCR lines align when their normalised texts are this similar
SAME = 0.999            # ...and read alike at this ratio (normalisation already ate punctuation)
CLOSE_READ = 0.8
SPAN_MATCH = 0.6        # matched pairs this good carry the printed span from scan to scan
GOLD_CUT = 0.6          # on a gold page, each copy ends at its last line this like the gold
ALIGNED_SHARE = 0.8     # leaf_map partners used as aligned pages: consistent, at this share


# ---------------------------------------------------------------- data

def sidecar(ident: str) -> dict:
    return json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))


def scoped_rows(ident: str) -> dict:
    """leaf -> the scoped lines the model would read, each {text, bbox, page_size}."""
    out = collections.defaultdict(list)
    with gzip.open(OCR / f"{ident}_listing.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            c = r["context"]
            if c.get("bbox"):
                out[c["leaf"]].append({"text": r["raw_line"], "bbox": c["bbox"],
                                       "page_size": c.get("page_size")})
    return out


def load_features(idents: set) -> dict:
    out = collections.defaultdict(dict)
    with gzip.open(OCR / "adleaf_features.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["id"] in idents:
                out[r.pop("id")][r["leaf"]] = r
    return out


def kinds(feats: dict) -> dict:
    """leaf -> blank / listing / non-entry, by the inventory's own rule and volume median."""
    shares = sorted(r["entry_share"] for r in feats.values() if not r["blank"])
    median = shares[len(shares) // 2] if shares else 0.0
    return {leaf: page_kind(r, median) for leaf, r in feats.items()}


def entry_lines(r: dict) -> int:
    return 0 if r["blank"] else round(r["entry_share"] * r["lines"])


def gold_sets(members: list) -> list:
    """The gold sets whose own volume or a twin is in this edition, with each copy's exact and
    fuzzy shares as survey_twins.py gold measured them, and the gold rows by leaf of the own
    volume."""
    G = json.loads((RESULTS / "survey_twins_gold.json").read_text(encoding="utf-8"))
    out = []
    for name, s in G["sets"].items():
        # own volume and twins only: a `check` is a neighbouring edition (ogden1839 lists the
        # 1843-44 Brooklyn copies), and its share says nothing about this edition's copies
        same = [v for v in s["volumes"]
                if v["verdict"] in ("own", "twin") or v.get("verified") == "twin"]
        if not ({s["own"]} | {v["id"] for v in same}) & set(members):
            continue
        shares = {v["id"]: {"exact": v["exact_share"], "fuzzy": v.get("fuzzy_share"),
                            "leaves": v.get("leaves")} for v in same}
        rows = collections.defaultdict(list)
        for line in (DATA / s["file"]).read_text(encoding="utf-8").splitlines():
            g = json.loads(line)
            m = re.search(r"_(\d{4})\.jp2", g["context"].get("image") or "")
            if m:
                rows[int(m.group(1))].append(g["raw_line"])
        out.append({"set": name, "file": s["file"], "own": s["own"], "rows": s["rows"],
                    "shares": shares, "by_leaf": dict(rows)})
    return out


# ---------------------------------------------------------------- matching

def ratio(a: str, b: str) -> float:
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return m.ratio() if m.real_quick_ratio() >= MATCH_FLOOR and m.quick_ratio() >= MATCH_FLOOR \
        else 0.0


def align(a: list, b: list) -> list:
    """Monotone alignment of two line lists maximising summed similarity (no gap cost):
    [(i, j, ratio)] for the pairs at MATCH_FLOOR or better."""
    A, B = [norm(x) for x in a], [norm(x) for x in b]
    sim = [[ratio(x, y) for y in B] for x in A]
    na, nb = len(A), len(B)
    S = [[0.0] * (nb + 1) for _ in range(na + 1)]
    step = [[None] * (nb + 1) for _ in range(na + 1)]
    for i in range(na - 1, -1, -1):
        for j in range(nb - 1, -1, -1):
            options = [(S[i + 1][j], "a"), (S[i][j + 1], "b")]
            if sim[i][j] >= MATCH_FLOOR:
                options.append((sim[i][j] + S[i + 1][j + 1], "m"))
            S[i][j], step[i][j] = max(options)
    pairs, i, j = [], 0, 0
    while i < na and j < nb:
        s = step[i][j]
        if s == "m":
            pairs.append((i, j, sim[i][j]))
            i, j = i + 1, j + 1
        elif s == "a":
            i += 1
        else:
            j += 1
    return pairs


def best_line(target: str, rows: list):
    """The row reading most like `target`: an exact normalised match if there is one."""
    t = norm(target)
    for r in rows:
        if norm(r["text"]) == t:
            return r, 1.0
    best, score = None, 0.0
    for r in rows:
        s = ratio(t, norm(r["text"]))
        if s > score:
            best, score = r, s
    return best, score


def column_from(rows: list, anchor: dict, n: int) -> list:
    """`n` lines from `anchor` down its column, by top edge."""
    x0, y0 = anchor["bbox"][0], anchor["bbox"][1]
    w = (anchor.get("page_size") or [max(r["bbox"][2] for r in rows)])[0]
    col = [r for r in rows if abs(r["bbox"][0] - x0) <= COL_TOL * w and r["bbox"][1] >= y0 - 5]
    col.sort(key=lambda r: r["bbox"][1])
    return col[:n]


# ---------------------------------------------------------------- excerpts

def _median(xs: list) -> float:
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def same_span(ref: list, win: list):
    """The lines of `win` (another scan, read from the same anchor down its column) that cover
    the printed span of `ref`, and where that span ends on `win`'s page.

    The scans differ in resolution and framing, so the span is carried across by the median
    slope of the matched pairs below the anchor (a pair's position is right even when its text
    is garbled), or failing any, by the ratio of the two scans' median line heights. Cutting
    where the text alignment ends was tried first: a copy whose OCR garbled lines matched short
    lines further down at 0.5, and its window ran nine lines past the printed span (Trow 1903
    p2 leaf 897). The end is returned because the crop must show the whole span: a line the
    OCR dropped is the point of the picture (Ogden leaf 89, where the microfilm OCR read six
    lines of ten)."""
    pairs = align([r["text"] for r in ref], [r["text"] for r in win])
    ry0, oy0 = ref[0]["bbox"][1], win[0]["bbox"][1]
    slopes = [(win[j]["bbox"][1] - oy0) / (ref[i]["bbox"][1] - ry0) for i, j, s in pairs
              if s >= SPAN_MATCH and i > 0 and ref[i]["bbox"][1] > ry0 and win[j]["bbox"][1] > oy0]
    h_other = _median([r["bbox"][3] - r["bbox"][1] for r in win])
    scale = _median(slopes) if slopes else \
        h_other / max(1.0, _median([r["bbox"][3] - r["bbox"][1] for r in ref]))
    end = oy0 + (ref[-1]["bbox"][3] - ry0) * scale
    return [r for r in win if r["bbox"][1] < end - 0.4 * h_other], end


def region(rows: list, end: float | None = None) -> dict:
    """The page box a crop shows: the lines' union, run down to `end` where a span was carried."""
    box = [min(r["bbox"][0] for r in rows), min(r["bbox"][1] for r in rows),
           max(r["bbox"][2] for r in rows), max(r["bbox"][3] for r in rows)]
    if end is not None:
        box[3] = max(box[3], int(end))
    return {"leaf": rows[0]["leaf"], "box": box, "page_size": rows[0].get("page_size")}


def excerpt(run: str, run_rows: list, others: dict, title: str, rng: random.Random,
            reference: list | None = None) -> dict | None:
    """EXCERPT_LINES lines of the chosen copy and the same printed lines in each other copy.

    `others` maps a copy to the rows to look in (its partner page, or every scoped line when
    the copies' pages do not align). The anchor is a line every other copy reads identically
    where one exists, else the line they read most alike. Every crop then shows the same
    printed span (`same_span`). With `reference` (gold rows), the gold is the anchor and the
    yardstick, and each copy is cut at its last line matching the gold strongly."""
    if not run_rows:
        return None
    if reference:
        anchors = [(None, reference[0])]
    else:
        cands = [r for r in sorted(run_rows, key=lambda r: (r["bbox"][0] // 400, r["bbox"][1]))
                 if ENTRY_RX.search(r["text"]) and len(column_from(run_rows, r, EXCERPT_LINES))
                 == EXCERPT_LINES]
        rng.shuffle(cands)
        anchors = [(r, r["text"]) for r in cands[:60]]
    best, best_score = None, -1.0
    for row, text in anchors:
        hits = {run: (row, 1.0) if row else best_line(text, run_rows)}
        hits.update({o: best_line(text, rows) for o, rows in others.items()})
        score = min(s for _r, s in hits.values())
        if score > best_score:
            best, best_score = hits, score
        if score >= SAME:
            break
    if best is None:
        return None
    pool = {run: run_rows, **others}
    windows = {}
    for c in [run, *others]:
        row = best[c][0]
        if row is not None:
            windows[c] = column_from([r for r in pool[c] if r["leaf"] == row["leaf"]], row,
                                     EXCERPT_LINES * 3)
    panels, regions = {}, {}
    if reference:
        base = reference[:EXCERPT_LINES]
        for c, win in windows.items():
            strong = [j for _i, j, s in align(base, [r["text"] for r in win]) if s >= GOLD_CUT]
            if strong:
                panels[c] = win[:max(strong) + 1]
                regions[c] = region(panels[c])
    else:
        ref = windows.get(run, [])[:EXCERPT_LINES]
        if not ref:
            return None
        panels[run], regions[run] = ref, region(ref)
        for c, win in windows.items():
            if c == run:
                continue
            cut, end = same_span(ref, win)
            if cut:
                panels[c], regions[c] = cut, region(cut, end)
    # mark each line: does another copy (or the gold) read it identically, or nearly?
    yard = {c: [norm(r["text"]) for r in rows] for c, rows in panels.items()}
    for c, rows in panels.items():
        refs = [norm(t) for t in reference] if reference else \
            [t for o, ts in yard.items() if o != c for t in ts]
        for r in rows:
            t = norm(r["text"])
            s = 1.0 if t in refs else max((ratio(t, x) for x in refs), default=0.0)
            r["mark"] = "same" if s >= SAME else "close" if s >= CLOSE_READ else "differs"
    return {"title": title, "anchor_score": round(best_score, 3), "reference": reference,
            "panels": {c: [{**r} for r in rows] for c, rows in panels.items()},
            "regions": regions}


def with_leaf(rows_by_leaf: dict, leaves) -> list:
    return [{**r, "leaf": leaf} for leaf in leaves for r in rows_by_leaf.get(leaf, [])]


# ---------------------------------------------------------------- per edition

def edition_for(ident: str, editions: list) -> dict:
    for e in editions:
        if any(m["id"] == ident for m in e["members"]):
            return e
    raise SystemExit(f"{ident}: in no edition of results/survey_twins_pairs.json")


def copy_card(m: dict, feats: dict, golds: list, picked: bool) -> dict:
    d = sidecar(m["id"])
    ia = (d.get("catalog_says") or {}).get("ia") or {}
    bs = d.get("book_says") or {}
    says = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in bs.items()
            if k in ("year_covered", "year_published", "reprint_year", "stated_name_count")}
    title_quote = (bs.get("title") or {}).get("value") if isinstance(bs.get("title"), dict) \
        else bs.get("title")
    k = kinds(feats)
    ne = d.get("non_entry_pages") or {}
    gold = {}
    for g in golds:
        if m["id"] in g["shares"]:
            gold[g["set"]] = g["shares"][m["id"]]
        elif m["id"] == g["own"]:
            gold[g["set"]] = {"exact": None, "fuzzy": None}
    return {"id": m["id"], "run": picked, "contributor": ia.get("contributor"),
            "ocr": m["ocr"] or "none recorded (legacy derive)", "ia_date": m["ia_date"],
            "title_quote": title_quote, "says": says, "letters": m["letters"], "whole": m["whole"],
            "listing_pages": sum(1 for v in k.values() if v == "listing"),
            "non_entry_pages": sum(1 for v in k.values() if v == "non-entry"),
            "blank_pages": sum(1 for v in k.values() if v == "blank"),
            "scoped_lines": (d.get("scope") or {}).get("kept"),
            "lines_per_leaf": m["lines_per_leaf"],
            "entry_lines": sum(entry_lines(r) for r in feats.values()),
            "non_entry_lines": ne.get("scoped_lines") or 0,
            "non_entry_leaves": ne.get("leaves") or [],
            "gold": gold}


def review_edition(label: str, run: str, editions: list, feats: dict, rng: random.Random) -> dict:
    e = edition_for(run, editions)
    # the measured pick, so the page reproduces as reviewed once hadro's decisions are stamped
    pick = e.get("recommended") or e["run"]
    members = [m for m in e["members"] if m["survey_status"] != "not-residential"]
    members.sort(key=lambda m: (m["id"] not in pick, m["id"]))
    ids = [m["id"] for m in members]
    golds = gold_sets(ids)
    cards = [copy_card(m, feats[m["id"]], golds, m["id"] in pick) for m in members]
    rows = {i: scoped_rows(i) for i in ids}
    hashed = {i: dict(zip(("ident", "kind", "n", "text_leaves", "hs", "ls"), hash_volume(i, True)))
              for i in ids}
    K = {i: kinds(feats[i]) for i in ids}

    pairs, maps, gaps = [], {}, {}
    for other in ids[1:]:
        lm = leaf_map(hashed[run], hashed[other])
        aligned = {a: v["leaf"] for a, v in lm.items()
                   if v.get("consistent") and v["share"] >= ALIGNED_SHARE}
        both = [a for a, b in aligned.items()
                if K[run].get(a) == "listing" and K[other].get(b) == "listing"]
        maps[other] = aligned
        gaps[other] = {a: entry_lines(feats[other][aligned[a]]) - entry_lines(feats[run][a])
                       for a in both if aligned[a] in feats[other] and a in feats[run]}
        partners = set(aligned.values())
        pairs.append({
            "other": other, "aligned_pages": len(aligned), "aligned_listing_pages": len(both),
            "entry_lines_run": sum(entry_lines(feats[run][a]) for a in both if a in feats[run]),
            "entry_lines_other": sum(entry_lines(feats[other][aligned[a]]) for a in both
                                     if aligned[a] in feats[other]),
            "run_unplaced": sorted(a for a, v in K[run].items()
                                   if v == "listing" and a not in aligned),
            "other_unplaced": sorted(b for b, v in K[other].items()
                                     if v == "listing" and b not in partners),
            "leaf_map": {a: aligned[a] for a in sorted(aligned)}})

    def near(c: str, leaves) -> list:
        """Rows of copy `c` on these leaves and their neighbours, each leaf once."""
        return with_leaf(rows[c], sorted({x for lf in leaves for x in (lf - 1, lf, lf + 1)}))

    def pool(c: str, run_leaf: int) -> list:
        """Where copy `c` prints what the pick prints on `run_leaf`: its aligned partner page,
        or, where its pages do not align (the Franks reprints re-set the type), anywhere."""
        b = maps[c].get(run_leaf)
        return near(c, [b]) if b else with_leaf(rows[c], sorted(rows[c]))

    excerpts = []
    listing = sorted(a for a, v in K[run].items() if v == "listing" and rows[run].get(a))
    if len(ids) == 2:
        other = ids[1]
        both = sorted(a for a in gaps[other])
        picks = [(a, "a page drawn at random") for a in rng.sample(both, min(RANDOM_PAGES,
                                                                             len(both)))]
        gap = gaps[other]
        if gap:
            lo, hi = min(gap, key=gap.get), max(gap, key=gap.get)
            if gap[hi] >= GAP_MIN:
                picks.append((hi, f"the page where {other} leads most "
                                  f"({gap[hi]:+d} entry-shaped lines)"))
            if -gap[lo] >= GAP_MIN:
                picks.append((lo, f"the page where {run} leads most "
                                  f"({-gap[lo]:+d} entry-shaped lines)"))
    else:   # several copies: the same entries in all of them
        picks = [(a, "a page drawn at random, and the same entries in every copy")
                 for a in rng.sample(listing, min(RANDOM_PAGES, len(listing)))]
    for a, why in picks:
        ex = excerpt(run, with_leaf(rows[run], [a]), {c: pool(c, a) for c in ids[1:]},
                     f"{run} leaf {a}: {why}", rng)
        if ex:
            excerpts.append(ex)

    # the gold page: the one place the truth is known
    for g in golds:
        leaf, ref = max(g["by_leaf"].items(), key=lambda kv: len(kv[1]))
        where = {c: (g["shares"].get(c) or {}).get("leaves") for c in ids}
        where[g["own"]] = [leaf]
        others = {c: near(c, where[c]) if where[c] else with_leaf(rows[c], sorted(rows[c]))
                  for c in ids if c != run}
        run_pool = near(run, where[run]) if where[run] else with_leaf(rows[run], sorted(rows[run]))
        ex = excerpt(run, run_pool, others, f"the gold page ({g['file']}, {g['own']} leaf {leaf}): "
                                            f"marks compare each line with the hand-corrected gold",
                     rng, reference=ref)
        if ex:
            excerpts.append(ex)

    flagged = {}
    for c in cards:
        if c["non_entry_leaves"]:
            leaf = rng.choice(c["non_entry_leaves"])
            flagged[c["id"]] = {"leaf": leaf, "lines": [r["text"] for r in rows[c["id"]].get(leaf, [])][:4]}
    return {"edition": label, "run": pick, "spare_lines": e["spare_lines"],
            "close_call": e["close_call"], "attested_years": e["attested_years"],
            "copies": cards, "pairs": pairs, "excerpts": excerpts, "flagged_sample": flagged}


# ---------------------------------------------------------------- html

def iiif(ident: str, leaf: int, region: str = "full", size: str = "!700,700") -> str:
    """`!w,h` fits within and never upscales: IIIF 403s a request to scale past 100%
    (survey_frontmatter.page_image)."""
    return f"{IIIF}/{ident}${leaf}/{region}/{size}/0/default.jpg"


def crop(ident: str, reg: dict, size: str = "!760,560") -> str:
    """The crop of a region, padded wider on the left, where an OCR that missed a line's first
    letter would otherwise cut the printed letter off (Longworth 1839 leaf 82: `allou` for
    Ballou)."""
    x0, y0, x1, y1 = reg["box"]
    w, h = reg.get("page_size") or [x1 + 100, y1 + 100]
    pad = 24
    x0, y0 = max(0, x0 - max(pad, int(0.03 * w))), max(0, y0 - pad)
    x1, y1 = min(w, x1 + pad), min(h, y1 + pad)
    return iiif(ident, reg["leaf"], f"{x0},{y0},{x1 - x0},{y1 - y0}", size)


def esc(x) -> str:
    return html.escape(str(x))


def fmt(n) -> str:
    return "—" if n is None else f"{n:,}" if isinstance(n, int) else esc(n)


CSS = """
body{font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;color:#1d1d1f;
background:#fafafa}
main{max-width:1500px;margin:0 auto;padding:24px 28px 60px}
h1{font-size:24px;margin:0 0 6px} h2{font-size:20px;margin:42px 0 6px;padding-top:18px;
border-top:2px solid #d0d0d6} h3{font-size:15px;margin:22px 0 8px;color:#333}
p{max-width:980px} .muted{color:#666} code{font:12.5px ui-monospace,Menlo,monospace}
table{border-collapse:collapse;margin:8px 0 14px;background:#fff}
th,td{border:1px solid #dcdce2;padding:5px 8px;text-align:left;vertical-align:top;font-size:13px}
th{background:#f0f0f4;font-weight:600} td.n{text-align:right;font-variant-numeric:tabular-nums}
tr.run td:first-child{border-left:4px solid #2f6fd6}
.pick{display:inline-block;background:#2f6fd6;color:#fff;border-radius:3px;padding:0 5px;
font-size:11px;margin-left:4px}
.note{background:#fff8e6;border:1px solid #f0d9a0;border-radius:6px;padding:10px 14px;
max-width:980px}
.grid{display:grid;gap:14px;align-items:start}
.panel{background:#fff;border:1px solid #dcdce2;border-radius:6px;padding:10px;min-width:0}
.panel h4{margin:0 0 6px;font-size:13px} .panel img{max-width:100%;display:block;
border:1px solid #eee;margin-bottom:8px;background:#f4f4f4}
.ocr{font:12px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;word-break:break-word}
.ocr div{padding:0 4px;border-left:4px solid transparent}
.same{border-left-color:#3a9a4a!important;background:#eef8ef}
.close{border-left-color:#d9a400!important;background:#fdf6df}
.differs{border-left-color:#c8442f!important;background:#fbecea}
.gold div{border-left-color:#888!important;background:#f3f3f3}
.thumbs{display:flex;gap:14px;flex-wrap:wrap} .thumbs figure{margin:0;background:#fff;
border:1px solid #dcdce2;border-radius:6px;padding:8px;max-width:340px}
.thumbs img{max-width:320px;max-height:420px;display:block} figcaption{font-size:12px;
color:#555;margin-top:4px}
.legend span{display:inline-block;padding:0 6px;margin-right:6px;border-left:4px solid}
"""


def render(report: dict, notes: dict) -> str:
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>Run-set close calls"
           f"</title><style>{CSS}</style></head><body><main>",
           "<h1>Run-set close calls: which copy of each edition the corpus run reads</h1>",
           f"<p class='muted'>Generated {esc(report['derived'])} by "
           f"<code>data_prep/survey_runset_review.py</code> at {esc(report['code_at'])}, from "
           f"the run set <code>survey_twins.py pairs</code> recommended on "
           f"{esc(report['pairs_derived'])}.</p>",
           "<p>For every edition held in more than one scan, the pairs pass picks one copy to run: "
           "the whole alphabet first, then the most lines per page. That rule counts what an OCR "
           "emitted, not whether it read the page, so it cannot separate the five copies below. "
           "<code>duplicate-of</code> is only stamped on your word, and "
           "<code>hpc/prep_volumes.py</code> needs the run set before staging the corpus.</p>",
           "<p class='legend'>Each excerpt shows the same printed lines in every copy: the "
           "scan's crop, then the OCR lines the model would read. Marks compare each line with "
           "the other copies (or, on a gold page, with the hand-corrected gold): "
           "<span class='same'>read identically</span><span class='close'>nearly (ratio ≥ 0.8)"
           "</span><span class='differs'>differently</span>. Two OCRs agreeing usually means "
           "both are right, but copies set in the same typeface can share a misreading (the "
           "Franks long s, read as f in three copies at once). Where they differ, the crop shows "
           "which one is right. <b>Entry-shaped lines</b> is "
           "the ad-page inventory's measure (a residence marker with a number, a name then an "
           "address, and so on), counted over every listing page.</p>"]
    out.append("<h3>The five at a glance</h3><table><tr><th>edition</th><th>copies</th>"
               "<th>current pick</th><th>my suggestion</th></tr>")
    for ed in report["editions"]:
        n = notes.get(ed["run"][0] if ed["run"] else "", {})
        out.append(f"<tr><td><a href='#{esc(ed['run'][0])}'>{esc(ed['edition'])}</a></td>"
                   f"<td class='n'>{len(ed['copies'])}</td><td><code>{esc(', '.join(ed['run']))}"
                   f"</code></td><td>{n.get('pick', '—')}</td></tr>")
    out.append("</table>")
    for ed in report["editions"]:
        out.append(edition_html(ed, notes.get(ed["run"][0], {})))
    out.append(clear_html(report["clear"]))
    out.append("</main></body></html>")
    return "\n".join(out)


def edition_html(ed: dict, note: dict) -> str:
    run = ed["run"][0]
    o = [f"<h2 id='{esc(run)}'>{esc(ed['edition'])}</h2>",
         f"<p class='muted'>{len(ed['copies'])} copies; {ed['spare_lines']:,} scoped lines in "
         f"the copies not chosen. Title-page years read: "
         f"{esc(', '.join(map(str, ed['attested_years'])) or 'none')}."
         f"</p>"]
    if note.get("read"):
        o.append(f"<div class='note'><b>My read.</b> {note['read']}</div>")
    golds = sorted({g for c in ed["copies"] for g in c["gold"]})
    o.append("<table><tr><th>copy</th><th>scan · OCR · IA date</th><th>title page says</th>"
             "<th>letters</th><th>listing pages</th><th>scoped lines</th><th>lines / page</th>"
             "<th>entry-shaped lines</th><th>scoped lines on flagged non-entry pages</th>"
             + "".join(f"<th>gold {esc(g)}: exact / ≥0.8</th>" for g in golds) + "</tr>")
    for c in ed["copies"]:
        says = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in c["says"].items())
        quote = f"“{esc((c['title_quote'] or '')[:70])}”" if c["title_quote"] else ""
        gold_cells = ""
        for g in golds:
            s = c["gold"].get(g)
            if s is None:
                gold_cells += "<td class='n'>under 3 lines exact</td>"
            elif s.get("exact") is None:
                gold_cells += "<td class='n'>(own volume)</td>"
            else:
                fz = f"{s['fuzzy']:.0%}" if s.get("fuzzy") is not None else "—"
                gold_cells += f"<td class='n'>{s['exact']:.0%} / {fz}</td>"
        o.append(f"<tr class='{'run' if c['run'] else ''}'><td><a href='https://archive.org/"
                 f"details/{esc(c['id'])}'><code>{esc(c['id'])}</code></a>"
                 f"{'<span class=pick>pick</span>' if c['run'] else ''}</td>"
                 f"<td>{esc(c['contributor'] or '')}<br>{esc(c['ocr'])} · {esc(c['ia_date'])}</td>"
                 f"<td>{esc(says)}<br><span class='muted'>{quote}</span></td>"
                 f"<td>{esc(c['letters'])}{'' if c['whole'] else ' (part)'}</td>"
                 f"<td class='n'>{fmt(c['listing_pages'])}</td>"
                 f"<td class='n'>{fmt(c['scoped_lines'])}</td>"
                 f"<td class='n'>{c['lines_per_leaf']:.1f}</td>"
                 f"<td class='n'>{fmt(c['entry_lines'])}</td>"
                 f"<td class='n'>{fmt(c['non_entry_lines'])} on {len(c['non_entry_leaves'])}</td>"
                 f"{gold_cells}</tr>")
    o.append("</table>")
    for p in ed["pairs"]:
        o.append(f"<p><b><code>{esc(run)}</code> against <code>{esc(p['other'])}</code>:</b> "
                 f"{p['aligned_pages']:,} pages aligned, {p['aligned_listing_pages']:,} of them "
                 f"listing pages in both. On those, entry-shaped lines "
                 f"{p['entry_lines_run']:,} against {p['entry_lines_other']:,}. Listing pages the "
                 f"other copy does not place: {len(p['run_unplaced'])} in the pick, "
                 f"{len(p['other_unplaced'])} in <code>{esc(p['other'])}</code>.</p>")
    for ex in ed["excerpts"]:
        o.append(excerpt_html(ex))
    if ed["flagged_sample"]:
        o.append("<h3>A page each copy has flagged non-entry, drawn at random</h3><div class='thumbs'>")
        for c, f in ed["flagged_sample"].items():
            lines = "<br>".join(esc(t[:60]) for t in f["lines"])
            o.append(f"<figure><a href='{iiif(c, f['leaf'], 'full', '!2000,2000')}'>"
                     f"<img loading='lazy' src='{iiif(c, f['leaf'], 'full', '!600,600')}'></a>"
                     f"<figcaption><code>{esc(c)}</code> leaf {f['leaf']}<br>"
                     f"<span class='ocr'>{lines}</span></figcaption></figure>")
        o.append("</div>")
    return "\n".join(o)


def excerpt_html(ex: dict) -> str:
    panels = ex["panels"]
    cols = len(panels) + (1 if ex.get("reference") else 0)
    o = [f"<h3>{esc(ex['title'])}</h3>",
         f"<div class='grid' style='grid-template-columns:repeat({cols},minmax(0,1fr))'>"]
    if ex.get("reference"):
        ref = "".join(f"<div>{esc(t)}</div>" for t in ex["reference"][:EXCERPT_LINES])
        o.append(f"<div class='panel'><h4>gold (hand-corrected)</h4><div class='ocr gold'>{ref}"
                 f"</div></div>")
    for c, rows in panels.items():
        reg = ex["regions"][c]
        leaf = reg["leaf"]
        lines = "".join(f"<div class='{r['mark']}'>{esc(r['text'])}</div>" for r in rows)
        same = sum(r["mark"] == "same" for r in rows)
        yard = "the gold" if ex.get("reference") else "another copy"
        o.append(f"<div class='panel'><h4><code>{esc(c)}</code> · leaf {leaf} · "
                 f"<a href='{iiif(c, leaf, 'full', '!2000,2000')}'>full page</a></h4>"
                 f"<a href='{crop(c, reg, 'full')}'>"
                 f"<img loading='lazy' src='{crop(c, reg)}'></a>"
                 f"<div class='muted'>{len(rows)} OCR lines in this span, {same} reading "
                 f"exactly as {yard}</div>"
                 f"<div class='ocr'>{lines}</div></div>")
    o.append("</div>")
    return "\n".join(o)


def clear_html(clear: list) -> str:
    o = ["<h2>The other twelve: not close</h2>",
         "<p>These need no images. Each pick is either the only whole alphabet against "
         "half-volume scans, or a book scan against a microfilm copy that delivers at most "
         "three-quarters of its lines per page. The last pair is the 1913 Trow business "
         "directory, which is not run at all.</p><table><tr><th>pick</th><th>not run</th>"
         "<th>scoped lines not run</th></tr>"]
    for e in clear:
        o.append(f"<tr><td><code>{esc(', '.join(e['run']) or 'none (not residential)')}</code>"
                 f"</td><td><code>{esc(', '.join(e['spare']))}</code></td>"
                 f"<td class='n'>{e['spare_lines']:,}</td></tr>")
    o.append("</table>")
    return "\n".join(o)


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(RESULTS / "runset_review.html"))
    ap.add_argument("--notes", default=str(RESULTS / "runset_review_notes.json"),
                    help="reviewer notes keyed by the pick: {pick, read} (optional)")
    args = ap.parse_args(argv)
    P = json.loads((RESULTS / "survey_twins_pairs.json").read_text(encoding="utf-8"))
    editions = P["editions"]
    picks = {run for _label, run in CLOSE}
    ids = {m["id"] for run in picks for m in edition_for(run, editions)["members"]}
    feats = load_features(ids)
    rng = random.Random(SEED)
    report = {"derived": _dt.date.today().isoformat(), "code_at": git_rev(),
              "pairs_derived": P["derived"], "seed": SEED, "editions": [], "clear": []}
    for label, run in CLOSE:
        print(f"{label} ...", file=sys.stderr)
        report["editions"].append(review_edition(label, run, editions, feats, rng))
    for e in editions:
        if not any(m["id"] in picks for m in e["members"]):
            report["clear"].append({"run": e["run"], "spare_lines": e["spare_lines"],
                                    "spare": [m["id"] for m in e["members"] if not m["run"]]})
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8")) \
        if Path(args.notes).exists() else {}
    out = Path(args.out)
    out.write_text(render(report, notes), encoding="utf-8")
    slim = json.loads(json.dumps(report))
    for ed in slim["editions"]:
        for p in ed["pairs"]:
            p["run_unplaced"] = len(p["run_unplaced"])
            p["other_unplaced"] = len(p["other_unplaced"])
    out.with_suffix(".json").write_text(json.dumps(slim, indent=1) + "\n", encoding="utf-8")
    for ed in report["editions"]:
        print(f"\n{ed['edition']}: pick {ed['run']}", file=sys.stderr)
        for c in ed["copies"]:
            print(f"  {'*' if c['run'] else ' '} {c['id']:28s} listing {c['listing_pages']:4d} "
                  f"scoped {c['scoped_lines'] or 0:7,d} entry {c['entry_lines']:7,d} "
                  f"non-entry {c['non_entry_lines']:5,d} gold {c['gold']}", file=sys.stderr)
        for p in ed["pairs"]:
            print(f"    vs {p['other']}: aligned {p['aligned_pages']} "
                  f"(listing both {p['aligned_listing_pages']}), entry {p['entry_lines_run']:,} "
                  f"vs {p['entry_lines_other']:,}; unplaced {len(p['run_unplaced'])} / "
                  f"{len(p['other_unplaced'])}", file=sys.stderr)
        print(f"    excerpts: {len(ed['excerpts'])}", file=sys.stderr)
    print(f"-> {out.relative_to(REPO)} (+ .json)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
