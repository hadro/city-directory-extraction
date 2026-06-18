# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "unsloth",
#   "unsloth_zoo",
#   "trl",
#   "datasets",
# ]
# ///
"""
DISPOSABLE speed probe: does Unsloth's bundled Triton kernels train Qwen3.5 faster than our
stock TRL/torch-fallback path? Same data shaping and smoke config as sft_qwen.py so train_runtime
is directly comparable to the baseline (job 2: ~33s for 200 samples, 25 steps, 1.32 s/it).

Run as an HF Job:
  hf jobs uv run --flavor l4x1 --timeout 30m --secrets HF_TOKEN=$(hf auth token) \
    train/sft_unsloth_smoke.py --train-file <smoke url> --max-train-samples 200 --batch-size 8

Not for production — it's only here to measure s/it. If Unsloth wins, fold its loader into sft_qwen.py.
"""
# Unsloth MUST be imported before transformers/trl so its patches apply.
from unsloth import FastLanguageModel
import argparse, json, sys, urllib.request
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig

FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]
SYSTEM_YAML = (
    "You convert ONE line from a historical US city directory into structured fields. "
    "Output YAML with exactly these keys: " + ", ".join(FIELDS) + ". "
    "Copy values verbatim; use True/False for is_business; use an empty string for absent "
    "fields. Output only the YAML.")


def _cell(record, f):
    v = record.get(f, "")
    return ("True" if v else "False") if isinstance(v, bool) else v


def to_yaml(record):
    def q(v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "\n".join(f"{f}: {q(_cell(record, f))}" for f in FIELDS)


def build_messages(ex):
    ctx = ex.get("context", {})
    tag = f"[dialect={ctx.get('dialect', '?')}; year={ctx.get('directory_year', '?')}]"
    return [
        {"role": "system", "content": SYSTEM_YAML},
        {"role": "user", "content": f"{tag} {ex['raw_line']}"},
        {"role": "assistant", "content": to_yaml(ex["record"])},
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-file", required=True)
    ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B")
    ap.add_argument("--max-train-samples", type=int, default=200)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-seq-len", type=int, default=512)
    ap.add_argument("--packing", action="store_true")
    ap.add_argument("--grad-ckpt", default="unsloth",
                    help='use_gradient_checkpointing: "unsloth" (default), or "false" to disable '
                         '(faster when VRAM is not the constraint, e.g. 0.8B on an L4)')
    args = ap.parse_args()
    grad_ckpt = False if str(args.grad_ckpt).lower() == "false" else args.grad_ckpt

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model, max_seq_length=args.max_seq_len,
        load_in_4bit=False, load_in_16bit=True, full_finetuning=False)
    model = FastLanguageModel.get_peft_model(
        model, r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=32, lora_dropout=0, bias="none",
        use_gradient_checkpointing=grad_ckpt, random_state=42, max_seq_length=args.max_seq_len)

    ds = load_dataset("json", data_files=args.train_file, split="train")
    if args.max_train_samples and args.max_train_samples < len(ds):
        ds = ds.shuffle(seed=42).select(range(args.max_train_samples))
    # Unsloth's SFTTrainer wants a rendered text column (it won't auto-apply the chat template
    # to a 'messages' column), so pre-render via apply_chat_template — the canonical Unsloth flow.
    ds = ds.map(lambda ex: {"text": tokenizer.apply_chat_template(build_messages(ex), tokenize=False)},
                remove_columns=ds.column_names)

    from dataclasses import fields as _dc_fields
    cfg_fields = {f.name for f in _dc_fields(SFTConfig)}
    cfg_kwargs = dict(output_dir="out_unsloth", num_train_epochs=1,
                      per_device_train_batch_size=args.batch_size, learning_rate=2e-4,
                      logging_steps=25, save_strategy="no", bf16=True, dataset_text_field="text",
                      packing=args.packing, packing_strategy="wrapped", report_to="none")
    cfg_kwargs["max_length" if "max_length" in cfg_fields else "max_seq_length"] = args.max_seq_len
    for k in [k for k in cfg_kwargs if k not in cfg_fields]:
        print(f"note: SFTConfig has no '{k}'; skipping", file=sys.stderr)
        cfg_kwargs.pop(k)

    trainer = SFTTrainer(model=model, args=SFTConfig(**cfg_kwargs), train_dataset=ds,
                         processing_class=tokenizer)
    trainer.train()
    print("UNSLOTH SMOKE DONE", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
