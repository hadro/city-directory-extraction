#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "churro-ocr[hf]>=0.3.0",
#   "torch",
#   "torchvision",
#   "accelerate",
# ]
# ///
"""
Run Churro-3B over a list of column crops on one GPU, saving each answer's raw XML. Runs on
Torch, one SLURM array task per shard (hpc/38_churro.sbatch); data_prep/reocr_columns.py stages
the shards and reads the answers back.

    uv run hpc/churro_columns.py <shard list> --device cuda [--max-tokens 8192] [--max-time 600]

Written for this repo after historical-ocr-eval's engines/run_churro.py (same churro-ocr calls,
same explicit device_map and dtype), which cannot be cloned onto Torch (no remote) and which
flattens Churro's XML into text. This keeps only the raw answer, `<crop>_churro-3b.raw.txt`
beside each crop, because the page's `<Metadata>` and `<Header>` are not lines of the listing
(reocr_bench.body_lines reads the `<Body>`). Resumable: a crop with its .raw.txt is skipped.

A VLM can loop until its token limit, and churro-ocr's is 25,000. The limits here are
generation's own (max_new_tokens, max_time), not an alarm: churro-ocr generates in a worker
thread, so a SIGALRM lands in asyncio, which swallows it, and the thread runs on (an 832 s crop
under a 600 s alarm, M2, 2026-10-06). The longest whole-page answer on the bench was 15,160
characters, ~5k tokens; a column is half that. A cut-off answer keeps its finished lines
(body_lines) and is marked "complete": false in the meta.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SLUG = "churro-3b"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shard", help="text file: one crop image path per line")
    ap.add_argument("--model", default="stanford-oval/churro-3B")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--max-time", type=float, default=600.0, help="seconds of generation per crop")
    a = ap.parse_args()
    crops = [Path(p) for p in Path(a.shard).read_text().split() if p.strip()]
    todo = [c for c in crops if not c.with_name(f"{c.stem}_{SLUG}.raw.txt").exists()]
    print(f"{len(crops)} crops, {len(todo)} to do", flush=True)
    if not todo:
        return 0
    import torch
    from churro_ocr.ocr import OCRClient
    from churro_ocr.providers import HuggingFaceOptions, OCRBackendSpec, build_ocr_backend
    print(f"torch {torch.__version__} cuda={torch.cuda.is_available()}", flush=True)
    client = OCRClient(build_ocr_backend(OCRBackendSpec(
        provider="hf", model=a.model,
        options=HuggingFaceOptions(
            model_kwargs={"device_map": a.device, "dtype": "auto"},
            generation_kwargs={"max_new_tokens": a.max_tokens, "max_time": a.max_time}))))
    done = failed = cut = 0
    t_all = time.time()
    for i, crop in enumerate(todo, 1):
        t0 = time.time()
        try:
            page = client.ocr_image(image_path=str(crop))
        except Exception as exc:                             # noqa: BLE001 - logged, run goes on
            print(f"[{i}/{len(todo)}] FAILED {crop.name}: {exc}", file=sys.stderr, flush=True)
            failed += 1
            continue
        raw = page.text or ""
        if not raw.strip():
            print(f"[{i}/{len(todo)}] EMPTY {crop.name}", file=sys.stderr, flush=True)
            failed += 1
            continue
        complete = "</HistoricalDocument>" in raw
        cut += not complete
        crop.with_name(f"{crop.stem}_{SLUG}.raw.txt").write_text(raw, encoding="utf-8")
        crop.with_name(f"{crop.stem}_{SLUG}.meta.json").write_text(json.dumps(
            {"model": a.model, "seconds": round(time.time() - t0, 1), "raw_chars": len(raw),
             "complete": complete, "max_tokens": a.max_tokens, "max_time": a.max_time}),
            encoding="utf-8")
        done += 1
        print(f"[{i}/{len(todo)}] {crop.name} {len(raw)} chars in {time.time() - t0:.0f}s"
              f"{'' if complete else ' CUT OFF'}", flush=True)
    print(f"done {done} ({cut} cut off), failed {failed}, {time.time() - t_all:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
