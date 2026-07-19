# Training options — cheap/free paths for the fine-tune

> Researched 2026-07-18 (web-verified pricing + issue-tracker state; flagged where estimated).
> Reference workload: **Qwen3.5-0.8B LoRA, 100k synthetic × 3 epochs, YAML target, packed**
> (~45M tokens seen, ~300k samples). Proven baseline: **HF Jobs `rtx-pro-6000` batch 64
> `--packing` ≈ $6 / ~2.7h** (measured — see HANDOFF.md "Training speed").
>
> The "$100+ problem" is not one run — it's iteration × family scaling (0.8B/2B/4B at 500k was
> estimated ~$150–250 on HF Jobs). The levers below attack both the per-run cost and the number
> of paid runs.

## Comparison (0.8B / 100k×3)

| path | new $ | wall-clock | setup | verdict |
|---|---|---|---|---|
| HF Jobs `rtx-pro-6000` b64 + packing | ~$6 | ~2.7h | zero (proven) | the reliable paid path |
| **Colab credits, A100 (existing notebook)** | **$0 new** (~60–85 of your CUs) | ~4–5h | low | **best next-retrain path** |
| **Modal free tier ($30/mo credit)** | **$0, renews monthly** | ~3–4h | medium (wrapper) | **best recurring free path** |
| Kaggle free T4 | $0 | ~30–35h over 1–2 wks (sessions) | medium (resume) | true-$0 fallback |
| vast.ai / RunPod RTX 4090 | ~$3–4 | ~5–8h | medium | cheapest paid, more ops |
| MLX on the 16GB M2 Air | $0 | ~2–4 days continuous | high (new stack) | experiment, not workhorse |
| HF Jobs t4/L4/a10g "cheap" tiers | ~$4–10 | 9–13h+ | zero | **don't bother** (see below) |

## 1. Colab credits + the existing notebook — spend what's already sunk

You already hold ~100 compute units (~$10 already paid) and the repo already has
`notebooks/colab_finetune.ipynb`. Rates: **$0.10/CU; T4 ≈ 1.76 CU/hr, A100 ≈ 15 CU/hr** (L4 rate
unconfirmed). Check your real balance under *Colab → View resources*.

- **A100 (40GB) is the move**: the measured a100-large (80GB) run was ~3.9h at batch 64. On 40GB
  the YAML-logits memory spike means **batch 32 (+ grad accumulation) + `--packing`** → est.
  ~4–5.5h ≈ **60–85 CU**. One full retrain fits in your balance; two won't.
- Free-tier T4 is *not* a real option for the full run: the measured L4 time was ~13h, T4 is
  ~2–2.5× slower → ~30h+ against a 12h session cap and fp16-only (no bf16 on Turing).
- Caveats: keep the tab alive (background execution needs a paid plan); OOM escape hatch env vars
  from HANDOFF if batch 32 still spikes; T4-tier fp16 autocast is already handled by
  `sft_qwen.py`'s adaptive precision.

**Verdict:** the immediate next retrain (the ditto/coverage fix) should go here — it costs zero
*new* dollars and near-zero setup.

## 2. Modal free tier — $30/month of recurring free GPU

Modal's Starter tier currently grants **$30/month compute credit, resetting monthly, no card
required** (modal.com/pricing). That's roughly 12h A100-class or ~15h L40S per month —
**4–5 full 0.8B retrains per month for $0**, renewing indefinitely.

- Setup: Modal is decorator-based Python, so `sft_qwen.py` needs a thin wrapper (an
  `@app.function(gpu="A100", timeout=...)` entrypoint that installs the PEP-723 deps and invokes
  main; mount/pass the train file or pull from `hadro/city-directory-synth`). Est. 1–2h one-off.
- This is the answer to the *family-scaling* cost: 0.8B/2B/4B at 500k spread over 2–3 monthly
  credit cycles ≈ $0 instead of ~$150–250.
- Risks: the $30/mo grant is a current promo-shaped fact — re-verify before relying on it
  long-term; per-GPU-class conversion rates above are search-derived, so smoke-test with a 3k
  run first (the repo's standard smoke) to measure real burn.

**Verdict:** set this up once, and the recurring training budget problem mostly disappears.

## 3. Kaggle — the true-$0 fallback

Free ~**30 GPU-hours/week**, T4×2 or P100, 9–12h session cap. Using one T4 at the repo-derived
estimate (~2.6 samp/s → ~32h) a full run spans **3–4 sessions across 1–2 weeks**, checkpointing
and manually resuming each time.

- Before attempting: `sft_qwen.py` currently saves per **epoch** (~10h apart on a T4 — right at
  the session boundary). Add step-based `save_steps` + `--resume-from-checkpoint` plumbing first
  (small TRL-native change), and push checkpoints to the Hub so a session death loses ≤ an hour.
- Same T4 caveats: fp16-only (handled), slower than every other path here.

**Verdict:** works, costs nothing, but it's a babysitting job. Use it if Modal's free tier ever
evaporates, or for one-off small smoke runs.

## 4. vast.ai / RunPod — the "just pay $3" path

Current spot prices: **RTX 4090 ~$0.29–0.59/hr** (vast.ai), **~$0.34/hr** community-cloud
(RunPod); L4 ~$0.39/hr. A 4090 (24GB, bf16, fast) should land the run in ~5–8h → **~$3–4 total**,
i.e. cheaper than HF Jobs per run.

- More ops than HF Jobs: pick an instance, SSH/docker, move data, babysit spot preemption.
  Worth it only if you're doing many paid runs and Modal/Colab credits are exhausted.

## 5. MLX on the 16GB M2 Air — experiment, don't depend on it

The Air already earns its keep on **inference/eval** (the full 17-volume panel eval ran locally in
~1.5h via MPS). Training is much shakier:

- `mlx-lm` gained **text-only Qwen3.5 loading in v0.30.7** (PR #869) — the vision-tower problem
  is solved there. But Qwen3.5 is the hybrid Gated-DeltaNet architecture, and there are **two
  open, unfixed mlx-lm bugs** in exactly that path:
  [#1206](https://github.com/ml-explore/mlx-lm/issues/1206) (LoRA backward-pass crash through the
  DeltaNet scan — structural, no fix yet) and
  [#1185](https://github.com/ml-explore/mlx-lm/issues/1185) (Metal descriptor leak killing LoRA
  runs after 60–220 iterations). Neither is confirmed *absent* at 0.8B; one community repo
  reports 0.8B/2B LoRA working (475 / 180 tok/s — on an M1 with 64GB, short run).
- Even optimistically (150–300 tok/s on a base M2), 45M tokens ≈ **42–83h continuous** — days of
  a fanless laptop at full throttle (expect thermal throttling to stretch that further).
- Interop friction: an MLX-trained adapter isn't a HF PEFT adapter; you'd fuse/convert to eval
  with the existing transformers harness (and
  [#1058](https://github.com/ml-explore/mlx-lm/issues/1058) reports conversion divergence on 4B),
  or write an mlx-based `qwen_predict` variant that emits the same preds format.
- If you try it anyway: 0.8B only, `mlx_lm.lora` with a 500-iteration smoke first (that alone
  answers whether #1206/#1185 bite), `--save-every` aggressively, and compare a fused-model
  synth-dev score against the TRL-trained baseline before trusting a long run.

**Verdict:** a fun weekend experiment with real bug risk; keep the Air as the eval box.

## 6. HF Jobs cheaper tiers — measured out, skip them

Current prices (huggingface.co/docs/hub/jobs-pricing): t4-small $0.40/hr, L4 $0.80, a10g-small
$1.00, a10g-large $1.50, a100-large $2.50, **rtx-pro-6000 $2.75 (the proven ~$6 run)**, h200 $5.
The repo already measured **L4 ≈ 13h → ~$10.40** (batch-capped by YAML-logits OOM) — *worse* than
rtx-pro-6000 in both dollars and time. t4-small would be slower still for roughly the same total
$. Cheaper-per-hour loses on this workload; the slow-kernel fallback makes throughput, not rate,
the cost driver. PRO ($9/mo) includes no Jobs allowance (Inference/Spaces perks only).

## Recommended plan

1. **Next retrain (ditto + coverage fixes): Colab A100 with the existing notebook** — $0 new
   money out of your sunk credits, ~4–5h, batch 32 + `--packing` + `exclude_modules=["visual"]`.
   (If your CU balance turns out low, fall back to the known $6 HF Jobs run — don't burn a day
   saving $6.)
2. **In parallel, stand up the Modal wrapper** (~1–2h) and validate with a 3k smoke run. All
   subsequent iteration + the eventual 2B/4B/500k family scaling rides the $30/mo free credit.
3. **Keep the M2 Air as the eval machine** (panel scoring, prediction spot-checks). Optionally run
   the 500-iter MLX smoke out of curiosity; report back to mlx-lm #1206 either way.
4. **Control run-count, not just run-cost:** batch multiple generator fixes per retrain, validate
   data changes with `--preview`/`--dry-run` and the 3k smoke before any full run, and hold the
   500k/family scale-up until the coverage fixes are confirmed on the 18-volume panel.

With this, the realistic total for finishing the current roadmap is **≈ $0–12** (mostly sunk
Colab credits + Modal free credit), versus the ~$150–250 all-HF-Jobs estimate.
