# v7 — cycle seven, and the pre-registered stop (2026-09-08)

Repo 5420e31, v7 synth data (all four files hash-verified changed), gold @ b66579b
(v7-matched synth_dev; 3 new held-out volumes NOT in the panel). Train job 17170381
(4h18m, L40S gl004, termination 8/8 OK). Eval job 17183676 (27m); 26/26 correct loader,
zero missing-adapter-keys. PANEL frozen at 21 volumes as instructed. Config = v6 = v5-torch.

## The three-way board (21 vols, n=1583, fixed parser, current gold, line-weighted)
| run | EM verbatim | EM normalized | punct gap | name-F1 norm |
|---|---|---|---|---|
| v5-torch | 67.5 | 79.0 | +11.5 | 0.937 |
| v6 | 75.2 | **78.6** | +3.3 | **0.943** |
| v7 | 74.5 | 77.6 | +3.0 | 0.939 |

## Judged on normalized, per instruction: THE STOP RULE FIRES
Pre-registered: "If name doesn't move on the normalized metric, the model is done — say so
and stop." name-F1 normalized across three cycles: 0.937 → 0.943 → 0.939. Flat (noise).
Normalized EM: 79.0 → 78.6 → 77.6 — flat-to-gently-declining for two cycles. Every verbatim
gain since v5-torch has been convention closure (gap +11.5 → +3.0), not extraction ability.

## The bankable win happened — and was traded away elsewhere
franks1786: 12.5 → 71.4% EM (comma fix; verbatim-only as predicted; beats the ~50% target).
Polk block up big verbatim (polk1917 56.9→52.8 is the exception; polk1925 80.0→72.5 down;
polk1933bk 65.3→69.4, polk1933si 67.9→64.3, queens 56.5→58.1 mixed).
But v7 gave back elsewhere: trowwilson 85.6→78.4, trow1884 81.6→78.0, mb1931 91.7→85.3,
trow1907 80.9→76.5. Net verbatim 74.5 vs v6's 75.2. Convention fixes are now reshuffling
EM between volumes, not adding to it — the signature of a saturated model.

## Brooklyn h/r/bds check (both cycles — the "lost" v6 comparison recovered)
v6 matched gold rates almost exactly (trowwilson 65.9 vs 65.9; worst boyd -5.3) — QUESTION
CLOSED, not a franks-comma-class fix. v7 drifted slightly worse (trowwilson 59.3 vs 65.9),
consistent with the general v7 give-back on Trow-era volumes.

## Externals (v7)
synth_dev 0.997/98.1 (in-dist ceiling); tulsa 61.4; lain 63.5; minneapolis 31.3 (still
below v5-torch's 36.5); nyu 0.830/54.4 (v6: 0.847/55.2).

## What this means (per the project's own pre-registrations)
Generator/composition iteration at 0.8B/100k is exhausted: three data compositions,
normalized extraction flat. The pre-registered next variables are DATA VOLUME (the 250k
A/B, ~10h free on L40S) and CAPACITY (2B/4B family — the original case for this cluster).
v6 remains the best single checkpoint (verbatim 75.2 / normalized 78.6).

## Files
adapter/ (v7 LoRA), eval_table.md + scores.jsonl (v7 rows), report_normalized_{v7,v6_
fixedparser,v5-torch_fixedparser}.txt, scores-v5torch-fixedparser.jsonl (baseline hygiene),
train/eval/smoke logs. Hub pushes: deferred to launch per project decision; all three
adapters (v5-torch, v6, v7) are backed up under torch-runs/ on this machine.
