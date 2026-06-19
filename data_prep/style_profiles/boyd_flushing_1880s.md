# Boyd — Flushing (Queens) Directory, 1880s–1890s

**Representative volume:** `ia/flushingnewyork188586boyd` — *Boyd's Flushing, N.Y. Directory,
for the years 1885-6* (W. Andrew Boyd, Passaic N.J.; printed by J.F. Morris & Co.).
Contains: (1) general persons directory of Flushing, and (2) classified business + farmers'
directory of the North Side Division, L.I.R.R. Visually sampled 2026-06-19.

## Structure (canvas indices, 0-based)
- Canvas 0: Red cloth cover. Canvas 1: ACPL Reynolds Historical Genealogy Collection card.
  Canvas 2: Allen County PL barcode. Canvases 3–4: Blank endpapers.
  Canvas 5: IA digitization notice. Canvas 6: **Title page**.
- Canvases 7–15 (est.): Advertising leaves (unnumbered); ads continue interspersed throughout.
- **Persons (residential) section** estimated to start around canvas 16 / printed page 1
  (offset = +15 throughout the persons section; no TOC or key page reached in front-matter sample).
- `column_count` = **1** (single full-width column; small-town directory style).
- `page_offset` (canvas_index − printed_page):
  - **+15** at canvas 73 / printed p.58 (HAL–HAR, persons section) — **use this for the persons section**.
  - **+64** at canvas 171 / printed p.107 (classified business section) — massive jump because
    ~49 unnumbered ad-leaf pages sit between the end of the residential section and the
    classified business section. Do NOT use +64 for the persons section.

**No abbreviations key page found** in the 12 sampled front-matter canvases — ads occupy the
entire front block. A resample at `--front 20` starting after canvas 6 may turn up a key if
one exists, but small-town directories often have no separate key.

## Entry format
`Surname Firstname[s], [occupation][, WorkAddr], h HomeAddr`

Flushing is a small town: street addresses frequently omit house numbers (just the street name).
Persons employed in New York City note it in parentheses after the occupation. `h do` = ditto
(home address repeats the one above).

Verbatim samples (canvas 0073, HAL–HAR, printed p.58):
- `Hallett William D, undertaker, h 25 Main`
- `Halliday Augusta, widow George, h 53 Main`    *(widow + husband's first name, no "of")*
- `Halliday Frank, h 53 Main`                    *(no occupation listed)*
- `Hamilton James C (clerk, N.Y.), h Sandford ave nr Union`
- `Harrison George W (teacher, N.Y.), h Amity cor Parsons ave`
- `Harvey Andrew, carpenter, 87 West Amity, h do`    *(h do = same address)*
- `Hamlin William B, cigars, 63 Main, h Bradford ave`
- `Hanze Charles, police captain, h Broadway cor Linden ave`
- `Harris Deborah, widow, h 129 Washington`      *(widow with no husband name given)*

## Abbreviations (inferred; no explicit legend)
`h` house · `nr` near · `cor` corner · `ave` avenue · `do` ditto (repeats preceding address) ·
`(N.Y.)` works in New York City · `wid.` / `widow` widow

## Structure — classified business section (canvas 171, p.107)
The volume's second half is a **classified business directory**, not a persons listing. Sections
visible: Milk Dealers, Milliners, Newspapers, Notaries, Nurseries, Oil, Oil Manufacturers,
Opera Glasses, Optician, Paint Manufacturers, Paints & Painters, Photographers. Format within
sections is sub-categorised, name + address only. This section is NOT the target for the
persons NER model.

## Genre
Residential persons directory — Flushing/Queens (KEEP shape for persons section).
Publisher: W. Andrew Boyd. The same Boyd series also covers Flushing 1890 and 1891/92
(sibling IA IDs: `flushingnewyorkc00boyd`, `flushingnewyork189192boyd`).
