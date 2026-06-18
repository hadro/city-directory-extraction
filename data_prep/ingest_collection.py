#!/usr/bin/env python3
"""
Ingest a collection link into the master directory list.

Given a URL — an NYPL collection page, an Internet Archive collection page, or any IIIF
Collection/Manifest URL — extract the child directory volumes and emit candidate rows in the
`master_directories.csv` schema (see master_directories.README.md).

Flow (review-then-append):
    1. ingest_collection.py <url>            # extract -> data_prep/master_directories.pending.csv
       ...you eyeball the pending file (esp. publisher/year/borough), fix/delete rows...
    2. ingest_collection.py --merge          # merge approved pending rows into the master, dedup

Source detection
----------------
    nypl  : digitalcollections.nypl.org/collections/<uuid>  (or a bare collection UUID)
            -> https://api-collections.nypl.org/manifests/collection/<uuid>  (IIIF v3 Collection)
    ia    : archive.org/details/<collection_id>             (or a bare IA identifier)
            -> advancedsearch.php?q=collection:<id> ...      (paginated JSON)
    iiif  : any IIIF Collection or Manifest URL (BPL, Columbia, CONTENTdm, ...)

Enrichment is best-effort: we parse year/publisher when confident, leave the rest blank, and put
the raw upstream title + any low-confidence guess in `notes`. Borough is never guessed (NYPL's set
is Manhattan-centric and mislabels). Volumes matching a held-out eval signature are flagged.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
MASTER = HERE / "master_directories.csv"
PENDING = HERE / "master_directories.pending.csv"
FIELDS = [
    "source", "id", "publisher", "city", "borough", "year",
    "start_page", "end_page", "column_count", "sample_page",
    "holding_institution", "notes",
]

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "city-directory-ingest/1.0 (+research)"})

# Known publishers (README curation list); first match wins. Order longest/most-specific first.
PUBLISHERS = [
    "Longworth", "Doggett", "Trow", "Lain", "Polk", "Sampson", "Boyd",
    "Wilson", "Goulding", "Franks", "Kollock", "Hodge", "Duncan", "Greenleaf",
]

# Volumes held OUT for the eval panel (README): never silently re-add as harvest rows.
# (publisher-substring, year-substring) — soft match, flagged in notes for review.
EVAL_HELDOUT = [
    ("Trow", "1850"),   # NYU Trow Manhattan 1850/51
    ("Lain", "1897"),   # Lain Brooklyn 1897
]

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


# ---------------------------------------------------------------- source detection

def detect_source(url: str) -> tuple[str, str]:
    """Return (kind, ident). kind in {nypl, ia, iiif}."""
    u = url.strip()
    if "digitalcollections.nypl.org" in u or "api-collections.nypl.org" in u:
        m = UUID_RE.search(u)
        if not m:
            raise ValueError(f"no NYPL collection UUID found in {u!r}")
        return "nypl", m.group(0)
    if UUID_RE.fullmatch(u):                       # bare UUID -> assume NYPL collection
        return "nypl", u
    if "archive.org" in u:
        m = re.search(r"archive\.org/(?:details|download)/([^/?#]+)", u)
        if not m:
            raise ValueError(f"no IA identifier found in {u!r}")
        return "ia", m.group(1)
    if u.startswith("http"):                       # any other URL -> treat as a IIIF manifest
        return "iiif", u
    return "ia", u                                 # bare token -> IA identifier


# ---------------------------------------------------------------- enrichment

def parse_year(text: str) -> str:
    """Extract a directory year/range from a title. '1875/76', '1875-76', or '1875'."""
    m = re.search(r"\b(1[789]\d{2}|20\d{2})\s*[/-]\s*(\d{2,4})\b", text)
    if m:
        return f"{m.group(1)}/{m.group(2)[-2:]}"
    m = re.search(r"\b(1[789]\d{2}|20\d{2})\b", text)
    return m.group(1) if m else ""


def parse_publisher(text: str) -> str:
    low = text.lower()
    for p in PUBLISHERS:
        if p.lower() in low:
            return p
    return ""


def eval_flag(publisher: str, year: str) -> str:
    for pub, yr in EVAL_HELDOUT:
        if pub.lower() in publisher.lower() and yr in year:
            return "REVIEW: matches held-out eval signature — keep OUT of harvest set or confirm"
    return ""


def make_row(source: str, ident: str, *, title: str = "", year_hint: str = "",
             city: str = "", institution: str = "") -> dict:
    title = (title or "").strip()
    year = parse_year(f"{year_hint} {title}".strip())
    publisher = parse_publisher(title)
    notes = []
    flag = eval_flag(publisher, year)
    if flag:
        notes.append(flag)
    if title:
        notes.append(f'title: "{title[:160]}"')
    return {
        "source": source, "id": ident,
        "publisher": publisher, "city": city, "borough": "", "year": year,
        "start_page": "", "end_page": "", "column_count": "", "sample_page": "",
        "holding_institution": institution, "notes": " | ".join(notes),
    }


# ---------------------------------------------------------------- extractors

def extract_nypl(uuid: str) -> list[dict]:
    url = f"https://api-collections.nypl.org/manifests/collection/{uuid}"
    r = _SESSION.get(url, timeout=60)
    r.raise_for_status()
    coll = r.json()
    rows = []
    for child in coll.get("items", []):
        cid = child.get("id", "")
        m = UUID_RE.search(cid)
        if not m:
            continue
        label = child.get("label", {})
        if isinstance(label, dict):                # IIIF v3 language map
            label = " ".join(v[0] for v in label.values() if v)
        rows.append(make_row("nypl", m.group(0), title=str(label), institution="NYPL"))
    return rows


def _ia_search(query: str) -> list[dict]:
    base = "https://archive.org/advancedsearch.php"
    rows, page, per = [], 1, 200
    while True:
        params = [
            ("q", query),
            ("fl[]", "identifier"), ("fl[]", "title"),
            ("fl[]", "year"), ("fl[]", "date"),
            ("rows", str(per)), ("page", str(page)), ("output", "json"),
        ]
        r = _SESSION.get(base, params=params, timeout=60)
        r.raise_for_status()
        resp = r.json().get("response", {})
        docs = resp.get("docs", [])
        for d in docs:
            ident = d.get("identifier")
            if not ident:
                continue
            yr = str(d.get("year") or d.get("date") or "")
            rows.append(make_row(
                "ia", ident, title=d.get("title", ""), year_hint=yr,
                institution="Internet Archive",
            ))
        if page * per >= resp.get("numFound", 0) or not docs:
            break
        page += 1
    return rows


def extract_ia(coll_id: str) -> list[dict]:
    """Treat the identifier as a collection; if that's empty, fall back to a single item."""
    rows = _ia_search(f"collection:{coll_id}")
    if not rows:
        print(f"  no collection members for {coll_id!r}; trying as a single item",
              file=sys.stderr)
        rows = _ia_search(f"identifier:{coll_id}")
    return rows


def extract_iiif(url: str) -> list[dict]:
    r = _SESSION.get(url, timeout=60)
    r.raise_for_status()
    doc = r.json()
    typ = str(doc.get("type") or doc.get("@type") or "")
    if "Collection" in typ:
        children = doc.get("items") or doc.get("manifests") or []
        rows = []
        for child in children:
            cid = child.get("id") or child.get("@id")
            if not cid:
                continue
            label = child.get("label", "")
            if isinstance(label, dict):
                label = " ".join(v[0] for v in label.values() if v)
            elif isinstance(label, list):
                label = " ".join(map(str, label))
            rows.append(make_row("iiif", cid, title=str(label)))
        return rows
    # single Manifest
    label = doc.get("label", "")
    if isinstance(label, dict):
        label = " ".join(v[0] for v in label.values() if v)
    return [make_row("iiif", url, title=str(label))]


# ---------------------------------------------------------------- csv io / dedup

def read_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as f:
        return {(r["source"].strip().lower(), r["id"].strip())
                for r in csv.DictReader(f) if r.get("id")}


def append_rows(path: Path, rows: list[dict]) -> None:
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def merge_pending() -> int:
    if not PENDING.exists():
        sys.exit(f"no pending file at {PENDING}")
    existing = read_keys(MASTER)
    added, skipped = [], 0
    with PENDING.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("id"):
                continue
            key = (r["source"].strip().lower(), r["id"].strip())
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            added.append({k: r.get(k, "") for k in FIELDS})
    append_rows(MASTER, added)
    print(f"merged {len(added)} rows into {MASTER.name} ({skipped} dupes skipped)", file=sys.stderr)
    if added:
        PENDING.unlink()
        print(f"cleared {PENDING.name}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="NYPL / IA collection page, or IIIF manifest URL")
    ap.add_argument("--merge", action="store_true",
                    help="merge reviewed pending rows into the master (dedup) and clear pending")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="print candidate rows to stdout; do not write the pending file")
    ap.add_argument("--limit", type=int, default=0, help="cap extracted rows (0=all)")
    args = ap.parse_args(argv)

    if args.merge:
        return merge_pending()
    if not args.url:
        ap.error("provide a URL to ingest, or --merge to finalize the pending file")

    kind, ident = detect_source(args.url)
    print(f"detected source={kind} ident={ident}", file=sys.stderr)
    rows = {"nypl": extract_nypl, "ia": extract_ia, "iiif": extract_iiif}[kind](ident)
    if args.limit:
        rows = rows[:args.limit]

    # dedup against both the master and anything already staged in pending
    seen = read_keys(MASTER) | read_keys(PENDING)
    fresh, dupes = [], 0
    for r in rows:
        key = (r["source"].lower(), r["id"])
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        fresh.append(r)

    print(f"extracted {len(rows)} items; {len(fresh)} new, {dupes} already known", file=sys.stderr)
    flagged = sum(1 for r in fresh if r["notes"].startswith("REVIEW"))
    if flagged:
        print(f"  {flagged} flagged for review (held-out eval signature)", file=sys.stderr)

    if args.print_only:
        w = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(fresh)
        return 0

    if fresh:
        append_rows(PENDING, fresh)
        print(f"wrote {len(fresh)} rows -> {PENDING}", file=sys.stderr)
        print(f"review it, then: python {Path(__file__).name} --merge", file=sys.stderr)
    else:
        print("nothing new to stage", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
