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
IA bucket is essentially cleared (6 rows left, listed above). *(Trow cleared next — see below.)*

### Session 4 (cont., 2026-06-20) — Trow cheap-agent pilot + bucket CLEARED

First real test of **lower-model (Sonnet) sub-agent delegation** (was "not tested"), then used it to
clear the Trow `column_count` bucket.

**Pilot — 5 Sonnet agents, 1 per volume, isolated contexts, structured-output schema, Opus-audited:**
- **`column_count` via cheap tier = reliable.** 5/5 high-confidence + plausible; Opus eye-checked 1857
  (2-col) and 1907 (3-col) — both correct, ad banners correctly excluded.
- **`page_offset` via cheap tier = needs a sanity gate.** Correct when the page number is clean, but
  the model grabs the WRONG number when an ad banner covers it (1907 returned a bottom-ad-strip "1414"
  → impossible offset −1035; 1915 similar). An arithmetic gate (`offset = leaf − printed`; reject if
  `printed > total` or `offset ∉ [−25,+60]`) auto-quarantines these → escalate/re-read. Offsets are
  low-priority anyway, so they're deferred.

**Finding: Trow's col 2→3 transition is 1857→1859** (1857 = 2-col, 1859 = 3-col — both eye-verified).
Every Trow from 1859 on is col=3 — confirmed at 1859/1863/1876/1907/1915 + the 1890s card. So the
bucket needed only the one ambiguous read (1859), not a 47-way fan-out.

**Trow bucket CLEARED:** `column_count` backfilled for **all 52 remaining Trow** — 1857=2 (pilot),
1859–1922/23 + 1898/99 + all part-volumes = 3 (bracketed). Only `trowsgeneraldire1853trow` left out
(REVIEW-flagged, pre-transition — likely col ≤2; leave for manual). `page_offset` recorded for the
gate-passers (1857 +6, 1859 +6, 1863 +12, 1876 +14); the rest deferred.

**Reusable gated harness built** (for future cohorts / offset re-reads / a `/schedule` routine):
`data_prep/trow_fanout_prep.py` (picks next N un-done Trow → samples → emits a read packet) +
`data_prep/trow_fanout.workflow.js` (gated Sonnet fan-out; `args` = packet). Two issues the demo batch
surfaced, now handled/noted: (a) one NYPL Trow 1898/99 row has a **blank `id`** in the master (flagged
in its notes — needs fixing; prep now skips blank-id rows); (b) the sampler **collides output dirs for
same-year "part" volumes** (p1/p2/p3 share a slug → overwrite) — per-part reads need a sampler slugify
fix that includes the id. Neither blocked the col backfill (parts are uniformly post-1900 col=3).

**Title-triage of the tail (s4 cont.):** of the ~165 still-blank rows, **112 are PHONEBOOK** (SKIP,
separate track), leaving 52 non-phonebook. **Backfilled 32 from publisher/era alone** (early
Manhattan/Brooklyn col=1; Upington BPL col=2; flagged Boyd-1860 BIZ + Lain-1897 eval-holdout). Sampled
the 14 transition-era rows via a **2nd cheap-tier gated fan-out** (7 mixed-publisher Sonnet agents) +
Opus audit of the degraded/inverted scans — **reconfirmed col is publisher-dependent**: Groot&Elston
1845/46 + Rode 1851 stayed **col=1** (vs Doggett's col=2 same era); **Smith Brooklyn transitions within
its own run, 1854 (col=1) → 1857 (col=2)**; Hope&Henderson 1856/57 col=2; broo-1912 col=2. The
REVIEW-flagged `trowsgeneraldire1853trow` resolved → col=2, so **Trow is now 100% done**. The 2nd
fan-out again showed the cheap tier self-flagging low confidence on inverted/faded scans (→ Opus audit).
**2 residuals** left: `micro_IABROOKLYN_0034` (Smith 1855, mid-transition) + `newyorkdirectory00durs`
(1910, IIIF fetch failed ×2).

**Scope clarified (s4): include 1920s+ *city* directories (not phone books).** The 6 post-1925 Polk/M&B
city directories — initially deferred — are **now INCLUDED**: sampled via a 3rd cheap-tier fan-out, all
**residential (KEEP)**, with borough-dependent density — Polk NYC 1925 = **col=6** (1920/21 were col=5),
1931 M&B = col=4, the four 1933/34 Polk borough vols = col 2 (Staten Island) / 3 (Brooklyn) / 4 / 4.
The 100 PHONEBOOK rows ≥1920 were **verified genuine telephone directories** (every title reads
"…Telephone Directory" / "Classified Telephone" — Donnelley/BPL) → correctly SKIP. So the year boundary
is no longer the filter; **genre (city-directory vs telephone-directory) is.**

**Current CSV state: 332/449 `column_count`** (was 170 at session start); **29/449 `page_offset`**.
The ~117 still-blank = 112 PHONEBOOK (verified telephone directories, SKIP) + 2 residuals + ~3 REVIEW —
i.e. **every in-scope residential volume now has a column count.**

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
- **Surya on the Mac (MPS) is slow** — the gold panel's listing pages are the densest pages
  (~150–200 text lines each; Surya cost ∝ line count), and `run_surya_on_samples` does *only*
  those, so it grinds. Surya is meant for **GPU/Colab** (per `directory-pipeline/pyproject.toml`);
  the whole panel is only ~113 listing images → minutes on a T4. On the Mac, bump
  `RECOGNITION_BATCH_SIZE`/`DETECTOR_BATCH_SIZE`, or do one volume at a time with `--dirs`.
  **MPS OOM on dense pages:** Trow/Polk listing pages have 250–300+ text lines; the default
  `--batch-size 4` queues ~1000+ line-crops and blows the ~18 GB MPS cap (`MPS backend out of
  memory`). Fix = shrink batches: `RECOGNITION_BATCH_SIZE=32 DETECTOR_BATCH_SIZE=4 … --batch-size 1`
  (resumable, so only the failed pages re-run). Do **not** set `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0`
  (removes the safety cap → can hard-crash the machine). The full 42-volume pass got through this way.
- **Blank-verso scans** — some volumes (Boyd Flushing 1890) alternate content (odd canvas) with
  **blank versos** (even); the sampler can land its `-k` listing picks on blanks → blank crops +
  hallucinated low-conf OCR on white paper. Fixed: `--blank-std` skip in `run_surya_on_samples`
  + a skip in `make_gold_tool`. Recovery: re-sample with a **larger `-k`** (e.g. 12) so some picks
  hit content, re-OCR (blanks auto-skipped). Detect via grayscale std (<7 ≈ blank).
- **Truncated downloads happen** — `download_images --resume` skips by *existence*, not integrity,
  so a partial JPEG (e.g. an exact 65536-byte stub) lingers and crashes decode. `verify()` misses
  end-of-data truncation; only a full `.load()` catches it. Delete the stub + re-sample to re-fetch.
  `run_surya_on_samples` now loads per-image so one bad file doesn't sink its batch.
- **Early volumes mix in non-listing sections** — Franks 1786 sampled an **almanac** (moon-phase
  lines), a **subscriber roll**, and an **officials list** (`ALEXANDER M'Dougall, Esq: President`)
  alongside real listings; the default middle-80% window straddles them. These aren't blank (the
  std/blank-guard won't catch them) — spot them by content (long prose, or no `Surname, occ, addr`
  structure). **Bounded-resample recipe:** find a known listing canvas (here 79 = P-names), estimate
  the A–Z span, then sample only that window — `pick_indices` uses `start_page`/`end_page` as the
  **canvas** window when set. Copy the volume's worklist row into a temp CSV with `start_page`/
  `end_page` (e.g. 36/110), `sample_directories.py <tmp.csv> --front 0 -k 8`, re-OCR, then **delete
  the surya json of any non-listing page** so it's excluded from the editor (pages load in canvas
  order, so a 164-line almanac at the front would otherwise eat the whole `--max-lines` cap).
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
  delegation **tested in s4** (Trow pilot, Sonnet tier): reliable for `column_count`; for
  `page_offset` it needs an arithmetic gate (ad banners over the page number cause misreads).

## NEXT — Phase 1 (continued): backfill at scale (326/449 `column_count`; tail triaged)

✅ **Done:** permissions; pilot volumes + already-downloaded; **session-3 cohorts (Longworth,
Doggett, Hearne, Lain + loc stub)**; **session-4 (E fraction test; B blank-publisher IA triage +
Brooklyn-run backfill; Trow cheap-agent pilot + bucket cleared — see above)**. **Trow is now cleared**
(2→3 transition = 1857→1859, rest col=3) and the ~172 blank-publisher IA rows are triaged + backfilled
(6 residual). Remaining **~165** are smaller NYPL/IA tails with **no dominant publisher** — triage by
title, cluster what clusters, sample representatives.

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
   | ~~Trow (51 vols)~~ | ~~51~~ | ✅ s4-cont: col=3 backfilled for all (2→3 transition = 1857→1859; only 1857=col2). Only REVIEW-1853 left. Offsets gated/deferred. Cheap-agent harness in `data_prep/trow_fanout*` |
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

> **⚠️ The gold-building work below (editor, conventions contract, panel status, gold-OCR lessons,
> Phase-2 loop) is now consolidated and maintained in [GROUND_TRUTH_HANDOFF.md](GROUND_TRUTH_HANDOFF.md)
> — that is canonical going forward (esp. the full conventions list + live panel count). The sections
> below are retained as the origin/history; this doc stays focused on the catalog backfill
> (column_count/page_offset/key_page) it grew out of.**

## Gold-ground-truth editor (`data_prep/make_gold_tool.py`, 2026-06-21)
Self-contained HTML tool to hand-build eval gold from the sampled pages. Reads Surya
line-level OCR (`{stem}_surya.json`: bbox+text+confidence) + `_sample_manifest.json`,
crops each line, and emits one portable `.html`: per row = **[line crop] · [raw_line,
editable] · [8 field cells]**, column-ordered, low-confidence (<0.7) rows tinted, junk
rows skippable. Export button → `gold.jsonl` in the EXACT `eval/evaluate.py` schema
(`raw_line` + `context{dialect,alphabetical_range,directory_year,image}` + `record{8 FIELDS}`),
drop into `data/`, scored unchanged. `raw_line` is pre-filled from Surya for free; the
8-field split stays human (true gold, no parser anchoring).
The full loop is **selector → sampler → surya → editor → validator**:
```bash
PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python   # has pillow
# 0. pick a representative panel + worklist (this repo):
python3 data_prep/sample_volumes.py            # -> data_prep/gold_sample/{worklist.csv,WORKLIST.md}
# 1. sample pages for the whole chosen set (one run, in directory-pipeline):
$PY ../directory-pipeline/sources/sample_directories.py \
      data_prep/gold_sample/worklist.csv --front 20 -k 2 --width 1800
# 2. OCR the listing pages (NEEDS the gpu env — surya not in the default venv):
#    in directory-pipeline:  uv sync --extra gpu  &&  python pipeline/run_surya_ocr.py output/<slug>
# 3. build the editor — column_count + year auto-resolve from master_directories.csv
#    via the manifest identifier (override with --cols only if a row is blank):
$PY data_prep/make_gold_tool.py ../directory-pipeline/output/<slug> \
      -o gold_<slug>.html            # --min-conf 0.5 to drop OCR noise; --cols N to override
# 4. correct in browser, Export -> data/gold_<slug>.jsonl, then validate:
python3 data_prep/validate_gold.py data/gold_<slug>.jsonl --images ../directory-pipeline/output --strict
```
**Validated** against existing Surya output (`directory-pipeline/output/greenbook:88`):
payload parses, crops decode, export schema matches `data/lain_eval.jsonl`; auto-cols matched
a faked `1876BPL` dir → col=2 from master. **Gotcha:** Surya needs the `gpu` extra
(transformers <5.0, conflicts with the `local-ocr` Chandra/Qwen env) and `uv`; it's a GPU/Colab
step, not the Apple-Silicon default venv. The builder itself only needs Pillow. Embeds crops as
base64 → keep Surya to the few `-k` listing pages per volume (88-page greenbook = 51 MB; a 2-page
sample ≈ 0.6 MB).

**`data_prep/sample_volumes.py`** — stratified representative selector. Strata default to
`(publisher, column_count)`; spreads picks across each stratum's year range (catches the
1→2→3-col transitions). Excludes PHONEBOOK/BIZ, eval holdouts, blank-id rows. Default run =
**42 volumes** (every publisher; Smith 1→2, Trow 2/3/4, Polk borough-dependent 2/3/4/5/6).
Writes a master-format `worklist.csv` (feed straight to the sampler) + `WORKLIST.md` checklist.
Tune with `--per N` / `--max M` / `--by publisher,column_count,decade`.

**`data_prep/validate_gold.py`** — QA on returned gold before it joins the panel. **ERRORS**
(break `evaluate.py`): bad JSON, missing/extra/`|`-containing/​newline fields, non-bool
is_business, empty name, missing context keys. **WARNINGS** (human glance): field tokens absent
from raw_line (typo/drift — *also fires on legit abbreviation expansion, e.g. `insur`→`insurance`,
~1% on real gold*), occupation that looks like an address, numberless address, firm-name with
is_business=False, bad year/dialect, duplicate rows, image-not-found, year-vs-master mismatch.
Prints field fill-rates + business ratio + lines/image. `--strict` exits 1 on any ERROR (CI-able).
Ran clean on `data/lain_eval.jsonl` (0 errors, 9 warnings — all genuine).

### Transcription conventions (DECIDED 2026-06-21 — the gold/synth/model contract)
These are baked into the editor's conventions panel and enforced by `validate_gold.py`. The
guiding rule: **gold must match how the model represents things** (van Strien eval-realism) — so
the *same* convention governs `synth_persons.py` (train), every `data/*_eval.jsonl` (eval), and
the model's output. Do **not** redefine fields just because you're retraining; a change means
migrating synth + all 7.5k existing eval rows + new gold at once.
- **`raw_line` = verbatim PAGE, the 8 record fields = canonical.** raw_line keeps the page's
  punctuation/structure (commas, prefixes, dittos); the split-out fields use the project's canonical
  form. This is the frame for every rule below. E.g. older directories print `Graves, Benjamin,
  accountant, 71 Dey` — raw_line keeps the surname comma, but `name = "Graves Benjamin"` (no comma).
  The model's *output* format (synth `_nyc_name` = `"{surname} {given}"`, no comma) is canonical; gold
  name must match it, not the OCR substring. *(The surname comma is itself part of the synth→real gap —
  synth never emits it, so the model must learn to strip it; the eval can only measure that if gold is
  canonical.)*
- **raw_line = the corrected PAGE, not the literal OCR.** Fix OCR misreads in raw_line too, not just
  the fields (long-s read as `f`: `Brewsler`→`Brewster`, `George-It.`→`George-st.`; dropped letters).
  raw_line and the fields must tell the same corrected story — `validate_gold`'s token-drift warnings
  flag exactly these one-sided fixes. (raw_line is faithful to the *page*, not to Surya's output.)
- **Verbatim values** — never expand abbreviations (`insur` stays `insur`, `clk.`, `wid.`, `(Rev.)`).
  Expansion is a *separate, reversible* downstream step keyed off the `style_profiles/` legends.
- **No commas in fields** — neither the field-separating commas nor the surname/given comma belong
  in a field value (a leftover comma scores wrong; the scorer strips trailing periods + case + space,
  but not commas). *(Duncan-1794 needed 42/58 surname commas stripped — the `Surname, Given` format.)*
- **Fractions as ASCII** — `1/2`, not the `½` glyph (encoding/tokenization robustness).
- **Titles/honorifics → `name`** (`Rev.`/`Dr.`/`Capt.`/`Mrs.`/`Miss`), verbatim, per
  `synth_persons.py` which generates them into the name string.
- **Role vs employer** — job word → `occupation_role`; an institution/company worked *at* →
  `employer` (e.g. `c. h. clk.` → occ `clk.`, employer `c. h.`).
- **`address` vs `home_address`** — the listed address → `address` (keep the `h`/`r`/`bds`
  prefix; the prefix already encodes work-vs-home). `home_address` is **only** for a *second*,
  separate `h.` home when an entry lists both a work address and a home. A lone `h 449 Clason av`
  goes in `address`. *(Caught + fixed 39/49 inverted rows in the first Lain-1876 gold this way;
  the role-based "work→address / home→home_address" split is rejected — it's undecidable for the
  common single combined-use address.)*
- **Widows → the `wid`/`widow` marker always → `spouse_name`** (verbatim). `widow of John` / `wid.
  John` → John is the husband (→ spouse_name; her own given name, if any, stays in name; if none,
  name is just the surname). `widow Ann` (no "of", a female given name) → Ann is her own name (→
  name), spouse_name is the bare marker. *(Disambiguator = the word "of".)*
- **Ditto marks → verbatim** — copy `do` / `〃` / `''`; don't resolve to the row above (per-line
  model can't see it). Matches the pipeline default (`--expand-dittos` off); resolution is downstream.
- **Race marker → `race_designation`** (verbatim) — the mark is **volume-specific**, defined on the
  volume's key page: Tulsa `(c)`, **Ogden 1839 Brooklyn `*`** ("Names having an `*` are the names of
  colored people"). Drop the mark from `name`, store it as printed in `race_designation` (not
  "colored"); empty when absent. **ALWAYS read the volume's explanation-of-marks page — the same symbol
  diverges:** in **Hope & Henderson 1856** `*` = *Eastern District* (geographic, NOT race — and has no
  schema field, so it's dropped entirely), while colored there is `col'd`. (See `ogden_brooklyn_1830s.md`
  and `hope_henderson_brooklyn_1850s.md`.)
- **Long-s (ſ) → `s`** everywhere (raw_line + fields) — OCR misreads it as `f` (`fexton`→`sexton`,
  `hofier`→`hosier`, `Roofevelt`→`Roosevelt`); it's a typographic form of s, like `½`→`1/2`.

### Phase-1.5 — building the real-OCR eval panel (started 2026-06-21)
The 42-volume panel (`gold_sample/worklist.csv`) is the **eval** set, kept OUT of training.
Per volume: sample → `run_surya_on_samples.py` → `make_gold_tool.py` (label, autosave/import) →
Export → `validate_gold.py` → drop in `data/<slug>_eval.jsonl` (note: `data/` is gitignored, like
all other eval sets — back up out-of-band). Score with `eval/evaluate.py` (the export's
`{raw_line,context,record}` schema is consumed directly as `--gold`); predictions from
`eval/{gliner,gemini,qwen_predict}.py` → `results_table.py`. Depth: ~40 lines/volume, ~100 on the
14 deep-flagged (Lain + col-transition publishers).

**Progress (2026-06-22):**
- **Surya pass COMPLETE for all 42 worklist volumes** (`run_surya_on_samples.py --dry-run` → 0 to
  OCR everywhere), incl. the dense Polk/Trow/M&B pages (got them past MPS OOM with small batches;
  see lessons). **Everything left is browser-only labeling — no more MPS/GPU step.**
- **14 volumes labeled → 893 gold lines** (era coverage 1786–1925; all 8 fields exercised;
  **layout col 1→6 complete**): `lain1876` (103, deep), `boyd1890` (75; topped up
  via Import after verso resample — lone Flushing/Queens rep), `doggett1846` (37), `duncan1794` (58;
  `Surname, Given` → batch comma-strip + 3 widow-inversions + long-s), `franks1786` (56;
  bounded-resampled past almanac/officials), `rode1851` (53; 3 wrapped advertiser raw_lines completed),
  `mercein1820` (60), `ogden1839` (66; **first race-marked volume** — `*`=colored → `race_designation`),
  `hearne1852` (52; Brooklyn micro; `employer` signal), `hopehenderson1856` (60; Brooklyn 2-col — the
  `*`=Eastern-District counter-case, all dropped correctly), `trow1907` (68; first deep multi-column,
  Manhattan col 3 — surname-dash `-Given` dittos), `trow1913` (93; col 4),
  `polk1917` (72; col 5 — Polk surname-ditto is `"` not `-`; `employer`-rich),
  `polk1925` (40; **col 6** — density ladder topped; kept short by design — dense-1920s-Polk style
  already covered by 1917, so no value deepening the same style at col-6 labeling cost). In progress:
  **Polk 1933/34 Staten Island** (`bc958330`, col 2 — first **outer-borough** volume + 1930s era; new
  strata, not more dense-Manhattan). All `data/*_eval.jsonl` validator-clean + `--self-test` green.
  (gitignored — back up out-of-band.) **Layout col 1→6 complete.** Deep progress: 5 of 14 (lain1876,
  trow1907, trow1913, polk1917, polk1925). **Parenthetical rule:** person `(firm)` → firm to
  `employer`; firm `(person)` → person stays in `name`. **Next priority = breadth (boroughs / std
  tail), not depth** — the layout + field spectrum is covered.
  **QA tip:** re-run `validate_gold` after each export; the slips it caught (commas, inverted widows,
  year mismatch, raw_line↔field OCR-fix drift) are the recurring ones.
- **First real-data numbers** = the GLiNER *floor* on Lain-1876 (`results/scores.jsonl`, label
  `gliner-lain1876`): macro-F1 **0.33**, whole-row EM **3.9%**; weakest field **`address` F1 0.16**
  (extractive GLiNER can't rebuild the `h` prefix / work-vs-home split), `name` F1 0.54. Rare fields
  (spouse/employer/home_address) found 0 → **read F1, not EM, for sparse fields** (high EM there is
  just empty-matches-empty). These are the floor; the Qwen-fine-tune and Gemini-bar runs are the
  signal — still TODO (need checkpoint/GPU + `GEMINI_API_KEY`).
- **New tooling since 2026-06-21:** editor focus-mode jump-to-next-column/page; autosave + Import;
  `make_gold_tool --max-lines N`; **`make_gold_tool` now prefers the master year over the manifest
  date** (IA dates two-year volumes by the first year → was tripping the validator on every Doggett
  row); `validate_gold` address/home_address + year-vs-master checks; `run_surya_on_samples
  --blank-std` (skip blank versos) + per-image batch loading (one corrupt jpg no longer sinks the batch).
- **Finalize recipe per export** (`gold(N).jsonl` → `data/<slug>_eval.jsonl`): home_address fix
  (move sole-home → address), then `validate_gold --strict`, then `evaluate.py --self-test`. New gold
  needs ~0 fixes now that the conventions panel is in the tool (Lain needed 39 home moves; Boyd/Doggett
  needed 0).
- **Next:** work down `WORKLIST.md` — all browser-only now. Std ~40 (`--max-lines 40`), deep ~100
  (`--max-lines 100`). Ready std `ia_*`: Duncan 1794, Franks 1786, Mercein 1820, Ogden 1839, Rode
  1851, Hearne 1852, Hope&Henderson 1856, Reynolds 1852, Smith 1854/55/56. Deep: Polk ×5, Trow
  1884/1907/1913, M&B 1931, Spooner. Skip `loc_spooner_01015253` (partial scan, no listing).

## Phase 2 — retrain loop (eval-driven; uses the real gold above)
*(Operational companion to "THEN — Phase 2" above, which lists the synth changes.)*
**The real gold is the measuring stick, never training data.** The loop:
1. Run the current model on the real gold → see *which* fields/styles/abbreviations fail
   (per publisher/era — that's the signal the breadth was for).
2. Parameterize `synth_persons.py` with the per-publisher/era legends + layouts from
   `style_profiles/` so synthetic lines carry the real patterns the model misses.
3. Regenerate synth → retrain → **re-eval on the same gold** to confirm lift (esp. Lain).
4. Convention stays fixed throughout (see contract above) so score deltas mean real change.

## Key paths
- Master list: `data_prep/master_directories.csv` (schema in `master_directories.README.md`).
- Style cards: `data_prep/style_profiles/` (`README.md` = card schema + build recipe + lessons).
- Ingest tool (FIELDS): `data_prep/ingest_collection.py`.
- Sampler + detectors: `../directory-pipeline/sources/sample_directories.py`,
  `../directory-pipeline/pipeline/detect_columns.py`, `detect_spreads.py`.
- Synth generator (Phase 2 target): `data_prep/synth_persons.py`.
