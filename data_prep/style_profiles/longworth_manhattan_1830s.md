# Longworth — New-York City Directory, 1830s

**Representative volume:** `ia/longworthsameric1839newy` — *Longworth's American Almanac,
New-York Register and City Directory, 1839* (David Longworth, publisher).
Visually sampled 2026-06-19.

## Structure (canvas indices, 0-based)
- Canvases 0–6: Library and binding material added by the digitizing institution (Allen County
  Public Library): canvas 0 = red cloth cover, canvas 1 = catalog card, canvas 2 = ACPL barcode,
  canvases 3–5 = blank endpapers, canvas 6 = handwritten ownership flyleaf ("C.A. Holstein /
  33 William St."). None are printed pages.
- Canvases 7–9: Blank/water-damaged pages — these ARE printed pages 1–3 by the page_offset
  calculation (+6 throughout), but the text is illegible due to water damage / foxing.
- Canvas 10: First readable content — **advertising insert**, Protection Mutual Insurance
  Company, 52 Wall St. (printed "1" = page 1 of the advertising block, separate from the
  directory body page sequence).
- Canvas 11: Advertising insert — L.S. Wicker, Ornamental Sign Painter, 84 Broad St.
- No front-matter TOC, preface, or abbreviations key page reached within the first 12 canvases.
  The --front 12 sample is exhausted by library/binding/ad material; the title page and any key
  page are either in the damaged section (canvases 7–9) or precede the listing in the first few
  printed pages. **Recommend a targeted resample** at `--front 20` to find the title page and
  confirm whether an abbreviations key exists.
- `column_count` = **1** (single full-width column; typical of pre-1850 NYC directories).
- `page_offset` (canvas_index − printed_page): **+6** at canvas 241 / printed p.235 AND
  at canvas 561 / printed p.555 — **constant throughout** (no drift). This confirms that the
  advertising pages form a fixed front block and are NOT interspersed in the listing.
  Formula: `printed_page = canvas_index − 6`.

## Entry format
`Surname Firstname[s], [occupation WorkplaceAddr] [h HomeAddr]`

Comma after given name(s) but NOT between occupation and workplace address (unlike Lain/Trow).
`h.` or `h` marks the home address. `m. d.` = physician; `c.` = corner; `b. b.` = boards(?).
Firms follow the same format: `Eastman & Co. wines 2 Counties-slip`.

Verbatim samples (canvas 0241, EAS–EBB, printed p.235):
- `Earnest James, sign painter 206 Pearl h. 19 Cherry`
- `Eastburn John W. printer 169 Ludlow`
- `Eastman Samuel B. printer 62 Oliver`
- `Easton Charles cot. broker 63 Wall c. Pearl h. 62 Rivington`
- `Easton George S. merchant 146 Pearl h. 82 Beekman`
- `East Ann widow of Josiah, 171 Division`

Verbatim samples (canvas 0561, RIP–ROA, printed p.555):
- `Ripley Charles, tavern 9 Little water`
- `Ritter Thomas, m. d. 104 Cherry`
- `Ritterband Leon M. furrier 224 Seventeenth`
- `Rivers Augusta, w. of Jas. R. boardng. 368 Broome`  *(w. of = widow of)*
- `Rivers widow Rachel, 45 Carmine`  *(widow in middle position — unusual variant)*
- `Roach William S. hairdresser 512½ Grand`

## Abbreviations

The **1839 rep volume** has no explicit legend page (marks inferred): `h.`/`h` house/home ·
`c.` corner · `m. d.` physician · `w. of`/`widow of` widow · `cot.` cotton · `b. b.` boards
(tentative) · `paperst.` paper stationer. Sparse, mostly spelled out (old style).

But the **earlier Longworth 1818/19 volume DOES print an explicit legend** at the head of the
A-listing (`nypl/69fdfa80-5d88-0134-e574-00505686a51c`, listing-start printed p.29 = canvas 30,
`page_offset` +1; sampled 2026-06-29). Verbatim — note the **widow/firm ordering rule**:

> Where a blank is left after the name in this Directory, it is always to be understood as a street;
> as Abraham Moses, 115 Broad is Broad-street. The lanes, alleys, slips, &c. always mentioned.
> **h. stands for house — n. near — c. for corner.** … the christian names of those where there are
> more than one of the same surname are correctly alphabeted. **The firms are always placed at the
> last of those of the same name; where females are known to be widows, they are so designated, and
> placed immediately preceding the firms.**

So the same **"street-implied" 1810s house-style** as Elliot 1811/12 ([elliot_newyork_1810s.md]),
plus an explicit **same-surname ordering rule** (individuals alphabetized by given name → widows →
firms last) — useful for synth ordering of a surname cluster.

## NYPL annual run 1797–1843 (sampled 2026-06-19)
The NYPL set is a near-complete annual run (48 rows, `New York City directory, 18xx-xx`,
IDs `…-00505686a51c`). Three representatives sampled across the range (`--front 20 -k 2`)
confirm the card generalizes to the whole cohort:

| Year | NYPL ID (head) | column_count | page_offset | notes |
|---|---|---|---|---|
| 1797 | `9c27dfc0` | 1 | **+19 constant** | c164=p.145, c281=p.262 |
| 1820/21 | `d0c00950` | 1 | **−5 → +7 (drift)** | c151=p.156, c355=p.348 |
| 1842/43 | `5a28bac0` | 1 | **−9 constant** | c226=p.235, c530=p.539 |

- **`column_count` = 1 holds across the entire 1797–1843 run** (verified at both extremes; the run
  predates the ~1845 two-column transition seen in Doggett). `column_count=1` was backfilled for all
  61 Longworth rows (NYPL + IA) on this basis.
- **`page_offset` is per-volume — no cohort constant.** Values range from +19 (1797) to −9 (1842) and
  some drift mid-volume (1820: −5→+7). Each volume's front matter is an almanac/register block of
  different length, and unpaginated plates drift the offset. Only the 3 sampled NYPL volumes have
  `page_offset` recorded; the other 45 NYPL + 10 IA rows need per-volume sampling to measure it.
- **Negative offsets** occur in later/larger volumes (1842: −9): the printed page number runs *ahead*
  of the canvas index, so `canvas_index = printed_page + offset`. (Same formula as positive offsets,
  just a negative constant.)
- **No TOC reached** in the 20-canvas front sample for any NYPL volume — the front matter is almanac
  calendar pages (monthly tables, e.g. Feb/Mar 1821) with no directory TOC, so `start_page`/`end_page`
  were left blank (would need a deeper front scan or the alphabetical-section boundaries).
- **Entry-format evolution:** 1797 uses a comma after the *surname*
  (`Cheeseman, Furman, shipwright, 71 Catharine-street.`) with `do.` = ditto for a repeated street.
  By 1820+ the comma moves to after the given name(s) (`DeWitt Peter, attorney and not. 37 Cedar`),
  matching the 1839 representative below. Single full-width column throughout.

## Genre
Residential persons directory — Manhattan (KEEP shape). Publisher: David Longworth.
Also contains almanac section (the "New-York Register" portion) before the directory body.
