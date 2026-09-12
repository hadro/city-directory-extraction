#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Read the survey sidecars and report where the BOOK disagrees with the CATALOG.

See docs/SURVEY_PLAN.md. `survey_census.py` wrote `catalog_says` (IA metadata + the current CSV
row); `survey_frontmatter.py` wrote `book_says` (the volume's own printed front matter, cited to
the leaf). This compares them. Offline -- it only reads data_prep/survey/.

The disagreements are the product. An agreement is a confirmed cell and needs no further work; a
disagreement is a cell that was wrong, or a volume that is not what the catalog thinks it is, and
each one arrives with the image URL that settles it.

    python3 data_prep/survey_report.py               # summary + disagreements
    python3 data_prep/survey_report.py --reads       # the phase-3 image-read queue
    python3 data_prep/survey_report.py --gaps        # cells the survey can now fill
    python3 data_prep/survey_report.py --self-test

Publisher comparison is deliberately loose (surname containment, case-folded). The catalog says
"Trow" where the title page says "TROW CITY DIRECTORY COMPANY", and "Upington" where the page says
"GEORGE UPINGTON". Those are agreements, not conflicts; flagging them would bury the real ones.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIDECAR = HERE / "survey"

STOP = {"the", "and", "of", "co", "company", "corp", "inc", "son", "sons", "bros", "brothers",
        "publisher", "publishers", "publishing", "directory", "city", "general", "new", "york"}


def tokens(s: str):
    return {w for w in re.findall(r"[a-z]+", (s or "").lower()) if len(w) > 2 and w not in STOP}


def publisher_agrees(catalog: str, book: str) -> bool:
    """True when the two name the same house. Containment either way -- the catalog holds a short
    label and the page holds the full legal imprint."""
    a, b = tokens(catalog), tokens(book)
    if not a or not b:
        return False
    return bool(a & b)


def year_of(s):
    m = re.match(r"\s*(\d{4})", str(s or ""))
    return int(m.group(1)) if m else None


def year_agrees(catalog, book) -> bool:
    """Directory years are legitimately ambiguous -- a volume 'for 1846' was published in 1845,
    and a '1852/53' row spans two. One year of slack, and a slash-range matches either end."""
    cy = year_of(catalog)
    if cy is None or book is None:
        return False
    if abs(cy - book) <= 1:
        return True
    m = re.search(r"/\s*(\d{2,4})", str(catalog))
    if m:
        tail = int(m.group(1))
        tail = cy - (cy % 100) + tail if tail < 100 else tail
        return abs(tail - book) <= 1
    return False


def load():
    docs = []
    for p in sorted(SIDECAR.glob("*.json")):
        try:
            docs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:                               # noqa: BLE001 - report, don't die
            print(f"unreadable sidecar: {p}", file=sys.stderr)
    return docs


def compare(doc):
    """-> list of (field, catalog_value, book_value, verdict, citation)."""
    cat = (doc.get("catalog_says") or {}).get("csv") or {}
    ia = (doc.get("catalog_says") or {}).get("ia") or {}
    book = doc.get("book_says") or {}
    out = []

    if "year" in book:
        b = book["year"]["value"]
        for label, src in (("csv", cat.get("year")), ("ia", ia.get("date") or ia.get("year"))):
            if src:
                out.append(("year/" + label, src, b,
                            "agree" if year_agrees(src, b) else "CONFLICT", book["year"]))
    if "publisher" in book:
        b = book["publisher"]["value"]
        if cat.get("publisher"):
            out.append(("publisher/csv", cat["publisher"], b,
                        "agree" if publisher_agrees(cat["publisher"], b) else "CONFLICT",
                        book["publisher"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--reads", action="store_true", help="the phase-3 image-read queue")
    ap.add_argument("--gaps", action="store_true", help="cells the survey can now fill")
    args = ap.parse_args(argv)

    if args.self_test:
        assert publisher_agrees("Trow", "TROW CITY DIRECTORY COMPANY")
        assert publisher_agrees("Upington", "GEORGE UPINGTON")
        assert publisher_agrees("Spooner", "Alden Spooner")
        assert not publisher_agrees("Trow", "Alden Spooner"), "different houses must conflict"
        # Generic words must not manufacture agreement between unrelated imprints.
        assert not publisher_agrees("New York Directory Co", "City Directory Publishing Co"), \
            "stopwords must not match two different houses to each other"
        assert year_agrees("1906", 1906) and year_agrees("1845", 1846), "one year of slack"
        assert year_agrees("1852/53", 1853), "a slash range matches either end"
        assert year_agrees("1899/00", 1900), "a two-digit tail crossing the century rolls over"
        assert not year_agrees("1845", 1899), "a real conflict must survive the slack"
        assert not year_agrees("", 1906) and not year_agrees("1906", None)
        print("self-test OK", file=sys.stderr)
        return 0

    docs = load()
    ia = [d for d in docs if d["source"] == "ia"]
    print(f"sidecars {len(docs)}  ({len(ia)} ia)\n")
    print("survey_status:")
    for k, n in Counter(d.get("survey_status") for d in docs).most_common():
        print(f"  {n:4d}  {k}")

    if args.reads:
        q = [d for d in ia if d.get("survey_status") == "needs-image-read"]
        print(f"\nphase-3 image-read queue: {len(q)} volumes, "
              f"{sum(len((d.get('structure') or {}).get('image_read_urls') or []) for d in q)} "
              f"candidate images")
        for d in q:
            urls = (d.get("structure") or {}).get("image_read_urls") or []
            cat = (d.get("catalog_says") or {}).get("csv") or {}
            print(f"  {d['id'][:38]:38s} {str(cat.get('year'))[:9]:9s} "
                  f"{str(cat.get('publisher'))[:18]:18s} {urls[0] if urls else '(no candidate)'}")
        return 0

    if args.gaps:
        fill = Counter()
        for d in ia:
            cat = (d.get("catalog_says") or {}).get("csv") or {}
            book = d.get("book_says") or {}
            st = d.get("structure") or {}
            if not cat.get("key_page") and st.get("legend_leaves"):
                fill["key_page (legend leaf found)"] += 1
            if not cat.get("year") and "year" in book:
                fill["year"] += 1
            if not cat.get("publisher") and "publisher" in book:
                fill["publisher"] += 1
            if not cat.get("title") and "title" in book:
                fill["title"] += 1
            if "volume_number" in book:
                fill["volume_number (new column)"] += 1
            if (d.get("page_numbers") or {}).get("tier") in ("A", "B"):
                fill["start/end_page + page_offset (free, tier A/B)"] += 1
        print("\ncells this survey can now fill:")
        for k, n in fill.most_common():
            print(f"  {n:4d}  {k}")
        return 0

    rows = [(d, c) for d in ia for c in compare(d)]
    verdicts = Counter(c[3] for _d, c in rows)
    print(f"\nconfirmations: {verdicts.get('agree', 0)} agree, "
          f"{verdicts.get('CONFLICT', 0)} conflict\n")

    conflicts = [(d, c) for d, c in rows if c[3] == "CONFLICT"]
    if not conflicts:
        print("no conflicts.")
        return 0
    print(f"CONFLICTS ({len(conflicts)}) -- catalog vs the printed page, with the leaf that says so:")
    for d, (field, cv, bv, _v, cit) in sorted(conflicts, key=lambda r: r[1][0]):
        print(f"\n  {d['id']}  [{field}]")
        print(f"    catalog : {cv!r}")
        print(f"    book    : {bv!r}   (leaf {cit['leaf']}, {cit['evidence_type']}, "
              f"{cit.get('attestation', cit.get('evidence_detail', cit['method']))})")
        print(f"    quote   : {cit['quote'][:100]!r}")
        print(f"    settle  : {cit['image']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
