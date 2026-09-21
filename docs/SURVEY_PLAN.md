# Corpus survey plan

> A comprehensive, resumable, overnight-paced survey of every **non-phonebook** volume in
> `data_prep/master_directories.csv` (337 rows: 184 `ia`, 151 `nypl`, 2 `loc`). The goal is to
> fill and **confirm** the catalog from the volumes themselves, harvest their OCR, find where
> the listings start and stop, and produce evidence-backed style profiles.
>
> Written 2026-09-12. Every number below was measured, not estimated; the measurement is named
> in place so a later session can re-run it rather than trust it.

## The two principles

**1. Agents buy exactly one thing: eyes on a page that text cannot settle.** Everything else is
a deterministic local script. The corpus is 337 volumes and ~150k leaves; anything that spends an
agent per leaf, or a page image where a byte range would do, does not finish.

**2. Catalog metadata is a hypothesis. The book is the evidence.** IA's `metadata` endpoint,
NYPL's MODS and the existing CSV values are all recorded as `catalog_says` and are never promoted
to fact. A field is confirmed only by something printed **in the volume** — and that something is
cited by leaf, canvas URL and verbatim quote, so any later reader can check it.

### The citation rule

Every diegetic claim in a sidecar carries its source. No exceptions, including the ones that
"obviously" agree with the catalog.

```json
"book_says": {
  "publisher": {
    "value": "George Upington",
    "leaf": 1,
    "canvas": "https://iiif.archive.org/iiif/1906BPL$1/canvas",
    "image": "https://iiif.archive.org/iiif/1906BPL$1/full/1800,/0/default.jpg",
    "evidence_type": "title_page",
    "quote": "GEORGE UPINGTON, Publisher",
    "method": "hocr-text",
    "confidence": "high"
  }
}
```

`method` is one of `hocr-text` · `ia-page-numbers` · `hocr-geometry` · `agent-read` · `human`.
A claim with no `leaf` is not a claim; it stays in `catalog_says`.

---

## What is already measured

### The three-way join is exact — and `leafNum - 1` is an off-by-one trap

For any IA item:

```
hOCR pageindex leaf L  (0-based)
  ==  IIIF canvas index L        (iiif.archive.org/iiif/<ident>/manifest.json)
  ==  <ident>_page_numbers.json entry with leafNum == L
```

Verified on 1906BPL against seven independent reads of the bottom-centre margin line in the hOCR
(leaves 200, 201, 400, 401, 700, 1000, 1100 → 202, 203, 400, 401, 694, 992, 1090 — all exact).

**`leafNum - 1` looks right and is wrong by exactly one printed page.** 1906BPL has 1254 hOCR
leaves and 1253 `page_numbers` entries, because leaf 0 has no entry; that off-by-one is the whole
trap. A `start_page` filled through the wrong mapping is plausible, uniform, and silently wrong
across the corpus.

The IIIF manifest carries **no page numbers** — its canvas labels are the canvas index as a string
(`"200"`). Its job is the image URL and confirming the alignment. Printed numbers come from
`_page_numbers.json`.

### Printed page numbers are free for 86 of 184 volumes

`<ident>_page_numbers.json` ships with every IA item — per-leaf
`{pageNumber, leafNum, ocr_value, confidence}` plus a volume-level `confidence`. Nothing in this
repo used it before. Censused over all 184 non-phonebook `ia` rows (184/184, 0 errors, 47 s):

| tier | vols | definition |
|---|---:|---|
| **A** trust directly | 31 | vol-conf ≥ 90 and ≥ 85% of leaves numbered |
| **B** verify monotone | 55 | vol-conf ≥ 50 or ≥ 70% numbered |
| **C** sparse / unreliable | 59 | neither |
| **D** empty | 39 | file present, zero numbers |

58,343 leaves already carry a printed number. **C is closer to D than to B** —
`brooklynnewyorkc19062geor` is "C" with 11 of 1346 leaves filled — so plan on
**86 free / 98 fallback**, not 145/39.

No shortcut for C/D: `ocr_value` (IA's raw candidate tokens) is populated only on
high-confidence runs. Checked 4 D + 2 C volumes — 0% on all six.

### The fallback fails where the primary succeeds, which is what makes a cascade honest

Reading the short numeric token from the bottom margin of the hOCR gave, on 1906BPL, a number on
**77%** of leaves with 15/132 non-monotone before any filtering, and recovered the full documented
drift curve: `-11 → -1 → +3 → +5 → +7 → +9 → +11`.

Tier C is dominated by dense 1900s–1910s ABBYY volumes (27 + 14 by decade; 49 of 59 are ABBYY) —
exactly the population where that regression works best. So:

1. `_page_numbers.json` where tier is A/B — free
2. hOCR bottom-margin regression where it is C/D — free, and well matched to that population
3. **agent page read only where both fail, or where the two disagree**

Two independent detectors means agreement is evidence rather than assumption.

### Evidence hierarchy for bibliographic confirmation

The title page is **in the hOCR**. Confirmation does not require an image read for most volumes.

| rank | source | authority | measured example |
|---|---|---|---|
| 1 | printed title page + copyright line | the volume's own claim | 1906BPL leaf 1: `VOLUME LXXXIII`, `GEORGE UPINGTON, Publisher`, `ENTERED ACCORDING TO ACT OP CONGRESS IN THE YEAR NINETEEN HUNDRED AND SIX` |
| 2 | microfilm target card | the filming library's cataloging | `micro_IABROOKLYN_0005` leaf 1: `Spooner's Brooklyn Directory, for the year 1826 … Published by Alden Spooner, at the office of the Star, No. 55 Fulton-street. June, 1826.` |
| 3 | TOC / section heads / inline legend | structure | `micro_IABROOKLYN_0005` leaf 5: `N. B. h. stands for house, n. for near, and c. for corner.` |
| — | IA `metadata`, NYPL MODS, current CSV | **hypothesis only** | `newyorkbrooklynd00durs`: title says 1786-1796, `date` says **1876** |
| ✗ | modern scan cover sheets, bookplates, `Digitized by the Internet Archive in 2013`, Reynolds/Durst collection stamps | noise — excluded by pattern | 1906BPL leaf 0 is a BPL PDF-instructions sheet, not the book |

The year is often attested in a form immune to digit OCR error: spelled out in the copyright line,
or as a regnal-style formula. `longworthsameric1798newy` leaf 7 dates itself
`Twenty-third Year of American Independence` (1775 + 23 = 1798) — and its title-page OCR is
otherwise mangled (`ATSD- CITY DIRECTORY* 70R THE ?• TivrtHy-thlrd`). **That is the escalation
case, and it is one leaf and one image.**

### `year` needs splitting before 337 rows get filled

Volumes routinely disagree with themselves. `micro_IABROOKLYN_0022` is CSV `1845` against a title
page reading "for 1845 and 1846"; Spooner's is "for the year 1826 … June, 1826"; Trow volumes were
published the autumn before their nominal year. Record `year_covered` and `year_published`
separately in the sidecar; keep the CSV's single `year` as the human-facing summary.

### The real competition for the title page is advertising, not other title pages

Found while building phase 0b, and it is the single thing most likely to corrupt this survey.
**1857BPL leaf 4 beat the real title page and dated the volume 1837.** It opens:

```
BROOKLYN DIRECTORY ADVERTISER.
ON BROOKLYN HEIGHTS,
ALPEED GREENLEAF, A.M., Proprietor and Principal.
Established May, 1837, at an outlay of 130,000.
```

It carries every cue a title page has — the word *directory*, a year, a proprietor. The real
title page is leaf 27: `SMITH'S / BROOKLYN DIRECTORY, / FOR THE YEAR ENDING / MAY 1st, 1857`.

Two things separate them, and **line count is not one of them** — the ad has 23 lines, the title
page 16, the wrong way round. What works:

1. an ad section head **names itself** (`advertiser` / `advertisements` in the leading lines)
2. ad copy is **prose**; a title page is display type in short lines. Share of lines over 55
   characters: ad **0.38**, title page **0.00**.

`title_strength()` in `survey_frontmatter.py` scores both, and anything below the bar escalates
rather than answering. Target cards are scored on the same scale rather than exempted — a blanket
"only title pages count" would escalate all 49 microfilm volumes; a genuine card scores 6.

### The conflict gate

When the page disagrees with **both** the CSV and IA metadata, that is far more often an ad
misread as a title page than a genuine catalog error. So the claim is kept, with its citation and
`conflicts_with_catalog`, its confidence drops to `low`, and the volume goes to the image-read
queue. **Nothing silently overwrites a correct cell**; the disagreement is surfaced for a human or
a phase-3 read to settle.

### `publisher` in the CSV is not the publisher on the title page

1857BPL: the CSV says **Smith**, the title page says the book is *SMITH'S Brooklyn Directory* and
the imprint names **CHARLES JENKINS**. Both are right — Smith is the compiler the title is named
for, Jenkins is who published it. 1906BPL's title page names *GEORGE UPINGTON* as publisher and
*WYNKOOP HALLENBECK CRAWFORD CO.* as printer (the latter visible in the page image but dropped by
the OCR). These want separate fields: `compiler`, `publisher`, `printer`. Until they exist, the
report treats surname containment as agreement so the genuinely different houses stand out.

### Phase 0 results (run 2026-09-12, all 184 IA volumes)

| | |
|---|---:|
| `frontmatter-done` | **103** |
| `needs-image-read` | **81** |
| field confirmations | **312 agree** |
| conflicts | **61** |
| claims extracted | year 141 · title 104 · publisher 93 · volume_number 61 · legend 60 |
| `year_covered` / `year_published` recorded separately | 42 / 21 |
| legend location | dedicated key page 20 · inline at listing head 40 |

Cells the survey can now fill: **86** `start/end_page` + `page_offset` (free, tier A/B), **61**
`volume_number` (a new column), **55** `key_page`.

**Twice as many legends are inline as are on a dedicated page (40 vs 20).** The `key_page` column
assumes a page; it needs a companion `legend_location`.

### Phase 0 writeback — done 2026-09-20, and two of those cells were not ready

`apply_survey.py` merged the sidecars into `master_directories.csv`: **248 fills, 198
confirmations, 32 conflicts left untouched**, and a second run writes nothing.

| written | | not written | |
|---|---:|---|---|
| `volume_number` | 61 | `start_page` / `end_page` / `page_offset` | needs Phase 2 |
| `legend_leaf` | 60 | `key_page` | unit mismatch — see below |
| `legend_location` | 60 | | |
| `year_covered` | 42 | | |
| `year_published` | 21 | | |
| `publisher`, `year` (empty cells only) | 4 | | |

**The `--gaps` line "86 start/end_page + page_offset (free, tier A/B)" counts routes, not values.**
It is computed from `page_numbers.tier` alone; Phase 0 never looked for where the listings start.
Nothing was in hand to write.

**`key_page` was the near-miss.** The CSV column is a *printed page*; `book_says.legend` carries a
*leaf*. On the 6 volumes where both exist, `key_page + page_offset` reproduces the sidecar leaf
exactly twice and is off by one on three more — the `leafNum − 1` trap, not a wobble. The leaf went
to a new `legend_leaf` column instead. **Resolved 2026-09-21** (below): the column was never the
problem, the unit was, so `key_page` is now *conditional* rather than forbidden — writable only
from a `method: ia-page-numbers` claim, which only the converter produces.

### `key_page`, converted — and the yield is 17, not 40

`survey_pagenumbers.py` (2026-09-21) does the leaf→printed-page lookup. Predicted 40 conversions;
**the real number is 17, and 11 of those reached the CSV.**

| of 45 tier-A/B volumes with a `legend_leaf` | |
|---|---:|
| leaf carries a printed number → claim | **17** |
| leaf is **unnumbered** → no claim | **28** |

**Front matter is frequently not paginated, and that is a fact about the books, not a gap in the
data.** `micro_IABROOKLYN_0002` leaf 5 and 1879BPL leaf 27 are blank, with their volumes' numbering
starting at leaves 8 and 29. Extrapolating backwards (leaf 29 = page 3, so leaf 27 "=" page 1)
would manufacture a number that **is not printed on the page** — in the one region where the offset
is least stable, since front matter routinely carries its own roman sequence or restarts at the
listing head. So a blank leaf yields nothing, and for those 28 volumes the key page must be cited
by leaf. That is the argument for `legend_leaf` being a real column rather than a staging area.

**Of the 17, only 3 reached the CSV**, and getting there took one wrong turn that is worth keeping
on the record.

**`confidence: null` does not mean "unscored". It means IA INTERPOLATED the number.** Proven by
opening the page. `hearnesbrooklync1852unse` runs:

```
leaf 24 -> '14' conf 100     leaf 25 -> '15' conf 100      <- read off the page
leaf 26 -> '16' conf null    27 -> '17' null    28 -> '18' null   <- filled in arithmetically
leaf 29 -> '19' conf 100     leaf 30 -> '20' conf 100      <- read off the page
```

The nulls are arithmetic between confident anchors. And leaf 27 is the directory's **opening
page** — caption title, the `*` NOTE, then the A listings — which **prints no folio at all**; the
`2` at its foot is a printer's signature mark. IA asserts page 17 for a page that prints nothing.

The first cut read null as "IA gave no opinion, so fall back to the volume's coherence" and graded
it `medium`, which is CSV-grade. **That put 8 interpolated folios into the CSV.** They were
retracted by `apply_survey.py --retract`. An interpolated folio is *weaker* evidence than a read
one, not neutral, and a volume whose legend leaf is interpolated cites its key page by **leaf**.

| of the 17 conversions | | |
|---|---:|---|
| `attestation: read`, CSV-grade | **3** | 1906BPL (IA conf 100), 1907BPL (99), `micro_IABROOKLYN_0004` (84) |
| `attestation: read`, confidence 0 | 4 | a real score, and a bad one |
| `attestation: interpolated` | 10 | never CSV-grade, however coherent the volume |

The other half of the original calibration fix stands: **monotone breaks must be a RATE.** These
volumes hold several alphabets and legitimately restart their numbering, so 1906BPL shows 11
backward steps in 1,245 leaves (0.9%) at leaf confidence 100 — and its ABBREVIATIONS page was
checked by eye and does print **21** at the foot. Gating `high` on zero breaks downgraded every
dense volume in the corpus.

### ⚠️ The `page/nNN` image URL is not globally aligned with `leafNum`

**This plan asserts one global join verified on one volume, and it does not hold corpus-wide.**
1906BPL's `n9` is leafNum 9 (its legend page, printing 21). `hearnesbrooklync1852unse`'s `n27` is
leafNum **28** — its legend sits at `n26`. The `_page_numbers.json` files differ in whether they
start at leafNum 0 or 1, and Hearne's has gaps (584 entries spanning 1..588).

Every `image` URL in every sidecar is therefore suspect by one leaf, including the ones cited in
the Phase 0 conflict queue above. **Unresolved** — it needs a per-volume alignment check, not a
constant.

**And the conversion found a live contamination in the column it was built to protect.**
`hearnesbrooklync1852unse` carries `key_page=27` — a **leaf**, written by commit `94fe7fe`, whose
own message says "Leaf 27 … prints the legend". The page itself prints no folio; its position in
the sequence is 17. `start_page=28` on the same row is likely the same error.

Once that volume's own claim dropped below CSV grade it stopped being *proposed*, so it stopped
appearing as a conflict too — a known-bad cell silently leaving the queue. `unit_suspects()` in
`apply_survey.py` now catches the bug class directly by asking whether a printed-page column holds
a value equal to the **legend leaf**. It flags 3: `hearnesbrooklync1852unse` (27, against its own
claim of 17), plus `micro_IABROOKLYN_0005` (5) and `1885BPL` (1) — the latter two may be
coincidence, since a legend really can sit at leaf 1 on printed page 1. None is auto-corrected; a
human entered them.

**The 32 refusals are a work queue, not noise.** 19 `publisher` + 13 `year`:

| class | n | |
|---|---:|---|
| `publisher` = `spooner` across the microfilm set | 9 | **the biggest single finding** |
| the read is OCR-damaged | 5 | `GEORGE TTBiNfiTriM`, `D. L0NGW0RTH`, `THOMAS LONGWOIITH` — Phase 3 |
| genuinely a different house | 3 | Lain→`CEO. H. CLARKE`, Franks→`SHEPARD KOLLOCK`, Boyd→`JOHN J. BRENNAN` |
| compiler vs publisher | 2 | Smith/`CHARLES JENKINS`, on 1857BPL *and* `micro_IABROOKLYN_0036` |
| the year read is not the volume's year | 9 | see below |
| the page contradicts the catalog for real | 3 | |
| OCR garbage | 1 | `flushingnewyorkc00boyd` reads 1800 against CSV 1890 |

**The `spooner` cluster is worth looking at first.** `micro_IABROOKLYN_0010/0012/0015/0019/0020/
0024/0025/0027` and `brooklynalphabet1843unse` all carry lowercase `spooner` in the CSV, against
target cards naming Lewis, Wm. J. Hearne, Henry R. Hearne, A. G. Stevens & Wm. H. Marschalk,
Thomas Leslie and Betts Burrell. Uniform, lowercase, and contradicted by nine different cards:
that reads as a collection-level default that was never revisited, not as nine assertions.

**Nine of the thirteen year conflicts are the extractor grabbing a year that isn't the volume's**,
and the *sources* of the bad year are more varied than the plan anticipated — it is not only ads:

- founding dates — `Established 1870`, `ESTABLISHED 1837`, `Established 1847` (3)
- **copyright-statute boilerplate** — `IN FORCE JULY 1, 1909` on two 1913 Trow volumes (2)
- **listing text bleeding into the front matter** — `R 1801 — A. E. Humphrey, Sec.` and
  `h 1853 1st av` are directory *entries*, house numbers read as years (2)
- prose discussing another year — 1866BPL's `more than the year 1863-4` (1)
- a photo credit — `Photo copyright, 1906, by Irving Underhill` (1)

The last two classes are new. A year-claim gate that required the year to sit near an imprint or
copyright *verb* would kill most of these.

Three are the *catalog* being wrong and the page proving it: `newyorkcitydirec00rode` (copyright
`in the year 1854` vs CSV 1851), `newyorkdirectory00durs_0` (a `1851` imprint vs CSV 1786 — the
reprint/original tangle again), and `longworthsameric00newy` (CSV 1816 against `SIXTY-FOURTH YEAR
OF AMERICAN INDEPENDENCE` = 1775 + 64 = **1839**). The gate refused all three anyway, which is the
design — they go to a human, not into the column.

### Four witnesses, not two — and the CSV is not IA

Year conflicts are adjudicated by **four independent witnesses**: the CSV, IA's `date`, a year
embedded in the IA identifier, and the page. Counting the CSV as part of "the catalog" destroys
the signal — `longworthsameric1839newy` has csv 1839, page 1839, identifier 1839 and IA 1816,
which is 3-1, not a stand-off. The 61 conflicts sort into a work queue:

- **the READ is the outlier → send the image (22)**
- **publisher, no year witness (19)**
- **the CATALOG is the outlier, IA wrong (16)** — findings, below
- split, no majority (4)

**All 16 catalog-outlier cases are IA metadata errors the page disproves**, and they cluster:

- **IA dates an entire series from its first volume.** Every `longworthsameric*` volume is dated
  **1797**; the books say 1814, 1816, 1835, 1836, 1839, 1840 — attested by `YEAR OF OUR LORD 1814`
  and by the regnal formula (`Sixty-first Year of American Independence` = 1836). Same pattern on
  Trow: `trowsgeneraldire19032trow` and `19073trow` are both dated **1853** by IA against printed
  `JULY 1, 1903` and `JULY 1, 1907`. This resolves the README's "Durst `longworthsameric*` rows
  have blank years" cleanup lead — the volumes identify themselves.
- **`newyorkbrooklynd00durs`: IA `date` 1876, page `For 1786`** — a digit transposition.
- **`newyorkdirectory00fran` and `_0`: IA 1889, page 1786** — 1889 is the facsimile reprint date,
  and the imprint on one of them names `THE TROW CITY DIRECTORY COMPANY`, confirming which row is
  the reprint rather than the original.
- **Upington 1906/1907 are both dated 1903 by IA**; the pages say 1906 and 1907, and the printed
  volume numbers corroborate independently — LXXXIII then LXXXIV.

Two operational notes. **IA returns transient 500s**: 4 of 184 volumes failed on one sweep and all
four succeeded on a plain retry, so the Range fetch retries 3× — without it, live volumes land in
the failure register as dead. And the extracted front-matter **text** is cached in
`data/survey_fm_text/` (12 MB, 181 volumes), so re-running the extraction is instant and offline;
this file was rewritten three times at ~3 network-hours each before that existed.

### Negative results — do not re-derive these

- **Voting the running head across a volume does not confirm the title.** Expected ~1,200
  redundant OCR samples of the title; on 1906BPL the top margin is *advertising*
  ("FRANKLIN TRUST COMPANY", "JAMES A. WEBB & SON"). Page numbers live in the bottom margin, ads
  in the top. Dead as a title check — but "top margin is ad inventory" is a real per-volume
  structural fact worth recording.
- **The surname harvest is done and its coverage result was negative.** See
  `docs/HANDOFF.md` — 99.3% of directory surnames appear on exactly one page, so the gold-surname
  miss rate is a leakage detector, not a coverage metric. A full sweep grows the pool essentially
  for free as a Phase-2 byproduct (page-unique names are unreachable by sampling and trivial by
  census), **but do not re-run the coverage experiment expecting a different number.** The open
  question — whether a rich pool teaches robust copying — needs a training run, not more names.
- **`ocr_value` is not a fallback** for tier C/D page numbers (0% populated; see above).

---

## Phases

Each phase is independently resumable, writes only sidecars, and can be stopped mid-corpus
without losing work. Phases 0 and 2 need no agents at all.

### Phase 0 — census and diegetic evidence (no agents)

**0a `survey_census.py`.** One IA metadata call per volume → derivative inventory, `imagecount`,
OCR engine/vintage, contributor, dates, titles, hOCR size, plus `_page_numbers.json` tiering.
Everything lands under `catalog_says`. Cached in `data/survey_census/` (gitignored, re-fetchable).

**0b `survey_frontmatter.py`.** The front matter is reachable **without the 21.7 GB sweep**: the
pageindex gives byte offsets, so leaves 0..N are one contiguous HTTP Range request per volume,
not a whole-volume download. Measured: 1906BPL's first 30 leaves are 5.75 MB of a 305 MB file
(1.9%); `longworthsameric1798newy` 0.73 MB of 14.3 MB. Parse those leaves, classify each (noise /
target card / title page / TOC / legend), extract cited claims, write `book_says`.

The read is **bounded**: IA's storage node sometimes ignores `Range` and answers 200 with the
whole file — 1.6 GB for `trowsgeneraldire1917trow` — so at most `end` bytes come off the socket
before the connection is dropped. That is safe precisely because front matter begins at byte ~583,
so the first `end` bytes of the whole file contain the same span. Verified during the run: only
the 3 deliberately-cached hOCR files exist on disk afterwards.

**0c `survey_report.py`.** Offline. Compares `book_says` against `catalog_says` and prints the
conflicts with the image URL that settles each. `--reads` prints the phase-3 queue, `--gaps` the
cells the survey can now fill.

Output: `data_prep/survey/<source>_<id>.json` (committed — this is the survey record; 336 files,
~1.3 MB).

### Phase 1 — OCR harvest (the only heavy step)

Serial, one volume at a time, backoff, resume. Fetch pageindex + `_hocr.html` once →
`data/<ident>_lines.jsonl.gz` + `_dropped.txt` → **delete the hOCR**. Peak disk stays at one
volume.

**Budget: 21.7 GB total, median volume 79 MB.** Four volumes exceed 500 MB and get their own
night: `trowsgeneraldire1917trow` **1588 MB** (2480 leaves), `trowsgeneraldire1915trow` 1470 MB,
`trowsgenerald192223p2trow` 643 MB, `trowsgenerald192223p1trow` 566 MB. For scale, 1906BPL's
305 MB hOCR yields an 81 MB `_lines.jsonl`.

### Phase 2 — free derivation (no agents, no network)

Per volume, from the JSONL + pageindex + `_page_numbers.json`:

- `detect_listing_bounds --from-jsonl` → start/end leaf, letter blocks, gaps, order violations,
  ambiguous edges
- printed `start_page` / `end_page` via the cascade above. **`survey_pagenumbers.py` now exists
  (2026-09-21) but only its tier-A/B half** — the direct `_page_numbers.json` lookup. The tier-C/D
  bottom-margin regression, which `survey_census.py`'s docstring has described since 2026-09-12,
  is still unwritten.
- **`page_offset` as a per-leaf curve**, not a scalar. The README's "drifts across a volume —
  local anchor, not a global constant" stops being a limitation: the sidecar stores the curve, the
  CSV keeps one human-readable local anchor near the listing start.
- **section inventory** — these volumes hold several alphabets (residential, business/trade,
  street, "new and changed", ward lists, churches). `detect_listing_bounds`' order-violation signal
  already detects the second alphabet; record *every* section's leaf range. 1906BPL leaf 8 is
  "Names too Late for Classification" — a supplementary listing sitting before the main one.
- **ad-run inventory** (the reported gaps) — feeds the banded-advertising work
- content-leaf census vs `imagecount` (the ~2× blank-verso overstatement)
- **ditto convention** — which glyph the volume prints and how its OCR renders it (1906BPL: `"`
  and `44`)
- abbreviation frequency table, median line length, line-length distribution
- surname/given-name pool as a byproduct

### Phase 3 — the one agent fan-out (cheap tier, gated)

Per volume, a script assembles a read packet of the **2–3 images the text could not settle** and
hands it to one cheap agent with structured output and an arithmetic/consistency gate — the shape
`data_prep/trow_fanout.workflow.js` already proved. Escalate gate failures to a stronger model in a
second small pass.

Typical packet: the abbreviations key page (genuinely needs eyes), a `column_count` confirm, and
any AMBIGUOUS boundary leaf. Volumes whose Phase-0 evidence is clean and whose bounds are
unambiguous may need only one image.

Note `key_page` is not always a separate page — some volumes print the legend inline at the
listing head. The style-profile schema currently assumes a page and needs a `legend_location`.

### Phase 4 — style profiles by family

~20–30 publisher × era families, not 337 volumes. Feed each family its transcribed legends,
measured abbreviation tables and sample lines → confirm or extend the cards in
`data_prep/style_profiles/`. The measured statistics let a card be **refuted**, which the
hand-built ones currently cannot be.

### Phase 5 — the NYPL tier (151 rows)

No OCR at all, so no Phase 1 or 2 — every field costs an image read. Run it **after** IA, so that:

- IA results calibrate the prompts before any spend, and
- **twins cross-fill**: many NYPL volumes have an IA counterpart of the same publisher and year.
  Printed page numbers are edition-stable even when canvas indices are not, so a measured IA
  `start_page` transfers and shrinks the expensive tier.

NYPL's existing fill is already partial (`start_page` ~86/151 from earlier visual work).

---

## Writeback discipline

**Nothing in this survey writes `master_directories.csv` directly.** Agents and scripts write
per-volume sidecars; a single idempotent `apply_survey.py` merges them in one pass with a diff
report. Reviewable git diffs, no concurrent-write corruption, safe to re-run nightly.

`apply_survey.py` exists as of 2026-09-20 and holds three rules: a sidecar fills an **empty** cell
and never overwrites a full one; a value is only written into a column that **means the same
thing** (`FORBIDDEN` names the columns it must not touch, with the reason); and a second run
writes nothing. Dry-run by default — `--write` commits, `--conflicts` prints every refused cell
with its citation and image URL.

### The decision record — `survey_decisions.json` (2026-09-21)

A regenerated queue cannot tell *"not yet reviewed"* from *"reviewed, the catalog was right"*, so
without this the same 32 conflicts reprint forever. The queue is derived; the verdict is not.
(`results/ditto_review_*.tsv` has the identical missing half — PIPELINE.md #1 asks to "record which
volume it was decided for" and nothing ever did.)

Keyed `(source, id, column)`, five verdicts: **`book-wins`** — the only path that overwrites a
non-empty cell, and it is refused without a `reason` — plus `catalog-wins`, `both-right`,
`needs-image` and `wontfix`, which retire a conflict without touching the cell. `--conflicts` then
shows the undecided queue and the decided list separately.

Seeded with the 7 verdicts this plan already establishes (2 `both-right` for the Smith/Jenkins
compiler split, 5 `needs-image` for OCR-mangled publishers). **The `spooner` cluster is left
undecided on purpose** — it needs a human. So are the 9 bad-year reads: recording `catalog-wins`
on those would paper over an extractor bug that should be fixed at the source.

The CSV stays the human-facing summary. The sidecar holds the citations, the offset curve, the
section inventory and the confidence — anything that would explode the column count.

## Leakage

A full-volume sweep contains **every gold page by construction**; sampling could dodge them and
this cannot. `docs/HANDOFF.md` records the trap — a one-page canvas drift pulled the polk1917 gold
page into a harvest slice and inflated a result 3.5×, with the standing warning **"never trust
canvas arithmetic to exclude a gold page; verify after downloading."**

So: an explicit `eval_holdout` marker in the sidecar, enforced *inside* the sweep, excluding
eval volumes whole or by verified leaf range — not filtered downstream by whoever remembers.

## Failure register

Every volume carries a `survey_status` with a reason code, so a nightly job never re-walks a known
dead volume: `ok` · `no-hocr` · `dead-ocr` (chars/page an order of magnitude below its class) ·
`not-residential` · `duplicate-of:<id>` · `restricted` · `fetch-failed`.

Related: **duplicate and multi-part detection.** `master_directories.README.md` already flags
p1/p2/p3 parts and duplicate scans across IA collections. Cluster on
(publisher, year, city, imagecount, title) and stamp `duplicate_of` / `part N of M`, or everything
downstream double-counts.

## Also worth recording while the sweep is running

- **rights status** per volume — a public HF release is the goal and there are 1933 rows in the
  non-phonebook set
- **provenance of the OCR itself** — IA `sha1` and `mtime` of the hOCR derivative plus fetch date,
  so a re-derivation is reproducible and a later IA re-OCR is detectable
- **a coverage report** — publisher × decade × borough. Thin in the 1860s–90s (21/16/18/14
  volumes) against 57 in the 1900s; Trow 1898/99 is a known hole.
- **OCR tier** from engine + chars/page, using the measured triage rule (an order of magnitude
  below its class), not "did it produce output". Corpus engines: ABBYY-8 **71**,
  tesseract-microfilm 49, ABBYY-9 39, none 21, ABBYY-11 4 — independently reproducing the
  71-volume ABBYY-8 bucket measured in `historical-ocr-eval`.
