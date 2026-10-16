#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "vllm==0.30.0",
#   "pillow==12.3.0",
# ]
# ///
"""
LightOnOCR-3 over a shard of half tiles with vLLM's batched decoding: the same tiles, resize,
empty prompt, decoding, loop handling and output files as hpc/lightonocr_tiles.py, many tiles
at a time. hpc/39_lightonocr.sbatch runs it with ENGINE=vllm.

    uv run hpc/lightonocr_vllm.py <shard list> [--temperature 0] [--tag vllm]

WHY (2026-10-16, hadro). lightonocr_tiles.py reads one tile at a time through Hugging Face
generate: each new token reads the model's ~2 GB of weights from GPU memory for one sequence,
and the full Torch run (job 19954791) measured 81 tokens/s, ~400 tokens a tile, 28.9 L40S-hours
for 20,712 tiles. vLLM generates the next token for every tile in its batch in one step, so one
read of the weights serves them all; it refills a finished tile's slot at once (continuous
batching) and keeps each tile's attention cache in small pages, so many tiles fit. LightOn's
model card serves this model with vLLM (`vllm serve lightonai/LightOnOCR-3-1B
--limit-mm-per-prompt '{"image": 1}' --mm-processor-cache-gb 0 --no-enable-prefix-caching`);
the settings below are those. The gain is measured, not assumed: the first run re-reads task 0
(the bench and screen tiles, TASKS=data/reocr_halves/bench_tasks.txt) with --tag vllm, scored
beside lightonocr-3-1b-greedy-torch (reocr_pair.py bench/score) before any batch.

Same as the per-tile runner: the tile resized to the card's longest side, the image alone as the
prompt, greedy at --temperature 0, the --max-new-tokens cap, the raw answer, untable/to_lines,
.txt/.raw.txt/.meta.json beside the tile, a tile with its .txt skipped on a re-run. A tile that
hits the cap is a loop: the looped tiles are read again together on their darkest ink (the
runner's bleed retry), and one that loops again is cut back (cut_loop). Different:
  * no per-tile clock (--max-time): a batch has none, and the full run's 15-minute cap never
    fired; `seconds` in the meta is the batch's time over its tiles;
  * batched arithmetic can differ from one-at-a-time in the last digits, so greedy can flip a
    near-tie (one comma between the M2 and CUDA on the bench): hence the task-0 parity run;
  * CUDA only: the M2 keeps lightonocr_tiles.py.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lightonocr_tiles import DEFAULT_MODEL, cut_loop, darkest, default_max_side, slug_for, to_lines  # noqa: E402


def data_url(img) -> str:
    """The tile as LightOn's client sends it: a base64 PNG."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def conversation(img) -> list:
    return [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url(img)}}]}]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shard", help="text file: one tile image path per line")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--max-side", type=int, default=0, help="default: the card's target")
    ap.add_argument("--max-new-tokens", type=int, default=4096)
    ap.add_argument("--temperature", type=float, default=0.2,
                    help="0.2 with top_p 0.9 is the card's setting; 0 = greedy")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="vllm", help="slug suffix, e.g. lightonocr-3-1b-greedy-vllm")
    ap.add_argument("--max-seqs", type=int, default=128, help="tiles decoded at once (vLLM max_num_seqs)")
    ap.add_argument("--chunk", type=int, default=256,
                    help="tiles per generate call: answers are written after each, so a stopped "
                         "task resumes from the last")
    ap.add_argument("--gpu-memory", type=float, default=0.90, help="vLLM gpu_memory_utilization")
    a = ap.parse_args()

    greedy = a.temperature == 0
    decode = "greedy" if greedy else (f"s{a.seed}" if a.seed else
                                      f"t{a.temperature:g}" if a.temperature != 0.2 else "")
    slug = "-".join(x for x in (slug_for(a.model), decode, a.tag) if x)
    max_side = a.max_side or default_max_side(a.model)
    tiles = [Path(p) for p in Path(a.shard).read_text().split() if p.strip()]
    todo = [p for p in tiles if not p.with_name(f"{p.stem}_{slug}.txt").exists()]
    print(f"model {a.model} | slug {slug} | engine vllm | longest side {max_side}px | "
          f"{len(tiles)} tiles, {len(todo)} to do", flush=True)
    if not todo:
        return 0

    from PIL import Image
    import vllm
    from vllm import LLM, SamplingParams
    t0 = time.time()
    llm = LLM(model=a.model, dtype=a.dtype, seed=a.seed, max_num_seqs=a.max_seqs,
              gpu_memory_utilization=a.gpu_memory, limit_mm_per_prompt={"image": 1},
              mm_processor_cache_gb=0, enable_prefix_caching=False)
    print(f"vllm {vllm.__version__}: loaded {a.model} in {time.time() - t0:.0f}s", flush=True)
    params = SamplingParams(temperature=0.0 if greedy else a.temperature,
                            top_p=1.0 if greedy else 0.9, max_tokens=a.max_new_tokens, seed=a.seed)
    gpu = None
    try:
        import torch
        gpu = torch.cuda.get_device_name() if torch.cuda.is_available() else None
    except Exception:                                    # noqa: BLE001 - informational only
        pass

    def fit(path):
        img = Image.open(path).convert("RGB")
        scale = max_side / max(img.size)
        if scale < 1:
            img = img.resize((round(img.width * scale), round(img.height * scale)),
                             Image.Resampling.LANCZOS)
        return img

    def read(images):
        """[(text, output tokens, prompt tokens, looped)] and the call's seconds."""
        t = time.time()
        outs = llm.chat([conversation(img) for img in images], params, use_tqdm=False)
        got = []
        for o in outs:
            c = o.outputs[0]
            n_out = len(c.token_ids)
            got.append((c.text, n_out, len(o.prompt_token_ids or []),
                        c.finish_reason == "length" or n_out >= a.max_new_tokens))
        return got, time.time() - t

    ok = failed = retried = truncated = looped_n = 0
    t_all, done = time.time(), 0
    for c0 in range(0, len(todo), a.chunk):
        paths = todo[c0:c0 + a.chunk]
        images = [fit(p) for p in paths]
        first, secs = read(images)
        loops = [k for k, g in enumerate(first) if g[3]]
        retry, rsecs = (read([darkest(images[k]) for k in loops]) if loops else ([], 0.0))
        again = dict(zip(loops, retry))
        per_tile = (secs + rsecs) / max(len(paths), 1)
        for k, path in enumerate(paths):
            raw, n_out, n_in, looped = first[k]
            bleed_retry = loop_truncated = False
            loop_raw = None
            if looped:
                looped_n += 1
                raw2, n2, _n, looped2 = again[k]
                if not looped2:
                    loop_raw, raw, n_out, bleed_retry = raw, raw2, n2, True
                else:
                    raw, loop_truncated = cut_loop(raw)
            retried += bleed_retry
            truncated += loop_truncated
            lines, was_table = to_lines(raw)
            stem = f"{path.stem}_{slug}"
            path.with_name(f"{stem}.raw.txt").write_text(raw, encoding="utf-8")
            if loop_raw is not None:
                path.with_name(f"{stem}.loop.raw.txt").write_text(loop_raw, encoding="utf-8")
            path.with_name(f"{stem}.meta.json").write_text(json.dumps({
                "model": a.model, "engine": "vllm", "vllm": vllm.__version__, "device": "cuda",
                "dtype": a.dtype, "gpu": gpu, "input_size": list(images[k].size),
                "input_tokens": n_in, "output_tokens": n_out, "seconds": round(per_tile, 2),
                "batch_tiles": len(paths), "batch_seconds": round(secs + rsecs, 1),
                "lines": len(lines), "complete": not looped, "looped": looped, "timed_out": False,
                "table_mode": was_table, "bleed_retry": bleed_retry, "loop_truncated": loop_truncated,
                "sampling": {"do_sample": not greedy, **({} if greedy else {"temperature": a.temperature,
                             "top_p": 0.9}), "seed": a.seed},
                "max_new_tokens": a.max_new_tokens}, indent=1), encoding="utf-8")
            if not lines:
                print(f"EMPTY {path.name}{' (loop cut to nothing)' if loop_truncated else ''} -- raw "
                      "and meta kept, no .txt", file=sys.stderr, flush=True)
                failed += 1
                continue
            path.with_name(f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            ok += 1
        done += len(paths)
        tok = sum(g[1] for g in first) + sum(g[1] for g in retry)
        print(f"[{done}/{len(todo)}] {len(paths)} tiles in {secs + rsecs:.0f}s "
              f"({tok / max(secs + rsecs, 1e-9):.0f} tok/s, {len(loops)} looped)", flush=True)
    print(f"done {ok}, failed {failed} ({looped_n} looped), bleed retries {retried}, "
          f"loops truncated {truncated}, {time.time() - t_all:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
