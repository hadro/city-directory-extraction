# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "transformers>=4.46",
#   "torch",
#   "peft>=0.13",
#   "accelerate>=1.0",
# ]
# ///
"""
Run a fine-tuned Qwen city-directory extractor over an eval set and emit predictions for
eval/evaluate.py -- the third row of the comparison table (qwen-*) next to the GLiNER floor
and Gemini bar.

It reproduces train/sft_qwen.py's prompt EXACTLY (same SYSTEM_PIPE/SYSTEM_YAML, same
user_prompt, and -- unlike the zero-shot baselines -- NO field guide), so the model is scored
through the same path it was trained on (van Strien's eval-realism rule).

    # full / merged checkpoint:
    uv run eval/qwen_predict.py --model <you>/city-directory-extractor-0.8b --gold data/nyu_eval.jsonl --target pipe
    # LoRA adapter on top of its base:
    uv run eval/qwen_predict.py --base-model Qwen/Qwen3.5-0.8B --model <you>/city-dir-0.8b-lora \
        --gold data/nyu_eval.jsonl --target pipe
    python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_qwen.txt --target pipe \
        --save results/scores.jsonl --label qwen-0.8b

    python3 eval/qwen_predict.py --self-test     # prompt/parse logic only; stdlib, no model

IMPORTANT: --target MUST match the --target train/sft_qwen.py was trained with (pipe or yaml).
A trained model emits its format consistently, so unlike zero-shot Gemini it doesn't need YAML
to avoid column-shift -- the plan's pipe-vs-YAML A/B is decided on the *trained* model here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional

# Must match train/sft_qwen.py + eval/evaluate.py (FIELDS, SYSTEM_PIPE, SYSTEM_YAML, user_prompt).
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

SYSTEM_PIPE = (
    "You convert ONE line from a historical US city directory into structured fields. "
    "Output exactly one row of pipe-separated values in this order:\n"
    + "|".join(FIELDS) + "\n"
    "Copy values verbatim from the line. Use True/False for is_business. Leave a field "
    "empty (nothing between the pipes) when the line does not contain it. Output only the row."
)
SYSTEM_YAML = (
    "You convert ONE line from a historical US city directory into structured fields. "
    "Output YAML with exactly these keys: " + ", ".join(FIELDS) + ". "
    "Copy values verbatim; use True/False for is_business; use an empty string for absent "
    "fields. Output only the YAML."
)


def system_for(target: str) -> str:
    return SYSTEM_YAML if target == "yaml" else SYSTEM_PIPE


def user_prompt(ex: dict) -> str:
    ctx = ex.get("context", {})
    tag = f"[dialect={ctx.get('dialect', '?')}; year={ctx.get('directory_year', '?')}]"
    return f"{tag} {ex['raw_line']}"


def parse_completion(text: str, target: str) -> str:
    """Extract the serialized record from the model's generated text (tolerate fences)."""
    if not text:
        return ""
    t = re.sub(r"^```[a-zA-Z]*\n?|\n?```\s*$", "", text.strip()).strip()
    if target == "yaml":
        return "\n".join(ln for ln in t.splitlines() if ln.strip())
    for line in t.splitlines():
        if "|" in line:
            return line.strip()
    return t.splitlines()[0].strip() if t.splitlines() else ""


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def predict(net, tok, examples, target, batch_size, max_new_tokens):
    """Yield one serialized record per example, in input order (greedy / deterministic)."""
    import torch
    for batch in _chunks(examples, batch_size):
        texts = [tok.apply_chat_template(
            [{"role": "system", "content": system_for(target)},
             {"role": "user", "content": user_prompt(ex)}],
            tokenize=False, add_generation_prompt=True) for ex in batch]
        enc = tok(texts, return_tensors="pt", padding=True).to(net.device)
        with torch.no_grad():
            out = net.generate(**enc, max_new_tokens=max_new_tokens,
                               do_sample=False, pad_token_id=tok.pad_token_id)
        for row in out[:, enc["input_ids"].shape[1]:]:
            yield parse_completion(tok.decode(row, skip_special_tokens=True), target)


def _load_model(model_id: str):
    """Load a Qwen3.5 checkpoint with the SAME class TRL/SFTTrainer used at train time.

    Qwen3.5 is multimodal (it carries a vision tower). When SFTTrainer is handed the model
    *id string*, it auto-loads the full vision-language model, so LoRA (target_modules=
    "all-linear") wraps both the text decoder AND the vision tower, and the adapter's keys are
    nested under that multimodal wrapper. Loading AutoModelForCausalLM here gives a text-only
    module tree with a DIFFERENT nesting -> PeftModel reports "missing adapter keys" and the
    trained text adapter is silently NOT applied (eval then scores at the base-model floor).
    Mirror training: try the image-text-to-text class first, fall back to causal LM."""
    try:
        from transformers import AutoModelForImageTextToText
        net = AutoModelForImageTextToText.from_pretrained(model_id, torch_dtype="auto", device_map="auto")
        print(f"  loaded {model_id} as AutoModelForImageTextToText (multimodal, matches training)", file=sys.stderr)
        return net
    except Exception as e:                              # genuinely text-only / merged checkpoint
        print(f"  multimodal load failed ({type(e).__name__}: {e}); using AutoModelForCausalLM", file=sys.stderr)
        from transformers import AutoModelForCausalLM
        return AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="auto", device_map="auto")


def load(model_id: str, base_model: Optional[str]):
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(base_model or model_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "left"                          # decoder-only batched generation
    if base_model:
        from peft import PeftModel
        base = _load_model(base_model)
        net = PeftModel.from_pretrained(base, model_id)
    else:
        net = _load_model(model_id)
    net.eval()
    return net, tok


def load_examples(path: str):
    """Read example JSONL from a local path, http(s) URL, or hf://datasets/<repo>/<file> (the
    last lets this run as an HF Job so the 5GB model downloads in the datacenter, not over your
    wifi). hf:// + private repos authenticate via the job's HF_TOKEN."""
    if path.startswith("hf://datasets/"):
        from huggingface_hub import hf_hub_download
        parts = path[len("hf://datasets/"):].split("/")
        path = hf_hub_download(repo_id="/".join(parts[:2]), filename="/".join(parts[2:]), repo_type="dataset")
        text = open(path, encoding="utf-8").read()
    elif path.startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(path) as r:
            text = r.read().decode("utf-8")
    else:
        text = open(path, encoding="utf-8").read()
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def push_preds(local_path: str, dest: str) -> None:
    """Upload the (tiny) preds file to hf://datasets/<repo>/<file> so a Job's output comes back
    without the model ever touching your machine."""
    from huggingface_hub import upload_file
    parts = dest[len("hf://datasets/"):].split("/")
    upload_file(path_or_fileobj=local_path, path_in_repo="/".join(parts[2:]),
                repo_id="/".join(parts[:2]), repo_type="dataset")


# --- offline self-test: prompt + parse, NO model / heavy deps ---------------------------------
def _self_test() -> int:
    assert system_for("pipe") == SYSTEM_PIPE and system_for("yaml") == SYSTEM_YAML
    up = user_prompt({"raw_line": "Smith John, clk, 12 Pine", "context": {"dialect": "nyc", "directory_year": "1860"}})
    assert up == "[dialect=nyc; year=1860] Smith John, clk, 12 Pine", up
    row = "Smith John|False|||clk||12 Pine|"
    for c in (row, f"```\n{row}\n```", f"sure:\n{row}"):
        got = parse_completion(c, "pipe")
        print(f"  {c!r} -> {got!r}", file=sys.stderr)
        assert got == row, got
    yblock = 'name: "Smith John"\noccupation_role: "clk"'
    assert parse_completion(f"```yaml\nname: \"Smith John\"\n\noccupation_role: \"clk\"\n```", "yaml") == yblock
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="fine-tuned checkpoint (full/merged, or a LoRA adapter with --base-model)")
    ap.add_argument("--base-model", default=None, help="base model id when --model is a LoRA adapter")
    ap.add_argument("--gold", help="eval JSONL ({raw_line, context, record}) to predict on")
    ap.add_argument("--out", default="data/preds_qwen.txt",
                    help="predictions file, one record per gold line (default under git-ignored data/)")
    ap.add_argument("--push-out", default=None,
                    help="also upload preds to hf://datasets/<repo>/<file> — use when running this "
                         "as an HF Job so the model stays in the datacenter; then download the tiny "
                         "preds and score locally")
    ap.add_argument("--target", choices=["pipe", "yaml"], default="pipe",
                    help="MUST match the format sft_qwen.py was trained with")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--self-test", action="store_true", help="check prompt/parse logic; no model")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.model or not args.gold:
        ap.error("--model and --gold are required (or use --self-test)")

    examples = load_examples(args.gold)
    if args.limit:
        examples = examples[:args.limit]

    net, tok = load(args.model, args.base_model)
    sep = "\n\n" if args.target == "yaml" else "\n"
    n = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for rec in predict(net, tok, examples, args.target, args.batch_size, args.max_new_tokens):
            out.write(rec + sep)
            n += 1
            if n % 100 == 0:
                print(f"  ... {n}/{len(examples)}", file=sys.stderr)

    print(f"wrote {n} predictions ({args.model}, {args.target}) -> {args.out}", file=sys.stderr)
    if args.push_out:
        push_preds(args.out, args.push_out)
        print(f"uploaded preds -> {args.push_out}", file=sys.stderr)
    # Point the hint at the file you'll actually score: the pushed hf:// target when --push-out is
    # set (evaluate.py reads hf:// too), else the local --out. Avoids suggesting the stale local
    # default after a Job that only pushed remotely.
    pred_for_hint = args.push_out or args.out
    print(f"score with: python3 eval/evaluate.py --gold {args.gold} --pred {pred_for_hint} --target {args.target}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
