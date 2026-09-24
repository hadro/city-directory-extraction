#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Stage whole volumes for a Torch prediction run (hpc/35_volumes.sbatch). Runs on the LAPTOP.

    python3 hpc/prep_volumes.py --ids micro_IABROOKLYN_0030,merceinscitydire00merc
    python3 hpc/prep_volumes.py --ids ... --chunk 10000 --out data/volumes
    tar czf cde-volumes.tar.gz data/volumes          # ship next to the bundle
    python3 hpc/prep_volumes.py --self-test

Reads the listing-scoped lines the corpus survey writes (data/survey_ocr/<id>_listing.jsonl.gz:
residential sections only, each line tagged `context.section`) and splits each volume into plain
JSONL chunks of --chunk lines, because eval/qwen_predict.py reads plain JSONL and has no resume.
A chunk is one SLURM array task: ~1 h on an L40S at the measured 2.7 rows/s, so no chunk comes
near a wall-clock limit, and a preempted chunk is simply re-run.

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


def split(ident: str, out: Path, chunk: int) -> list:
    src = SRC / f"{ident}_listing.jsonl.gz"
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

    with gzip.open(src, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                buf.append(line if line.endswith("\n") else line + "\n")
                if len(buf) == chunk:
                    flush()
    flush()
    return chunks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", help="comma list of IA identifiers")
    ap.add_argument("--chunk", type=int, default=10000, help="lines per array task")
    ap.add_argument("--out", default=str(REPO / "data" / "volumes"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.ids:
        ap.error("--ids is required")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest, tasks = {}, []
    for ident in args.ids.split(","):
        chunks = split(ident, out, args.chunk)
        manifest[ident] = {"source": str((SRC / f"{ident}_listing.jsonl.gz").relative_to(REPO)),
                           "lines": sum(c["lines"] for c in chunks), "chunks": chunks}
        tasks += [f"{ident} {c['path']} {c['lines']}" for c in chunks]
        print(f"{ident}: {manifest[ident]['lines']:,} lines -> {len(chunks)} chunks",
              file=sys.stderr)
    (out / "tasks.txt").write_text("\n".join(tasks) + "\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    total = sum(v["lines"] for v in manifest.values())
    print(f"\n{len(tasks)} array tasks, {total:,} lines; at the measured 2.7 rows/s (4B, L40S) "
          f"that is ~{total / 2.7 / 3600:.1f} GPU-hours", file=sys.stderr)
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
    finally:
        SRC = real
    print("self-test OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
