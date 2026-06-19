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

## Abbreviations (inferred; no explicit legend page found)
`h.` / `h` house/home · `c.` corner · `m. d.` physician · `w. of` / `widow of` widow ·
`cot.` cotton · `b. b.` boards (tentative) · `paperst.` paper stationer ·
`a. t. s.` (unknown — likely an organization abbreviation)

Abbreviations are sparse and mostly spelled out (old style, c.1839).

## Genre
Residential persons directory — Manhattan (KEEP shape). Publisher: David Longworth.
Also contains almanac section (the "New-York Register" portion) before the directory body.
