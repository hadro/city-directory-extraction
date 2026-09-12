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
    """True when the two name the same house.

    Three passes, each answering a different way the same name can look different:

    1. a shared significant token -- the catalog holds a short label ("Trow") and the page holds
       the full legal imprint ("THE TROW CITY DIRECTORY COMPANY").
    2. de-spaced containment -- OCR splits words. "THOMAS LONG WORTH" is Longworth, and it showed
       up four separate ways across the Longworth volumes (LONGWOIITH, LOKCWORTH, L0NGW0RTH,
       LONG WORTH). Comparing letters-only defeats the split without defeating anything else.
    3. token prefix -- "Hearnes" against "HENRY R. & WILLIAM J. HEARNE".

    What it deliberately does NOT try to fix is character-level OCR damage: "GEORGE UHNUTON" and
    "GEORGE TTBiNfiTriM" are both Upington, and both stay conflicts. That is correct. Anything
    loose enough to match them would match unrelated houses, and a name the OCR mangled that badly
    is exactly what an image read is for.
    """
    a, b = tokens(catalog), tokens(book)
    if not a or not b:
        return False
    if a & b:
        return True
    na = re.sub(r"[^a-z]", "", (catalog or "").lower())
    nb = re.sub(r"[^a-z]", "", (book or "").lower())
    if len(na) >= 5 and na in nb:
        return True
    if len(nb) >= 5 and nb in na:
        return True
    return any(len(x) >= 5 and len(y) >= 5 and (x.startswith(y) or y.startswith(x))
               for x in a for y in b)


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


ID_YEAR = re.compile(r"(1[78]\d\d|19[0-4]\d)")


def id_year(ident: str):
    """A year embedded in the IA identifier -- a free THIRD witness, independent of both the
    catalog metadata and the page.

    `doggettsnewyorkc1847dogg`, `brooklynnewyork1907p1geor`, `longworthsameric1839newy` all name
    their year, and it repeatedly sides with the printed page against IA's `date` field. Bounded
    to plausible directory years so sequence numbers do not parse: `longworthsameric3818long`
    contains "3818" and yields nothing, which is the correct answer.

    Returns None when the identifier names more than one candidate year -- ambiguity is not a vote.
    """
    found = {int(m) for m in ID_YEAR.findall(ident or "")}
    return found.pop() if len(found) == 1 else None


def adjudicate(ident, csv_year, ia_date, book_year):
    """-> (verdict, witnesses, outliers). Find the odd one out among four INDEPENDENT witnesses.

    There are four, not two, and an earlier version of this lost the signal by lumping the CSV in
    with IA's metadata as one "catalog" voice. `longworthsameric1839newy` is the case that showed
    it: the CSV says 1839, the page says 1839, the identifier says 1839, and only IA's `date`
    field says 1816. That is a clean 3-1 against IA, not a stand-off.

    This is what turns a list of conflicts into a work queue:
      * `book` alone outside the majority -> the read is probably wrong; send the image.
      * `ia` (or `csv`) alone outside it   -> the catalog is wrong and the page proves it.
    """
    w = {}
    for k, v in (("csv", year_of(csv_year)), ("ia", year_of(ia_date)),
                 ("id", id_year(ident)), ("book", book_year)):
        if v is not None:
            w[k] = v
    if len(w) < 3:
        return "too-few-witnesses", w, []

    # The majority cluster: the witness the most others agree with, within a year.
    best_k = max(w, key=lambda k: sum(1 for v in w.values() if abs(w[k] - v) <= 1))
    best_n = sum(1 for v in w.values() if abs(w[best_k] - v) <= 1)
    if best_n * 2 <= len(w):
        return "split -- no majority", w, []

    outliers = sorted(k for k, v in w.items() if abs(v - w[best_k]) > 1)
    if not outliers:
        return "agree", w, []
    if outliers == ["book"]:
        return "the READ is the outlier (send the image)", w, outliers
    if "book" not in outliers:
        return f"the CATALOG is the outlier ({'+'.join(outliers)} wrong)", w, outliers
    return "split -- no majority", w, outliers


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
        # OCR splits words; letters-only containment defeats that without loosening anything else.
        assert publisher_agrees("Longworth", "THOMAS LONG WORTH")
        assert publisher_agrees("Longworth", "D. LONG WORTH")
        assert publisher_agrees("Hearnes", "HENRY R. Sc WILLIAM J. HEARNE"), "prefix, not equality"
        assert publisher_agrees("Spooner", "E. B. SPOONER")
        # Character-level damage must NOT be papered over -- these are what an image read is for.
        assert not publisher_agrees("Upington", "GEORGE UHNUTON"), "mangled OCR stays a conflict"
        assert not publisher_agrees("Upington", "GEORGE TTBiNfiTriM")
        # ... and the loosening must not start matching genuinely different houses.
        assert not publisher_agrees("Smith", "CHARLES JENKINS"), "a real finding must survive"
        assert not publisher_agrees("Boyd", "JOHN J. BRENNAN")
        # Generic words must not manufacture agreement between unrelated imprints.
        assert not publisher_agrees("New York Directory Co", "City Directory Publishing Co"), \
            "stopwords must not match two different houses to each other"
        assert year_agrees("1906", 1906) and year_agrees("1845", 1846), "one year of slack"
        assert year_agrees("1852/53", 1853), "a slash range matches either end"
        assert year_agrees("1899/00", 1900), "a two-digit tail crossing the century rolls over"
        assert not year_agrees("1845", 1899), "a real conflict must survive the slack"
        assert not year_agrees("", 1906) and not year_agrees("1906", None)

        # The third witness. Bounded so sequence numbers do not parse as years.
        assert id_year("doggettsnewyorkc1847dogg") == 1847
        assert id_year("longworthsameric1839newy") == 1839
        assert id_year("longworthsameric3818long") is None, "3818 is not a year"
        assert id_year("1906BPL") == 1906
        assert id_year("newyorkdirectory00fran") is None, "no year named"
        # A slash-year identifier yields its first year, which is the right answer: matching is
        # non-overlapping, so "190607" (the 1906/07 volume) reads 1906 and the trailing 07 is not
        # a second candidate.
        assert id_year("brooklynnewyork190607geor") == 1906
        assert id_year("reprint1889of1786directory") is None, "two real candidates is not a vote"

        # Longworth: csv + page + identifier all say 1839, only IA's `date` says 1816. Lumping
        # csv in with ia as one "catalog" voice reported this as a stand-off; it is 3-1.
        v, w, out = adjudicate("longworthsameric1839newy", "1839", "1816", 1839)
        assert out == ["ia"] and v.startswith("the CATALOG is the outlier"), (v, w, out)
        # 1856BPL: the read came off an ad ("ESTABLISHED 1837"); csv, ia and id all say 1856.
        v, _w, out = adjudicate("1856BPL", "1856", "1856", 1837)
        assert out == ["book"] and v.startswith("the READ is the outlier"), (v, out)
        # Only two witnesses -- not enough to adjudicate, so say so rather than pick.
        assert adjudicate("newyorkdirectory00fran", None, "1889", 1786)[0] == "too-few-witnesses"
        # Everyone agrees; not a conflict at all once the identifier is counted.
        assert adjudicate("doggettsnewyorkc1847dogg", "1847", "1845", 1847)[2] == ["ia"]
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
    # Group by what the third witness says, so the list is a work queue rather than a list.
    buckets = {}
    for d, c in conflicts:
        field, cv, bv, _v, cit = c
        if field.startswith("year"):
            verdict, w, _out = adjudicate(
                d["id"], (d.get("catalog_says", {}).get("csv") or {}).get("year"),
                (d.get("catalog_says", {}).get("ia") or {}).get("date"), bv)
        else:
            verdict, w = "publisher (no year witness)", {}
        buckets.setdefault(verdict, []).append((d, c, w))

    print(f"CONFLICTS ({len(conflicts)}) -- catalog vs the printed page, with the leaf that says "
          f"so.\nYear conflicts are adjudicated by four independent witnesses: the CSV, IA's "
          f"metadata,\na year embedded in the IA identifier, and the page itself.\n")
    for verdict in sorted(buckets, key=lambda k: -len(buckets[k])):
        print(f"\n{'=' * 78}\n{verdict.upper()}  ({len(buckets[verdict])})\n{'=' * 78}")
        for d, (field, cv, bv, _v, cit), w in sorted(buckets[verdict], key=lambda r: r[0]["id"]):
            print(f"\n  {d['id']}  [{field}]"
                  + (f"   witnesses: {', '.join(f'{k}={v}' for k, v in sorted(w.items()))}"
                     if w else ""))
            print(f"    catalog : {cv!r}")
            print(f"    book    : {bv!r}   (leaf {cit['leaf']}, {cit['evidence_type']}, "
                  f"{cit.get('attestation', cit.get('evidence_detail', cit['method']))})")
            print(f"    quote   : {cit['quote'][:100]!r}")
            print(f"    settle  : {cit['image']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
