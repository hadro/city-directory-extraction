# The `banner` correction — why every 1906BPL figure has a before and an after

**Made 2026-09-13, branch `ditto-resolution`.** One line of `ia_volume_to_jsonl.py` changed and it
moved the volume's kept-line count by 6,091. This is the canonical record: what was wrong, what the
numbers are now, and **which published figures are pinned to the pre-correction artifact and stay
correct only against it**.

If you are here because a figure did not reproduce, jump to
[What is pinned to the old artifact](#what-is-pinned-to-the-old-artifact).

---

## What was wrong

Stage 1's geometry filter drops a line whose box is wider than `WIDE_RATIO ×` the page's own
median line width, on the reasoning that display advertising crosses columns and a body entry does
not. The ratio was fine. **The normalizer was contaminated.**

Line widths on a listing page are **bimodal**: a short-fragment mode (wrap tails like `Laf av`,
ditto stubs, gutter specks, OCR noise) and the body mode. On 1906BPL leaf 83, 124 of 312 lines sit
under 150px against a body cluster at 350–600px. The plain median therefore lands at 400 — the *low
edge of the body* — and `1.5 × 400 = 600` falls **inside the body's own upper tail**, whose maximum
on that leaf is 599.

Measured on 300 random content leaves (49,918 lines surviving text+bigtype), the rule was killing

> **1,038 entry-shaped lines to catch 951 non-entries — a 1:0.9 ratio.**

A coin flip. 58% of its drops were single-segment lines that no wrap-join had touched, e.g.
`Passiglia Jos barber h 708 DeKalb av`.

## How it hid for so long

The docstring said, truthfully, *"Measured on six 1906BPL leaves: 32 drops, every one inspected a
running head, an ad headline, or OCR garbage. No false positives found."* Six leaves could not have
shown a class this size and a bigger sample was never run.

The only figure being watched at volume scale was the **keep rate**, and a keep rate cannot
distinguish cutting advertising from cutting people. Both look like "68.0%".

It was found by reading `--dump-dropped`, which is the entire reason that flag exists. The module
docstring's own warning — *"Selecting only on what a filter kept, and never looking at what it cut,
is the recurring trap this project has already paid for three times"* — was describing this bug
before anyone had found it. Four times now.

## The fix

`ia_volume_to_jsonl.body_width()`: drop the fragment mode, then take a **median** of what remains.

```python
BODY_WIDTH_FLOOR = 0.5
def body_width(widths):
    m = statistics.median(widths) or 1.0
    body = [w for w in widths if w >= BODY_WIDTH_FLOOR * m]
    return (statistics.median(body) if body else m) or 1.0
```

`WIDE_RATIO` 1.5 → **1.4**, now applied against `body_width` rather than the plain median.

**A median and not a high percentile, deliberately.** `p90 × 1.15` scores better than anything else
on 1906BPL — 3 entry-kills against 560 catches — and was rejected, because where advertising is a
large share of a page's lines **p90 *is* the ad width**. It lets `SHEFFIELD & BIRMINGHAM SILVER
PLATED` and `IMPORTER of CHINA, GLASS &` through on micro_IABROOKLYN_0013, which are the two ad
lines the thin tier was checked against in the first place. The threshold needs a statistic the
junk mode cannot drag down and the ad tail cannot drag up.

### Measured, three volumes, both OCR tiers, 1798–1906

Entry-shaped lines killed / non-entry lines caught, per volume sample:

| normalizer | 1906BPL | micro13 | longworth1798 | ad-marker lines kept |
|---|---|---|---|---|
| `median × 1.5` (old) | 1,038 / 951 | 16 / 87 | 84 / 589 | 87 (78%) |
| `body_width × 1.4` (new) | **101 / 723** | 19 / 80 | **36 / 330** | **87 (78%)** |

Identical advertising retention, a tenth of the entry kills on the thick tier.

Hand-read every delta cell. 1906BPL: 0 newly-killed, 937 rescued per 300 leaves, all clean entries
(`44 Mich'l carp'r h 2727 Fort Hamilton P'kway`). longworth1798: 1 newly-killed against 49 rescued.
**The one regression is micro13** — 4 newly-killed against 1 rescued in 2,840 lines, and all four
are real entries with OCR trash appended that makes them wide (`Mason Nehemiah, merchant 116 High
iple |`). A wash on the thin tier, accepted for the thick-tier gain.

### Whole-volume effect

| | before | after |
|---|---|---|
| 1906BPL kept | 199,012 (68.0%) | **205,103 (70.1%)** |
| 1906BPL `banner` drops | 9,492 | **3,401** |
| micro13 kept | 2,889 (83.5%) | **2,899 (83.8%)** |
| micro13 `banner` drops | 109 | **99** |

Candidates are unchanged (292,793 / 3,460) — joining happens before filtering and did not move.

**+6,091 lines enter the 1906BPL corpus**, disproportionately real entries.

### Caveat on the entry-shaped counts

"Entry-shaped" is a **regex proxy** — an occupation token plus a digit plus 4+ words — not gold.
During the measurement it was caught missing `roofer`, `tinsmith` and `cloakmkr`, so it
**undercounts** entries and the true rescue is larger than the numbers above. The direction is
established by hand-reading samples of every delta cell, which is the evidence that matters;
treat the absolute counts as estimates. Scoring this properly against
`data/entry_labels_1906BPL.jsonl` would need a labelling pass aimed at wide lines — the 140
existing labels are a general volume sample and almost none land on them.

### Unchanged failure mode

A leaf that is **entirely one display advertisement** has no body mode to find, so `body_width`
calibrates to the ad exactly as the plain median did. That is what `context.band` and the
page-type classifier are for. This change does not touch it.

---

## What is pinned to the old artifact

`data/1906BPL_lines.jsonl` **was not regenerated.** It still holds the 199,012 lines produced by
the pre-correction rule. Everything below reads that file and therefore **still reproduces exactly
against it** — nothing is retracted, and no published number here is now wrong *as scoped*.

What changes is that the file is no longer what the code produces. Re-running stage 1 yields
205,103 lines, and any figure below then describes a different population than the one it was
measured on.

| artifact | pinned figure | what a regeneration does to it |
|---|---|---|
| `eval/entry_rate.py`, `results/entry_rate_validation_1906BPL.py` | entry_rate 97.5% on 140 labels | 6,091 new lines enter the population it estimates over. The 140 labels were drawn from the old file, so the estimate is for a population that no longer exists. **Re-draw and re-label.** |
| `results/band_vs_fabrication_1906BPL.py`, `results/ab_band_fabrication_1906BPL.py` (+ its PREREGISTRATION) | 5.6% not-real stratified; band separates fabrication 98:1 | Band assignment is per-line and unaffected, but band *shares* of the volume shift with 6,091 new lines. The pre-registered stratified draw is void against a new file. **Re-stratify before re-running.** |
| `results/implied_surname_lines_1906BPL.py`, `results/implied_surname_validation.py` | implied-surname counts | Denominator moves. |
| `results/header_orphan_dispute_share_1906BPL.py` | dropped headers explain 2.6% of the 23.5% dispute rate | **Worst case: it imports `page_geometry`/`geom_reject` live while reading the old JSONL.** Re-running it *today* already mixes a pre-correction file with post-correction code. Its orphan counts will move even with no regeneration. |
| `docs/PAGE_TYPE_CLASSIFIER.md` | 239 hand-labelled leaves; zero ad lines admitted, 0.2% listing lines lost | Labels are per-leaf and survive, but the leaf-doc feature `share_banner` (see below) and the line population both shift. |
| `docs/FIGURE_AUDIT.md` | "1906BPL kept lines 199,012 ✓", "micro13 kept 2,889 ✓" | Verified correctly on 2026-09-13 against the artifact. Superseded by this document the same day. |

### `build_leaf_docs.py` was deliberately NOT changed

`data_prep/build_leaf_docs.py` computes its own `share_banner` as `1.5 × plain median` — the same
contaminated statistic. It is **left as-is on purpose**, with a comment saying why: it is a
recorded *feature*, not a rule, and the 239 hand-labelled leaves behind the page-type work were
labelled against those values. Changing it silently would move the ground under that labelling.
Change it only together with a relabel, and take `body_width()` rather than inventing a third
statistic.

---

## Consequence for the `join_wraps` false-merge gate ("fix C")

The correction made a *different* pending fix more valuable, which is the kind of interaction
worth recording.

`join_wraps` merges an indented line into the entry above it. On 1906BPL the continuation indent is
bimodal by parent type — a ditto-led parent's continuations sit at ~3.9 median-heights, a
full-surname parent's at ~5.2 — and `INDENT_RATIO = 3.0` catches both. The shallow word-parent cell
is overwhelmingly **the next entry**, not a continuation: a ditto line whose mark ABBYY dropped.

Re-measured whole-volume under the corrected banner rule (`754` joins in the cell):

| | old banner rule | new banner rule |
|---|---|---|
| merged line survives filters | 499 | **557** (+58) |
| surviving **fabricated composites** (both halves entry-shaped) | 273 | **310** (+37, +14%) |

Because a false merge that used to be dropped as `banner` cost nothing, and now survives as a
record. **311** of those split into two separately-surviving records if the join is blocked — so
the gate converts ~310 fabricated composites into ~620 correct entries.

Hand-read 14 random survivors; all 14 are unambiguously two directory entries glued together:

```
'Olmer Jos restaurant 51 Broad Mhtn h 143 Himrod'  +  'Mary wid August h 143 Himrod'
'Faye Alfred M h 249 Prospect pi'                  +  'Edwin M elk h 174 Johnson'
'Esposito Anthony signs h 249 E 5th'               +  'Anthony R painter h 194 Pres’t'
```

The 37 newly-surviving ones are triples — three people in one record:

```
'Coleman Adolphine wid Davis h 137 Penn Annie wid h 28 Fleet pi Arthur elk h 199 Cornelia'
```

**Not yet implemented, and two things must happen first.** The gate's `DEEP_INDENT = 4.4` is
calibrated on 1906BPL's indent bimodality *alone*, and Trow prints its ditto glued to the given
name (`-Michl`, no space — see `normalize_ditto_lead`'s KNOWN GAP), so the parent classifier would
read a Trow ditto line as a full-surname parent and fire the gate on **genuine** wraps. Confirm the
two-mode structure on a Trow and one further publisher. And the 310 rests on the same regex proxy
flagged above; it wants ~80 targeted labels.

Two fixes measured alongside it were **rejected** and should not be retried without new evidence:

- **`banner` on the widest segment rather than the union box** — 4 lines per 300 leaves. 58% of
  banner drops are single-segment; joining is not what makes lines wide.
- **wrap-join vgap measured from the previous segment instead of the first** — does what it
  intends (3+ segment joins 104 → 199, dangling hyphens −18%) and **loses 475 kept lines** doing
  it, because longer unions trip `banner` more often.
