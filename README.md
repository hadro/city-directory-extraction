# city-directory-extraction

One project, two halves, aimed at **extracting structured person records from historical US city
directories** and releasing the results to the community:

- **(A) The model** — fine-tune a small open model (Qwen3.5) to turn one OCR'd directory line
  into a structured 8-field record: train on synthetic data, evaluate on real hand-labeled gold,
  publish models + datasets on Hugging Face.
- **(B) The data** — everything the model trains and is judged on: a 449-volume multi-institution
  **catalog** of digitized NYC directories (~1786–1925), per-publisher×era **style profiles**,
  a hand-labeled **real-OCR gold eval panel**, and the **synthetic training-data generator** that
  the catalog work parameterizes. The catalog + profiles are also intended as a standalone
  community reference resource in their own right.

These halves are on track to become **two repos** (working names: `city-directory-data` and
`city-directory-model`). The [Layout](#layout--organized-for-the-future-split) below is grouped by
that seam, and [The future split](#the-future-split) documents the interface between them.

> This project spun out of the sibling [`directory-pipeline`](../directory-pipeline) repo, whose
> Gemini-based NER step (`pipeline/extract_entries.py`) the model aims to replace for the
> city-directory *persons* shape. The pipeline repo also hosts the page-sampler
> (`sources/sample_directories.py`) and column/spread detectors that workstream (B) relies on.
>
> **Current working state lives in the handoff docs, not in the original plan:**
> [docs/HANDOFF.md](docs/HANDOFF.md) (the model: results, gotchas, next steps),
> [docs/GROUND_TRUTH_HANDOFF.md](docs/GROUND_TRUTH_HANDOFF.md) (gold panel, labeling contract),
> [docs/VISUAL_SAMPLING_HANDOFF.md](docs/VISUAL_SAMPLING_HANDOFF.md) (catalog backfill), and
> [docs/FRONTMATTER_KEYPAGE_HANDOFF.md](docs/FRONTMATTER_KEYPAGE_HANDOFF.md) (key-page /
> listing-start / page-offset sampling). [docs/plan.md](docs/plan.md) is the original rationale
> and data landscape — read it for background, the handoffs for truth.

## Where things stand (2026-07)

**Model (A):** first full fine-tune trained, eval-loader bug fixed, and scored twice — on NYU gold
and across the whole 18-volume gold panel.

`hadro/city-dir-08b-yaml` (0.8B, 100k synthetic, 3 epochs, YAML) on NYU gold (500 rows):

| model | macro-F1 | micro-F1 | whole-row EM |
|---|---|---|---|
| GLiNER zero-shot (floor) | 0.381 | 0.594 | 8% |
| **qwen-0.8b-yaml (ours)** | **0.760** | 0.755 | 26% |
| Gemini 3.1-flash-lite (bar) | 0.672 | **0.910** | **70%** |

**Honest read:** we edge Gemini on macro-F1 (rare fields like spouse/race), but Gemini leads
micro-F1 and whole-row EM — the high-volume `name`/`address` fields and complete rows, which are
what matter for replacing it in the pipeline.

The **first full-panel run** (all 18 gold volumes, 1786–1933) sharpened that into four systematic
gaps, all *training-coverage* problems, not capacity problems (panel-wide field F1: name 0.52,
address 0.44, home_address 0.07, race 0.00):

1. **Ditto marks** — the generator never emits surname-repeat dittos (`"`/`-`), so the model strips
   them; every ditto row scores 0 on `name` → EM=0% on all dense Polk/Trow volumes. Biggest lever.
2. **`home_address`** — the two-address pattern is under-produced; the model collapses `h.` into
   `address`.
3. **Address styles** — 1930s hyphenated outer-borough house numbers (`24-12`, `LIC`/`JH`) and
   1786-era formats are out-of-distribution.
4. **`race_designation`** — never emitted (small n; clean synthetic fix).

**Conclusion: stop adding breadth; fix synthetic coverage, retrain, re-score.** The 18-volume
panel is now the regression harness. Full numbers and diagnosis in
[docs/HANDOFF.md](docs/HANDOFF.md); table in [results/eval_table.md](results/eval_table.md).

**Data (B):** `master_directories.csv` at **449 rows** (NYPL / IA / LoC; NYPL API responses
archived before the 2026-08-01 deprecation). `column_count` backfilled for **332/449** — every
in-scope residential volume. **17 publisher×era style cards** written. The gold panel stands at
**18 volumes / 1,169 hand-labeled lines** (continuous 1786–1933, layout columns 1–6, all five
boroughs, all 8 fields exercised) from a 41-volume worklist, all validator-clean. The
front-matter/key-page pass (listing `start_page`, abbreviations `key_page`, `page_offset`) is
**25/41 done**; the remaining 16 need deep scans.

**Next (in order):**
1. Inject the four missing features into `synth_persons.py` (dittos first), regenerate, retrain
   (see [Training options](#train--evaluate) — the measured cheap path is ~$6/run), re-score the
   panel; confirm the `name`/EM lift.
2. Finish the remaining 16 front-matter volumes; fold key-page legends into style profiles.
3. Parameterize per-publisher styles in the generator (Wave 1), broaden the panel, scale the
   family (0.8B/2B/4B, 500k), publish with cards.

## Scope

The target is **one NYC-comprehensive model** that parses NYC directories ~**1786–1925** across
all boroughs and publishers (Trow, Lain, Polk, Doggett, Upington, Spooner, Hearne, Longworth, …),
with **cross-city transfer measured as a stretch goal** (Tulsa 1921 and Minneapolis 1900 held
out). Tulsa stays in the mix as a second trained dialect. Telephone directories (112 cataloged)
and business/copartnership directories are out of scope — cataloged as future separate tracks.

## The schema — the contract between the halves

Everything flows through one **union schema (8 fields)**:

`name · is_business · spouse_name · race_designation · occupation_role · employer · address · home_address`

plus a serialization rule — **YAML, not pipe** (pipe is positional; a dropped field column-shifts
the rest; measured ~54% row breakage) — and a fixed **gold/synth/model labeling contract**
(`raw_line` = verbatim page including OCR quirks; the 8 fields = canonical values; ~17 conventions
covering dittos, widows, race marks, parenthetical firms…). The conventions live in
[docs/GROUND_TRUTH_HANDOFF.md](docs/GROUND_TRUTH_HANDOFF.md) and are what will keep two repos
honest with each other after the split.

## Layout — organized for the future split

```
# ──────────────── future repo 1: city-directory-data ────────────────
# gathering, profiling, gold labeling, training-data generation
data_prep/
  # catalog (the 449-volume master list)
  master_directories.csv        # multi-source (nypl|ia|loc|iiif) catalog; schema in its README
  master_directories.README.md  # catalog schema + provenance log + leads
  ingest_collection.py          # collection link -> staged rows (review-then-append); nypl/ia/loc/iiif
  nypl_api_archive/             # 155+ MODS JSONs (NYPL API deprecates 2026-08-01) — committed
  # visual sampling + style profiles
  inspect_frontmatter.py        # IIIF -> cached front-matter pages + contact sheets (key-page pass)
  trow_fanout_prep.py / trow_fanout.workflow.js  # gated cheap-tier fan-out for metadata backfill
  style_profiles/               # 17 per-publisher×era cards (.md) + style_profiles.json
  # real-OCR gold eval panel (hand-labeled; see GROUND_TRUTH_HANDOFF.md)
  sample_volumes.py             # stratified selector -> gold_sample/{worklist.csv,WORKLIST.md}
  run_surya_on_samples.py       # batch Surya OCR over worklist dirs (listing-only; resumable)
  make_gold_tool.py             # self-contained HTML labeling editor from Surya JSON
  validate_gold.py              # QA: ERRORS (break evaluate.py) + WARNINGS (convention slips)
  gold_sample/                  # 41-volume worklist + labeling checklist
  # training data: synthetic generator + name pools
  synth_persons.py              # (line -> record) generator; --profile {tulsa,nyc,mix}
  fetch_names.py                # build names/surnames.tsv (40k era-skewed census surnames)
  harvest_names.py              # pipeline entries CSVs -> harvested real-surname pool
  names/surnames.tsv            # committed census pool (harvested pool is generated, gitignored)
  # eval-set builders (external gold -> union schema)
  nyu_to_eval.py                # NYU NDJSON -> held-out NYC gold (EVAL ONLY, CC-BY-SA-NC)
  ftd_to_eval.py                # French Trade Directories -> cross-lingual transfer eval
  harvest_own.py                # pipeline output -> in-domain eval (Tulsa + Lain; real OCR)
  harvest_minneapolis.py        # Minneapolis 1900 (MIT) -> union-schema SILVER eval

# ──────────────── future repo 2: city-directory-model ────────────────
# training, evaluation, publishing
train/
  sft_qwen.py             # TRL SFT; --target pipe|yaml, LoRA/--qlora/--full, --packing, --dry-run
  sft_unsloth_smoke.py    # Unsloth speed probe (kept for the record; not worth it at 0.8B)
eval/
  evaluate.py             # field-level P/R/F1/EM; --save/--label; --self-test
  gliner_baseline.py      # zero-shot GLiNER extractive baseline (the floor)
  gemini_baseline.py      # Gemini baseline (the bar); defaults --target yaml
  qwen_predict.py         # fine-tuned Qwen -> preds; loads the MULTIMODAL class (see gotchas)
  results_table.py        # results/scores.jsonl -> model × eval-set Markdown table
notebooks/colab_finetune.ipynb  # free-Colab T4 fine-tune -> push to Hub
cards/                    # MODEL_CARD.md + DATASET_CARD.md templates
results/                  # eval_table.md (tracked); scores.jsonl log (gitignored, regenerable)

# ──────────────── shared ────────────────
data/                     # gitignored: downloads + generated sets (the interface artifacts)
docs/                     # handoffs (per-workstream), plan.md, BLOG_NOTES.md
```

## The future split

The seam is **datasets**: repo 1 *produces* JSONL datasets (synthetic train, gold eval panel,
external eval sets), repo 2 *consumes* them and produces models + scores. They already exchange
nothing else — locally via `data/*.jsonl`, remotely via the HF datasets
(`hadro/city-directory-synth`, `hadro/cde-evals`).

What has to stay in sync across the split (flag these in both READMEs when it happens):

- **The 8-field schema + YAML serialization** — baked into `synth_persons.py` and
  `validate_gold.py` (repo 1) and `evaluate.py` / the train-prompt in `sft_qwen.py` /
  `gemini_baseline.py` (repo 2). Extract the field list + (de)serializers into one tiny shared
  module (or versioned schema file) at split time.
- **The labeling contract** (GROUND_TRUTH_HANDOFF conventions) — authored on the data side,
  binding on the model side.
- **Eval held-outs** — NYU Trow 1850/51 and Lain Brooklyn 1897 must stay out of repo 1's
  sampling/harvesting (they're `REVIEW:`-flagged in the catalog).
- The sibling `directory-pipeline` repo remains a dependency of repo 1 only (page sampler, OCR).

## Quickstart (synthetic data)

```bash
# eyeball a sample (default profile = mix of both dialects)
python3 data_prep/synth_persons.py --n 8 --preview
python3 data_prep/synth_persons.py --n 8 --preview --profile nyc    # or --profile tulsa

# generate a mixed training set
python3 data_prep/synth_persons.py --n 100000 --out data/synth_train.jsonl --seed 13
```

Each JSONL row is `{raw_line, context:{publisher, alphabetical_range, directory_year},
record:{…8 fields…}}`. `raw_line` carries optional OCR noise (the model input); `record` is the
clean target; `context` is page-level metadata fed in the prompt rather than predicted — the
prompt tag is `[publisher=trow; year=1913/14]` (`dialect` retired 2026-07-19; the tulsa profile
tags `publisher=polk`, the same Polk as late-NYC volumes). Names
draw from 40k census surnames + harvested real-name pools (the original inline ~54-surname list
was the documented root cause of the model regularizing unseen surnames).

## Train & evaluate

All scripts are PEP-723 self-contained; each has `--self-test`, `--preview`, or `--dry-run`.
Train AND eval with the **same `--target`** (yaml) and the **same model class** (see gotchas in
[docs/HANDOFF.md](docs/HANDOFF.md) — the eval-loader bug cost us several runs).

```bash
# 0) inspect the exact SFT examples (--preview-prompts is stdlib-only; --dry-run needs the
#    ML deps, so run it under uv, and --train-file is required either way)
python3 train/sft_qwen.py --train-file data/synth_train.jsonl --preview-prompts 4
uv run train/sft_qwen.py --train-file data/synth_train.jsonl --dry-run   # verify: 0 visual adapters

# 1) build eval sets (all map into the same 8-field schema)
python3 data_prep/nyu_to_eval.py  --in data/1850.ndjson --out data/nyu_eval.jsonl --limit 3000
python3 data_prep/ftd_to_eval.py  --in data/ftd.json    --out data/ftd_eval.jsonl
python3 data_prep/harvest_own.py  --dir ../directory-pipeline/output/tulsa_1921 --out data/tulsa_eval.jsonl
python3 data_prep/harvest_minneapolis.py --dir data/minneapolis/ground_truth --out data/minneapolis_eval.jsonl

# 2) fine-tune. Cheapest measured cloud path: HF Jobs rtx-pro-6000, batch 64, --packing (~$6 for
#    0.8B/100k×3). Free/cheap alternatives (Colab T4 notebook, Kaggle, local MLX): docs/TRAINING_OPTIONS.md
python3 train/sft_qwen.py --train-file data/synth_train.jsonl --target yaml --packing \
    --model Qwen/Qwen3.5-0.8B --hub-model-id <you>/city-directory-extractor-0.8b --push-to-hub

# 3) baselines and the fine-tuned model -> preds; score everything into one table
uv run eval/gliner_baseline.py --gold data/nyu_eval.jsonl                       # the floor
uv run eval/gemini_baseline.py --gold data/nyu_eval.jsonl --limit 500           # the bar (GEMINI_API_KEY)
uv run eval/qwen_predict.py --base-model Qwen/Qwen3.5-0.8B --model <you>/city-directory-extractor-0.8b \
    --gold data/nyu_eval.jsonl --target yaml                                    # ours (check: NO "missing adapter keys")
python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_qwen.txt --target yaml \
    --save results/scores.jsonl --label qwen-0.8b
python3 eval/results_table.py --out results/eval_table.md
```

## The catalog & style profiles (workstream B)

`data_prep/master_directories.csv` is a 449-row, multi-institution catalog of digitized NYC city
directories, built by throwing collection **links** at `ingest_collection.py` (detects
`nypl`/`ia`/`loc`/`iiif` sources, stages rows for review, appends on `--merge`). NYPL API
responses are archived under `nypl_api_archive/` because that API deprecates **2026-08-01**. The
sibling `directory-pipeline/sources/sample_directories.py` resolves each row to a IIIF manifest
and downloads **only** a few sampled pages per volume (never whole volumes).

From those samples we build **style profiles** (`data_prep/style_profiles/`): 17 per-publisher×era
cards capturing column count, the abbreviations legend (ground truth), entry format, and
page-offset behavior. They backfill structural metadata in the catalog (`column_count` 332/449;
`start_page`/`key_page`/`page_offset` 25/41 on the gold panel) **and** are the lever to
parameterize `synth_persons.py` so synthetic lines match real layout and abbreviations.

Workflow, per-cohort logs, and gotchas (microfilm spreads, page-offset drift, phonebook-vs-city
genre, cheap-tier sub-agent delegation):
[docs/VISUAL_SAMPLING_HANDOFF.md](docs/VISUAL_SAMPLING_HANDOFF.md) and
[docs/FRONTMATTER_KEYPAGE_HANDOFF.md](docs/FRONTMATTER_KEYPAGE_HANDOFF.md).

### Real-OCR gold eval panel

A hand-labeled **gold eval panel** built from the cataloged volumes via a dedicated toolchain
(`sample_volumes.py` → `run_surya_on_samples.py` → `make_gold_tool.py` → `validate_gold.py`):
Surya-OCR a few listing pages per volume, label each entry into the 8-field schema in a browser
editor, validate, drop the result into `data/<slug>_eval.jsonl` for `eval/evaluate.py`. It is
**eval-only** and governed by the labeling contract. Status: **18 volumes / 1,169 lines**, all
validator-clean. Conventions + per-volume log:
[docs/GROUND_TRUTH_HANDOFF.md](docs/GROUND_TRUTH_HANDOFF.md).

## Data sources

| Source | Role | License |
|---|---|---|
| Synthetic (`synth_persons.py`) | **Training** | ours → permissive |
| Real-OCR gold panel (18 vols, ours) | Eval / regression harness | ours |
| [NYU NYC directories 1850–1890](https://archive.nyu.edu/handle/2451/61521) | Eval / benchmark | CC-BY-SA-**NC** ⚠ |
| [French Trade Directories](https://zenodo.org/records/8167628) | Transfer eval | open (CC) |
| [Minneapolis 1900 (DirCity)](https://github.com/adamrangwala/DirCity_Directory_Crop-out-with-Key-Lines) | In-domain US eval (silver) | MIT |
| `../directory-pipeline/output` (Tulsa 1921, Lain Brooklyn 1897) | In-domain eval | ours |
| `master_directories.csv` + `nypl_api_archive/` + `style_profiles/` | **Catalog (B)**; sampling source + standalone resource | NYPL/IA/LoC metadata; cards ours |

⚠ NYU is **non-commercial**; it is used for *evaluation only* so the released, synthetic-trained
model stays permissively reusable. Eval-held-out volumes (NYU Trow Manhattan 1850/51, Lain
Brooklyn 1897) are kept OUT of the sampling/harvest set and `REVIEW:`-flagged in the catalog.

## Hugging Face resources (namespace `hadro`)

- `hadro/city-directory-synth` — synthetic train (100k) + smoke (3k). PUBLIC.
- `hadro/cde-evals` — NYU + synth-dev eval sets + preds. PRIVATE (respects NYU CC-BY-SA-NC).
- `hadro/city-dir-08b-yaml` — the good 0.8B run (see Status). Earlier runs documented in the handoff.
