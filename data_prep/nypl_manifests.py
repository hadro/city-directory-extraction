#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
NYPL IIIF manifests: a local cache, and a compact index of their canvases.

    python3 data_prep/nypl_manifests.py fetch            # the 111 volumes with no IA counterpart
    python3 data_prep/nypl_manifests.py fetch --all      # every NYPL city directory in the catalog
    python3 data_prep/nypl_manifests.py index            # cache -> data_prep/nypl_canvas_index.json.gz
    python3 data_prep/nypl_manifests.py --self-test

WHY (2026-10-27). Costing an OCR of the NYPL volumes IA does not hold (results/nypl_ocr_cost.py)
needed each volume's page count, and the catalog has none. The manifest at
`https://api-collections.nypl.org/manifests/<uuid>` lists one canvas per scanned page, public and
without a key, so `fetch` pulled the 111 volumes that `results/nypl_ia_overlap.py` found unique
(122,916 canvases). NYPL's API was announced to deprecate on 2026-08-01 (README) and the manifest
endpoint still answered on 2026-10-27; `nypl_api_archive/` exists for the same reason.

THE CACHE, `data/nypl_manifests/<uuid>.json` (gitignored, 197 MB for the 111). Each manifest is
~3 MB because every canvas repeats a block of `rendering` links, so `index` keeps what an OCR job
needs and drops the rest:

    data_prep/nypl_canvas_index.json.gz   (committed)
      {"<uuid>": {"label": "<manifest label>", "canvases": [[printed label, IIIF image id, w, h], ...]}}

A page image is `https://iiif.nypl.org/iiif/3/<image id>/full/<size>/0/default.jpg`. `w` and `h`
are the canvas size the manifest declares (2560 x 2560 on every volume looked at), not necessarily
the master's pixels; ask the image service's `info.json` for those.

`inspect_frontmatter.py` keeps its own manifests under the sibling pipeline's
`output/_frontmatter/nypl_<uuid>/manifest.json`; this cache is separate on purpose, since that
directory holds 1 of these 111.

`fetch` is polite (4 connections, a User-Agent, 3 tries), skips a manifest already cached, and
writes through a temp file so an interrupted run leaves no half manifest.
"""
import argparse
import concurrent.futures as cf
import csv
import gzip
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CATALOG = HERE / "master_directories.csv"
OVERLAP = REPO / "results" / "nypl_ia_overlap.json"
CACHE = REPO / "data" / "nypl_manifests"
INDEX = HERE / "nypl_canvas_index.json.gz"
UA = {"User-Agent": "Mozilla/5.0 (research; city-directory metadata)"}
URL = "https://api-collections.nypl.org/manifests/{}"
WORKERS = 4
IMAGE_ID = re.compile(r"/iiif/\d+/([^/]+)/")


def nypl_ids(everything: bool):
    """The uuids to fetch: the unique volumes from the overlap pass, or every non-phone-book row."""
    if everything:
        rows = csv.DictReader(open(CATALOG, encoding="utf-8"))
        return [r["id"] for r in rows
                if r["source"] == "nypl" and r["id"] and "PHONEBOOK" not in r["notes"].upper()]
    rows = json.load(open(OVERLAP, encoding="utf-8"))["rows"]
    return [r["id"] for r in rows if r["verdict"] in ("unique", "tested-different") and r["id"]]


def valid(path: Path) -> bool:
    try:
        return bool(json.load(open(path, encoding="utf-8")).get("items"))
    except (OSError, ValueError):
        return False


def get(ident: str):
    path = CACHE / f"{ident}.json"
    if path.exists() and valid(path):
        return ident, "cached", path.stat().st_size
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL.format(ident), headers=UA)
            body = urllib.request.urlopen(req, timeout=120).read()
            tmp = path.with_suffix(".part")
            tmp.write_bytes(body)
            tmp.replace(path)
            return ident, "fetched", len(body)
        except Exception as e:                                           # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    return ident, f"FAILED {str(last)[:60]}", 0


def cmd_fetch(args):
    CACHE.mkdir(parents=True, exist_ok=True)
    ids = nypl_ids(args.all)
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(get, ids))
    failed = [r for r in res if r[1].startswith("FAILED")]
    print(f"{len(res)} manifests: {sum(r[1] == 'fetched' for r in res)} fetched, "
          f"{sum(r[1] == 'cached' for r in res)} cached, {len(failed)} failed -> {CACHE}")
    for f in failed:
        print("FAILED", f[0], f[1])
    return 1 if failed else 0


def canvases(manifest: dict):
    out = []
    for c in manifest.get("items", []):
        label = ((c.get("label") or {}).get("en") or [""])[0]
        m = IMAGE_ID.search(c.get("id", ""))
        out.append([label, m.group(1) if m else None, c.get("width"), c.get("height")])
    return out


def cmd_index(args):
    index = {}
    for path in sorted(CACHE.glob("*.json")):
        m = json.load(open(path, encoding="utf-8"))
        label = ((m.get("label") or {}).get("en") or [""])[0]
        index[path.stem] = {"label": label, "canvases": canvases(m)}
    if not index:
        print(f"nothing in {CACHE}; run fetch first")
        return 1
    doc = {"derived": date.today().isoformat(), "source": URL.format("<uuid>"), "volumes": index}
    with gzip.open(INDEX, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    n = sum(len(v["canvases"]) for v in index.values())
    print(f"{len(index)} volumes, {n:,} canvases -> {INDEX} ({INDEX.stat().st_size / 1e6:.1f} MB)")
    return 0


def self_test():
    m = {"label": {"en": ["A"]}, "items": [
        {"id": "https://iiif.nypl.org/iiif/3/56813750/full/!760,760/0/default.jpg",
         "label": {"en": ["6"]}, "width": 2560, "height": 2560},
        {"id": "x", "label": {"none": ["n/a"]}, "width": 1, "height": 2}]}
    assert canvases(m) == [["6", "56813750", 2560, 2560], ["", None, 1, 2]], canvases(m)
    print("self-test ok")
    return 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--all", action="store_true", help="every NYPL city directory, not just the unique ones")
    sub.add_parser("index")
    args = ap.parse_args()
    return {"fetch": cmd_fetch, "index": cmd_index}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
