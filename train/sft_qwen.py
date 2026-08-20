# /// script
# requires-python = ">=3.10"
# dependencies = [
#   # PINNED EXACTLY, deliberately. These were floors (">=") until 2026-08-04, which meant
#   # `uv run` resolved whatever was current on the day and two runs weeks apart were not the
#   # same experiment. v4 (2026-07-20) and v5 (2026-08-03) differed by at least peft
#   # 0.19.1 -> 0.20.0 (read from their adapter_config.json), and v5 came back with a
#   # generation-termination defect v4 did not have. The mechanism was never identified — which
#   # is exactly the point: an unreproducible training script cannot be debugged.
#   #
#   # To move a pin: bump it, run the 3k smoke, and confirm --check-termination still passes.
#   # Record the versions in the model card. Do NOT relax these back to ">=".
#   "trl==1.9.2",
#   "transformers==5.14.1",
#   "datasets==5.0.1",
#   "accelerate==1.14.0",
#   "peft==0.20.0",
#   "bitsandbytes==0.50.0",
#   "torch==2.13.0",
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
    tag = f"[publisher={ctx.get('publisher', '?')}; year={ctx.get('directory_year', '?')}]"
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
    ap.add_argument("--revision", default=None,
                    help="pin the base-model repo revision (commit sha) for reproducibility. The "
                         "deps are pinned exactly above; this pins the other half of the "
                         "environment, since a base repo's chat template or tokenizer can change "
                         "under you between runs.")
    ap.add_argument("--check-termination", type=int, default=8, metavar="N",
                    help="after training, generate N held-out examples and FAIL if the model does "
                         "not stop cleanly (0 to skip). v5 trained perfectly by every training "
                         "metric — loss 0.009, token-acc 0.998 — yet never learned to emit its "
                         "stop token, so it ran on into a replayed 'user' turn. Nothing in the "
                         "training loop noticed. This is the check that would have.")
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
    ap.add_argument("--dry-run", action="store_true",
                    help="build the LoRA-wrapped model and print which modules get adapters "
                         "(verifies exclude_modules), then exit — no training, no GPU needed")
    ap.add_argument("--packing", action="store_true",
                    help="pack short examples to fill max_seq_len (HF's efficiency default); big "
                         "throughput win for our short directory lines, no kernels needed")
    ap.add_argument("--save-steps", type=int, default=0,
                    help="checkpoint every N steps instead of once per epoch. Needed wherever a run "
                         "can be cut short by a wall-clock limit or preemption (SLURM/HPC, Kaggle) — "
                         "epoch checkpoints are ~1h+ apart. 0 = keep save_strategy='epoch'.")
    ap.add_argument("--save-total-limit", type=int, default=2,
                    help="keep only the N most recent step checkpoints (disk hygiene on shared FS)")
    ap.add_argument("--resume-from-checkpoint", default=None,
                    help="resume from a checkpoint dir, or 'auto' to pick the latest in --output-dir "
                         "(no-op if none exists yet, so a requeued job can use it unconditionally)")
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

    # Record the resolved dependency versions. The PEP-723 block above pins only FLOORS, so
    # `uv run` resolves whatever is current on the day — and two runs weeks apart are not
    # necessarily the same experiment. When v5 came back with a generation-termination defect
    # that v4 didn't have, the job log turned out to contain no version information at all
    # (uv's download lines omit them), so the one thing needed to diagnose it was unrecoverable.
    # Print them where `hf jobs logs` will keep them.
    import importlib.metadata as _md
    _vers = {}
    for _p in ("torch", "transformers", "trl", "peft", "accelerate", "datasets", "tokenizers"):
        try:
            _vers[_p] = _md.version(_p)
        except Exception:
            _vers[_p] = "?"
    print("dependency versions: " + "  ".join(f"{k}=={v}" for k, v in _vers.items()), file=sys.stderr)

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

    if args.dry_run:
        if peft_config is None:
            sys.exit("--dry-run inspects LoRA targeting; not meaningful with --full")
        import collections, re as _re
        from transformers import AutoModelForImageTextToText
        from peft import get_peft_model
        print(f"[dry-run] loading {args.model} (multimodal, as SFTTrainer would) on CPU...", file=sys.stderr)
        base = AutoModelForImageTextToText.from_pretrained(args.model, torch_dtype="auto")
        pm = get_peft_model(base, peft_config)
        mods, visual = collections.Counter(), 0
        for pname, _ in pm.named_parameters():
            if ".lora_" in pname:
                mods[pname.split(".lora_")[0].split(".")[-1]] += 1
                if "visual" in pname:
                    visual += 1
        print("[dry-run] adapted submodule types (count of lora_A/B tensors):", file=sys.stderr)
        for k, v in sorted(mods.items()):
            print(f"    {k}: {v}", file=sys.stderr)
        pm.print_trainable_parameters()
        print(f"[dry-run] adapter params touching 'visual': {visual}", file=sys.stderr)
        print("[dry-run] OK — exclude_modules working (no vision adapters)" if visual == 0
              else "[dry-run] WARNING — vision tower still being adapted!", file=sys.stderr)
        return 0

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
        save_strategy="steps" if args.save_steps else "epoch",
        save_steps=args.save_steps or 500,             # ignored when save_strategy="epoch"
        save_total_limit=args.save_total_limit,
        bf16=use_bf16,
        fp16=not use_bf16,
        packing=args.packing,
        packing_strategy="wrapped",   # TRL 0.20+ needs this for packing; filtered out on older TRL
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
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    tok_kw = ("processing_class" if "processing_class" in inspect.signature(SFTTrainer.__init__).parameters
              else "tokenizer")
    trainer = SFTTrainer(model=args.model, args=cfg, train_dataset=ds, peft_config=peft_config,
                         **{tok_kw: tokenizer})

    # 'auto' = resume the latest checkpoint if one is there, else start fresh. That lets a SLURM
    # script pass the flag unconditionally: first submission trains from scratch, a requeue after
    # a wall-clock kill picks up where it left off.
    resume = args.resume_from_checkpoint
    if resume == "auto":
        from transformers.trainer_utils import get_last_checkpoint
        import os
        resume = get_last_checkpoint(args.output_dir) if os.path.isdir(args.output_dir) else None
        print(f"resume: {resume or 'no checkpoint found — starting fresh'}", file=sys.stderr)
    trainer.train(resume_from_checkpoint=resume)
    trainer.save_model(args.output_dir)

    # ---- termination check: does the model actually STOP? -------------------------------------
    # Run BEFORE the push, so a broken model is never published. Every training-side metric can
    # look perfect while the model has not learned to emit its stop token; the only way to know is
    # to generate and look. Warn-don't-die by default is deliberate: a 2.6h run should not be
    # thrown away over a check, but the failure must be impossible to miss in the log.
    if args.check_termination:
        n = min(args.check_termination, len(ds))
        print(f"\n=== termination check: generating {n} examples ===", file=sys.stderr)
        bad = []
        try:
            import torch as _t
            m = trainer.model.eval()
            for i in range(n):
                msgs = ds[i]["messages"][:2]                     # system + user only
                text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
                enc = tokenizer(text, return_tensors="pt").to(m.device)
                with _t.no_grad():
                    # Stop on BOTH <|im_end|> (tokenizer.eos, what the SFT trained) and
                    # <|endoftext|> (tokenizer.pad, what the base config declares). Without this
                    # generate() honours only the config EOS and runs past the model's own answer
                    # — which makes this probe report a runaway that generation settings caused.
                    # Keep in sync with eval/qwen_predict.py, or the probe is not testing eval.
                    stops = [t for t in {tokenizer.eos_token_id, tokenizer.pad_token_id}
                             if t is not None]
                    out = m.generate(**enc, max_new_tokens=160, do_sample=False,
                                     eos_token_id=stops,
                                     pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
                gen = out[0][enc["input_ids"].shape[1]:]
                txt = tokenizer.decode(gen, skip_special_tokens=True)
                # A healthy completion is ONE record and then stop. These markers mean the model
                # ran past its own answer into a replayed conversation turn.
                stopped = gen[-1].item() in (tokenizer.eos_token_id, tokenizer.pad_token_id)
                # Count records by lines that START with "name:". A bare substring count also
                # matches "spouse_name:", so every correct record for a married person looked
                # like a runaway and the check fired on healthy models.
                n_records = sum(1 for ln in txt.splitlines() if ln.startswith("name:"))
                runaway = any(k in txt for k in ("<think>", "\nuser\n", "\nassistant\n")) \
                    or n_records > 1
                if runaway or not stopped:
                    bad.append((i, txt[:160].replace("\n", " | ")))
            if bad:
                print(f"*** TERMINATION CHECK FAILED: {len(bad)}/{n} completions ran away or "
                      f"never emitted a stop token.", file=sys.stderr)
                for i, t in bad[:3]:
                    print(f"    [{i}] {t}", file=sys.stderr)
                print("*** The adapter will still be saved/pushed, but DO NOT trust its eval "
                      "numbers: a runaway completion corrupts YAML parsing downstream. Re-check "
                      "the dependency pins at the top of this file before using it.", file=sys.stderr)
            else:
                print(f"termination check OK — {n}/{n} completions stopped cleanly", file=sys.stderr)
        except Exception as e:                      # never let the check itself kill a good run
            print(f"termination check could not run ({type(e).__name__}: {e})", file=sys.stderr)

    if args.push_to_hub:
        trainer.push_to_hub()
    print(f"done -> {args.hub_model_id or args.output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
