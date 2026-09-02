# v6 — cycle six retrain on Torch (2026-09-01)

Repo da4ab27, v6 synth data (5,655 period-directionals, polk-tulsa retag), gold @ 5d66106
(v6-matched synth_dev, retagged tulsa_eval). Train job 16704017 (4h12m, L40S gl044, 4689
steps, loss 0.0037, termination 8/8 OK). Eval job 16709719 (34m, gl033); 26/26 sets loaded
AutoModelForImageTextToText, zero missing-adapter-keys. Config identical to v5-torch.

## 21-volume board (line-weighted, n=1583) — vs the v5-torch baseline
| | macro | micro | EM | EM-normalized | punct. gap |
|---|---|---|---|---|---|
| v6 | **0.835** | **0.892** | **66.5%** | 70.2% | +3.7 |
| v5-torch | 0.809 | 0.870 | 58.7% | 70.4% | +11.7 |

+7.8 EM points on the panel. NYU (restricted): 0.847 / 0.847 / 55.2% (was 0.817 / 0.828 / 51.2).
tulsa 0.908 / 62.7% and synth_dev 0.992 / 96.0% — both reset columns, fine.

## Prediction 1 (19th-c gap collapses to ~0; 20th-c stays 0): PARTLY confirmed
19th-c gap +18.0 -> +5.5; 20th-c stayed +0.2. The Trow volumes collapsed as predicted
(trow1884 +48.9->+2.8, EM +44.0; trowwilson +38.3->+6.6, EM +35.3; rode1851 EM +26.4).
BUT mid-century gaps survive: doggett1846 +21.6, hopehenderson1856 +18.4 (unchanged),
rode1851 +17.0, longworth1818 +10.4 — a second, un-modeled punctuation convention remains.

## Prediction 2 (Polk race FPs -> 0; polk1917/1925 rise): NOT confirmed at eval level
race_designation pred_ne was ALREADY 0 on all five NYC Polk volumes for v5-torch — the
6.3% training-data rate never surfaced as eval false positives, so the fix was vacuous
here. polk1917 EM 11.1 -> 12.5, polk1925 7.5 -> 7.5: still on the panel floor. Whatever
keeps Polk EM low, it isn't race markers (their macro did move: polk1925 .725->.787).

## NEW REGRESSION: franks1786 EM 50.0 -> 12.5 (macro .851 -> .726)
Not punctuation-normalizable (gap +0.0 — the normalizer forgives periods, not commas).
Cause visible in pred diffs: v6 copies the house-number comma verbatim ("57, Cherry-st")
where franks gold strips it ("57 Cherry-st"); v5 stripped it. A v6 generator surface form
taught comma-retention that collides with the franks1786 gold convention. Also down:
doggett1846 EM -5.4, minneapolis 36.5 -> 26.1 (external transfer cost).

## Suggested asks back to Josh
1. Which v6 surface form introduced number-comma addresses, and which convention should
   win (franks gold vs generator) — same class as the (co'd) story.
2. The surviving mid-century punctuation gap (doggett/rode/hopehenderson/longworth) is a
   different convention than directionals — worth one look at those preds before cycle 7.
3. Polk floor is not race markers — needs its own diagnosis.
4. hf download of gated cde-evals exits silently with no files — nearly scored v6 against
   the v5 synth_dev; gold synced via the Mac git clone instead.

## Files
adapter/ (v6 LoRA), eval_table.md, scores.jsonl, report_normalized_v6.txt,
train-16704017.out, eval-16709719.out, smoke-16703878.out.
Hub push still pending a write token (applies to v5-torch and v6 both).

## UPDATE 2026-09-02 — official re-score (parser fix + gold @ 0d68d80)
Josh upstreamed the parse_yaml unescape fix (repo b708f3e) and corrected 6 gold volumes
(casing slips + unsupported periods: lain1876, mb1931, polk1917, rode1851, trow1913,
trowwilson1865). Self-test on polk1925: "yaml round trip OK — all 40 gold rows survive."
Re-scored the existing v6 preds (CPU only, no retraining):

**v6 official 21-volume board: 0.854 macro / 0.921 micro / 75.2% EM** (was 0.835/0.892/66.5).
Polk block lands exactly on the ANALYSIS.md simulation (polk1917 56.9, polk1925 80.0,
polk1933bk 65.3, polk1933si 67.9, queens1933 56.5). Gold edits added the rest:
trowwilson 86.8 (+1.2), lain1876 78.6 (+2.9), synth_dev 97.6 EM (+1.6, parser fix reaches
quoted values there too). nyu 0.847/55.2 unchanged. Files: scores-parserfix.jsonl,
eval_table-parserfix.md — THESE ARE THE AUTHORITATIVE v6 NUMBERS. The pre-fix versions are
kept as scores-oldparser.jsonl / eval_table-oldparser.md (and on Torch as
scores-v6-prefix-oldparser.jsonl) for the parser-fix-vs-gold-edit decomposition only.
