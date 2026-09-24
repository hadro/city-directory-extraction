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
    "image": "https://iiif.archive.org/iiif/1906BPL$1/full/1400,/0/default.jpg",
    "evidence_type": "title_page",
    "quote": "GEORGE UPINGTON, Publisher",
    "method": "hocr-text",
    "confidence": "high"
  }
}
```

`method` is one of `hocr-text` · `ia-page-numbers` · `hocr-geometry` · `agent-read` · `human`.
A claim with no `leaf` is not a claim; it stays in `catalog_says`.

**`image` is always a IIIF URL**, never `archive.org/download/<id>/page/nNN` — that is a separate
numbering whose alignment with the leaf is per-volume, and citing it sent readers to the wrong page
on 2 of 3 volumes checked. See the resolution below; build it with
`survey_frontmatter.page_image()`.

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

### The `page/nNN` image URL was not leaf-aligned — RESOLVED 2026-09-21

**Cite images by IIIF. `archive.org/download/<id>/page/nNN` is a fourth numbering and its
alignment with the leaf index is per-volume.** Measured by opening pages in both schemes:

| volume | collection | `page/n<leaf>` | IIIF `$<leaf>` |
|---|---|---|---|
| 1906BPL leaf 9 | BPL | ✅ ABBREVIATIONS page, prints 21 | ✅ same page |
| `hearnesbrooklync1852unse` leaf 27 | Columbia | ❌ wrong page (prints 18); legend is at `n26` | ✅ the legend |
| `micro_IABROOKLYN_0012` leaf 1 | microfiche | — | ✅ the target card |

IIIF was correct on all three, across three collections; `page/nNN` on one of three. IIIF also
uses the same integer as the hOCR pageindex, so it is the scheme the rest of the survey is already
indexed by — not merely the safer choice.

`survey_frontmatter.page_image()` is now the single definition and returns IIIF;
`survey_pagenumbers.py` and the migration import it. **539 existing citations across 167 sidecars
were migrated** by `survey_fix_image_urls.py` (idempotent; 539 insertions, 539 deletions, no other
line touched).

**This mattered most for the queue that was about to be worked.** The `spooner` cluster is
adjudicated by opening the cited target card; nine of them cited one leaf off would have been
judged against the wrong page — the same class of error that put a leaf in `key_page`. The first
card opened under the corrected URL already moved a row: `micro_IABROOKLYN_0012` reads *"Brooklyn:
Printed by Lewis Nichols, 112 Bridge-street. 1835."* — so the publisher is **Lewis Nichols**, and
the sidecar's `Lewis` is a truncation, not the name.

The original error is worth naming because it repeats: `page_image()` carried a docstring saying
it was *"verified against the hOCR leaf index, visually, on 1906BPL leaf 1."* That was true, and
1906BPL is the one volume where the two schemes agree.

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

**The `spooner` cluster — SETTLED 2026-09-21. Not one of the nine names Spooner.** All nine were
read at the corrected IIIF citation and confirmed. They attest a clean succession:

| 1833–34 | Nichols & Delaree | *printed by* Lewis Nichols |
| 1835–36 | Lewis Nichols | |
| 1838–39 | A. G. Stevens & Wm. H. Marschalk | Arnold & Van Anden |
| 1843–44 | Thomas Leslie, Henry R. & William J. Hearne | Stationers' Hall Works |
| 1844–45 | Henry R. & William J. Hearne, & Edwin Van Nostrand | Stationers' Hall Works |
| 1847–48 | Wm. J. Hearne & James E. Webb | Lees & Foulkes |
| 1848–49 | Henry R. & William J. Hearne | Lees & Foulkes |
| 1849–50 | Henry R. & William J. Hearne | Lees & Foulkes |

### The whole Brooklyn microfilm series, read end to end (2026-09-22)

Phase 3 read every target card in `micro_IABROOKLYN_0001`–`0028`. **The catalog's `spooner` was
not simply wrong — it was right, and then it was carried past its expiry.**

| vols | years | publisher / compiler the card names | `spooner`? |
|---|---|---|---|
| 0001–0006 | 1822–1829 | **Alden Spooner**, "at the office of the Long-Island Star" | ✅ correct |
| 0007–0009 | 1830–1832 | Lewis Nichols, then William Bigelow | ❌ Spooner is the **printer** |
| 0010 | 1833/34 | Nichols & Delaree | ❌ |
| **0011** | **1834/35** | **Alden Spooner & William Bigelow** | ✅ **correct again** |
| 0012–0014 | 1835–1838 | Lewis Nichols | ❌ Spooner prints it |
| 0015–0018 | 1838–1842 | Stevens & Marschalk · Ogden · the Leslies | ❌ |
| 0019–0025, 0027–0028 | 1843–1851 | the Hearne brothers, with Leslie, Van Nostrand, Webb | ❌ |
| 0022 | 1845/46 | Silas H. Crowell | ❌ |
| **0026** | **1848/49** | **E. B. Spooner**, compiled by Thomas P. Teale | ✅ **correct — a different Spooner** |

Three things follow, and the second is why this took a full read rather than a bulk edit:

1. **Alden Spooner published the 1820s volumes and printed the 1830s ones.** The catalog recorded
   the name that stayed on the page while its role changed underneath.
2. **The series cannot be corrected wholesale.** `spooner` is right on 8 of the 26 read, wrong on
   18, and `0011` is *both* — Spooner is a co-compiler there and the printer. A rule that rewrote
   every `spooner` row would have introduced six new errors to fix eighteen.
3. **`0026`'s Spooner is E. B., not Alden**, and its compiler is Teale — which the sibling
   identifier `brooklyncitydire1848teal` had been quietly recording all along.

Two frames (`0018`, `0022`) were so underexposed as to be unreadable as served; a percentile
stretch plus a gamma lift recovered both. `0018`'s film frame also crops the left edge, losing the
first word of every line — the publisher statement survives intact, and the sidecar says so.

### Trow numbers itself from the first New York directory, and an ad I vetoed says so

The same check on Trow's **general** (residential) directories, read 2026-09-22:

| vol | for the year ending | copyright | implies vol 1 in |
|---:|---|---:|---:|
| CXX (120) | July 1, **1907** | 1906 | 1788 |
| CXXI (121) | Aug 1, **1908** | 1907 | 1788 |
| CXXII (122) | Aug 1, **1909** | 1908 | 1788 |
| CXXIII (123) | Aug 1, **1910** | 1909 | 1788 |

Four for four. And the corpus holds five 1786 rows — `newyorkdirectory00fran`, *The New York
directory for 1786* — **the first New York city directory**, which is where a series numbering
back to ~1787/88 would start, allowing for the early gaps.

**Trow says so itself, in the advertisement the year gate throws away.**
`trowsgeneraldir1904p1trow` carries *"FIRST NEW YORK DIRECTORY Printed 1786"* — which
`YEAR_VETO` correctly suppresses as a year claim, because it is not this volume's date. It is
Trow asserting descent from the 1786 directory. **A bad year and a real fact in the same line**,
which is a good argument for the veto *skipping* a claim rather than deleting the text.

**A third series, and this one prints its own origin outright.** `newyorkcitydirec00rode` leaf 17:

> THE NEW-YORK CITY DIRECTORY, FOR 1854–1855. **Thirteenth Publication. ESTABLISHED IN 1842.**
> NEW-YORK: CHARLES R. RODE, 161 BROADWAY, **LATE DOGGETT & RODE.**

| | vol | for | implies vol 1 in |
|---|---:|---:|---:|
| Doggett | 4 | 1845 | 1842 |
| Doggett | 6 | 1847 | 1842 |
| Rode | 13 | 1854 | 1842 |

Three volumes, two publishers, one answer — **and the page states "ESTABLISHED IN 1842" rather than
leaving it to be inferred**, while "LATE DOGGETT & RODE" names the succession. So Doggett and Rode
are one series, exactly as Spooner→Nichols→Hearne→Upington is one and Trow is one. That also
settles a year conflict: the catalog's 1851 is wrong.

So: three independent series, each numbering itself continuously from its origin — Brooklyn from
Spooner's 1822, Manhattan from Franks' 1786, and Doggett/Rode from an 1842 the book prints itself.

### 🎯 Some volumes PRINT THEIR OWN ENTRY COUNT, which `entry_rate` has never had

Doggett's title pages state, in words, how many names the book contains:

| volume | printed on the title page | parses to |
|---|---|---:|
| `doggettsnewyorkc1845dogg` | "CONTAINS SIXTY-ONE THOUSAND THREE HUNDRED & THIRTY-THREE NAMES." | **61,333** |
| `doggettsnewyorkc1847dogg` | "CONTAINS SIXTY-EIGHT THOUSAND ONE HUNDRED AND FIFTY-NINE NAMES." | **68,159** |

**This is a ground-truth denominator, printed by the publisher, for a quantity the pipeline
currently can only estimate.** `entry_rate` measures the share of extracted lines that look like
entries; it has never had an independent answer to *how many entries the volume actually has*. A
stated count gives extraction **recall** on a real number.

Three things make it cheap and durable:

- **It is spelled out**, so it is immune to digit OCR error — the same reason the plan already
  prefers the spelled-out copyright year. `survey_frontmatter.words_to_number()` parses both
  exactly, today, with no new code.
- **The image is what makes it usable.** 1847's hOCR reads `SIXTY-EIGHT THOUSAND ONE HXTNDRED AND
  FIFTT-NUfE`; the printed page is perfectly legible. A clean case for what an agent read buys.
- **A regex over the Phase-1 JSONL finds the rest for free.** A scan of the cached front matter
  already turns up **10 volumes** whose front matter makes a claim about its name count — two
  absolute (above) and the rest comparative, which are useful differently:
  `1863BPL` "contains several thousand more names than any heretofore",
  `brooklyncitydire1848teal` "nearly Three thousand more names than that of last [year]",
  and `trowsgeneraldire1915trow` "The following 1832 pages contain names of individuals,
  copartnerships and corporations" — a printed **page** count for the listing section, which is a
  direct check on `detect_listing_bounds`.

Recorded as `stated_name_count` in the sidecar. Worth a dedicated harvest in Phase 2.

### ⚠️ `column_count` audit: 3 of 3 Trow NYC volumes checked were wrong

Reading the listings rather than the front matter turned up a different class of error. Each of
these volumes' `notes` records an offset anchor — *"col=3 (pilot s4); offset +14 @ leaf511/p497"* —
so the note names the exact leaf to open. Opening it:

| volume | anchor | offset | recorded | **counted** |
|---|---|---|---|---|
| `trowsnewyorkcity1859trow` | leaf 323 = p.317 | +6 ✓ | 3 | **2** |
| `trowsnewyorkcity1863trow` | leaf 338 = p.326 | +12 ✓ | 3 | **2** |
| `trowsnewyorkcity1876trow` | leaf 511 = p.497 | +14 ✓ | 3 | **2** |

**Every offset is right and every column count is wrong**, which suggests the two were not
measured on the same pass. It also refutes the 1859 note's claim that *"the 2→3 transition is
1857→1859"* — 1859 is still 2-column, and so is 1876.

**160 rows carry a `column_count` citing an `s4` read** (54 twos, 51 threes, 51 ones). `column_count`
feeds the style profiles and the page-type work, so a wrong value is not inert — and each row's own
note names the leaf, so the audit is cheap.

**But the bracket is only wrong at one end.** Checked since: `trowsgeneraldir1906p2trow` leaf 401
is genuinely **3 columns**, and `brooklyndirector00ogde` leaf 29 is genuinely **1**. So:

| checked | 1839 | 1859 | 1863 | 1876 | **1906** | 1922/23 |
|---|---|---|---|---|---|---|
| recorded | 1 | 3 | 3 | 3 | 3 | 3 |
| **counted** | **1 ✓** | **2 ✗** | **2 ✗** | **2 ✗** | **3 ✓** | **5 ✗** |

The `1859-1915 all 3-col` bracket is right at its high end and wrong at its low end, so **the 2→3
transition falls somewhere between 1876 and 1906** — not at 1857→1859 as the 1859 note claims.
Locating it properly needs the 1880s–90s Trow volumes, and it is worth locating: it is the single
fact that would let the bracket be re-dated rather than abandoned.

*(`trowsgenerald192223p2trow` also moved 3 → **5**, but that is a measurement rather than a
correction: its 3 came from a bracket covering 1859–1915, and 1922/23 sits outside it.)*

### Two listing conventions in Manhattan Trow, both new to the project's records

`trowsnewyorkcity1859trow` leaf 323 prints:

- **`Gaskin Joseph (col'd), barber, h 41 Watts`** — a race marker in **Manhattan**. The project has
  documented Brooklyn's (`*` in Hearne and Ogden, and Hope & Henderson's sense); this is a third
  form, *parenthesised after the name* rather than prefixed. Recorded as `race_marker`.
- **`Gatty (refused), 169 Monroe`** — a resident who declined to give particulars. The entry keeps
  the surname and address and drops everything else. Worth knowing before a filter decides a
  name-plus-address line with no occupation is a fragment.

**And the arithmetic found a hole — exactly one.** Attested Trow *general* volumes run:

| vol | 117 | 118 | 119 | 120 | 121 | 122 | 123 | 124 | 125 | **126** | 127 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| year ending | 1904 | 1905 | 1906 | 1907 | 1908 | 1909 | 1910 | 1911 | 1912 | **— none —** | 1914 |

Eleven consecutive volume numbers, one missing. **Volume 126, for the year ending August 1 1913,
is absent from the corpus.** The catalog *does* hold four 1913 Trow rows, and every one is the
**business** directory (VOL. LXVI) — so none of them is this. A specific, checkable acquisition
target, produced by arithmetic on printed volume numbers rather than by noticing an absence,
which is the hard direction.

**The cross-check that makes it trustworthy is distinguishing *missing* from *unread*.** Vol 118
was flagged the same way and is *not* a gap: `trowsgeneraldir1905p1/p2/p3` are in the corpus, and
Phase 0b had already pulled `vol=118` from all three out of the hOCR — even though their title
*text* came out as `^'i •M.i .■..•/„i<: TROW^'S^ GENERAL DIR`. A roman numeral survives OCR that
destroys everything around it, which makes `volume_number` unusually cheap to harvest at scale.

So the method is: arithmetic proposes the gap, the catalog decides whether it is a hole or a
to-do. It also needs the business/general split to be right first — mistake the 1913 business
volumes for general ones and the gap closes on paper while staying open in fact.

### And why the catalog said "Spooner" at all: it is ONE series, 1822 → 1912

`volume_number` is an independent handle on a volume's place in its series, and four series now
carry enough attested numbers to check. **Every one is internally consistent** — `year − volume`
is constant within each, so the numbering is a clean annual sequence:

| series | attested | `year − vol` |
|---|---|---|
| Hearnes | 10th 1851 · 11th 1852 · 12th 1853 · 13th 1854 | 1841, all four |
| Reynolds (Williamsburgh) | 2nd 1851 · 3rd 1852 · 4th 1853 · 5th 1854 | 1849, all four |
| Upington | LXXXII 1905 (both parts) | 1823 |
| Brooklyn Directory Co | LXXXVIII 1912 (all three parts) | 1824 |

And the last two connect to the first volume in the corpus:

```
vol  82 in 1905  -> vol 1 falls in 1824   (Upington)
vol  83 in 1906  -> vol 1 falls in 1824   (1906BPL)
vol  88 in 1912  -> vol 1 falls in 1825   (Brooklyn Directory Co)   <- off by one
```

**The 1912 title page explains its own discrepancy**: *"There was no edition of this book
published for the year 1911."* Skip a year and volume 88 slips from 1911 into 1912. The gap the
book documents about itself reconciles its numbering with volumes seven years earlier.

So the Brooklyn city directory is **one continuous series from the early 1820s to 1912**, passing
from Alden Spooner through Nichols, Ogden, the Leslies, the Hearnes, Lain and Upington to the
Brooklyn Directory Co. `micro_IABROOKLYN_0001` is *Spooner's Brooklyn Directory* for **1822**.

That is almost certainly why the catalog says `spooner` on volumes Spooner had nothing to do with:
**it is the series founder's name, applied to the series.** Not a typo, not a stray default — a
defensible cataloguing choice that stops being true about the *publisher* after 1829 while
remaining true about the *series*. Which is an argument for the `compiler`/`publisher`/`printer`
split the plan already wants, plus something to hold the series identity.

### How it first surfaced: ten rows, and the tenth explains the other nine

`micro_IABROOKLYN_0009` (1832–33) never appeared in the queue at all. Its card reads:

> Brooklyn Directory, for 1832-33. **Published by William Bigelow**, 55 Fulton-street.
> Brooklyn: **Printed by A. Spooner**, 57 Fulton-street. 1832.

**Spooner was the printer.** The extractor had `published|printed` in one alternation, so on this
card it read `A. Spooner`, matched the CSV, and registered a **confirmation** — the row was
silently counted as evidence *for* the wrong value. A whole series was catalogued from its printer,
and the same bug that caused it hid the proof.

Alden Spooner did publish Brooklyn directories in the 1820s (`micro_IABROOKLYN_0005` is *Spooner's
Brooklyn Directory* for 1826), which is presumably where the label came from before it was carried
down the series unrevisited.

**Every one of the nine survey reads was also wrong**, which is why each row got a corrected claim
and not just a verdict. Seven were **truncated** — at a comma (`Thomas Leslie`, dropping both
Hearnes), at a forename (`Henry R`), at 28 characters, and in the worst case at the opening
parenthesis of `H(enry) R. & W(illiam) J. Hearne`, yielding a publisher of **`H`**. Two cited a
listings page and read a *resident* whose trade was publishing: `Ballard Rev J, publisher N Y
Recorder` and `Betts Burrell, proprietor of steamboat Dream`. Both re-cite to a **printed title
page** (leaf 6 and leaf 7), which outranks a target card in the evidence hierarchy.

So the conflicts were real and the extracted names were never usable as answers — a distinction
worth keeping, because the other 10 publisher conflicts came from the same extractor.

### The extractor, fixed (2026-09-22)

Four causes, all measured against the cached front-matter text and re-run offline over all 184
volumes (`--redo`, 0 failures):

1. **`published` and `printed` were one alternation**, so a printer could win. Split, with
   `PRINTED_BY` consulted only as a last resort, and the printer now recorded in its own
   `book_says.printer` claim (7 volumes) instead of competing for the publisher's slot.
2. **A target card is a typed prose paragraph that wraps; the matcher read it line by line.**
   Cards are now reflowed before matching. Display type still is not — the newline guard that
   stops `GEORGE UPINGTON\nOFFICE\n317 Washington` is exactly right for a title page.
3. **Brackets and OCR crumbs ended names early.** `H(enry) R. & W(illiam) J. Hearne` yielded `H`.
4. **`_INIT`'s `[a-z]{0,3}` reads `Webb.` as an abbreviation**, so a name ran into the imprint
   after it. `trim_name()` cuts at a real sentence boundary — a full word plus a period plus a
   capital — which an initial never forms.

A comma is crossed **only when an `&` follows it**. Crossing every comma also swallowed addresses
(`LAIN & COMPANY, OFFICES 15 Court`, `William A. Mercein, No. 93 Gold-street`), and address words
are capitalised, so no charset rule separates them from a surname. Measured 9/10 against 8/10; the
one cost is that `Thomas Leslie, Henry R., & William J. Hearne` stops at `Thomas Leslie`. **A
truncated partner list is a far cheaper error than an address welded to a publisher's name.**

Net over the corpus: 93 publisher claims before, 93 after, **zero lost**, one changed — the
`0009` correction — plus 7 new printer claims.

⚠️ **And a re-read no longer destroys better evidence.** `doc["book_says"] = book` was a wholesale
replacement, so one `--redo` would have wiped every `ia-page-numbers` key_page and all nine
hand-confirmed publishers, silently — visible only later as the CSV drifting back. `merge_book()`
keeps any claim carrying `confirmed_by` or a method this module does not own. The sidecar is the
survey's record; phase 0b is one contributor to it, not its owner.

**A `csv_label` on the claim** keeps the two sides honest: `value` is what the page says
("Thomas Leslie, Henry R., & William J. Hearne"), and the CSV takes the short family label the
column's own convention already uses (`Trow/Wilson` on 27 rows, `Hearnes` on 7). Truncating the
attestation is what caused this; fragmenting the grouping key would break the publisher × era
families the style profiles rest on.

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

### Phase 1 — OCR harvest (the only heavy step) — DONE 2026-09-22

Serial, one volume at a time, backoff, resume. Fetch pageindex + `_hocr.html` once →
`data/<ident>_lines.jsonl.gz` + `_dropped.txt` → **delete the hOCR**. Peak disk stays at one
volume.

**Built 2026-09-22 as `survey_harvest.py`, with one change to that design: the kept asset is a
word dump, not the filtered lines.** Output goes to `data/survey_ocr/` (never `data/<id>_lines.jsonl`,
which holds pinned artifacts — `docs/BANNER_CORRECTION.md`):

| file | what | why |
|---|---|---|
| `<id>_words.jsonl.gz` | one record per pageindex leaf: every word, box, `x_wconf`, grouped by `ocr_line`; empty leaves included | **the asset**. Lossless for everything the repo reads from hOCR, at ~7.6% of its bytes (1857BPL: 60.5 MB → 4.6 MB) |
| `<id>_lines.jsonl.gz` | `ia_volume_to_jsonl.sweep()` over the dump, default settings | what `qwen_predict.py` reads |
| `<id>_dropped.txt.gz` | every rejected line with its reason | read it before trusting the kept file |

The filters are not finished (the banner fix moved 1906BPL by 6,091 lines) and the `[publisher=]`
tag comes from a column the survey is still correcting, so filtered lines alone would force a
21.7 GB re-download the next time either moved. `--rederive` re-filters every volume offline.

**Equivalence is measured, not argued.** `sweep()` now reads pages through `page_lines(leaf)`,
which `Item` (hOCR) and `WordDump` (the dump) both implement. On 1856BPL the dump path and the
direct hOCR path produce **byte-identical** `_lines` and `_dropped` (61,439 kept), and
`micro_IABROOKLYN_0013` reproduces the documented 2,899.

**Eval holdout is marked, not cut.** Phase 2 needs whole volumes, so gold leaves stay in and carry
`eval_holdout` (`gold` / `adjacent` / `volume`) in both the dump record and every emitted line's
`context`. The gold leaf is **located by text**, not taken from the jp2 filename: gold lines are
matched against leaves ±3 around it and the best match wins, with the jp2 number, the chosen leaf
and the match score recorded in the sidecar. A weak match tags the jp2 leaf too. Both neighbours
are `adjacent`. `1897BPL` (`BANNED_IA_ITEMS`) is tagged `volume` on every leaf. 16 of the 184
volumes carry gold. The leaf-keyed sets (`micro13_*`, `1906BPL_sample500`) are included, although
`verify_harvest_leakage.gold_pages()` does not see them because they carry no `image`.

Each sidecar gets a `harvest` block: status (`ok` · `no-hocr` · `fetch-failed` · `derive-failed`),
hOCR sha1 as downloaded **against the 2026-09-12 census sha1**, so an IA re-OCR is detectable,
word/line/char counts, mean `x_wconf`, chars per content leaf, filter outcome, and the git
revision the filters ran at. `--report` adds `dead-ocr`: chars per content leaf below 10% of the
volume's OCR-engine-class median.

### Phase 1 results (run 2026-09-22) — DONE, 184/184 `ok`

| | |
|---|---:|
| volumes | **184 ok** · 0 no-hocr · 0 fetch-failed · 0 dead-ocr |
| words dumped | **132,634,451** |
| candidate lines kept | **18,942,321** (median keep rate 82.8%) |
| dump size | **1.53 GB** from 21.66 GB of hOCR (7.1%); `data/survey_ocr/` 2.0 GB in all |
| hOCR re-derived by IA since the census | **0** — all 180 downloads match the 2026-09-12 sha1 |
| wall clock | ~5 h of per-volume time |

**The download redirector, not IA as a whole, was what failed.** `archive.org/download` sends each
request to a storage node, and for some items it kept choosing one that returned 500 for many
minutes, while that item's own `workable_servers` served it. `micro_IABROOKLYN_0003` failed 4/4 over
~8 minutes that way while a direct request to its replica succeeded. `download()` now tries every
replica before backing off; 9 fetches in the run needed it. A plain retry, which was enough for
the 4-of-184 Range failures in Phase 0, is not enough for a whole-file fetch.

**Eval holdout: 16 volumes, 15 verified at jp2 → leaf offset 0.** The jp2 number *is* the hOCR
leaf on every volume where the text could check it. The exception proves why the check exists
rather than refuting the arithmetic: `micro_IABROOKLYN_0035` (hopehenderson1856) jp2 205 matched
no leaf, because **leaf 205 is a dead film frame** — 167 chars of noise (`“HAT AD TERETE Ade an`)
sitting alphabetically exactly where the gold belongs, between Guthrie (leaf 204) and Haley (leaf 206).
The gold was transcribed from the image, so no OCR could match it. The weak-match rule tagged
jp2 205 *and* the best guess (207). 205 is correct. 207 is a harmless false positive.

**`x_wconf` is not comparable across engines.** Median of per-volume mean word confidence:
tesseract **82.3**, ABBYY-9 31.6, `none` 27.5, ABBYY-11 21.5, ABBYY-8 **12.6** — the ABBYY-8 tier
is the *clean* one. Use it within an engine class only; see the engine-confound note in the
memory index. `dead-ocr` uses chars per content leaf per class for the same reason.

**Keep-rate outliers are Phase-2 leads, not failures.** Lowest: `newyorkdirectory00durs_0` 29.7%,
`newyorkbrooklynd00durs` 29.9% (the Durst 1786 reprint/original pair), `brooklynnewyorkc19123broo`
37.8%, `micro_IABROOKLYN_0041` 40.1% (the 1860 *business* directory, `not-residential`).

**Correction to the failure register:** `longworthsameric4818long` is `restricted` for **images**
(IIIF 403) but its hOCR is **not empty** — 378 content leaves, 133,519 words, mean conf 27.4.
The text route exists.

**Budget: 21.7 GB total, median volume 79 MB.** Four volumes exceed 500 MB and get their own
night: `trowsgeneraldire1917trow` **1588 MB** (2480 leaves), `trowsgeneraldire1915trow` 1470 MB,
`trowsgenerald192223p2trow` 643 MB, `trowsgenerald192223p1trow` 566 MB. For scale, 1906BPL's
305 MB hOCR yields an 81 MB `_lines.jsonl`.

### Phase 2 — free derivation (no agents, no network)

#### Progress 2026-09-22: listing bounds and printed pages, all 184 IA volumes

`survey_derive.py` is the driver. It reads only the Phase 1 dumps (plus the small
`_page_numbers.json` cache), writes sidecar blocks, and never touches the CSV.

**`bounds` → `listing`.** `detect_listing_bounds` modelled a volume as one A→Z run, and on this
corpus that produced a listing ending *before* it started on 17 of 184 volumes. It now segments
the letter votes into ascending **alphabets**. The largest alphabet is the listing and every one is
recorded as a section. Each rule answers a case found in the corpus:

| rule | case |
|---|---|
| a restart costs 8 leaves | a PART covers a stretch of the alphabet (Trow p1 = A→H); stray single leaves are skipped |
| small isolated edge clusters are trimmed | 1856BPL leaves 12, 29: front-matter ads voting A |
| a leaf votes only with ≥25% of the median voting lines | 1867BPL leaves 2–4: ads voting A on 14–28 lines |
| …but an alphabet's end reaches a short page right after it | 1862BPL leaf 508 "Zyla Bobert" is the real last page |
| ties go against a restart | `brooklynnewyorkc1904geor`: 8 one-leaf ad votes split one alphabet |
| a split alphabet is rejoined across an interlude | `brooklyncitydire1848teal`'s **Mc section**: `M'Cage` → `Cage`, voting C…L between M and N |

Read from the dump, the result is **identical to reading the hOCR** (1906BPL, 1856BPL, micro_0013).
The filtered-lines path is kept as a cross-check: it agrees within 2 leaves on 167/184, and on
every disagreement opened by eye the dump was closer (1897BPL: lines stopped at leaf 1002 in M).
Flags: 90 clean · `partial-alphabet` 69 · `multi-section` 35 · `edge-disagreement` 17 · `sparse` 9
(the dash-ditto ABBYY-8 Trow/Brooklyn volumes) · `small-listing` 5.

What the bounds found:

- **The letter ranges identify parts, and the parts tile.** Trow 1903–1914 run A–H / H–R / R–Z
  (1906, 1910: A–G / G–P / P–Z; 1908 in four). **The Brooklyn `…c19NNgeor` volumes are
  catalogued as whole directories and are halves**: 1905 = `1905p1geor` A–K + `c1905geor` K–Z,
  and likewise 1903–1910. `brooklynnewyorkc00broo`, with no year in its id, is part 1 of 1912.
- **Duplicates show as identical ranges** — Trow 1903 p2 / `19032trow`, 1907 p3 / `19073trow`,
  1914 p2 / `19142trow`; Brooklyn 1903 `1903p1geor` / `c19031geor`, 1906 `c00geor` / `c19062geor`.
- **Second alphabets are real structure.** Brooklyn 1855–57 carry two full alphabets. 1856BPL heads
  its first "WESTERN DISTRICT", so the second is presumably the Eastern. Every Trow p3
  1903–1912 ends in a **street directory** ("BOROUGH OF MANHATTAN … from 209 Bleecker … Left.
  Rt."). 1879BPL, 1911p1 and 1914p1 open with "NAMES TOO LATE FOR INSERTION".
- ⚠️ **`trowsgeneraldire1853trow` is not a Trow general directory.** Its title page, read in
  Phase 0, is **WILSON'S BUSINESS DIRECTORY … NEW-YORK**, the same catalog error as the 1913 set.
  Its "listing" was 27 leaves of 948: five short B→W runs, the shape of names sorted under trade headings. **Stamped `not-residential` 2026-09-23, confirmed by hadro**, making 8 `not-residential` volumes.

**The empty-leaf question is answered: scanner artefacts, not lost text.** 68 volumes put an empty
leaf between every page (the whole ABBYY-8 Trow/Brooklyn family, Longworth, Flushing) — the "~2×
`imagecount`" item. Consecutive *text* leaves print consecutive folios (`trowsgeneraldir1904p1trow`
411, 413, 417 → 151, `151!`, `1B4`), so nothing is missing, and pages must be counted over text
leaves.

**`pages` → `folios` + `book_says.start_page` / `end_page`.** `survey_folios.py` is the tier-C/D
reader this plan promised. It takes margin numbers, a piecewise-constant fit over text leaves, and
`read` / `inferred` per leaf. It never extrapolates past its first or last read.

| calibration against IA's READ numbers (conf ≥ 90), 85 volumes | |
|---|---:|
| leaves where the leaf's own margin shows the fitted number | **99.5%** agree |
| leaves filled between reads (`inferred`) | 98.0% agree |

⚠️ **The calibration found IA wrong, at confidence 100, on a tier-A volume.** 1904BPL sets
`pageNumber = leafNum` on 381 leaves whose own margins print otherwise (leaf 10 prints 22, leaf
612 prints 604), while IA's own `ocr_value` shows the tokens it actually saw — `['1904', '317',
'3004']`, a year, a street number, a phone number. Tier A was never a guarantee. Also, IA derives
its numbers from **this same OCR**, so "two independent detectors" overstated it: two readers of
one text.

**The OCR drops or mangles a folio's leading digit**, and a few truncated folios in a row fit a
sequence of their own: `brooklynnewyorkc1912broo` reads 120…153 where its main run continues to 1153,
and `trowsgeneraldir1911p1trow` "ends" on `003` (603). The first run graded those `high`. A claim now
drops to `low` on a **sequence break** or an **end page below the listing's own text-leaf count**,
and `high` needs a sequence read on ≥ 10 leaves.

**Cross-volume check, not tuned for:** the Brooklyn parts join exactly — 1904 p1 ends p.558 and
part 2 starts p.559; 1909 582→583; 1912 625→626 and 1153→1154 (1154 + 367 text pages = the p3
claim of 1521, exactly). The single-volume BPL scans end on the **same page** as the two-part
`geor` sets (1903 p.1054, 1907 p.1089, 1908 p.1107), so they are the same edition. Where both
claims exist, `end − start + 1` matches the listing's text leaves to 0.97–1.00.

| claims | high | medium | low | none |
|---|---:|---:|---:|---:|
| `start_page` | 27 | 11 | 37 | 109 |
| `end_page` | 56 | 9 | 23 | 96 |

84 volumes carry at least one CSV-grade (high/medium) claim, which would fill **37 `start_page`
and 65 `end_page` cells, all empty today**. One conflict: `merceinscitydire00merc` CSV 105 vs
**106**. Leaf 104 prints "106 / MERCEIN'S / Acbeson Hugh, cartman", and the page before is an ad,
so the CSV is one page early. The row's own note had already recorded "first clean directory page
printed p106 = canvas c101", and c101 is leaf 104 in a numbering 3 off from IA's leaves, which also
explains its `page_offset` of −5.

**Written 2026-09-23, on hadro's decision.** `apply_survey.py` makes the three columns
*conditional*: `method: hocr-geometry`, `attestation: read`, `confidence: high` (stricter than
`key_page`'s high-or-medium), and `page_offset` only from the same claim as its `start_page`.
Before that change, **10 randomly sampled high claims (seed 20260923) were opened at their IIIF
images: 10/10 print the cited folio, and 10/10 are the listing's true first or last page**. Two of
the neighbouring title pages carry a librarian's "Pt. 2", confirming the part assignment.

| written | cells |
|---|---:|
| `end_page` | 56 |
| `start_page` | 26 + merc 105 → 106 (`book-wins`) |
| `page_offset` | 23 + merc −5 → −2 (`book-wins`) |

107 cells in 70 rows, no other column touched, and a second run writes nothing. Every
survey-written row satisfies `start_page + page_offset == cited leaf`, except `micro_IABROOKLYN_0028`
and `_0033`, whose pre-existing offsets were measured deeper in the volume (+8 at leaf 146, +55 at
leaf 186) and were left alone by rule 1. Those two plus merc were the three new `page_offset`
conflicts; merc is decided, and the other two are drift, not error.

#### Phase 3 page reads (2026-09-23): every listing edge without a high claim, read off the image

235 listing edges (every non-`not-residential` volume whose start or end lacked a high claim) were
read from IIIF head and foot strips, plus the neighbouring leaf of each of the 80 edges already
written to the CSV. Recorded by `survey_readpackets.py --record-pages` as `method: agent-read`
claims with the verbatim folio, and the margin fit's earlier answer kept in `margin_fit_said`.
`survey_derive.py pages` no longer overwrites a read.

⚠️ **8 of the 80 page cells written on 2026-09-23 were wrong, and the 10-sample spot-check had
passed 10/10.** At a 10% error rate, ten clean draws happen 35% of the time. That is a sample
too small for the claim it was used to support. The errors share one cause:

| volume | written | page says | why |
|---|---|---|---|
| 1908BPL | start 22 | **21** | the caption page (leaf 9) was missed |
| trowsgeneraldir1911p1trow | start 18 | **17** | the caption page (leaf 55) was missed |
| trowsgenerald192223p1trow | start 253 | **252** | leaf 186 opens the listing, 185 is the title page |
| micro_IABROOKLYN_0025 / 0033 | start 14 / 21 | *unprinted* | the caption page (leaf 21 / 64) prints no folio |
| micro_IABROOKLYN_0028 | start 37 | *unprinted* | the bounds opened in **B**; the whole A section was missed on bad film |
| brooklynnewyorkc19031geor | end 553 | **554** | the listing runs one leaf past the fit's last read |
| flushingnewyork189192boyd | end 123 | **124** | ditto; p.125 opens the Business Directory |

**A caption page votes on too few entry lines to open its listing**, so the detected start is
one page late wherever the listing begins under a display title. That is a detector bug, not a
reader bug, and worth fixing at the source: extend a listing's start back to the caption page.

**The number at the foot of a caption page is usually a printer's SIGNATURE, not a folio**, and
the image cannot tell them apart. The page sequence can. 31 of 39 small foot numbers on opening
pages fail to continue into the following leaves: 1859trow's caption page shows "1" with the next
leaves printing 22, 23, 24 (p.21), and 1856/1857BPL's "3" sits on p.33, the start of the third
16-page gathering. Rule: a foot number under 60 counts as a folio only if the next text leaves
continue it (twice for values under 10, since stray 2s and 3s are everywhere). Otherwise it is
recorded `unprinted`, with the sequence's page in the note.

Retraction is now **ledgered**. A cell whose claim a read has overruled is cleared only if
`data_prep/survey_written.json` records this survey writing that exact value. Equality with the old
claim is not proof of authorship: without the ledger the first dry run would have cleared four
human values (micro_IABROOKLYN_0005 start 5, rode 25, doggett1845 13, hearnes1852 offset 10) that
merely equalled what the fit had said, and all four are consistent with the page sequence.

Found in passing:
- **Pages that fall between parts:** Trow 1904 p.1105 and 1910 pp.566–567 are in neither part's
  scan. *(This line first also listed Brooklyn 1912 p.1154 and Trow 1922/23 pp.1025–1026. They are
  there after all: p3's leaf 9 prints 1154 and 1922/23 p2's leaf 7 prints 1025. The strip read had
  taken the second listing page for the first. See "Edge extension" below.)*
- **Two-page spreads on one frame** in the microfilm set (0012, 0015, 0019, 0021, 0033, 0034,
  0040). The leaf holds two folios, and `end_page` is the right-hand one.
- **Roman-numbered appendices** close two listings (micro_IABROOKLYN_0025 `LVI`, 0027 `IX`), so
  no arabic end page is printed.
- **1898 and 1902 Lain/Upington running heads print the year beside the folio**
  (`1016 ZWE-ZWI 1902 ZWI-ZYS`). The centre number is the year, the corner one the page.
- `trowsgenerald192223p1trow`'s title page says **"Complete in One Volume — Vol. 133"**, although
  IA splits it into two items.
- `trowsgeneraldire1915trow` and `1917trow` leaves are **photographs of the open book**, not page
  scans, and are unreadable at any IIIF size.
- `longworthsameric4818long` is **truncated**: the 1823–24 almanac, then p.55. Pages 1–54 of the
  directory are not in the item.
- `micro_IABROOKLYN_0028` is Hearnes' 1850–51, the same edition as `hearnesbrooklync1850unse`.

**Written 2026-09-23 (hadro's decision):** 137 cells, comprising 127 fills (77 `end_page`, 25 `start_page`,
25 `page_offset`), the 6 corrections above, and 4 retractions where the true first page prints no
folio. The ledger holds 230 survey-written page cells.

#### Edge extension (2026-09-23): the caption-page miss fixed at the source

`detect_listing_bounds.extend_edges()` pulls each listing edge outward across pages that still read
as listing: ≥5 lines keyed on the edge letter at ≥25% share, within 3 leaves. At a start it also
takes a **caption page** ("DIRECTORY" in its first 12 lines) at ≥9% share, and stops there. The key
admits what the sort-key vote refuses and an opening page is full of: `A A Automatic Mfg Co`, `A&B`,
initials. `listing.voted_bounds` keeps the vote's answer alongside.

57 extension steps across the corpus were opened at their full-page IIIF images: **54 right, 3
wrong, and the 3 were all a title-and-abbreviations page** (1922/23 p1 leaf 185, 1917 leaves 210–211,
at 0.049–0.083 share) taken for a caption page. The weakest genuine caption page (1905p1 leaf 117) is
at 0.100, so the floor is 0.09, a narrow margin. Against the 292 image-checked edges, exact starts
went **126 → 136 / 142**.

⚠️ **The ground truth was wrong more often than the extension.** Of the 14 edges where they
disagreed, 9 were my own strip reads calling an edge "confirmed" without seeing the next page:
1856BPL ends on p.338, not 337 (the Z section is on p.338); 3818long on 346, not 345; Trow 1910 p1
on 565, not 564; the 1912 p3, 1922/23 p2, 1907 p2 and 1910 p2 starts are each a page earlier. **A
strip of one leaf cannot confirm an edge; only the neighbour can.** The corrected reads cite the
full-page image. The remaining misses are real detector limits: `1903p1geor` and `c19031geor` end one
page short on thin OCR, `micro_0028` misses its A section, and `micro_0033` starts two pages late.

Retraction is now one rule: **a ledgered cell whose current claim no longer supports it is
cleared**, and refilled on the same run if the current claim is CSV-grade. That also covers an edge
that moved (micro_IABROOKLYN_0004 had 47 from leaf 41, but the listing runs on to leaf 42, whose folio
is illegible, so the cell is cleared). `survey_derive.py pages` sets aside a read that said "not the
edge" once the edge has moved.

Why so many `none` on `start_page`: a listing's opening page often prints no folio (caption title,
legend). For 39 volumes the first read is 1–3 leaves after the start, and the rule above forbids
extrapolating it — **one image each settles them**, which is exactly the Phase-3 shape. 20
volumes fit no folios at all (ABBYY-8 drops most of them).

Leads, unbuilt: **guide words** — listing running heads print their alphabetic range ("ALE—ALL",
"BEE—BEG"), a second listing detector independent of the sort-key vote; a **leading-digit
repair** for folios, which would lift the ABBYY-8 tier; and a heading-based section inventory to
name the sections the alphabets found. Three volumes ship no `_page_numbers.json` at all
(`longworthsameric1798newy`, `micro_IABROOKLYN_0015`, `trowsgeneraldir1909p3trow`), against the
census's "every IA item".

#### The original design

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

### Phase 3 — DONE for the IA tier (2026-09-22): 75 volumes read, queue empty

`survey_readpackets.py` hands out the leaves Phase 0b chose and writes the answers back as cited
claims — leaf, canvas, IIIF image, verbatim quote, `method: agent-read`. **358 agent-read claims
across 75 volumes**, and `needs-image-read` went 81 → 0 unread.

| | before | after |
|---|---:|---:|
| `publisher` filled (ia rows) | 179 | **185** |
| `volume_number` | 61 | **76** |
| `year_covered` | 42 | **93** |
| `year_published` | 21 | **49** |
| year conflicts | 13 | **1** |
| `not-residential` identified | 0 | **7** |

It also produced claim types the schema did not have: `printer` (23), `stated_name_count` (4),
`series_gap` (4), `race_marker` (2), `reprint_year`, `series_established`, `twin_of`,
`ditto_convention`, `refusal_marker`.

**What a read bought that text could not.** Every one of these came off an image and none of them
could have come from the hOCR: the Spooner series' true publishers; the `TROW BUSINESS DIRECTORY`
title pages that reclassified four rows; Doggett's printed entry counts, one of which the OCR
renders `SIXTY-EIGHT THOUSAND ONE HXTNDRED AND FIFTT-NUfE`; the roman-numeral `M, DCC, LXXX, VI`
that no digit regex can see; and three column counts that were simply wrong.

⚠️ **A 403 is not self-explaining.** `longworthsameric4818long` was stamped `restricted` and the
stamp was retracted the same day: the failures were my own request asking IIIF to scale a page
*to* 1400px when the scan was narrower, answered `Requests for scales in excess of 100% are not
allowed`. `page_image()` now emits `full/!1400,1400` — best fit within, never upscale — and 791
citations were migrated to it. Reading the response body would have said so immediately.

### Phase 3 — the original design (cheap tier, gated)

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

**Stamped so far (2026-09-22):**

- `restricted` — `longworthsameric4818long`. IIIF returns **403 on every leaf**, so it has no
  image route. *(It was also recorded here as having an empty hOCR; Phase 1 found 133,519 words
  on 378 content leaves, so the text route exists.)* Not a collection-level block: other
  `durstoldyorklibrary` volumes serve fine, so this is item-level.
- `not-residential` — 6 volumes. `micro_IABROOKLYN_0041` (Boyd's Brooklyn **Business** Directory,
  1860), `micro_IABROOKLYN_0038` (Brooklyn **Business** Directory, 1858-59), and **all four 1913
  Trow rows** — see below.

**⚠️ The whole 1913 Trow set is the BUSINESS directory, and nothing in the catalog says so.**
`trowsgeneraldir1913p1trow` / `p2` / `p3` and `trowsgeneraldire19131trow` are all catalogued as
*"Trow's general directory of the boroughs of Manhattan and Bronx"*, and their identifiers say
`generaldir`. Their printed title pages say:

> TROW **BUSINESS** DIRECTORY OF THE BOROUGHS OF MANHATTAN AND THE BRONX … ARRANGED UNDER
> BUSINESS CLASSIFICATIONS AND FULLY INDEXED … 1913, VOLUME LXVI

p2 and p3 carry a librarian's red *"pt. 2"* / *"pt. 3"* beside the year, so the three are parts of
one business directory. p1's title page is a blank verso — it was read from the **show-through**,
mirrored and contrast-lifted.

**Do not generalise this to the 1904 set.** `trowsgeneraldir1904p3trow` leaf 9 is a three-column
**residential** listings page (printed p.1106: *"Ryan Thos police h 513 E 87th"*). Same publisher,
same identifier pattern, same "part N" shape, opposite answer — the parts have to be read, not
inferred from a sibling.

`trowsgeneraldire19131trow` is also a **probable duplicate** of `p2`: identical `imagecount` (834)
against a different scandate (2010 vs 2013), the same manuscript accession number **63209** on its
copyright page as p1, and the same title-page show-through. Not stamped `duplicate-of` — that
evidence is suggestive, not conclusive, and a leaf-level comparison would settle it.

**A free key-page signal, found in passing.** That 1904 listings page prints
*"(For list of abbreviations see page 17.)"* — **the listings name their own key page.** Harvesting
that pattern corpus-wide needs no image read at all, only a regex over the Phase-1 JSONL, and it
yields a *printed page number* directly, which is exactly the unit `key_page` wants and the unit
`_page_numbers.json` so often cannot supply.

⚠️ **"Business" in a title does not mean out of scope, and a keyword sweep would get this wrong.**
12 rows match `business|mercantile|copartnership|trade`, and **10 of them are combined volumes** —
`Brooklyn City AND Business Directory` (1869, 1871, 1875, 1876, 1880) and Reynolds'
`City Directory AND Business Advertiser` (0044-0048). Those carry a residential alphabet and stay
in. Only the two named above are business-only. The discriminator is *and*, which is exactly the
kind of thing that survives a human read and not a regex.

Related: **duplicate and multi-part detection.** `master_directories.README.md` already flags
p1/p2/p3 parts and duplicate scans across IA collections. Cluster on
(publisher, year, city, imagecount, title) and stamp `duplicate_of` / `part N of M`, or everything
downstream double-counts.

## Also worth recording while the sweep is running

- **rights status** per volume — a public HF release is the goal and there are 1933 rows in the
  non-phonebook set
- ⚠️ **racist content in the advertising, which a public release needs a stated position on.**
  Found while reading `micro_IABROOKLYN_0041` leaf 2 (1860): a full-page D. Appleton & Co.
  advertisement for stereoscopic views whose product list includes a category of "illustrations of
  negro life" by a blackface minstrel troupe, one title of which contains a racial slur. This is
  not incidental to one page — minstrel and blackface material was mainstream commercial
  advertising in this era, so the ad sections across the 1850s-1880s volumes will carry more of it.

  The project already has the *apparatus* for this: `docs/` and the style profiles record the
  Hearne/Ogden `*` race marker as a deliberately **preserved** datum, on the grounds that
  stripping it "destroys irrecoverably" the only racial identification those volumes carry. That
  reasoning was about the **listings**, where the marker is evidence about Brooklyn's free Black
  community. The **advertising** is a different case with the same material: not a record of
  people, and not something the extraction pipeline needs at all.

  Nothing to decide here — but the release should say which it is doing and why, and the ad-run
  inventory Phase 2 already plans to build (`ad-run inventory — the reported gaps`) is the natural
  place to carry the flag, since it identifies the ad leaves anyway.
- **provenance of the OCR itself** — IA `sha1` and `mtime` of the hOCR derivative plus fetch date,
  so a re-derivation is reproducible and a later IA re-OCR is detectable
- **a coverage report** — publisher × decade × borough. Thin in the 1860s–90s (21/16/18/14
  volumes) against 57 in the 1900s; Trow 1898/99 is a known hole.
- **OCR tier** from engine + chars/page, using the measured triage rule (an order of magnitude
  below its class), not "did it produce output". Corpus engines: ABBYY-8 **71**,
  tesseract-microfilm 49, ABBYY-9 39, none 21, ABBYY-11 4 — independently reproducing the
  71-volume ABBYY-8 bucket measured in `historical-ocr-eval`.
