# Plan: Fine-tune & release a city-directory structured-extraction model

> Project plan for this repo. File paths written as `directory-pipeline/…` live in the
> sibling **directory-pipeline** repo (the IIIF/OCR/Gemini pipeline this project draws data
> and code from), not here. A working copy of this plan is also kept under `~/.claude/plans/`.

## Context — why this work

You currently extract structured records from historical directories with Gemini
(`directory-pipeline/pipeline/extract_entries.py`). You want to (1) move off Gemini for the
NER step **at scale**, and (2) release a fine-tuned model **and** its training/eval datasets
to the community on Hugging Face. The sibling directory-pipeline repo already has a Phase-0
decision doc (`directory-pipeline/docs/huggingface-uv-scripts.md`) that treats fine-tuning
as a "Phase 4 scale path." This plan **elevates that Phase 4 into its own focused project**
and adds the two things that doc lacks: an external gold-data landscape, and a
learn-it-then-do-it execution path aimed at a public release.

This is closely modeled on two proven precedents in *exactly* your domain:
- **Mattingly, "Parsing 3.6M historical names with small models"** — fine-tuned small
  Qwen3.5 (0.8B/2B/4B) on **synthetic** data, text→structured, **94–96%**, beating frontier
  models on cost/speed/accuracy at volume. Output format mattered as much as model size.
- **van Strien, `small-models-for-glam/index-card-extractor-4b`** — fine-tuned an open model
  for record→structured extraction, trained + published via **HF Jobs**, with the
  "patterns" you linked describing bootstrapping data, eval discipline, and community release.

### Decisions locked (from your answers)
- **First model:** text → structured (NER). Keep Surya/Chandra/Gemini for OCR; fine-tune
  only the OCR-text → structured-record step. Smallest, cheapest, most data, gentlest learning curve.
- **Entry shape:** **city-directory persons** across two real dialects — **Tulsa 1921** and
  **NYC Trow/Doggett 1850–1890** — modeled with one union schema (name · is_business · spouse ·
  race · occupation · employer · address · home_address). This is the "on-brand" directory
  shape and the one with real external gold.
- **Home:** a **new public repo** for code; datasets + models published to **Hugging Face**
  (start in your personal namespace; optionally upstream to `small-models-for-glam` later).

---

## The data landscape (answering "what else is out there?")

| Source | What it is | Format | License | Role here |
|---|---|---|---|---|
| **NYU — NYC City Directories Extracted Persons, 1850–1890** ([handle](https://archive.nyu.edu/handle/2451/61521)) | Wolf/Chioh/Balogh/Spaan, 2020. Millions of persons entries from Doggett's + Trow's directories | **NDJSON** (name, occupation, work addr, home addr/hometown), 40 annual files, 585 MB | **CC-BY-SA-NC 4.0** (⚠ non-commercial + share-alike) | **Primary real eval/benchmark**; optional license-tagged augmentation |
| **French Trade Directories (FTD)** ([source v1](https://doi.org/10.5281/zenodo.6394464), [nested-NER benchmark](https://zenodo.org/records/8167628), [paper 2302.10204](https://arxiv.org/abs/2302.10204)) | 19th-c. Paris directories: **page images + transcriptions + nested-entity annotations** (8,765 entries / 78 pages); same person/company→activity→address shape | Images + text + IOB/nested NER + models | Open (CC, per Zenodo records) | **Transfer/generalization eval**; methodology reference (true image+layout gold) |
| **Minneapolis 1900** ([adamrangwala/DirCity](https://github.com/adamrangwala/DirCity_Directory_Crop-out-with-Key-Lines)) | OCR **transcription** gold for the 1900 Minneapolis directory (~832 lines / 10 pages) + page images. Its empty annotation scaffold (`*_enhanced_template.json`) independently converges on ~our schema | line `.txt` transcriptions (no parsed records yet) | **MIT** (permissive) | **New US dialect/era** (3rd, between NYC & Tulsa); → union-schema **silver** eval via `harvest_minneapolis.py` (needs review). Permissive + has page images → cleanest seed for the image-paired US benchmark |
| **NYPL "Million-Record NYC City Directories"** (project behind the NYU set) | hOCR → structured JSON pipeline + meetup notes | hOCR/JSON | Open | Reference design for parsing directory lines |
| **`small-models-for-glam`** ([org](https://huggingface.co/small-models-for-glam)) | `Qwen3.5-{0.8B,2B,4B}-SFT-name-parser-yaml` + `synthetic-parsed-names-yaml` (500k) + `index-card-extractor-4b` | HF models + datasets | Open | **Closest reusable blueprints** + upstream target |
| **`biglam`** ([org](https://huggingface.co/biglam)) | Adjacent structured-record sets: `bpl-card-catalog` (838k), `rubenstein-manuscript-catalog`, `index-cards-*` | HF datasets | Open | Adjacent task patterns; community alignment |
| **Your own `directory-pipeline/output/`** | Green Book (~331k entries) + Woods + **Tulsa 1921 city directory** | CSV + aligned JSON + IIIF bboxes | Yours | **Tulsa = real in-domain persons eval** (image-paired via `canvas_fragment`); Green Book is establishments (out of scope for model #1) |
| Method refs | [arXiv 2504.00414](https://arxiv.org/html/2504.00414) (multimodal LLMs for OCR/post-correction/NER in historical docs); [cneud OCR-GT list](https://cneud.github.io/ocr-gt/) | — | — | Benchmark/method context |

**Key gap = your opportunity:** there is no widely-known **US** city-directory dataset that
pairs page *images* with structured records as gold (NYU is text-derived; FTD is French).
Your pipeline produces per-entry IIIF bounding boxes, so reviewing your own pages can create
a genuinely novel image-paired US-directory benchmark — a strong community contribution.
(The MIT Minneapolis 1900 set above is the closest external prior art — US page images +
transcriptions — but it ships *no* structured records, only OCR text, so it underlines rather
than closes the gap.)

### External sources evaluated (June 2026)

Four candidate gold sources were reviewed; only one is net-new and on-target:
- **Minneapolis 1900** (`adamrangwala/DirCity`) — **the one worth using.** US, MIT, a 3rd
  dialect; ships OCR-transcription gold only (no parsed records), so `harvest_minneapolis.py`
  parses it into the union schema as **silver** for review. Its annotation scaffold
  independently converges on ~our schema (surname/first/spouse/home_address/residence-code/
  occupation/employer) — a nice external validation of the schema.
- **`soduco/dataset_french_trade_directories_19_century`** — the GitHub home of the FTD set we
  **already use**. Same data; the only extra is the image + cropped-entry + **bounding-box**
  layer (Zenodo 6394464) vs the text-only nested-NER JSON (Zenodo 8167628) that `ftd_to_eval.py`
  pulls. Useful only for a future multimodal/layout eval, not the current text→record model.
- **`github.com/soduco`** (org) — all Paris/French: FTD + map-vectorization/cadastre/geocoding.
  No US data and no new directory-NER gold; `processor-ner` is a minor method reference only.
- **geographie-cites, "geocoding Paris directories 1787–1914"** — ~23M records, but they are the
  *automated pipeline output* (silver), French, and geocoding-shaped — not hand gold. Cite as
  method; don't ingest. The hand gold from this lineage is the FTD 8,765 entries we already score on.

### Pending pipeline runs (Josh — to unlock more Brooklyn eval data)

Two `directory-pipeline/output` collections need their pipeline runs finished before they can
become extra real eval sets (both NYC-dialect, different publishers/years from NYU & Tulsa):

- **Hearne's Brooklyn 1852** (`output/hearnes_brooklyn_city_directory_for_hearnesbrooklync1852/hearnesbrooklync1852unse`)
  — 584 pages already OCR'd + aligned, but **NER not run**. Finish with `pipeline extract` to get an
  entries CSV, then `harvest_own.py` builds an in-domain 1852 eval (contemporaneous with the NYU era).
- **Lain's Brooklyn Street Directory & Buyer's Guide** (`output/lain_s_brooklyn_street_directory_and_buy_ldpd_11290437_000`)
  — **275 images downloaded only; OCR + align + extract not run.** Finish the full pipeline first.
  (A street/buyers directory — by-address shape — so a different schema than the persons model.)

(Lain & Healy's Brooklyn **1897** personal directory is already OCR'd + extracted and is wired into
`harvest_own.py` as a ready third real eval set.)

---

## Recommended approach

### 1. Data strategy — synthetic-first, real-gold-eval (the license-clean play)
Mattingly's decisive move was training on **synthetic** data, which (a) sidesteps source
licensing, (b) gives unlimited, balanced, noise-injectable examples, and (c) is itself
releasable under a permissive license. Adopt this:

- **Train primarily on synthetic** directory lines → records. Build a generator with a
  custom period/locale provider (19th-c. occupations, street abbreviations like
  "h.", "bds.", "r.", "cor.", OCR noise: `rn↔m`, `l↔1`, `O↔0`, broken hyphenation). This is
  the analog of Mattingly's `CulturalHeritageProvider`. **You own it → release as CC-BY/Apache.**
- **Evaluate on real gold:** NYU NYC (held-out), FTD (cross-lingual transfer), and your own
  reviewed **Tulsa** pages (real-image, in-the-wild).
- **Optional augmentation** with a license-tagged slice of NYU pairs — but keep the permissive,
  synthetic-only model as the primary community artifact to avoid CC-NC contamination.
- **NYU pairs (resolved):** the NYU NDJSON carries `complete_entry` (raw OCR line) +
  `labeled_entry`/`corrected_entry` (parsed subjects/occupations/locations) — ready-made
  (line→record) eval pairs. Map locations to the union schema: `h`-labeled → `home_address`,
  primary/unlabeled → `address`; `labeled_widow`/`labeled_black` → spouse/race markers.

### 2. Output format — avoid JSON
Small models break strict JSON (it's *why* `extract_entries.py` needs `_recover_partial_json()`).
Persons records are flat (≤6 fields), so lead with **pipe-delimited rows** (matches the CSV
deliverable, fewest tokens) and **A/B against YAML** (Mattingly's proven choice) in Phase 1.
Pick the winner on parse-failure rate.

> **Measured (NYU 500, gemini-3.1-flash-lite, Jun 2026):** pipe is *positional*, so a model that
> omits an empty field column-shifts everything after it. This silently corrupted **54%** of
> Gemini's rows (empty `employer` dropped → `address` slid one column left), crashing its macro-F1
> to **0.20 — below GLiNER zero-shot's 0.33**, a pure artifact. **YAML names each key and is
> immune**, so `gemini_baseline.py` / `gliner_baseline.py` default to YAML for the generative bar.
> Pipe stays viable for the *trained* model (which learns to always emit all 8 fields); decide
> per measured parse-failure rate, not a priori.

### 3. Base model — the Qwen3.5 small family
Prototype on **Qwen3.5-2B** (accuracy/speed sweet spot), then train **0.8B** and **4B** and
publish all three as a family (mirrors `small-models-for-glam` name-parser). Recommend 0.8B/2B
for production. SFT via **TRL `SFTTrainer`**, LoRA first (cheap/fast), full fine-tune for finals.

### 3a. Alternative & baseline track — GLiNER (extractive, original `urchade/GLiNER`)
Run the original **`urchade/GLiNER`** (v0.2.27 — Apache-2.0, ~200–340M DeBERTa encoder,
CPU-servable, with **relex** relation extraction and a ~1.9× quantize/compile speedup) as a
cheap span-based foil to the generative SFT. It extracts the schema fields **zero-shot** (no
fine-tune required); `eval/gliner_baseline.py` assembles them into the SAME pipe rows and scores
through `eval/evaluate.py`, so it sits directly in the baseline comparison table. Trade-offs: it
is **extractive** (labels verbatim spans), so `is_business` is set by the converters' heuristic and
inherited surnames must be carried into the input (the `harvest_minneapolis.py` surname logic) —
but it sidesteps the JSON/format brittleness in §2 entirely and is far cheaper at scale, making it
a credible *production* option, not just a baseline. **GLiNER-relex** binds fields to the right
person on dense/multi-person lines (a later refinement; these dialects are one-person-per-line).
Use `urchade/gliner_multi-v2.1` for the French FTD transfer eval. Repo: <https://github.com/urchade/GLiNER>.

### 4. Training infra — HF Jobs (no local GPU needed)
`hf jobs uv run --flavor a100-large …` with a PEP-723 single-file training script (the
van Strien pattern). Pay per GPU-minute; a 0.8–4B SFT run is well under an hour (~$1–3,
A100-large $2.50/hr).

**No paid plan required, though.** HF Jobs needs HF Pro ($9/mo), but the *work* doesn't:
`sft_qwen.py` runs unchanged on **free Colab/Kaggle T4s** (`notebooks/colab_finetune.ipynb`),
and **pushing models + datasets to the Hub is free**. Precision auto-selects fp16 on the T4
(Turing has no bf16); `--qlora` (4-bit) fits 4B in the T4's 16GB. Inference/eval is ~free
(`qwen_predict.py` runs on CPU/T4 in minutes). So the whole train-and-release loop can be $0.

### 5. New repo structure (`city-directory-extraction`)
```
city-directory-extraction/
  README.md                      # task, data, models, how-to
  docs/plan.md                   # this plan
  data_prep/
    synth_persons.py             # curated period pools (Faker optional) → (line → record) pairs  [primary train data]
    nyu_to_eval.py               # NYU NDJSON → held-out eval pairs (+ license tag)
    ftd_to_eval.py               # French Trade Directories → transfer eval
    harvest_own.py               # pull reviewed Tulsa entries from ../directory-pipeline/output via pipeline/api.py
    harvest_minneapolis.py       # Minneapolis 1900 (MIT) OCR-transcription gold -> union-schema SILVER eval (needs review)
  train/sft_qwen.py              # PEP-723; TRL SFT (LoRA / --qlora 4-bit / --full); local, `hf jobs`, or free Colab
  notebooks/colab_finetune.ipynb # free-Colab fine-tune on a T4 (no paid HF plan) → push to Hub
  eval/evaluate.py               # field-level precision/recall/exact-match; Gemini-baseline compare
  eval/gliner_baseline.py        # zero-shot GLiNER (urchade) → pipe preds for evaluate.py (extractive baseline)
  eval/gemini_baseline.py        # Gemini baseline (the go/no-go "bar") → pipe preds; same prompt/schema as the SFT model
  eval/results_table.py          # pivot evaluate.py --save logs → the model × eval-set comparison table (Markdown)
  eval/qwen_predict.py           # run the fine-tuned Qwen over an eval set → preds (same prompt as sft_qwen.py)
  cards/                         # model-card + dataset-card templates (license, intended use, limits, biases, tags)
```
The repo **reads from** `directory-pipeline/output/` through the curated
`directory-pipeline/pipeline/api.py` surface — no duplication of pipeline logic.

### 6. Publish to Hugging Face
- **Datasets:** synthetic train set (permissive), the eval/benchmark set, dataset cards with
  provenance + per-source license. Keep NYU-derived data clearly CC-BY-SA-NC and separate.
- **Models:** the Qwen3.5 family, model cards with eval table, intended use, limitations,
  historical-bias notes, and **discovery tags** (the agent-race post shows tags materially
  affect findability). Ship sibling/version checkpoints per the "extending-a-community-model"
  pattern. Personal namespace first; upstream to `small-models-for-glam` if desired.

---

## Phased roadmap

| Phase | Goal | Deliverable | ~Effort |
|---|---|---|---|
| **0 — Learn the loop** | Replicate ONE precedent end-to-end on a tiny sample to learn HF Jobs + TRL + push-to-hub (e.g. reproduce Mattingly's name parser on 5k of his synthetic rows, or the agent-race Jim Crow fine-tune) | A model you trained + pushed; confidence in the tooling | ½–1 day |
| **1 — Schema + data** | Lock persons schema; build synthetic generator; build NYU/FTD/own eval sets; A/B pipe vs YAML | HF dataset (synthetic train + held-out eval) + dataset card | 1–2 days |
| **2 — First fine-tune + baseline** | SFT Qwen3.5-2B via HF Jobs; establish baselines on the *same* held-out set — **Gemini** and **zero-shot GLiNER** (`eval/gliner_baseline.py`); measure field-level P/R/EM | First model + a baseline table (Qwen vs Gemini vs GLiNER) | 1 day |
| **3 — Iterate + family** | Tune data/format/epochs; train 0.8B + 4B; **optionally LoRA-fine-tune GLiNER on the same synthetic set as an alternative extractive line**; cross-eval all on NYU + FTD + Tulsa (+ Minneapolis) | Released model family + eval report | 1–2 days |
| **4 — Release** | Model + dataset cards (licenses, limits, biases, tags); optional demo Space | Public HF models + datasets | ½ day |
| **5 — Integrate back** | Add a `run_local_ner.py` backend in the pipeline that calls the fine-tuned model (or the cheaper CPU-served GLiNER, whichever the Phase-2/3 table favors) and writes the same `entries_{model_slug}.csv` (per anchor-doc Phase 2) | Pipeline runs city-directory NER off Gemini | 1 day |

---

## Learning path (start here)
1. **HF LLM course** — [Chapter 11 "Fine-tuning LLMs"](https://huggingface.co/learn/llm-course/chapter11/1), esp.
   [Supervised Fine-Tuning (TRL `SFTTrainer`)](https://huggingface.co/learn/llm-course/chapter11/3) and
   [LoRA/PEFT](https://huggingface.co/learn/llm-course/chapter11/4). Closer to our small-model/GLAM focus:
   the [smol-course SFT unit](https://huggingface.co/learn/smol-course/en/unit1/3). API reference:
   [TRL `SFTTrainer` docs](https://huggingface.co/docs/trl/en/sft_trainer) +
   [TRL SFT script](https://github.com/huggingface/trl/blob/main/trl/scripts/sft.py) (good PEP-723 / `hf jobs uv run` template).
2. **Closest precedents to read + replicate:** Mattingly's post + his published models/dataset;
   van Strien's [extending-a-community-model] and [index-card-classifier] patterns; the
   [agent-race](https://danielvanstrien.xyz/posts/2026/agent-race/) post (HF-Jobs one-liner
   workflow, label-leakage discipline, tagging).
3. **The HF-Jobs "fine-tune from a sentence" workflow** and `smolagents/ml-intern` Space.
4. Then do **Phase 0** above — hands-on replication is the fastest way to internalize it.

## Reuse from the directory-pipeline repo (don't rebuild)
- `directory-pipeline/pipeline/api.py` — curated surface to read `output/` data from this repo.
- `directory-pipeline/analysis/compare_extraction.py` and
  `directory-pipeline/collections/greenbook/model_eval.py` — existing NER-quality /
  model-comparison scaffolding to adapt into `eval/evaluate.py` (field-level P/R).
- `directory-pipeline/analysis/review_entries.py` + `directory-pipeline/analysis/fix_entries.py`
  — to turn raw Tulsa Gemini output into reviewed gold for the in-domain eval set.
- The existing `ner_prompt.md` field definitions — source of truth for the persons schema.

## Verification (how we'll know it works)
- **Data:** `synth_persons.py` emits N pairs; spot-check 20 by eye; confirm noise/abbrev variety.
- **Training:** a Phase-0 tiny run completes on HF Jobs and the model appears in your namespace.
- **Accuracy:** `eval/evaluate.py` reports field-level exact-match/P/R on held-out NYU; the
  fine-tuned 2B **matches or beats the Gemini baseline** on the same set (the go/no-go gate).
- **Generalization:** non-trivial scores on FTD (transfer) and on your reviewed Tulsa pages.
- **Eval realism (van Strien's rule):** score through the *same* inference path the model will
  actually run in, not just training-checkpoint metrics.
- **Integration:** the Phase-5 backend produces a valid `entries_{model_slug}.csv` that
  `explore_entries.py` / `fix_entries.py` read unchanged.
- **Baseline:** `eval/gliner_baseline.py --self-test` passes and its pipe preds score through
  `eval/evaluate.py` unchanged; the live GLiNER run needs the `gliner` dep (`uv run`).

## Risks & licensing (flag early)
- **NYU is CC-BY-SA-NC 4.0** (non-commercial + share-alike). Training on it can taint a
  release meant for *anyone* to reuse. Mitigation: **synthetic-first training** (permissive,
  yours) with NYU used for *eval* + clearly-tagged optional augmentation only.
- **Synthetic-real gap:** synthetic may miss real OCR failure modes → inject realistic noise
  and always validate on real gold (NYU/FTD/Tulsa).
- **Format/JSON brittleness:** decided above (pipe/YAML, not JSON).
- **Historical bias:** directories encode period-specific occupational/racial categorization —
  document in the model card.
- **Checkpoint drift:** pin Qwen3.5 + dependency revisions in the PEP-723 headers.

## References
- NYU dataset: <https://archive.nyu.edu/handle/2451/61521>
- French Trade Directories: <https://zenodo.org/records/8167628> · <https://doi.org/10.5281/zenodo.6394464> · <https://arxiv.org/abs/2302.10204>
- Mattingly: <https://wjbmattingly.com/blog/parsing-3-6-million-historical-names-with-small-models/>
- van Strien — agent race: <https://danielvanstrien.xyz/posts/2026/agent-race/> · DHD slides: <https://danielvanstrien.xyz/slides/dhd-webinar-2026-may-05/>
- ai-patterns-for-glam: extending-a-community-model.qmd · index-card-classifier.qmd (your linked commit)
- HF orgs: <https://huggingface.co/small-models-for-glam> · <https://huggingface.co/biglam>
- GLiNER (extractive baseline): <https://github.com/urchade/GLiNER> (v0.2.27, Apache-2.0) · checkpoints `urchade/gliner_medium-v2.1`, `urchade/gliner_multi-v2.1`
- Minneapolis 1900 (US, MIT): <https://github.com/adamrangwala/DirCity_Directory_Crop-out-with-Key-Lines>
- Anchor doc (sibling repo): `directory-pipeline/docs/huggingface-uv-scripts.md`
