# Handoff — Ground-truth gold + style profiles

> **Canonical doc for the real-OCR gold eval panel, the labeling conventions, the gold toolchain,
> and the per-publisher style cards.** Resume the gold-building work here.
> Companions: [VISUAL_SAMPLING_HANDOFF.md](VISUAL_SAMPLING_HANDOFF.md) (the catalog backfill +
> visual-sampling history this grew out of), [HANDOFF.md](HANDOFF.md) (the Qwen model),
> [../data_prep/style_profiles/README.md](../data_prep/style_profiles/README.md) (style-card schema).

## What this is

Hand-built **real-OCR gold** for the city-directory extractor's eval panel: take Surya-OCR'd
listing pages from the sampled volumes, label each entry into the union 8-field schema, and use it
to measure the synth-trained model on *real* directory styles (the synth→real gap). The panel is
**eval-only — never training data.** Alongside it, per-publisher×era **style cards** record each
volume's print conventions (abbreviations key, column count, marks).

**Union schema (8 fields):** `name · is_business · spouse_name · race_designation · occupation_role
· employer · address · home_address`. Export format (consumed directly by `eval/evaluate.py` as
`--gold`): one JSON line `{raw_line, context:{dialect,alphabetical_range,directory_year,image},
record:{…8 fields}}`.

## The toolchain (`data_prep/`)

| script | role |
|---|---|
| `sample_volumes.py` | stratified selector → `gold_sample/worklist.csv` (42 reps; publisher×col, deep/std targets) + `WORKLIST.md` checklist |
| `run_surya_on_samples.py` | batch Surya OCR (gpu env) over the worklist dirs; listing-pages-only, blank-skip, resumable, per-image load |
| `make_gold_tool.py` | builds the self-contained HTML editor from Surya JSON + manifest; line-crop · raw_line · 8 fields; autosave/Import; **cols/year auto-resolve from master_directories.csv**; `--max-lines N` |
| `validate_gold.py` | QA on the export — ERRORS (break evaluate.py) + WARNINGS (drift/convention slips) + fill-rates |

**Per-volume loop** (run from `directory-pipeline/`; Surya needs `uv sync --extra gpu`, and is
slow on Mac MPS — see Lessons):
```
PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python
# (once) sample the worklist:  $PY sources/sample_directories.py <repo>/data_prep/gold_sample/worklist.csv --front 20 -k 2 --width 1800
$PY ../city-directory-extraction/data_prep/run_surya_on_samples.py --dirs output/<slug>     # OCR
$PY ../city-directory-extraction/data_prep/make_gold_tool.py output/<slug> -o gold_<slug>.html --max-lines 80
# label in browser → Export gold.jsonl → then in city-directory-extraction:
python3 data_prep/validate_gold.py ~/Downloads/gold.jsonl --images ../directory-pipeline/output --strict
cp ~/Downloads/gold.jsonl data/<slug>_eval.jsonl
python3 eval/evaluate.py --gold data/<slug>_eval.jsonl --self-test
```
`data/` is **gitignored** (like all eval sets) — back gold up out-of-band.

**Finalize recipe** (what each export gets, before placing): home_address fix (sole-home → address) →
`validate_gold` → fix flagged slips → `--self-test`. The recurring slips: leftover commas, inverted
widows, year-vs-master mismatch, raw_line↔field OCR-fix drift, parenthetical-firm-in-name.

## The contract (eval-realism) — why the conventions are what they are

**Gold must match how the model represents things** (van Strien's eval-realism rule), so the *same*
convention governs `synth_persons.py` (train), every `data/*_eval.jsonl` (eval), and the model's
output. Do **not** redefine fields when retraining — a change means migrating synth + all existing
eval rows + new gold at once. The master split:

- **`raw_line` = the verbatim PAGE** (every comma, prefix, ditto; OCR *misreads* fixed — it's faithful
  to the page, not to Surya's output).
- **The 8 record fields = canonical** (the model's output form).

## Conventions (the full set — also in the editor's panel)

1. **Verbatim values** — never expand abbreviations (`insur` stays `insur`; keep `h`/`r`/`bds`/`clk.`/
   `wid.`). Expansion is a separate downstream step keyed off the `style_profiles/` legends.
2. **raw_line = corrected page** — fix OCR misreads in raw_line too (long-s `f`→`s`: `fexton`→`sexton`;
   `Brewsler`→`Brewster`), so raw_line and fields tell the same story. `validate_gold` token-drift flags one-sided fixes.
3. **No commas in fields** — drop both the field-separating commas *and* the surname/given comma.
   `Graves, Benjamin, accountant, 71 Dey` → name `Graves Benjamin` (raw_line keeps the comma; synth
   `_nyc_name` is `"{surname} {given}"`, no comma).
4. **Fractions as ASCII** — `1/2`, not `½`.
5. **Long-s → `s`** everywhere (typographic form of s).
6. **Titles/honorifics → `name`**, in-place, verbatim — `Rev.`/`Dr.`/`Capt.`/`Mrs.`/`Miss`
   (`Mortimer Rev Benj.`, `Gibert Lyman (Rev.)`). Don't reorder, don't expand.
7. **Role vs employer** — job word → `occupation_role`; institution/company worked *at/of* → `employer`
   (`c. h. clk.` → clk + Court House; `pastor of 1st Unitarian Church` → pastor + the church; `foreman
   white lead factory` → foreman + factory). Drop the connector `of`. A bare trade word (`hotel`,
   `tanner`) is all occupation.
8. **`address` vs `home_address`** — the listed address → `address` (keep `h`/`r`/`bds` prefix; it
   already encodes work-vs-home). `home_address` is **only** a second, separate `h.` home. A lone
   `h 449 Clason av` goes in `address`. (The role-based work→address/home→home split is rejected —
   undecidable for the common single combined-use address.)
9. **Widows → `wid`/`widow` marker always → `spouse_name`** (verbatim). `widow of John` / `wid. John`
   → John is the husband (her own given name, if any, stays in name; if none, name is just surname).
   `widow Ann` (no "of") → Ann is her own name (→ name), `spouse_name` is the bare marker. **`of`
   is the disambiguator.** `(Hazel W)` after a man → wife → `spouse_name = Hazel W` (drop parens).
10. **Race marker → `race_designation`** (verbatim), **volume-specific — read each volume's key page**:
    Tulsa `(c)`, **Ogden 1839 `*`** = colored; **Hope & Henderson 1856 `*`** = *Eastern District*
    (geographic, NOT race → dropped, no field) and colored is `col'd`. Same symbol, opposite meaning.
11. **Ditto marks → verbatim** — copy `do`/`〃`/`''`; don't resolve to the row above.
12. **Surname-repeat dash → verbatim** — dense volumes replace a repeated surname with a leading mark:
    Trow `-` (`-Michl` = "Juarez Michl"), Polk `"` (`" J C & Co`). Keep the mark; don't write out the
    surname. (Whatever character the volume uses; OCR usually emits `-`.)
13. **Parenthetical firm vs principal** — person `(firm)` → firm to `employer` (drop parens),
    is_business False (`Emmons Jas M (F R Emmons & Bro)`); firm `(person)` → person stays in `name`,
    is_business True (`Emmons J C & Co (Jno C Emmitt)`).
14. **`is_business`** — True only when the **name** is a firm (`& Co`, `Bros`, `et co.`), never from
    bold/typography (the model can't see it; bold = paid advertiser). A person who runs a business
    stays False with the company in `employer`.
15. **Wrapped entries are one record** — join continuation lines into both the entry's fields and its
    `raw_line` (incl. hyphenated word-breaks: `Bar-`/`clay` → `Barclay`). Surya truncates wrapped
    advertiser entries — complete the raw_line.
16. **No schema field → drop it** — telephone (`Tel. 5550 Beekman`), Eastern-District `*`, district
    notes, periodical/agent metadata. Map the core to the 8 fields; never invent a field or cram into
    the wrong one. **Skip an entry only when the *source* is genuinely garbled** (e.g. `Anothor,
    Reasen`), not when it's just long/complex.

Edge cases that recur in dense commercial volumes: multi-office businessmen (`v pres … & pres …` →
combine roles/addresses with `&`), out-of-town firms with NYC agents (drop the agent line), `R`/`r`
= Room, neighborhood abbreviations (`WNB`=West New Brighton, `Stap`, `Tomp`) → kept verbatim in
`address`.

## Panel status — 15 volumes / 949 lines (1786–1933/34; col 1→6 complete; all 8 fields; first outer borough)

| volume | lines | era / layout / note |
|---|---|---|
| franks1786 | 56 | 1786 Manhattan, col 1 (bounded-resampled past almanac/officials) |
| duncan1794 | 58 | 1794 Manhattan, col 1 (`Surname, Given`) |
| mercein1820 | 60 | 1820 Manhattan, col 1 |
| ogden1839 | 66 | 1839 Brooklyn, col 1 — **race** (`*`=colored) |
| doggett1846 | 37 | 1846 Manhattan, col 2 |
| rode1851 | 53 | 1851 Manhattan, col 1 |
| hearne1852 | 52 | 1852 Brooklyn micro, col 1 — **employer** signal |
| hopehenderson1856 | 60 | 1856 Brooklyn, col 2 — `*`=Eastern District |
| lain1876 | 103 | 1876 Brooklyn, col 2 (deep) |
| boyd1890 | 75 | 1890 Flushing/**Queens**, col 1 |
| trow1907 | 68 | 1907 Manhattan, **col 3** (first deep multi-column) |
| trow1913 | 93 | 1913 Manhattan, **col 4** |
| polk1917 | 72 | 1917 Manhattan, **col 5** — employer-rich |
| polk1925 | 40 | 1925 Manhattan, **col 6** (density ladder topped) |
| polk1933si | 56 | 1933/34 **Staten Island**, col 2 — first **outer borough** + 1930s; neighborhood codes (WNB/Stap/Tomp/NB) |

**Deep: 5 of 15** (lain1876, trow1907, trow1913, polk1917, polk1925). **First real numbers** = GLiNER
floor on lain1876 (`results/scores.jsonl`, label `gliner-lain1876`): macro-F1 **0.33**, whole-row EM
**3.9%**, weakest `address` F1 0.16. The Qwen-fine-tune + Gemini-bar runs on the panel are still TODO.

**Next priority = breadth, not depth** — the layout (col 1–6) and all 8 fields are covered. Done:
**Polk 1933/34 Staten Island** (col 2, first **outer borough** + 1930s; 56 lines). Next: the other
Polk-1933 borough vols (Brooklyn/Bronx/Queens), M&B 1931, and the std tail (Smith col-transition,
Spooner, Reynolds, the NYPL early-Manhattan run).

## Reading F1 vs EM (for scoring runs)
For **sparse fields** (spouse/employer/race/home), read **F1 (non-empty), not EM** — high EM there
is just empty-matches-empty. `evaluate.py` separates them.

## Style cards (`data_prep/style_profiles/`)
13 cards written (Franks, Duncan*, Mercein, Ogden, Doggett, Hearne, Hope&Henderson, Lain ×2,
Longworth, Spooner, Trow, Upington). Each quotes the volume's abbreviations key (ground truth),
column count, entry format, and **volume-specific marks** — critically the race/district marks
(Ogden `*`=colored vs H&H `*`=Eastern District; cross-referenced in both cards). Write/extend a card
when you hit a volume's key page. Schema in `style_profiles/README.md`.

## Lessons (gold-OCR specific; catalog-backfill gotchas are in VISUAL_SAMPLING_HANDOFF)
- **Surya on MPS is slow** + **OOMs on dense pages** (Trow/Polk 300–600 lines): `RECOGNITION_BATCH_SIZE=32
  DETECTOR_BATCH_SIZE=4 … --batch-size 1` (resumable). Don't use `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0`.
  Best run on **Colab/CUDA** (the whole panel is ~113 listing images).
- **Blank-verso scans** (Boyd Flushing) — sampler lands `-k` picks on blanks → blank crops/hallucinated
  OCR. `--blank-std` skips them; recover by re-sampling a larger `-k`.
- **Truncated downloads** — `--resume` skips by existence not integrity; a 64 KB stub crashes decode
  (`verify()` misses it, only `.load()` catches). Delete + re-sample. Per-image load means one bad jpg
  doesn't sink the batch.
- **Early volumes mix in non-listing sections** (almanac/subscriber-roll/officials) — bound the sample
  to the listing canvas window via `start_page`/`end_page` in a temp CSV, then delete non-listing
  surya jsons so they don't eat `--max-lines`.
- **Volume-specific marks** — always read the volume's own explanation-of-marks page (the `*` divergence
  is the cautionary case).

## Phase 2 — eval-driven retrain loop
Gold stays eval-only. (1) Run the current model on the panel → see which fields/styles/abbreviations
fail. (2) Parameterize `synth_persons.py` with the per-publisher legends/layouts from `style_profiles/`.
(3) Regenerate synth → retrain → re-eval on the **same** gold. Convention fixed throughout, so score
deltas mean real change.

## Key paths
- Toolchain: `data_prep/{sample_volumes,run_surya_on_samples,make_gold_tool,validate_gold}.py`
- Worklist: `data_prep/gold_sample/{worklist.csv,WORKLIST.md}`
- Gold sets: `data/*_eval.jsonl` (gitignored); scorer `eval/evaluate.py`; predictors `eval/{gliner,gemini,qwen_predict}.py`
- Style cards: `data_prep/style_profiles/*.md` (+ `style_profiles.json`)
- Sampler/Surya (sibling repo): `../directory-pipeline/sources/sample_directories.py`, `pipeline/run_surya_ocr.py`
