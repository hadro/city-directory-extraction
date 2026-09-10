# Pre-registration — does a leading OCR'd ditto (`44`) corrupt the parse of the rest of the line?

**Written 2026-09-10, BEFORE the powered run, and not edited afterwards.** This project has lost
three results to interpreting before persisting, and has twice reported a confident wrong number
about its own corpus. Stating the metric and the decision rule in advance is the cheap half of the
remedy; the expensive half (persist first) is handled by writing predictions to
`ab_ditto44_1906BPL_2b100k_preds/` before any analysis runs.

## The question

`44` is ABBYY's reading of the surname-repeat ditto mark `"`, and it is the single most common
leading token in 1906BPL — 84,053 of 199,012 lines (42%). **The generator never emits it**: the
trained ditto forms are `-` (trow) and `" ` (polk), so `44` is out of distribution for every
adapter this project has produced.

The uninteresting half is settled: `name` gets `44` copied into it verbatim, which downstream
normalization fixes for free. The question that decides where the fix belongs is whether an
unfamiliar leading token **also perturbs the parse of the other seven fields** — most plausibly by
running the `name` field too far and swallowing the occupation.

If it does, normalization belongs at ingest (`ia_volume_to_jsonl.py`), before the model sees the
line. If it does not, it belongs entirely in downstream post-processing and the model input should
be left alone, preserving `raw_line` as the audit trail against the page image.

## Design

Paired, within-row. 500 lines carrying a leading `44`/`**`, seeded-random (seed 20260910) from
listing leaves 20–1200 of 1906BPL, ≥4 tokens, **excluding the 105 pilot rows**. Each line is run
twice through `2b-100k`:

- **arm A** — verbatim, as `ia_volume_to_jsonl.py` emits it
- **arm B** — leading `44`/`**` replaced with `"`, nothing else touched

Pairing is what makes this worth running at n=500: each row is its own control, so the ~7% of rows
that carry the metric's noise floor in *both* arms cancel instead of swamping the effect.

## Primary metric, fixed in advance

**Occupation swallow** = the raw line contains a known occupation token AND the predicted
`occupation_role` is empty.

The occupation lexicon (343 tokens) is derived from gold `occupation_role` values across every
`data/*_eval.jsonl` except `ftd_eval` (French), keeping tokens that appear ≥3 times in ≥2 volumes
and subtracting the entire gold name vocabulary — so surnames and given names that leaked into
occupation labels cannot inflate it. Five OCR variants that gold by contract never contains
(`elk`→clk, `eom`→com, `lah`→lab, `earp`→carp, `tailoi`→tailor) are added explicitly and listed
here so the addition is auditable rather than silent.

**The metric was validated on the n=105 pilot before this run**: it flags exactly the two rows
(18, 30) that were identified by hand as boundary failures, and flags seven further rows
identically in both arms.

## Decision rule, fixed in advance

McNemar's exact test on the discordant pairs (rows where exactly one arm swallows).

- **p < 0.05 with arm B better** → the leading token perturbs the parse. Normalize at ingest in
  `ia_volume_to_jsonl.py`, keeping the original in `context.raw_line_original` so the audit trail
  against the page image survives.
- **p ≥ 0.05** → not established at this n. The fix belongs downstream in
  `postprocess/resolve_dittos.py` only, and `raw_line` is left alone.

A null is a publishable result here and **must be persisted with its predictions**, not summarized
and discarded — the exact failure that cost 4.16 h on the publisher A/B, where a materiality guard
returned before the save.

## Pre-registered secondary observations (not decision-bearing)

1. Count of rows differing in any non-`name` field. Pilot: 4/105.
2. Which fields move. Pilot: address 2, occupation_role 2, home_address 1.
3. Apostrophe rendering drift (`B'way` vs `B’way`), which moved in **both** directions in the
   pilot and is expected to be noise.

## What this run cannot settle

- One volume, one OCR engine, one adapter (2b-100k). `4b-100k` is unusable on this machine
  (51× slower — HANDOFF), so this says nothing about the release candidate.
- 1906BPL's publisher tag is `upington`, and `synth_persons.py` gives upington a ditto rate of
  **0.0** — the tag was trained with no ditto rows at all. The publisher A/B found the tag inert
  on both 2B and 4B, so this is recorded as a caveat rather than a confound, but it is not tested
  here.
- The pilot's own evidence was equivocal: a strict metric gave 2/101 vs 0/196 (p≈0.11) while a
  looser one (empty occupation + long name) showed no difference at all. This run uses the strict
  metric, pre-registered above, and does not get to switch.
