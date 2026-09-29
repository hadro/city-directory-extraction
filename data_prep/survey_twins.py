#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Twins: one printed edition, scanned more than once. Found from the text, because the catalog
cannot see them and the identifiers mislead.

    python3 data_prep/survey_twins.py gold            # which IA volumes print each gold set's lines
    python3 data_prep/survey_twins.py pairs           # every volume against every other: editions
    python3 data_prep/survey_twins.py --self-test

WHY (2026-09-28). The Brooklyn microfilm series was also scanned as books, and the book scans'
OCR reads the same pages far better. Smith's directory for the year ending May 1857 is
`micro_IABROOKLYN_0036` (tesseract) and `1857BPL` (ABBYY 9). Against the 229 hand-corrected gold
lines of its gold page, the microfilm copy reproduces 16% exactly and the book scan 81%. The
five-volume Torch run read the microfilm copies, so part of what stage 6 calls the OCR ceiling is
a choice of scan. And a twin of a gold volume carries the gold page's text with no
`eval_holdout` tag, because the harvest looks for gold only in the volume named in the gold
image path.

The identifier's year is not the edition. `1856BPL` prints "for the year ending May 1, 1856", the
twin of `micro_IABROOKLYN_0034`, not of `_0036`. So twins are paired by text, never by year.

`gold` -> results/survey_twins_gold.json
----------------------------------------
Every gold set in data/*_eval.jsonl is matched line for line against every harvested IA volume's
candidate lines (data/survey_ocr/<id>_lines.jsonl.gz: before section scoping, so front-matter
gold is not missed). A gold line matches when the two texts are identical after lower-casing and
reducing punctuation to spaces. Gold `raw_line` is hand-corrected, so an exact match means the
OCR line reads as printed.

Exact matching is what separates editions, but no single share does. Consecutive editions list
mostly the same people in the same order, so a fuzzy match cannot tell them apart, and how many
lines they reprint verbatim varies by city and decade:

| gold | its twin | own volume | neighbouring editions |
|---|---|---|---|
| smith1856 (Brooklyn 1856-57) | 1857BPL **80%** | 15% (microfilm) | 1855-56 (`1856BPL`) **0.4%** |
| doggett1846 (Manhattan) | none | 78% | 1847 **27%**, 1845 **22%** |
| trow1907 (Manhattan, ABBYY-8) | none | 10% | 1905 p2 **12%**, 1906 p2 **10%** |

So a twin is judged against the gold's own volume where that volume reads its own gold decently,
and against an absolute bar where it cannot:

    own      the volume the gold image (or the set's `ia_id`) names
    twin     reproduces >= TWIN_ABS of the gold lines exactly; or, where the own volume reads
             >= OWN_DECENT of them, >= TWIN_REL x the own volume's share (and >= TWIN_MIN)
    check    >= CHECK_ROWS exact lines otherwise: a neighbouring edition, or a twin whose OCR
             is too noisy to match exactly. Only a page read settles which

On every case above this marks no neighbour a twin. It does leave noisy twins at `check`:
`trowsgeneraldire1917trow` reads the Polk 1917 NYPL gold page at 4 of 69 exact lines, because
ABBYY-8 reads its ditto as `ii`, yet the lines are otherwise identical. So `fuzzy` is reported
beside each candidate: the share of up to FUZZY_ROWS gold lines with a difflib ratio >= 0.8 to a
line on the leaves around the exact hits. It is a lead, not a verdict. It gave Polk 1917 97%,
while the trowwilson1865 gold scored no candidate at all against `bub_gb_hY4tAAAAYAAJ`, whose
page 735 shares its entries but, read off the image, prints Mason & Hamlin at "No. 7 Mercer
Street" where the gold prints "596 Broadway": a neighbouring edition.

`verified` marks what was settled by reading lines or images: `twin` for every pair in
`survey_harvest.GOLD_TWINS`, which tags the twin's gold pages as eval holdout, and `not-twin` for
NOT_TWINS below.

The NYPL-sourced gold sets (image `0021_56825862.jpg`) are scanned too: their editions can exist
in the IA corpus, and nothing else would find them there.

Skipped: `iapanel_*` (their `raw_line` IS the IA line, so they match their own volume by
construction; they moved to data/iapanel/ on 2026-09-28, so the guard is now belt and braces),
and derived copies of another set (SKIP).

`pairs` -> results/survey_twins_pairs.json
------------------------------------------
Every volume against every other, from its residential lines (`_listing`; a not-residential
volume's whole candidate lines). A bottom-k sketch of each volume's unique lines finds the pairs
sharing >= PAIR_MIN; each is then matched in full and judged by PAGE STRUCTURE, not by how much
it shares:

    page concentration   for each page with >= PAGE_VOTE matched lines, the share landing on
                         its modal page in the other volume; the median, taken both ways

A page of one edition is a page of its twin, so every twin measured 1.0 on both sides. A
neighbouring edition re-breaks its pages, so a page's reprinted lines straddle two: 0.72-0.85 on
every neighbouring pair of Brooklyn, Trow, Doggett and Longworth editions. Sharing cannot
separate them: 1907BPL and 1908BPL share 60% of their lines; 1856BPL and its microfilm twin 5%.

    same-edition   concentration >= SAME_CONC both ways, on >= SAME_PAGES pages each
    undecided      >= 0.9 on fewer pages. The 1830s Brooklyn directories align page for page
                   across consecutive years on 20-24 pages, standing type carried over:
                   `micro_IABROOKLYN_0007` and `_0008` print "for the year 1830" and "1831".
                   So a short run proves nothing, and two different title-page years make the
                   pair neighbours
    neighbour      otherwise

Printed pages are compared on aligned pages wherever both margin fits read them. Twins agree
(1904BPL and `brooklynnewyorkc1904geor`: 99.9% of 15,487 lines); where they do not, a fit
misread: 1906BPL's p.670 is `brooklynnewyorkc00geor`'s "p.70", the leading digit dropped.

Editions are the same-edition pairs unioned, plus the gold scan's same-text pairs (the Franks
1786 reprints re-set the type, so their pages do not align). For each edition the run set is the
whole alphabet delivering the most lines per page, or failing a whole copy, the best of each
part. A recommendation for review, never a stamp.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import difflib
import gzip
import hashlib
import json
import multiprocessing
import os
import re
import statistics
import subprocess
import sys
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
OCR = DATA / "survey_ocr"
SIDECARS = HERE / "survey"
RESULTS = REPO / "results"
sys.path.insert(0, str(HERE))

from survey_harvest import GOLD_TWINS  # noqa: E402
from verify_harvest_leakage import page_id  # noqa: E402

MIN_CHARS = 15          # a gold line shorter than this after normalising is not evidence
MIN_TOKENS = 3
TWIN_ABS = 0.50         # neighbours measured up to 31% (1906BPL's sample in 1907BPL)
OWN_DECENT = 0.20       # below this the own volume's OCR is no yardstick (smith1856's is 15%)
TWIN_REL = 0.90
TWIN_MIN = 0.10
CHECK_ROWS = 3
FUZZY_ROWS = 150
FUZZY_RATIO = 0.80
DERIVED_PREFIX = "iapanel_"
SKIP = {
    "1906BPL_sample500_norm_eval.jsonl": "the same 500 rows as 1906BPL_sample500, normalized",
    "bands_1906BPL_eval.jsonl": "band labels; no raw_line",
}
# read off the image and found to be another edition: (gold set file, IA identifier) -> why
NOT_TWINS = {
    ("trowwilson1865_eval.jsonl", "bub_gb_hY4tAAAAYAAJ"):
        "leaf 753 (p.735, REY-RHE) runs Reynolds Francis..Rheinfeldt and its ad band prints "
        "Mason & Hamlin at 'No. 7 Mercer Street'; the gold page runs Reynolds Isaac..Rheide "
        "under '596 Broadway'. Same entries, different edition (read 2026-09-28)",
}


def verdict(ident: str, exact: int, share: float, own: str, own_share: float):
    if ident == own:
        return "own"
    if share >= TWIN_ABS or (own_share >= OWN_DECENT and share >= max(TWIN_MIN,
                                                                     TWIN_REL * own_share)):
        return "twin"
    return "check" if exact >= CHECK_ROWS else None


def norm(text: str) -> str:
    """Lower-case, punctuation to spaces, whitespace collapsed: '188:Adams ©.' -> '188 adams'."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def eligible(t: str) -> bool:
    return len(t) >= MIN_CHARS and len(t.split()) >= MIN_TOKENS


def git_rev() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", str(Path(__file__))],
                               cwd=REPO, capture_output=True, text=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def sidecar_ids() -> dict:
    """lower-cased IA identifier -> identifier as the sidecars spell it."""
    return {p.stem[3:].lower(): p.stem[3:] for p in SIDECARS.glob("ia_*.json")}


def volume_card(ident: str) -> dict:
    """What a reader needs beside a candidate to judge it: title, dates, engine, status."""
    p = SIDECARS / f"ia_{ident}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    ia = (d.get("catalog_says") or {}).get("ia") or {}
    yc = (d.get("book_says") or {}).get("year_covered") or {}
    return {"title": (ia.get("title") or "")[:90], "ia_date": ia.get("date"),
            "year_covered": yc.get("value") if isinstance(yc, dict) else None,
            "ocr": ia.get("ocr"), "survey_status": d.get("survey_status")}


def load_gold() -> dict:
    """{set name: {"file", "rows", "own", "own_from", "lines": [normalised eligible lines]}}"""
    ids = sidecar_ids()
    sets = {}
    for path in sorted(DATA.glob("*_eval.jsonl")):
        if path.name.startswith(DERIVED_PREFIX) or path.name in SKIP:
            continue
        rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
        own, own_from = None, None
        for r in rows:
            ctx = r.get("context") or {}
            if ctx.get("ia_id"):
                own, own_from = ctx["ia_id"], "ia_id"
                break
            img = ctx.get("image")
            if img and img != "?":
                pid = page_id(img)
                if pid[0] == "ia":
                    own, own_from = ids.get(pid[1], pid[1]), "ia-image"
                else:
                    own_from = pid[0]
                break
        lines = sorted({t for r in rows if (t := norm(r.get("raw_line") or "")) and eligible(t)})
        sets[path.name[:-len("_eval.jsonl")]] = {"file": path.name, "rows": len(rows),
                                                 "own": own, "own_from": own_from, "lines": lines}
    return sets


_GOLD: dict = {}
_SAMPLE: dict = {}


def _init(gold_index: dict, sample: dict):
    global _GOLD, _SAMPLE
    _GOLD, _SAMPLE = gold_index, sample


def _best_ratio(g: str, pool: list) -> float:
    top = 0.0
    for t in pool:
        sm = difflib.SequenceMatcher(None, g, t, autojunk=False)
        if sm.real_quick_ratio() <= top or sm.quick_ratio() <= top:
            continue
        top = max(top, sm.ratio())
        if top == 1.0:
            break
    return top


def scan_volume(path: str):
    """One volume's exact hits per gold set, and the fuzzy share around them."""
    ident = Path(path).name[:-len("_lines.jsonl.gz")]
    hits = collections.defaultdict(lambda: collections.defaultdict(list))
    by_leaf = collections.defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            leaf = row["context"]["leaf"]
            t = norm(row["raw_line"])
            by_leaf[leaf].append(t)
            for g in _GOLD.get(t, ()):
                hits[g][t].append(leaf)
    out = {}
    for g, h in hits.items():
        leaf_counts = collections.Counter(l for ls in h.values() for l in set(ls))
        fuzzy = None
        if len(h) >= CHECK_ROWS:
            near = set()
            for leaf, _n in leaf_counts.most_common(3):
                near.update(range(leaf - 1, leaf + 2))
            pool = [t for leaf in sorted(near) for t in by_leaf.get(leaf, ())]
            rows = _SAMPLE[g]
            fuzzy = round(sum(_best_ratio(r, pool) >= FUZZY_RATIO for r in rows) / len(rows), 4)
        out[g] = {"exact": len(h), "leaves": [l for l, _n in leaf_counts.most_common(6)],
                  "fuzzy": fuzzy}
    return ident, out


def gold(args) -> int:
    sets = load_gold()
    index = collections.defaultdict(list)
    for name, s in sets.items():
        for t in s["lines"]:
            index[t].append(name)
    sample = {}
    for name, s in sets.items():
        step = max(1, len(s["lines"]) // FUZZY_ROWS)
        sample[name] = s["lines"][::step][:FUZZY_ROWS] or [""]
    paths = sorted(str(p) for p in OCR.glob("*_lines.jsonl.gz"))
    if args.ids:
        want = set(args.ids.split(","))
        paths = [p for p in paths if Path(p).name[:-len("_lines.jsonl.gz")] in want]
    print(f"{len(sets)} gold sets, {len(index):,} distinct eligible gold lines; "
          f"scanning {len(paths)} volumes", file=sys.stderr)

    per_set = collections.defaultdict(dict)
    with multiprocessing.Pool(max(1, (os.cpu_count() or 2) - 1), _init, (dict(index), sample)) as pool:
        for n, (ident, out) in enumerate(pool.imap_unordered(scan_volume, paths), 1):
            for g, rec in out.items():
                per_set[g][ident] = rec
            if n % 25 == 0:
                print(f"  {n}/{len(paths)}", file=sys.stderr)

    report = {"derived": _dt.date.today().isoformat(), "code_at": git_rev(),
              "method": "exact normalised-line match, gold raw_line vs IA candidate lines",
              "params": {"min_chars": MIN_CHARS, "min_tokens": MIN_TOKENS,
                         "twin_abs": TWIN_ABS, "own_decent": OWN_DECENT, "twin_rel": TWIN_REL,
                         "twin_min": TWIN_MIN, "check_rows": CHECK_ROWS,
                         "fuzzy_rows": FUZZY_ROWS, "fuzzy_ratio": FUZZY_RATIO},
              "volumes_scanned": len(paths), "skipped": SKIP, "sets": {}}
    for name, s in sorted(sets.items()):
        n = len(s["lines"])
        found = per_set.get(name, {})
        own_share = found[s["own"]]["exact"] / n if s["own"] in found and n else 0.0
        vols = []
        for ident, rec in found.items():
            share = rec["exact"] / n if n else 0.0
            v = verdict(ident, rec["exact"], share, s["own"], own_share)
            if v:
                checked = ("twin" if ident in GOLD_TWINS.get(s["file"], ())
                           else "not-twin" if (s["file"], ident) in NOT_TWINS else None)
                vols.append({"id": ident, "verdict": v, "verified": checked,
                             "exact": rec["exact"], "exact_share": round(share, 4),
                             "fuzzy_share": rec["fuzzy"], "leaves": rec["leaves"],
                             **({"note": NOT_TWINS[(s["file"], ident)]}
                                if checked == "not-twin" else {}),
                             **volume_card(ident)})
        vols.sort(key=lambda v: (-v["exact_share"], v["id"]))
        report["sets"][name] = {"file": s["file"], "rows": s["rows"], "eligible_lines": n,
                                "own": s["own"], "own_from": s["own_from"],
                                "own_in_corpus": s["own"] in {Path(p).name[:-15] for p in paths}
                                if s["own"] else None,
                                "volumes": vols}

    out = Path(args.out)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print_gold(report)
    print(f"\n-> {out.relative_to(REPO)}", file=sys.stderr)
    return 0


def print_gold(report: dict):
    for name, s in report["sets"].items():
        own = s["own"] or f"({s['own_from'] or 'no image'})"
        print(f"\n{name}: {s['eligible_lines']} eligible of {s['rows']} rows; own {own}")
        if not s["volumes"]:
            print("    no IA volume reproduces >= %d lines" % CHECK_ROWS)
        for v in s["volumes"]:
            fz = "" if v["fuzzy_share"] is None else f" fuzzy {v['fuzzy_share']:.0%}"
            ok = f" [{v['verified']}]" if v["verified"] else ""
            print(f"    {v['verdict']:5s} {v['id']:30s} exact {v['exact']:4d} "
                  f"({v['exact_share']:5.1%}){fz}  leaves {v['leaves'][:3]}{ok}  "
                  f"| {v.get('ia_date')} {str(v.get('title'))[:44]}")


# --------------------------------------------------------------------------------------- pairs
SAMPLE_K = 3000     # bottom-k sketch: a volume's smallest unique-line hashes, so two volumes
                    # sample the same lines wherever they share them
DF_MAX = 6          # a sketched line printed in more volumes than this is boilerplate
PAIR_MIN = 0.03     # a pair is examined when either direction's sketch containment reaches this
PAGE_VOTE = 5       # a page votes on page structure only with this many matched lines
FOLIO_MIN = 30      # matched lines with a printed page on both sides, before folios decide
SAME_CONC = 0.95    # every twin measured 1.0 on both sides; neighbouring editions 0.72-0.85
SAME_PAGES = 30     # ...on at least this many voting pages. Below it, the 1830s Brooklyn
                    # directories reach 1.0 across consecutive years on 20-24 pages: standing
                    # type, carried from one year's edition to the next
FOLIO_OK = 0.80
WHOLE_FIRST, WHOLE_LAST = "B", "W"   # a listing from A-B through W-Z is a whole alphabet
LEAF_RX = re.compile(r'"leaf":\s*(\d+)')


def _h(t: str) -> int:
    return int.from_bytes(hashlib.blake2b(t.encode("utf-8"), digest_size=8).digest(), "big")


def hash_volume(ident: str):
    """A volume's residential lines (its whole candidate lines if it has none), reduced to the
    eligible lines printed once in it: (ident, kind, lines read, text leaves, hashes, leaves)."""
    listing = OCR / f"{ident}_listing.jsonl.gz"
    path, kind = ((listing, "listing") if listing.exists()
                  else (OCR / f"{ident}_lines.jsonl.gz", "lines"))
    counts, leaf_of, n = collections.Counter(), {}, 0
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            n += 1
            t = norm(row["raw_line"])
            if eligible(t):
                h = _h(t)
                counts[h] += 1
                leaf_of[h] = row["context"]["leaf"]
    # every leaf carrying a candidate line: the text leaves a folio segment counts pages over
    text_leaves = set()
    with gzip.open(OCR / f"{ident}_lines.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            m = LEAF_RX.search(line)
            if m:
                text_leaves.add(int(m.group(1)))
    uniq = sorted(h for h, c in counts.items() if c == 1)
    return (ident, kind, n, sorted(text_leaves), array("Q", uniq),
            array("L", (leaf_of[h] for h in uniq)))


def folio_map(ident: str, text_leaves: list) -> dict:
    """leaf -> printed page, from the sidecar's margin-fit segments. A segment numbers pages over
    its text leaves, so it is used only where this volume's text leaves count out exactly."""
    p = SIDECARS / f"ia_{ident}.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for s in (d.get("folios") or {}).get("segments") or []:
        tl = [leaf for leaf in text_leaves if s["first_leaf"] <= leaf <= s["last_leaf"]]
        if len(tl) == s["last_page"] - s["first_page"] + 1:
            out.update({leaf: s["first_page"] + i for i, leaf in enumerate(tl)})
    return out


def _concentration(matches: list, key: int):
    """Median over pages (with PAGE_VOTE matches) of the share landing on the page's modal
    partner. A page of one edition is a page of its twin; a neighbouring edition breaks its
    pages elsewhere, so a page's reprinted lines straddle two."""
    groups = collections.defaultdict(collections.Counter)
    for m in matches:
        groups[m[key]][m[1 - key]] += 1
    shares = [c.most_common(1)[0][1] / sum(c.values())
              for c in groups.values() if sum(c.values()) >= PAGE_VOTE]
    return (round(statistics.median(shares), 3) if shares else None), len(shares)


def pair_detail(A: dict, B: dict, db: dict) -> dict:
    matches = [(la, db[h]) for h, la in zip(A["hs"], A["ls"]) if h in db]
    n = len(matches)
    conc_a, pages_a = _concentration(matches, 0)
    conc_b, pages_b = _concentration(matches, 1)
    both = [(A["folio"][la], B["folio"][lb]) for la, lb in matches
            if la in A["folio"] and lb in B["folio"]]
    agree = (round(sum(x == y for x, y in both) / len(both), 3)
             if len(both) >= FOLIO_MIN else None)
    leaves_a = {la for la, _ in matches}
    leaves_b = {lb for _, lb in matches}
    return {"matched": n,
            "contain_a": round(n / len(A["hs"]), 4) if A["hs"] else 0.0,
            "contain_b": round(n / len(B["hs"]), 4) if B["hs"] else 0.0,
            "page_conc_a": conc_a, "pages_a": pages_a,
            "page_conc_b": conc_b, "pages_b": pages_b,
            "folio_pairs": len(both), "folio_agree": agree,
            "cover_a": round(len(leaves_a) / len(A["line_leaves"]), 3) if A["line_leaves"] else 0,
            "cover_b": round(len(leaves_b) / len(B["line_leaves"]), 3) if B["line_leaves"] else 0,
            "span_a": [min(leaves_a), max(leaves_a)] if leaves_a else None,
            "span_b": [min(leaves_b), max(leaves_b)] if leaves_b else None}


def attested_year(ident: str):
    """The year the title page prints (`book_says.year_covered`), if the survey read one."""
    p = SIDECARS / f"ia_{ident}.json"
    yc = (json.loads(p.read_text(encoding="utf-8")).get("book_says") or {}).get("year_covered")
    return yc.get("value") if isinstance(yc, dict) else None


def relation(p: dict) -> str:
    """same-edition / undecided / neighbour, from page structure (see the docstring). Title-page
    years settle an undecided pair when both are read and differ: `micro_IABROOKLYN_0007` and
    `_0008` align page for page on 23 pages, and print "for the year 1830" and "... 1831"."""
    conc = min(p["page_conc_a"] or 0.0, p["page_conc_b"] or 0.0)
    ya, yb = p.get("year_a"), p.get("year_b")
    if conc >= SAME_CONC and min(p["pages_a"], p["pages_b"]) >= SAME_PAGES:
        return "same-edition"
    if conc >= 0.9:
        return "neighbour" if ya and yb and ya != yb else "undecided"
    return "neighbour"


def member_card(ident: str, V: dict) -> dict:
    """One scan of an edition, as the run-set choice sees it."""
    d = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    ia = (d.get("catalog_says") or {}).get("ia") or {}
    L = d.get("listing") or {}
    v = V[ident]
    first, last = L.get("first_letter"), L.get("last_letter")
    return {"id": ident, "ia_date": ia.get("date"), "title": (ia.get("title") or "")[:80],
            "ocr": ia.get("ocr"), "survey_status": d.get("survey_status"),
            "letters": f"{first or '?'}-{last or '?'}",
            "whole": bool(first and last and first <= WHOLE_FIRST and last >= WHOLE_LAST),
            "kind": v["kind"], "lines": v["lines"], "text_leaves": len(v["line_leaves"]),
            "lines_per_leaf": round(v["lines"] / len(v["line_leaves"]), 1)
            if v["line_leaves"] else 0.0}


def gold_text_edges(V: dict) -> list:
    """Same-text pairs the page test cannot see but the gold scan proved: a gold set's own
    volume and each of its GOLD_TWINS (the Franks 1786 reprints re-set the type, so their pages
    do not align, yet reprint the gold page at 57% exact)."""
    path = RESULTS / "survey_twins_gold.json"
    if not path.exists():
        return []
    own = {s["file"]: s["own"] for s in json.loads(path.read_text(encoding="utf-8"))["sets"].values()}
    return [{"a": own[f], "b": t, "via": f} for f, twins in GOLD_TWINS.items()
            for t in twins if own.get(f) in V and t in V]


def _uf():
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    return parent, find


DUP_COVER = 0.80    # two parts matching over this share of each other's pages are one part


def edition_groups(rows: list, V: dict, text_edges: list) -> list:
    """Union the same-edition pairs (and the gold-proven same-text pairs) into editions, and
    choose what to run of each.

    A whole alphabet beats parts, and among copies of the same span the one delivering more
    lines per page wins: the printed page is the same, so the difference is what OCR and the
    filters lost. Parts are kept only where no whole copy exists, one per part, where two parts
    are the same part when each matches over DUP_COVER of the other's pages (their letter ranges
    are read by OCR and can differ by a letter). Not-residential volumes are never run. This is
    a recommendation for review, never a stamp."""
    parent, find = _uf()
    same = [p for p in rows if p["relation"] == "same-edition"]
    for p in same + text_edges:
        parent[find(p["a"])] = find(p["b"])
    groups = collections.defaultdict(list)
    for x in list(parent):
        groups[find(x)].append(x)
    gold_twins = {t for twins in GOLD_TWINS.values() for t in twins}
    out = []
    for members in groups.values():
        cards = sorted((member_card(m, V) for m in members), key=lambda c: c["id"])
        live = [c for c in cards if c["survey_status"] != "not-residential"]
        wholes = [c for c in live if c["whole"]]
        close = False
        if wholes:
            best = max(wholes, key=lambda c: c["lines_per_leaf"])
            run = [best["id"]]
            rivals = [c for c in wholes if c is not best]
            close = any(c["lines_per_leaf"] >= 0.95 * best["lines_per_leaf"] for c in rivals)
        else:
            pp, pfind = _uf()
            for c in live:
                pfind(c["id"])
            for p in same:
                if (p["a"] in pp and p["b"] in pp and p["cover_a"] >= DUP_COVER
                        and p["cover_b"] >= DUP_COVER):
                    pp[pfind(p["a"])] = pfind(p["b"])
            parts = collections.defaultdict(list)
            for c in live:
                parts[pfind(c["id"])].append(c)
            run = []
            for cs in parts.values():
                best = max(cs, key=lambda c: c["lines_per_leaf"])
                run.append(best["id"])
                close |= any(c is not best and c["lines_per_leaf"] >= 0.95 * best["lines_per_leaf"]
                             for c in cs)
        for c in cards:
            c["run"] = c["id"] in run
            c["gold_twin"] = c["id"] in gold_twins
        spare = sum(c["lines"] for c in live if not c["run"] and c["kind"] == "listing")
        years = sorted({y for m in members if (y := attested_year(m))})
        out.append({"members": cards, "run": sorted(run), "spare_lines": spare,
                    "close_call": close, "attested_years": years,
                    "pairs": [{k: p.get(k) for k in ("a", "b", "page_conc_a", "page_conc_b",
                                                      "pages_a", "pages_b", "folio_agree",
                                                      "folio_pairs", "contain_a", "contain_b",
                                                      "via")}
                              for p in same + text_edges
                              if p["a"] in members and p["b"] in members]})
    out.sort(key=lambda g: -g["spare_lines"])
    return out


def print_groups(groups: list, rows: list):
    total = sum(g["spare_lines"] for g in groups)
    print(f"{len(groups)} editions held in more than one scan; "
          f"{total:,} residential lines in the copies not chosen\n")
    for g in groups:
        years = f", title pages read: {g['attested_years']}" if g["attested_years"] else ""
        close = "; CLOSE CALL" if g["close_call"] else ""
        print(f"edition ({len(g['members'])} scans, {g['spare_lines']:,} spare lines{years}{close})")
        for c in g["members"]:
            flag = ("RUN " if c["run"] else "    ") if c["survey_status"] != "not-residential" \
                else "n/r "
            gold = " [gold twin]" if c["gold_twin"] else ""
            print(f"  {flag}{c['id']:30s} {c['letters']:5s} {str(c['ia_date'])[:9]:9s} "
                  f"{str(c['ocr'])[:22]:22s} {c['lines']:8,d} lines {c['lines_per_leaf']:6.1f}/leaf"
                  f"{gold}")
        for p in g["pairs"]:
            f = p["folio_agree"]
            if p.get("via"):
                print(f"      = {p['a']} / {p['b']}: same text by the gold scan ({p['via']})")
            elif f is not None and f < FOLIO_OK:
                print(f"      ! folios disagree on aligned pages, {p['a']} vs {p['b']}: {f:.0%} "
                      f"of {p['folio_pairs']} (a fit misread, not a different edition)")
    und = [p for p in rows if p["relation"] == "undecided"]
    if und:
        print(f"\nundecided (aligned pages, but under {SAME_PAGES} of them):")
        for p in und:
            print(f"  {p['a']:30s} {p['b']:30s} pages {p['pages_a']}/{p['pages_b']} "
                  f"shared {p['contain_a']:.0%}/{p['contain_b']:.0%}")


def pairs(args) -> int:
    idents = sorted(p.name[:-len("_lines.jsonl.gz")] for p in OCR.glob("*_lines.jsonl.gz"))
    print(f"hashing {len(idents)} volumes", file=sys.stderr)
    V = {}
    with multiprocessing.Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        for n, (ident, kind, lines, text_leaves, hs, ls) in enumerate(
                pool.imap_unordered(hash_volume, idents), 1):
            V[ident] = {"kind": kind, "lines": lines, "hs": hs, "ls": ls,
                        "line_leaves": set(ls), "folio": folio_map(ident, text_leaves)}
            if n % 25 == 0:
                print(f"  {n}/{len(idents)}", file=sys.stderr)

    # sketch containment over the union of every volume's bottom-k
    sketch = {v: set(d["hs"][:SAMPLE_K]) for v, d in V.items()}
    union = set().union(*sketch.values())
    where = collections.defaultdict(list)
    for v, d in V.items():
        for h in d["hs"]:
            if h in union:
                where[h].append(v)
    contain = collections.defaultdict(dict)
    for v, s in sketch.items():
        s = [h for h in s if len(where[h]) <= DF_MAX]
        c = collections.Counter(w for h in s for w in where[h] if w != v)
        for w, k in c.items():
            contain[v][w] = k / len(s)
    cand = sorted({tuple(sorted((v, w))) for v in contain for w, r in contain[v].items()
                   if max(r, contain[w].get(v, 0.0)) >= PAIR_MIN})
    print(f"{len(cand)} candidate pairs", file=sys.stderr)

    rows = []
    for b in sorted({b for _a, b in cand}):
        db = dict(zip(V[b]["hs"], V[b]["ls"]))
        for a, _b in (p for p in cand if p[1] == b):
            det = pair_detail(V[a], V[b], db)
            row = {"a": a, "b": b, "sketch_a": round(contain[a].get(b, 0.0), 4),
                   "sketch_b": round(contain[b].get(a, 0.0), 4), **det,
                   "year_a": attested_year(a), "year_b": attested_year(b)}
            row["relation"] = relation(row)
            rows.append(row)
    rows.sort(key=lambda p: (p["relation"] != "same-edition", p["a"], p["b"]))
    groups = edition_groups(rows, V, gold_text_edges(V))
    report = {"derived": _dt.date.today().isoformat(), "code_at": git_rev(),
              "params": {"sample_k": SAMPLE_K, "df_max": DF_MAX, "pair_min": PAIR_MIN,
                         "page_vote": PAGE_VOTE, "folio_min": FOLIO_MIN,
                         "same_conc": SAME_CONC, "same_pages": SAME_PAGES,
                         "min_chars": MIN_CHARS, "min_tokens": MIN_TOKENS},
              "relations": dict(collections.Counter(p["relation"] for p in rows)),
              "editions": groups,
              "volumes": {v: {"kind": d["kind"], "lines": d["lines"], "unique_lines": len(d["hs"]),
                              "folio_leaves": len(d["folio"])} for v, d in sorted(V.items())},
              "pairs": rows}
    out = Path(args.out_pairs)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print_groups(groups, rows)
    print(f"\n-> {out.relative_to(REPO)}", file=sys.stderr)
    return 0


def _self_test() -> int:
    assert norm("Clark Alexander, 188:Adams ©. -") == "clark alexander 188 adams"
    assert norm("  Holmes  Isaac,policeman, 53 Butler") == "holmes isaac policeman 53 butler"
    assert eligible("holmes isaac policeman 53 butler")
    assert not eligible("do 12 main"), "short lines are not evidence"
    assert not eligible("telephonebushwick 828"), "two tokens are not evidence"
    assert _best_ratio("holmes isaac policeman 53 butler",
                       ["holmes isaac policeman 58 butler", "smith john"]) > 0.95
    assert _best_ratio("abc", []) == 0.0
    # the cases the rule was set on (exact shares from the 2026-09-28 run)
    assert verdict("1857BPL", 184, 0.803, "micro_IABROOKLYN_0036", 0.153) == "twin"
    assert verdict("1858BPL", 3, 0.013, "micro_IABROOKLYN_0036", 0.153) == "check"
    assert verdict("micro_IABROOKLYN_0016", 27, 0.409, "brooklyndirector00ogde", 0.348) == "twin"
    assert verdict("brooklynalphabet1843unse", 7, 0.106, "brooklyndirector00ogde", 0.348) == "check"
    assert verdict("doggettsnewyorkc1847dogg", 10, 0.270, "doggettsnewyorkc1846dogg",
                   0.784) == "check", "a neighbouring Doggett edition"
    assert verdict("trowsgeneraldir1905p2trow", 8, 0.118, "trowsgeneraldir1907p2trow",
                   0.103) == "check", "own OCR too poor to be the yardstick"
    assert verdict("1907BPL", 142, 0.306, "1906BPL", 0.782) == "check"
    assert verdict("newyorkdirectory00durs_0", 32, 0.571, "newyorkdirectory00fran_0",
                   0.018) == "twin"
    assert verdict("x", 2, 0.02, None, 0.0) is None
    # page structure: the pairs the SAME_* constants were read off (2026-09-28)
    pair = {"page_conc_a": 1.0, "page_conc_b": 1.0, "pages_a": 253, "pages_b": 254}
    assert relation(pair) == "same-edition", "1857BPL / micro_IABROOKLYN_0036"
    assert relation({**pair, "pages_a": 23, "pages_b": 24}) == "undecided"
    assert relation({**pair, "pages_a": 23, "pages_b": 24, "year_a": 1830,
                     "year_b": 1831}) == "neighbour", "standing type across two years"
    assert relation({"page_conc_a": 0.769, "page_conc_b": 0.772, "pages_a": 1063,
                     "pages_b": 1073}) == "neighbour", "1907BPL / 1908BPL"
    assert _concentration([(1, 10)] * 5 + [(2, 11)] * 4 + [(2, 12)], 0) == (0.9, 2)
    assert _concentration([(1, 10)] * 5 + [(2, 11)] * 5, 0) == (1.0, 2)
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["gold", "pairs"])
    ap.add_argument("--ids", help="comma list of IA identifiers to scan (default: all)")
    ap.add_argument("--out", default=str(RESULTS / "survey_twins_gold.json"))
    ap.add_argument("--out-pairs", default=str(RESULTS / "survey_twins_pairs.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "gold":
        return gold(args)
    if args.cmd == "pairs":
        return pairs(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
