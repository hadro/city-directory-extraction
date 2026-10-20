"""
What the repo knows about a volume, for the records browser (browse/README.md): one row of the
`volumes` table per IA identifier, and the columns build_db.py copies onto every record of it
(`copy` under [volumes] in sources.toml).

    python3 browse/volumes.py 1906BPL micro_IABROOKLYN_0039    # print what it finds
    python3 browse/volumes.py --self-test

Three sources, read as they are:
    data_prep/master_directories.csv     the catalog: publisher, city, year, title, ...
    data/survey_census/<id>.json         IA's own metadata (gitignored; re-fetchable)
    data_prep/survey/ia_<id>.json        the survey sidecar: the stated name count, the listing's
                                         leaves, the re-OCR
A volume missing from any of them gets nulls for that source's columns, never an error.

`year` is the catalog's `year` read as its first year ("1852/53" -> 1852), for filtering and
sorting; `catalog_year` keeps it as written, which master_directories.README.md makes the
human-facing summary.

`scan` is the material, by rule: `microfiche` where IA files it in its `microfiche` collection
(the BPL micro_IABROOKLYN_* volumes), `BPL PDF upload` for BPL's ####BPL uploads, `book scan`
otherwise (Columbia, Allen County). IA's OCR engine label is no help here -- it tracks the scan
source, not quality (measured 2026-09-13).

`reocr` is the volume's re-OCR, if it has had one. It is the OCR the volume's listing reads NOW,
not necessarily what a given run read: a run staged before the re-OCR read IA's. Today the two
agree (every data/volumes_reocr volume has one, no data/volumes_run1 volume does), but the staged
lines carry no OCR provenance, so this stays a volume fact and is not copied onto records.
"""
from __future__ import annotations

import csv
import functools
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "data_prep" / "master_directories.csv"
CENSUS = REPO / "data" / "survey_census"
SIDECARS = REPO / "data_prep" / "survey"


@functools.lru_cache(maxsize=1)
def _catalog() -> dict:
    if not CATALOG.exists():
        return {}
    with CATALOG.open(encoding="utf-8", newline="") as fh:
        return {r["id"]: r for r in csv.DictReader(fh) if r.get("source") == "ia"}


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _int(s):
    m = re.match(r"\s*(\d+)", str(s or ""))
    return int(m.group(1)) if m else None


def _blank(s):
    return s if s not in ("", None) else None


def scan(ident: str, collections: list) -> str:
    if "microfiche" in collections:
        return "microfiche"
    if any("microfilm" in c for c in collections):
        return "microfilm"
    if re.fullmatch(r"\d{4}x?BPL", ident):
        return "BPL PDF upload"
    return "book scan"


def label(year, publisher, city, borough) -> str | None:
    """"1858 Lain (Brooklyn)": what Datasette shows for a volume in place of its identifier."""
    place = borough if city in (None, "", "New York") else city
    text = " ".join(str(x) for x in (year, publisher) if x)
    return (f"{text} ({place})" if place else text) or None


@functools.lru_cache(maxsize=None)
def describe(ident: str) -> dict:
    """{column: value} for one volume, in the volumes table's column order."""
    cat = _catalog().get(ident, {})
    census = _json(CENSUS / f"{ident}.json")
    side = _json(SIDECARS / f"ia_{ident}.json")
    stated = (side.get("book_says") or {}).get("stated_name_count") or {}
    listing = side.get("listing") or {}
    collections = census.get("collection") or []
    if isinstance(collections, str):
        collections = [collections]
    city, borough = _blank(cat.get("city")), _blank(cat.get("borough"))
    return {
        "volume": ident,
        "label": label(_blank(cat.get("year")), _blank(cat.get("publisher")), city, borough),
        "year": _int(cat.get("year")),
        "catalog_year": _blank(cat.get("year")),
        "year_covered": _blank(cat.get("year_covered")),
        "year_published": _blank(cat.get("year_published")),
        "ia_date": _blank(census.get("date")),
        "publisher": _blank(cat.get("publisher")),
        "ia_publisher": _blank(census.get("publisher")),
        "printer": _blank(cat.get("printer")),
        "city": city,
        "borough": borough,
        "title": _blank(cat.get("title")) or _blank(census.get("title")),
        "volume_number": _blank(cat.get("volume_number")),
        "column_count": _int(cat.get("column_count")),
        "scan": scan(ident, collections),
        "contributor": _blank(cat.get("contributing_institution")) or _blank(
            census.get("contributor")),
        "ia_collections": collections or None,
        "ia_ocr": _blank(census.get("ocr")),
        "reocr": _blank((side.get("reocr") or {}).get("engine")),
        "leaves": _int(census.get("imagecount")),
        "listing_leaves": (f"{listing['start_leaf']}-{listing['end_leaf']}"
                           if listing.get("start_leaf") is not None else None),
        "stated_name_count": stated.get("value"),
        "stated_approximate": bool(stated.get("approximate")) if stated else None,
        "ia_url": f"https://archive.org/details/{ident}",
        "catalog_notes": _blank(cat.get("notes")),
    }


def _self_test() -> int:
    assert label("1852/53", "Hearne", "Brooklyn", "Brooklyn") == "1852/53 Hearne (Brooklyn)"
    assert label("1906", "Upington", "New York", "Brooklyn") == "1906 Upington (Brooklyn)"
    assert label(None, None, None, None) is None
    assert scan("micro_IABROOKLYN_0039", ["brooklyncitydirectoriesonmicrofiche", "microfiche"]) \
        == "microfiche"
    assert scan("1906BPL", ["brooklyncitydirectoriesonmicrofiche", "americana"]) \
        == "BPL PDF upload", "the collection's name is not the microfiche tag"
    assert scan("doggettsnewyorkc1845dogg", ["durstoldyorklibrary"]) == "book scan"
    assert _int("1852/53") == 1852 and _int("") is None and _int(None) is None
    d = describe("no_such_volume")
    assert d["volume"] == "no_such_volume" and d["year"] is None and d["scan"] == "book scan"
    print("self-test ok")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(_self_test())
    for ident in sys.argv[1:]:
        print(json.dumps(describe(ident), indent=1, ensure_ascii=False))
