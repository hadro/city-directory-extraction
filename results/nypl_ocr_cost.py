#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What would it cost to OCR the unique NYPL volumes on Hugging Face Jobs? About $135-155.

    python3 results/nypl_ocr_cost.py                    # -> results/nypl_ocr_cost.json

Run 2026-10-27. The volumes are the 111 fetchable NYPL city directories that
`results/nypl_ia_overlap.py` found with no counterpart in the IA run set (a 112th has no NYPL id).
Pages come from `data_prep/nypl_canvas_index.json.gz` (`data_prep/nypl_manifests.py`): 122,916
canvases, median 770 a volume, from 159 to 3,884.

    one L40S at $1.80/h (HF Jobs, per minute while Starting/Running), LightOn at 0.53 s a tile

    scope                      tiles    L40S-h    cost    range (0.40-0.71 s a tile)
    listing pages only (est.) 507,524      75     $134     $102-180
    every page                584,748      86     $155     $117-208

Plan on $150-200 and budget $250: the job also fetches page images from NYPL, and a loop reruns.
OCR every page. It is $20 more, and the NYPL volumes have no listing bounds to scope by.

HOW THE NUMBERS ARE MADE
  tiles     the project's LightOn tiles are half a column, so a page is 2 x the catalog's
            `column_count` tiles (the book-scan canary: 2,304 pages -> 8,908 tiles at columns
            2, 2, 1, 3). Every one of the 111 volumes has a column count.
  seconds   0.53 s a tile: the vLLM canary on NYU's L40S (PIPELINE #27, job 20525205: 8,908 tiles,
            engine load 77-82 s, 1876BPL 0.40 to Doggett 0.71). NOT measured on HF.
  listing   no NYPL volume has bounds. The share of a volume's leaves that the survey scoped as
            listing is taken from the IA run-set volumes of the same family: early (Longworth,
            Mercein, Duncan) 0.82, Doggett and Rode 0.84, Trow/Wilson 0.85, Trow general 0.91.
            The post-1915 Polk volumes have no IA analogue and borrow Trow general's 0.91.
  rates     from https://huggingface.co/docs/hub/jobs-pricing, read 2026-10-27 (`HF_RATES`).

WHERE IT GOES. Tiles by family: Trow and Trow/Wilson 1852-1899 54% (43 volumes, ~$72), Polk
1915-34 31% (9 volumes, ~$41) from 15% of the pages because they print 4-6 columns, early 8%,
Trow 1900-14 6%, Doggett 2.5%.

OTHER HARDWARE. L40S is the baseline because it is the card the 0.53 s was measured on. An A100
($2.50) would have to read tiles 1.4x faster to break even, an H200 ($5.00) 2.8x, an RTX PRO 6000
($2.75) 1.5x. NYU saw an H200 no faster than an L40S on the 4B without the fast kernels, and
nobody has timed LightOn on either. An L4 ($0.80) is probably slower per dollar, because decoding
is bound by memory bandwidth (reasoning, not a measurement).

THE FOLLOW-ON IS BIGGER. The 4B over the OCR's lines is about 14.2M lines at 141 lines a Polk or
Trow general listing leaf, 151 Doggett, 159 Trow/Wilson, 48 early (kept lines per listing leaf,
IA run set medians), which is as many lines as the whole IA run set. At 12.6 rows/s that is ~313
L40S-hours, ~$563. 14.2M is low for Polk: 4-6 columns hold more lines a page than Trow's three.

NOT COUNTED, and not known
  - Tile cutting. IA tiles find their gutters from IA's word positions; NYPL has no OCR, so a
    gutter finder (or fixed column splits from the catalog) has to be written. Development, not GPU.
  - Image quality. Canvases declare 2560 x 2560. A 5-6 column Polk page cut from that may be too
    coarse for small type; the master's pixels (`info.json`) and a look at tiles come first.
  - HF Jobs limits: the default timeout is 30 minutes, so every job needs a longer `--timeout`;
    a positive credit balance is required (PRO's monthly credits count toward it).
  - Whether NYPL throttles a few hundred thousand image requests from one job.
  - A pilot: one volume is about $1-2 and replaces the 0.53 s with a measured HF rate.
"""
import argparse
import csv
import gzip
import json
import statistics
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "data_prep" / "master_directories.csv"
TIERS = REPO / "data_prep" / "run_tiers.json"
SIDECARS = REPO / "data_prep" / "survey"
INDEX = REPO / "data_prep" / "nypl_canvas_index.json.gz"
OVERLAP = REPO / "results" / "nypl_ia_overlap.json"

HF_SOURCE = "https://huggingface.co/docs/hub/jobs-pricing"
HF_READ = "2026-10-27"
HF_RATES = {                     # $ per hour
    "l4": 0.80, "l40s": 1.80, "a10g-large": 1.50, "a100-large": 2.50,
    "h200": 5.00, "rtx-pro-6000": 2.75, "cpu-upgrade": 0.03,
}
BASELINE = "l40s"
TILE_SEC = {"low": 0.40, "mid": 0.53, "high": 0.71}      # PIPELINE #27 canary, per task
TILES_PER_COLUMN = 2                                       # half tiles
ENGINE_START_SEC = 80                                      # vLLM load a task, PIPELINE #27
TILES_PER_JOB = 10_000
ROWS_PER_SEC_4B = 12.6                                     # PIPELINE, venv-kernels batch 64


def ia_family(ident, publisher):
    if publisher.startswith(("Longworth", "Mercein")) or ident.startswith("newyorkdirectory"):
        return "early"
    if publisher.startswith("Doggett") or publisher == "Rode":
        return "Doggett"
    if ident.startswith(("trowsnewyorkcity", "bub_gb")):
        return "TrowWilson"
    if ident.startswith("trowsgenerald"):
        return "TrowGeneral"
    return None


def nypl_family(publisher, year):
    y = int(year[:4])
    if y < 1850 and not publisher.startswith("Doggett"):
        return "early"
    if publisher.startswith(("Doggett", "Groot")):
        return "Doggett"
    if publisher.startswith("Trow/Wilson") or (publisher == "Trow" and y < 1882):
        return "TrowWilson"
    if publisher == "Trow":
        return "TrowGeneral" if y >= 1900 else "TrowWilson"
    return "Polk"


def ia_family_params(catalog):
    """Median listing share of a volume's leaves, and kept lines a listing leaf, per family."""
    run_set = json.load(open(TIERS, encoding="utf-8"))["volumes"]
    share, per_leaf = defaultdict(list), defaultdict(list)
    for ident in run_set:
        row = catalog.get(ident)
        fam = ia_family(ident, row["publisher"]) if row else None
        sidecar = SIDECARS / f"ia_{ident}.json"
        if not fam or not sidecar.exists():
            continue
        d = json.load(open(sidecar, encoding="utf-8"))
        leaves = int(((d.get("catalog_says") or {}).get("ia") or {}).get("imagecount") or 0)
        scope = d.get("scope") or {}
        listing = sum(s["end_leaf"] - s["start_leaf"] + 1 for s in scope.get("sections", [])
                      if s["kind"] in ("listing", "late_names"))
        if leaves and listing:
            share[fam].append(listing / leaves)
        if listing and scope.get("kept"):
            per_leaf[fam].append(scope["kept"] / listing)
    params = {f: {"listing_share": statistics.median(share[f]),
                  "lines_per_listing_leaf": statistics.median(per_leaf[f]),
                  "ia_volumes": len(share[f]), "borrowed_from": None} for f in share}
    params["Polk"] = dict(params["TrowGeneral"], borrowed_from="TrowGeneral")
    return params


def git_rev():
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "data_prep", "results"],
                               cwd=REPO, capture_output=True, text=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "results" / "nypl_ocr_cost.json"))
    args = ap.parse_args()

    catalog = {r["id"]: r for r in csv.DictReader(open(CATALOG, encoding="utf-8")) if r["id"]}
    index = json.load(gzip.open(INDEX, "rt", encoding="utf-8"))["volumes"]
    overlap = json.load(open(OVERLAP, encoding="utf-8"))["rows"]
    params = ia_family_params(catalog)

    rows = []
    for r in overlap:
        if r["verdict"] not in ("unique", "tested-different") or not r["id"]:
            continue
        pages = len(index[r["id"]]["canvases"])
        cols = int(catalog[r["id"]]["column_count"])
        fam = nypl_family(r["publisher"], r["year"])
        p = params[fam]
        listing_pages = pages * p["listing_share"]
        rows.append({
            "id": r["id"], "year": r["year"], "publisher": r["publisher"], "family": fam,
            "canvases": pages, "columns": cols,
            "tiles_all": pages * TILES_PER_COLUMN * cols,
            "listing_pages_est": round(listing_pages),
            "tiles_listing_est": round(listing_pages * TILES_PER_COLUMN * cols),
            "lines_est": round(listing_pages * p["lines_per_listing_leaf"]),
        })

    by_family = defaultdict(lambda: {"volumes": 0, "canvases": 0, "tiles_listing_est": 0, "lines_est": 0})
    for x in rows:
        b = by_family[x["family"]]
        b["volumes"] += 1
        b["canvases"] += x["canvases"]
        b["tiles_listing_est"] += x["tiles_listing_est"]
        b["lines_est"] += x["lines_est"]
    total_tiles = sum(b["tiles_listing_est"] for b in by_family.values())
    for b in by_family.values():
        b["share_of_tiles"] = round(b["tiles_listing_est"] / total_tiles, 3)
        b["cost_usd_mid"] = round(b["tiles_listing_est"] * TILE_SEC["mid"] / 3600 * HF_RATES[BASELINE])

    scenarios = []
    for scope, key in (("listing pages only (est.)", "tiles_listing_est"), ("every page", "tiles_all")):
        tiles = sum(x[key] for x in rows)
        for speed, sec in TILE_SEC.items():
            hours = tiles * sec / 3600
            scenarios.append({"scope": scope, "tile_seconds": speed, "tiles": tiles,
                              "gpu_hours": round(hours, 1),
                              "cost_usd": round(hours * HF_RATES[BASELINE]),
                              "jobs_of_10k_tiles": round(tiles / TILES_PER_JOB),
                              "engine_start_usd": round(tiles / TILES_PER_JOB * ENGINE_START_SEC / 3600
                                                        * HF_RATES[BASELINE], 1)})

    lines = sum(x["lines_est"] for x in rows)
    hours_4b = lines / ROWS_PER_SEC_4B / 3600
    out = {
        "derived": date.today().isoformat(), "code_at": git_rev(),
        "method": "tiles = canvases x 2 x column_count; seconds a tile from the NYU L40S canary; "
                  "NOT measured on HF Jobs",
        "hf_jobs": {"source": HF_SOURCE, "read": HF_READ, "baseline": BASELINE,
                    "usd_per_hour": HF_RATES,
                    "break_even_speedup_vs_baseline": {k: round(v / HF_RATES[BASELINE], 2)
                                                       for k, v in HF_RATES.items() if k != BASELINE}},
        "assumptions": {"tile_seconds": TILE_SEC, "tiles_per_column": TILES_PER_COLUMN,
                        "engine_start_seconds": ENGINE_START_SEC, "tiles_per_job": TILES_PER_JOB,
                        "rows_per_second_4b": ROWS_PER_SEC_4B, "family_params": params},
        "volumes": len(rows), "canvases": sum(x["canvases"] for x in rows),
        "scenarios": scenarios,
        "by_family": dict(by_family),
        "follow_on_4b": {"lines_est": lines, "l40s_hours": round(hours_4b),
                         "cost_usd": round(hours_4b * HF_RATES[BASELINE]),
                         "note": "low for Polk: 4-6 columns hold more lines a page than Trow general"},
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"{len(rows)} volumes, {out['canvases']:,} canvases")
    for s in scenarios:
        print(f"  {s['scope']:26} {s['tile_seconds']:>4}: {s['tiles']:9,} tiles {s['gpu_hours']:6.1f} h  ${s['cost_usd']}")
    print(f"  4B follow-on: {lines:,} lines, {hours_4b:.0f} h, ${out['follow_on_4b']['cost_usd']}")
    print("->", args.out)


if __name__ == "__main__":
    main()
