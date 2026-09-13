# Pre-registration — what is 1906BPL's fabrication rate, per band, on an unbiased sample?

**Written 2026-09-13, BEFORE the run, and not edited afterwards.** Same discipline as
[`ab_ditto44_1906BPL_2b100k_PREREGISTRATION.md`](ab_ditto44_1906BPL_2b100k_PREREGISTRATION.md):
state the metric and the decision rule in advance, and persist the predictions before any analysis
touches them.

## Why this run exists

`entry_rate.py`'s headline for this volume — **10.4% not-real** — comes from
`data/1906BPL_sample500_eval.jsonl`, which is **25 leaves × the first 20 kept lines of each**.
Sampled positions are exactly 0–19 on leaves holding 121–181 kept lines, so it reads the **top ~12%
of every page**, which is where advertising strips live
([`band_vs_fabrication_1906BPL.py`](band_vs_fabrication_1906BPL.py)):

| band | expected in a uniform 500 | observed |
|---|---|---|
| head | 3.6 | **36** |
| foot | 3.8 | **0** |
| unbanded | 24.1 | **0** |
| body | 468.5 | 464 |

Head lines are 83.3% not-real on that sample, so the 10.4% is biased **upward**. Three quantities
the project has never measured follow directly: the **unbanded** rate, the **foot** rate, and
whether **body lines lower down a page** behave like body lines at the top.

## Design

**Stratified, 150 lines per band, 600 total**, drawn from `data/1906BPL_lines.jsonl` (199,012 kept
lines, whole volume — not restricted to the listing span, because the question is what fraction of
*what we feed the model* becomes a fake person).

- Strata: `body` (186,470 lines), `head` (1,414), `foot` (1,525), `unbanded`/null (9,603).
- Seeded random **within** each stratum, seed **20260913**, no position or leaf restriction. This is
  the specific defect being corrected, so it is the one thing that must not be repeated.
- One arm. This is an estimation run, not an A/B.
- Model: `2b-100k`, `--target yaml`, the only locally runnable adapter (the 4B is 51× slower on
  this box and would take months).

Predictions are written to `results/ab_band_fabrication_1906BPL_preds/` **before any scoring runs**.
A null or an inconvenient result is persisted, not summarised and discarded — the exact failure that
cost 4.16 h on the publisher A/B.

## Primary metric, fixed in advance

**`entry_rate.py`'s `is_entry`** — `name` non-empty AND an address-shaped string — hand-validated at
97.5% against 40 read lines, against 67.5% for the obvious surname-shape proxy. Not-real = `not
is_entry`. No new metric is introduced for this run.

Two quantities are reported:

1. **Per-band not-real rate**, with a 95% Wilson interval on each.
2. **Volume-wide estimate** = Σ over bands of (band's share of the 199,012 kept lines) × (that
   band's measured rate). This is the number the project currently does not have.

## Decision rules, fixed in advance

**On whether the band separates fabrication:**

- **strip (head+foot) rate ≥ 3× body rate** → confirmed on an unbiased sample. `context.band` is a
  fabrication filter as well as a geometric one, and cutting strips is justified on measured
  grounds.
- **1× – 3×** → real but weak. Keep it as a marked field and a review queue; do not cut on it.
- **strip rate ≤ body rate** → the 17.7× was an artefact of top-of-page sampling and the band's
  fabrication claim is withdrawn. The geometric result against 239 hand-labelled leaves stands
  regardless; only the fabrication interpretation falls.

**On the unbanded stratum** (4.83% of lines, never measured, expected to be full-page advertising):

- **≥ 50% not-real** → unbanded leaves are a distinct and major fabrication source and earn their
  own treatment; this is phase 3 of PAGE_TYPE_CLASSIFIER.md becoming load-bearing rather than
  tidy-up.
- **< 50%** → they are ordinary lines the ditto gate could not bound, and `band: null` should not be
  read as a warning.

**On the published figure:**

- If the volume-wide estimate differs from 10.4% by more than 2 points, **PIPELINE.md's 10.4% is
  replaced** by the stratified estimate, with the top-of-page number kept and labelled as such.
  The 20.7%/10.4% tier comparison is marked unreliable until the microfilm volume is re-measured
  the same way, since `preds_2b-100k_micro_IABROOKLYN_0013.txt` covers all 2,889 lines and so is
  *not* subject to this bias — the two numbers are not currently like-for-like.

## Pre-registered secondary observations (not decision-bearing)

1. Whether body-band not-real rate varies with position down the page (deciles of `body`). The
   top-of-page sample cannot see this and it is the cleanest test of whether the bias is positional.
2. What the not-real lines *are*. The existing sample shows OCR wreckage (`w* 13 cJ`) beside genuine
   interior ad copy; "not real" is not a synonym for "advertising" and the mix matters for what to
   build next.
3. Foot vs head rate. Foot strips carry page numbers, head strips carry display ads, so they may
   not behave alike — and the current sample contains zero foot lines.

## What this run cannot settle

- **It is a proxy, not gold.** `is_entry` cannot see field-boundary quality: `name='44 Wm elk'` with
  an empty occupation scores as a perfect entry. This measures fabrication, never record quality.
  That still needs PIPELINE.md #10.
- **One volume, one engine, one adapter.** Nothing here transfers to the thin tesseract tier, which
  has no bands at all and where fabrication is worse.
- **150 per stratum** gives roughly ±8 points at 50% and ±3 at 5%. Small differences between head
  and foot will not be resolvable.
- The band itself is derived from ditto extent, so a stratum is only as meaningful as the ditto gate
  that produced it.
