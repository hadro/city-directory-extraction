# Post-OCR correction: is it a step this pipeline wants?

**Written 2026-09-15 on branch `claude/post-ocr-correction-research-ngqd7l`. Measured and
substantially revised 2026-09-20, when the experiment it proposed was actually run.**

Asked: would post-OCR correction — find/replace, or a trained corrector — help the
city-directory extraction pipeline?

**The answer to the question as posed is settled elsewhere and is not re-argued here.** A generic
LLM correction pass between stages 1 and 4 is rejected, for three measured reasons, in
[PIPELINE.md](PIPELINE.md) § "Explicitly deprioritized". This document is about what is left after
that: the generator's noise model, the parallel corpus this project built by accident, and what
measuring both actually returned.

> **Status after the 2026-09-20 run: the original recommendation did not survive it.** The memo
> ranked "re-aim the generator's noise model from a measured confusion table" first and "normalise
> at ingest" second, and called the second one free. Running `ocr_delta.py` showed the measured
> table is not usable, and reading the corpus showed the ingest normalisation is inert where it
> was wanted and wrong where it would fire. Both are marked in place below. What survives is
> narrower and is in §9.

---

## 1. The finding that reframes the question

**This pipeline already has a post-OCR corrector. It is the extractor.**

`synth_persons.py` corrupts the input line and leaves the target clean (`synth_persons.py:85`,
*"OCR noise is applied to the INPUT line only; target stays clean"*). Every training example is
therefore a post-OCR correction pair with an extraction step stapled to it. The model is trained
to read `Brewsler` and write `Brewster` — it just also writes the other seven fields while it does
so.

That matters because of the mechanism this project already established
([TAKEOVER.md](TAKEOVER.md), "copying vs sampling"):

> *If the correct output is a substring of the raw line, copying handles it and the rate is
> irrelevant; if it requires deleting, re-casing or re-ordering, the generator must demonstrate it.*

OCR correction is the second kind — a substitution is never a substring copy. So the model's
ability to correct OCR is **entirely determined by what `add_noise` demonstrates**, and by nothing
else. That makes `add_noise` the lever. This section is the one part of the original memo that
nothing has challenged.

## 2. What `add_noise` produces (measured 2026-09-15, re-measured after the fix 2026-09-20)

`python3 data_prep/measure_synth_noise.py` reproduces every figure here. Run it before and after
any change to `add_noise` or `_NOISE_SUBS`; do not edit these numbers by hand.

| `--noise` | lines touched | edits/line | input CER |
|---|---|---|---|
| 0.35 (shipped) — *before the fix* | 25.7% | 0.431 | 0.0100 |
| **0.35 (shipped) — after** | **33.4%** | **0.652** | **0.0152** |
| 0.6 — after | 58.4% | 1.132 | 0.0262 |
| 1.0 — after | 96.3% | 1.870 | 0.0434 |

Mean generated line length is 43 characters. Against that, the production reference:

> IA hOCR, **CER-all 0.067** (`historical-ocr-eval`, 10 panel volumes)

Three implementation defects were diagnosed on 2026-09-15 and fixed on 2026-09-20 (commit
`f3e2bf8`): `--noise 0.35` touched 25.7% of lines rather than 35% because a chosen confusion pair
silently no-opped when absent from the line; `("ii", "n")` could never fire and was removed; and
every edit landed at the first match, skewing corruption toward the start of the line. A fourth of
the same class, in the comma-deletion branch, was found by re-measuring and fixed too.

**The fix narrows the gap and does not close it.** Training input went from 6.7× cleaner than
production to 4.4× cleaner, and the *ceiling* — every line corrupted at `--noise 1.0` — is 0.0434,
still 1.5× short of 0.067. So the original claim survives the bugs that might have manufactured it:
**the rate knob cannot close this gap; the shape of the corruption has to change.**

None of the ten remaining pairs was derived from this corpus. They are the generic OCR-confusion
list (`m`/`rn`, `l`/`1`, `O`/`0`) — a reasonable prior, and not the same thing as a measurement.
§5 was supposed to replace them. It could not.

## 3. The blind spot: the gold panel cannot see any of this

Labelling convention #2 ([GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md) L118):

> **raw_line = corrected page** — fix OCR misreads in raw_line too (long-s `f`→`s`:
> `fexton`→`sexton`; `Brewsler`→`Brewster`), so raw_line and fields tell the same story.

So the 21-volume panel scores the model on **hand-cleaned input**. Production hands it raw hOCR.
**The regression harness is blind to OCR robustness by construction, and the blindness runs in the
flattering direction.** The 82.0 normalized EM is a ceiling measured on input quality the pipeline
never sees.

**As of 2026-09-20 the size of that cleaning is measured, not asserted: the labellers changed
45.0% of gold rows.** What that 45.0% is made of is §5, and it is not all OCR.

One adjacent claim is *not* supported. `nyu_eval` is the one eval set built on uncorrected OCR, and
the 4B scores 56.2 EM on it against 82.0 on the panel. It is tempting to read that 26-point gap as
the cost of OCR noise. **Don't.** NYU is a third-party CRF parse with three synthesized fields and a
different labelling basis ([GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md) §"Derived vs
transcribed gold"); the gap is confounded beyond use. **The cost of OCR noise to extraction remains
unmeasured.**

## 4. What bounds the upside — the repo's own negative result

**Fabrication does not follow OCR quality.** ([HANDOFF.md](HANDOFF.md) §"Fabrication is driven by
PAGE TYPE") The 1906 ABBYY tier is **13× cleaner** than the 1836 microfilm tier on non-ASCII
garbage (1.0% vs 13.3%), and fabricated-record rates are 5.1% vs 6.1% with overlapping CIs. All
eight 1906 failures were advertising copy, not OCR damage.

> *Better scanning does not reduce fabrication; it produces cleanly-rendered fiction.*

Post-OCR correction is a better-scanning intervention. **It will not touch fabrication**, which is
the pipeline's largest known correctness defect. Anyone proposing correction as a fabrication fix
is proposing something this project has already falsified.

What correction *can* buy is the other failure mode: micro13's leaf 76, *"real entries wrecked by
microfilm OCR (`Clure John, Jaborerrear 107.Gold)) |. .`), degraded but not invented."* Real people
whose records come out damaged. That is disjoint from fabrication, and it is a real cost.

## 5. The parallel corpus — RUN 2026-09-20, and the headline is negative

The gold tool pre-filled `raw_line` from `{stem}_surya.json` and the labeller edited it in place,
so the pre-correction text is still on disk. `data_prep/ocr_delta.py` recovers it. Full report:
[`results/ocr_delta_panel.txt`](../results/ocr_delta_panel.txt).

```bash
python3 data_prep/ocr_delta.py --gold 'data/*_eval.jsonl' \
    --surya-root ../directory-pipeline/output --out data/ocr_pairs.jsonl --noise-table
```

**What came back.** 4,325 aligned pairs over 26 volumes, 259 of them wrapped entries — nearly
double the ~2,300 estimated. 45.0% of gold rows differ from the OCR the labeller started from;
overall CER 0.1829. Damage lands on `address` in 56.7% of changed rows, `name` in 19.0%,
`home_address` 8.8%, `occupation_role` 7.9%, `employer` 7.1%.

**And `--noise-table` does not yield a usable `_NOISE_SUBS`.** The measured table is dominated by
edits that are not scanner confusions at all:

| measured | count | what it actually is |
|---|---|---|
| `' '` → `'\n'` | 276 | joining a wrapped entry |
| `''` → `'-'` | 74 | same, hyphenated wrap |
| `''` → `' av.'` | 36 | labeller completing an abbreviation off the page |
| `' 1/2'` → `'½'` | 11 | labelling convention #4, applied by hand |

The genuine character confusions underneath are 3–11 occurrences each — `('c','e')` 11,
`('l','i')` 10, `('s','f')` 4. That is not a measurement, it is a handful. The examples make the
mechanism plain:

```
ocr : Foster Samuel C. porterhouse, 31 Bowery, h. 75 Mul-
page: Foster Samuel C. porterhouse, 31 Bowery, h. 75 Mulberry
```

That is convention 9a completing a wrap, not a misread being corrected. **The corpus conflates
three edit types — OCR fix, labelling convention, wrap completion — and only the first is a
confusion.** Separating them is a real job, not a flag, and it is the precondition for anything
downstream of this section.

**Two structural problems the original memo did not account for:**

- **This is Surya, not IA hOCR.** The gold panel was OCR'd with Surya; production ingests IA hOCR.
  A confusion table measured here is aimed at **the wrong engine**, however clean it gets. No
  amount of separating edit types fixes this. To aim the generator at production, the pairs have
  to come from hOCR — which means hand-labelling against hOCR, not reusing this panel.
- **One confusion is worth keeping anyway.** `('"', '11')` at 8× is the **ditto mark**, and it
  independently corroborates the Trow 1915 glyph family (`11`, 91,431 lines) and the `44` → `"`
  normalisation already shipped in `ia_volume_to_jsonl.py`. It is the one entry in the table this
  project had a prior reason to expect, and it arrived unprompted.

**Caveats the script prints itself.** 275 rows did not align at `--min-sim 0.55`, which biases CER
**downward** — the worst lines are the ones that drop out. polk1933bk aligned 18 of 49, so its
0.4478 describes 37% of the volume, consistent with its known-degenerate Surya JSON (146 boxes,
355 embedded newlines). Eight gold sets have no Surya pass and are skipped: `nyu`, `ftd`,
`minneapolis`, `micro13_body`, `micro13_frontmatter`, both 1906BPL samples, `bands_1906BPL`.

It also cannot separate a labeller's OCR fix from a labeller's slip. `validate_gold.py`'s
token-drift warnings are the cross-check; a pair seen once is noise, one seen eighty times is the
scanner.

**What survives:** the corpus (`data/ocr_pairs.jsonl`, gitignored, regenerate with the command
above) is the raw material for the **degraded-input panel** that any noise-model change needs
before it can be scored. That was always the more important of its two purposes. It is now the
only one.

## 6. The options, re-ranked after the run

### ~~Tier 1 — normalise at ingest, "do this regardless"~~ — REJECTED 2026-09-20

The original argument: `ia_volume_to_jsonl.py` performs no character normalisation, while gold
convention #5 mandates *"Long-s → `s` everywhere"*, so the model trains on folded input and runs on
unfolded — a free, deterministic, zero-risk fix.

The second half is true; there is no character normalisation in the ingest (`normalize_ditto_lead`
is a leading-token rule, not a character rule). **The first half does not survive contact with the
corpus, and the proposed rule is wrong in both directions:**

- **`ſ` barely exists in the data.** U+017F appears **once across all 34 gold eval sets**, and
  **zero times in 1906BPL's 205,590 ingested lines**. The long-s problem convention #2 describes
  (`fexton`→`sexton`) is an ASCII `f` that an English OCR model produced from a long-s glyph — a
  *lexical* repair, which character normalisation cannot touch and a blind `f`→`s` would destroy
  every real f to attempt. `ocr_delta.py` measures it at 4 occurrences. The mismatch this rule was
  supposed to close stays open.
- **Where `ſ` does appear, `s` is the wrong target.** It is in the 29 microfilm volumes IA OCR'd
  with `-l eng+Fraktur` (`data_prep/survey_ocr_params.py`), and there the correct fix is
  **`ſ`→`f`** — `ſerrymaster`→ferrymaster, `Bunſord`→Bunford — because the Fraktur model is
  emitting `ſ` where the true letter is f. A `ſ`→`s` rule fires on exactly those volumes and is
  wrong every time.

So the rule is inert where it was wanted and harmful where it would fire. The rest of the proposed
tier (curly→straight quotes, `½`→`1/2` per conv #4, dash folding) may well be fine — `½` shows up
11× in the measured table as a hand-applied convention, which is a genuine argument for automating
it — but **each rule needs the same per-rule check, and the tier must not be adopted as a block.**

### Tier 2 — re-aim the generator's noise model — DOWNGRADED, blocked on §5

Still the most promising *direction*, for the reasons in §1: it uses the project's established
lever, costs one training run (~$6), adds zero inference cost and zero production dependency, and
cannot hallucinate, because a model trained on realistic noise decides with the whole line in view
and the extraction objective constraining it.

**But its input does not exist.** The measured `_NOISE_SUBS` it was to be built on is dominated by
wraps and conventions (§5), and is measured on the wrong OCR engine besides. Before this is
actionable, someone has to separate OCR fixes from convention edits in the pairs, and then decide
whether a Surya-derived table is worth aiming an hOCR-facing model with at all. **Do not raise
`--noise` on the strength of the 4.4× figure alone** — that changes the rate, and §2 is the
evidence that the rate is not the part that is wrong.

### Tier 3 — a trained corrector stage. Not justified, and the analysis is unchanged.

1. **A directory line is the adversarial case for LM-based correction.** Correction works by using
   context to constrain a language model. A 43-character directory line is a surname, a trade
   abbreviation and a street number — almost pure named entity, with essentially no linguistic
   context. Worse, the correct output is frequently not the likely one: this corpus contains
   `Dusenbery`, `Dusenbury` and `Duryea` as three printed spellings of one surname on one page
   (trow1884), and conv #2a says a printer's error must be **preserved**. A corrector with a good
   English prior normalises all three and is wrong every time — the same failure the project
   diagnosed when the 54-surname pool made the model regularise unseen surnames.
2. **It has a failure mode the current design does not.** The extractor cannot silently rewrite the
   page, because `raw_line` passes through. A corrector can, and hallucination rises with input
   CER — worst exactly on the microfilm tier where it is most needed.
3. **The measurement to justify it still does not exist.** §5 was supposed to produce it and
   produced a conflated corpus instead.

If tier 3 is ever run, the design that fits this corpus is **constrained, not generative**: use
correction as a candidate generator and let something else adjudicate. Two adjudicators are already
in the repo — the **alphabetical walk** (`alpha_run_filter.py`; a corrected surname must sort
between its neighbours, which needs no threshold) and the **harvested name pools**
(`names/surnames.tsv`, 40k era-skewed census surnames, as a gazetteer). Accept a correction only
when the walk and the gazetteer agree; abstain otherwise and keep the original.

## 7. The stop rule, as revised

The original §7 pre-registered a gate on step 0: *if overall CER is below ~0.02 and damage rarely
lands on `name`, the blind spot is small and the answer is tier 1 and stop.* Measured: CER 0.1829
and `name` damaged in 19.0% of changed rows, which reads as a decisive "proceed".

**That reading would be wrong, and the gate as written cannot be evaluated.** 0.1829 is inflated by
wrap completions and hand-applied conventions that no OCR engine produced, and it is Surya's number
rather than hOCR's. The gate asked a well-formed question of a measurement that turned out not to
answer it. **Rewrite the gate before re-running it:** it must be stated over OCR-fix edits only, on
listing lines, from the engine production actually uses.

The rest of the pre-registration stands, and the part most worth keeping is this:

> **Tier 2 ships only if it gains on the degraded-input panel without losing on the clean panel.**
> A gain on degraded input paid for by a loss on clean input means the model has traded reading
> accuracy for noise tolerance — the wrong trade for a corpus that is roughly half clean ABBYY
> scans. **If degraded-input EM does not move, the noise model was not the constraint: say so and
> stop.** Do not proceed to tier 3 on the theory that a bigger intervention would have worked —
> that is the reasoning the v7 cycle already falsified.

And the prediction, written down in advance so it can be wrong: **tier 2 will move degraded-input
EM and will not move the clean panel by more than noise.** If the clean panel moves materially in
either direction, something other than the noise model changed; diagnose rather than ship.

## 8. The landscape — models and research

> **Verification status, 2026-09-20.** The original was written in an environment where
> `huggingface.co` and `arxiv.org` were egress-blocked, so everything here came from search
> snippets. Egress works from the current environment and the load-bearing claims were re-checked.
> **Verified** items were read from the model card or the paper. **Unverified** items are still
> snippet-level and are marked; do not depend on them without reading the source.

### Corrections made on re-check

- **The attribution was wrong.** *When to Use OCR Post-correction for Named Entity Recognition?*
  (ICADL 2020) is **Huynh, Hamdi & Doucet** — Hamdi is the second author, not the first. Cited as
  "Hamdi et al." throughout the original.
- **And its finding cuts both ways, which the original did not say.** The paper reports that
  post-correction helps when OCR sits at 2–10% CER / 10–25% WER — but also that it is most
  beneficial **above 3% CER / 20% WER, and DEGRADES NER below those rates, through spurious
  corrections.** The original used this paper only as an argument for doing the work. Roughly half
  this corpus is the clean ABBYY tier, where the same paper predicts active harm. That makes
  per-tier application, and abstention on clean input, a requirement rather than a refinement.
- **OCRonos-Vintage, more precisely** (card read): 124M parameters, GPT-2 architecture trained with
  `llm.c`, 18B tokens from Library of Congress / Internet Archive / HathiTrust, hard cut-off
  1955-12-29 with the vast majority pre-1940 and **~65% from 1880–1920**. Instruction format is
  hard-coded as `### Text ###` / `### Correction ###`. The original's "majority 1880–1920" was
  loose; ~65% is the card's number. Still the best era and cost fit, and CPU-runnable.
- **CLOCR-C verified** (arXiv 2408.17428, Jonathan Bourne): >60% CER reduction on the NCSE dataset,
  downstream NER gains reported as increased Cosine Named Entity Similarity, and socio-cultural
  context in the prompt improves performance while misleading context degrades it.
- **HIPE-OCRepair's metric verified, against my own re-check.** A web summariser reported it as
  character-level F1; the competition paper (arXiv 2607.08143) defines the primary metric as
  character-level **Match Error Rate**, `cMER = (S+D+I)/(H+S+D+I)`. The original was right. Noted
  because the error was mine and nearly went into this document as a correction.
- **Kanerva et al. verified as a citation** (arXiv 2502.01205, RESOURCEFUL-2025 pp. 38–47): English
  CER reduced, *"a practically useful performance for Finnish was not reached."* The title is the
  finding.

### Still unverified — snippet-level only, do not cite as fact

- Kanerva's specific **"Llama-3.1-70B cut 18th-century English CER by 38.7% relative"**.
- Thomas et al. (LT4HALA 2024, the BLN600 work): **Llama-2 54.51% vs fine-tuned BART 23.30%**.
- HIPE-OCRepair's **"best adapted system BnF-Mistral ≈0.005 cMER, preference ≈0.9"**, and its
  **abstention / over-correction** findings — the words "abstention" and "over-correction" do not
  appear in the competition announcement I read, so that claim points at a different document.
- Every model card other than OCRonos: `pykale/bart-large-ocr`, `pykale/llama-2-7b-ocr`,
  `yelpfeast/byt5-base-english-ocr-correction`, `viklofg/` and `KBLab/swedish-ocr-correction`,
  `ml6team/byt5-base-dutch-ocr-correction`, `jvdzwaan/ocrpostcorrection-task-1`. The Swedish pair
  remains the closest methodological template (byte-level, historical, explicitly handles `ſ`), and
  `jvdzwaan` is error *detection* rather than correction, which is arguably the more useful half
  here given that detection plus abstention is the low-risk design.

### The one lead worth re-reading if this is ever picked up

**Multimodal LLMs for OCR, Post-Correction and NER in Historical Documents (2025)** — models that
see **the image as well as the text** do substantially better. Relevant because this project throws
the image away at ingest: `ia_volume_to_jsonl.py` reads hOCR and never downloads a page. If
correction ever becomes important enough, re-introducing the line crop is a bigger lever than a
better text-only corrector, and the gold toolchain already crops lines. (Unverified.)

The recurring caution across all of them: hallucination, script-switching and instruction-following
breakdown, all worsening as input CER rises. For a corpus whose output is people's names and
addresses, a corrector that invents a plausible surname is worse than one that leaves
`Jaborerrear` alone.

## 9. What is actually left to do

Ordered, and much shorter than the original — because three of its four steps have now been run and
two of them came back negative.

1. **DONE 2026-09-20.** Both self-tests pass; `add_noise`'s three (four) bugs are fixed (`f3e2bf8`);
   `ocr_delta.py` has been run and its report is committed (`eb71e47`).
2. **Separate the edit types in `data/ocr_pairs.jsonl`** — OCR fix vs labelling convention vs wrap
   completion. Everything downstream is blocked on this and nothing else. A wrap completion is
   detectable (the OCR side ends in `-` or the gold side is strictly longer at a line boundary);
   conventions are enumerable from `GROUND_TRUTH_HANDOFF.md`. What is left after removing both is
   the only honest OCR-error measurement this project has.
3. **Then re-state the §7 gate** over that residue, on listing lines, and decide tier 2 against it.
   Expect the residual CER to be far below 0.1829 and quite possibly below the 3% floor at which
   Huynh/Hamdi/Doucet predict correction does net harm — in which case the answer is *stop*, and
   that is a real and useful outcome, not a failure.
4. **Independently of all of the above: build the degraded-input panel.** It is the fix for §3,
   which is a live measurement defect whatever happens to the noise model — the panel currently
   flatters the model and nobody can say by how much.
5. **Do not** adopt the tier-1 normalisation block, and do not raise `--noise` on the 4.4× figure.
   Both are argued above.

The recurring lesson in [TAKEOVER.md](TAKEOVER.md) is that this project's expensive mistakes were
all confident reasoning about its own corpus that a measurement later reversed — the `synth_dev`
saturation argument, the unprimed Gemini bar, the 14.4% fabrication rate. The original version of
this document closed by saying *"this document is confident reasoning about its own corpus; treat
it accordingly."* It was, and the measurement reversed its top two recommendations within five
days. The warning was the most accurate thing in it.
