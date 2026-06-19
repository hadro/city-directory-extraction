# Doggett — New-York City Directory, 1840s

**Representative volume:** `ia/doggettsnewyorkc1845dogg` — *Doggett's New-York City Directory,
for 1845 & 1846* (John Doggett Jr., 156 Broadway; "Fourth Publication; contains 61,333 names").
Visually sampled 2026-06-19.

## Structure (canvas indices, 0-based)
- Canvases 0–3: Full-page ad leaves (before title; unnumbered).
- Canvas 4: Title page (unnumbered).
- Canvas 5: Copyright + caution page. Key note: *"Each and every copy of this work is STOLEN,
  which has not, on page 13, a circular stamp"* — implies persons listing starts at printed p. 13
  (after almanac p.6, refused-names p.10, and late-additions p.12).
- Canvas 6–7: Preface "TO THE PUBLIC" (roman pp. iii–iv; date: "Directory Establishment,
  156 Broadway, June 30th, 1845").
- Canvas 8: **TABLE OF CONTENTS** (section page references):
  - Almanac: 6 · Appraisers: 413 · Banks: 414 · Churches: 421 · Consuls Foreign: 412 ·
    General Information: 413 · Name or Names refused for this work: **10** ·
    Names too late for insertion: **12** · Nurses: 408 · Police: 409 · Post Office: 411 ·
    Rail Road Companies: 429 · Advertisements: 435
  - *Persons listing is not separately titled in the TOC — it is the main body of the work.*
- Canvases 9–10: Almanac pages (July 1845–June 1846).
- Canvas 11: Ad leaf (C.B. Hatch, 97 William St).
- **No explicit abbreviations key page found** in the sampled 12 front-matter canvases. Older
  style: conventions are sparse and embedded in entries rather than collected in a legend.
  Would need a resample at `--front 15` starting around canvas 12 to confirm whether a key
  page exists between the almanac/TOC and the listing start.
- `column_count` = **2** (counted visually from listing pages; no preface statement found).
- `page_offset` (canvas_index − printed_page): **+10** at canvas 145 / printed p.135;
  **+16** at canvas 337 / printed p.321. Interpolated estimate near listing start (p.~13): **~+6**
  (unmeasured directly). Drift is due to interspersed unnumbered ad leaves throughout the volume.

## Entry format
`Surname Firstname, occupation[, WorkplaceAddr], [h HomeAddr]`

Notable/prominent persons in ALL CAPS:
`FOX BALDWIN N. grocer, 32 Water, h. 147 ch'ry`

Some entries include only a workplace with no home address; some include only a home address.
Widow/survivor format: `Fox Ann, widow of Jeremy, 17 pl` (spelled out "widow of" — no abbreviation
in this volume; the wid. abbreviation was not confirmed in the front matter).

Verbatim samples (canvas 0145, FOW–FRA, printed p.135):
- `Fountain H. K. forwarding mer, 5 South`
- `Fountain John, mason, 3/3 Third`
- `Fowler Moses C. lastmaker, 47 Sheriff`
- `Fowler N. Hill, drygoods, 167 Pearl, h 46 Fourth`
- `Fowler Thomas B. hatter, 132 Bowery, h 277 Broome`
- `FOWLE JOHNSON & CO. com. mers. 84 Pearl`
- `FOX HALE Elias, 280 Broadway, h 87 Twelfth`
- `Fox Ann, widow of Jeremy, 17 pl`
- `Fox Martha, widow of Seth, 86 Vandam`
- `Fox Charles, (co'd) seamn, 139 W. Fifteenth`   *(co'd = colored — race designation)*

Samples (canvas 0337, SCH, printed p.321):
- `Schofield Joshua & Sons, hardware, 211 Pearl`
- `Schonmaker Daniel, auction, 168 Pearl`
- `SCHRODER HENRY, engraver`
- `Schroder Frederick H. lithographer, 123 Fulton, h 149 Suffolk`
- `Schultz Anna C. widow of John, 77 Delaney`
- `SCHWARTZ George, confectioner, 174 Third`

## Abbreviations
No explicit legend in front matter; conventions inferred from entries:
`h` / `h.` house (home address) · `co'd` colored · `mer` merchant · `com.` commission ·
`cor` corner · `av` avenue · `n` near · `pl` place · `st` street · `r` rear

Occupations and descriptors generally spelled out (less compressed than later Lain/Trow style).

## Cohort 1842–1855 (sampled 2026-06-19)
Doggett published the NYC directory from 1842 (taking over from Longworth). The cohort is 12 rows
(4 IA `doggettsnewyorkc18xx`, 8 NYPL `…-00505686a51c` + later UUIDs), 1842/43–1854/55. Four
representatives sampled across the range (`--front 20 -k 2`):

| Year | ID (head) | column_count | page_offset |
|---|---|---|---|
| 1842/43 | nypl `8ca2a950` | 2 | **+5 constant** (c117=p.112, c275=p.270) |
| 1845 | ia `…1845dogg` (this card) | 2 | +10→+16 drift |
| 1846/47 | nypl `88fe6240` | 2 | **+17→+29 drift** (c159=p.142, c373=p.344) |
| 1847 | ia `…1847dogg` | 2 | **+6→+8 ~const** (jp2 158=p.152, 368=p.360) |
| 1854/55 | nypl `a4b1de40` | 2 | **+3→−3 drift** (c294=p.291, c686=p.689) |

- **`column_count` = 2 across the entire 1842–1855 run** — Doggett was already two-column in its
  first (1842/43) volume, unlike the Longworth single-column directories it replaced (Doggett was the
  denser "61,333 names" product). `column_count=2` backfilled for all 11 uncarded Doggett rows.
- **`page_offset` is per-volume and mostly drifts** (interspersed unnumbered ad leaves): values span
  +3 to +17 near listing start and drift up to +29 or down past 0 by volume end. NYPL 1842/43 is the
  only sampled volume with a constant offset. Only the 4 sampled volumes have `page_offset` recorded;
  the remaining 7 (1843/44, 1844/45, 1845/46, 1848/49, 1851, 1854/55 IA n/a, + IA 1846/1848) need
  per-volume sampling to measure it.
- Entry format and ALL-CAPS prominent-name convention are stable across the run (1842/43 listing
  matches the 1845 samples below: `Surname Firstname, occupation, address`; widow = `widow of X`).

## Genre
Residential persons directory — Manhattan (KEEP shape). Publisher: John Doggett Jr.
