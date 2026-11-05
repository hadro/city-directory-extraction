#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""How many NYPL volumes are unique? 112 of 151 have no counterpart in the IA run set.

    python3 results/nypl_ia_overlap.py                  # -> results/nypl_ia_overlap.json

Run 2026-10-27. The master catalog holds 156 NYPL rows; 5 are phone books, which are out of
scope, leaving 151 city directories (all Manhattan, 1786-1933/34 apart from the 1933/34 Polk
Brooklyn, Queens and Staten Island volumes). The corpus run reads the 153 IA volumes in
`data_prep/run_tiers.json`. Which NYPL volumes does that run already cover as editions, and which
add something? SURVEY_PLAN.md Phase 5 (the NYPL tier) assumed "many NYPL volumes have an IA
counterpart of the same publisher and year".

    NYPL city directories                       151
      same edition as a run-set IA volume        39   (34 matched, 3 probable, 1 reprint, 1 text-verified)
      no IA counterpart                         112   (111 + the one tested-different pair below)

METHOD. NYPL has no OCR here, so this is a catalog match, not a text match. An NYPL row is the
same edition as an IA volume when the publisher series agrees and the year the IA volume PRINTS
(title page, volume number, "Nth year of American Independence"; the survey sidecars'
`book_says`) is the year the NYPL row is labelled with. The identifiers' years are not the
edition (SURVEY_PLAN.md: `1856BPL` is the 1855-56 book), so every rule below is written from what
the volume prints, and `RULES` records the quotation. Three conventions the rules rest on:

  Trow    "FOR THE YEAR ENDING JULY 1, 1907" is NYPL `1906/07`: the NYPL label is `year-1/year`
          and names the year the book ENDS. Volume number n ends in 1787 + n (Vol. 116 = 1903,
          Vol. 128 = 1915 per its own "past 127 years"). IA `trowsgeneraldir1905p1/p2` print
          "JULY 1, 1906" on a Vol. CXVIII title page; the sequence (CXVII = 1904, CXIX = 1906)
          makes Vol. 118 the year ending 1905, so it is read as an OCR slip for `1904/05`.
          If it is truly 1906 that one pair moves, and the count is off by one.
  Longworth  the book runs July to July, and the label is the START year: "26th Year American
          Independence, July 1801" is NYPL `1801/02`. The Nth year begins in July 1775 + N.
  Doggett    "FOR 1845 & 1846, Fourth Publication" is NYPL `1845/46`.

HOW SURE EACH MATCH IS (`confidence` in the JSON):
  matched            publisher, printed year and, where it prints one, the volume number agree
  probable           the printed volume or publication number agrees but the NYPL row carries a
                     different publisher name (Rode's 13th publication is NYPL's `Doggett` 1854/55)
                     or the NYPL row is one of two parts (Polk 1915)
  reprint            same work, other printing: NYPL's Franks 1786 is the original, IA's volume
                     is Durst's 1874 reprint (the twin of franks1786 in survey_twins_gold.json)
  text-verified      `survey_harvest.GOLD_TWINS`: the polk1917 NYPL gold page read against the IA
                     scan, fuzzy 97% (survey_twins.py docstring)
  tested-different   same publisher and label, and a page read says NOT the same edition:
                     NYPL Trow/Wilson 1865/66 vs `bub_gb_hY4tAAAAYAAJ` (`survey_twins.NOT_TWINS`:
                     Mason & Hamlin at "No. 7 Mercer Street" against "596 Broadway"). Counted as
                     unique

THE 39 IS AN UPPER BOUND. That one tested pair of three NYPL gold sets with a same-label IA volume
(polk1917 twin, trowwilson1865 not, trow1913 inconclusive: ABBYY-8 reads the ditto `ii`, so the
exact-line test cannot judge it) says a matching label does not prove a matching edition.

WHAT IS LEFT. The 112 unique rows by era: 1786-1819 31, 1820-51 25, 1852-81 26, 1882-1914 21,
1915-34 9. By series: Longworth 38, Trow/Wilson 24, Trow 23, Polk 7, the rest small publishers and
the 1931 and 1933/34 volumes. Nearly all of Trow/Wilson 1852-81 and Trow 1882-1902 is unique, the
Longworth years IA lacks (mostly 1799-1842), and everything after 1918. Three Longworth 1797 rows
are probably copies of one edition (`possible_copies` in the JSON; unconfirmed), and the blank-id
`1898/99` Trow row cannot be fetched at all: about 110 distinct editions. The four 1933/34 Polk
rows in `same_year_publisher_groups` are four different volumes, not copies.

NOT DONE. No NYPL page was read against an IA page, apart from the gold pages above. A page-read
of the 39 would turn "upper bound" into a count; the cheapest check is the 3 probable and the 11
Trow general volumes, where one NYPL volume is three IA parts.
"""
import argparse
import collections
import csv
import json
import re
import subprocess
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSV_PATH = REPO / "data_prep" / "master_directories.csv"
TIERS = REPO / "data_prep" / "run_tiers.json"
SIDECARS = REPO / "data_prep" / "survey"

# NYPL label -> publisher prefixes that may carry it (None: any), IA volume(s), confidence, why.
# The IA volumes are named by `ia` when they are a fixed list, and by `trow_year` when they are
# the Trow general directory's parts, found from the catalog (id `trowsgenerald*`, year = IA's).
RULES = []


def rule(nypl_year, pubs, ia, confidence, basis):
    RULES.append({"nypl_year": nypl_year, "publishers": pubs, "ia": ia,
                  "confidence": confidence, "basis": basis})


rule("1786", None, ["newyorkdirectory00durs_0"], "reprint",
     "Durst's 1874 reprint of Franks's 1786 directory (survey_harvest.GOLD_TWINS, franks1786)")
rule("1794", None, ["newyorkdirectory00dunc"], "matched",
     "title page 'FOR THE YEAR 1794'; NYPL holds two copies")
rule("1798", None, ["longworthsameric1798newy"], "matched",
     "'Twenty-third Year of American Independence', 1798")
LONGWORTH = [
    ("1801/02", "longworthsameric2618long", "'JULY, 1801, 26th Year American Independence'"),
    ("1812/13", "longworthsameric1813newy", "'THIRTY-SEVENTH YEAR OF AMERICAN INDEPENDENCE', July 4th 1812"),
    ("1813/14", "longworthsameric3818long", "ident 38 = 38th year; almanac 'for the year of our Lord 1814'"),
    ("1815/16", "longworthsameric4018long", "ident 40 = 40th year; almanac 'for 1816'"),
    ("1823/24", "longworthsameric4818long", "ident 48 = 48th year; sidecar year_covered 1823"),
    ("1826/27", "longworthsameric1826newy", "'FIFTY-FIRST YEAR OF AMERICAN INDEPENDENCE'"),
    ("1835/36", "longworthsameric6018long", "ident 60 = 60th year; imprint 1835"),
    ("1836/37", "longworthsameric6118long", "'Sixty-first Year of American Independence'"),
    ("1839/40", "longworthsameric00newy", "'SIXTY-FOURTH YEAR OF AMERICAN INDEPENDENCE'"),
    ("1840/41", "longworthsameric6518long", "'sixty-fifth year of American Independence'"),
]
for y, ident, why in LONGWORTH:
    rule(y, ["Longworth"], [ident], "matched", why)
rule("1820/21", ["Mercein"], ["merceinscitydire00merc"], "matched",
     "'FOR THE YEARS OF OUR LORD 1820-21. Being the 45th year of American Independence'")
for y, ident, why in [
        ("1845/46", "doggettsnewyorkc1845dogg", "'FOR 1845 & 1846. Fourth Publication'"),
        ("1846/47", "doggettsnewyorkc1846dogg", "'FOR 1846 and 1847'"),
        ("1847/48", "doggettsnewyorkc1847dogg", "'FOR 1847 & 1848. Sixth Publication'"),
        ("1848/49", "doggettsnewyorkc1848dogg", "'1848-1849' publication")]:
    rule(y, ["Doggett"], [ident], "matched", why)
rule("1854/55", ["Doggett"], ["newyorkcitydirec00rode"], "probable",
     "'FOR 1854-1855. Thirteenth Publication. ESTABLISHED IN 1842': Doggett's series, 1842 + 12; "
     "NYPL files the volume under Doggett")
for y, ident, why in [
        ("1856/57", "trowsnewyorkcity1857trow", "'FOR THE YEAR ENDING MAY 1, 1857'"),
        ("1859/60", "trowsnewyorkcity1859trow", "'The Directory for 1859-60 contains 147,325 names'"),
        ("1862/63", "trowsnewyorkcity1863trow", "'TO THE SEVENTY-SIXTH VOLUME': Vol. 76 ends 1787 + 76 = 1863"),
        ("1876/77", "trowsnewyorkcity1876trow", "front matter '1876-77'")]:
    rule(y, ["Trow"], [ident], "matched", why)
rule("1865/66", ["Trow/Wilson"], ["bub_gb_hY4tAAAAYAAJ"], "tested-different",
     "same label, read off the image 2026-09-28 and NOT the same edition (survey_twins.NOT_TWINS)")
for ia_year in list(range(1903, 1913)) + [1914]:
    rule(f"{ia_year - 1}/{str(ia_year)[2:]}", ["Trow"], {"trow_year": str(ia_year)}, "matched",
         f"Trow's general directory Vol. {ia_year - 1787}, 'FOR THE YEAR ENDING JULY/AUGUST 1, {ia_year}'")
rule("1915-pt1", None, {"trow_year": "1915"}, "probable",
     "IA 'Volume 128' (Polk's Trow) for 1915; NYPL splits 1915 into two parts")
rule("1915-pt2", None, {"trow_year": "1915"}, "probable",
     "IA 'Volume 128' (Polk's Trow) for 1915; NYPL splits 1915 into two parts")
rule("1917", ["Polk"], ["trowsgeneraldire1917trow"], "text-verified",
     "survey_harvest.GOLD_TWINS polk1917: NYPL gold page against the IA scan, fuzzy 97%")
rule("1921/22", ["Polk"], {"trow_year": "1922/23"}, "matched",
     "NYPL title is 'New York City directory, 1922-1923'; IA 'VOL 133 ... 1922-1923'")


def git_rev():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "data_prep", "results"],
                               cwd=REPO, capture_output=True, text=True).stdout.strip()
        return out + ("-dirty" if dirty else "")
    except Exception:
        return None


def era(year: str) -> str:
    y = int(year[:4])
    return ("1786-1819" if y < 1820 else "1820-1851" if y < 1852 else
            "1852-1881" if y < 1882 else "1882-1914" if y < 1915 else "1915-1934")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "results" / "nypl_ia_overlap.json"))
    args = ap.parse_args()

    catalog = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    run_set = set(json.load(open(TIERS, encoding="utf-8"))["volumes"])
    ia_rows = {r["id"]: r for r in catalog if r["source"] == "ia"}
    nypl = [r for r in catalog if r["source"] == "nypl" and "PHONEBOOK" not in r["notes"].upper()]

    def trow_parts(year):
        return sorted(i for i, r in ia_rows.items()
                      if i.startswith("trowsgenerald") and r["year"] == year and i in run_set)

    problems = []
    for ru in RULES:
        if isinstance(ru["ia"], dict):
            ru["ia_volumes"] = trow_parts(ru["ia"]["trow_year"])
        else:
            ru["ia_volumes"] = list(ru["ia"])
        # bub_gb is in the run set as a volume, whatever the verdict says of it
        missing = [i for i in ru["ia_volumes"] if i not in run_set]
        if not ru["ia_volumes"] or missing:
            problems.append(f"rule {ru['nypl_year']}: IA volume not in the run set: "
                            f"{missing or 'none found'}")

    rows, used = [], collections.Counter()
    for r in nypl:
        hit = None
        for n, ru in enumerate(RULES):
            if r["year"] != ru["nypl_year"]:
                continue
            if ru["publishers"] and not any(r["publisher"].startswith(p) or p.startswith(r["publisher"])
                                            for p in ru["publishers"]):
                continue
            hit = ru
            used[n] += 1
        verdict = hit["confidence"] if hit else "unique"
        rows.append({
            "id": r["id"] or None, "year": r["year"], "publisher": r["publisher"],
            "borough": r["borough"] or None, "title": r["title"],
            "verdict": verdict,
            "ia_volumes": hit["ia_volumes"] if hit else [],
            "basis": hit["basis"] if hit else None,
        })
    for n, ru in enumerate(RULES):
        if not used[n]:
            problems.append(f"rule {ru['nypl_year']} {ru['publishers']} matched no NYPL row")

    counts = collections.Counter(x["verdict"] for x in rows)
    same = sum(v for k, v in counts.items() if k not in ("unique", "tested-different"))
    unique = [x for x in rows if x["verdict"] in ("unique", "tested-different")]

    groups = collections.defaultdict(list)
    for x in unique:
        groups[(x["year"], x["publisher"])].append(x)
    summary = {
        "nypl_city_directories": len(rows),
        "same_edition_as_run_set_ia": same,
        "no_ia_counterpart": len(unique),
        "verdicts": dict(counts),
        "blank_id_rows": [x["year"] for x in rows if not x["id"]],
        "unique_by_era": dict(collections.Counter(era(x["year"]) for x in unique)),
        "unique_by_publisher": dict(collections.Counter(x["publisher"] for x in unique).most_common()),
        "same_year_publisher_groups": {f"{y} {p}": [(g["id"] or "")[:8] + " " + g["title"] for g in v]
                                       for (y, p), v in groups.items() if len(v) > 1},
        "possible_copies": [x["id"][:8] for x in unique if x["year"] == "1797"],
    }
    out = {
        "derived": date.today().isoformat(), "code_at": git_rev(),
        "method": "catalog match: publisher series + the edition year the IA volume prints; "
                  "no NYPL page was read except the gold pages named in `basis`",
        "run_set_volumes": len(run_set),
        "summary": summary,
        "rules": [{k: v for k, v in ru.items() if k != "ia"} for ru in RULES],
        "rows": rows,
        "problems": problems,
    }
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"{len(rows)} NYPL city directories: {same} same edition as a run-set IA volume, "
          f"{len(unique)} with none")
    print("  verdicts:", dict(counts))
    print("  unique by era:", summary["unique_by_era"])
    for p in problems:
        print("PROBLEM:", p)
    print("->", args.out)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
