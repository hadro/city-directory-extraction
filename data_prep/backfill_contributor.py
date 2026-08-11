#!/usr/bin/env python3
"""Backfill `contributing_institution` in master_directories.csv.

Why this exists: `holding_institution` records where the scan is *hosted*, which for the 291
`source=ia` rows is just "Internet Archive". That erases the libraries that actually digitized
the volumes — Brooklyn Public Library alone contributed 186 of them. Since the catalog is meant
to ship as a standalone community reference, it needs to credit them.

For `ia` rows the contributor comes from the IA metadata API. A handful of BPL items carry no
`contributor` field at all; those fall back to `uploader` / `collection`, both of which name BPL
unambiguously. `nypl` and `loc` rows are their own contributor.

Idempotent, and caches API responses so re-runs are free:

    python3 data_prep/backfill_contributor.py            # write the column
    python3 data_prep/backfill_contributor.py --dry-run  # report only
    python3 data_prep/backfill_contributor.py --refresh  # ignore the cache
"""

import argparse
import csv
import json
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASTER = HERE / "master_directories.csv"
CACHE = HERE / ".ia_contributor_cache.json"

NEW_FIELD = "contributing_institution"
AFTER_FIELD = "holding_institution"

SOURCE_DEFAULTS = {
    "nypl": "New York Public Library",
    "loc": "Library of Congress",
}

# IA `contributor` strings vary by deposit batch; collapse to one label per institution.
NORMALIZE = {
    "brooklyn public library, brooklyn collection": "Brooklyn Public Library",
    "brooklyn public library": "Brooklyn Public Library",
    "allen county public library genealogy center": "Allen County Public Library",
    "columbia university libraries": "Columbia University Libraries",
    "the new york public library": "New York Public Library",
}

# Fallbacks for items with no `contributor`: (metadata field, substring) -> institution.
FALLBACKS = [
    ("uploader", "bklynlibrary.org", "Brooklyn Public Library"),
    ("collection", "brooklynpubliclibrary", "Brooklyn Public Library"),
    ("collection", "durstoldyorklibrary", "Columbia University Libraries"),
    ("collection", "allen_county", "Allen County Public Library"),
]


def normalize(raw):
    return NORMALIZE.get(raw.strip().lower(), raw.strip())


def ia_metadata(ident, timeout=45):
    url = f"https://archive.org/metadata/{ident}/metadata"
    with urllib.request.urlopen(url, timeout=timeout) as fh:
        return json.load(fh).get("result") or {}


def resolve_ia(ident):
    """-> (institution, how) or (None, reason). `how` is 'contributor' or a fallback field."""
    try:
        meta = ia_metadata(ident)
    except Exception as exc:                                     # network, 404, malformed JSON
        return None, f"fetch failed: {exc}"

    contributor = meta.get("contributor") or ""
    if isinstance(contributor, list):
        contributor = contributor[0] if contributor else ""
    if contributor.strip():
        return normalize(contributor), "contributor"

    for field, needle, institution in FALLBACKS:
        value = meta.get(field) or ""
        if isinstance(value, list):
            value = " ".join(value)
        if needle in str(value).lower():
            return institution, field

    return None, "no contributor, no fallback matched"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report, don't write the CSV")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache, re-fetch every item")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    with MASTER.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    cache = {} if args.refresh or not CACHE.exists() else json.loads(CACHE.read_text())

    ia_ids = sorted({r["id"] for r in rows if r["source"] == "ia"})
    todo = [i for i in ia_ids if i not in cache]
    print(f"{len(rows)} rows | {len(ia_ids)} IA items | {len(todo)} to fetch "
          f"({len(ia_ids) - len(todo)} cached)")

    if todo:
        with ThreadPoolExecutor(args.workers) as pool:
            for ident, (institution, how) in zip(todo, pool.map(resolve_ia, todo)):
                if institution:
                    cache[ident] = institution
                else:
                    print(f"  UNRESOLVED {ident}: {how}", file=sys.stderr)
        CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))

    unresolved = []
    for row in rows:
        source = row["source"]
        if source in SOURCE_DEFAULTS:
            row[NEW_FIELD] = SOURCE_DEFAULTS[source]
        elif source == "ia":
            row[NEW_FIELD] = cache.get(row["id"], "")
            if not row[NEW_FIELD]:
                unresolved.append(row["id"])
        else:                                                    # `iiif` rows: hand-curated
            row[NEW_FIELD] = row.get(NEW_FIELD) or row.get(AFTER_FIELD, "")

    print(f"\n{NEW_FIELD}:")
    for institution, n in Counter(r[NEW_FIELD] for r in rows).most_common():
        print(f"  {n:4d}  {institution or '(unresolved)'}")

    if unresolved:
        print(f"\n{len(unresolved)} unresolved: {', '.join(unresolved[:10])}", file=sys.stderr)

    if args.dry_run:
        print("\n--dry-run: not written")
        return 1 if unresolved else 0

    if NEW_FIELD not in fieldnames:
        fieldnames.insert(fieldnames.index(AFTER_FIELD) + 1, NEW_FIELD)

    with MASTER.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nwrote {MASTER}")
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
