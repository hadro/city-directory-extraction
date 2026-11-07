#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["duckdb==2.0.0"]
# ///
"""
A local stand-in for the records release, for running the address-search Space (space/README.md)
before the release is on Hugging Face.

    uv run space/build_parquet.py            # data/browse.db -> data/space/records.parquet
    uv run space/build_parquet.py --index-only     # only the two indexes, for an existing file

Only the columns the Space reads, the eval_holdout rows dropped (they are never published), one
copy of a volume that is in browse.db twice (ROOTS_NEWEST_FIRST), in the release's planned order:
year, volume, leaf, line. Not a release: the release is built from
the record files, with its own columns and card (cards/RECORDS_CARD.md). Then the Space's two word
indexes beside it, which the Space would otherwise build at every start: the finder's
(search.write_index, records.words.parquet) and the Browse tab's (browse.write_terms,
records.terms.parquet).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb

import browse
import search

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "browse.db"
OUT = REPO / "data" / "space" / "records.parquet"
COLUMNS = ["record_id", "volume", "leaf", "year", "publisher", "city", "borough", "raw_line", "name_resolved",
           "occupation_role", "address_resolved", "home_address_resolved", "usable", "crop",
           "role", "scan", "employer", "spouse_name", "printed_page"]      # the last five: browse.py
# A volume assembled from two roots was in browse.db's records twice until PIPELINE #41, which
# moved the older copies to records_superseded ([one_copy] in browse/sources.toml, the same list
# as this one); this guard is kept for a database built before that, or without [one_copy]. Keep
# one copy, from the root earliest in this list, newest first. A
# volume under a root not listed stops the build. The release plan's rule ("One reading per
# volume in the export") is the same, except that the release ships nothing from run 1's root,
# while this stand-in keeps a volume run 1 alone has (1906BPL until D lands, and the 0030/0036
# scans outside the run set).
ROOTS_NEWEST_FIRST = ["data/volumes_books_first_clean_v2", "data/volumes_books_damaged_v6",
                      "data/volumes_reocr_v2", "data/volumes_run1"]
# The same edition under another volume id: a survey sidecar's `duplicate-of:<id>` (0030 is
# another scan of Hearne 1852, 0036 of 1857BPL). The release never ships these
# (hpc/prep_volumes.corpus_ids); this stand-in drops one once its edition is loaded under the
# other id, and keeps it until then.
SIDECARS = REPO / "data_prep" / "survey"


def copies_of_loaded(volumes: set) -> dict:
    """{volume: the id it duplicates} for the volumes whose edition is also loaded."""
    out = {}
    for v in volumes:
        p = SIDECARS / f"ia_{v}.json"
        status = str(json.loads(p.read_text(encoding="utf-8")).get("survey_status")) if p.exists() else ""
        if status.startswith("duplicate-of:") and status.split(":", 1)[1] in volumes:
            out[v] = status.split(":", 1)[1]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--index-only", action="store_true", help="write only the word index of --out")
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.index_only:
        return index(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = time.time()
    con = duckdb.connect()
    con.execute("INSTALL sqlite; LOAD sqlite")
    con.execute(f"ATTACH '{a.db}' AS b (TYPE sqlite, READ_ONLY)")
    cols = ", ".join(f"r.{c}" for c in COLUMNS)
    tmp = out.with_suffix(".parquet.tmp")
    rank = "CASE root " + " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(ROOTS_NEWEST_FIRST)) \
           + " END"
    con.execute(f"""
        CREATE TEMP TABLE twice AS SELECT volume, list(DISTINCT root) AS roots,
               arg_min(root, {rank}) AS keep_root, bool_or({rank} IS NULL) AS unknown
        FROM b.records GROUP BY volume HAVING count(DISTINCT root) > 1""")
    unknown = con.execute("SELECT volume, roots FROM twice WHERE unknown").fetchall()
    if unknown:
        raise SystemExit(f"volumes under a root not in ROOTS_NEWEST_FIRST: {unknown}")
    copies = copies_of_loaded({v for v, in con.execute("SELECT DISTINCT volume FROM b.records").fetchall()})
    drop = ", ".join(f"'{v}'" for v in copies) or "''"
    keep = f"""coalesce(r.eval_holdout, '') = '' AND r.volume NOT IN ({drop})
              AND (r.volume NOT IN (SELECT volume FROM twice)
                   OR r.root = (SELECT keep_root FROM twice t WHERE t.volume = r.volume))"""
    con.execute(f"""
        COPY (
          SELECT {cols}, CAST(split_part(r.record_id, ':', 3) AS INTEGER) AS line, v.label
          FROM b.records r LEFT JOIN b.volumes v USING (volume)
          WHERE {keep}
          ORDER BY r.year, r.volume, r.leaf, line
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 100000)""")
    tmp.replace(out)
    n, held, dup = con.execute(
        f"SELECT (SELECT count(*) FROM read_parquet('{out}')), "
        "(SELECT count(*) FROM b.records WHERE coalesce(eval_holdout, '') <> ''), "
        "(SELECT count(*) FROM b.records r JOIN twice t USING (volume) "
        "WHERE r.root <> t.keep_root AND coalesce(r.eval_holdout, '') = '')").fetchone()
    twice = [f"{v} (kept {k})" for v, k in con.execute("SELECT volume, keep_root FROM twice").fetchall()]
    print(f"{out}: {n:,} rows ({held:,} eval_holdout rows dropped; {dup:,} rows of older copies "
          f"of {', '.join(twice) or 'no volume'} dropped; editions loaded twice under two ids: "
          f"{', '.join(f'{v} (a copy of {t})' for v, t in copies.items()) or 'none'}), "
          f"{out.stat().st_size / 2**20:.0f} MB, {time.time() - t:.0f} s")
    return index(out)


def index(out: Path) -> int:
    for write in (search.write_index, browse.write_terms):
        t = time.time()
        path = write(str(out))
        print(f"{path}: {path.stat().st_size / 2**20:.0f} MB, {time.time() - t:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
