# Hearne — Brooklyn City Directory, 1850s

**Representative volume:** `ia/hearnesbrooklync1852unse` — *Hearnes' Brooklyn City Directory,
for 1852-1853* ("Eleventh Annual Publication"; Henry R. & William J. Hearne, Office 1 Front Street,
cor. Fulton, Brooklyn; printer William Foulkes, 41 Fulton cor. Front st.; price One Dollar).
Visually sampled 2026-06-19.

> Publisher spelling: the title reads **HEARNES'** but the copyright/imprint is **HENRY R. &
> WILLIAM J. HEARNE** (no final *s*). Master-list publisher field = "Hearnes". "Eleventh Annual
> Publication" in 1852 ⇒ the series began ~1842.

## Structure (jp2 leaf indices, 0-based)
- Leaves 0–10: IA scan wrappers / blank cover stock (brown paper, no text).
- Leaf 11: **Title page**. Leaf 12: copyright ("Entered … in the year 1852, by Henry R. & William
  J. Hearne … Southern District of New York").
- Leaf 13+: **Advertisements** section with its *own* pagination (leaf 13 = ad page "3"). The ad
  block occupies the front and runs through leaf 26 (still a full-page ad: "FITHIAN & JOY, Sash,
  Blind, and Door Manufacturers").
- **Leaf 27 = the abbreviations key page** (printed p.17, unnumbered — no running head). It is *not*
  in the front matter: the legend is printed at the head of the "A" listings, immediately behind the
  ad wall, and the first entries (`Abberly Richard…`) follow it on the same page. A `--front 20`
  sample stops 7 leaves short of it — see the resampling lesson in
  [`README.md`](README.md). Legend verbatim:
  > NOTE.—Names having a \* are the names of colored people.—
  > Abbreviations: h. stands for house, n. for near, c. for corner, op. for
  > opposite, b. for between. The precise location of residences thus de-
  > scribed, may be ascertained by reference to the STREET DIRECTORY.
- Persons listing (body) carries the running head **"BROOKLYN CITY DIRECTORY"** and its own arabic
  pagination, starting at leaf 28 = printed p.18.
- `column_count` = **1** (single full-width column — confirmed on regular-IA 1850 & 1852 *and* the
  microfilm `micro_IABROOKLYN` scans).
- `page_offset` (leaf − printed_page): **per-volume, drifts** (interspersed ad leaves):
  | Volume | offset (near start → later) |
  |---|---|
  | `hearnesbrooklync1850unse` (1850) | +16 → +22 (leaf152=p.136, leaf352=p.330) |
  | `hearnesbrooklync1852unse` (1852) | +10 → +16 (measured curve below) |
  | `micro_IABROOKLYN_0028` (1850/51) | +8 (leaf146=p.138) |
  | `micro_IABROOKLYN_0032` (1854/55) | +6 (leaf196=p.190) |

  For **1852 the curve is measured, not anchored** — recovered from the running-head page number on
  all 457 body leaves that print one (of 584 pages OCR'd; see "Full-volume run" below). It is a
  monotone step function outside the ad-riddled leaves 44–48:

  | from leaf | offset |
  |---|---|
  | 28 | +10 |
  | 44–48 | unstable (+8…+12; interspersed ad leaves, and OCR misreads the page number on 44/46) |
  | 66 | +12 |
  | 190 | +14 |
  | 202 | +16 (holds to the end of the body) |

  The two anchors previously recorded here (leaf175=p.163 → +12, leaf413=p.397 → +16) both sit on
  the measured curve; they just missed the +10 opening step and the 44–48 instability. Leaves
  143, 302 and 577 carry page numbers the OCR misread — ignore them, don't treat them as steps.

## Entry format
`Surname Firstname, occupation [StreetRelation] [NY] [h HomeAddr]`

Brooklyn street-relation grammar (no house numbers on many entries — location given relative to
cross/named streets):
- `n` near · `c` corner · `b` between · `op` opposite · `r` rear · `av` avenue · `pl` place ·
  `h` house/home
- **`NY` = works in New York** (commuter notation — Brooklyn resident whose business is across the
  river in Manhattan), usually followed by `h` + the Brooklyn home address:
  `Evans Ira P, grocer 79 Front NY h Union c Court` · `Skinner Samuel S, 79 Maiden lane N Y h 8 Remsen`
- Prominent persons / officials in **ALL CAPS**, office in parens:
  `EVANS MARTIN, druggist (Alderman 7th ward) Myrtle c …`
- **`*` prefix = colored** — *resolved*, from the volume's own key page (leaf 27): "Names having a
  \* are the names of colored people." This is the **Ogden 1839 sense, not the Hope & Henderson
  sense** — Hearne's `*` is a race marker and goes to `race_designation` verbatim (`"*"`), star kept
  **off** the `name` field, per convention #10:
  `*Flood Alvy, barber 82 Atlantic h 177 Adams` · `*Rue Pero, lighterman 22 Chapel` ·
  `*Chinn William H, hair dresser 55 Atlantic h 25 Chapel`
  Measured over the full 1852 volume: **312 asterisked entry lines on 151 of 584 pages**, ≈**1.3%**
  of entry-shaped lines (cf. Ogden 1839's ≈11%). Asterisked households cluster — 107 Navy, 31 Chapel
  and 103 Concord each carry several — so the marker is also a usable handle on Brooklyn's free
  Black community in 1852. Treat it as historically significant data: it is the *only* racial
  identification the volume carries, and stripping the star destroys it irrecoverably.
- Widow format spelled out: `Fitzpatrick Mary, widow of Michael, 197 York` · `Slade John, widow 58 Fulton`

Verbatim samples (1852, leaf 175, printed p.163, EPS–EVA):
- `Estabrook Ethan, secretary to the board of Assessors office City Hall h 147 Myrtle av`
- `Eustace George W, morocco dresser 21st st n 3d av Gowanus`
- `Evans Ira P, grocer 79 Front NY h Union c Court`
- `EVANS MARTIN, druggist (Alderman 7th ward) Myrtle c …`

Samples (1850, leaf 152, printed p.136, FIT–FLA):
- `Fitzpatrick Richard, grocer Hamilton av op Court st`
- `Fitzsimmons Margaret, widow Willow n Pacific`

## Abbreviations
**From the printed legend** (leaf 27, quoted in full above): `h.` house · `n.` near · `c.` corner ·
`op.` opposite · `b.` between · `*` **colored**. The legend also directs relative locations to the
**STREET DIRECTORY** — that is where a `Dean n Vanderbilt av` style address resolves to a number.

Inferred from listings, *not* in the legend: `r` rear · `av` avenue · `pl` place ·
`NY` / `N Y` works in New York (Manhattan). Occupations spelled out (older, uncompressed style).

Note the legend prints its abbreviations **with periods** (`h.`, `n.`, `c.`, `op.`, `b.`) but the
listings **never do**. Counted across the whole volume: `h` 3216 bare / 0 with period, `n` 6277 / 0,
`c` 2468 / 1, `op` 99 / 0, `b` 649 / 0. Follow the **listings**, not the legend, for `raw_line` —
and don't let a prompt that quotes the legend prime the transcriber for periods the body never sets.

## Full-volume run (external — `directory-pipeline`)

This is the one Hearne volume that has been run end-to-end through the sibling
`directory-pipeline` project, so it is the deepest evidence behind this card. **Not in this repo**
(≈2 GB); it lives at:

```
~/github/directory-pipeline/output/hearnes_brooklyn_city_directory_for_hearnesbrooklync1852/
  ocr_prompt.md, ner_prompt.md, selection.txt        # generated prompts + page selection
  hearnesbrooklync1852unse/
    manifest.json, select_pages.html
    <NNNN>_…_<LLLL>.jp2.jpg                          # page image
    <NNNN>_…_<LLLL>.jp2_surya.{txt,json}             # surya OCR
    <NNNN>_…_<LLLL>.jp2_gemini-2.0-flash.txt         # gemini-2.0-flash OCR
    <NNNN>_…_<LLLL>.jp2_gemini-2.0-flash_aligned.json  # line bboxes + IIIF canvas fragments
    <NNNN>_…_<LLLL>.jp2_gemini-2.0-flash_viz.jpg     # bbox overlay
```

**584 pages**, complete for every stage. The `_aligned.json` is the valuable part — **surya's line
boxes carrying gemini's text** (the two files' boxes are byte-identical), with a
`canvas_fragment` against `https://iiif.archive.org/iiif/hearnesbrooklync1852unse$<N>/canvas`,
i.e. citable coordinates for every transcribed line in the volume.

Ingesting this into `data/*.jsonl` is planned in
[`docs/PIPELINE_INGEST_PLAN.md`](../../docs/PIPELINE_INGEST_PLAN.md); this volume is its first
target. Two Hearne-specific wrinkles recorded there: **235 bracket-overflow lines** (`… 41 Little
[Hoyt` — a word set in a *neighbouring* line's right margin, attaching **up or down** depending on
which neighbour dangles) and **418 hyphen-wrap lines** (which `join_wraps` already closes up
correctly: `h 135 Jorale-` + `mon n Court` → `h 135 Joralemon n Court`).

Two join traps in that directory, both verified:

- **The `<NNNN>` filename prefix is a running index, not the leaf number.** It tracks the leaf only
  through index 187; from 188 it drifts (`0231_…_0235`, `0584_…_0588`) because 4 leaves are absent.
  **397 of the 584 files** have prefix ≠ leaf. Parse the leaf from the `_<LLLL>.jp2` segment at the
  end, never from the prefix.
- **`canvas_uri` is leaf − 1** (leaf 175 → `…unse$174/canvas`) — the same off-by-one as the IA
  `_page_numbers.json` leaf/canvas join. Don't double-apply it.

## Genre
Residential persons directory — **Brooklyn** (KEEP shape). Publisher: Henry R. & William J. Hearne.
Cohort = 7 master-list rows 1850–1854/55: regular IA (`hearnesbrooklync18xxunse`) + microfilm
(`micro_IABROOKLYN_0028…0032`). The microfilm scans are **single-page, single-column** (NOT
double-page spreads), just darker/degraded — readable. `column_count=1` backfilled for all 7;
`page_offset` recorded for the 4 sampled (per-volume, no cohort constant).
