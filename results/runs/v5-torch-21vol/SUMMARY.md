# v5-torch on the 21-volume panel + normalized diagnostic (2026-08-31)

Same adapter as the 18-vol run (job 15966832); re-scored at repo 4d3dd46 with gold
from hadro/cde-evals @ 37b7067 (26 sets). Eval job 16673079, 29m40s, L40S gl036.
Sanity: 26/26 sets loaded AutoModelForImageTextToText; zero "missing adapter keys".
The three new volumes reproduce Josh's local MPS EMs exactly (74.5 / 50.3 / 37.6).

## 21-volume board (line-weighted, n=1583) — the new baseline
macro-F1 0.809 · micro-F1 0.870 · whole-row EM 58.7%
(The drop vs the 18-vol numbers is by design — the new volumes were chosen to expose
a training blind spot. Do not compare across panel versions.)
NYU (restricted, now upstream default): 0.817 / 0.828 / 51.2%.

## The directional-period hypothesis: SUPPORTED
--report-normalized, whole-row EM verbatim -> normalized, line-weighted:
  19th-century (13 vols, n=1034):  64.3 -> 82.3   gap +18.0
  20th-century (8 vols, n=549):    48.1 -> 48.1   gap  +0.0  (every volume exactly 0)
Falsification test: "if the 20th-c volumes move materially, the diagnosis is wrong."
They did not move at all. Pre-registered large-gap volumes: trow1884 +48.9,
trowwilson1865 +38.3, rode1851 +30.2, hopehenderson1856 +18.4, doggett1846 +16.2,
longworth1818 +9.5, lain1876 +8.7, nyu +5.4.
One miss: ogden1839 predicted large, observed +0.0 — but its verbatim EM is 90.9%,
so at most 9.1 points of gap were even possible; benign ceiling effect, and its
remaining errors are semantic.

## What this implies
~12 EM points of the whole panel (18 points across the 19th century) are punctuation
convention, not extraction ability. Fixing synth_persons.py to emit period-directionals
for pre-1900 styles (gated on the publisher/era context tag, like the dittos fix) and
retraining 0.8B/100k (~4h L40S, free) is the highest-leverage next run — ahead of any
250k or 2B/4B scale-up, whose baselines would otherwise be polluted by this artifact.
The 20th-century Polk/Queens EMs (7-20%) are untouched by normalization — those are
real semantic/format gaps, a separate problem.

## Files
eval_table.md, scores.jsonl (label qwen-0.8b-yaml-v5-torch), report_normalized_v5-torch.txt,
eval-16673079.out (job log), preds for the three new volumes.
