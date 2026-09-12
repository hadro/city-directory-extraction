#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Phase 0a of the corpus survey: what the CATALOG claims, and which derivatives exist.

See docs/SURVEY_PLAN.md. This writes only `catalog_says` -- IA's metadata endpoint, plus the
current CSV row. None of it is treated as fact; `survey_frontmatter.py` (phase 0b) writes
`book_says` from the volume's own printed pages, and disagreement between the two is the
signal this survey exists to produce.

What it is really for, beyond bookkeeping: routing. `<ident>_page_numbers.json` ships with every
IA item and carries a per-leaf printed page number, but it is EMPTY or sparse on half the corpus,
and the volume-level `confidence` field tells you which -- for free, before you download a single
page. Measured over all 184 non-phonebook `ia` rows (0 errors, 47 s):

    A trust directly   31    conf >= 90 and >= 85% of leaves numbered
    B verify monotone  55    conf >= 50 or >= 70% numbered
    C sparse           59    neither
    D empty            39    file present, zero numbers

Plan on 86 free / 98 fallback, NOT 145/39: tier C is closer to D than to B
(`brooklynnewyorkc19062geor` is "C" with 11 of 1346 leaves filled). The fallback is the
bottom-margin regression in `survey_pagenumbers.py`, and it happens to work best exactly where
tier C lives -- 49 of those 59 volumes are dense ABBYY.

    python3 data_prep/survey_census.py                  # all ia rows, resumable
    python3 data_prep/survey_census.py --report         # re-print tiers from cache, no network
    python3 data_prep/survey_census.py --ident 1906BPL  # one volume
    python3 data_prep/survey_census.py --self-test      # offline

Two caches, deliberately different:
  * `data/survey_census/<ident>.json` -- the raw API response distillate, including the full file
    listing. Bulky, re-fetchable, gitignored.
  * `data_prep/survey/<source>_<id>.json` -- the sidecar. Curated, committed, and the thing
    `apply_survey.py` later merges into master_directories.csv.

Phonebook rows are excluded here (the survey is the residential corpus). NYPL and LoC rows are
phase 5 and get no IA lookup; a stub sidecar is still written so the corpus is countable.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MASTER = HERE / "master_directories.csv"
SIDECAR = HERE / "survey"
RAWCACHE = REPO / "data" / "survey_census"

UA = {"User-Agent": "Mozilla/5.0 (research; city-directory corpus survey; +josh)"}
META = "https://archive.org/metadata/{ident}"

# IA's own page-number detector. Present on every item; populated on about half.
PN_SUFFIX = "_page_numbers.json"

# Raw-cache schema version. Bump when the shape of probe_ia()'s output changes; entries without
# a matching `_v` are refetched rather than half-read. v1 stored `files` as {name: size}, which
# lost the sha1/mtime the sidecar needs to detect a later IA re-OCR.
CACHE_V = 2


def _get(url: str, timeout: int = 90, retries: int = 3) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                          # noqa: BLE001 - network, surfaced below
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def pn_tier(filled: int, leaves: int, conf) -> str:
    """Route a volume to its page-number source. Returns A / B / C / D.

    The thresholds are the measured ones (see module docstring). `conf` is IA's volume-level
    confidence, which is the cheap router -- but it is NOT sufficient alone, because a volume can
    carry a middling confidence over almost no filled leaves. Both terms are required for A.
    """
    if not leaves or not filled:
        return "D"
    frac = filled / leaves
    if conf is not None and conf >= 90 and frac >= 0.85:
        return "A"
    if (conf is not None and conf >= 50) or frac >= 0.70:
        return "B"
    return "C"


def probe_ia(ident: str, refresh: bool = False) -> dict:
    """-> the raw distillate for one IA item. Cached; a cache hit costs no network."""
    RAWCACHE.mkdir(parents=True, exist_ok=True)
    cached = RAWCACHE / f"{ident}.json"
    if cached.exists() and not refresh:
        try:
            doc = json.loads(cached.read_text(encoding="utf-8"))
            if doc.get("_v") == CACHE_V:
                return doc
        except Exception:                               # noqa: BLE001 - corrupt cache, refetch
            pass

    out: dict = {"id": ident, "_v": CACHE_V}
    try:
        m = json.loads(_get(META.format(ident=ident)))
        md = m.get("metadata", {}) or {}
        files = {f.get("name"): f for f in m.get("files", [])}
        out.update(
            server=m.get("server"), dir=m.get("dir"),
            ocr=md.get("ocr"), imagecount=md.get("imagecount"),
            date=md.get("date"), year=md.get("year"), title=md.get("title"),
            creator=md.get("creator"), publisher=md.get("publisher"),
            contributor=md.get("contributor"), uploader=md.get("uploader"),
            language=md.get("language"), scandate=md.get("scandate"),
            possible_copyright_status=md.get("possible-copyright-status"),
            licenseurl=md.get("licenseurl"), rights=md.get("rights"),
            collection=md.get("collection"),
            files={n: {"size": f.get("size"), "sha1": f.get("sha1"), "mtime": f.get("mtime")}
                   for n, f in files.items()},
        )
        pn = f"{ident}{PN_SUFFIX}"
        if pn in files:
            d = json.loads(_get(f"https://{m['server']}{m['dir']}/{pn}"))
            pages = d.get("pages", [])
            filled = [p for p in pages if str(p.get("pageNumber") or "").strip()]
            out.update(
                pn_present=True, pn_vol_conf=d.get("confidence"), pn_leaves=len(pages),
                pn_filled=len(filled),
                pn_hi=sum(1 for p in filled if (p.get("confidence") or 0) >= 90),
                # ocr_value is IA's raw candidate tokens. Measured populated ONLY on
                # high-confidence runs -- 0% across 4 tier-D and 2 tier-C volumes -- so it is
                # recorded for the record and is not a fallback.
                pn_ocrvalue=sum(1 for p in pages if p.get("ocr_value")),
            )
        else:
            out.update(pn_present=False)
    except Exception as e:                              # noqa: BLE001 - recorded, not raised
        out["error"] = f"{type(e).__name__}: {e}"[:200]

    cached.write_text(json.dumps(out), encoding="utf-8")
    return out


def hocr_bytes(raw: dict) -> int:
    f = (raw.get("files") or {}).get(f"{raw['id']}_hocr.html") or {}
    try:
        return int(f.get("size") or 0)
    except (TypeError, ValueError):
        return 0


def sidecar_path(row: dict) -> Path:
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in row["id"])[:90]
    return SIDECAR / f"{row['source']}_{safe}.json"


def build_sidecar(row: dict, raw: dict | None) -> dict:
    """Merge a CSV row + IA distillate into the committed sidecar's `catalog_says` half.

    `book_says` is left untouched -- survey_frontmatter.py owns it, and re-running the census
    must never clobber evidence that cost a page read to obtain.
    """
    p = sidecar_path(row)
    doc = {}
    if p.exists():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                               # noqa: BLE001 - rebuild rather than die
            doc = {}

    doc.setdefault("source", row["source"])
    doc.setdefault("id", row["id"])
    doc.setdefault("book_says", {})
    doc.setdefault("survey_status", "pending")

    cat = {
        "csv": {k: (row.get(k) or "").strip() or None
                for k in ("publisher", "city", "borough", "year", "title", "column_count",
                          "start_page", "end_page", "key_page", "page_offset",
                          "holding_institution", "contributing_institution", "notes")},
    }
    if raw and not raw.get("error"):
        cat["ia"] = {k: raw.get(k) for k in
                     ("title", "date", "year", "publisher", "creator", "contributor",
                      "imagecount", "ocr", "scandate", "language", "collection",
                      "possible_copyright_status", "licenseurl", "rights")}
        hb = hocr_bytes(raw)
        f = (raw.get("files") or {}).get(f"{raw['id']}_hocr.html") or {}
        doc["derivatives"] = {
            "hocr_bytes": hb,
            "hocr_sha1": f.get("sha1"),
            "hocr_mtime": f.get("mtime"),
            "has_hocr": hb > 0,
            "has_pageindex": f"{raw['id']}_hocr_pageindex.json.gz" in (raw.get("files") or {}),
            "fetched": time.strftime("%Y-%m-%d"),
        }
        if raw.get("pn_present"):
            tier = pn_tier(raw.get("pn_filled") or 0, raw.get("pn_leaves") or 0,
                           raw.get("pn_vol_conf"))
            doc["page_numbers"] = {
                "present": True, "tier": tier,
                "vol_confidence": raw.get("pn_vol_conf"),
                "leaves": raw.get("pn_leaves"), "filled": raw.get("pn_filled"),
                "high_confidence": raw.get("pn_hi"), "ocr_value_leaves": raw.get("pn_ocrvalue"),
                # The join, restated in the artifact so nobody re-derives it wrong.
                "join": "hocr_leaf L == iiif canvas L == page_numbers entry leafNum L",
                "route": ("ia-page-numbers" if tier in ("A", "B") else "hocr-margin-regression"),
            }
        else:
            doc["page_numbers"] = {"present": False, "tier": "D",
                                   "route": "hocr-margin-regression"}
    elif raw and raw.get("error"):
        doc["survey_status"] = "fetch-failed"
        doc["error"] = raw["error"]

    doc["catalog_says"] = cat
    return doc


def load_rows(include_phonebooks: bool = False):
    rows = list(csv.DictReader(open(MASTER, encoding="utf-8")))
    out = []
    for r in rows:
        if not (r.get("id") or "").strip():
            continue
        if not include_phonebooks and "PHONEBOOK" in (r.get("notes") or ""):
            continue
        out.append(r)
    return out


def report(rows):
    """Tier + engine + bandwidth summary, from cache only. No network."""
    ia = [r for r in rows if r["source"] == "ia"]
    raws = []
    for r in ia:
        p = RAWCACHE / f"{r['id']}.json"
        if p.exists():
            try:
                raws.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:                           # noqa: BLE001
                pass
    ok = [x for x in raws if not x.get("error")]
    print(f"ia rows {len(ia)} | censused {len(raws)} | errors {len(raws) - len(ok)}")
    if not ok:
        return

    tiers = Counter(pn_tier(x.get("pn_filled") or 0, x.get("pn_leaves") or 0,
                            x.get("pn_vol_conf")) for x in ok)
    label = {"A": "trust directly", "B": "verify monotone", "C": "sparse/unreliable",
             "D": "empty"}
    print("\npage-number tier:")
    free = 0
    for t in "ABCD":
        print(f"  {t}  {tiers.get(t, 0):4d}  {label[t]}")
        if t in "AB":
            free += tiers.get(t, 0)
    print(f"  -> {free} free / {len(ok) - free} need the bottom-margin fallback")
    print(f"  -> {sum(x.get('pn_filled') or 0 for x in ok):,} leaves already numbered")

    print("\nocr engine:")
    for e, n in Counter(str(x.get("ocr") or "none").split(" ")[0] for x in ok).most_common():
        print(f"  {n:4d}  {e}")

    sizes = sorted((hocr_bytes(x), x["id"]) for x in ok if hocr_bytes(x))
    if sizes:
        tot = sum(s for s, _ in sizes)
        print(f"\nphase-1 hOCR sweep: {tot / 1e9:.1f} GB over {len(sizes)} volumes, "
              f"median {sizes[len(sizes) // 2][0] / 1e6:.0f} MB")
        big = [(s, i) for s, i in sizes if s > 500e6]
        if big:
            print(f"  {len(big)} volumes over 500 MB -- schedule alone:")
            for s, i in sorted(big, reverse=True):
                print(f"    {s / 1e6:7.0f} MB  {i}")
    print(f"\nimagecount across tier: "
          f"{sum(int(x.get('imagecount') or 0) for x in ok):,} "
          f"(overstates CONTENT leaves ~2x for ABBYY-8 -- blank versos)")


def _self_test():
    """Offline. Pins the tier routing, which is the only judgement call in this file."""
    assert pn_tier(1245, 1253, 96.3) == "A", "1906BPL is the reference tier-A volume"
    assert pn_tier(0, 640, 0) == "D", "zero filled is D regardless of leaf count"
    assert pn_tier(0, 0, None) == "D", "no page_numbers file at all is D"
    # The measured trap: middling confidence over almost no filled leaves is NOT trustworthy.
    assert pn_tier(11, 1346, 55) == "B", "conf alone can only reach B, never A"
    assert pn_tier(11, 1346, 10) == "C", "low conf + 0.8% filled is C"
    assert pn_tier(199, 543, 20) == "C", "37% filled, low conf -> C"
    assert pn_tier(1000, 1000, 95) == "A", "fully numbered + high conf -> A"
    # A must require BOTH terms -- this is the case that would silently promote junk.
    assert pn_tier(500, 1000, 99) == "B", "high conf but only 50% filled must not reach A"

    row = {"source": "ia", "id": "x/y", "publisher": "Trow", "city": "New York", "year": "1875"}
    assert sidecar_path(row).name == "ia_x_y.json", "sidecar filename must be path-safe"

    doc = build_sidecar({"source": "ia", "id": "zzz"}, None)
    assert doc["book_says"] == {}, "census must never write book_says"
    assert doc["catalog_says"]["csv"]["publisher"] is None, "blank CSV cells become null"
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true", help="offline; no network")
    ap.add_argument("--report", action="store_true", help="summarise from cache; no network")
    ap.add_argument("--ident", help="census a single IA identifier")
    ap.add_argument("--refresh", action="store_true", help="ignore the raw cache")
    ap.add_argument("--workers", type=int, default=6, help="concurrent IA requests (be polite)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N volumes (smoke test)")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    rows = load_rows()
    if args.ident:
        rows = [r for r in rows if r["id"] == args.ident]
        if not rows:
            ap.error(f"{args.ident} is not a non-phonebook row in master_directories.csv")
    if args.report:
        report(rows)
        return 0

    SIDECAR.mkdir(parents=True, exist_ok=True)
    ia = [r for r in rows if r["source"] == "ia"]
    other = [r for r in rows if r["source"] != "ia"]
    if args.limit:
        ia = ia[:args.limit]

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        raws = list(ex.map(lambda r: probe_ia(r["id"], args.refresh), ia))

    n_err = 0
    for row, raw in zip(ia, raws):
        doc = build_sidecar(row, raw)
        if raw.get("error"):
            n_err += 1
        elif doc.get("survey_status") == "pending":
            doc["survey_status"] = "census-done"
        sidecar_path(row).write_text(json.dumps(doc, indent=1), encoding="utf-8")

    # Phase 5 rows get a stub so the corpus is countable and the failure register is complete.
    for row in other:
        doc = build_sidecar(row, None)
        # setdefault is wrong here: build_sidecar already seeded "pending", so the phase-5 marker
        # never landed and 151 nypl rows sat in the failure register under the wrong code.
        if doc.get("survey_status") in (None, "pending"):
            doc["survey_status"] = "phase5-pending"
        sidecar_path(row).write_text(json.dumps(doc, indent=1), encoding="utf-8")

    print(f"censused {len(ia)} ia volumes in {time.time() - t0:.0f}s "
          f"({n_err} errors); wrote {len(ia) + len(other)} sidecars to {SIDECAR}",
          file=sys.stderr)
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
