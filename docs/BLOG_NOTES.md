# Blog notes — Fine-tuning a tiny open model to structure historical city directories

> Notes toward a post, drafted 2026-06-18. Companion: [HANDOFF.md](HANDOFF.md), [plan.md](plan.md).

> # ⚠️ STALE AS OF 2026-08-04 — DO NOT PUBLISH ANY NUMBER BELOW
>
> Every figure in this draft is from **v1** scored on **NYU only** against an **unprimed** Gemini,
> and NYU was scored including three fields that turned out not to be ground truth. Four things
> have since changed, and they invert the conclusion:
>
> 1. **The model is five cycles newer.** Panel-wide (18 volumes, 1169 lines): **v5 = 0.826 macro /
>    0.875 micro / 61.5% EM**, versus the v1 NYU figures quoted below (0.760 / 0.755 / 26%).
> 2. **The Gemini bar below is the *unprimed* one** (0.672 / 0.910 / 70%). It had been given a
>    stale labeling contract. Re-primed with the current contract Gemini scores **0.790 / 0.844 /
>    58.0%** on the panel — the only bar that should ever be cited.
> 3. **The headline conclusion is now false.** "Gemini still leads decisively on micro-F1 and
>    whole-row EM" was true of v1; **v5 leads the primed bar on all three aggregates.**
> 4. **NYU's `spouse_name`, `race_designation` and `is_business` are synthesized by our own
>    regexes**, not transcribed, and disagree with the printed page. NYU must be scored with
>    `--exclude-fields`. Restricted NYU macro: v5 **0.810** vs v4 0.797.
>
> **What survives, and is arguably the better post:** the *method* — fix the data, not the model —
> and the measurement lessons, which are now much sharper than when this was drafted. Every
> remaining gap in v1 was closed by changing the **generator** and retraining, with no change to
> model size or architecture (`name` 0.52→0.77, `address` 0.44→0.85, `home_address` 0.07→0.84,
> `occupation_role` 0.70→0.89).
>
> **Four real war stories worth writing up, all with the same shape — a metric that lied:**
> - the **eval-loader bug**: train and eval loaded different model classes, so the LoRA adapter
>   silently didn't apply and a trained model scored at the untrained floor;
> - the **stale-prompt baseline**: our "we beat Gemini 17/18 volumes" result was mostly an artifact
>   of testing Gemini against a labeling contract we'd since changed;
> - the **runaway-generation bug**: v5 trained to loss 0.009 / token-acc 0.998 and still never
>   learned to emit its stop token; combined with a last-key-wins YAML parser this faked a
>   12-point EM *regression* that never happened;
> - the **derived-gold trap**: we scored a model against labels our own regex had invented, so a
>   model that got *more* faithful to the page scored *worse*.
>
> Rewrite from [HANDOFF.md](HANDOFF.md) and
> [GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md); do not copy figures from below.

## Working title ideas
- "Getting a 0.8B model within striking distance of Gemini at reading 1880s city directories"
- "Synthetic data in, structured history out: fine-tuning a tiny extractor"
- "You can train a small open model to do this — here's the whole recipe (and how to measure it honestly)"

## The one-paragraph pitch
Historical city directories (the phone books of the 1800s–1900s) are a goldmine for genealogy and
urban history, but each entry is a dense, abbreviated line of text. We wanted to turn lines like
`Smith John, clk, 12 Pine` into clean structured records — without paying a frontier API per line
forever. So we **generated our own synthetic training data**, fine-tuned a **0.8B-parameter open
model** (Qwen3.5) with LoRA for about $10 on a rented GPU, and **evaluated on real archival gold**
from NYU. The result: a tiny, free-to-run model that's **competitive with Gemini 3.1-flash-lite on
per-field accuracy** (macro-F1 0.760 vs 0.672) — though Gemini still leads clearly on
volume-weighted accuracy and whole-row correctness (micro-F1 0.910 vs 0.755; 70% vs 26% exact
rows). The most useful lesson turned out to be about *measurement*: which F1 you report completely
changes the story.

## The task, concretely
Each directory line → one record with 8 fields:
`name, is_business, spouse_name, race_designation, occupation_role, employer, address, home_address`.

Two directory "dialects" to cover the range: **Tulsa 1921** and **NYC Trow/Doggett, 1850–1890**.
Input example → output:
```
[dialect=nyc; year=1860] Smith John, clk, 12 Pine
->
name: "Smith John"
is_business: false
occupation_role: "clk"
address: "12 Pine"
```

## The recipe (the part people can copy)

### 1. Make the data instead of hunting for it
Labeled historical data is scarce and often license-encumbered. Rather than scrape, we **wrote a
generator** (`synth_persons.py`) that composes realistic directory lines *and* their ground-truth
records from name lists, occupation lists, street lists, and per-dialect formatting rules. Profiles
(`--profile {tulsa,nyc,mix}`) bake in each city's conventions. This gives unlimited, perfectly
labeled, license-clean training data. We generated **100k** training lines, a **1k** dev split, and
a **3k** smoke set.

Precedent that this works: Mattingly's "3.6M names" project and van Strien's `small-models-for-glam`
both train small models on synthetic/programmatic data for GLAM (galleries, libraries, archives,
museums) tasks.

### 2. Pick a small base model — and the right output format
- **Model:** `Qwen/Qwen3.5-0.8B`. Small enough to run on a laptop/free Colab T4, capable enough to
  learn this with LoRA.
- **Output format: YAML, not a pipe-delimited / positional format.** This matters more than it
  sounds. A positional format (`name|is_business|...`) breaks catastrophically the moment the model
  omits an empty field — every later column shifts, and one mistake corrupts the whole row. (We
  measured a positional format mangling ~half of all rows.) YAML names every key, so a dropped field
  is just an absent key, not a cascade. Train *and* evaluate in the same format.

### 3. Fine-tune with LoRA on rented GPUs
- LoRA (low-rank adapters) means you train a ~50 MB adapter, not the whole model — cheap and fast.
- We used **HuggingFace Jobs** to rent a GPU per run: upload a self-contained script, it installs
  deps and runs in the datacenter. The winning run was **0.8B, 100k examples, 3 epochs, A100,
  batch 64 → ~4 hours, ~$10.** (It *should* be ~30 min — Qwen3.5 needs custom fast kernels
  (`flash-linear-attention`, `causal-conv1d`) that we didn't get installed, so it fell back to a
  ~10× slower path. Worth installing if you're cost-sensitive or scaling up; we ate it because a
  one-off $10 was fine.)
- The trained adapter gets pushed straight to the Hub.

### 4. Evaluate on REAL data, not held-out synthetic — and pick your metric carefully
Two disciplines kept us honest. First, **score on real archival gold from NYU**, not synthetic dev
(which converges to ~1.0 and tells you nothing about the real world). Second — and this is the part
most write-ups skip — **the choice of F1 changes the conclusion**:
- **macro-F1** averages each field equally. (Watch out: if you naively include fields the gold
  doesn't even contain, they score 0 and unfairly tank the number — average only over *present*
  fields.)
- **micro-F1** pools every field decision, so it's weighted by how often each field appears —
  dominated by the high-volume fields (`name`, `address`).
- **whole-row exact match** — the fraction of lines reconstructed *perfectly*.

Anchors: **GLiNER zero-shot** (no training) as a floor; **Gemini 3.1-flash-lite** (a frontier API)
as the bar.

## Results (NYU real gold)
| model | macro-F1 | micro-F1 | whole-row EM | notes |
|---|---|---|---|---|
| GLiNER zero-shot (floor) | 0.381 | 0.594 | 8% | no training |
| Gemini 3.1-flash-lite (bar) | 0.672 | **0.910** | **70%** | frontier API, per-call cost |
| **Qwen3.5-0.8B fine-tune (ours)** | **0.760** | 0.755 | 26% | runs locally, free to share |

On held-out synthetic data the model is ~perfect (macro ~1.0) — the synthetic task is fully learned,
so all the remaining work is the **synthetic→real gap.**

**The honest picture — and the headline lesson.** Report *macro-F1* and our 0.8B "beats" Gemini
(0.760 vs 0.672); report *micro-F1* or *whole-row exact match* and Gemini wins decisively (0.910 vs
0.755; 70% vs 26%). Both are true. We edge Gemini on the *rare* fields (averaged equally by macro),
but Gemini is far better on the *common* ones (`name`, `address`) and at getting whole rows exactly
right — which is what actually matters for a production pipeline. **So the honest claim isn't "we
beat Gemini"; it's "a $10 0.8B model gets competitive on per-field accuracy, and the remaining gap
is concentrated in `name`/`address`."** That's the next lever: make the generator look more like the
messy real thing (OCR noise, abbreviations) so the high-volume fields catch up. (And the broader
lesson: always say *which* F1 — a single number can tell opposite stories.)

## Practical gotchas worth knowing (will save you a day)
These are the non-obvious things that genuinely matter if you replicate this:

1. **Use a named-key output format (YAML/JSON), never positional.** See above — one dropped field
   shouldn't corrupt the whole record.
2. **Modern Qwen base models are multimodal.** Two consequences if you LoRA-fine-tune one:
   - `target_modules="all-linear"` will also adapt the unused **vision tower** — set
     `exclude_modules=["visual"]` (or load the text-only model class at train time) to avoid wasting
     ~half the adapter on layers you'll never use.
   - **Load the same model class for training and inference.** `SFTTrainer(model="<id>")` auto-loads
     the full multimodal model; if your inference script defaults to the text-only
     `AutoModelForCausalLM`, the LoRA keys won't line up and the adapter **silently fails to load** —
     your "fine-tuned" model is secretly the base model. Tell-tale sign: a trained model that scores
     like an untrained one, plus a "missing adapter keys" warning. Match the classes (we load
     `AutoModelForImageTextToText`).
3. **Evaluate on real data from day one.** Synthetic dev numbers look great and mean little; the real
   gold set is the only one that tells you if you're done.
4. **Rented-GPU jobs are async and time-capped.** Set a generous `--timeout` (you pay for actual
   runtime, not the cap), and wait for the "done" sentinel before kicking off evaluation, or it'll
   404 on a half-uploaded model. To skip a multi-GB model download on slow internet, run inference
   *as a job too* and push just the tiny predictions file back.

## What's next (roadmap, if useful for the post)
- Close the synthetic→real gap: add OCR noise / abbreviation variety to the generator so real `name`
  and whole-row accuracy climb.
- Train the full family (0.8B / 2B / 4B) at larger scale and broaden evaluation to more cities
  (French trade directories, Tulsa, Minneapolis) to show cross-domain transfer.
- Publish the model, the synthetic dataset, and model/dataset cards so others can build on it.

## To verify before publishing
- Re-confirm the headline numbers and the exact base-model / library versions for reproducibility.
- A clean retrain with `exclude_modules=["visual"]` to confirm the vision adapter contributed nothing.
- Links: model + dataset on the Hub, the generator script, the eval harness.
