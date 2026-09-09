# Scale runs — the 250k A/B and the 2B/4B family

**Written 2026-09-08. RUN 2026-09-09 — results below the design.** Two experiments, teed up for
NYU Torch.

---

## ✅ RESULTS — volume negative, capacity positive

| run | EM verb | **EM norm** | `name` F1 norm | externals agg |
|---|---|---|---|---|
| v6 | 75.2 | 78.6 | 0.943 | 59.5 |
| v7 | 74.5 | 77.6 | 0.939 | 58.7 |
| v8-250k | 71.8 | **74.8** | 0.937 | 54.4 |
| 2b-100k | 77.8 | **81.1** | 0.942 | 61.0 |
| **4b-100k** | **78.4** | **82.0** | **0.952** | **62.8** |

**Experiment 1 (volume): NEGATIVE.** 2.5× the data made the 0.8B worse — −2.8 normalized, lost all
four externals. Matches the pre-registered "250k flat" row, and then some.

**Experiment 2 (capacity): POSITIVE and monotone**, hitting the pre-registered row *"the 0.8B is
capacity-limited after all, and the release decision changes."* **`4b-100k` displaces v6** — it wins
the normalized panel and all four externals individually, which was the stated bar.

**The prediction written into this document was wrong**, and deliberately so — it said "we expect
both to come back flat" and gave that as a reason to run rather than skip. Volume was flat-to-worse
as expected; capacity was not. The reasoning error is recorded in HANDOFF.md's SCALE RUNS section:
`synth_dev` saturation measures fit to the *generator's* distribution and says nothing about
capacity on the *real* one.

Full record: `docs/HANDOFF.md` → "SCALE RUNS", artifacts under `results/runs/scale-runs/`.

---

## The original design (kept — it is why the results are interpretable)

> **Read this first.** Generator/composition iteration is finished — v7 settled it (three
> compositions, normalized EM 79.0 → 78.6 → 77.6). These two runs test the only pre-registered
> variables never tried: **volume** and **capacity**. Neither is a generator change.
>
> **We expect both to come back flat**, and that expectation is written down on purpose. `synth_dev`
> is macro 0.997 / EM 98.1% — the model already reproduces its own training distribution almost
> perfectly, so the ~20-point gap to real gold (normalized ~78) is a *distribution* gap that neither
> more rows of the same distribution nor more parameters should close.
>
> **That is a reason to run them, not a reason to skip them.** Right now that claim is an inference
> from saturation; nobody has measured it. A flat result converts it into a measurement and makes it
> citable — "we tested volume and capacity and neither helped" is a genuine finding for a 0.8B
> result. It also gives NYU real throughput numbers for their own hardware, which is worth having
> independently of what happens to the score.

---

## Experiment 1 — the 250k A/B (volume)

**Question:** does 2.5× the training data move extraction, holding composition fixed?

**Design.** `data/synth_train_250k.jsonl` was generated with the *same generator commit and the
same seed* as v7's 100k. Verified: **its first 100,000 rows are byte-identical to v7's training
file.** So the 250k set is a strict superset, and the A/B isolates volume perfectly — not one row
of the shared 100k differs.

- **Control:** v7 (already run, already on the board). No new baseline needed.
- **Variable:** n = 100,000 → 250,000. Nothing else.
- Dev and smoke are unchanged (`synth_dev` seed 99, `synth_smoke` seed 7), so eval is held constant.
- Verified on the 250k: 0 self-crossed streets over 12,382 two-street instances, 0 race forms not
  attested in the corpus, 0 `home_address` values keeping a residency marker, dev/train overlap 0,
  smoke/train overlap 0, and **100% distinct `raw_line`** — the generator is not repeating itself
  at this scale, so the extra 150k are genuinely new examples.

```bash
source hpc/env.sh
sbatch $(slurm_gpu_args) \
  --export=ALL,RUN_NAME=v8-250k,TRAIN_FILE=$DATA/synth_train_250k.jsonl \
  hpc/20_train.sbatch
```

Estimator (`hpc/estimate_run.py --n 250000 --size 0.8B --gpu l40s`): **~18 h on an L40S**, one job,
no chaining. Treat that as an upper bound — the estimator predicted 6.0 h for v7's 100k and the
real run took 4 h 18 m, so it runs ~30% conservative. An H200 would be ~4 h.

---

## Experiment 2 — the 2B/4B family (capacity)

**Question:** does a bigger model extract better, holding data fixed?

**Design.** Use the **same 100k v7 training file** — *not* the 250k. Changing both size and volume
at once confounds the two experiments and neither answers its question.

- **Control:** v7 (0.8B, 100k).
- **Variable:** `MODEL_SIZE` only.
- LoRA config stays r=16 / α=32 / dropout 0.05 for comparability.

```bash
export MODEL_SIZE=2B          # then repeat with 4B
source hpc/env.sh             # batch, grad-accum and wall-clock follow automatically
```

`env.sh` holds the *effective* batch at 64 everywhere via grad-accum, so a smaller card changes
throughput but not the optimization trajectory.

### ⚠️ Three pre-flight steps, in order. Do not skip the first.

**1. `--dry-run` — verifies `exclude_modules` on the new architecture. CPU only, no GPU.**

```bash
python3 train/sft_qwen.py --model Qwen/Qwen3.5-2B --dry-run
```

This exists because of the project's **first** silent scoring artifact (2026-06-18): training
auto-loaded the full multimodal model while eval loaded `AutoModelForCausalLM`, the adapter was
silently not applied, and NYU's macro read 0.358 instead of 0.760. The guard is
`exclude_modules="(?i).*visual.*"`, which keeps LoRA off the vision tower. **That regex was only
ever validated against 0.8B.** If 2B or 4B names its vision modules differently, the regex silently
stops matching, LoRA adapts the vision tower, and you waste capacity on a tower that never sees an
image. The dry-run prints which modules get adapters and asserts zero visual ones. Run it for both
sizes before submitting anything.

**2. Prefetch the weights.** Jobs run with `HF_HUB_OFFLINE=1`, so an unprefetched model fails on the
compute node with no network:

```bash
MODEL_ID=Qwen/Qwen3.5-2B bash hpc/01_prefetch.sh
```

**3. Smoke, then re-anchor the estimate.** Everything at 2B/4B is extrapolation from the 0.8B
measurement. Feed the real throughput back in:

```bash
sbatch $(slurm_gpu_args) --export=ALL,RUN_NAME=smoke-2b hpc/10_smoke.sbatch
python3 hpc/estimate_run.py --measured <samples/sec from the smoke log> --size 2B
```

### Pick the GPU deliberately — it matters more than usual here

| run | L40S | H200 |
|---|---|---|
| 2B on 100k | ~23.6 h | **~5.4 h** |
| 4B on 100k | **~43.5 h** ⚠️ | **~10.0 h** |

**Do not run 4B on an L40S.** At ~43.5 h it sits inside a 48 h wall with almost no margin; any
queue slowdown or checkpoint stall loses the run. On an H200 it is a comfortable single job.

The reason the H200 helps so much is counterintuitive and worth knowing: Qwen3.5's 248,320-token
vocabulary makes the loss path materialise a `[batch × 512 × 248320]` logits tensor — ~57 GB at
batch 64, far larger than any of these models' weights. **That term does not scale with model
size**, so 0.8B → 4B adds only ~7 GB to a ~60 GB budget. Batch, not parameters, sets the VRAM wall,
which is why extra memory converts directly into speed rather than merely into "fits".

---

## For every run in both experiments

- **`PANEL` stays frozen at 21 volumes** in `hpc/30_eval.sbatch`. `doggetts1850`, `smith1855` and
  `smith1856` are on the Hub but deliberately held out — adding them breaks comparability with
  v5-torch/v6/v7 exactly the way the 18 → 21 change did.
- **NYU must keep `--exclude-fields spouse_name,race_designation,is_business`** — those are
  regex-derived, not transcribed.
- **Judge on `evaluate.py --report-normalized`, not verbatim.** This is the whole lesson of v6/v7:
  v6 gained +17.8 verbatim over v5-torch and +0.9 normalized. Report both; decide on normalized.
- **Run `--report-normalized` on the externals too**, not just the panel. NYU's v6/v7 reports
  covered the panel only, which left the release decision resting on verbatim externals until it
  was closed by hand. Externals are `nyu` (at `--limit 500`), `tulsa`, `lain`, `minneapolis`.
- **Keep the prediction files, not just the adapter.** This is the cheapest insurance in the
  project: stored predictions let you re-score against a metric you think of *later*, on CPU, in
  seconds. v5-torch's preds were kept and answered the external-punctuation question instantly;
  v6's and v7's were not, and answering the same question for them cost a 3.5 h regeneration.
  `/scratch` purges ~60 days after each run.
- **Sanity-check the download before scoring** — the silent gated-download failure nearly scored v6
  against the wrong `synth_dev`:
  ```bash
  ls data/*_eval.jsonl | wc -l
  python3 eval/evaluate.py --gold data/polk1925_eval.jsonl --self-test
  ```
- **Check for `missing adapter keys` in the eval log.** It means the adapter silently did not apply
  and you scored the bare base model.

## What each outcome means

| result | reading |
|---|---|
| 250k flat on normalized | Volume is not the constraint. Converts the current inference into a measurement — the citable version of "more data does not help." |
| 250k improves normalized | The saturation argument is wrong, and `synth_dev` at 98.1% was measuring the generator's self-similarity rather than the model's ceiling. Worth knowing, and it reopens data scaling. |
| 2B/4B flat on normalized | Capacity is not the constraint either. Strongest possible support for shipping the 0.8B: same quality, a fraction of the inference cost. **This is the outcome that makes the 0.8B result publishable rather than merely convenient.** |
| 2B/4B improves normalized | The 0.8B is capacity-limited after all, and the release decision changes. |

**Whatever happens, v6 remains the release checkpoint unless a scale run beats it on the
normalized metric across the panel *and* the externals.** v6 currently wins on 4,613 held-out rows
on both metrics; a verbatim-only win is not sufficient to displace it.
