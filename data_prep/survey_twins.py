#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Twins: one printed edition, scanned more than once. Found from the text, because the catalog
cannot see them and the identifiers mislead.

    python3 data_prep/survey_twins.py gold            # which IA volumes print each gold set's lines
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
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import difflib
import gzip
import json
import multiprocessing
import os
import re
import subprocess
import sys
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
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["gold"])
    ap.add_argument("--ids", help="comma list of IA identifiers to scan (default: all)")
    ap.add_argument("--out", default=str(RESULTS / "survey_twins_gold.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "gold":
        return gold(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
