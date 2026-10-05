#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Stage whole volumes for a Torch prediction run (hpc/35_volumes.sbatch). Runs on the LAPTOP.

    python3 hpc/prep_volumes.py --ids micro_IABROOKLYN_0030,merceinscitydire00merc
    python3 hpc/prep_volumes.py --ids ... --chunk 10000 --out data/volumes
    python3 hpc/prep_volumes.py --ids ... --files data/iapanel/*.jsonl   # + eval files
    tar czf cde-volumes.tar.gz data/volumes          # ship next to the bundle
    python3 hpc/prep_volumes.py --self-test

Reads the listing-scoped lines the corpus survey writes (data/survey_ocr/<id>_listing.jsonl.gz:
residential sections only, each line tagged `context.section`) and splits each volume into plain
JSONL chunks of --chunk lines, because eval/qwen_predict.py reads plain JSONL and has no resume.
A chunk is one SLURM array task: ~25 min on an L40S at the measured 7.3 rows/s (14 min on an
H200 at 11.88; the 2.7 once assumed here was a load-dominated figure), so no chunk comes
near a wall-clock limit, and a preempted chunk is simply re-run.

The run set is hadro's (data_prep/survey_runset.json, stamped into the sidecars by
`data_prep/survey_twins.py stamp`). A volume stamped `duplicate-of:<id>` is another scan of an
edition the corpus run reads elsewhere, so staging it would count its people twice: it is
refused unless --allow-duplicates (run 2 staged two microfilm copies on purpose, to compare
them with their book scans). A volume whose `run_set` says `skip_non_entry_pages` loses the lines
on its `non_entry_pages` leaves: Ogden 1839's book scan, whose 135 blank versos the OCR read
through the paper.

Writes, under --out:
    <id>/chunk_000.jsonl ...   the lines, in volume order, unchanged
    tasks.txt                  one line per chunk: "<id> <chunk path> <n lines>" -- the array index
    manifest.json              per chunk: lines, first/last leaf, sha1; per volume: source, totals
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "data" / "survey_ocr"
SIDECARS = REPO / "data_prep" / "survey"


def run_set(ident: str):
    """(survey_status, the leaves the run set says to skip) from the volume's sidecar."""
    p = SIDECARS / f"ia_{ident}.json"
    if not p.exists():
        return None, set()
    d = json.loads(p.read_text(encoding="utf-8"))
    skip = set((d.get("non_entry_pages") or {}).get("leaves") or []) \
        if (d.get("run_set") or {}).get("skip_non_entry_pages") else set()
    return d.get("survey_status"), skip


def split(ident: str, out: Path, chunk: int, src: Path = None, skip_leaves=()) -> list:
    src = src or SRC / f"{ident}_listing.jsonl.gz"
    if not src.exists():
        raise SystemExit(f"no listing-scoped lines for {ident} at {src} -- run "
                         f"data_prep/survey_derive.py scope first")
    vdir = out / ident
    vdir.mkdir(parents=True, exist_ok=True)
    for old in vdir.glob("chunk_*.jsonl"):
        old.unlink()
    chunks, buf = [], []

    def flush():
        if not buf:
            return
        p = vdir / f"chunk_{len(chunks):03d}.jsonl"
        text = "".join(buf)
        p.write_text(text, encoding="utf-8")
        leaves = [json.loads(x)["context"]["leaf"] for x in (buf[0], buf[-1])]
        chunks.append({"path": str(p.relative_to(out)), "lines": len(buf),
                       "first_leaf": leaves[0], "last_leaf": leaves[1],
                       "sha1": hashlib.sha1(text.encode("utf-8")).hexdigest()})
        buf.clear()

    with (gzip.open(src, "rt", encoding="utf-8") if src.suffix == ".gz"
          else open(src, encoding="utf-8")) as fh:
        for line in fh:
            if line.strip():
                if skip_leaves and json.loads(line)["context"]["leaf"] in skip_leaves:
                    continue
                buf.append(line if line.endswith("\n") else line + "\n")
                if len(buf) == chunk:
                    flush()
    flush()
    return chunks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", help="comma list of IA identifiers")
    ap.add_argument("--files", nargs="*", default=[],
                    help="extra JSONL files (e.g. eval/ia_panel.py's data/iapanel/iapanel_<set>.jsonl), "
                         "each staged as its own pseudo-volume named after the file")
    ap.add_argument("--allow-duplicates", action="store_true",
                    help="stage volumes stamped duplicate-of: (a scan comparison, not the corpus)")
    ap.add_argument("--chunk", type=int, default=10000, help="lines per array task")
    ap.add_argument("--out", default=str(REPO / "data" / "volumes"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.ids and not args.files:
        ap.error("--ids or --files is required")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest, tasks = {}, []
    sources = [(i, SRC / f"{i}_listing.jsonl.gz") for i in (args.ids or "").split(",") if i]
    sources += [(Path(f).name.replace("_eval.jsonl", "").replace(".jsonl", ""), Path(f).resolve())
                for f in args.files]
    plan = {ident: run_set(ident) for ident, _src in sources}
    dups = {i: s for i, (s, _skip) in plan.items() if str(s).startswith("duplicate-of:")}
    if dups and not args.allow_duplicates:
        ap.error("another copy of these editions is in the run set (data_prep/survey_runset.json"
                 "): " + ", ".join(f"{i} is {s}" for i, s in dups.items())
                 + ". --allow-duplicates stages them anyway")
    for ident, src in sources:
        skip = plan[ident][1]
        chunks = split(ident, out, args.chunk, src, skip)
        manifest[ident] = {"source": str(src.relative_to(REPO)),
                           "lines": sum(c["lines"] for c in chunks), "chunks": chunks}
        if skip:
            manifest[ident]["skipped_leaves"] = sorted(skip)
        tasks += [f"{ident} {c['path']} {c['lines']}" for c in chunks]
        print(f"{ident}: {manifest[ident]['lines']:,} lines -> {len(chunks)} chunks",
              file=sys.stderr)
    (out / "tasks.txt").write_text("\n".join(tasks) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    total = sum(v["lines"] for v in manifest.values())
    print(f"\n{len(tasks)} array tasks, {total:,} lines: ~{total / 7.3 / 3600:.1f} L40S GPU-hours "
          f"at 7.3 rows/s, ~{total / 11.88 / 3600:.1f} H200 at 11.88 (4B, measured 2026-09-28)",
          file=sys.stderr)
    print(f"submit with: sbatch $(slurm_gpu_args) --array=0-{len(tasks) - 1} "
          f"hpc/35_volumes.sbatch", file=sys.stderr)
    return 0


def _self_test() -> int:
    import tempfile
    global SRC
    tmp = Path(tempfile.mkdtemp())
    real, SRC = SRC, tmp
    try:
        with gzip.open(tmp / "v_listing.jsonl.gz", "wt", encoding="utf-8") as fh:
            for i in range(25):
                fh.write(json.dumps({"raw_line": f"Abbott {i}", "context": {"leaf": 10 + i // 5}})
                         + "\n")
        chunks = split("v", tmp / "out", 10)
        assert [c["lines"] for c in chunks] == [10, 10, 5], chunks
        assert (chunks[0]["first_leaf"], chunks[2]["last_leaf"]) == (10, 14)
        text = "".join((tmp / "out" / c["path"]).read_text() for c in chunks)
        assert text.count("\n") == 25, "every line lands in exactly one chunk, in order"
        kept = split("v", tmp / "out", 10, skip_leaves={11, 13})
        assert [c["lines"] for c in kept] == [10, 5], "a skipped leaf's five lines are gone"
        assert (kept[0]["first_leaf"], kept[1]["last_leaf"]) == (10, 14)
    finally:
        SRC = real
    print("self-test OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
