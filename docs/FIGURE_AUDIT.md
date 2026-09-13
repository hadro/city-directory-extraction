# Audit — is every published figure scoped the way it is cited?

**Run 2026-09-13.** Prompted by three separate findings in one session where a number turned out to
be measured on a narrower population than the sentence quoting it implied. Rather than assume that
was three accidents, every checkable figure in [PIPELINE.md](PIPELINE.md) was **recomputed from the
artifacts in this repo** and compared against the published value.

Method: recompute, do not re-read. A figure that cannot be recomputed is listed as such, which is
itself a finding.

---

## Verified exactly — no action

| figure | published | recomputed |
|---|---|---|
| 1906BPL kept lines | 199,012 | **199,012** |
| 1906BPL candidates | 292,793 | **292,793** |
| combined keep rate | 68.0% | **68.0%** |
| `44` leading tokens | 84,053 (42%) | **84,053 (42.2%)** |
| listing bounds | leaves 9–1215 | **9–1215** |
| leaves in letter blocks vs plain range | 1,041 / 1,207 → 166 ad-run leaves (13%) | **1,041 / 1,207 → 166 (13%)** |
| alpha-run cut | 7.5% | **14,965 lines = 7.5%** |
| cross-line dispute rate | 23.5% | **31,564 = 23.5%** |
| cross_leaf / letter_conflict | ~20k each | **20,302 / 20,228** |
| micro13 kept | 2,889 (83.5%) | **2,889 (83.5%)** |
| ditto-lead share | 67.3% | 67.4% — trivial drift from re-ingest |
| wrapped continuations | 12.8% | 12.7% of candidates (11.3% of raw hOCR lines — denominator is candidates) |

The pipeline's structural numbers are sound. What follows is entirely about **scope**.

---

## Finding 1 — "text filter keeps 76%" is a 14-leaf measurement

PIPELINE.md stage 1 reads *"Calibrated: keeps 76% on 1906BPL"*, immediately above a throughput
table giving 68.0%. The source is `ia_volume_to_jsonl.py`'s own docstring, which is scoped and
honest where the runbook is not:

> "Measured on **14 seeded-random leaves** of 1906BPL: keeps **76%**."
> "Measured on **six 1906BPL leaves** … Combined with the text filter this keeps 73.1% (text alone
> keeps 76.0%)."

Recomputed whole-volume, from `data/1906BPL_dropped.txt` (drops are exclusive — a line rejected by
the text filter never reaches the geometry filter):

| | 14/6-leaf subset | whole volume |
|---|---|---|
| text filter alone keeps | 76.0% | **72.5%** |
| text + geometry keeps | 73.1% | **68.0%** |

**3.5 points** overstated. The direction matters: the filter is *less* permissive than advertised,
so slightly more is being discarded before the model ever sees it than the runbook implies.

The irony is local. Stage 1 already carries the warning **"⚠️ Calibrate on the whole volume. The
gates are shares, so a `--leaves` subset calibrates on its own sample"** — written about the ditto
gate, and not applied to the filter three paragraphs above it.

---

## Finding 2 — the 97.5% that justifies the QA stage rests on 40 lines nobody kept

`entry_rate.py` is the only instrument this project has for fabrication, and its licence to exist
is one sentence in its docstring:

> "Accuracy, against 40 lines from 1906BPL hand-labelled by reading them: … surname-shape 67.5% …
> this proxy 97.5%."

**Those 40 labels are not in the repo.** No `data/`, `results/` or `docs/` file contains them. So
the number cannot be re-checked, cannot be extended, and cannot be re-run after any change to
`is_entry` — and `is_entry` is exactly the function every fabrication claim in this project passes
through.

This is the repo's own standard turned on its most load-bearing proxy: predictions are persisted
before analysis, gold is committed, A/Bs are pre-registered — and the validation underneath all of
it is a claim in a comment. **Re-label 40 lines and commit them.** It is under an hour and it
converts the project's most-cited number from an assertion into a check.

---

## Finding 3 — "9,830 gold records" is a glob over a directory that keeps growing

PIPELINE.md: *"Within-line is deterministic: 17 hits across 9,830 gold records, zero false
positives."* HANDOFF defines the denominator as **"every `data/*_eval.jsonl`"**.

That population is not fixed. It is now **11,119 records across 34 files**, and it includes files
that are not gold at all:

- `1906BPL_sample500_eval.jsonl` (500) and `1906BPL_sample500_norm_eval.jsonl` (500) are **ingest
  samples with empty `record` stubs** — verified, zero populated fields — swept in by the glob
  because they match the filename pattern.

The finding (17 within-line hits, zero false positives) is not undermined; the denominator is.
**Name the panel explicitly** rather than globbing a directory, and re-state the figure against it.

---

## Findings already corrected earlier in this session

Listed so the pattern is visible in one place, since each was found separately.

| figure | cited as | actually |
|---|---|---|
| 1906BPL fabrication **10.4%** | volume rate | **top 20 kept lines of each of 25 leaves** — the top ~12% of pages, where ad strips live. Stratified: **5.6%** |
| micro13 fabrication **20.7%** | volume rate, "clean tier is 2× better" | **kept leaves only, n=2,227**; whole volume **30.1%**. Real gap **5.4×** |
| surname block headers | mechanism recorded, magnitude not | measured: 2.5× the dispute rate but **2.6% of all disputes** |

---

## The pattern, and the cheap guard

Five of six scope errors share one shape: **a number measured on a subset, then quoted in a sentence
whose subject is the whole volume.** In four of the five the underlying docstring was correctly
scoped and the runbook dropped the qualifier in summarising it.

The guard is not more rigour at measurement time — that was already there. It is:

1. **Carry the denominator into the sentence.** "76% (14 leaves)" costs four words and cannot be
   mis-quoted downstream.
2. **Never define a population by a glob.** `data/*_eval.jsonl` silently acquired 1,000 non-gold
   rows.
3. **Persist the labels behind a validation, not just its result** — finding 2 is the only one here
   that cannot be checked at all, and it is the most important number in the QA stage.

## What this audit did not cover

- HANDOFF.md's full history. It is a working record of ~2,200 lines including explicitly superseded
  sections; only figures reachable from PIPELINE.md were traced.
- Model accuracy numbers (EM 82.0 / 81.1 / 78.6) — these come from `evaluate.py` over the gold
  panel and were not re-run here; that needs a GPU pass, not a recomputation.
- The OCR figures (CER-all 0.067, djvu 0.723 vs 0.159) — measured in `historical-ocr-eval`, a
  different repo, and not re-derivable from artifacts here.
