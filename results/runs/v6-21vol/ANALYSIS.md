# Two diagnoses from the v6 predictions (2026-09-01)

Both analyses run over the v6 eval predictions (job 16709719) against cde-evals gold @ 5d66106.
Nothing here changes any published number — the simulated re-scores below are diagnostics.

## Finding 1 — THE POLK FLOOR IS A SCORING BUG, NOT THE MODEL

Polk NYC gold keeps the printed ditto marker: a leading double-quote (`" Jno H`).
The trainer's serializer (train/sft_qwen.py `to_yaml.q()`) escapes quotes in TRAINING
TARGETS: the model was taught to write `name: "\" Jno H"` — valid, correctly-escaped YAML.
The scorer (eval/evaluate.py `parse_yaml`) strips surrounding quotes but NEVER UNESCAPES,
so the model's correct answer parses as `\" Jno H` and is scored wrong against `" Jno H`.
The round-trip is asymmetric; every ditto row in the five NYC Polk volumes pays for it
(34–54 name "failures" per volume are exactly this).

Fix (one line, in parse_yaml — inverse of q()):
    rec[key] = m.group(2).replace('\\"','"').replace('\\\\','\\')

Simulated re-score of the v6 preds with that fix (nothing retrained):
| volume | EM scored | EM fixed | Δ | macro scored → fixed |
|---|---|---|---|---|
| polk1917 | 12.5 | 56.9 | +44.4 | 0.586 → 0.691 |
| polk1925 | 7.5 | 80.0 | +72.5 | 0.787 → 0.937 |
| polk1933bk | 18.4 | 65.3 | +46.9 | 0.773 → 0.869 |
| polk1933si | 21.4 | 67.9 | +46.5 | 0.761 → 0.850 |
| queens1933 | 19.4 | 56.5 | +37.1 | 0.736 → 0.819 |
| (mid-century vols) | — | — | +0.0 | unaffected, different issue |

21-volume board with the fix: **0.853 macro / 74.9% EM** (scored: 0.835 / 66.5%).

Caveats for Josh: (a) the artifact has depressed every YAML run's Polk numbers since the
panel existed — historical board entries need re-scoring after the fix, and baselines whose
output doesn't escape quotes (Gemini?) were never hit, so cross-model Polk comparisons to
date are not apples-to-apples; (b) qwen_predict.parse_completion's first-record logic keys
on field names only and needs no change; the fix lives in parse_yaml.

Residual Polk failures after the fix (EM 57–80%) are mostly abbreviation mangling on
dense Polk vocab: hlpr→helper, fctywkr→factwkr, pntr→ptr, firemn→firm, blksmith→blocksmith,
elec contr→electr. That's a real generator-coverage item (Polk-style dense abbreviations),
much smaller than it looked.

## Finding 2 — the surviving mid-century punctuation convention, named

It is abbreviation periods on ADDRESS-GRAMMAR tokens, which 1810s–1850s gold prints WITH
periods and the model emits bare (all concentrated in `address`):
  r. (residence marker — 8/9 of rode1851's punct misses), n. (near), c./cor. (corner),
  bet. (between), av., st., ft., b.
Examples: gold `r. 213 W. 40th` vs pred `r 213 W. 40th`; gold `Hunter st. cor. Fulton av.`
vs pred `Hunter st. cor Fulton av`. Counts match the normalization gaps exactly
(doggett 8 rows ≈ +21.6). There is also a small REVERSE clash: the model writes `h.` where
doggett/hopehenderson gold prints bare `h` (and hopehenderson gold itself mixes `h`/`h.`).
v6's directional fix didn't touch these tokens — v5→v6 punct-miss profiles on doggett are
essentially unchanged. Cycle-7 generator spec: era/publisher-gate periods on
{r, n, c/cor, bet, av, st, ft, b} the same way directionals were gated, and align the
h-marker per volume.

## Also noted
franks1786's collapse (separate from both findings): v6 copies the house-number comma
verbatim ("57, Cherry-st") where franks gold strips it — a v6 surface-form/convention
collision, decision needed on which side wins.
