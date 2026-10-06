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
    python3 hpc/prep_volumes.py --corpus --plan                         # sizes only, no writes
    python3 hpc/prep_volumes.py --corpus --chunk 20000 --out data/volumes_corpus
    tar czf cde-volumes.tar.gz data/volumes          # ship next to the bundle
    python3 hpc/prep_volumes.py --self-test

`--corpus` stages the decided run set: every surveyed volume with listing-scoped lines that is
neither `not-residential` nor `duplicate-of:` (153 volumes, 2026-10-05). `--plan` sizes a staging
from the sidecars' counts (scope.kept less the flagged pages' lines) without reading or writing a
line. A job array has a size limit, so the submit commands come in batches of --max-array tasks,
each with a TASK_OFFSET that hpc/35_volumes.sbatch adds to SLURM_ARRAY_TASK_ID.

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
them with their book scans).

Flagged pages are skipped by default (2026-10-05): the lines on a volume's `non_entry_pages`
leaves (data_prep/survey_adleaves.py) never reach the model, which would make people of them.
An image check of 32 flagged run-set pages found no listing page with usable OCR among them:
17 full-page ads, 2 blank pages read through the paper (Ogden's 135 versos are this kind), and
13 listing pages whose OCR failed, mostly legible microfilm. Those 13 hold real entries, so the
skipped pages are also the re-OCR queue. --keep-non-entry stages them anyway.

Writes, under --out:
    <id>/chunk_000.jsonl ...   the lines, in volume order, unchanged
    tasks.txt                  one line per chunk: "<id> <chunk path> <n lines>" -- the array index
    manifest.json              per chunk: lines, first/last leaf, sha1; per volume: source, totals
    staging.json               what was staged, from which code, and what was skipped
"""
from __future__ import annotations

import argparse
import datetime as _dt
import gzip
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "data" / "survey_ocr"
SIDECARS = REPO / "data_prep" / "survey"


def run_set(ident: str, keep_non_entry: bool = False):
    """(survey_status, the leaves to skip) from the volume's sidecar: its flagged non-entry
    pages, unless keep_non_entry."""
    p = SIDECARS / f"ia_{ident}.json"
    if not p.exists():
        return None, set()
    d = json.loads(p.read_text(encoding="utf-8"))
    skip = set() if keep_non_entry else set((d.get("non_entry_pages") or {}).get("leaves") or [])
    return d.get("survey_status"), skip


def corpus_ids() -> list:
    """The decided run set, from the sidecars: listing-scoped lines, residential, not a copy."""
    out = []
    for p in sorted(SIDECARS.glob("ia_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        status = str(d.get("survey_status"))
        if ((d.get("scope") or {}).get("kept") and status != "not-residential"
                and not status.startswith("duplicate-of:")):
            out.append(d["id"])
    return out


def planned_lines(ident: str, keep_non_entry: bool) -> int:
    """Lines a staging would write for the volume, from its sidecar's counts alone."""
    d = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    kept = (d.get("scope") or {}).get("kept") or 0
    skipped = 0 if keep_non_entry else (d.get("non_entry_pages") or {}).get("scoped_lines") or 0
    return kept - skipped


def submit_lines(n_tasks: int, max_array: int) -> list:
    """sbatch commands covering n_tasks in batches no larger than the cluster's array limit."""
    return [f"TASK_OFFSET={o} sbatch $(slurm_gpu_args) --export=ALL,TASK_OFFSET={o} "
            f"--array=0-{min(max_array, n_tasks - o) - 1} hpc/35_volumes.sbatch"
            for o in range(0, n_tasks, max_array)]


def git_rev() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True,
                             capture_output=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, text=True,
                               capture_output=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except OSError:
        return "unknown"


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
    ap.add_argument("--keep-non-entry", action="store_true",
                    help="stage the lines on flagged non-entry pages too (skipped by default)")
    ap.add_argument("--chunk", type=int, default=10000, help="lines per array task")
    ap.add_argument("--corpus", action="store_true", help="stage the decided run set")
    ap.add_argument("--plan", action="store_true",
                    help="size the staging from sidecar counts; write nothing")
    ap.add_argument("--max-array", type=int, default=1000,
                    help="the cluster's job-array size limit: submit commands are batched by it")
    ap.add_argument("--out", default=str(REPO / "data" / "volumes"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.corpus:
        if args.ids:
            ap.error("--corpus stages the run set; drop --ids")
        args.ids = ",".join(corpus_ids())
    if not args.ids and not args.files:
        ap.error("--ids, --corpus or --files is required")
    if args.plan:
        ids = [i for i in args.ids.split(",") if i]
        lines = {i: planned_lines(i, args.keep_non_entry) for i in ids}
        total = sum(lines.values())
        for size in sorted({args.chunk, 10000, 20000}):
            n = sum(math.ceil(v / size) for v in lines.values() if v)
            print(f"chunk {size:6,d}: {n:5,d} array tasks, ~{size / 7.3 / 60:4.0f} min each on an "
                  f"L40S, ~{size / 11.88 / 60:4.0f} on an H200", file=sys.stderr)
        print(f"{len(ids)} volumes, {total:,} lines: ~{total / 7.3 / 3600:.0f} L40S GPU-hours, "
              f"~{total / 11.88 / 3600:.0f} H200 (4B, measured 2026-09-28)", file=sys.stderr)
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest, tasks = {}, []
    sources = [(i, SRC / f"{i}_listing.jsonl.gz") for i in (args.ids or "").split(",") if i]
    sources += [(Path(f).name.replace("_eval.jsonl", "").replace(".jsonl", ""), Path(f).resolve())
                for f in args.files]
    plan = {ident: run_set(ident, args.keep_non_entry) for ident, _src in sources}
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
    (out / "staging.json").write_text(json.dumps({
        "staged": _dt.date.today().isoformat(), "code_at": git_rev(), "corpus": args.corpus,
        "run_set": "data_prep/survey_runset.json" if args.corpus else None,
        "chunk": args.chunk, "volumes": len(manifest), "lines": total, "tasks": len(tasks),
        "keep_non_entry": args.keep_non_entry,
        "skipped_leaves": sum(len(v.get("skipped_leaves", [])) for v in manifest.values()),
    }, indent=1) + "\n", encoding="utf-8")
    print(f"\n{len(tasks)} array tasks, {total:,} lines: ~{total / 7.3 / 3600:.1f} L40S GPU-hours "
          f"at 7.3 rows/s, ~{total / 11.88 / 3600:.1f} H200 at 11.88 (4B, measured 2026-09-28)",
          file=sys.stderr)
    print("submit with:", *submit_lines(len(tasks), args.max_array), sep="\n  ", file=sys.stderr)
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
        assert submit_lines(2500, 1000)[-1].endswith("--array=0-499 hpc/35_volumes.sbatch")
        assert len(submit_lines(2500, 1000)) == 3 and "TASK_OFFSET=2000" in submit_lines(2500, 1000)[2]
        assert submit_lines(21, 1000) == [submit_lines(21, 1000)[0]] and "0-20" in submit_lines(21, 1000)[0]
    finally:
        SRC = real
    print("self-test OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
