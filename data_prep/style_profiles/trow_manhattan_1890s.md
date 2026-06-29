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
**ditto** for the repeated surname on continuation lines. **In gold: keep it verbatim as a plain
hyphen `-`** (what OCR emits — `-Michl h 1773 1st av` under Juarez → name `-Michl`, NOT "Juarez
Michl"); don't resolve the surname (downstream step). Heavy in this dense col-3 format — whole runs
of `-Given` entries.

Verbatim samples (printed p.353):
- `Dupp Wm. painter, h 305 E. 29th`
- `Duppler Chas. tngr. 33, 3d av. h 240 E. 10th`
- `— Chas. cooper, h 5205, 3d av.`  *(— = repeats "Duppler")*
- `Dupre Felton, books, 549, 5th av.`

## Abbreviations legend — FULLY TRANSCRIBED 2026-06-20 (printed "ABBREVIATIONS" block, canvas 15)
**Important:** the volume's printed **ABBREVIATIONS** block (on the title / "A"-listing-start page)
is a **places / streets / trade-category** key — **not** the h/r/bds entry-marker glossary. The
entry markers below come from reading listing lines; some terms (corner, opposite, house, widow)
appear in both.

*Entry markers (from listing lines):* `h` house · `r` rear · `bds` boards · `av` avenue ·
`bet` between · `cor`/`c` corner · `st` street · `opp` opposite · `wid.` widow · `clk` clerk ·
`mfr` manufacturer · `wks` works.

*Printed key (verbatim, 4 columns ≈ 110 entries):* `ag. implts.` agricultural implements ·
`al.` alley · `Am.` American · `assn.` association · `asst.` assistant · `Att'y` Attorney ·
`bdgh.` boarding house · `bkbinder` bookbinder · `bot. meds.` botanic medicines · `B'klyn` Brooklyn ·
`bldg.` building · `bldr.` builder · `Cath.` Catharine · `(Rev.)` clergyman · `commr.` commissioner ·
`cons.` consolidated · `Cotton Ex.` Cotton Exchange · `ct.` court · `C. H.` Court House · `Dist.` District ·
`eatingh.` eating-house · `E.` East · `E. R.` East River · `elec. insts.` electrical instruments ·
`embdr.` embroiderer · `embds.` embroideries · `eng.` engineer · `Exch.` Exchange · `fcy.` fancy ·
`fwdg.` forwarding · `ft.` foot · `gds.` goods · `Gt.` Great · `gr.` green · `hdkfs.` handkerchiefs ·
`hgr.` hanger · `hts.` heights · `h. furng.` house furnishing · `impr.` importer · `ins.` insurance ·
`insp.` inspector · `Jeff.` Jefferson · `J. C.` Jersey City · `Laf.` Lafayette · `la.` lane ·
`Lex.` Lexington · `(Ltd.)` limited · `L. I.` Long Island · `mfg.` manufacturing · `mkt` market ·
`matls` materials · `math. insts.` mathematical instruments · `mkr.` maker · `mech` mechanical ·
`men's furng.` men's furnishing · `mer.` merchant · `Mt.` Mount · `mus. insts.` musical instruments ·
`n` near · `N.` North · `N. R.` North River · `pk.` park · `pat. meds.` patent medicines ·
`phil. insts.` philosophical instruments · `phot. matls.` photographic materials · `pl` place ·
`pktbk.` pocket book · `Pt.` Point · `pres.` president · `Produce Ex.` Produce Exchange ·
`prof.` professor · `provns.` provisions · `pub. acct.` public accountant · `Pub.` Publishing ·
`P. G.` Purchasers' Guide · `R.R.` Railroad · `Scher.` Schermerhorn · `sec.` secretary · `sl.` slip ·
`soc.` society · `S.` South · `sq.` square · `Sta.` Station · `S. I.` Staten Island · `supt.` superintendent ·
`surg. insts.` surgical instruments · `tel. insts.` telegraph instruments · `ter.` terrace ·
`Tomp.` Tompkins · `trans.` transportation · `treas.` treasurer · `u. s. a.` United States Army ·
`u. s. n.` United States Navy · `Vand'b't` Vanderbilt · `v. pres.` vice president ·
`vet. surg.` veterinary surgeon · `W.` West · `Wil'by.` Willoughby · `wkr.` worker.

## Bonus resource (preface, canvas 8)
The preface prints **spelling-variant name clusters** ("TO FIND A NAME YOU MUST KNOW HOW IT IS
SPELLED"): Allan/Allen/Allyn, Auld/Old, Ayers/Ayres, Bauer/Baur/Bower, Bergen/Berger/Burger,
Bigelow/Biglow, Cohen/Cohn/Kohn, Reis/Reiss/Rice, Schafer/Schaffer/Schaefer/Schaeffer/Shaffer… —
directly relevant to the model's surname-regularization failure; candidate seed for name generation.

## Other panel Trow volumes — key page confirmed (2026-06-29)

The "**ABBREVIATIONS block = A-listing-start page**" pattern holds across the whole Trow run; each
volume's key page is its `start_page`, with the same places/streets/trade legend family (length grows
over time). Measured this session:

| volume | master id | key/start (printed) | key at canvas | offset | legend note |
|---|---|---|---|---|---|
| Trow/Wilson 1865-66 | `nypl/4b119360-…9131` | p24 | c24 | 0 | shorter legend (`al`,`b.mds`=boarding house,`E.R`=East River,`frwg`,`junc`,`mer`…); preceded by Commercial-Register index + "names refused" + nurses |
| Trow 1884-85 | `nypl/4b69a410-…a570` | p17 | c19 | +2 | `ag.imple`,`al`,`Am`,`asso`,`ass't`,`b'gh`,`bldsmkr`… ; A-start "Aab Elizabeth, wid Louis" |
| **Trow 1890-91 (rep)** | `nypl/4b984650-…f64d` | p15 | c15 | −1 (front) | the fully-transcribed legend above |
| Trow 1913-14 | `nypl/4bfc3730-…db31` | p17 | c24 | +7 | legend grown to a **full page**; titled "TROW GENERAL DIRECTORY OF THE BOROUGHS OF MANHATTAN AND BRONX 1913, ending Aug 1 1914"; `column_count=4` |

Takeaway for synth: the Trow abbreviations vocabulary is a stable, era-growing places/streets/trade
key — distinct from the h/r/bds **entry-marker** glossary — usable as the Trow-family style layer.

## Genre
Residential persons directory (KEEP shape).
