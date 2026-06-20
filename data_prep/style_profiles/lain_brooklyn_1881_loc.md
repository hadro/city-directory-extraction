# Lain — Brooklyn Directory 1881 (LoC serial item)

**Source:** `loc/01015253` — LoC LCCN `01015253` is a **serial catalog record** for "The Brooklyn
city directory" spanning the Spooner → Lain → Brooklyn Directory Co. run, ~1800s–c.1912. The
specific volume available at `gdc:00531550882` is the **24th annual volume, for the year ending
May 1, 1881**, compiled and published by **Geo. T. Lain / Lain & Company, 213 Montague Street,
Brooklyn**. The master list row (`loc/01015253`) carries publisher=Spooner as the originating
publisher of the serial; the sampled volume is Lain. Visually sampled 2026-06-19.

## RESOLVED — this LoC item is a PARTIAL scan; no persons listing exists here

**Settled 2026-06-19 (full manifest pulled).** The LoC IIIF manifest for `gdc:00531550882`
resolves to **only 20 canvases total** — and all 20 are front matter + the classified business
section: title/preface/élite-directory insert (canvases 0–5), **Index to Advertisements**
(canvases 6–10), and **Index to Business Directory** pp. iii–vi (canvases 15–18, referencing
business pages up to 1411) + a **Business Register** advertiser page (canvas 20). There is **no
residential persons listing page anywhere in this digitization** — it is a ~20-leaf partial scan of
a ~1411-page volume. This is **not** a sampling problem (no `--front N` value will surface a persons
page that isn't digitized); the earlier "resample with `--front 5`" suggestion is therefore moot.

**Consequence:** a persons-listing profile cannot be built from the LoC source. `column_count=2` is
set in the CSV by inference from the confirmed Lain-1881 identity (identical era/publisher to
`lain_brooklyn_1880s.md`); `page_offset` and `key_page` are left blank (unmeasurable here). If a
persons profile for this exact volume is ever needed, find a fuller scan (IA/NYPL) of the Lain
1880-81 volume instead.

## Structure (canvas indices, 0-based, as sampled)
- Canvases 0–1: Worn cover + blank endpaper (physical artifact).
- Canvas 2: **Title page** — *The Brooklyn Directory for the Year Ending May 1st, 1881.*
  Compiled by Geo. T. Lain. Published by Lain & Company, 213 Montague Street, Brooklyn.
  Price $5.50. Press of Wynkoop & Hallenbeck. (Copyright registered 1880.)
- Canvas 3: Ad leaf (Lamb church furniture; Serrell patents; Francis Raas pharmacist, Brooklyn).
- Canvas 4: **PREFACE** — "twenty-fourth annual volume." Population/names-in-directory table
  1860–1880; 1880 entry: 62,036 names → compare 132,228 for the 1884/85 volume (huge growth).
  Date: "Brooklyn, June, 1880."
- Canvas 5: Insert — "BROOKLYN ÉLITE DIRECTORY, STREET CLASSIFIED — 20,000 Names of Householders
  from the best Streets of the City" (Lain & Co.). A separate premium product.
- Canvases 6–10: "INDEX TO ADVERTISEMENTS" (roman pp. vi–ix; 5 pages visible).
- Canvas 15: "INDEX TO BUSINESS DIRECTORY" (page iii of the business section index). Shows
  classified categories: Fire Brick (p.1281), Hair Dressers (p.1306), Hardware (p.1311), etc.
  Persons listing is NOT this section.

## Entry format
No persons listing page was captured in this sample. Based on publisher identity and era, the
format is expected to be the same as **`lain_brooklyn_1880s.md`** (Lain 1884/85):
- 2 columns, repeated full surname, `h` = home, `wid.` = widow, same abbreviation set.
- Reference that card for the complete abbreviations legend.

## LoC serial note
The LoC LCCN covers the full Brooklyn directory serial. Earlier volumes (Spooner, Hearnes,
Lain predecessors, ~1822–1860s) would have **different formats** — single column, fewer
abbreviations, possibly different publisher conventions. If you need to card a pre-1870 volume
from this serial, treat it independently (don't assume Lain-era format).

## Genre
Residential persons directory — Brooklyn (KEEP shape). Publisher of sampled volume: Lain & Co.
