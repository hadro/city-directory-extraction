# Trow — New York City Directory (Manhattan), ~1890s

**Representative volume:** `nypl/4b984650-317a-0134-f64d-00505686a51c` — *Trow's New York City
Directory, Vol. CIV, for the year ending May 1, 1891* (The Trow City Directory Company).
Visually sampled 2026-06-19.

## Structure (canvas indices, 0-based)
- Title page: **canvas 6**. Copyright verso: 7. Preface: **canvas 8**. Foldout map: 4.
  Index to Advertisers: 11+. **Abbreviations key = listing-start page: canvas 14** (the
  "ABBREVIATIONS" block and the "A" listing begin on the same page).
- `column_count` = **3** — *stated in the preface* ("it now being printed in three columns").
  Note: `detect_columns` reported 2 on listing pages (under-count) — preface wins.
- `page_offset` (canvas_index − printed_page): ≈ **−1** near the front (printed p.26 @ canvas 25),
  drifting to ≈ **+9** deep in (printed p.353 @ canvas 362) due to unpaginated plates. Record local.
- Listing pages carry **ad strips top & bottom**; running heads are the 3-letter alpha guides
  (e.g. DUP / DUR).

## Entry format
`Surname Given[, occupation][, employer/business][, h <home address>]` — with a leading `—` as a
**ditto** for the repeated surname on continuation lines.

Verbatim samples (printed p.353):
- `Dupp Wm. painter, h 305 E. 29th`
- `Duppler Chas. tngr. 33, 3d av. h 240 E. 10th`
- `— Chas. cooper, h 5205, 3d av.`  *(— = repeats "Duppler")*
- `Dupre Felton, books, 549, 5th av.`

## Abbreviations legend (from the key page, canvas 14 — partial; refine on a hi-res re-read)
`h.` house · `r.` rear/resides · `bds.` boards · `av.` avenue · `bet.` between · `cor.` corner ·
`st.` street · `pl.` place · `opp.` opposite · `wid.` widow · `clk` clerk · `mfr` manufacturer ·
`B'klyn` Brooklyn · `N./S./E./W.` North/South/East/West · `wks` works · `R.R.` railroad ·
`U.S.` United States · `Prot.` Protestant. *(Full legend is ~6 mini-columns; transcribe completely
when building the production profile.)*

## Bonus resource (preface, canvas 8)
The preface prints **spelling-variant name clusters** ("TO FIND A NAME YOU MUST KNOW HOW IT IS
SPELLED"): Allan/Allen/Allyn, Auld/Old, Ayers/Ayres, Bauer/Baur/Bower, Bergen/Berger/Burger,
Bigelow/Biglow, Cohen/Cohn/Kohn, Reis/Reiss/Rice, Schafer/Schaffer/Schaefer/Schaeffer/Shaffer… —
directly relevant to the model's surname-regularization failure; candidate seed for name generation.

## Genre
Residential persons directory (KEEP shape).
