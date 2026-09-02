# Taking this over — read this first

**Written 2026-09-01.** Three-minute orientation for an agent or person picking this up cold.
Deeper context: [HANDOFF.md](HANDOFF.md) (long, start at "RESUME HERE"),
[GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md) (labelling conventions),
[NAME_HARVEST_PLAN.md](NAME_HARVEST_PLAN.md) (one specific future task).

---

## Where the project actually is

**The stated goal is met.** A 0.8B fine-tune beats the primed Gemini baseline. On the corrected
18-volume board, `qwen-v5` leads primed-pub Gemini by **+0.053 macro / +11.1 whole-row EM**. That
was true since v4; nobody knew because three scoring bugs were suppressing it.

**The best model is `v6`** — trained on NYU Torch 2026-09-01, 21-volume panel.

| | macro | micro | EM |
|---|---|---|---|
| v5-torch (corrected) | 0.826 | 0.897 | 67.3% |
| **v6** | **0.853** | — | **74.9%** |

⚠️ **v6's numbers are a SIMULATION, not a scored run.** NYU scored v6 before the `parse_yaml`
unescape fix landed and before the gold-quality pass; the figures above are their hand-computed
projection. **v6 is not on the board.** Closing that is open item #1.

**Do not use verbatim whole-row EM as the headline.** Use `evaluate.py --report-normalized`. Cycle
six's +7.8 verbatim EM was **−0.3** normalized — i.e. no real improvement. See the
"⛔ STOP CHASING PUNCTUATION" section in HANDOFF.md before proposing any convention work.

---

## The single most important fact

**The training data published on `hadro/city-directory-synth` PREDATES the last two generator
fixes.** Verified 2026-09-01:

| fix | commit | in the shipped `synth_train.jsonl`? |
|---|---|---|
| surname-repeat ditto rate | `8d5c438` | ❌ shipped data has 14.0%, generator now gives ~78% |
| franks `num_comma` | `7f456d2` | ❌ shipped data has 0%, generator now gives ~67% |

**So the next retrain must regenerate first.** Do not train on what is currently on the Hub — you
would reproduce v6 and learn nothing.

```bash
python3 data_prep/synth_persons.py --self-test
python3 data_prep/synth_persons.py --profile mix --n 100000 --seed 13 --target yaml --out data/synth_train.jsonl
python3 data_prep/synth_persons.py --profile mix --n 3000  --seed 7  --target yaml --out data/synth_smoke.jsonl
python3 data_prep/synth_persons.py --profile mix --n 1000  --seed 99 --target yaml --out data/synth_dev.jsonl
```
Then upload train/smoke to `hadro/city-directory-synth` (archive a versioned `synth_train_v7.jsonl`
alongside, per convention) and `synth_dev.jsonl` to the private `hadro/cde-evals`.

---

## Open items, in priority order

1. **Get v6 onto the board.** NYU re-runs *only the scoring step* over their existing v6 predictions
   — no GPU, seconds of CPU. They need to `git pull` (fixed `evaluate.py` + round-trip guard) and
   re-download gold from `hadro/cde-evals` on the **login node** (six volumes changed 2026-09-01).
   Their simulation and the real score will not match exactly; the gold moved under them.
2. **Push the adapters.** `v5-torch` and `v6` are both still only on `/scratch` (purged after ~60
   days) and in `~/Downloads`. v5-torch is the baseline v6 is measured against. Pending a write
   token on their side.
3. **One more retrain**, carrying `8d5c438` (ditto) + `7f456d2` (franks) and nothing else. This is
   the last generator change with a measured case. **Judge it on the normalized metric.** If `name`
   does not move, the model is done — say so and stop.
4. **Gold labelling** — tools are generated and gitignored in the repo root:
   `gold_doggetts1850.html` (**do this first** — hand-labelled spouse/race/is_business for the
   publisher NYU is drawn from would retire the `--exclude-fields` workaround on the external
   benchmark), then `gold_upington1906.html`, `gold_smith185{4,5,6}.html`.
   **Hold new volumes OUT of `PANEL` in `hpc/30_eval.sbatch`** until the next model is scored on the
   current 21, or you lose the clean A/B again.
5. **Release.** `cards/MODEL_CARD.md` and `cards/DATASET_CARD.md` still carry pre-fix numbers.

**Explicitly NOT worth doing** (each measured, not assumed):
- cycle-seven punctuation work (ceiling +5.5 EM, all typography)
- scaling synthetic data or training 2B/4B — `synth_dev` is macro 0.992 / EM 96.0%, the model has
  saturated its own distribution; capacity and volume are not the constraint
- re-probing GLiNER2 — done and documented in `eval/gliner2_baseline.py`

---

## Loose ends with no owner

- **`results/runs/`** is untracked. It holds NYU's run artifacts (`SUMMARY.md`, job logs,
  `report_normalized_*`). Decide whether run artifacts belong in git or should be gitignored like
  `scores.jsonl`.
- **42 `nyu` gold rows contain a literal `|`**, which the pipe serializer truncates
  (`'9 Carmine |'` → `'9 Carmine'`). `evaluate.py --self-test` now fails on this for `--target pipe`
  and warns for yaml. Probably junk in NYU's regex-derived silver — likely fix is to scrub the gold,
  not escape the delimiter. Affects the pipe-target board entries (GLiNER, qwen-2b).
- **`train/sft_qwen.py`'s `--check-termination` probe and `eval/qwen_predict.py` must stay in sync**
  on stop tokens. Both were fixed together in `d476deb`; a change to one needs the other.

---

## Hard-won things that will cost you a cycle if you forget

**Four silent scoring artifacts, all of which looked exactly like model failures:**

| when | what | cost |
|---|---|---|
| 2026-06-18 | eval loaded `AutoModelForCausalLM` vs training's multimodal class; adapter silently not applied | NYU macro read 0.358, was 0.760 |
| 2026-08-04 | `parse_yaml` was last-key-wins; a runaway completion's truncated copy overwrote good values | ~12 points EM |
| 2026-09-01 | `parse_yaml` stripped quotes but never UNESCAPED; Polk's printed ditto marker could not match | 60–90% of rows in five volumes; read as a "Polk floor" |
| 2026-09-01 | pipe target truncates a gold value containing `\|` | 42 nyu rows |

**`evaluate.py --self-test` now round-trips the gold through the real serializer and both parsers.**
It catches two of the four. Run it on a Polk volume after any change to serialization or scoring.
Before this, `--self-test` compared gold against gold *as Python dicts* — which is why three of the
four survived it.

**When a volume or field scores absurdly low, verify the round trip before blaming the model.**
Four for four.

**Local eval works and reproduces CUDA exactly.** You do not need the cluster to score:

```bash
uv venv evalenv --python 3.12
VIRTUAL_ENV=./evalenv uv pip install "transformers==5.14.1" "peft==0.20.0" "accelerate>=1.0" torch sentencepiece protobuf
./evalenv/bin/python eval/qwen_predict.py --base-model Qwen/Qwen3.5-0.8B --model <adapter-dir> \
    --gold data/<vol>_eval.jsonl --out /tmp/p.txt --target yaml --batch-size 16
```
~50 min for the 21-volume panel on an M2. Verified byte-identical to the L40S output on three
control volumes, all three metrics. `qwen_predict.py` handles MPS as of 2026-09-01 — before that
`device_map="auto"` SIGSEGVed with **no traceback**, which looks like the script doing nothing.

**`--base-model` is required** — `sft_qwen.py` trains LoRA, so a run directory is an adapter.
**Watch for `missing adapter keys`** — it means the adapter silently did not apply and you scored
the bare base model.

---

## Who does what

Josh labels gold (browser, on his Mac) and owns the generator and repo. **NYU Torch** (collaborator)
owns training and scoring — they have the pinned environment, a GPU allocation, and have caught two
significant bugs the local side missed. They work from `hpc/README.md` and pull code from GitHub and
data from Hugging Face; nothing is `scp`'d.

The two shareable status pages written for them:
- v5-torch verification — <https://claude.ai/code/artifact/f795b373-e6ec-4787-b7fb-71aacccd13f3>
- 21-volume re-score instructions — <https://claude.ai/code/artifact/db8febe1-6c91-491a-929c-a68f78ff5a22>

Both predate the `parse_yaml` fix and the punctuation decision, so **treat their numbers as stale**
even though the procedures still hold.
