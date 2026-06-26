# city-directory-extraction

Two linked workstreams aimed at **extracting structured person records from historical city
directories** and releasing the results to the community:

- **(A) The model** — fine-tune a small open model (Qwen3.5) to turn one OCR'd directory line
  into a structured 8-field record, train synthetic / eval on real gold, and publish models +
  datasets on Hugging Face.
- **(B) The NYC directory catalog** — a multi-institution catalog of digitized NYC city
  directories (~1786–1925) plus per-publisher×era **style profiles** distilled from visual
  sampling. It feeds the generator in (A) **and** is intended as a standalone community
  reference resource in its own right.

> This is the focused fine-tuning project spun out of the sibling
> [`directory-pipeline`](../directory-pipeline) repo, whose Gemini-based NER step
> (`pipeline/extract_entries.py`) the model aims to replace for the city-directory *persons*
> shape. The directory-pipeline repo also hosts the page-sampler and column/spread detectors
> that workstream (B) relies on.
>
> **Current working state lives in the handoff docs, not in the original plan:**
> [docs/HANDOFF.md](docs/HANDOFF.md) (the model),
> [docs/GROUND_TRUTH_HANDOFF.md](docs/GROUND_TRUTH_HANDOFF.md) (the real-OCR gold eval panel,
> labeling conventions, gold toolchain, and style profiles), and
> [docs/VISUAL_SAMPLING_HANDOFF.md](docs/VISUAL_SAMPLING_HANDOFF.md) (the catalog backfill it grew
> out of). The [docs/plan.md](docs/plan.md) is the original rationale and data landscape, but
> predates the scope changes below — read it for background, the handoffs for truth.

## Scope (current)

The target is **one NYC-comprehensive model** that parses NYC directories ~**1786–1925** across
all boroughs and publishers (Trow, Lain, Polk, Doggett, Upington, Spooner, Hearne, Longworth, …),
with **cross-city transfer measured as a stretch goal** (Tulsa 1921 and Minneapolis 1900 held
out). This is a reframe from the project's origin as two fixed dialects (Tulsa 1921 + NYC
Trow/Doggett 1850–1890); Tulsa stays in the mix as a second trained dialect and doubles as a
held-out transfer test.

**Union schema (8 fields):** `name · is_business · spouse_name · race_designation ·
occupation_role · employer · address · home_address`.

## Approach in one paragraph

Train **synthetic-first** (license-clean, ours to release) on directory-style lines, then
**evaluate on real gold** (NYU NYC 1850–1890, French Trade Directories, Minneapolis 1900, and our
own reviewed pages). Fine-tune the small **Qwen3.5** family (0.8B/2B/4B) with TRL SFT, run it on
**HF Jobs**, emit **YAML** (not pipe — see "Key decisions" in the handoff: pipe is positional and
column-shifts on a dropped field), and publish models + datasets with proper cards. Modeled on
Mattingly's "3.6M names" and van Strien's `small-models-for-glam/index-card-extractor`. The lever
for closing the synthetic→real gap is workstream (B): real names + real layout/abbreviation styles
harvested from the cataloged volumes, folded back into the generator.

## Layout

```
data_prep/
  # --- workstream A: generator + eval-set builders + name pools ---
  synth_persons.py        # ✅ (line -> record) generator; --profile {tulsa,nyc,mix} --target --n --seed
  fetch_names.py          # ✅ build names/surnames.tsv (40k era-skewed US-Census surnames)
  harvest_names.py        # ✅ pipeline entries CSVs -> real harvested surname pool (folded into generator)
  names/surnames.tsv      # ✅ committed census surname pool (surnames_harvested.tsv is generated, gitignored)
  nyu_to_eval.py          # ✅ NYU NDJSON -> held-out NYC gold (verbatim labels, score-gated)
  ftd_to_eval.py          # ✅ French Trade Directories (SODUCO) -> cross-lingual transfer eval
  harvest_own.py          # ✅ pipeline output -> in-domain eval (Tulsa + Lain; --dialect; real OCR)
  harvest_minneapolis.py  # ✅ Minneapolis 1900 (MIT) transcription -> union-schema SILVER eval (review)
  # --- real-OCR GOLD eval panel (hand-labeled; see GROUND_TRUTH_HANDOFF.md) ---
  sample_volumes.py       # ✅ stratified selector -> gold_sample/{worklist.csv,WORKLIST.md} (42 reps)
  run_surya_on_samples.py # ✅ batch Surya OCR over worklist dirs (gpu env; listing-only; resumable)
  make_gold_tool.py       # ✅ build self-contained HTML labeling editor from Surya JSON (autosave/import; --max-lines)
  validate_gold.py        # ✅ QA the export: ERRORS (break evaluate.py) + WARNINGS (drift/convention slips)
  gold_sample/            # ✅ worklist.csv (subset of master) + WORKLIST.md checklist
  # --- workstream B: NYC directory catalog + style profiles ---
  master_directories.csv  # ✅ 449-row multi-source (nypl|ia|loc|iiif) catalog; schema in its README
  master_directories.README.md  # ✅ catalog schema + provenance log + leads
  ingest_collection.py    # ✅ collection link -> staged master rows (review-then-append); nypl/ia/loc/iiif
  nypl_api_archive/        # ✅ 155 MODS JSONs + collection JSON (NYPL API deprecates 2026-08-01) — committed
  style_profiles/          # ✅ per-publisher×era style cards (.md) + machine-readable style_profiles.json
  trow_fanout_prep.py / trow_fanout.workflow.js  # ✅ gated cheap-tier fan-out for visual metadata backfill
train/
  sft_qwen.py             # ✅ TRL SFT; --target pipe|yaml, LoRA/--qlora/--full, --packing, --dry-run
  sft_unsloth_smoke.py    # ✅ Unsloth speed probe (kept for the record; not worth it at 0.8B — see handoff)
eval/
  evaluate.py             # ✅ field-level P/R/F1/EM; --target; --save <jsonl> --label; --self-test
  gliner_baseline.py      # ✅ zero-shot GLiNER (urchade) extractive baseline -> preds (+ --self-test)
  gemini_baseline.py      # ✅ Gemini baseline (the "bar"); defaults --target yaml (+ --self-test)
  qwen_predict.py         # ✅ run fine-tuned Qwen -> preds; loads multimodal class; remote hf:// + --push-out
  results_table.py        # ✅ pivot results/scores.jsonl -> model × eval-set Markdown table (+ --self-test)
notebooks/colab_finetune.ipynb  # ✅ free-Colab T4 fine-tune -> push to Hub
cards/                    # ✅ MODEL_CARD.md + DATASET_CARD.md templates
results/                  # eval_table.md (tracked); scores.jsonl log is gitignored (regenerable)
data/                     # gitignored: downloads + generated sets
docs/                     # HANDOFF.md, VISUAL_SAMPLING_HANDOFF.md, plan.md, BLOG_NOTES.md
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
address, home_address}}`. `raw_line` carries optional OCR noise (the model input); `record` is the
clean target; `context` is page-level metadata fed in the prompt rather than predicted. Names are
drawn from the census (40k) + harvested real-name pools (was an inline ~54-surname list — the
documented root cause of the model regularizing unseen surnames).

## Train & evaluate

```bash
# 0) inspect the exact SFT examples (stdlib only — no ML deps)
python3 train/sft_qwen.py --train-file data/synth_train.jsonl --preview-prompts 4
python3 train/sft_qwen.py --dry-run    # CPU/free: prints which modules get LoRA adapters

# 1) build eval sets (all map into the same 8-field schema)
python3 data_prep/nyu_to_eval.py  --in data/1850.ndjson --out data/nyu_eval.jsonl --limit 3000   # NYC gold (EVAL ONLY, CC-BY-SA-NC)
python3 data_prep/ftd_to_eval.py  --in data/ftd.json    --out data/ftd_eval.jsonl                # French cross-lingual transfer
python3 data_prep/harvest_own.py  --dir ../directory-pipeline/output/tulsa_1921 --out data/tulsa_eval.jsonl  # in-domain (real OCR)
python3 data_prep/harvest_minneapolis.py --dir data/minneapolis/ground_truth --out data/minneapolis_eval.jsonl  # US silver eval (MIT; review)

# 2) fine-tune a small Qwen3.5 — FREE on a Colab/Kaggle T4 (see notebooks/colab_finetune.ipynb),
#    or local GPU, or `hf jobs uv run <local_script.py>`. Train AND eval with the SAME --target.
#    Best value GPU: rtx-pro-6000 batch 64 + --packing (~$6 for 0.8B/100k×3). See handoff "Training speed".
python3 train/sft_qwen.py --train-file data/synth_train.jsonl --target yaml --packing \
    --model Qwen/Qwen3.5-0.8B --hub-model-id <you>/city-directory-extractor-0.8b --push-to-hub

# 3) score predictions against gold (one serialized row per gold line, same order; --target MUST match training)
python3 eval/evaluate.py --gold data/synth_dev.jsonl --self-test   # sanity-check the harness

# baselines -> pipe/yaml preds; --save logs metrics per run
uv run eval/gliner_baseline.py --gold data/nyu_eval.jsonl                 # extractive floor
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_gliner.txt \
    --save results/scores.jsonl --label gliner

# bar: Gemini, SAME lines/schema/prompt (needs GEMINI_API_KEY; default gemini-3.1-flash-lite, YAML).
uv run eval/gemini_baseline.py --gold data/nyu_eval.jsonl --limit 500
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_gemini.txt --target yaml \
    --save results/scores.jsonl --label gemini-3.1-flash-lite

# the fine-tuned model: qwen_predict loads the multimodal class (verify NO "missing adapter keys" warning).
# default sft_qwen is LoRA -> pass --base-model (the adapter's base); drop it for a merged/full checkpoint.
uv run eval/qwen_predict.py --base-model Qwen/Qwen3.5-0.8B --model <you>/city-directory-extractor-0.8b \
    --gold data/nyu_eval.jsonl --target yaml
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_qwen.txt --target yaml \
    --save results/scores.jsonl --label qwen-0.8b

# assemble the model x eval-set comparison table (commit the .md; scores.jsonl is regenerable)
python3 eval/results_table.py --out results/eval_table.md
```

## The NYC directory catalog (workstream B)

`data_prep/master_directories.csv` is a 449-row, multi-institution catalog of digitized NYC city
directories, built by throwing collection **links** at `ingest_collection.py` (which detects
`nypl` / `ia` / `loc` / `iiif` sources, stages rows to a pending file for review, then appends on
`--merge`). The NYPL API responses are archived under `nypl_api_archive/` because that API
deprecates **2026-08-01**. The sibling `directory-pipeline/sources/sample_directories.py` reads
this catalog, resolves each row to a IIIF manifest, and downloads **only** a few sampled pages per
volume (never whole volumes).

From those visual samples we build **style profiles** (`data_prep/style_profiles/*.md` +
`style_profiles.json`): per-publisher×era cards capturing column count, the abbreviations legend
(ground truth), entry format, and page-offset behavior. These backfill structural metadata in the
catalog (`column_count` is ~332/449 done) **and** are the Phase-2 lever to parameterize
`synth_persons.py` so synthetic lines match real layout/abbreviations.

See [docs/VISUAL_SAMPLING_HANDOFF.md](docs/VISUAL_SAMPLING_HANDOFF.md) for the full catalog-backfill
workflow, the per-cohort log, and the hard-won gotchas (microfilm spreads, page-offset drift,
phonebook vs city-directory genre, cheap-tier sub-agent delegation with arithmetic gating).

### Real-OCR gold eval panel

A separate, hand-labeled **gold eval panel** is built from the cataloged volumes via a dedicated
toolchain (`sample_volumes.py` → `run_surya_on_samples.py` → `make_gold_tool.py` → `validate_gold.py`):
Surya-OCR a few listing pages per volume, label each entry into the 8-field schema in a browser
editor, validate, and drop the result into `data/<slug>_eval.jsonl`. It is **eval-only**, governed by
a fixed gold/synth/model labeling **contract** (raw_line = verbatim page; the 8 fields = canonical),
and consumed directly by `eval/evaluate.py`. The labeling conventions (~16 rules — verbatim,
no-field-commas, widows, race/district marks, surname-dash dittos, parenthetical firm/principal,
drop-what-has-no-field…) and the panel status live in
[docs/GROUND_TRUTH_HANDOFF.md](docs/GROUND_TRUTH_HANDOFF.md).

## Data sources

| Source | Role | License |
|---|---|---|
| Synthetic (`synth_persons.py`) | **Training** | ours → permissive |
| [NYU NYC directories 1850–1890](https://archive.nyu.edu/handle/2451/61521) | Eval / benchmark | CC-BY-SA-**NC** ⚠ |
| [French Trade Directories](https://zenodo.org/records/8167628) | Transfer eval | open (CC) |
| [Minneapolis 1900 (DirCity)](https://github.com/adamrangwala/DirCity_Directory_Crop-out-with-Key-Lines) | In-domain US eval (silver; needs review) | MIT |
| `../directory-pipeline/output` (Tulsa 1921) | In-domain eval | ours |
| `../directory-pipeline/output` (Lain & Healy Brooklyn 1897) | In-domain eval (NYC dialect) | ours |
| `master_directories.csv` + `nypl_api_archive/` + `style_profiles/` | **Catalog (workstream B)**; sampling source + intended standalone resource | NYPL/IA/LoC metadata; cards ours |

⚠ NYU is **non-commercial**; it is used for *evaluation only* so the released, synthetic-trained
model stays permissively reusable. Eval-held-out volumes (NYU Trow Manhattan 1850/51, Lain
Brooklyn 1897) are kept OUT of the sampling/harvest set and `REVIEW:`-flagged in the catalog.

## Status

**Workstream A (model):** First full fine-tune done and measured. `hadro/city-dir-08b-yaml`
(0.8B, 100k synthetic, 3 epochs, YAML) scores on NYU gold (500 rows):

| model | macro-F1 | micro-F1 | whole-row EM |
|---|---|---|---|
| GLiNER zero-shot (floor) | 0.381 | 0.594 | 8% |
| **qwen-0.8b-yaml (ours)** | **0.760** | 0.755 | 26% |
| Gemini 3.1-flash-lite (bar) | 0.672 | **0.910** | **70%** |

**Honest read:** we edge Gemini on macro-F1 (we do relatively better on *rare* fields like
spouse/race), but **Gemini still leads on micro-F1 and whole-row EM** — the high-volume
`name`/`address` fields and complete-row correctness, which are what matter for replacing Gemini
in the pipeline. The remaining gap is concentrated in `name` (the model regularizes unseen
surnames). The fix — real census + harvested name pools — is built and committed; the lift is
awaiting a regenerate + retrain. *(An earlier eval-loader bug made the trained model score at the
base-model floor; root-caused and fixed — see the handoff. Symptom: a trained model scoring like
an untrained one.)*

**Workstream B (catalog + gold):** `master_directories.csv` grown to 449 rows across NYPL/IA/LoC;
NYPL API archived; ~332/449 rows have `column_count` (every in-scope residential volume); 13
publisher×era style cards written. The **real-OCR gold eval panel is underway: 14 volumes / ~890
hand-labeled lines** (continuous 1786–1925, layout col 1→6, all 8 fields exercised incl. race &
employer), all validator-clean — see [docs/GROUND_TRUTH_HANDOFF.md](docs/GROUND_TRUTH_HANDOFF.md).
Phase 2 (style profiles → generator → retrain → re-eval on this gold) is the next integration point
with workstream A.

**Next:** regenerate synthetic data with the real-name pools + a publisher/era context tag,
retrain on `rtx-pro-6000` batch 64 + `--packing` (~$6), re-run the eval panel, and confirm the
`name` / whole-row-EM lift (especially on Lain). Then parameterize per-publisher styles, broaden
the real eval panel, scale the family, and publish models + datasets with the cards. Full
step-by-step in [docs/HANDOFF.md](docs/HANDOFF.md).

## Hugging Face resources (namespace `hadro`)

- `hadro/city-directory-synth` — synthetic train (100k) + smoke (3k). PUBLIC.
- `hadro/cde-evals` — NYU + synth-dev eval sets + preds. PRIVATE (respects NYU CC-BY-SA-NC).
- `hadro/city-dir-08b-yaml` — the good 0.8B run (see Status). Earlier runs documented in the handoff.
</content>
</invoke>
