#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
A delta 4B job: predict only the lines no earlier run has a prediction for. Runs on the LAPTOP.

    python3 hpc/prep_volumes.py --ids <ids> --chunk 20000 --out data/volumes_<new>   # as ever
    python3 hpc/delta_volumes.py stage --new data/volumes_<new> --old data/volumes_<old> \\
        --out data/volumes_delta_<name>
    COPYFILE_DISABLE=1 tar czf cde-volumes-delta-<name>.tar.gz \\
        -s ',^data/volumes_delta_<name>,data/volumes_delta,' data/volumes_delta_<name>
    # Torch: sbatch ... --export=ALL,VOL=$DATA/volumes_delta,... hpc/35_volumes.sbatch
    python3 hpc/delta_volumes.py merge --new data/volumes_<new> --old data/volumes_<old> \\
        --delta data/volumes_delta_<name>
    python3 postprocess/copy_guard.py --volumes data/volumes_<new> --run 4b-100k   # then assemble
    python3 hpc/delta_volumes.py --self-test

Why reuse is sound: the 4B is greedy and sees nothing but its prompt, the constant system prompt
and eval/qwen_predict.user_prompt(line) (publisher, year, raw line). A prediction made for a prompt
in an earlier staging is the model's answer for that prompt in a new one. (Batched bf16 decoding
can flip a rare token with the batch's padding; either reading is the model's answer.)

Why it pays: a re-import changes few prompts. D's re-read left 99.8% of the lines on leaves with no
re-read tile as they were (PIPELINE #27, "What a re-import would cost the 4B"), so the damaged
tier's delta is ~1% of its 4.68M lines, ~1-2 GPU-h against ~103 for a full pass.

stage   per volume of --new, indexes the predictions under each --old/<id>/ (a chunk counts only
        if its .sha1 matches and its records align 1:1 with its lines, the checks
        postprocess/assemble_records.load_run makes), and writes the prompts none of them has,
        once each, as chunks of --chunk lines under --out/delta/, with tasks.txt, manifest.json
        and staging.json in prep_volumes.py's format: hpc/35_volumes.sbatch runs them unchanged
        with VOL pointed at the unpacked directory, beside any other job's data/volumes.
merge   writes chunk_NNN.preds_<run>.txt and its .sha1 beside every chunk of --new, each record
        copied verbatim from --old or --delta, and refuses if any line has neither. The files are
        what the cluster would have written, so copy_guard and assemble_records run on --new as on
        any staging.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
from qwen_predict import user_prompt  # noqa: E402  the model's input, less the system prompt

BLANK = re.compile(r"\n\s*\n")          # evaluate.load_pred's record separator
DELTA = "delta"                         # the delta staging's one pseudo-volume


def chunk_lines(path: Path):
    raw = path.read_bytes()
    return raw, [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()]


def records(pred: Path) -> list:
    """A prediction file's records as written, split as evaluate.load_pred splits them."""
    return [b for b in BLANK.split(pred.read_text(encoding="utf-8")) if b.strip()]


def index(vdirs, run: str):
    """({prompt: [record, ...]}, [unusable chunks]) over the predictions in these volume
    directories, each prompt's records in the order its lines come. Two copies of one prompt can
    decode differently in different batches (8 of 20,000 records in 1876BPL's first chunk: a
    repeated ad line's "50 Cts. Per Lb." kept or lost its period), so merge gives the k-th copy
    the k-th record, and a volume that did not change merges byte-identical."""
    idx, unusable = {}, []
    for vdir in vdirs:
        for c in sorted(Path(vdir).glob("chunk_*.jsonl")):
            p = c.with_name(f"{c.stem}.preds_{run}.txt")
            if not p.exists():
                continue
            raw, lines = chunk_lines(c)
            sha = p.with_name(p.name + ".sha1")
            recs = records(p)
            if ((sha.exists() and sha.read_text().strip() != hashlib.sha1(raw).hexdigest())
                    or len(recs) != len(lines)):
                unusable.append(str(c))
                continue
            for ex, rec in zip(lines, recs):
                idx.setdefault(user_prompt(ex), []).append(rec)
    return idx, unusable


def volumes(staging: Path) -> list:
    """The staging's volume ids, in its manifest's order."""
    return list(json.loads((staging / "manifest.json").read_text(encoding="utf-8")))


def git_rev() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True,
                             capture_output=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, text=True,
                               capture_output=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except OSError:
        return "unknown"


def stage(new: Path, olds: list, out: Path, run: str, chunk: int) -> dict:
    if (out / "tasks.txt").exists():
        raise SystemExit(f"{out} is already staged: a delta goes in a NEW directory")
    todo, seen, lines_new, reused, unusable = [], set(), 0, 0, []
    for ident in volumes(new):
        idx, bad = index([o / ident for o in olds], run)
        unusable += bad
        for c in sorted((new / ident).glob("chunk_*.jsonl")):
            for ex in chunk_lines(c)[1]:
                lines_new += 1
                key = user_prompt(ex)
                reused += key in idx
                if key not in idx and key not in seen:
                    seen.add(key)
                    todo.append(json.dumps(ex, ensure_ascii=False) + "\n")
    vdir = out / DELTA
    vdir.mkdir(parents=True)
    chunks = []
    for i in range(0, len(todo), chunk):
        text = "".join(todo[i:i + chunk])
        p = vdir / f"chunk_{len(chunks):03d}.jsonl"
        p.write_text(text, encoding="utf-8")
        chunks.append({"path": str(p.relative_to(out)), "lines": len(todo[i:i + chunk]),
                       "sha1": hashlib.sha1(text.encode("utf-8")).hexdigest()})
    (out / "tasks.txt").write_text("".join(f"{DELTA} {c['path']} {c['lines']}\n" for c in chunks),
                                   encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(
        {DELTA: {"source": str(new), "lines": len(todo), "chunks": chunks}}, indent=1),
        encoding="utf-8")
    summary = {"staged": _dt.date.today().isoformat(), "code_at": git_rev(), "delta_of": str(new),
               "old": [str(o) for o in olds], "run": run, "chunk": chunk, "volumes": 1,
               "lines": len(todo), "tasks": len(chunks), "new_lines": lines_new,
               "reused": reused, "unusable_old_chunks": unusable}
    (out / "staging.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def merge(new: Path, olds: list, delta: Path, run: str, overwrite: bool = False) -> dict:
    didx, bad = index([delta / DELTA], run)
    if bad:
        raise SystemExit(f"delta predictions do not match their chunks: {bad[:3]}")
    plan, missing, counts = [], 0, {"from_old": 0, "from_delta": 0}
    for ident in volumes(new):
        idx, _bad = index([o / ident for o in olds], run)
        nth = collections.Counter()
        for c in sorted((new / ident).glob("chunk_*.jsonl")):
            p = c.with_name(f"{c.stem}.preds_{run}.txt")
            if p.exists() and not overwrite:
                raise SystemExit(f"{p} exists: merge writes a fresh staging's predictions "
                                 f"(--overwrite to replace)")
            raw, lines = chunk_lines(c)
            recs = []
            for ex in lines:
                key = user_prompt(ex)
                old, k = idx.get(key), nth[key]
                nth[key] += 1
                if old:
                    rec = old[k] if k < len(old) else old[0]
                    counts["from_old"] += 1
                else:
                    rec = (didx.get(key) or [None])[0]
                    counts["from_delta"] += rec is not None
                recs.append(rec)
            missing += recs.count(None)
            plan.append((c, p, raw, recs))
    if missing:
        raise SystemExit(f"{missing:,} lines have no prediction in --old or --delta: "
                         f"is the delta's run back and unpacked, and staged from this --new?")
    for c, p, raw, recs in plan:            # nothing is written unless every line resolved
        p.write_text("".join(r + "\n\n" for r in recs), encoding="utf-8")
        p.with_name(p.name + ".sha1").write_text(hashlib.sha1(raw).hexdigest() + "\n",
                                                 encoding="utf-8")
    return dict(counts, chunks=len(plan))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["stage", "merge"])
    ap.add_argument("--new", help="the new full staging (hpc/prep_volumes.py --out)")
    ap.add_argument("--old", nargs="+", default=[],
                    help="earlier stagings whose predictions are reused")
    ap.add_argument("--out", help="stage: the delta staging to write (a new directory)")
    ap.add_argument("--delta", help="merge: the delta staging, its predictions unpacked beside it")
    ap.add_argument("--run", default="4b-100k")
    ap.add_argument("--chunk", type=int, default=20000, help="stage: lines per array task")
    ap.add_argument("--overwrite", action="store_true",
                    help="merge: replace prediction files already in --new")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.cmd or not args.new or not args.old:
        ap.error("stage or merge, with --new and --old")
    new, olds = Path(args.new), [Path(o) for o in args.old]
    if args.cmd == "stage":
        if not args.out:
            ap.error("stage needs --out")
        s = stage(new, olds, Path(args.out), args.run, args.chunk)
        print(f"{s['new_lines']:,} lines in {new}: {s['reused']:,} reuse a prediction, "
              f"{s['lines']:,} prompts to predict in {s['tasks']} tasks "
              f"(~{s['lines'] / 12.6 / 3600:.1f} GPU-h at 12.6 rows/s)", file=sys.stderr)
        if s["unusable_old_chunks"]:
            print(f"  {len(s['unusable_old_chunks'])} old chunks unusable (stale sha1 or "
                  f"misaligned): their lines are in the delta", file=sys.stderr)
        if s["tasks"]:
            print(f"submit with: sbatch $(slurm_gpu_args) --export=ALL,VOL=$DATA/volumes_delta,"
                  f"TASK_OFFSET=0 --array=0-{s['tasks'] - 1} hpc/35_volumes.sbatch", file=sys.stderr)
        else:
            print("nothing to predict: merge now, with this empty staging as --delta", file=sys.stderr)
    else:
        if not args.delta:
            ap.error("merge needs --delta")
        m = merge(new, olds, Path(args.delta), args.run, args.overwrite)
        print(f"{m['chunks']} chunks: {m['from_old']:,} records reused, {m['from_delta']:,} from "
              f"the delta", file=sys.stderr)
    return 0


def _self_test() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp())

    def line(text, leaf=1):
        return {"raw_line": text, "context": {"publisher": "trow", "directory_year": "1915",
                                              "ia_id": "v", "leaf": leaf}}

    def staging(d, chunks):
        (d / "v").mkdir(parents=True)
        man = []
        for i, ls in enumerate(chunks):
            p = d / "v" / f"chunk_{i:03d}.jsonl"
            p.write_text("".join(json.dumps(x) + "\n" for x in ls), encoding="utf-8")
            man.append({"path": f"v/{p.name}", "lines": len(ls)})
        (d / "manifest.json").write_text(json.dumps({"v": {"chunks": man}}), encoding="utf-8")

    def predict(c, run="4b-100k", sha=True):
        raw, ls = chunk_lines(c)
        p = c.with_name(f"{c.stem}.preds_{run}.txt")
        p.write_text("".join(f"name: {x['raw_line'].split()[0]}\naddress: '{x['raw_line']}'\n\n"
                             for x in ls), encoding="utf-8")
        if sha:
            p.with_name(p.name + ".sha1").write_text(hashlib.sha1(raw).hexdigest() + "\n")
        return p

    old, new = tmp / "old", tmp / "new"
    staging(old, [[line("Abel John, clk"), line("Abbot Mary, wid")], [line("Acker Hy, tailor", 2)]])
    for c in sorted((old / "v").glob("chunk_*.jsonl")):
        predict(c)
    # the re-import: one line respelled, one gone, one added twice, the rest as they were
    staging(new, [[line("Abel John, clk"), line("Abbott Mary, wid"), line("Ace Jas, carman"),
                   line("Ace Jas, carman")], [line("Acker Hy, tailor", 2)]])
    s = stage(new, [old], tmp / "delta", "4b-100k", chunk=1)
    assert (s["new_lines"], s["reused"], s["lines"], s["tasks"]) == (5, 2, 2, 2), s
    assert (tmp / "delta" / "tasks.txt").read_text().splitlines() == [
        "delta delta/chunk_000.jsonl 1", "delta delta/chunk_001.jsonl 1"]
    try:
        stage(new, [old], tmp / "delta", "4b-100k", chunk=1)
        raise AssertionError("a second stage into the same directory must refuse")
    except SystemExit:
        pass
    try:
        merge(new, [old], tmp / "delta", "4b-100k")
        raise AssertionError("merge must refuse before the delta's predictions are back")
    except SystemExit:
        pass
    assert not list(new.glob("v/*.preds_*")), "a refused merge writes nothing"
    for c in sorted((tmp / "delta" / "delta").glob("chunk_*.jsonl")):
        predict(c)
    m = merge(new, [old], tmp / "delta", "4b-100k")
    assert (m["from_old"], m["from_delta"], m["chunks"]) == (2, 3, 2), m
    got = records(new / "v" / "chunk_000.preds_4b-100k.txt")
    assert got[0] == records(old / "v" / "chunk_000.preds_4b-100k.txt")[0], "reused verbatim"
    assert got[1].endswith("'Abbott Mary, wid'") and got[2] == got[3], got
    assert (new / "v" / "chunk_001.preds_4b-100k.txt").read_bytes() == \
        (old / "v" / "chunk_001.preds_4b-100k.txt").read_bytes(), "an unchanged chunk is byte-identical"
    raw = (new / "v" / "chunk_000.jsonl").read_bytes()
    assert (new / "v" / "chunk_000.preds_4b-100k.txt.sha1").read_text().strip() == \
        hashlib.sha1(raw).hexdigest(), "the sha1 is the new chunk's, as the cluster writes it"
    # a stale old prediction (made from another staging of its chunk) is never reused
    (old / "v" / "chunk_001.preds_4b-100k.txt.sha1").write_text("0" * 40 + "\n")
    s2 = stage(new, [old], tmp / "delta2", "4b-100k", chunk=10)
    assert s2["lines"] == 3 and len(s2["unusable_old_chunks"]) == 1, s2
    # two copies of one prompt decoded differently: the k-th copy keeps the k-th record
    old3, new3 = tmp / "old3", tmp / "new3"
    for d in (old3, new3):
        staging(d, [[line("Ad 50 Cts. Per Lb."), line("Abel John, clk"), line("Ad 50 Cts. Per Lb.")]])
    p3 = predict(old3 / "v" / "chunk_000.jsonl")
    p3.write_text("address: '50 Cts. Per Lb.'\n\nname: Abel\n\naddress: '50 Cts. Per Lb'\n\n",
                  encoding="utf-8")
    (tmp / "delta3" / DELTA).mkdir(parents=True)
    merge(new3, [old3], tmp / "delta3", "4b-100k")
    assert (new3 / "v" / "chunk_000.preds_4b-100k.txt").read_bytes() == p3.read_bytes()
    # the model's input is publisher + year + raw line: the same words in another year are new
    assert user_prompt(line("Abel John, clk")) != user_prompt(
        {"raw_line": "Abel John, clk", "context": {"publisher": "trow", "directory_year": "1917"}})
    print("self-test OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
