#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Printed name counts: how many names a directory says it holds, cited to the page.

    python3 data_prep/survey_counts.py scan        # -> results/stated_counts_candidates.json
    python3 data_prep/survey_counts.py record      # verified CLAIMS -> sidecars + results/stated_counts.json
    python3 data_prep/survey_counts.py --self-test

WHY (docs/SURVEY_PLAN.md, "Some volumes PRINT THEIR OWN ENTRY COUNT"). Doggett's 1845 title page
says "CONTAINS SIXTY-ONE THOUSAND THREE HUNDRED & THIRTY-THREE NAMES", and against it the first
whole-volume run's named records came to 1.002 per printed name once runovers were set aside
(PIPELINE.md stage 6). It is the only gold-free recall check the project has had. Every other
volume that prints its own count gives one more, on a whole volume, for nothing.

`scan` reads each volume's word dump from its first leaf to a few leaves into the listing, where
title pages, prefaces and publishers' notices sit, and keeps every passage that sets a number
beside "names":

    digits      "upwards of 125,000 names", "Number of names ... 61,333"
    words       "SIXTY-ONE THOUSAND ... NAMES", parsed by survey_frontmatter.words_to_number,
                which refuses anything it cannot read: 1847's OCR has "ONE HXTNDRED AND
                FIFTT-NUfE", so that one is kept unparsed and flagged for an image read
    comparative "several thousand more names than any heretofore": no count, but a claim
    pages       "The following 1832 pages contain names": a check on the listing bounds instead

A candidate is not a claim. Candidates are read, and the image settles any whose OCR is noisy,
before a count is written to a sidecar as `book_says.stated_name_count`.

`record` writes CLAIMS, the counts read on 2026-09-28, each with how it was checked:

    text    the dump's own OCR, clean digits in a sentence saying what they count. Where the
            same preface also gives last year's count and the increase, the arithmetic is noted
    image   read off the IIIF crop of the passage (1876BPL, 1899xBPL, micro 0039 and 0046)
    sum     1875BPL prints the count under every letter, and the 26 add up exactly to its total

It never overwrites a claim already in the sidecar; an existing claim with a different value is
reported and left alone. Most of what the scan finds is NOT this volume's count, and is left out:
ads for a publisher's other books (Upington's "Elite Directory ... Contains 30,000 names" is in
nine Brooklyn volumes), increases, and prefaces' histories of earlier editions.

The report sets each count against the edition's residential lines (`scope.kept`, all parts of
a multi-part edition). Lines should outnumber names, because runovers, headings and ads are lines
too. Where they do not, names were lost before the model ever ran.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import json
import multiprocessing
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OCR = REPO / "data" / "survey_ocr"
SIDECARS = HERE / "survey"
RESULTS = REPO / "results"
sys.path.insert(0, str(HERE))

from survey_frontmatter import page_image, words_to_number  # noqa: E402

INTO_LISTING = 3        # leaves past the listing's first leaf that are still read
NUM = r"(\d{1,3}(?:[,.]\s?\d{3})+|\d{4,7})"
NUMBER_WORDS = (r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
                r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
                r"fifty|sixty|seventy|eighty|ninety|hundred|thousand")
PATTERNS = [
    ("digits", re.compile(NUM + r"\s+(?:[A-Za-z]+\s+){0,3}?names\b", re.I)),
    ("digits", re.compile(r"\bnames\b[^.\n]{0,50}?\b" + NUM + r"\b", re.I)),
    ("comparative", re.compile(r"([\w\-, ]{3,40}?)\s+more\s+names", re.I)),
    ("pages", re.compile(r"following\s+" + NUM + r"\s+pages\s+contain", re.I)),
    # spelled out: anything between CONTAIN(S/ING) and NAMES, parsed afterwards, so a noisy word
    # keeps the candidate (flagged) instead of losing it
    ("words", re.compile(r"contain(?:s|ing)?\s+((?:[\w\-&',.]+\s+){1,12}?)names\b", re.I)),
]
SANE = (500, 3_000_000)


def leaf_texts(ident: str, stop_leaf: int) -> list:
    """[(leaf, text)] for dump leaves up to stop_leaf, lines joined by newlines."""
    out = []
    with gzip.open(OCR / f"{ident}_words.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["leaf"] > stop_leaf:
                break
            words = rec.get("lines") or []
            out.append((rec["leaf"], "\n".join(" ".join(w[5] for w in ln) for ln in words)))
    return out


def parse_number(s: str):
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def candidates_in(text: str) -> list:
    out = []
    flat = re.sub(r"\s+", " ", text)
    for kind, rx in PATTERNS:
        for m in rx.finditer(flat):
            quote = flat[max(0, m.start() - 60):m.end() + 30].strip()
            value, parsed = None, False
            if kind in ("digits", "pages"):
                value = parse_number(m.group(1))
                parsed = value is not None and SANE[0] <= value <= SANE[1]
                if kind == "digits" and value and 1780 <= value <= 1945 and "," not in m.group(1):
                    parsed = False              # a bare year beside "names", not a count
            elif kind == "words":
                phrase = re.sub(r"[&]", " and ", m.group(1)).strip(" ,.")
                if not re.search(NUMBER_WORDS, phrase, re.I) and not re.search(r"[A-Z]{4,}", phrase):
                    continue                    # "contains the names of" -- prose, no count
                value = words_to_number(phrase)
                parsed = value is not None and SANE[0] <= value <= SANE[1]
            out.append({"kind": kind, "value": value, "parsed": parsed, "match": m.group(0)[:120],
                        "quote": quote[:220]})
    return out


def scan_volume(ident: str):
    d = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    start = (d.get("listing") or {}).get("start_leaf")
    stop = (start + INTO_LISTING) if start is not None else 60
    found = []
    for leaf, text in leaf_texts(ident, stop):
        for c in candidates_in(text):
            found.append({"id": ident, "leaf": leaf, **c, "image": page_image(ident, leaf)})
    return ident, found


def scan(args) -> int:
    idents = sorted(p.name[:-len("_words.jsonl.gz")] for p in OCR.glob("*_words.jsonl.gz"))
    if args.ids:
        want = set(args.ids.split(","))
        idents = [i for i in idents if i in want]
    found = []
    with multiprocessing.Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        for ident, c in pool.imap_unordered(scan_volume, idents):
            found += c
    found.sort(key=lambda c: (c["id"], c["leaf"]))
    out = Path(args.out)
    out.write_text(json.dumps({"derived": _dt.date.today().isoformat(),
                               "volumes_scanned": len(idents), "candidates": found},
                              indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in found:
        v = f"{c['value']:,}" if c["parsed"] else ("?" if c["kind"] != "comparative" else "")
        print(f"{c['id'][:28]:28s} {c['leaf']:4d} {c['kind']:11s} {v:>10s}  {c['quote'][:110]}")
    print(f"\n{len(found)} candidates in {len({c['id'] for c in found})} volumes -> "
          f"{out.relative_to(REPO)}", file=sys.stderr)
    return 0


# ident -> (count, leaf, evidence_type, how, approximate, note). The quote is taken from the scan's
# candidate on that leaf holding the count, or from QUOTES where the OCR garbled it.
CLAIMS = {
    "doggettsnewyorkc1846dogg": (65838, 7, "preface", "text", False,
                                 "the preface's own table: 1845 was 61,333 (the 1845 title page's "
                                 "claim), + 4,505 this year = 65,838"),
    "doggettsnewyorkc1848dogg": (67246, 7, "preface", "text", False,
                                 "printed 67,246; the OCR reads the comma as a period"),
    "longworthsameric1813newy": (17750, 7, "preface", "text", False, None),
    "trowsnewyorkcity1857trow": (150000, 11, "preface", "text", True, "'about 150,000'"),
    "trowsnewyorkcity1859trow": (147325, 7, "preface", "text", False,
                                 "'being 7,521 more than it contained last year'"),
    "trowsnewyorkcity1863trow": (153186, 7, "preface", "text", False,
                                 "last year's (1862-63) was 152,825"),
    "trowsgeneraldir1903p1trow": (405264, 13, "preface", "text", False,
                                  "the whole 1903 edition, all three parts; the same preface "
                                  "gives 1856 150,000 and 1872 211,000"),
    "trowsgeneraldir1912p1trow": (550000, 43, "publishers_table", "text", True,
                                  "'Contains over 550,000 names': a lower bound, closing the "
                                  "table of the New York Directory's publishers"),
    "trowsgeneraldire1915trow": (1104676, 10, "preface", "text", False,
                                 "'names of private citizens', on the listing's 1,832 pages"),
    "1868BPL": (74120, 8, "preface", "text", False, "'an increase of 5,150 over last year'"),
    "1875BPL": (109785, 19, "preface", "sum", False,
                "printed per letter; the 26 counts sum exactly to the printed total"),
    "1876BPL": (114724, 17, "preface", "image", False, "'an increase of 4,939 over last year'"),
    "1878BPL": (118320, 15, "preface", "text", False, "'an increase of 696'"),
    "1880BPL": (125440, 7, "preface", "text", False,
                "1884BPL's preface independently says the 1880 volume 'then contained 125,440'"),
    "1883BPL": (142371, 7, "preface", "text", False, "'an increase ... of 7,362 names'"),
    "1884BPL": (152290, 15, "preface", "text", False, "'an increase over last year of 9,909'"),
    "1886BPL": (163934, 21, "preface", "text", False, None),
    "1887BPL": (175761, 16, "preface", "text", False, "'an increase over last year of 12,827'"),
    "1889BPL": (188074, 3, "preface", "text", False, "'an increase over last year of 6,974'"),
    "1897BPL": (243691, 23, "preface", "text", False, "'or 7,711 more names than last year'"),
    "1899xBPL": (271797, 43, "preface", "image", False,
                 "leaf 15 carries ANOTHER edition's preface, in an older face: '161,238 names ... "
                 "the population of Brooklyn is 704,610' (1884's 152,290 + 8,958, ~1885)"),
    "micro_IABROOKLYN_0039": (50000, 9, "preface", "image", True,
                              "'We claim, this year, 50,000 names'; the previous issue had 38,000"),
    "micro_IABROOKLYN_0046": (7345, 10, "preface", "image", False,
                              "Reynolds's table also gives 1850: 5,300 and 1851: 5,603"),
}
QUOTES = {   # read off the image where the OCR could not carry the digits, or not near "names"
    "micro_IABROOKLYN_0046": "Number of names contained in the Directory for 1852 . . . 7,345",
    "1875BPL": "The following shows the number of names under each letter : A 2,252 ... "
               "Total number in this volume is 109,785",
    # the count sits past the end of the scan's quote window
    "trowsnewyorkcity1863trow": "In the last year's Directory, the number of names was 152,825, "
                                "while the present year it contains 153,186.",
    "trowsgeneraldir1903p1trow": "The number of names in the Directory for 1856 was 150,000; in "
                                 "1872, 211,000, while the present volume contains 405,264.",
    "micro_IABROOKLYN_0039": "The number of names given in the issue of M... 38,000. We claim, "
                             "this year, 50,000 names",
}
BY_LETTER = {"1875BPL": dict(A=2252, B=10181, C=8293, D=6079, E=1834, F=4692, G=4889, H=8816,
                             I=358, J=2088, K=4649, L=4652, M=12691, N=1851, O=2229, P=4008,
                             Q=390, R=5678, S=11356, T=3498, U=245, V=1553, W=6825, X=2, Y=409,
                             Z=267)}
PARTS = {"trowsgeneraldir1903p1trow": ["trowsgeneraldir1903p1trow", "trowsgeneraldir1903p2trow",
                                       "trowsgeneraldir1903p3trow"],
         "trowsgeneraldir1912p1trow": ["trowsgeneraldir1912p1trow", "trowsgeneraldir1912p2trow",
                                       "trowsgeneraldir1912p3trow"]}


def _quote(ident: str, leaf: int, value: int, cands: list) -> str:
    if ident in QUOTES:
        return QUOTES[ident]
    digits = f"{value:,}"
    for c in cands:
        if c["id"] == ident and c["leaf"] == leaf and (c["value"] == value or digits in c["quote"]
                                                        or digits.replace(",", ".") in c["quote"]):
            return c["quote"]
    raise SystemExit(f"{ident}: no candidate on leaf {leaf} carries {digits} -- re-run scan")


def record(args) -> int:
    cands = json.loads(Path(args.out).read_text(encoding="utf-8"))["candidates"]
    written, kept, conflicts, rows = [], [], [], []
    for ident, (value, leaf, etype, how, approx, note) in sorted(CLAIMS.items()):
        path = SIDECARS / f"ia_{ident}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        claim = {"value": value, "leaf": leaf,
                 "canvas": f"https://iiif.archive.org/iiif/{ident}${leaf}/canvas",
                 "image": page_image(ident, leaf), "evidence_type": etype,
                 "quote": _quote(ident, leaf, value, cands),
                 "method": "agent-read" if how in ("image", "sum") else "hocr-text",
                 "confidence": "medium" if approx else "high", "approximate": approx,
                 "checked": how, **({"note": note} if note else {}),
                 **({"by_letter": BY_LETTER[ident]} if ident in BY_LETTER else {})}
        have = (doc.get("book_says") or {}).get("stated_name_count")
        if have and have.get("value") != value:
            conflicts.append((ident, have.get("value"), value))
        elif have:
            kept.append(ident)
        elif args.write:
            doc.setdefault("book_says", {})["stated_name_count"] = claim
            path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            written.append(ident)
        else:
            written.append(ident)
    # every stated count in the sidecars, new and old, against the edition's residential lines
    for p in sorted(SIDECARS.glob("ia_*.json")):
        ident = p.stem[3:]
        d = json.loads(p.read_text(encoding="utf-8"))
        c = (d.get("book_says") or {}).get("stated_name_count")
        if ident in CLAIMS and not args.write:
            v = CLAIMS[ident]
            c = c or {"value": v[0], "approximate": v[4], "leaf": v[1], "method": "(dry run)"}
        if not c:
            continue
        parts = PARTS.get(ident, [ident])
        lines = sum((json.loads((SIDECARS / f"ia_{i}.json").read_text(encoding="utf-8"))
                     .get("scope") or {}).get("kept") or 0 for i in parts)
        rows.append({"id": ident, "stated": c["value"], "approximate": bool(c.get("approximate")
                                                                          or "APPROX" in str(c.get("note", ""))),
                     "leaf": c.get("leaf"), "method": c.get("method"), "parts": parts,
                     "residential_lines": lines,
                     "lines_per_name": round(lines / c["value"], 3) if c["value"] else None})
    report = {"derived": _dt.date.today().isoformat(), "claims": rows,
              "written": written, "already_recorded": kept,
              "conflicts": [{"id": i, "sidecar": a, "read": b} for i, a, b in conflicts]}
    (RESULTS / "stated_counts.json").write_text(json.dumps(report, indent=1) + "\n",
                                                encoding="utf-8")
    verb = "wrote" if args.write else "would write (dry run; --write to commit)"
    print(f"{verb} {len(written)} claims; {len(kept)} already recorded; "
          f"{len(conflicts)} conflicts {conflicts or ''}\n")
    print(f"{'volume':28s} {'stated':>10s} {'lines':>10s} {'lines/name':>10s}")
    for r in sorted(rows, key=lambda r: r["lines_per_name"] or 0):
        approx = "~" if r["approximate"] else " "
        print(f"{r['id'][:28]:28s} {approx}{r['stated']:>9,d} {r['residential_lines']:>10,d} "
              f"{r['lines_per_name']:>10.3f}")
    return 0


def _self_test() -> int:
    assert sum(BY_LETTER["1875BPL"].values()) == CLAIMS["1875BPL"][0], "the printed checksum"
    c = candidates_in("CONTAINS SIXTY-ONE THOUSAND THREE HUNDRED & THIRTY-THREE NAMES.")
    assert any(x["kind"] == "words" and x["value"] == 61333 for x in c), c
    c = candidates_in("CONTAINS SIXTY-EIGHT THOUSAND ONE HXTNDRED AND FIFTT-NUfE NAMES")
    assert any(x["kind"] == "words" and not x["parsed"] for x in c), "noisy: kept, unparsed"
    assert any(x["value"] == 125000 for x in candidates_in("upwards of 125,000 names"))
    assert any(x["kind"] == "comparative" for x in
               candidates_in("contains several thousand more names than any heretofore"))
    assert any(x["kind"] == "pages" and x["value"] == 1832 for x in
               candidates_in("The following 1832 pages contain names of individuals"))
    assert not candidates_in("contains the names of the inhabitants"), "prose, no count"
    assert not any(x["parsed"] for x in candidates_in("1857 names")), "a bare year"
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["scan", "record"])
    ap.add_argument("--ids")
    ap.add_argument("--out", default=str(RESULTS / "stated_counts_candidates.json"))
    ap.add_argument("--write", action="store_true", help="record: write the sidecars")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "scan":
        return scan(args)
    if args.cmd == "record":
        return record(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
