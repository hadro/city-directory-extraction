# city-directory-extraction

Fine-tuning small open models to extract **structured person records from historical
city directories** — and releasing the models + datasets to the community on Hugging Face.

This is the focused fine-tuning project spun out of the
[`directory-pipeline`](../directory-pipeline) repo, whose Gemini-based NER step
(`pipeline/extract_entries.py`) this work aims to replace for the city-directory
*persons* shape, covering two real dialects — **Tulsa 1921** (employer + `r/b/rms` address +
`(c)`) and **NYC Trow/Doggett 1850–1890** (separate work/home address, `wid`/`col'd` markers).
Union schema: name · is_business · spouse · race · occupation · employer · address · home_address.

> Full rationale, data landscape, and the phased roadmap live in [docs/plan.md](docs/plan.md).

## Approach in one paragraph

Train **synthetic-first** (license-clean, ours to release) on directory-style lines, then
**evaluate on real gold** (NYU NYC 1850–1890, French Trade Directories, and our own
reviewed pages). Fine-tune the small **Qwen3.5** family (0.8B/2B/4B) with TRL SFT, run it on
**HF Jobs**, emit a non-JSON target (pipe-delimited or YAML — decided by A/B test), and
publish models + datasets with proper cards. Modeled on Mattingly's "3.6M names" and
van Strien's `small-models-for-glam/index-card-extractor`.

## Layout

```
data_prep/
  synth_persons.py     # ✅ (line -> record) generator — Tulsa 1921 + NYC Trow/Doggett dialects (--profile)
  nyu_to_eval.py       # ✅ NYU NDJSON -> held-out NYC gold pairs (verbatim labels, score-gated)
  ftd_to_eval.py       # ✅ French Trade Directories (SODUCO) -> cross-lingual transfer eval
  harvest_own.py       # ✅ pipeline output -> in-domain eval (Tulsa + Lain-1897 schemas; real OCR)
  harvest_minneapolis.py # ✅ Minneapolis 1900 (MIT) transcription gold -> union-schema SILVER eval (review)
train/sft_qwen.py      # ✅ TRL SFT (PEP-723; LoRA / --qlora 4-bit / --full; --preview-prompts = dep-free dry run)
notebooks/colab_finetune.ipynb # ✅ free-Colab fine-tune on a T4 (no paid plan) -> push to Hub
eval/evaluate.py       # ✅ field-level precision/recall/exact-match (+ --self-test; --save logs metrics)
eval/gliner_baseline.py # ✅ zero-shot GLiNER (urchade) extractive baseline -> pipe preds (+ --self-test)
eval/gemini_baseline.py # ✅ Gemini baseline (the "bar"); same prompt/schema as the SFT model (+ --self-test)
eval/results_table.py  # ✅ pivot results/scores.jsonl -> model × eval-set Markdown table (+ --self-test)
eval/qwen_predict.py   # ✅ run the fine-tuned Qwen over an eval set -> preds (same prompt as sft_qwen; + --self-test)
cards/                 # ✅ MODEL_CARD.md + DATASET_CARD.md templates
results/               # eval_table.md (tracked); scores.jsonl log is gitignored (*.jsonl, regenerable)
data/                  # gitignored: downloads + generated sets
```

## Quickstart (synthetic data)

```bash
# eyeball a sample (default profile = mix of both dialects)
python3 data_prep/synth_persons.py --n 8 --preview
python3 data_prep/synth_persons.py --n 8 --preview --profile nyc    # or --profile tulsa

# generate a mixed training set
python3 data_prep/synth_persons.py --n 100000 --out data/synth_train.jsonl --seed 13
```

Each JSONL row is `{raw_line, context:{dialect, alphabetical_range, directory_year},
record:{name, is_business, spouse_name, race_designation, occupation_role, employer,
address, home_address}}`. Schema, abbreviations, and field distributions are matched to the
two real gold sets — the 1921 Tulsa directory (`../tulsa-city-directories/1921.csv` + its
ABBREVIATIONS key in `1921.html`) and the NYU NYC 1850–1890 set (its `complete_entry` raw
lines + `labeled_entry` parses). `raw_line` carries optional OCR noise (the model input);
`record` is the clean target; `context` (dialect / 3-letter range / year) is page-level
metadata fed in the prompt rather than predicted.

## Train & evaluate

```bash
# 0) inspect the exact SFT examples (stdlib only — no ML deps)
python3 train/sft_qwen.py --train-file data/synth_train.jsonl --preview-prompts 4

# 1) build eval sets (all map into the same schema as the synthetic data)
python3 data_prep/nyu_to_eval.py  --in data/1850.ndjson --out data/nyu_eval.jsonl --limit 3000   # NYC gold (EVAL ONLY, CC-BY-SA-NC)
python3 data_prep/ftd_to_eval.py  --in data/ftd.json    --out data/ftd_eval.jsonl                # French cross-lingual transfer
python3 data_prep/harvest_own.py  --dir ../directory-pipeline/output/tulsa_1921 --out data/tulsa_eval.jsonl  # in-domain (real OCR)
python3 data_prep/harvest_minneapolis.py --dir data/minneapolis/ground_truth --out data/minneapolis_eval.jsonl  # US silver eval (MIT; review)

# 2) fine-tune a small Qwen3.5 — FREE on a Colab/Kaggle T4 (see notebooks/colab_finetune.ipynb),
#    or local GPU, or `hf jobs uv run <url>`. Add --qlora to fit 4B on a 16GB T4.
python3 train/sft_qwen.py --train-file data/synth_train.jsonl \
    --model Qwen/Qwen3.5-0.8B --hub-model-id <you>/city-directory-extractor-0.8b --push-to-hub

# 3) score predictions (one serialized row per gold line, same order) against gold
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred preds.pipe.txt
python3 eval/evaluate.py --gold data/synth_dev.jsonl --self-test   # sanity-check the harness

# baselines -> pipe preds (default to git-ignored data/preds_*.txt); --save logs metrics per run
uv run eval/gliner_baseline.py --gold data/nyu_eval.jsonl                 # +--model urchade/gliner_multi-v2.1 for FTD
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_gliner.txt \
    --save results/scores.jsonl --label gliner-medium

# bar: Gemini, SAME lines/schema/prompt (needs GEMINI_API_KEY; default gemini-3.1-flash-lite).
# Defaults to YAML output: pipe is positional, so a dropped empty field shifts columns and
# silently broke ~54% of Gemini's rows on NYU. Score with the matching --target yaml.
uv run eval/gemini_baseline.py --gold data/nyu_eval.jsonl --limit 500
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_gemini.txt --target yaml \
    --save results/scores.jsonl --label gemini-3.1-flash-lite

# after a fine-tune: score the trained model into the same table (--target MUST match training).
# default sft_qwen is LoRA -> pass --base-model (the adapter's base); drop it for a merged/full checkpoint.
uv run eval/qwen_predict.py --base-model Qwen/Qwen3.5-0.8B --model <you>/city-directory-extractor-0.8b \
    --gold data/nyu_eval.jsonl --target pipe
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_qwen.txt --target pipe \
    --save results/scores.jsonl --label qwen-0.8b

# assemble the model x eval-set comparison table (commit the .md; scores.jsonl is regenerable)
python3 eval/results_table.py --out results/eval_table.md
```

## Data sources

| Source | Role | License |
|---|---|---|
| Synthetic (`synth_persons.py`) | **Training** | ours → permissive |
| [NYU NYC directories 1850–1890](https://archive.nyu.edu/handle/2451/61521) | Eval / benchmark | CC-BY-SA-**NC** ⚠ |
| [French Trade Directories](https://zenodo.org/records/8167628) | Transfer eval | open (CC) |
| [Minneapolis 1900 (DirCity)](https://github.com/adamrangwala/DirCity_Directory_Crop-out-with-Key-Lines) | In-domain US eval (silver; needs review) | MIT |
| `../directory-pipeline/output` (Tulsa 1921) | In-domain eval | ours |
| `../directory-pipeline/output` (Lain & Healy Brooklyn 1897) | In-domain eval (NYC dialect) | ours |

⚠ NYU is **non-commercial**; it is used for *evaluation only* so the released,
synthetic-trained model stays permissively reusable.

## Status

Phase 1 (schema + data + eval prep) — **complete & verified**. Every script runs and its
output is validated by the eval harness; the three eval converters were each run on real
downloaded data: `synth_persons.py` (multi-dialect synthetic), `nyu_to_eval.py` (NYC gold),
`ftd_to_eval.py` (French transfer), `harvest_own.py` (Tulsa in-domain from real OCR),
`harvest_minneapolis.py` (Minneapolis 1900 silver from real MIT transcriptions),
`train/sft_qwen.py` (TRL SFT; dry-run-verified), `eval/evaluate.py` (scoring + `--save` metrics
log; self-test passes), `eval/gliner_baseline.py` (GLiNER extractive baseline; self-test passes
+ pipe preds score through the harness), `eval/gemini_baseline.py` (Gemini "bar"; self-test
passes), `eval/results_table.py` (comparison-table builder; self-test passes), plus `cards/` templates.

**Now (Phase 2 — in progress):** establishing baselines on held-out NYU — GLiNER zero-shot
floor measured (macro-F1 0.33); Gemini bar is the next run (needs `GEMINI_API_KEY`). Then the
first fine-tune (Hugging Face token + GPU, local or `hf jobs`), fill the eval table via
`results_table.py`, and publish the model + synthetic dataset with the cards.
