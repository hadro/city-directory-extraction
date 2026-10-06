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

from survey_adleaves import ENTRY_RX  # noqa: E402
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


# The contract checks (docs/PIPELINE.md, "Explicitly deprioritized"): an OCR must print what the
# page prints. A vision model can expand the abbreviations NER depends on (`bds` -> `boards`) or
# drop a ditto (`do`), and it can invent a clean entry the page never held.
ABBR = {"h", "r", "b", "bds", "bd", "wid", "n", "c", "cor", "nr", "lab", "carp", "clk", "mer",
        "do", "av", "st"}
EXPANSIONS = {"boards", "widow", "house", "laborer", "carpenter", "clerk", "merchant", "near",
              "corner", "avenue", "street", "ditto"}


def page_score(candidate: list, reference: list) -> dict:
    """One page (see the module docstring). Besides agreement:
        abbr_kept   share of the reference's abbreviation tokens (ABBR) found in the candidate
                    line that matches its line (ratio >= CLOSE)
        expanded    matched lines where the candidate spells out what the reference abbreviates
        invented    share of the candidate's entry-shaped lines that match no reference line
                    (ratio < JUNK): an entry the page may not hold"""
    cand_raw = [t for t in candidate if eligible(norm(t))]
    cand = [norm(t) for t in cand_raw]
    ref = [norm(t) for t in reference if eligible(norm(t))]
    if not ref:
        return {"ref": 0, "cand": len(cand), "exact": None, "close": None, "junk": None}
    cset = set(cand)
    exact = close = abbr_ref = abbr_kept = expanded = 0
    for r in ref:
        if r in cset:
            best, score_ = r, 1.0
        else:
            score_, best = max(((_ratio(r, c), c) for c in cand), default=(0.0, None))
        exact += r in cset
        if score_ < CLOSE:
            continue
        close += 1
        rt, bt = r.split(), collections.Counter(best.split())
        wanted = collections.Counter(t for t in rt if t in ABBR)
        abbr_ref += sum(wanted.values())
        abbr_kept += sum(min(n, bt[t]) for t, n in wanted.items())
        if wanted and any(t in EXPANSIONS and t not in rt for t in bt):
            expanded += 1
    best_ref = [max((_ratio(c, r) for r in ref), default=0.0) for c in cand]
    junk = sum(b < JUNK for b in best_ref)
    entry = [b for t, b in zip(cand_raw, best_ref) if ENTRY_RX.search(t)]
    return {"ref": len(ref), "cand": len(cand), "exact": exact / len(ref),
            "close": close / len(ref), "junk": junk / len(cand) if cand else None,
            "abbr_kept": abbr_kept / abbr_ref if abbr_ref else None, "expanded": expanded,
            "invented": sum(b < JUNK for b in entry) / len(entry) if entry else None}


def load_candidate(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        out[(r["volume"], r["leaf"])] = r
    return out


def score(args) -> int:
    bench = json.loads(OUT.read_text(encoding="utf-8"))
    base = {}
    for vol in {p["volume"] for p in bench["pages"]}:
        base[vol] = lines_by_leaf(vol)
    runs = {"ia-microfilm": {(p["volume"], p["leaf"]): {"lines": base[p["volume"]].get(p["leaf"], []),
                                                          "boxed": True}
                             for p in bench["pages"]}}
    for path in args.candidate or []:
        got = load_candidate(Path(path))
        runs[Path(path).stem] = {k: {"lines": v["lines"],
                                     "boxed": bool(v.get("boxes")) and len(v["boxes"]) == len(v["lines"])}
                                 for k, v in got.items()}
    report = {"scored": _dt.date.today().isoformat(), "runs": {}}
    for name, got in runs.items():
        per, agg = [], collections.defaultdict(list)
        for p in bench["pages"]:
            key = (p["volume"], p["leaf"])
            if key not in got:
                continue
            s = page_score(got[key]["lines"], p["reference"])
            g = page_score(got[key]["lines"], p["gold"]) if p["gold"] else None
            per.append({"volume": p["volume"], "leaf": p["leaf"], "book": s, "gold": g})
            agg["boxed"].append(1.0 if got[key]["boxed"] else 0.0)
            agg["expanded"].append(s.get("expanded") or 0)
            for k in ("exact", "close", "junk", "abbr_kept", "invented"):
                if s.get(k) is not None:
                    agg[f"book_{k}"].append(s[k])
                if g and g.get(k) is not None and k in ("exact", "close"):
                    agg[f"gold_{k}"].append(g[k])
        means = {k: round(sum(v) / len(v), 3) for k, v in agg.items() if k != "expanded"}
        means["expanded_lines"] = sum(agg["expanded"])
        report["runs"][name] = {"pages": len(per), "mean": means, "per_page": per}
    cols = ["book_close", "book_exact", "gold_close", "gold_exact", "book_junk", "book_invented",
            "book_abbr_kept", "expanded_lines", "boxed"]
    print(f"{'run':24s} {'pages':>5s} " + " ".join(f"{c.replace('book_', ''):>12s}" for c in cols))
    for name, r in report["runs"].items():
        print(f"{name:24s} {r['pages']:5d} " + " ".join(
            f"{r['mean'].get(c, float('nan')):12.3f}" if c != "expanded_lines"
            else f"{r['mean'].get(c, 0):12d}" for c in cols))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return 0


STAGE = DATA / "reocr_stage"
RUNS = DATA / "reocr_runs"


def stem(volume: str, leaf: int) -> str:
    return f"{volume}_{leaf:04d}"


def stage(args) -> int:
    """Download each bench page's image to data/reocr_stage/<volume>/<volume>_<leaf>.jpg: the
    layout historical-ocr-eval's engine runners read (engines/run_churro.py and friends)."""
    import urllib.request
    bench = json.loads(OUT.read_text(encoding="utf-8"))
    n = 0
    for p in bench["pages"]:
        dst = STAGE / p["volume"] / f"{stem(p['volume'], p['leaf'])}.jpg"
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(urllib.request.urlopen(p["image"], timeout=180).read())
        n += 1
    print(f"{n} images fetched -> {STAGE.relative_to(REPO)}", file=sys.stderr)
    return 0


TESSERACT = "/opt/homebrew/bin/tesseract"


def prepare(im, variant: str):
    """(image tesseract reads, scale from the original). `raw`: grayscale. `contrast`:
    autocontrast and an unsharp mask for faded film. `sauvola`: local thresholding, which suits
    uneven film exposure and bleed-through that defeat one global threshold; `-k10` softens it
    (k 0.1 for 0.2), `-2x` doubles the image first so thin glyphs and word gaps survive it.
    Plain `sauvola` reads 94% of the book scan's lines closely but glues `n Johnson` and drops
    `c` and `h`, the tokens the record fields rest on (2026-10-05)."""
    from PIL import Image, ImageFilter, ImageOps
    g = im.convert("L")
    if variant == "raw":
        return g, 1.0
    if variant == "contrast":
        return ImageOps.autocontrast(g, cutoff=1).filter(ImageFilter.UnsharpMask(2, 150, 3)), 1.0
    if variant.startswith("sauvola"):
        import numpy as np
        scale = 2.0 if "-2x" in variant else 1.0
        k = 0.1 if "-k10" in variant else 0.2
        if scale != 1.0:
            g = g.resize((int(g.width * scale), int(g.height * scale)), Image.LANCZOS)
        a = np.asarray(g, dtype=np.float64)
        w, R = int(41 * scale) | 1, 128.0
        pad = w // 2
        p_ = np.pad(a, pad + 1, mode="reflect")
        ii = p_.cumsum(0).cumsum(1)
        ii2 = (p_ ** 2).cumsum(0).cumsum(1)
        H, W_ = a.shape

        def box(t):
            return (t[w:w + H, w:w + W_] - t[0:H, w:w + W_] - t[w:w + H, 0:W_] + t[0:H, 0:W_])
        mean = box(ii) / (w * w)
        var = np.maximum(box(ii2) / (w * w) - mean ** 2, 0)
        thr = mean * (1 + k * (np.sqrt(var) / R - 1))
        return Image.fromarray(np.where(a > thr, 255, 0).astype("uint8")), scale
    raise ValueError(variant)


def tesseract_page(job):
    """(volume, leaf, variant, lines, boxes): tesseract's lines in reading order, from its TSV."""
    import os
    import subprocess
    import tempfile
    from PIL import Image
    volume, leaf, variant, psm = job
    img = Image.open(STAGE / volume / f"{stem(volume, leaf)}.jpg")
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        prepared, scale = prepare(img, variant)
        prepared.save(tmp.name)
        # --dpi: on raw film frames tesseract guesses ~633 dpi and reports "Empty page!!"
        out = subprocess.run([TESSERACT, tmp.name, "stdout", "--psm", str(psm), "--dpi", "300",
                              "-l", "eng", "tsv"],
                             capture_output=True, text=True,
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout
    lines = collections.OrderedDict()
    for row in out.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        key = (int(f[2]), int(f[3]), int(f[4]))
        x, y, w, h = (int(v) for v in f[6:10])
        words, box, confs = lines.setdefault(key, ([], [x, y, x + w, y + h], []))
        words.append(f[11])
        confs.append(max(0.0, float(f[10])))
        box[:] = [min(box[0], x), min(box[1], y), max(box[2], x + w), max(box[3], y + h)]
    return (volume, leaf, variant, [" ".join(ws) for ws, _, _ in lines.values()],
            [[round(v / scale) for v in b] for _, b, _ in lines.values()],
            [round(sum(c) / len(c), 1) for _, _, c in lines.values()])


def tesseract(args) -> int:
    import multiprocessing
    bench = json.loads(OUT.read_text(encoding="utf-8"))
    variants = args.variants.split(",")
    jobs = [(p["volume"], p["leaf"], v, args.psm) for p in bench["pages"] for v in variants]
    RUNS.mkdir(parents=True, exist_ok=True)
    out = collections.defaultdict(list)
    with multiprocessing.Pool(args.workers) as pool:
        for n, (vol, leaf, v, lines, boxes, confs) in enumerate(
                pool.imap_unordered(tesseract_page, jobs), 1):
            out[v].append({"volume": vol, "leaf": leaf, "lines": lines, "boxes": boxes,
                           "confs": confs})
            if n % 24 == 0:
                print(f"  {n}/{len(jobs)}", file=sys.stderr)
    for v, rows in out.items():
        path = RUNS / f"tesseract-5.5-{v}-psm{args.psm}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        print(f"-> {path.relative_to(REPO)}", file=sys.stderr)
    return 0


PAIR_OVERLAP = 0.5      # two readings are one printed line when their boxes overlap this much
PAIR_TEXT = 0.6         # ...and their texts are at least this alike


def _overlap(a, b) -> float:
    """The smaller of the vertical and horizontal overlaps, each as a share of the shorter."""
    v = min(a[3], b[3]) - max(a[1], b[1])
    h = min(a[2], b[2]) - max(a[0], b[0])
    if v <= 0 or h <= 0:
        return 0.0
    return min(v / min(a[3] - a[1], b[3] - b[1]), h / min(a[2] - a[0], b[2] - b[0]))


def merge_page(base: dict, other: dict, rule: str, add_unpaired: bool) -> dict:
    """One page, two tesseract readings of it. Every line of `base` is kept, in its order; where
    `other` read the same printed line (boxes overlapping PAIR_OVERLAP, texts PAIR_TEXT alike),
    `rule` picks the text: `conf`, the higher mean word confidence, or `other`, always the other
    reading. Base is the Sauvola run, which finds the lines, and other the contrast run, which
    keeps the small tokens (`n`, `c`, `h`) Sauvola glues or drops."""
    used, lines, boxes = set(), [], []
    for i, (t, bx) in enumerate(zip(base["lines"], base["boxes"])):
        best, best_r = None, PAIR_TEXT
        for j, (u, by) in enumerate(zip(other["lines"], other["boxes"])):
            if j in used or _overlap(bx, by) < PAIR_OVERLAP:
                continue
            r = difflib.SequenceMatcher(None, norm(t), norm(u), autojunk=False).ratio()
            if r >= best_r:
                best, best_r = j, r
        if best is None:
            lines.append(t)
        else:
            used.add(best)
            take_other = (rule == "other" or
                          other.get("confs", [0])[best] > base.get("confs", [0] * (i + 1))[i])
            lines.append(other["lines"][best] if take_other else t)
        boxes.append(bx)
    if add_unpaired:
        for j, (u, by) in enumerate(zip(other["lines"], other["boxes"])):
            if j not in used and not any(_overlap(by, bx) >= PAIR_OVERLAP for bx in base["boxes"]):
                lines.append(u)
                boxes.append(by)
    return {"volume": base["volume"], "leaf": base["leaf"], "lines": lines, "boxes": boxes}


def merge(args) -> int:
    a, b = load_candidate(Path(args.base)), load_candidate(Path(args.other))
    rows = [merge_page(a[k], b[k], args.rule, args.add_unpaired) for k in sorted(a) if k in b]
    path = RUNS / f"{args.name}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} pages -> {path.relative_to(REPO)}", file=sys.stderr)
    return 0


def import_run(args) -> int:
    """historical-ocr-eval's runners write `<stem>_<slug>.txt` beside each staged image, one line
    per printed line (engines/run_churro.py prints the slug): -> data/reocr_runs/<slug>.jsonl."""
    rows = []
    for txt in sorted(STAGE.rglob(f"*_{args.slug}.txt")):
        base = txt.name[:-len(f"_{args.slug}.txt")]
        volume, leaf = base.rsplit("_", 1)
        lines = [t for t in txt.read_text(encoding="utf-8").splitlines() if t.strip()]
        rows.append({"volume": volume, "leaf": int(leaf), "lines": lines})
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{args.slug}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} pages -> {path.relative_to(REPO)}", file=sys.stderr)
    return 0


def _self_test() -> int:
    ref = ["Smith John, laborer, 12 Pine st", "Brown Mary, wid, h 4 Oak st",
           "Jones Wm, cartman, h 9 Elm st"]
    s = page_score(ref, ref)
    assert (s["exact"], s["close"], s["junk"], s["abbr_kept"]) == (1.0, 1.0, 0.0, 1.0)
    s = page_score(["Smith Jobn, laborer, 12 Pine st", "xq zz vv ww tt rr ss"], ref)
    assert s["exact"] == 0.0 and abs(s["close"] - 1 / 3) < 1e-9 and s["junk"] == 0.5
    assert page_score([], ref)["exact"] == 0.0
    s = page_score(["Brown Mary, widow, house 4 Oak st"], ref)
    assert s["expanded"] == 1 and s["abbr_kept"] < 1.0, "an expanded abbreviation is caught"
    s = page_score(ref + ["Wilson Peter, grocer, h 77 Main st"], ref)
    assert s["invented"] == 0.25, "an entry the page does not hold"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["build", "stage", "tesseract", "import", "merge",
                                               "score"])
    ap.add_argument("--base", help="merge: the run whose lines are kept")
    ap.add_argument("--other", help="merge: the run whose readings may replace them")
    ap.add_argument("--rule", default="conf", choices=["conf", "other"], help="merge: who wins")
    ap.add_argument("--add-unpaired", action="store_true",
                    help="merge: also keep lines only the other run found")
    ap.add_argument("--name", help="merge: the output run's name")
    ap.add_argument("--candidate", nargs="*", help="score: candidate runs, JSONL {volume, leaf, "
                                                   "lines[, boxes]}")
    ap.add_argument("--variants", default="raw,contrast,sauvola", help="tesseract: preparations")
    ap.add_argument("--psm", type=int, default=3, help="tesseract: page segmentation mode")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--slug", help="import: the engine slug its runner printed")
    ap.add_argument("--out", help="score: write the report as JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    cmds = {"build": build, "stage": stage, "tesseract": tesseract, "import": import_run,
            "merge": merge, "score": score}
    if args.cmd in cmds:
        return cmds[args.cmd](args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
