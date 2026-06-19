# Franks / Kollock — New-York Directory, 1786

**Representative volume:** `nypl/b14662b0-81a8-0134-2a18-00505686a51c` — *The New-York directory: containing, a valuable and well calculated almanack; tables of the different coins…* Compiled by David Franks; printed by Shepard Kollock, corner of Wall and Water Streets, New-York, 1786. Visually sampled 2026-06-19.

**Scope:** This is the **first New-York City directory ever published** — 82 pages in a 12mo format. Tiny volume; the persons listing is the main body (roughly pp. 17–52 based on IIIF canvas labels and visible page numbers). The NYPL copy is incomplete: lacks original title page and pp. 5-6, supplied in 1896 facsimile from the N.Y. Historical Society copy.

## Sister copies and reprints

| Source | ID | Type | Notes |
|--------|-----|------|-------|
| NYPL | `b14662b0-81a8-0134-2a18-00505686a51c` | Original 1786 | Sampled; page_offset +8 measured |
| IA | `newyorkdirectory00fran` | Original 1786 | IA scan; page_offset not measured |
| IA | `newyorkdirectory00fran_0` | Original 1786 | IA scan; page_offset not measured |
| IA | `newyorkdirectory00durs_0` | 1874 Patterson reprint | Same format; page_offset not measured |
| LoC | `96203733` | 1876 Disturnell reprint | Same format; page_offset not measured |

All copies/reprints share `column_count = 1` and the same entry format. Page offsets depend on each institution's digitization.

## Structure (canvas indices, NYPL IIIF 1-based)

- Canvases 1–16 (est.): Library/binder material, supplied facsimile title page, almanac section (months, tide tables, state-by-state currency conversion tables).
- **Canvas 25** = printed page 17 (currency table "TABLE of DOLLARS, &c." — final almanac page; `page_offset = 25 − 17 = +8`).
- **Canvas 36** = printed page 28 (D–F section; `page_offset = 36 − 28 = +8`).
- **Canvas 47** = printed page 39 (M section; `page_offset = 47 − 39 = +8`).
- Persons listing ends around canvas 52/printed p. 44 (est.); pp. 45–52 contain civil officers, clergy, physicians, post-office, university, rates of porterage, mail schedules (see TOC).
- `column_count` = **1** (single column, full page width; standard for 18th-century directories).
- `page_offset` = **+8 constant** (no interspersed ads in the listing body; advertising is all in front matter).
  - Formula: `canvas_index = printed_page + 8`

## Entry format

`Surname Firstname[s], [occupation[, &c.],] Street-number, Street-name`

No distinction between home and work address — **one address per entry**. Street number precedes street name (comma-separated from name, but comma also separates fields generally). Firm entries follow the same format: `Surname Partner1 & Partner2, merch. 233, Q. st.`

Verbatim samples (canvas 36, D–F section, printed p. 28):
```
Dewint John, merchant, 12, Duke-street
Delap Samuel, 239, Queen-street
Depeyster W. A.                          [name only — no occ. or address]
Draper Geo. doctor, &c. 47, Han.-square
Degro Peter, painter and glazier, 136, Q.st.
Deleplane Jo. Quaker speaker, 132, Q. st.
Dale Samuel, 78, Queen-street            [no occupation]
Deremur Nicholas, hatter, 85, Queen-street
Douglass Geo. & S. merchants, 233, Q. st.
Dobson Tho. merchant, 330, Q. street
Egbert Moses, , Whitehall               [blank occupation field]
Eastburn John W. printer 169 Ludlow     [commas dropped between fields — variant style]
Franks D. conveyancer, &c. 66, Broadw. [compiler himself in the listing]
```

Verbatim samples (canvas 47, M section, printed p. 39):
```
Murro & McGraith, merch. 23, Maid-lane
Morgan J. jun. paint. & glaz. 15, Wat.ft.
Miller Peter, tobacconist, 19, Water-street
Mitchell & Herbertson, 42, Golden-hill
Montanye Ab. brass-founder, 13, King-street
Mercein Andrew, baker, 16, King-street
Montgomery Robert, minister, of the Seceder church, 7, Nassau-street
Mooney Wm. upholsterer, 14, Nassau-ft.
Murphy Mary, tavernkeeper, 57, M. lane
Maxwell Wm. snuff and tobacco manufacturer, 35, Wall-street
```

## Abbreviations (inferred — no explicit key page)

`merch.` / `mer.` merchant · `&c.` etc. (additional activities) · `gent.` gentleman · `jun.` junior · `paint. & glaz.` painter and glazier · `tobaco.` tobacconist · `Dr.` / `doctor` physician · `Broadw.` / `B.` Broadway · `Q.st.` / `Q. ft.` / `Q. street` / `Queen-street` Queen Street · `Wat.ft.` / `Wat.-street` / `Water-street` Water Street · `Han.-square` Hanover Square · `Maid-lane` / `M. lane` Maiden Lane · `Wm.-ft.` / `William-street` William Street · `Golden-hill` Golden Hill Street · `Nassau-ft.` / `Nassau-street` Nassau Street

Field separator: comma. Conventions are loose in this early volume — some entries drop commas between occupation and address, some lack occupation, a few have blank occupation fields.

## Genre

Residential + business persons directory — Manhattan (KEEP shape). 82 pages total; short listing (~33 pages). No ditto marks or abbreviation key page; each entry is self-contained. Publisher: David Franks (compiler), Shepard Kollock (printer).

The volume contains an almanac section before the directory body — that section is NOT a training target.
