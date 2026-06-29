# Handoff — front-matter / key-page / listing-start sampling (42-panel)

> Working state as of 2026-06-29. This is the **funding-independent** workstream: visually identify,
> for each gold-panel volume, its **front matter**, its **abbreviations key page**, and the **page
> where the persons listing begins** — and backfill `master_directories.csv` + write/extend the
> per-publisher **style cards**. Free: reads IIIF page images directly; **no Gemini**.
> Companion: [VISUAL_SAMPLING_HANDOFF.md](VISUAL_SAMPLING_HANDOFF.md) (the broader gold/sampling work),
> [../data_prep/style_profiles/README.md](../data_prep/style_profiles/README.md) (card schema).

## Goal & deliverables (per volume)
1. `start_page` — the printed page where the alphabetical persons listing begins.
2. `key_page` — the printed page carrying the "ABBREVIATIONS" / explanation-of-marks legend (or
   "none" where the volume has no dedicated key page).
3. `page_offset` — `canvas_index(0-based) − printed_page`, a local anchor near the listing start.
4. The **abbreviations legend transcribed** into the volume's style card (the real synth lever) and
   summarized in the CSV `notes`.

## CONVENTION (pinned this session — read before recording anything)
- `start_page` / `key_page` / `end_page` columns hold the **PRINTED page number** (matches the README
  and the existing NYPL rows — verified: Hodge `start=5` = the printed-page-5 listing start; Franks
  `start=20` is a printed page in the almanac→listing run).
- `page_offset` bridges to the scan: **`canvas = printed_page + page_offset`**. Always fill it when you
  set start/key, so the canvas is recoverable.
- **Document BOTH**: put the canvas index explicitly in `notes` (e.g. "listing A-start printed p3 =
  canvas c9; c10=printed p4 → offset +6"). Columns = printed page; notes = canvas + offset + legend.
- Do **not** silently overwrite eval-affecting fields (`year`, `column_count`): if the volume
  contradicts the master, set what you directly observe and add a `REVIEW:` note (see Rode below).

## Tooling — `data_prep/inspect_frontmatter.py` (stdlib only, no deps)
```bash
PY=python3   # plain stdlib; no venv needed
cd /Users/joshhadro/github/city-directory-extraction/data_prep
# list first N canvases (idx | label | image URL):
$PY inspect_frontmatter.py list  <nypl|ia|loc|iiif> <id> [N]
# download canvas idx i..j-1 as <tag>_<idx>.jpg into the script's dir:
$PY inspect_frontmatter.py get   <nypl|ia|loc|iiif> <id> i j [tag]
```
Resolvers: `nypl`→`api-collections.nypl.org/manifests/{id}` (v3), `ia`→`iiif.archive.org/iiif/{id}/manifest.json`,
`loc`→loc.gov item, `iiif`→manifest URL. Handles IIIF v2 and v3.

### Recipe (per volume)
1. `get <src> <id> 0 18 <tag>` → contact sheet: `montage <tag>_0*.jpg -tile 5x4 -geometry 250x340+3+3 -label '%f' <tag>_sheet.jpg` → `Read` it to locate title / TOC / key / listing-start.
2. Confirm the exact listing-start + key page by **`Read`-ing the specific canvas full-res** (filename = canvas idx — unambiguous).
3. Read a **printed page number** on a numbered listing page near the start → compute `page_offset`.
4. Record printed start/key + offset + canvas-in-notes; transcribe the legend into the style card.

### Pitfalls (cost real time — heed them)
- **Montage grid-position drift:** with blank versos / plates, "row×col counting" mis-assigns tiles by
  ±2. **Trust the `%f` filename label or do a targeted single-canvas Read** for the start/key decision.
- **`page_offset` needs verification:** ad banners sit over page numbers → misreads. Read the printed
  number directly; if a listing page shows a *signature* mark (e.g. "5*", "B") that's NOT the page no.
- **IA downloads are slow / occasionally drop:** ranges sometimes return fewer files than asked —
  re-run the `get`. NYPL is fast/reliable.
- **Blank-verso volumes** (Boyd Flushing): content on odd canvas, blank on even → printed pN = canvas
  12+2N, not a constant offset.
- **Ad-heavy volumes** (Brooklyn business dirs, Polk, Trow): the residential A-listing sits *behind* a
  large advertising + business-directory block — the listing start can be canvas 150–250, not the front.

## DONE — 13 / 42 (committed d2662ea)
| volume | id | start(p) | key(p) | offset | legend / note |
|---|---|---|---|---|---|
| Boyd Flushing 1890 | `flushingnewyorkc00boyd` | 1 | none | (blank-verso) | simple village fmt |
| Ogden 1839 | `brooklyndirector00ogde` | 3 | 3 | +6 | `*`=colored; h/n/c/opp |
| Reynolds W'burgh 1852 | `micro_IABROOKLYN_0046` | 15 | none | −2 | N.Y. h.=commuter |
| Spooner 1826 | `micro_IABROOKLYN_0005` | 5 | 5 | −1 | h/n/c |
| Brooklyn 1840/41 | `micro_IABROOKLYN_0017` | 5 | 5 | +2 | `*`=colored; h/n/c/op/b |
| Rode 1854/55 | `newyorkcitydirec00rode` | 25 | 25 | −1 | rich NYC abbrevs; **REVIEW** |
| Hodge 1790 | `nypl/614e2e50…e971` | 5 | none | +7 | register era, no key |
| Trow 1865/66 | `nypl/4b119360…9131` | 24 | 24 | 0 | key on A-start page |
| Trow 1884/85 | `nypl/4b69a410…a570` | 17 | 17 | +2 | key on A-start page |
| Trow 1913/14 | `nypl/4bfc3730…db31` | 17 | 17 | +7 | full-page abbrevs |
| Polk 1917 | `nypl/4c08ab00…ec38` | 229 | none | −2 | NO key page (Polk pattern) |
| Duncan/McComb 1794 | `nypl/dc1b4800…cf90` | 1 | none | +15 | register era, do.=ditto |
| Groot & Elston 1845/46 | `nypl/5ba77660…3427` | 1 | 1 | +14 | Doggett/Rode legend family |

**Style cards:** new `rode_manhattan_1850s`, `reynolds_williamsburgh_1850s`, `hodge_newyork_1790`;
enriched `ogden_brooklyn_1830s` (offset), `spooner_brooklyn_1840s` (1826+1840 legends),
`trow_manhattan_1890s` (1865/1884/1913 coverage table).

## Patterns discovered (generalize across the panel)
- **Trow:** ABBREVIATIONS block is always **on** the A-listing-start page → `key_page = start_page`.
- **Polk:** **no dedicated key page**; the alpha section just begins; conventions are standard Polk
  (h=home, r=rear, bds=boards, wid=widow) and ditto-heavy. Listing starts deep (~printed p229+).
- **Early NY (1786–1820):** no key page (era-typical); `do.`=ditto, comma-after-surname, relations
  spelled out ("corner of"); long almanac/register/city-description front matter precedes the listing.
- **Mid-century NYC (Doggett / Rode / Groot & Elston):** share one abbreviations legend family
  (`al/b/c/ct/e=east river/ex/frwrg/h/la/mer/mkr/manf/n.r=north river/op/pl/shpg/sq/ter`) — all
  "late Doggett" lineage. A single style layer can serve the cohort.

## Data-quality flag (REVIEW)
- **Rode `newyorkcitydirec00rode`:** title page (canvas 17) reads **"for 1854–1855, Thirteenth
  Publication, Chas R. Rode late Doggett & Rode"** and the listing is **2-column** → master
  `year=1851, column_count=1` are both wrong; the gold set labeled `rode1851` is mislabeled by ~3 yrs.
  Recorded as a `REVIEW:` note (not overwritten) — decide whether to relabel the gold set.

## REMAINING — 29 volumes, by cohort
**Mechanical (delegated to subagents 2026-06-29 — mostly "no key page, just start+offset"):**
- *Cohort A — early-NY faded NYPL:* Duncan/Greenleaf 1791 `f554e950…b4cf`, Elliot 1812
  `e9592bb0…f2a6`, Elliot&Crissy 1811 `7cd3acc0…12ab`, Long 1814 `6d811c30…6f98` (listing deep, >c29),
  Longworth 1818/19 `69fdfa80…e574`, Low/Buell/Bull 1796 `2dfca400…7dee`, Franks/Kollock 1786
  `b14662b0…2a18` (listing ~c28, has card).
- *Cohort B — IA early + Doggett:* Duncan 1794 `newyorkdirectory00dunc`, Franks 1786
  `newyorkdirectory00fran_0`, Mercein 1820 `merceinscitydire00merc` (card exists), durst 1910
  `newyorkdirectory00durs` (also needs publisher ID), Doggett 1846 `doggettsnewyorkc1846dogg`,
  Doggett 1850/51 `nypl/4adf9ec0…03ad` (start=21 already).

**Deep scans (kept inline — need offset/data-quality judgment):**
- *Brooklyn ad-heavy:* Hearnes 1852 `micro_IABROOKLYN_0030`, Smith 1854/55/56 `micro_IABROOKLYN_0033/
  0034/0036`, Lain 1876 `1876BPL` (title c16), Hope&Henderson 1856 `micro_IABROOKLYN_0035` (offset+31).
- *Polk A-starts:* 1920/21 `4c11d740…5877` (start=201), 1925 `bf529e00…6597`, 1933×3 `c2afe390…72be` /
  `bc958330…d037` / `e9621e80…ce16`, M&B 1931 `b97ce630…0b6f`.
- *Other:* Trow 1907 (IA, part 2) `trowsgeneraldir1907p2trow`, Upington 1906 `brooklynnewyorkc19062geor`,
  Brooklyn 1912 `brooklynnewyor1912p3broo`, loc Spooner `loc/01015253` (partial scan — note only).

## How to resume
Process a volume with the recipe above → write to `master_directories.csv` (printed page in columns,
canvas+offset+legend in notes) → create/extend the matching `data_prep/style_profiles/*.md` card →
commit. Re-run baseline tally any time:
`python3 -c "import csv;rows=list(csv.DictReader(open('data_prep/master_directories.csv')));print('key',sum(1 for r in rows if r['key_page'].strip()),'offset',sum(1 for r in rows if r['page_offset'].strip()),'start',sum(1 for r in rows if r['start_page'].strip()))"`
(baseline 2026-06-29 post-13: key 10, offset 40, start 90 / 449).
