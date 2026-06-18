# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "trl>=0.12",
#   "transformers>=4.46",
#   "datasets>=3.0",
#   "accelerate>=1.0",
#   "peft>=0.13",
#   "bitsandbytes>=0.43",
# ]
# ///
"""
Supervised fine-tune (SFT) of a small Qwen3.5 model to turn a single historical
city-directory line into a structured pipe-delimited (or YAML) record.

Trains on the JSONL produced by data_prep/synth_persons.py
({raw_line, context, record}). Runs locally (with a GPU) or, unchanged, on HF Jobs:

    hf jobs uv run --flavor a100-large \\
        https://raw.githubusercontent.com/<you>/city-directory-extraction/main/train/sft_qwen.py \\
        --train-file hf://datasets/<you>/city-directory-synth/train.jsonl \\
        --model Qwen/Qwen3.5-0.8B --hub-model-id <you>/city-directory-extractor-0.8b --push-to-hub

Inspect the exact training examples first, with NO heavy deps (stdlib only):

    python3 train/sft_qwen.py --train-file data/synth_train.jsonl --preview-prompts 4

Notes
-----
* `--model` must be a real, available checkpoint id; pin a revision for reproducibility.
  Qwen3.5 small sizes (~0.8B/2B/4B) are the target family (see docs/plan.md).
* Default uses LoRA (cheap/fast); pass --full for a full fine-tune, or --qlora for 4-bit
  (fits e.g. 4B on a free 16GB T4 / Colab). Precision auto-selects bf16 (Ampere+) vs fp16 (T4).
* No paid HF plan needed: this runs on free Colab/Kaggle GPUs and `--push-to-hub` is free.
  See notebooks/colab_finetune.ipynb for a ready-to-run free-Colab flow.
* `assistant_only_loss` trains on the completion only. TRL APIs shift between versions;
  if a kwarg is rejected, adjust to your installed TRL.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

# Must match data_prep/synth_persons.py FIELDS
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


def _cell(record, f):
    v = record.get(f, "")
    return ("True" if v else "False") if isinstance(v, bool) else v


def to_pipe(record):
    return "|".join(_cell(record, f) for f in FIELDS)


def to_yaml(record):
    def q(v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "\n".join(f"{f}: {q(_cell(record, f))}" for f in FIELDS)


def user_prompt(ex: dict) -> str:
    ctx = ex.get("context", {})
    tag = f"[dialect={ctx.get('dialect', '?')}; year={ctx.get('directory_year', '?')}]"
    return f"{tag} {ex['raw_line']}"


def build_messages(ex: dict, target: str) -> list:
    system = SYSTEM_PIPE if target == "pipe" else SYSTEM_YAML
    ser = to_pipe if target == "pipe" else to_yaml
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt(ex)},
        {"role": "assistant", "content": ser(ex["record"])},
    ]


def read_jsonl(path: str):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train-file", required=True, help="JSONL from synth_persons.py")
    ap.add_argument("--target", choices=["pipe", "yaml"], default="pipe")
    ap.add_argument("--preview-prompts", type=int, default=0,
                    help="print N formatted training examples and exit (no ML deps needed)")
    ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B")
    ap.add_argument("--hub-model-id", default=None)
    ap.add_argument("--output-dir", default="out_sft")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--max-train-samples", type=int, default=0,
                    help="cap training examples after a shuffle (0 = all). This task converges in "
                         "well under one epoch, so a small cap + --epochs 1 trains in minutes.")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--grad-accum", type=int, default=1)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq-len", type=int, default=512)
    ap.add_argument("--full", action="store_true", help="full fine-tune instead of LoRA")
    ap.add_argument("--qlora", action="store_true",
                    help="4-bit QLoRA — fits e.g. 4B on a free 16GB T4 (Colab); LoRA-only, not with --full")
    ap.add_argument("--push-to-hub", action="store_true")
    args = ap.parse_args(argv)

    # ---- lightweight path: inspect the data without importing torch/trl ----
    if args.preview_prompts:
        for i, ex in enumerate(read_jsonl(args.train_file)):
            if i >= args.preview_prompts:
                break
            print("=" * 80)
            for m in build_messages(ex, args.target):
                print(f"[{m['role']}]\n{m['content']}\n")
        return 0

    # ---- training path: heavy imports happen only here ----
    import torch
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer

    ds = load_dataset("json", data_files=args.train_file, split="train")
    if args.max_train_samples and args.max_train_samples < len(ds):
        ds = ds.shuffle(seed=42).select(range(args.max_train_samples))
        print(f"capped training set to {args.max_train_samples} examples (shuffled)", file=sys.stderr)
    target = args.target

    def fmt(ex):
        return {"messages": build_messages(ex, target)}

    ds = ds.map(fmt, remove_columns=ds.column_names)

    # Adaptive precision: Ampere+ gets bf16; Turing (e.g. the free Colab T4) only fp16.
    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()

    if args.qlora and args.full:
        sys.exit("--qlora cannot combine with --full (QLoRA is 4-bit base + LoRA)")

    peft_config = None
    if not args.full:
        from peft import LoraConfig
        peft_config = LoraConfig(
            r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
            task_type="CAUSAL_LM",
            # "all-linear" adapts every linear layer, so it maps cleanly onto Qwen3.5's hybrid
            # (attention + linear-attention) layers — naming q/k/v/o_proj left ~1/4 of layers
            # un-adapted (the "missing adapter keys" warning).
            target_modules="all-linear",
            # ...but Qwen3.5 is multimodal: all-linear otherwise also adapts the vision tower
            # (visual.*, ~half the saved tensors) which we never use for text -> wasted capacity
            # AND a train/eval load-class mismatch footgun. Exclude it so the adapter is text-only.
            exclude_modules="(?i).*visual.*",
        )

    model_init_kwargs = None
    if args.qlora:
        from transformers import BitsAndBytesConfig
        model_init_kwargs = {"quantization_config": BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if use_bf16 else torch.float16)}

    # TRL's config API drifts between versions; build kwargs, then keep only what THIS
    # SFTConfig accepts (e.g. max_seq_length was renamed to max_length) so a minor version
    # bump can't crash the run on remote infra.
    from dataclasses import fields as _dc_fields
    cfg_fields = {f.name for f in _dc_fields(SFTConfig)}
    cfg_kwargs = dict(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=25,
        save_strategy="epoch",
        bf16=use_bf16,
        fp16=not use_bf16,
        packing=False,
        assistant_only_loss=True,
        model_init_kwargs=model_init_kwargs,
        push_to_hub=args.push_to_hub,
        hub_model_id=args.hub_model_id,
        report_to="none",
    )
    cfg_kwargs["max_length" if "max_length" in cfg_fields else "max_seq_length"] = args.max_seq_len
    for k in [k for k in cfg_kwargs if k not in cfg_fields]:
        print(f"note: this TRL's SFTConfig has no '{k}'; skipping it", file=sys.stderr)
        cfg_kwargs.pop(k)
    cfg = SFTConfig(**cfg_kwargs)
    # Hand the trainer a TEXT tokenizer explicitly. Newer TRL otherwise calls AutoProcessor,
    # which for Qwen checkpoints pulls in a vision image-processor (needs PIL/torchvision we
    # don't ship). Kwarg is `processing_class` on new TRL, `tokenizer` on older.
    import inspect
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    tok_kw = ("processing_class" if "processing_class" in inspect.signature(SFTTrainer.__init__).parameters
              else "tokenizer")
    trainer = SFTTrainer(model=args.model, args=cfg, train_dataset=ds, peft_config=peft_config,
                         **{tok_kw: tokenizer})
    trainer.train()
    trainer.save_model(args.output_dir)
    if args.push_to_hub:
        trainer.push_to_hub()
    print(f"done -> {args.hub_model_id or args.output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
