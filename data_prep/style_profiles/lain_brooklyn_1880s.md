# Lain — Brooklyn City Directory, 1880s

**Representative volume:** `ia/1885BPL` — *Lain's Brooklyn City Directory, 1884-85*
(Lain and Company). Visually sampled 2026-06-19.

## Structure (canvas indices, 0-based)
- Canvas 0: Modern BPL cover page (not original; supplies a PDF-page TOC — see below).
- Canvas 1: Original title page + NOTICE + **ABBREVIATIONS** block + start of (A) listings.
  - `key_page` = **1**; the abbreviations legend and the persons listing start on the same canvas.
- Printed pages begin at 1 (canvas 1); running heads follow `ABC–ABC  <page>  ABC–ABC` pattern.
- `column_count` = **2** — two text columns separated by a vertical rule; vertical ad strips run
  in the outer margin, often sideways. (No preface statement found; counted visually.)
- `page_offset` (canvas_index − printed_page): ≈ **0** near the listing start (canvas 2 =
  printed p.2); drifts to **+26** by p.442 (canvas 468) and **+50** by p.1044 (canvas 1094)
  due to interspersed unnumbered colour-ad pages throughout the volume.

**BPL digitization TOC** (from the modern cover, in PDF page numbers — NOT original page numbers):
- Residential directory listings: PDF pp. 2–1513
- Index to Municipal Register: 1514–1515
- Municipal Register: 1516–1533
- Street and Avenue Directory: 1534–1563

Note: the BPL cover itself says "the color-printed advertisement pages in the directories were
not numbered" — this explains the growing page_offset drift above.

## Entry format
`Surname Firstname[s], [wid. SpouseSurname/First,] [Occupation][, Employer/WorkAddr], [h HomeAddr]`

Full surname repeated on every line — **no ditto dash** (unlike Trow).

Verbatim samples (canvas 1, A-section start):
- `Aab George, machinist, h 294 Stockton`
- `Aadel Joseph, shoeomkr, h 550 B'way`
- `Aaens Henry, lab. h 62 Atlantic av`
- `Aaholm Jacob, perfumery, 97 William`  *(business address only — no h)*
- `Abbey Westminster S. grocer, 61 Front N.Y. h 229 Union`  *(business in Manhattan, home in Brooklyn)*

Widow entries (canvas 5-6, ADA-ADD):
- `Adams Mary, wid. Philip, h 343 Pacific`
- `Adams Ellen, wid. Thomas, grocer, 71 N. 7th`
- `Adams Elizabeth, wid. Thomas, upholsterer`

Notable persons appear in ALL CAPS:
- `ADAMS HENRY H. county treas'r, 13 Court`

## Abbreviations legend (transcribed from canvas 1)
`acct.` accountant · `agl.` agricultural · `agt.` agent · `al` alley · `art.` artificial ·
`av` avenue · `asst` assistant · `bk.` book · `bldg.` building · `bldr.` builder ·
`B'way` Broadway · `c` corner · `c.b.` custom house · `clk.` clerk · `com.` commission ·
`comm.` commissioner · `ct.` court · `dept.` department · `depty.` deputy · `E.` east ·
`furnig.` furnishing · `ft` foot · `gds.` goods · `h` house · `hgts.` heights ·
`impr.` importer · `imps.` implements · `ins.` insurance · `insp.` inspector ·
`insts.` instruments · `kpr.` keeper · `la` lane · `lab.` laborer · `Laf.` Lafayette ·
`Lex.` Lexington · `mfr.` manufacturer · `mtls.` materials · `mer.` merchant · `mkt.` market ·
`n` near · `N.` north · `N.Y.` New York · `oper.` operator · `opp` opposite · `pat.` patent ·
`pl.` place · `pres't` president · `r.` rear · `rd.` road · `S.` south · `Scher.` Schermerhorn ·
`sec.` secretary · `sq` square · `supt.` superintendent · `surgl.` surgical · `tel.` telegraph ·
`treas'r` treasurer · `u.s.a.` United States Army · `u.s.n.` United States Navy ·
`Vand't` Vanderbilt · `Wash'n` Washington · `W.` west · `wf` wharf · `wid.` widow

## Cohort 1884–1899 (sampled 2026-06-19)
Five more IA BPL volumes sampled (`--front 20 -k 2`) to extend this card. All confirm the 1885BPL
structure — **2 columns** with marginal vertical ad strips, full surname repeated, same legend:

| Volume | year | column_count | page_offset (at sample point) |
|---|---|---|---|
| `1884BPL` | 1884 | 2 | +54 @ p.402 → +82 @ p.984 (heavy drift) |
| `1885BPL` | 1884/85 | 2 | ≈0 near start → +50 @ p.1044 *(this card's rep)* |
| `1886BPL` | 1886 | 2 | +60 @ p.336 |
| `1887BPL` | 1887 | 2 | +53 @ p.367 |
| `1889BPL` | 1889 | 2 | +20 @ p.422 |
| `1899xBPL` | 1899 | 2 | +52 @ p.542 (Lain & Healy imprint) |

- **`column_count` = 2 across 1884–1899** — backfilled for all 5 newly-sampled rows.
- **`page_offset` drifts heavily and per-volume** (unnumbered colour-ad pages throughout): by ⅓ of
  the way in, offsets are already +20 to +60, and 1884 reaches +82 by p.984. The recorded CSV
  `page_offset` is the value **at the first sample point (~⅓ through), not near the listing start** —
  the leaf/page anchor is in each row's notes. (Unlike 1885BPL where the near-start value ≈0 was
  measurable because it had a modern BPL cover; the raw IA scans here lead with ad pages.)
- **Front matter differs from 1885BPL:** these IA scans open with advertisement pages (leaf 1 = ad
  page, running head "BROOKLYN CITY & BUSINESS DIRECTORY" / "LAIN'S BROOKLYN DIRECTORY"), so the
  abbreviations key + (A) listing start sit deeper than the `--front 20` sample reaches. The legend
  is already transcribed above (from 1885BPL) — not re-transcribed per volume. `key_page` left blank
  for the cohort rows.
- **1899 is "Lain & Healy"** (the imprint changed) but the format/legend are unchanged.
- **HELD-OUT:** `1897BPL` (Lain & Healy) is an eval held-out volume — deliberately NOT sampled.

## Genre
Residential persons directory — Brooklyn (KEEP shape). Publisher: Lain and Company.
