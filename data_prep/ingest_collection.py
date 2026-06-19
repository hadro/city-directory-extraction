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
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
MASTER = HERE / "master_directories.csv"
PENDING = HERE / "master_directories.pending.csv"
ARCHIVE_DIR = HERE / "nypl_api_archive"
NYPL_API = "https://api.repo.nypl.org/api/v2"           # deprecated 2026-08-01 — archive while we can
NYPL_IIIF_ITEM = "https://api-collections.nypl.org/manifests/{}"
FIELDS = [
    "source", "id", "publisher", "city", "borough", "year",
    "start_page", "end_page", "column_count", "sample_page",
    "holding_institution", "title", "notes",
]

# NYC boroughs, for filling `borough` from MODS subject.geographic / titles when unambiguous.
BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]

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


def boroughs_in_title(title: str) -> list:
    """Boroughs explicitly named in the title. The title is the reliable borough signal; MODS
    subject.geographic is noisy (catalogers cross-reference e.g. a Brooklyn subject onto a
    Manhattan 'New York City directory'), so we deliberately do NOT use subjects here."""
    low = (title or "").lower()
    return [b for b in BOROUGHS if b.lower() in low]


def make_row(source: str, ident: str, *, title: str = "", year_hint: str = "",
             city: str = "", institution: str = "") -> dict:
    title = (title or "").strip()
    year = parse_year(f"{year_hint} {title}".strip())
    publisher = parse_publisher(title)
    flag = eval_flag(publisher, year)
    return {
        "source": source, "id": ident,
        "publisher": publisher, "city": city, "borough": "", "year": year,
        "start_page": "", "end_page": "", "column_count": "", "sample_page": "",
        "holding_institution": institution, "title": title[:200], "notes": flag,
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


# ---------------------------------------------------------------- NYPL enrichment + archival
# The NYPL Digital Collections API (api.repo.nypl.org) is being deprecated 2026-08-01. We use it
# while it lives to pull clean MODS metadata, and archive every response to nypl_api_archive/ so the
# metadata survives the shutdown. Without a token we fall back to scraping the IIIF item manifests.

def _ensure_list(obj) -> list:                          # ported from directory-pipeline nypl_utils
    if obj is None:
        return []
    return obj if isinstance(obj, list) else [obj]


def _unwrap_text(obj) -> str:                           # MODS values are {'$': value}-wrapped
    if isinstance(obj, dict):
        return str(obj.get("$", ""))
    return str(obj) if obj else ""


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def _apply_enrichment(row: dict, publisher_text: str, year_text: str, title: str = "") -> None:
    """Fill publisher/year/title/borough from extracted metadata, then re-check the held-out eval
    flag (publisher is blank at extraction time, so this is the first point the Trow-1850 /
    Lain-1897 check can fire). Only fills blanks — never overwrites curated values."""
    pub = parse_publisher(publisher_text) or publisher_text.strip()
    if pub and not row["publisher"]:
        row["publisher"] = pub
    yr = parse_year(year_text)
    if yr and not row["year"]:
        row["year"] = yr
    if title and not row.get("title"):
        row["title"] = title[:200]
    if not row["borough"]:
        named = boroughs_in_title(row.get("title") or title)
        if len(named) == 1:
            row["borough"] = named[0]
        elif len(named) > 1 and "covers " not in row["notes"]:
            span = "covers " + ", ".join(sorted(set(named)))
            row["notes"] = f"{row['notes']} | {span}" if row["notes"] else span
    flag = eval_flag(row["publisher"], row["year"])
    if flag and not row["notes"].startswith("REVIEW"):
        row["notes"] = f"{flag} | {row['notes']}" if row["notes"] else flag


def _mods_extract(mods: dict) -> dict:
    """Pull publisher / year / primary title / geographic subjects out of a MODS record."""
    pub = year = title = ""
    for oi in _ensure_list(mods.get("originInfo")):
        if not isinstance(oi, dict):
            continue
        pub = pub or _unwrap_text(oi.get("publisher"))
        di = oi.get("dateIssued")
        year = year or _unwrap_text(_ensure_list(di)[0] if isinstance(di, list) else di)
    titles = _ensure_list(mods.get("titleInfo"))
    primary = next((t for t in titles if isinstance(t, dict) and t.get("usage") == "primary"),
                   titles[0] if titles else None)
    if isinstance(primary, dict):
        title = _unwrap_text(primary.get("title"))
        part = _unwrap_text(primary.get("partNumber"))
        if part and part not in title:
            title = f"{title}, {part}"
    geos = []
    for s in _ensure_list(mods.get("subject")):
        if isinstance(s, dict):
            for g in _ensure_list(s.get("geographic")):
                geos.append(_unwrap_text(g) if isinstance(g, (dict, str)) else str(g))
    return {"publisher": pub, "year": year, "title": title, "geos": geos}


def enrich_nypl_api(new_rows, all_rows, coll_uuid, token, delay, archive_known) -> None:
    """Preferred path. Fetch item_details for each NYPL item, archive the JSON, and fill publisher/
    year on the *new* rows. Archives all items (unless archive_known is False) since the API is dying."""
    sess = requests.Session()
    sess.headers.update(_SESSION.headers)
    sess.headers["Authorization"] = f'Token token="{token.strip()}"'   # tolerate CRLF .env files
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # archive the collection-level response once, while we can
    cpath = ARCHIVE_DIR / f"_collection_{coll_uuid}.json"
    if not cpath.exists():
        try:
            r = sess.get(f"{NYPL_API}/collections/{coll_uuid}",
                         params={"page": 1, "per_page": 500}, timeout=30)
            r.raise_for_status()
            cpath.write_text(json.dumps(r.json(), ensure_ascii=False), encoding="utf-8")
            time.sleep(delay)
        except Exception as e:
            print(f"  [api] collection archive FAILED: {type(e).__name__}: {e}", file=sys.stderr)

    by_id = {r["id"]: r for r in new_rows}
    targets = (all_rows if archive_known else new_rows)
    nypl = [r for r in targets if r["source"] == "nypl"]
    total = len(nypl)
    for i, r in enumerate(nypl, 1):
        uuid = r["id"]
        apath = ARCHIVE_DIR / f"{uuid}.json"
        try:
            if apath.exists():                          # idempotent: reuse archive, skip the fetch
                data = json.loads(apath.read_text(encoding="utf-8"))
            else:
                resp = sess.get(f"{NYPL_API}/items/item_details/{uuid}",
                                params={"page": 1, "per_page": 1}, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                apath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                time.sleep(delay)                       # only pause when we actually hit NYPL
            target = by_id.get(uuid)
            if target is not None:                      # only the new pending rows get enriched
                mods = data.get("nyplAPI", {}).get("response", {}).get("mods") or {}
                m = _mods_extract(mods)
                _apply_enrichment(target, m["publisher"], m["year"], m["title"])
        except Exception as e:
            print(f"\n  [api] {uuid} FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            t = by_id.get(uuid)
            if t is not None and "enrich failed" not in t["notes"]:
                t["notes"] = ("enrich failed | " + t["notes"]).strip(" |")
        print(f"  [api] {i}/{total} items archived/enriched", end="\r", file=sys.stderr)
    print(file=sys.stderr)


def enrich_nypl_iiif(new_rows, delay) -> None:
    """Fallback path (no token). Scrape publisher/year out of the IIIF item manifest metadata and
    archive each manifest to nypl_api_archive/{uuid}.iiif.json (clearly labeled vs. the API JSON)."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    nypl = [r for r in new_rows if r["source"] == "nypl"]
    total = len(nypl)
    for i, r in enumerate(nypl, 1):
        uuid = r["id"]
        apath = ARCHIVE_DIR / f"{uuid}.iiif.json"
        try:
            if apath.exists():
                man = json.loads(apath.read_text(encoding="utf-8"))
            else:
                resp = _SESSION.get(NYPL_IIIF_ITEM.format(uuid), timeout=30)
                resp.raise_for_status()
                man = resp.json()
                apath.write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
                time.sleep(delay)
            text_parts = []
            for entry in man.get("metadata", []):
                val = entry.get("value", {})
                if isinstance(val, dict):
                    val = " ".join(x for v in val.values() for x in (v if isinstance(v, list) else [v]))
                text_parts.append(_strip_html(str(val)))
            text = " ".join(text_parts)
            m = re.search(r"Publisher:\s*([^|<]+)", text)
            pub = m.group(1).strip() if m else ""
            ym = re.search(r"Date Issued:\s*(\d{4}[^|<]*)", text)
            label = man.get("label", "")
            if isinstance(label, dict):
                label = " ".join(v[0] for v in label.values() if v)
            _apply_enrichment(r, pub, ym.group(1) if ym else text, title=str(label))
        except Exception as e:
            print(f"\n  [iiif] {uuid} FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"  [iiif] {i}/{total} items archived/enriched", end="\r", file=sys.stderr)
    print(file=sys.stderr)


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
    ap.add_argument("--enrich", action="store_true",
                    help="(NYPL) fetch per-item metadata to fill publisher/year; archive every "
                         "response to nypl_api_archive/ (API deprecated 2026-08-01)")
    ap.add_argument("--token", default=os.environ.get("NYPL_API_TOKEN", ""),
                    help="NYPL Digital Collections API token (or set NYPL_API_TOKEN). "
                         "Absent -> fall back to IIIF-manifest scraping")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="seconds between NYPL item fetches (politeness throttle)")
    ap.add_argument("--no-archive-known", action="store_true",
                    help="only fetch/archive the new rows, not the full collection")
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

    if args.enrich and kind == "nypl":
        if args.token:
            print(f"enriching via NYPL API (delay={args.delay}s); archiving -> {ARCHIVE_DIR}",
                  file=sys.stderr)
            enrich_nypl_api(fresh, rows, ident, args.token, args.delay,
                            archive_known=not args.no_archive_known)
        else:
            print("no NYPL_API_TOKEN — falling back to IIIF-manifest scraping", file=sys.stderr)
            enrich_nypl_iiif(fresh, args.delay)
    elif args.enrich:
        print(f"--enrich only applies to NYPL sources (this is {kind}); skipping", file=sys.stderr)

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
