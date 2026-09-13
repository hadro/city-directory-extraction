# Plan — a small leaf-type classifier for the page-type gap

**Written 2026-09-10. This is a plan, not a result. Nothing in the "target" columns has been
measured; every number attributed to the repo has.** That distinction is the whole point of writing
it down before running anything — see the pre-registration in
[`results/ab_ditto44_1906BPL_2b100k_PREREGISTRATION.md`](../results/ab_ditto44_1906BPL_2b100k_PREREGISTRATION.md)
for the house pattern this follows.

Companion: [PIPELINE.md](PIPELINE.md) next-step **#11 (page-type detection)**, which this plan is a
concrete proposal for. Method borrowed from Daniel van Strien, *[Agents for data
curation](https://danielvanstrien.xyz/posts/2026/agents-data-curation/)* (2026): an agent proposes
labels, a human adjudicates, a ~149M-parameter encoder is fine-tuned on a couple of hundred examples
via SetFit, and the trained classifier is then applied at corpus scale for a rounding error of the
cost of running an LLM over everything.

---

## STATUS — phase 0 ran, and it moved the unit of analysis

**2026-09-10.** `data_prep/build_leaf_docs.py` is written and self-tested;
`results/leaf_band_structure_1906BPL.py` ran on a 150-leaf seeded sample and is persisted with its
JSON. **It invalidated the leaf-level design below, before any model was trained**, which is the
cheapest possible place to find that out.

Advertising in 1906BPL is not sold by the page. It is sold as a **strip across the head and foot of
ordinary listing pages**. Measured by the vertical position of ditto-lead lines — 42% of this
volume's lines, near-impossible in ad copy, so about as good a label-free marker of "inside a
listing run" as exists here:

| band | ditto-lead / all lines | |
|---|---|---|
| y 0.0–0.1 | 6 / 816 | **0.7%** — head strip, no listing entries |
| y 0.1–0.9 | 16,356 / 36,049 | **45%**, and flat across all eight deciles |
| y 0.9–1.0 | 0 / 708 | **0.0%** — foot strip, no listing entries |

**141 of 150 sampled listing-span leaves (94%) are mixed**: ad strip, clean listing body, ad strip.
Both leaves the existing tools cite by hand as *genuine listing* are this shape — leaf 13 opens with
seven lines of detective-agency advertising, leaf 200 with twelve lines of Upington's own ad and
closes with four more. Leaf 26, cited as an *ad leaf*, has real entries through its middle.

So a four-class leaf label is not merely imprecise, it is unavailable: the `mixed` escape hatch
would take 94% of the listing span and leave the headline number describing the remainder. **The
unit is a band within a leaf, not the leaf.**

It also reprices the comparator. `--interior drop`'s recorded cost of "~172 genuine listing leaves"
is not junk-for-junk — those leaves are mixed, so the cut **discards ~172 clean listing bodies to
remove their strips**. Any band-level instrument dominates any leaf-level decision here by
construction, which is a stronger claim than the one this plan set out to test.

**What the phase-0 probe cannot settle:** the ditto-lead proxy marks where the body *is*. A band
with no ditto lines is equally consistent with "advertising" and with "running head the text filter
already kills", so it bounds the body without proving what the strips contain. Reading the strips
is phase 1's job, and it is now a much smaller job.

### Margin advertising — looked like a fourth and fifth edge, is already handled

Reading leaf 13's page image (rather than its text) showed ads running **vertically up the left and
right margins** as well as across head and foot — which would have meant a rectangle with four
draggable edges, not a band with two. Checked before building it, and it is a non-problem:

- The **left** vertical ad (`LOUIS I. GRIMES, REAL ESTATE`) **was never OCR'd at all** — zero hOCR
  lines begin in the leftmost tenth of leaf 13.
- The **right** one produced three lines, each with the unmistakable geometry of rotated type:
  heights of 1,100–1,253 px against a 23 px median, aspect ratios 12.8–24.6.
- All three are **already dropped** by the stage-1 filters — verified against
  `data/1906BPL_dropped.txt`, which records them as `allcaps`, `bigtype`, `bigtype`.

So the existing geometry filter handles margin advertising, the UI needs two edges rather than
four, and this is recorded here so nobody re-derives it from the page images a third time.

---

## STATUS 2 — 197 leaves labelled, and the model may not be needed

**2026-09-12.** First labelled batch: `data/bands_1906BPL_train.jsonl`, 197 leaves — 193 with a
body, 4 without, **0 irregular** (the band assumption holds on this volume). Analysis persisted in
[`results/band_labels_vs_ditto_rule_1906BPL.py`](../results/band_labels_vs_ditto_rule_1906BPL.py).

The labeller moved both edges on every leaf, by a near-constant amount: **top median −0.0150,
bottom median +0.0150**, with 68% / 69% landing on exactly those values. So the deterministic rule
to beat is not the bare ditto extent but the ditto extent *expanded by a constant*:

| rule | admits no ad | exact both ways | listing lost | ad admitted |
|---|---|---|---|---|
| bare ditto extent | 183/190 | 0/190 | 1,016 | 63 |
| extent ± 0.010 | 183/190 | 133/190 | 179 | 73 |
| **extent ± 0.015** | **183/190** | **150/190** | **131** | **80** |
| extent ± 0.020 | 168/190 | 152/190 | 76 | 114 |

0.42% total line disagreement. **On the aggregate, a trained band model has essentially no room to
earn its keep** — which is exactly what the pre-registered bar existed to find out.

### But the aggregate hides the failure that matters

Of the 80 non-listing lines the ±0.015 rule admits, **71 (89%) come from 6 leaves**. Leaf 904 alone
admits 22 lines of pure advertising — `Law of Real Property`, `Mammoth Storage Warehouses and Moving
Vans`, `PETER F. REILLY, Proprietor`. Each one becomes a fabricated person. The rule is not "96%
right"; it is exactly right nearly everywhere and catastrophically wrong on ~4% of leaves. This is
the same shape of error `entry_rate.py` is documented as having, found again by looking at the
distribution instead of the total.

**The cause is one line, and it is diagnosable.** `44` is ABBYY's reading of the ditto mark *and* a
literal street number. The recurring Temple Bar advertisement carries `44 COURT ST.`, the ditto
regex matches it, and the "first ditto line" lands inside the advertisement. Measured independently
on a fresh 300-leaf sample: a ditto-matching line that is really a bare street address appears on
**3.3% of leaves**, 8 of the 10 found being that same advertisement — agreeing with the 3.7%
failure rate seen against the labels.

### What that means for the instrument

**Do not train a band regressor.** 96% of edges need no model, and the residual is not a geometry
problem: separating `44 COURT ST.` from `44 Wm elk h 86 Laf av` requires *reading the line*, which
no threshold on position or extent can do. The sharp target is a much smaller one — **decide whether
a ditto-matching line is actually a ditto** — and it is the same question the per-volume glyph gate
already asks at volume scale, asked per line.

That also makes it useful beyond this plan: the same decision governs stage 5's cross-line
resolution, where a false ditto gets a surname carried into it.

### Two gaps in this batch, and one that cannot be closed from it

- **Strip contents carry no information.** `head_touched`/`foot_touched` are false on all 193 body
  leaves — every strip label is the untouched default `["advertising"]`. This is precisely what the
  `_touched` bookkeeping was added for. Do not count, analyse or train on the strip fields here.
- **Leaves 39, 129, 134, 165** are marked `has_body: false` with `page_type: null`. All four read as
  full-page advertising, but the file does not say so and it is not inferred.
- **Anchoring, and it is the important one.** These labels were made with the prefill on screen, so
  "human agrees with prefill plus a constant" is partly circular — it measures how the labeller
  adjusted a starting guess, not whether the guess was right. The seven large deliberate corrections
  argue against pure anchoring but do not dispose of it. **The `--blind` evaluation set is now the
  load-bearing measurement rather than an optional rigour step**, and until it exists none of the
  agreement numbers above should be quoted as accuracy. → **Settled below.**

---

## STATUS 3 — phase 1 is done, and the answer is no model

**2026-09-13.** 49 blind leaves labelled (`data/bands_1906BPL_eval.jsonl`), disjoint from training.
239 labelled leaves in total. Full analysis in
[`results/band_labels_vs_ditto_rule_1906BPL.py`](../results/band_labels_vs_ditto_rule_1906BPL.py).

### Anchoring: disposed of

| | train median | blind median | landing on ±0.0150 |
|---|---|---|---|
| top offset | −0.0150 | −0.0163 | train **68%** / blind **0%** |
| bottom offset | +0.0150 | +0.0160 | train **69%** / blind **0%** |

The two labelling processes fail in different ways — anchored keyboard nudges quantise onto
multiples of 0.005, free mouse drags from a neutral 0.10/0.90 start do not. **0% of blind labels
sit on the values 68% of anchored labels sit on, and the medians still agree to 0.0013**, with
overlapping IQRs. The constant is a property of the page layout, not of the starting guess.

### The instrument, and it is three words of change

Take the extent of ditto-lead lines **computed over the lines `text_reject` keeps**, expand by
0.015 of page height at each end.

| label set | extent over | no ad admitted | exact | listing lost | ad admitted |
|---|---|---|---|---|---|
| train | all ditto lines | 183/190 | 150/190 | 131 | 80 |
| train | **filter-surviving ditto lines** | **190/190** | 155/190 | 137 | **0** |
| blind | all ditto lines | 49/49 | 40/49 | 28 | 0 |
| blind | **filter-surviving ditto lines** | **49/49** | 40/49 | 28 | **0** |

**Zero advertising lines admitted across all 239 labelled leaves**, costing 137 lost listing lines
in ~63,000 (0.2%) — the harmless direction, since a lost line is a lost record while an admitted ad
line is a fabricated person.

The `44 COURT ST.` failure closes because `text_reject` **already** calls it `allcaps` and drops it.
No new rule, no threshold, no model, no training data beyond what was needed to *check*.

**The distinction that makes it safe is case, and it took looking rather than reasoning.** Two of
the nine `44 <Street>`-shaped training lines are not advertising at all — `44 Montauk av` (leaf 251)
and `44 Crooke av` (leaf 574) are wrapped continuations indented under an entry ending in `h`, whose
leading `44` is a house number. `text_reject` keeps both, being mixed case. A regex on
`44 <Word> <StreetType>` would have excluded them and been wrong.

### What phase 1 does not settle

- **The blind set contains no ad-intrusion case** — 0 of 49 leaves carry a `44 <Street>` line
  against 9 of 190 in train (P(zero in 49) = 0.09, so chance rather than evidence of absence). It
  independently validates the **offset**; the **fix** is measured only on the training leaves, which
  is where the failures live and is the weaker of the two designs.
- **One volume, one engine, one publisher, one labeller.** `44` is 1906BPL's mark under a per-volume
  gate; whether the 0.015 offset transfers is untested. Phase 2 is now the whole remaining question.

### Phases 3 and 4, revised

Phase 3 (full-page ad leaves) survives: 4 train leaves were marked `has_body: false` and the rule
needs a stated behaviour when a leaf has fewer than 20 filter-surviving ditto lines. Phase 4 still
stands, but what ships is a rule, not a model — so `band` can be written at ingest in
`ia_volume_to_jsonl.py` rather than bolted on, and the queue is for leaves where the extent is
undefined rather than for low-confidence predictions.

Phases below are revised accordingly. The strategy — small model, agent-proposed labels, human-read
holdout, ship as a queue — is unchanged; the unit and the metric are not.

---

## Why this problem and not one of the others

The model never refuses. Every non-entry line that survives stages 1 and 3 becomes a confidently
structured fake person. `entry_rate.py` puts that at **10.4% on 1906BPL (ABBYY) and 20.7% on 1836
microfilm (tesseract)** — call it **~20,700 fabricated records in one volume**, at a proxy
hand-validated to 97.5% on 40 read lines.

Two facts make this the right place to spend a classifier, and they are the reason to do it here
rather than on the ditto dispute rate or the missing quality proxy:

**The target is large and it clusters.** [PIPELINE.md](PIPELINE.md) stage 2 measures **166 of 1,207
leaves inside 1906BPL's listing span (13%) as ad runs *between* letter blocks** — the three largest
being M→N (88 leaves), S→T (58) and B→C (39), all spot-checked as display advertising. Advertising
does not arrive one line at a time; it arrives in page runs. A per-leaf decision therefore gets a
whole run right or wrong at once, which is both the opportunity and the risk.

**Correctness and cost point the same direction, which is rare.** Stage 4 runs at 0.38–0.6 lines/s;
199,012 lines is ~6 days of local compute. Any line the classifier removes before stage 4 is GPU
time saved *and* a fabrication prevented. There is no trade to manage.

## Why a learned model, when three leaf-level heuristics have already failed

This matters more than the method, so it goes first. `detect_listing_bounds.py` and
`alpha_run_filter.py` between them have already measured that **leaf granularity is not the
problem** — specific hand-designed leaf *features* are:

| what was tried | measured outcome |
|---|---|
| modal first-letter share | genuine listing leaf 13 = 34%; **ad leaf 819 = 38%**. The ad page scores *higher*. |
| modal-letter confidence floor | ad/prose leaf 130 scores **0.96**; a 0.70 floor collapsed the line cut to 0.2% |
| voter share | listing leaf 200 = 17%; **ad leaf 26 = 28%**. Inverted again. |
| column detection from hOCR boxes | wrapped-line indents make left edges multi-modal; dropped 64% of a page including clean entries |

Every one of those reads a *statistic over the page's shape*. None of them reads the page. The
reason ad leaf 819 out-scores listing leaf 13 on sort-key share is that ad copy is full of business
names, which are alphabetical-looking by accident — but ad copy and listing copy do not share a
vocabulary, a syntax, or a line length distribution. `Telephone 1234 Main — Estimates Cheerfully
Furnished` and `Ackerman And'w J foreman h 460 Ralph av` are trivially separable to anything that
reads tokens, and indistinguishable to anything that counts first letters.

**That is the hypothesis this plan tests, and it is falsifiable:** the failures above are failures
of feature design, not of leaf granularity, and a text encoder over the leaf's own words clears the
bar the four heuristics could not.

It might not. Ad leaves in these books carry real addresses and real surnames, and the encoder may
find them as confusable as the sort-key statistic did. That result would be worth having too — it
is the evidence that pushes #11 to the VLM-on-leaf-image option, which is a much larger job.

---

## The comparator, fixed in advance

This is the part that makes the experiment decision-bearing rather than a demo, and the repo
already has it: `detect_listing_bounds.py --interior` offers a measured precision/recall pair on
1906BPL.

| setting | ad leaves excluded | genuine listing leaves lost |
|---|---|---|
| `--interior keep` (default) | 199 | 0 |
| `--interior drop` | 384 | **~172** |

Phase 0 changed what that table means. Because 94% of listing-span leaves are mixed, `--interior
drop` is not excluding 384 ad leaves and losing 172 junk ones — it is **removing ~172 clean listing
bodies along with their strips**. The leaf-level baseline is therefore weaker than it looked, and
beating it is no longer an interesting bar on its own.

**Pre-registered primary comparison, restated at band level.** The quantity that matters is lines,
not leaves, and it is measurable against both existing baselines on the same volume:

> On the 50 human-read holdout leaves, score each *line* as listing / non-listing. Report
> **non-listing lines removed** and **listing lines destroyed**, for: (a) `--interior keep`,
> (b) `--interior drop`, (c) the band model. **The band model must remove more non-listing lines
> than `--interior drop` while destroying fewer listing lines than `--interior keep`** — i.e. it
> must beat both baselines on both axes at once, not trade between them.

That is a demanding bar and it is the honest one, because the phase-0 structure says it should be
achievable: the boundary at y≈0.12 and y≈0.87 is sharp, not gradual.

**The deterministic baseline must be beaten too, and it is nearly free:** cut at the first and last
ditto-lead line of each leaf. Report it in the same table. If a trained model does not beat *that*,
ship the one-line rule — though note it cannot be the evaluation, since it is the same signal the
phase-0 measurement used, and it degrades by construction on volumes with sparse or unrecognised
ditto marks (every pre-1850 book, per the per-volume glyph gate).

### Decision rule

- **Beats both baselines on both axes** → proceed to phase 2 (generalization), wire in as a queue.
- **Beats `--interior drop` on junk removed but destroys more listing lines than `--interior keep`**
  → a partial win, reportable as "a better interior cut", not as page-type detection.
- **Does not beat the first-and-last-ditto rule** → stop. Ship the rule, record the null with its
  predictions, and #11's remaining gap is the full-page ad leaves, which is a different and smaller
  problem than the one this plan opened with.

A null here is a publishable result and **must be persisted with its per-leaf predictions**, not
summarized and discarded — that is the specific failure that cost 4.16 h on the publisher A/B.

---

## Phase 0 — Build the leaf corpus (no ML) — **DONE**

`data_prep/build_leaf_docs.py`. One JSON object per leaf. Self-tested; whole-volume run on 1906BPL
is ~1 s/6 leaves of byte-seek, no network beyond the cached hOCR.

**Build the document from the leaf's *pre-filter* text.** This is the one design decision that is
easy to get silently wrong: stages 1 and 3 remove running heads, banners and page furniture, and
those are exactly the tokens that say "this is not a listing page." Filtering first would hide the
signal from the classifier.

The union is free from artifacts that already exist — `data/1906BPL_lines.jsonl` (199,012 kept,
`context.leaf` on every row) ∪ `data/1906BPL_dropped.txt` (93,781 rows, leaf in column 1, drop
reason in column 2) reconstructs all 292,793 candidate lines across 1,240 leaves. Reading the hOCR
directly is the independent path and should be used for at least one volume as a cross-check, the
same way stage 2 checks both.

Carry alongside the text, because they are free and a linear model over them is the ablation
baseline the encoder has to beat:

- `n_lines`, median line length, share of lines with a digit, share ALL-CAPS
- modal first letter and its share — **the feature already measured not to work alone**, included
  precisely so the writeup can say whether the encoder adds anything over it
- the drop-reason histogram from `dropped.txt` (`banner` / `bigtype` / text-filter)
- `alpha_run_filter`'s per-leaf cut fraction
- leaf position within the volume, and within its letter block

Median leaf is **167 kept lines** (p10 125, p90 179), so a full leaf is on the order of 1–1.5k
tokens. ModernBERT's long context helps here but sentence-transformer wrappers commonly truncate at
512 — **pre-register the representation rather than tuning it after seeing scores**: primary is the
full leaf text at `max_seq_length=1024`; if that truncates more than a third of leaves, fall back to
a deterministic evenly-spaced 60-line sample, decided *before* looking at any accuracy number.

Still to build: the labeling interface (next section).

## Phase 1 — Label bands on 250 leaves, train, run the comparator (~1–2 days)

**Labels, revised after phase 0.** Not a leaf class. Per leaf:

- `has_body` — does this leaf contain any listing at all? (the 166 full-page ad leaves are `false`)
- `body_top`, `body_bottom` — the y-fractions bounding the listing body
- `strip_kind` for the head and foot bands — `advertising` / `running-head` / `front-matter` /
  `index-or-back-matter` / `empty`. **This is the part the phase-0 probe explicitly could not
  settle**, and it is what decides whether a strip is a fabrication risk or something the text
  filter already handles.

A leaf whose ads are interleaved *within* the body rather than banded gets `irregular` and is
excluded from the headline with its count reported. Phase 0 suggests that is rare here; if it turns
out common, that is the next finding and the plan bends again.

**The interface — BUILT.** `data_prep/label_leaf_bands.py` + `.html`. The page image with two
draggable edges, hOCR line boxes overlaid with ditto-lead lines picked out in green, keyboard
navigation, save-to-JSONL over a localhost POST. Self-tested; the embedded JS is parse-checked.

```bash
# training set — prefilled from ditto extent, boxes overlaid
python3 data_prep/label_leaf_bands.py --ident 1906BPL --n 200 --seed 20260910 \
    --out data/bands_1906BPL_train.jsonl

# evaluation set — no prefill, no overlay, disjoint from training by construction
python3 data_prep/label_leaf_bands.py --ident 1906BPL --n 50 --seed 20260911 --blind \
    --exclude data/bands_1906BPL_train.jsonl --out data/bands_1906BPL_eval.jsonl
```

Vendored from `directory-pipeline/pipeline/select_pages.py`: the localhost-server + POST-to-save +
`/done` mechanism and the external-HTML-template split, which is the fiddly part and was already
solved there. What changed: that tool globs local `*.jpg` and this repo downloads no images, so
page images are fetched on demand for sampled leaves only into `data/ia_cache/pageimg/` (~400 KB
each, ~250 of them, and **the model never sees them** — the picture is for the human eye); its
include/exclude model became two band edges plus a strip class; and the template is filled by token
replacement rather than `str.format`, because the file is mostly CSS and JS braces and doubling
every one of them invites a silent syntax error.

Two correctness details that took measuring rather than assuming. The hOCR page box and the IA page
JPEG **share a pixel space per leaf** — leaf 13 is 2016×3048 in both — so a y-fraction maps to the
image with no scaling; but they are *not* constant across leaves (leaf 0 of the same volume is
2550×3301), so everything is a fraction of that leaf's own `page_dims`. And `--blind` does not merely
hide the prefill in the UI: the box coordinates are **absent from the served HTML entirely**, so the
overlay cannot be recovered from view-source.

Labeling a band is a drag, not a reading task.

**Labeling protocol, and the hazard in it.** Van Strien's method has the agent generate the labels.
That is fine for training and *not* fine for evaluation in this repo, whose recurring failure mode
is selecting on what a filter kept. So:

- **Training set (200 leaves):** agent proposes a label + one-line reason from the contact sheet;
  human adjudicates in bulk, overriding by exception. Fast, and errors here cost accuracy, not
  validity.
- **Evaluation set (50 leaves): human-read only, never seen by the agent, sampled by seeded random
  from listing-span leaves before any model exists.** The classifier's headline number must never be
  its agreement with the agent that trained it.
- Seed the sampler toward the known-hard cases already identified by hand — ad leaves 26, 130, 145,
  819 and listing leaves 13, 200 — but record them as a named hard subset scored separately, not
  blended into the headline.

**Train.** The band framing makes the model *smaller*, not larger. A line-level binary — is this
line inside the listing body — with the line's text plus its y-fraction and its neighbours' labels
is a sequence-labeling problem over ~200 leaves × ~170 lines ≈ 34,000 labeled lines obtained from
250 band drags. That is a large training set acquired at the cost of a small one, and it is the
direct payoff of labeling bands instead of leaves.

SetFit over a ~149M ModernBERT encoder, per the post, on line text; y-fraction and the free features
enter as a second-stage feature. On this data that is minutes on the M2, not hours — **no HPC and no
HF Jobs needed**, which matters because `hpc/README.md` establishes that Torch compute nodes have no
outbound internet and everything must be pre-staged. Corpus-scale inference is ~293k lines/volume ×
291 volumes with a 149M encoder — hours per volume locally against the Qwen stage's 6 *days*, and
the natural place for the blog's rented-GPU option if it needs one.

**Also train the ablation:** logistic regression on y-fraction and the phase-0 free features alone,
no text. Given how sharp the phase-0 boundary is, this may well be most of the result. If it
matches the encoder, ship it — it is auditable, has no dependencies, and this repo has been burned
by complexity that bought nothing.

**Report:** the pre-registered lines-removed / lines-destroyed table above against all three
baselines, the strip-class confusion matrix, the hard-subset score, and the encoder-vs-ablation
delta.

## Phase 2 — Does it survive a change of engine and publisher? (~1 day)

The `44` finding is measured on one volume, one engine, one adapter, and PIPELINE.md flags that as
the most load-bearing untested assumption in the pipeline. Do not repeat the pattern.

**Hold out by volume, never by leaf** — leaves within a volume share typography, OCR engine and
advertiser set, so a leaf-level split reports memorization. Label 40 evaluation leaves each from a
tesseract-microfilm volume (`micro_IABROOKLYN_0013` tier, where the fabrication rate is 2× worse and
the payoff correspondingly larger) and one non-Upington publisher, train on 1906BPL only, and score
cold.

**Re-run `leaf_band_structure` on each first — it is one command and it is the cheap half of this
phase.** The strip layout is a publisher's advertising convention, not a property of directories:
`franks1786` is a single-column folio with no display advertising at all, so its band structure
should be flat and the whole instrument inapplicable. Knowing which volumes are banded and which are
not is worth having independently of whether any model gets trained, and it is the generalization
question asked directly rather than through a model's error bars.

Pre-registered: **a drop of more than 15 points across the engine boundary means the model is
learning ABBYY's artifacts, not page structure**, and it must be retrained per OCR tier rather than
shipped as one corpus-wide model. That is a fine outcome; it just has to be known before it is
claimed otherwise.

## Phase 3 — Full-page ad leaves, only if phases 1–2 pass

Phase 0 absorbed the old phase 3 — line-level *was* the concession to mixed leaves, and mixed leaves
turned out to be the norm, so the band model is already line-level. What is left over is the
opposite population: the **166 full-page ad leaves in the letter-block gaps**, which have no body to
bound. The band model handles them as `has_body = false`, and that prediction needs its own number
because the 150-leaf phase-0 sample contains them only in proportion.

These are also the easy case — a leaf with zero ditto-lead lines and no alphabetical run is already
flagged by `detect_listing_bounds` as a gap. The open question is only how many are missed, not
whether the signal exists.

## Phase 4 — How it lands in the pipeline

**As a queue and a marked field, not a gate.** Two reasons, both already established in the repo:

1. The van Strien classifier scored **65.8% accuracy / 0.556 macro F1** on its own task. Assume a
   comparable ceiling. A silent filter at that accuracy would destroy real entries at a rate this
   project could not detect, because — per stage 6 — there is no whole-volume gold to catch it.
2. It is what everything else here does. The ditto review queue (40 candidates), the cross-line
   dispute queue (31,500 rows), `AMBIGUOUS` edges in stage 2: nothing in this pipeline silently
   picks a winner on an uncertain call.

So: write `band` (`head` / `body` / `foot`) and `band_confidence` into `context` per line, add a
`--dump-flagged` review listing ranked by confidence, and **make it opt-in to cut**. This also
resolves the same structural conflict PIPELINE.md next-step #3 raises for `alpha_run_filter` — mark,
don't drop, so ditto expansion never loses an antecedent.

One bonus the leaf framing did not have: a per-line band label is **orthogonal evidence for the
cross-line ditto dispute (next-step #6)**, which PIPELINE.md says is concentrated at leaf and column
boundaries. A ditto whose antecedent search would cross a head or foot strip is a dispute the band
model can flag without any new labeling.

---

## Effort and cost

| phase | effort | compute |
|---|---|---|
| 0 corpus + band structure | ~½ day | none | **done** |
| 1a labeling UI | ~½ day | none | **done** |
| 1b 250 band drags, train, comparator | 1–2 days (labeling dominates) | minutes, local |
| 2 cross-engine generalization | ~1 day | minutes, local |
| 3 full-page ad leaves | ~½ day | minutes, local |
| 4 pipeline integration | ~1 day | hours for a full-corpus pass |

Phases 0–2 are the experiment; **phase 1's decision rule is the gate**, and stopping there on a null
costs about three days and produces a result worth writing down.

## What this plan cannot settle

- **It does not measure record quality.** A line correctly placed in the listing body says nothing
  about whether the model parses it well. That still needs #10 (a whole-volume gold slice), and the
  two should not be conflated in any writeup.
- **It cannot use the gold slice twice.** If #10 is labeled first, those lines are either the
  model's training data or its evaluation data. Not both.
- **The band assumption is itself the ceiling.** The instrument assumes advertising is banded. Where
  it is interleaved — and phase 0 only shows that is uncommon *in 1906BPL* — the model cannot help,
  and `irregular` leaves are excluded from the headline by construction. Report their count next to
  it every time.
- **One corpus, one language, one genre.** Everything here is NYC directories 1786–1925. Nothing
  about it transfers to another collection without relabeling.
- **The agent-labeled training set carries the agent's biases into the model.** The human-read
  held-out evaluation set is the control for that, and it is the reason phase 1 is not simply "run
  the notebook from the blog post."
