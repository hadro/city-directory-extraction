# Handoff — Visual sampling of directory volumes

> Self-contained handoff for the **visual-sampling** workstream (started 2026-06-19).
> Designed to be picked up cold (incl. Claude Code / Dispatch on mobile). Companion:
> [HANDOFF.md](HANDOFF.md) (the broader Qwen fine-tune project), [../README.md](../README.md).

## Goal
Take a *visual* sample (front matter + a couple listing pages) of the volumes in
`data_prep/master_directories.csv` (449 rows: nypl/ia/loc) to:
1. **Backfill structural metadata** — `column_count`, `start_page`/`end_page`, and the new
   `key_page` + `page_offset` — for the ~290 non-NYPL rows that are blank.
2. **Locate + transcribe each volume's abbreviations key page** (the "Explanation of abbreviations":
   `h`=house, `r`=resides, `bds`=boards, `wid`=widow, …) — the *ground-truth* style legend. The
   front-matter **table of contents** gives section start pages (persons/street/business).
3. **Build per-publisher×era style profiles** (`data_prep/style_profiles/`) and use them to
   parameterize the synthetic generator `data_prep/synth_persons.py` — the lever to close the
   synth→real gap (the model regularizes unseen surnames / misses out-of-style layouts, e.g. Lain
   Brooklyn). *(Out of scope for now: auto OCR/NER prompts, eval-set expansion.)*

## Status — Phase 0 (pilot) DONE ✅
Validated the whole chain on **Trow 1890/91** (nypl `4b984650-317a-0134-f64d-00505686a51c`) and
confirmed it generalizes (Doggett 1845 TOC found). Committed:
- this repo: `b970511` — `key_page`+`page_offset` columns (CSV + `ingest_collection.py` FIELDS +
  README schema), Trow pilot row backfilled, `data_prep/style_profiles/` (README + first card
  `trow_manhattan_1890s.md`).
- sibling `directory-pipeline`: `bd4ca4f` (branch `claude/local-ocr-city-directories-ey5741`) —
  `sources/sample_directories.py --front N` option (samples front matter too).

Pilot downloads live in `directory-pipeline/output/<slug>/` (gitignored): 7 volumes
(nypl Trow, ia Lain/Doggett/Longworth/Flushing/phonebook, loc Spooner) sampled at `--front 12 -k 2`
(Trow re-pulled at `--front 27`).

## Status — Phase 1 (scale-out) STARTED 2026-06-19

**Completed so far (4 sessions):**

**Sessions 1–2 — pilot volumes carded** (`e1f5b46`, 2026-06-19):

| Style card | Source/ID | col | key_page | page_offset |
|---|---|---|---|---|
| `lain_brooklyn_1880s.md` | `ia/1885BPL` | 2 | 1 | 0→+50 (drift) |
| `doggett_manhattan_1840s.md` | `ia/doggettsnewyorkc1845dogg` | 2 | — | +10→+16 |
| `longworth_manhattan_1830s.md` | `ia/longworthsameric1839newy` | 1 | — | +6 (constant) |
| `boyd_flushing_1880s.md` | `ia/flushingnewyork188586boyd` | 1 | — | +15 persons / +64 biz |
| `lain_brooklyn_1881_loc.md` | `loc/01015253` | 2* | — | n/a (partial scan) |

*The `loc/01015253` Lain-1881 stub is **RESOLVED in session 3** (see below): the LoC item is a
20-canvas partial scan with no persons listing, so `column_count=2` is inferred from the Lain
identity and `page_offset`/`key_page` are unmeasurable.

**Already-downloaded un-carded volumes** (`d775172`, 2026-06-19):

- `nypl/b14662b0` (Franks/Kollock 1786): carded as `franks_newyork_1786.md` — first NYC
  directory ever published; 1 col; page_offset **+8 constant** (measured from IIIF canvas labels
  25/36/47 vs printed pp. 17/28/39); format `Surname Firstname, occupation, Number, Street`.
  Covers 5 CSV rows (1 NYPL original + 2 IA originals + 2 reprints — column_count=1 backfilled
  for all; page_offset only set for the NYPL copy; others need sampling to measure their offset).
- `ia/newyorkcityincl1917newy_1` ("New York City Inclusive"): confirmed **PHONEBOOK** — all
  sampled canvases are classified business ad sections; listing pages are 4–5 narrow columns with
  embedded ads (Donnelley-style telephone directory); NOT a residential persons training target.
  Notes updated in CSV.

**Permissions** (`d775172`, 2026-06-19): `.claude/settings.json` created with HF CLI read
patterns (`hf jobs ps *`, `hf jobs logs *`, `hf auth whoami`, `hf download *`). Note: `Read` and
basic Bash commands (`ls`, `grep`, etc.) are auto-allowed for subagents already; HF CLI was the
only gap. Subagent delegation has not yet been tested in practice.

### Session 3 (2026-06-19) — 4 cohorts cleared + stub resolved

Each cohort sampled at `--front 20 -k 2`, a few representatives across the date range; `column_count`
backfilled for the **whole** cohort once verified, `page_offset` measured only on the sampled volumes.

| Cohort | Rows backfilled | col | Reps sampled | page_offset (per-vol) | Card |
|---|---|---|---|---|---|
| **Longworth** (NYPL+IA, 1797–1843) | 58 → col=1 | 1 | 1797 `9c27dfc0`, 1820/21 `d0c00950`, 1842/43 `5a28bac0` | +19 const / −5→+7 / −9 const | extended `longworth_manhattan_1830s.md` |
| **Doggett** (NYPL+IA, 1842–1855) | 11 → col=2 | 2 | 1842/43 `8ca2a950`, 1846/47 `88fe6240`, 1854/55 `a4b1de40`, ia 1847 | +5 / +17→+29 / +3→−3 / +6→+8 | extended `doggett_manhattan_1840s.md` |
| **Hearne** (Brooklyn, 1850–55) | 7 → col=1 | 1 | ia 1850 & 1852, micro `_0028`/`_0032` | +16→+22 / +12→+16 / +8 / +6 | **new** `hearne_brooklyn_1850s.md` |
| **Lain** (Brooklyn BPL, 1884–99) | 5 → col=2 | 2 | 1884/86/87/89/99 BPL | +54→+82 / +60 / +53 / +20 / +52 | extended `lain_brooklyn_1880s.md` |
| **loc stub** `01015253` | 1 → col=2* | 2* | full manifest pulled (20 canvases) | n/a — partial scan | closed `lain_brooklyn_1881_loc.md` |

Commits: `efd4786` (Longworth+Doggett), `6045953` (Hearne), `72841e7` (Lain), `df31ebb` (loc stub).

**Cross-cutting findings (apply to all future cohorts):**
- **`column_count` IS clusterable per publisher/era; `page_offset` is NOT.** A whole cohort's column
  count can be backfilled from a few sampled extremes, but every volume's offset must be measured
  individually (front-matter/ad-block length varies per digitization). So the cheap win is col-count;
  offsets are optional per-volume follow-up.
- **Verify col-count at the date-range extremes** to catch the ~1845 1→2-column transition. Doggett
  was already 2-col in 1842; Longworth stayed 1-col through 1843 — the transition is publisher-, not
  just year-dependent.
- **Negative `page_offset` is normal** in later/denser volumes (printed page runs ahead of canvas):
  `canvas_index = printed_page + offset` holds for any sign.
- **`micro_IABROOKLYN` microfilm scans are single-page single-column, NOT spreads** (refines the old
  microfilm-spread warning below) — just darker/degraded, fully readable.
- **LoC items can be partial scans** (front matter + business index only). Pull the full manifest and
  check the canvas count before assuming a persons listing exists to sample.

**Current CSV state:** **170 rows** have `column_count` (was 88; +58 Longworth, +11 Doggett, +7
Hearne, +5 Lain, +1 loc-stub); **21 rows** have `page_offset` (was 5; +3/+4/+4/+5 across the four
cohorts). ~279 rows (of 449) still need `column_count`. Remaining per-volume `page_offset` for the
sampled cohorts (45 NYPL + 10 IA Longworth, 7 Doggett, 3 Hearne) is low-priority follow-up.

### Session 4 (2026-06-19) — E (fraction test) + Brooklyn-run triage/backfill (option B)

**E — "consistent fraction" hypothesis: TESTED & REJECTED.** Full verdict in step 5 below — no
fraction heuristic is viable; key/TOC landmarks are *absolute* near-front (first ~15–25 canvases),
not a fraction of total, and the feature is absent in 5/7 carded publishers. Net: keep `--front 20`.

**B — blank-publisher IA triage (172 rows).** 103 were already PHONEBOOK (settled). Triaged the
remaining **69 from titles**: they are essentially the **entire Brooklyn residential run, 1830–1912**
— overwhelmingly KEEP, only **1 SKIP** (`micro_IABROOKLYN_0038` = a pure *Business* Directory, flagged
BIZ). Sampled 4 anchors (`1858BPL`, `1869BPL`, `brooklynnewyorkc1906geor`, `micro_0026`=1848/49) to
lock col-count + publishers, then backfilled **63 rows** of `column_count` (+ `publisher` on 36):

| Cohort | Rows | Backfilled | Verified by |
|---|---|---|---|
| **Lain Brooklyn** `18xxBPL` 1858–1883 | 16 | publisher=Lain, col=2 | 1858 (J. Lain) + 1869 (Geo. T. Lain) title pages; 2-col listings |
| **Upington Brooklyn** `*geor` 1903–1910 | 18 | publisher=Upington, col=2 | 1906 title page (Geo. Upington, vol. LXXXIII); 2-col listing |
| **Spooner/Teale early Bklyn** micro 1830–1849 (+2 reg-IA) | 23 | col=1 (pub=Spooner on the 2 confirmed 1848 rows) | 1848/49 title (Teale/Spooner) + single-col listing |
| **Lain-era Consolidated** micro 1857–1860 | 4 | col=2 (publisher unverified) | bracket (1858 col-2 ↔ 1862 Lain) |
| **Williamsburgh** `micro_0043` 1849/50 | 1 | col=1 | era bracket |
| **1786-96 compilation** `…durs` | 1 | col=1 | 18th-C style |

New/updated cards: **`upington_brooklyn_1900s.md`** (new publisher), **`spooner_brooklyn_1840s.md`**
(new), and **`lain_brooklyn_1880s.md` extended to 1858–1899** (Lain's Brooklyn run is ~26 yrs longer
than carded). **Key structural finding: the Brooklyn col 1→2 transition is 1855–1858** (Hearne col-1
in 1855 ↔ Lain col-2 in 1858) — earlier + publisher-specific vs. the ~1845 Manhattan transition.

**Duplicates found** (dedupe at sample time): `micro_0026`≡`brooklyncitydire1848teal` (1848-49);
`brooklynalphabet1843unse`≈`micro_0019` (1843); `micro_0037`≈`1858BPL` (Consolidated 1858); plus the
`*geor` 1903–1910 set has many intra-year copies + p1/p2/p3 parts.

**Still open in this bucket (6 rows):** the BIZ skip (`micro_0038`, intentional); `newyorkdirectory00durs`
(1910 Manhattan, Trow-era? needs sample); 4× `*broo` 1912 Brooklyn (Upington-successor? needs sample).

**Current CSV state (after session 4):** **233 rows** have `column_count` (was 170; +63 Brooklyn run);
**313 rows** have `publisher` (+36); **21 rows** have `page_offset` (unchanged — B measured no offsets).
**216 rows (of 449) still need `column_count`** — biggest bucket now **Trow (51)**; the blank-publisher
IA bucket is essentially cleared (6 rows left, listed above).

## The workflow (all FREE — no Gemini/API)
```bash
PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python   # has requests/numpy/PIL
MASTER=/Users/joshhadro/github/city-directory-extraction/data_prep/master_directories.csv
cd /Users/joshhadro/github/directory-pipeline

# 1. sample front matter (~20 pages: title/TOC/key) + listing pages — downloads ONLY those pages
$PY sources/sample_directories.py "$MASTER" --front 20 -k 2 --width 1800 \
      --source ia --publisher Trow --limit 1            # filters: --source/--publisher/--limit; --dry-run to just resolve
# 2. deterministic structure detectors (no model)
$PY pipeline/detect_columns.py output/<slug>            # -> output/<slug>/columns_report.csv (num_columns, confidence)
$PY pipeline/detect_spreads.py output/<slug> --csv output/<slug>/spreads_report.csv
# 3. VISUAL read of output/<slug>/*.jpg (Read tool renders images): find title page (year), TOC
#    (section page numbers), abbreviations key (transcribe legend); read a listing page -> confirm
#    columns + entry format; compute page_offset = canvas_index - printed_page near listing start.
# 4. backfill the row(s) in $MASTER and write data_prep/style_profiles/<publisher>_<era>.md
```

## Lessons / gotchas (hard-won in the pilot and Phase 1)
- **Abbreviations key = ground truth**; in some volumes (Trow) it doubles as the listing-start page.
- **`detect_columns` under-counts** dense listings (Trow: detector said 2; the preface says **3**).
  Trust the preface / your eye for `column_count`; treat the detector as a hint.
- **`--front 12` too shallow** for ad-heavy volumes — use **`--front 20`** (Trow's key sits ~canvas
  14 behind ads + a foldout map + the advertiser index).
- **`page_offset` drifts** across a volume (Trow: ≈ −1 at front, ≈ +9 by p.353) due to unpaginated
  plates → record a *local* value near the listing start, not a global constant.
- **`page_offset` can be constant** in older volumes where ads are a fixed front block with no
  interspersed pages (Longworth 1839: exactly +6 at both measured points; Franks 1786: exactly +8).
- **Section-boundary jumps** are huge: Boyd Flushing 1885/86 jumps +49 between persons and
  classified-business sections (a large unnumbered ad insert). Always note which section an offset
  measurement applies to.
- **LoC serial records** cover a multi-decade run; the specific digitized volume may differ from the
  catalog publisher. Always read the title page (sampled as a front-matter canvas) before assuming
  the master-list publisher matches the physical volume. **And check the manifest canvas count** —
  some LoC items are *partial* scans (e.g. `loc/01015253` = only 20 canvases: front matter + business
  index, no persons listing at all), so no `--front N` will ever surface a listing page.
- **Donnelley/telephone directories** look like persons directories at first glance but have 4-5
  narrow columns with ads embedded in listing pages — unmistakable once you see a listing page.
  The IA "New York City Inclusive" series is one of these. Already-PHONEBOOK rows in the CSV are
  often these.
- **Publisher clustering** is the efficiency lever: once you sample one volume from a publisher/era
  and write the card, other volumes in that cohort only need page_offset measured (not a new card).
  Sample one Hearnes, cover all 7; extend the Lain card for each subsequent Lain year.
- **Reprints** (Patterson 1874 of Franks 1786; Disturnell 1876) have the same entry format but
  potentially different page_offsets (different digitizing institution adds different front matter).
  Backfill `column_count` from the original's card; leave `page_offset` blank until sampled.
- **Microfilm volumes** *can* be double-page **spreads** + degraded (`detect_spreads` flags them; a
  spread = 2 printed pages per canvas, complicating `page_offset`) — but **not always**: the
  `micro_IABROOKLYN` Hearne scans turned out to be single-page single-column, just dark. Confirm by
  eye rather than assuming microfilm ⇒ spread.
- **Bonus:** Trow's preface prints **spelling-variant name clusters** (Bauer/Baur/Bower,
  Schafer/Schaffer/Schaefer…) — a candidate seed for name generation vs. surname regularization.
- **Subagent permissions:** `Read` and basic Bash (`ls`, `grep`, etc.) are auto-allowed for
  subagents. HF CLI commands (`hf jobs ps`, `hf jobs logs`, etc.) are NOT — added to
  `.claude/settings.json` via `/fewer-permission-prompts` (2026-06-19). Subagent visual-read
  delegation not yet tested in practice.

## NEXT — Phase 1 (continued): backfill at scale (~216 rows still need `column_count`)

✅ **Done:** permissions; pilot volumes + already-downloaded; **session-3 cohorts (Longworth,
Doggett, Hearne, Lain + loc stub)**; **session-4 (E fraction test; B blank-publisher IA triage +
Brooklyn-run backfill — see above)**. Biggest remaining bucket now: **Trow (51)**. The ~172
blank-publisher IA rows are triaged + backfilled (only 6 residual rows left).

**Remaining steps:**

2. Sample `--front 20 -k 2` across non-NYPL rows **in publisher batches** (same publisher/era →
   share a card; only measure page_offset per volume). `--dry-run` first. **Skip eval-heldout**
   volumes (`1897BPL` Lain and NYU Trow 1850 stay OUT).

   High-leverage batches to do next (ordered by ROI):
   | Publisher | Remaining vols | Action |
   |---|---|---|
   | ~~Lain Brooklyn (1884–1899)~~ | ~~done~~ | ✅ col=2 + offset backfilled for 5 (1884/86/87/89/99); card extended. 1897BPL stays OUT (eval). Still TODO: loc/01015253 stub |
   | ~~Hearne Brooklyn (7 vols)~~ | ~~done~~ | ✅ new card `hearne_brooklyn_1850s.md`; col=1 backfilled for all 7; offset done for 4 (2 IA + 2 micro). Remaining: per-volume offset for 3 |
   | ~~Doggett (12 vols)~~ | ~~done~~ | ✅ col=2 backfilled for all 11; offset done for 4 (1842/43, 1846/47, 1854/55 nypl + ia 1847). Remaining: per-volume offset for 7 |
   | ~~Longworth (61 vols)~~ | ~~done~~ | ✅ col=1 backfilled for all 61; offset done for 3 (NYPL 1797/1820/1842). Remaining: per-volume `page_offset` for 45 NYPL + 10 IA (low priority — offset is per-volume, no shortcut) |
   | Trow (51 vols) | 51 | Have card; sample each → measure offset only |
   | ~~Blank-publisher IA rows~~ | ~~172~~ | ✅ s4: 103 PHONEBOOK + 68 Brooklyn KEEP (col backfilled, 3 publishers ID'd: Lain/Upington/Spooner) + 1 BIZ. 6 residual: durs-1910, 4× broo-1912, the BIZ skip |

   ~~Also: resample `loc/01015253` (Lain 1881)~~ ✅ RESOLVED — LoC item is a 20-canvas partial scan
   (no persons listing digitized); col=2 inferred from Lain identity, stub card closed.

3. Run `detect_columns` + `detect_spreads` over downloaded dirs.
4. Per volume: fill `column_count`, `start_page`/`end_page` (from TOC + `page_offset`), `key_page`;
   transcribe each distinct publisher/era legend once.
5. ✅ **"Consistent fraction" hypothesis — TESTED & REJECTED (session 4, 2026-06-19).** Logged
   `key_page_idx/total` and `toc_idx/total` across all 7 carded representatives (totals from live IIIF
   manifests). Verdict: **no fraction heuristic is viable — the fraction is the wrong frame.**
   - **Structurally too sparse.** Only **2 of 7** volumes have a locatable abbreviations key (Trow
     key=canvas 14, Lain key=canvas 1) and only **1** has an original TOC (Doggett, canvas 8); the
     other ~15 cohort volumes added zero key/TOC sightings. Most pre-1880 directories (Longworth,
     Doggett, Hearne, Boyd, Franks) have **no collected key page at all** — older style embeds
     conventions in the entries; the standalone "Explanation of Abbreviations" is a later Trow/Lain
     (1880s+) feature. n=2 (key) and n=1 (TOC) cannot define a per-publisher cluster.
   - **Doesn't cluster where it exists.** Trow `key/total`=0.0090 vs Lain 0.0006 — **15× apart at
     near-identical totals** (1558 vs 1564 canvases). The spread is driven entirely by front-matter
     depth (Trow: 13 canvases of foldout-map+ads+advertiser-index before the key; Lain BPL scan: 1),
     which the cards already proved is **per-digitization, not per-publisher** — the same quantity that
     makes `page_offset` un-clusterable. And where a key exists it sits **on the listing-start page**,
     not a separate front-matter page.
   - **Only invariant is absolute, not fractional:** every key/TOC/title landmark lands in the **first
     ~15–25 canvases**, which `--front 20` already captures. So there is **no scan cost to save** — the
     cheap front window already finds the front-matter landmarks; the expensive deep quantity
     (`page_offset`) is exactly the one that won't cluster. **Keep `--front 20`; do not build a fraction
     predictor.** The efficiency lever stays publisher-clustering of `column_count` (already established).
6. Targeted QA (Opus): `trowsgeneraldire1853trow` REVIEW; reprints (Patterson 1874 of Franks 1786,
   Disturnell 1876); the blank-publisher IA triage. *(Longworth blank-year rows and the loc/Spooner
   serial were resolved in session 3.)*

## THEN — Phase 2: style profiles → synth generator
- Consolidate `data_prep/style_profiles/*.md` + a machine-readable `style_profiles.json` (legends +
  TOC maps). Card schema is in `style_profiles/README.md`.
- Extend `synth_persons.py` (`render_tulsa`/`render_nyc`, `_finish()` `context`) with a style layer
  keyed by publisher/era so synthetic lines use volume-accurate abbreviations/layout; then regenerate
  + retrain + re-run the eval panel (existing Wave-1 procedure in HANDOFF.md) to confirm the
  `name`/EM lift, esp. on Lain.

## Key paths
- Master list: `data_prep/master_directories.csv` (schema in `master_directories.README.md`).
- Style cards: `data_prep/style_profiles/` (`README.md` = card schema + build recipe + lessons).
- Ingest tool (FIELDS): `data_prep/ingest_collection.py`.
- Sampler + detectors: `../directory-pipeline/sources/sample_directories.py`,
  `../directory-pipeline/pipeline/detect_columns.py`, `detect_spreads.py`.
- Synth generator (Phase 2 target): `data_prep/synth_persons.py`.
