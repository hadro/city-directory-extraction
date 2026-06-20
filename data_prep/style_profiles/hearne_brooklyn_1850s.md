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
  block occupies the front; **no abbreviations key page reached** in the `--front 20` sample.
- Persons listing (body) carries the running head **"BROOKLYN CITY DIRECTORY"** and its own arabic
  pagination; sampled at leaves 152/175/352/413 (printed pp. 136/163/330/397). A deeper resample
  would be needed to confirm whether an explicit abbreviations legend exists between the ads and the
  body.
- `column_count` = **1** (single full-width column — confirmed on regular-IA 1850 & 1852 *and* the
  microfilm `micro_IABROOKLYN` scans).
- `page_offset` (leaf − printed_page): **per-volume, drifts** (interspersed ad leaves):
  | Volume | offset (near start → later) |
  |---|---|
  | `hearnesbrooklync1850unse` (1850) | +16 → +22 (leaf152=p.136, leaf352=p.330) |
  | `hearnesbrooklync1852unse` (1852) | +12 → +16 (leaf175=p.163, leaf413=p.397) |
  | `micro_IABROOKLYN_0028` (1850/51) | +8 (leaf146=p.138) |
  | `micro_IABROOKLYN_0032` (1854/55) | +6 (leaf196=p.190) |

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
- `*` prefix on scattered names — meaning **uncertain** (possibly late addition or "removed";
  not resolved from front matter): `*Flood Alvy, barber 82 Atlantic h 177 Adams` · `*Rue Pero, lighterman 22 Chapel`
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
No explicit legend reached in the front-20 sample (ads occupy the front). Inferred from listings:
`h` house/home · `n` near · `c` corner · `b` between · `op` opposite · `r` rear · `av` avenue ·
`pl` place · `NY` / `N Y` works in New York (Manhattan) · `*` uncertain (late-add/removed?).
Occupations spelled out (older, uncompressed style).

## Genre
Residential persons directory — **Brooklyn** (KEEP shape). Publisher: Henry R. & William J. Hearne.
Cohort = 7 master-list rows 1850–1854/55: regular IA (`hearnesbrooklync18xxunse`) + microfilm
(`micro_IABROOKLYN_0028…0032`). The microfilm scans are **single-page, single-column** (NOT
double-page spreads), just darker/degraded — readable. `column_count=1` backfilled for all 7;
`page_offset` recorded for the 4 sampled (per-volume, no cohort constant).
