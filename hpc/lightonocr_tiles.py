#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "transformers==5.19.0",
#   "torch==2.14.1",
#   "torchvision==0.29.1",
#   "accelerate==1.15.0",
#   "pillow==12.3.0",
# ]
# ///
"""
Run LightOnOCR-3 over a list of half tiles on one GPU, one SLURM array task per shard
(hpc/39_lightonocr.sbatch); data_prep/reocr_columns.py stages the tiles and data_prep/reocr_pair.py
reads the answers back.

    uv run hpc/lightonocr_tiles.py <shard list> [--temperature 0] [--tag torch]

Vendored, 2026-10-14, from historical-ocr-eval/engines/run_lightonocr.py at 5a99596 (with its
untable(), which undoes LightOn's table mode on ~6% of tiles) and markdown_to_lines
(engines/run_paddleocr_vl.py), the runner that produced the bench numbers (LightOnOCR-3-1B on half
tiles: 91.5% of gold entries exact, 100% close). Kept as they are: the loader (the 1B's checkpoint
is named for an older transformers, hence the key remap and the refusal to run on a partially
loaded model), the resize to the card's longest side, the empty prompt, the sampling, the two
cut-offs and the output contract. The library versions are the bench's. So a Torch run differs
from the bench only in device and dtype (CUDA bf16 against MPS fp32), which is why its first
task re-reads the bench tiles to be scored again. Changes: a shard list instead of a directory,
and --tag in the slug, so answers made on Torch never overwrite the bench's when unpacked.

Per tile, beside the .jpg:
    <tile>_<slug>.txt        one line per line, reading order (Markdown flattened)
    <tile>_<slug>.raw.txt    the model's raw Markdown
    <tile>_<slug>.meta.json  model, device, timing, tokens, cut-off flags, sampling
Hitting --max-new-tokens is a loop. The tile is read once more on its darkest ink only
(`darkest`, for bleed-through), kept if that does not loop ("bleed_retry": true: its digits are
less sure, so downstream should trust them less); otherwise the first answer is cut back to the
line where the repetition begins ("loop_truncated": true) and the pairing falls back to
tesseract for the rest. Hitting --max-time is the hardware's budget: raw kept, no .txt,
unscored. Resumable: a tile with its .txt is skipped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

DEFAULT_MODEL = "lightonai/LightOnOCR-3-1B"
_FENCE = re.compile(r"^\s*```")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]{4,}\|?\s*$")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def markdown_to_lines(md: str) -> list:
    """The model's Markdown as page lines in reading order: table rows split into their cells,
    heading and emphasis markers stripped, the words kept."""
    out = []
    in_fence = False
    for raw in md.splitlines():
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(raw.rstrip())
            continue
        line = _IMG.sub("", raw)
        line = _HTML_TAG.sub(" ", line)
        if _TABLE_SEP.match(line):
            continue
        if "|" in line and line.strip().startswith("|"):
            for cell in line.strip().strip("|").split("|"):
                cell = cell.strip()
                if cell:
                    out.append(cell)
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"[*_]{1,3}(.+?)[*_]{1,3}", r"\1", line)
        line = line.replace("\\", "").strip()
        if line:
            out.append(line)
    return out


_CAPTION = re.compile(r"^\s*#{1,6}\s*Table\s+[-–—]\s+")   # "### Table - Directory"
_TYPE = re.compile(r"^\s*\*?Type:\s*[\w ]+\*?\s*$")                   # "*Type: listing*"
_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_SEP = re.compile(r"^\s*\|?[\s:|]*-{3,}[\s:|-]*\|?\s*$")
# "Falconer David", "McDougal Duncan", "Fanjoy & Enoch" -- but not "N. Y. h.", "Walworth st."
_ENTRY_START = re.compile(r"^[A-Z][a-z'’]+[A-Za-z'’-]*\s+(?:&\s+)?[A-Z]")


def untable(raw: str) -> tuple[str, bool]:
    """Undo LightOn's table mode before flattening. Returns (text, was_table).

    On about 6% of directory tiles (8 of 138 on the Brooklyn bench, seed 0, and which
    tiles flips with the seed) the model opens with `<table>`, an INVENTED caption
    ("### Table - Directory", "Table - Historical Entries"), "*Type: listing*", and a
    header row ("| Name | Title | Location |"). None of that is on the page, and
    markdown_to_lines would keep it as 4-5 lines of text that read like entries downstream.

    The rows come in two forms, and the cells say which, so it is decided per tile by a
    vote over every cell after the first in its row:
      * ENTRY PACKING -- "| Fagans Julius, segars, 145½ Ewen | Falconer David, salesman,
        66 S. 5th |": consecutive entries laid across a row in reading order. Each cell
        is its own line, as markdown_to_lines already does for a page rendered as a table.
      * FIELD SPLIT -- "| Farrell Dominick, gardener | h. Walworth st. |": ONE entry cut
        into fields, so the cells are joined back. The model ate the comma at the cut;
        directory style puts one after the occupation, so ", " is restored -- unless the
        cell already ends in punctuation, or in a digit: "h. 116 | Myrtle av" is a house
        number running over to its street, not a field boundary.
    A later cell that opens like an entry ("Surname Given," / "Surname & ...") votes
    packing; one opening "h.", a street or a number votes field split. Joining packed
    entries would glue two people into one line -- 35 lines to 15 on one tile -- so the
    vote is not optional.
    """
    if "<table" not in raw and not re.search(r"^\s*\|", raw, re.M):
        return raw, False
    lines, table, rows = raw.splitlines(), False, {}
    for i, line in enumerate(lines):
        m = _ROW.match(line)
        if m and not (i + 1 < len(lines) and _SEP.match(lines[i + 1]) and "|" in lines[i + 1]):
            rows[i] = [c.strip() for c in m.group(1).split("|") if c.strip()]
    later = [c for cells in rows.values() for c in cells[1:]]
    packed = bool(later) and 2 * sum(bool(_ENTRY_START.match(c)) for c in later) >= len(later)
    out = []
    for i, line in enumerate(lines):
        if re.fullmatch(r"\s*</?table>\s*", line) or _CAPTION.match(line) or _TYPE.match(line):
            table = True
            continue
        if (_SEP.match(line) and "|" in line) or (_ROW.match(line) and i not in rows):
            table = True                                     # rule, or the header row
            continue
        if i in rows:
            table = True
            if packed:
                out.extend(rows[i])
                continue
            entry = ""
            for cell in rows[i]:
                entry = cell if not entry else entry + (
                    " " if entry[-1] in ",.;:" or entry[-1].isdigit() else ", ") + cell
            if entry:
                out.append(entry)
            continue
        out.append(line)
    return "\n".join(out), table


def to_lines(raw: str) -> tuple[list[str], bool]:
    text, was_table = untable(raw)
    return markdown_to_lines(text), was_table


def darkest(img, share: float = 0.10):
    """The tile with only ink darker than its own `share` grey percentile kept black. On
    heavy bleed-through (the reverse page's text showing through, mirrored) LightOn loops: on
    micro_IABROOKLYN_0047 leaf 90 every seed and greedy wrote one entry and then 4,000 zeros.
    Thresholded at the 10th percentile it read 15 of 15 lines with no loop; at a milder
    threshold the remaining bleed made it invent entries (historical-ocr-eval, 2026-10-14).
    Thinned strokes cost digits, so this is a retry for a looped tile, never a default."""
    from PIL import Image
    g = img.convert("L")
    hist, total, seen, thr = g.histogram(), g.width * g.height, 0, 0
    for v, n in enumerate(hist):
        seen += n
        if seen >= share * total:
            thr = v
            break
    return g.point(lambda v: 0 if v <= thr else 255).convert("RGB")


def cut_loop(raw: str) -> tuple:
    """(the answer with its loop cut off, whether it was cut). A loop is a tail repeating with a
    period of 1-200 characters for at least 60 characters and three periods. A loop of whole
    lines keeps the first copy of the repeated line (the model read it, then repeated it); a
    loop inside a line ("130 Grand, 10100000...") drops that line, whose end is the loop."""
    n, best, period = len(raw), len(raw), 0
    for p in range(1, 201):
        j = n - p - 1
        while j >= 0 and raw[j] == raw[j + p]:
            j -= 1
        if n - (j + 1) >= max(60, 3 * p) and j + 1 < best:
            best, period = j + 1, p
    if best == n:
        return raw, False
    if "\n" in raw[best:best + period]:          # whole lines repeat: keep the first copy
        start = raw.find("\n", best) + 1 if raw[best - 1:best] not in ("", "\n") else best
        return raw[:start + period], True
    nl = raw.rfind("\n", 0, best)
    return (raw[:nl + 1] if nl >= 0 else ""), True


def slug_for(model: str) -> str:
    tail = model.rsplit("/", 1)[-1].lower()
    return re.sub(r"[^a-z0-9.+-]+", "-", tail).strip("-")


def default_max_side(model: str) -> int:
    """The model card's longest-side target: 2048 for the 4B, 1540 for the 1B and 0.8B."""
    return 2048 if "4b" in model.lower() else 1540


def load_model(model_id: str, dtype, device: str):
    """Model and processor, refusing a partially loaded checkpoint. The 1B's config says
    model_type mistral3, so the Auto class builds a model whose vision tower is missing (it then
    returns empty pages); LightOnOcrForConditionalGeneration loads it, with the text model's keys
    remapped from the older transformers that saved it. The 0.8B and 4B (Qwen3.5) load through
    the Auto class."""
    from transformers import (AutoConfig, AutoModelForImageTextToText, AutoProcessor,
                              LightOnOcrForConditionalGeneration, LightOnOcrProcessor)
    archs = AutoConfig.from_pretrained(model_id).architectures or []
    if any(a.lower().startswith("lightonocr") for a in archs):
        model, info = LightOnOcrForConditionalGeneration.from_pretrained(
            model_id, dtype=dtype, output_loading_info=True,
            key_mapping={r"^language_model\.model\.": "model.language_model."})
        processor = LightOnOcrProcessor.from_pretrained(model_id)
    else:
        model, info = AutoModelForImageTextToText.from_pretrained(
            model_id, dtype=dtype, output_loading_info=True)
        processor = AutoProcessor.from_pretrained(model_id)
    bad = {k: sorted(info.get(k) or []) for k in ("missing_keys", "unexpected_keys",
                                                  "mismatched_keys")}
    if any(bad.values()):
        raise SystemExit(f"{type(model).__name__} did not load {model_id} cleanly -- "
                         + "; ".join(f"{k}: {len(v)} e.g. {v[:3]}" for k, v in bad.items() if v))
    return model.to(device).eval(), processor


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shard", help="text file: one tile image path per line")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--max-side", type=int, default=0, help="default: the card's target")
    ap.add_argument("--max-new-tokens", type=int, default=4096)
    ap.add_argument("--max-time", type=float, default=900.0, help="seconds of generation per tile")
    ap.add_argument("--temperature", type=float, default=0.2,
                    help="0.2 with top_p 0.9 is the card's setting; 0 = greedy")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="torch", help="slug suffix, e.g. lightonocr-3-1b-greedy-torch")
    a = ap.parse_args()

    greedy = a.temperature == 0
    decode = "greedy" if greedy else (f"s{a.seed}" if a.seed else
                                      f"t{a.temperature:g}" if a.temperature != 0.2 else "")
    slug = "-".join(x for x in (slug_for(a.model), decode, a.tag) if x)
    sampling = ({"do_sample": False} if greedy else
                {"do_sample": True, "temperature": a.temperature, "top_p": 0.9})
    max_side = a.max_side or default_max_side(a.model)
    tiles = [Path(p) for p in Path(a.shard).read_text().split() if p.strip()]
    todo = [p for p in tiles if not p.with_name(f"{p.stem}_{slug}.txt").exists()]
    print(f"model {a.model} | slug {slug} | longest side {max_side}px | "
          f"{len(tiles)} tiles, {len(todo)} to do", flush=True)
    if not todo:
        return 0

    import torch
    from PIL import Image
    dtype = getattr(torch, a.dtype)
    print(f"torch {torch.__version__} cuda={torch.cuda.is_available()} device={a.device} "
          f"dtype={a.dtype}", flush=True)
    t0 = time.time()
    model, processor = load_model(a.model, dtype, a.device)
    print(f"loaded {type(model).__name__} cleanly in {time.time() - t0:.0f}s", flush=True)
    if "LightOnOcr" in type(model).__name__:
        processor.image_processor.size = {"longest_edge": max_side}
    template_kwargs = {} if "LightOnOcr" in type(model).__name__ else {"enable_thinking": False}

    ok = failed = cut = retried = truncated = 0
    t_all = time.time()
    for i, path in enumerate(todo, 1):
        img = Image.open(path).convert("RGB")
        scale = max_side / max(img.size)
        if scale < 1:
            img = img.resize((round(img.width * scale), round(img.height * scale)),
                             Image.Resampling.LANCZOS)
        def read(image):
            conversation = [{"role": "user", "content": [{"type": "image", "image": image}]}]
            inputs = processor.apply_chat_template(
                conversation, add_generation_prompt=True, tokenize=True, return_dict=True,
                return_tensors="pt", **template_kwargs)
            inputs = {k: (v.to(device=a.device, dtype=dtype) if v.is_floating_point() else v.to(a.device))
                      for k, v in inputs.items()}
            n_in = inputs["input_ids"].shape[1]
            torch.manual_seed(a.seed)
            t0 = time.time()
            with torch.inference_mode():
                out = model.generate(**inputs, max_new_tokens=a.max_new_tokens, **sampling,
                                     max_time=a.max_time)
            new = out[0, n_in:]
            return processor.decode(new, skip_special_tokens=True), int(new.shape[0]), n_in, time.time() - t0

        try:
            raw, n_out, n_in, elapsed = read(img)
            # Outcomes, each recorded in the meta: clean; timed out (the hardware's clock: no
            # .txt); looped and rescued by the darkest-ink retry (the looped answer kept as
            # .loop.raw.txt); looped twice, cut back to before the repetition.
            looped = n_out >= a.max_new_tokens
            timed_out = elapsed >= a.max_time and not looped
            bleed_retry = loop_truncated = False
            loop_raw = None
            if looped:
                raw2, n2, _n, e2 = read(darkest(img))
                elapsed += e2
                if n2 < a.max_new_tokens and e2 < a.max_time:
                    loop_raw, raw, n_out, bleed_retry = raw, raw2, n2, True
                elif n2 < a.max_new_tokens:              # the retry ran out of clock
                    timed_out = True
                else:                                    # looped again: keep what came before
                    raw, loop_truncated = cut_loop(raw)
        except Exception as exc:                              # noqa: BLE001 - logged, run goes on
            print(f"[{i}/{len(todo)}] FAILED {path.name}: {exc}", file=sys.stderr, flush=True)
            failed += 1
            continue
        retried += bleed_retry
        truncated += loop_truncated
        cut += looped or timed_out
        lines, was_table = to_lines(raw)
        stem = f"{path.stem}_{slug}"
        # raw and meta first, so a tile that parses to nothing or ran out of clock can be read
        path.with_name(f"{stem}.raw.txt").write_text(raw, encoding="utf-8")
        if loop_raw is not None:
            path.with_name(f"{stem}.loop.raw.txt").write_text(loop_raw, encoding="utf-8")
        path.with_name(f"{stem}.meta.json").write_text(json.dumps({
            "model": a.model, "device": a.device, "dtype": a.dtype,
            "gpu": torch.cuda.get_device_name() if torch.cuda.is_available() else None,
            "input_size": list(img.size), "input_tokens": n_in, "output_tokens": n_out,
            "seconds": round(elapsed, 1), "tok_per_s": round(n_out / max(elapsed, 1e-9), 1),
            "lines": len(lines), "complete": not (looped or timed_out), "looped": looped,
            "timed_out": timed_out, "table_mode": was_table, "bleed_retry": bleed_retry,
            "loop_truncated": loop_truncated, "sampling": {**sampling, "seed": a.seed},
            "max_new_tokens": a.max_new_tokens, "max_time": a.max_time}, indent=1),
            encoding="utf-8")
        if timed_out:
            print(f"[{i}/{len(todo)}] CUT OFF at {a.max_time:.0f}s {path.name}: raw kept, no .txt",
                  file=sys.stderr, flush=True)
            failed += 1
            continue
        if not lines:
            print(f"[{i}/{len(todo)}] EMPTY {path.name}{' (loop cut to nothing)' if loop_truncated else ''}"
                  " -- raw and meta kept, no .txt", file=sys.stderr, flush=True)
            failed += 1
            continue
        path.with_name(f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        ok += 1
        print(f"[{i}/{len(todo)}] {path.name} {len(lines)} lines, {n_out} tok in {elapsed:.1f}s"
              f"{' LOOPED' if looped else ''}{' BLEED RETRY' if bleed_retry else ''}"
              f"{' LOOP TRUNCATED' if loop_truncated else ''}{' table' if was_table else ''}", flush=True)
    print(f"done {ok}, failed {failed} ({cut} cut off or looped), bleed retries {retried}, "
          f"loops truncated {truncated}, {time.time() - t_all:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
