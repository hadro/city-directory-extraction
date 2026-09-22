#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Phase 3: assemble the image-read packets, and record what the reader saw.

    python3 data_prep/survey_readpackets.py --next 6          # the next unread volumes
    python3 data_prep/survey_readpackets.py --fetch 6 --out DIR
    python3 data_prep/survey_readpackets.py --record FILE.json
    python3 data_prep/survey_readpackets.py --status
    python3 data_prep/survey_readpackets.py --self-test

Phase 0b marks a volume `needs-image-read` when the hOCR could not settle its bibliography, and
it has ALREADY chosen the leaves worth looking at (`structure.image_read_urls`). This script is
the plumbing either side of the eyes: it hands out packets and it writes the answers back as
cited claims, so a read is recorded the same way an hOCR match is -- leaf, canvas, IIIF image,
verbatim quote -- and can be audited the same way.

WHY THIS COULD NOT HAVE RUN BEFORE 2026-09-21. Every candidate URL was built on the
`archive.org/download/<id>/page/nNN` scheme, whose alignment with the leaf index is per-volume:
correct on 1906BPL, off by one on hearnesbrooklync1852unse. Reading 150-odd pages through those
URLs would have produced confident, well-cited, systematically wrong answers on an unknown
fraction of the corpus. The citations are IIIF now.

WHAT A READ MAY AND MAY NOT CLAIM

`method` is `agent-read`, which `merge_book()` in survey_frontmatter.py treats as un-overwritable
by a later hOCR re-read -- eyes outrank a regex. That makes a careless read expensive, so:

  * quote what is PRINTED, verbatim, including its OCR-defeating spelling. The quote is the
    evidence; a paraphrase is not auditable.
  * a publisher is who the page says PUBLISHED it, never the printer -- they differ on most of
    these title pages, and the printer goes in its own field. This is the error that mis-attributed
    a whole microfilm series to Spooner, who printed it.
  * `year_covered` is what the listings describe ("for the year ending May 1st, 1857"),
    `year_published` is the imprint or copyright date. Record both when both are printed; they
    legitimately differ, Trow volumes being published the autumn before their nominal year.
  * a legend is the abbreviations key. Record its LEAF; the printed page number is
    survey_pagenumbers.py's job and often does not exist at all, front matter being frequently
    unpaginated.
  * silence is an answer. `null` means the page does not say, and is always better than a guess --
    an advertisement's founding date has already been mistaken for a volume's year nine times.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIDECAR = HERE / "survey"
UA = {"User-Agent": "Mozilla/5.0 (research; city-directory corpus survey; +josh)"}

sys.path.insert(0, str(HERE))
from survey_frontmatter import page_image, canvas   # noqa: E402  (one definition of the URL)

FIELDS = ("year", "publisher", "title", "legend")


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return None


def queue():
    """-> [(path, doc)] volumes still needing eyes, worst-documented first.

    Ordered by how little the hOCR recovered, so the volumes where a read buys the most come
    first and a partial run is still the most valuable partial run.
    """
    out = []
    for p in sorted(SIDECAR.glob("*.json")):
        d = load(p)
        if not d or d.get("survey_status") != "needs-image-read":
            continue
        if (d.get("book_says") or {}).get("_read"):
            continue                                     # already read
        out.append((p, d))
    out.sort(key=lambda pd: sum(1 for f in FIELDS if f in (pd[1].get("book_says") or {})))
    return out


def packet(doc: dict) -> dict:
    book = doc.get("book_says") or {}
    st = doc.get("structure") or {}
    urls = list(st.get("image_read_urls") or [])
    if not urls:                                         # fall back to the classified leaves
        for leaf in (st.get("title_page_leaf"), st.get("target_card_leaf"),
                     st.get("copyright_page_leaf")):
            if leaf is not None:
                urls.append(page_image(doc["id"], int(leaf)))
    cat = (doc.get("catalog_says") or {}).get("csv") or {}
    return {
        "id": doc["id"],
        "catalog": {k: cat.get(k) for k in ("year", "publisher", "title", "city")},
        "already_known": {k: (book.get(k) or {}).get("value") for k in FIELDS if k in book},
        "missing": [f for f in FIELDS if f not in book],
        "classes": {k: v.get("class") for k, v in (st.get("classes") or {}).items()
                    if v.get("class") not in ("blank", "other")},
        "images": urls[:3],
    }


def leaf_of(url: str):
    m = re.search(r"\$(\d+)/", url or "")
    return int(m.group(1)) if m else None


def fetch(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=120) as r:
            dest.write_bytes(r.read())
        return True
    except Exception as e:                               # noqa: BLE001
        print(f"  FETCH FAILED {url}: {type(e).__name__}", file=sys.stderr)
        return False


def cite_read(ident: str, leaf: int, value, quote: str, evidence: str, extra=None) -> dict:
    c = {"value": value, "leaf": int(leaf), "canvas": canvas(ident, int(leaf)),
         "image": page_image(ident, int(leaf)), "evidence_type": evidence,
         "quote": (quote or "").strip()[:300], "method": "agent-read", "confidence": "high"}
    if extra:
        c.update(extra)
    return c


def record(payload: dict) -> int:
    """Write one batch of reads into the sidecars. Every claim needs a leaf and a quote."""
    wrote = 0
    for entry in payload.get("reads") or []:
        ident = entry["id"]
        matches = [p for p in SIDECAR.glob(f"*_{ident}.json")]
        if not matches:
            print(f"  no sidecar for {ident}", file=sys.stderr)
            continue
        p = matches[0]
        doc = load(p)
        book = doc.setdefault("book_says", {})
        for field, claim in (entry.get("claims") or {}).items():
            if claim is None or claim.get("value") in (None, ""):
                continue
            if claim.get("leaf") is None or not (claim.get("quote") or "").strip():
                print(f"  {ident}/{field}: refused -- a claim needs a leaf AND a quote",
                      file=sys.stderr)
                continue
            extra = {k: v for k, v in claim.items()
                     if k not in ("value", "leaf", "quote", "evidence_type")}
            book[field] = cite_read(ident, claim["leaf"], claim["value"], claim["quote"],
                                    claim.get("evidence_type", "title_page"), extra)
            wrote += 1
        book["_read"] = {"date": time.strftime("%Y-%m-%d"), "by": "agent-read",
                         "found": sorted(k for k in (entry.get("claims") or {})
                                         if (entry["claims"][k] or {}).get("value") not in
                                         (None, "")),
                         "note": entry.get("note", "")}
        got = [f for f in FIELDS if f in book]
        doc["survey_status"] = "frontmatter-done" if len(got) >= 2 else "needs-image-read"
        p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return wrote


def self_test():
    assert leaf_of("https://iiif.archive.org/iiif/1856BPL$9/full/1400,/0/default.jpg") == 9
    assert leaf_of("nonsense") is None
    c = cite_read("1856BPL", 9, 1856, "SMITH'S BROOKLYN DIRECTORY", "title_page")
    assert c["method"] == "agent-read" and c["leaf"] == 9
    assert c["image"] == "https://iiif.archive.org/iiif/1856BPL$9/full/1400,/0/default.jpg"
    assert c["canvas"].endswith("$9/canvas")
    # An agent-read claim must be un-overwritable by a later hOCR re-read: eyes beat a regex.
    from survey_frontmatter import merge_book
    kept = merge_book({"year": c}, {"year": {"value": 1837, "method": "hocr-text"}})
    assert kept["year"]["value"] == 1856, "a read must survive --redo"
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--next", type=int, metavar="N", help="print the next N packets as JSON")
    ap.add_argument("--fetch", type=int, metavar="N", help="download the next N packets' images")
    ap.add_argument("--out", default="/tmp/readpackets")
    ap.add_argument("--record", metavar="FILE", help="write a batch of reads back")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.record:
        n = record(json.loads(Path(args.record).read_text(encoding="utf-8")))
        print(f"wrote {n} claims")
        return 0
    if args.status:
        q = queue()
        print(f"needs-image-read, unread: {len(q)}")
        done = sum(1 for p in SIDECAR.glob("*.json")
                   if ((load(p) or {}).get("book_says") or {}).get("_read"))
        print(f"already read: {done}")
        return 0

    n = args.fetch or args.next or 5
    q = queue()[:n]
    out = []
    if args.fetch:
        d = Path(args.out)
        d.mkdir(parents=True, exist_ok=True)
        for _p, doc in q:
            pk = packet(doc)
            saved = []
            for url in pk["images"]:
                leaf = leaf_of(url)
                dest = d / f"{doc['id']}__leaf{leaf}.jpg"
                if dest.exists() or fetch(url, dest):
                    saved.append(str(dest))
            pk["files"] = saved
            out.append(pk)
    else:
        out = [packet(doc) for _p, doc in q]
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
