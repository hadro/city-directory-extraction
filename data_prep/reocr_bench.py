#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
A free yardstick for re-OCRing the Brooklyn microfilm: score any OCR of a microfilm page against
the book scan of the same printed page, and against the gold where the page has one.

    python3 data_prep/reocr_bench.py build        # -> results/reocr_bench.json (pages + references)
    python3 data_prep/reocr_bench.py score        # IA's own microfilm OCR: the baseline
    python3 data_prep/reocr_bench.py score --candidate <pages.jsonl> [--name gemini-flash]
    python3 data_prep/reocr_bench.py --self-test

WHY (2026-10-05). The microfilm OCR is the largest recall loss left in the corpus. 39 microfilm
volumes have no book scan, and where one exists IA's tesseract delivers about 40% of its lines
(docs/SURVEY_PLAN.md, "Printed name counts"). An image check of flagged pages found legible
microfilm listing pages whose OCR came back as fragments. A re-OCR is the remedy. Choosing an
engine needs a measure, and gold is scarce. But 8 microfilm volumes are copies of an edition the
corpus also holds as a book scan, page for page (survey_twins.py, "Editions held twice"). So
the book scan's lines for a page are a reference for any OCR of the microfilm image of it, at no
labelling cost.

`build` samples, per pair, PAGES_PER_PAIR microfilm listing pages whose book partner is placed
confidently (seeded), plus every microfilm page that holds gold. A page's partners are the book
leaves holding at least PARTNER_MIN of its exactly matched lines and PARTNER_SHARE of them, so
one microfilm frame can stand for two book pages (Brooklyn 1843-44's later frames). Each page
records the IIIF image an OCR engine would read, the book scan's eligible lines on its partners
(the reference), and the gold rows located on it.

`score` reads candidate OCR as JSONL, one page per line: {"volume", "leaf", "lines": [...]}. Per
page it reports:
    book_exact   share of reference lines the candidate reproduces exactly (lower-cased,
                 punctuation as spaces: survey_twins.norm)
    book_close   ...with a difflib ratio of at least CLOSE
    junk         share of the candidate's eligible lines like no reference line (ratio < JUNK)
    gold_exact / gold_close   the same against the gold rows, on gold pages
The book scan's OCR is not perfect (ABBYY-9 reads 81-83% of the Smith gold lines exactly), so
book_* is agreement with it, an underestimate for a perfect OCR, and the same for every
candidate. IA's microfilm lines are always scored beside a candidate, as the baseline.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import difflib
import gzip
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
OUT = REPO / "results" / "reocr_bench.json"
sys.path.insert(0, str(HERE))

from survey_twins import eligible, hash_volume, norm  # noqa: E402

IIIF = "https://iiif.archive.org/iiif"
SEED = 20261005
PAGES_PER_PAIR = 5
PARTNER_MIN = 3
PARTNER_SHARE = 0.2
REF_MIN = 30            # a sampled page's partners hold at least this many reference lines
CLOSE = 0.8
JUNK = 0.5
GOLD = {  # gold set -> the microfilm volume its pages are found on, and how its rows place there
    "smith1855_eval.jsonl": "micro_IABROOKLYN_0034",
    "smith1856_eval.jsonl": "micro_IABROOKLYN_0036",
    "hearne1852_eval.jsonl": "micro_IABROOKLYN_0030",
    "ogden1839_eval.jsonl": "micro_IABROOKLYN_0016",
}


def pairs() -> list:
    """(microfilm id, book-scan id) for every microfilm copy stamped a duplicate of a book."""
    out = []
    for p in sorted(SIDECARS.glob("ia_micro_IABROOKLYN_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        st = str(d.get("survey_status"))
        if st.startswith("duplicate-of:"):
            out.append((d["id"], st.split(":", 1)[1]))
    return out


def lines_by_leaf(ident: str) -> dict:
    """leaf -> the volume's candidate lines on it (before section scoping), in order."""
    out = collections.defaultdict(list)
    with gzip.open(OCR / f"{ident}_lines.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            out[r["context"]["leaf"]].append(r["raw_line"])
    return out


def residential(ident: str) -> set:
    d = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    return {leaf for r in (d.get("sections") or {}).get("runs", []) if r.get("residential")
            for leaf in range(r["start_leaf"], r["end_leaf"] + 1)}


def partners(micro: str, book: str) -> dict:
    """micro leaf -> the book leaves printing the same page (see the module docstring)."""
    _m = hash_volume(micro, True)
    _b = hash_volume(book, True)
    where = dict(zip(_b[4], _b[5]))
    votes = collections.defaultdict(collections.Counter)
    for h, leaf in zip(_m[4], _m[5]):
        if h in where:
            votes[leaf][where[h]] += 1
    out = {}
    for leaf, c in votes.items():
        n = sum(c.values())
        keep = sorted(b for b, k in c.items() if k >= PARTNER_MIN and k >= PARTNER_SHARE * n)
        if keep:
            out[leaf] = keep
    return out


def gold_pages() -> dict:
    """(micro, leaf) -> gold raw lines, from each gold set's rows and the survey's location of
    its pages: the gold image's jp2 number is the leaf on the volume it was transcribed from
    (verified at offset 0 on 15 volumes), and a twin's pages are placed by text (ogden1839's
    images are of the book scan; its microfilm leaves come from the line hashes)."""
    out = collections.defaultdict(list)
    for set_file, micro in GOLD.items():
        rows = [json.loads(x) for x in (DATA / set_file).read_text(encoding="utf-8").splitlines()]
        by_img = collections.defaultdict(list)
        for g in rows:
            m = re.search(r"([A-Za-z0-9_]+?)_(\d{4})\.jp2", g["context"].get("image") or "")
            if m:
                by_img[(m.group(1).split("%2F")[-1], int(m.group(2)))].append(g["raw_line"])
        for (vol, leaf), raw in by_img.items():
            if vol == micro:
                out[(micro, leaf)] += raw
            else:   # transcribed from the book scan: find the microfilm leaf holding the most
                cand = lines_by_leaf(micro)
                keys = {norm(t) for t in raw}
                best = max(cand, key=lambda lf: sum(norm(t) in keys for t in cand[lf]))
                out[(micro, best)] += raw
    return dict(out)


def build(args) -> int:
    rng = random.Random(SEED)
    gold = gold_pages()
    pages = []
    for micro, book in pairs():
        print(f"{micro} -> {book}", file=sys.stderr)
        part = partners(micro, book)
        book_lines = lines_by_leaf(book)
        micro_res = residential(micro)

        def reference(leaf):
            return [t for b in part.get(leaf, []) for t in book_lines.get(b, []) if eligible(norm(t))]

        pool = [leaf for leaf in sorted(part) if leaf in micro_res and len(reference(leaf)) >= REF_MIN]
        picks = set(rng.sample(pool, min(PAGES_PER_PAIR, len(pool))))
        picks |= {leaf for (m, leaf) in gold if m == micro}
        for leaf in sorted(picks):
            pages.append({"volume": micro, "leaf": leaf, "book": book,
                          "book_leaves": part.get(leaf, []),
                          "image": f"{IIIF}/{micro}${leaf}/full/max/0/default.jpg",
                          "reference": reference(leaf),
                          "gold": gold.get((micro, leaf), [])})
    doc = {"built": _dt.date.today().isoformat(), "seed": SEED, "pages": pages,
           "pairs": [list(p) for p in pairs()]}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n_gold = sum(bool(p["gold"]) for p in pages)
    print(f"{len(pages)} pages ({n_gold} with gold), "
          f"{sum(len(p['reference']) for p in pages):,} reference lines -> {OUT.relative_to(REPO)}",
          file=sys.stderr)
    return 0


def _ratio(a: str, b: str) -> float:
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return m.ratio() if m.real_quick_ratio() >= JUNK and m.quick_ratio() >= JUNK else 0.0


def page_score(candidate: list, reference: list) -> dict:
    """book_exact / book_close / junk for one page (see the module docstring)."""
    cand = [norm(t) for t in candidate if eligible(norm(t))]
    ref = [norm(t) for t in reference if eligible(norm(t))]
    if not ref:
        return {"ref": 0, "cand": len(cand), "exact": None, "close": None, "junk": None}
    cset = set(cand)
    exact = sum(r in cset for r in ref)
    close = sum(r in cset or any(_ratio(r, c) >= CLOSE for c in cand) for r in ref)
    junk = sum(not any(_ratio(c, r) >= JUNK for r in ref) for c in cand) if cand else 0
    return {"ref": len(ref), "cand": len(cand), "exact": exact / len(ref),
            "close": close / len(ref), "junk": junk / len(cand) if cand else None}


def score(args) -> int:
    bench = json.loads(OUT.read_text(encoding="utf-8"))
    base = {}
    for vol in {p["volume"] for p in bench["pages"]}:
        base[vol] = lines_by_leaf(vol)
    runs = {"ia-microfilm": {(p["volume"], p["leaf"]): base[p["volume"]].get(p["leaf"], [])
                             for p in bench["pages"]}}
    if args.candidate:
        cand = {}
        for line in Path(args.candidate).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            cand[(r["volume"], r["leaf"])] = r["lines"]
        runs[args.name or Path(args.candidate).stem] = cand
    report = {"scored": _dt.date.today().isoformat(), "runs": {}}
    for name, got in runs.items():
        per, agg = [], collections.defaultdict(list)
        for p in bench["pages"]:
            key = (p["volume"], p["leaf"])
            if key not in got:
                continue
            s = page_score(got[key], p["reference"])
            g = page_score(got[key], p["gold"]) if p["gold"] else None
            per.append({"volume": p["volume"], "leaf": p["leaf"], "book": s, "gold": g})
            for k in ("exact", "close", "junk"):
                if s[k] is not None:
                    agg[f"book_{k}"].append(s[k])
                if g and g[k] is not None and k != "junk":
                    agg[f"gold_{k}"].append(g[k])
        means = {k: round(sum(v) / len(v), 3) for k, v in agg.items()}
        report["runs"][name] = {"pages": len(per), "mean": means, "per_page": per}
        print(f"{name:20s} {len(per):3d} pages  " + "  ".join(f"{k} {v:.3f}" for k, v in
                                                            sorted(means.items())))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return 0


def _self_test() -> int:
    ref = ["Smith John, laborer, 12 Pine st", "Brown Mary, widow, 4 Oak st",
           "Jones Wm, cartman, h 9 Elm st"]
    s = page_score(ref, ref)
    assert (s["exact"], s["close"], s["junk"]) == (1.0, 1.0, 0.0)
    s = page_score(["Smith Jobn, laborer, 12 Pine st", "xq zz vv ww tt rr ss"], ref)
    assert s["exact"] == 0.0 and abs(s["close"] - 1 / 3) < 1e-9 and s["junk"] == 0.5
    assert page_score([], ref)["exact"] == 0.0
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["build", "score"])
    ap.add_argument("--candidate", help="score: candidate OCR, JSONL {volume, leaf, lines}")
    ap.add_argument("--name", help="score: the candidate's name in the report")
    ap.add_argument("--out", help="score: write the report as JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "build":
        return build(args)
    if args.cmd == "score":
        return score(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
