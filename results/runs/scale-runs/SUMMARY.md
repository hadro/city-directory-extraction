# Scale runs — results (2026-09-10)

Both SCALE_RUNS.md experiments complete, plus the 4B. All on the frozen 21-volume panel
(n=1583), fixed parser, gold @ b66579b; externals normalized per instruction. Every eval:
26/26 correct loader, zero missing-adapter-keys. Training config identical across runs
(LoRA r16/α32/d0.05, effective batch 64, unpacked, 3 epochs, lr 2e-4).

## The board (EM normalized is the decision metric)
| run | EM verb | EM norm | name-F1 norm | externals norm (nyu/tulsa/lain/minn) | ext agg |
|---|---|---|---|---|---|
| v6 (release bar) | 75.2 | 78.6 | 0.943 | 56.0 / 62.8 / 65.0 / 26.1 | 59.5 |
| v7 | 74.5 | 77.6 | 0.939 | 54.6 / 61.5 / 63.8 / 31.3 | 58.7 |
| **2b-100k** | 77.8 | 81.1 | 0.942 | 55.0 / 64.1 / 66.4 / 34.8 | 61.0 |
| **4b-100k** | **78.4** | **82.0** | **0.952** | **56.2 / 67.5 / 65.9 / 35.2** | **62.8** |
| v8-250k (0.8B) | 71.8 | 74.8 | 0.937 | 53.2 / 57.7 / 58.6 / 21.3 | 54.4 |

## Verdicts against the pre-registered outcome table
**Experiment 1 (volume): NEGATIVE — 2.5× data made the 0.8B WORSE.** v8-250k trails v7
(same composition, 100k) by 2.8 normalized panel points and on every external. More of the
same synthetic distribution over-commits the small model to that distribution; the
synth_dev-at-98% reading was right about volume. Volume is not the constraint — measured.

**Experiment 2 (capacity): POSITIVE, and monotone.** 0.8B → 2B → 4B climbs 78.6 → 81.1 →
82.0 normalized, externals aggregate 59.5 → 61.0 → 62.8. The 4B moves the NAME field
(0.952 vs 0.943) — the metric that stayed flat through three 0.8B cycles. Per the outcome
table: "the 0.8B is capacity-limited after all, and the release decision changes."

**Release rule applied:** 4b-100k beats v6 on normalized on the panel AND on every external
individually. By the stated rule, **4b-100k displaces v6 as release candidate** — with the
cost caveat that it's 5× the parameters (inference cost/latency), and 2b-100k captures
most of the gain at half that; that trade-off is a release decision, not a scoring one.

## Operational finds this cycle (for the harness)
1. **Qwen3.5-4B's chat template defaults to thinking-mode at generation** — it ends the
   generation prompt with an OPEN `<think>` (0.8B/2B templates emit a closed empty block).
   Untreated, completions are chain-of-thought prose; the in-training termination check
   caught it (8/8, correctly this time). Fix in eval/qwen_predict.py (archived here as
   qwen_predict.py.patched): pass `enable_thinking=False` in apply_chat_template — verified
   byte-identical no-op for 0.8B/2B, verified clean records for 4B by GPU probe. The same
   kwarg should go into sft_qwen.py's --check-termination generation for future 4B runs
   (its 8/8 FAIL on the 4B was real but for the template reason, not a stop-token reason).
2. **10_smoke.sbatch's dry-run step doesn't pass --model**, so it always validates the 0.8B
   regardless of MODEL_ID — scale smokes aren't checking the model they train. (Login-node
   dry-runs of 2B/4B were run by hand: exclude_modules regex holds, 0 visual adapters.)
3. **env.sh's exported-defaults gotcha strikes submissions too**: an inherited MODEL_ID
   silently overrides MODEL_SIZE; first smoke pair trained 0.8B twice. Guard: export
   MODEL_ID explicitly and verify weight-tensor counts in the log (0.8B=473, 2B=617, 4B=723).
4. 20_train.sbatch's header echoes GPU_TYPE, not the actual device (cosmetic).
5. Preemption worked as designed: 4B trained across 3 stints (2 preemptions), resumed from
   checkpoints, zero babysitting. Measured speeds: 2B ~17 samp/s on L40S (4h54m/100k);
   4B on H200 much faster than estimated; v8-250k 10h28m.

## Files
adapters/{2b-100k,4b-100k,v8-250k}/ · preds/ (ALL prediction files for v7, 2b, 4b, v8-250k —
per "keep the prediction files") · train/eval/smoke logs · scores.jsonl + eval_table.md ·
qwen_predict.py.patched. Hub pushes still deferred to launch per project decision; five
adapters now backed up locally (v5-torch, v6, v7, 2b, 4b, v8-250k).
