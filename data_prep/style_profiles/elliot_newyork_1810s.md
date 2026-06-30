# Elliot — New-York Directory, 1811–1812

**Representative volumes:**
- `nypl/7cd3acc0-5d7f-0134-12ab-00505686a51c` — *Elliot & Crissy's New-York Directory, for the Year
  1811* (36th of American independence).
- `nypl/e9592bb0-5d82-0134-f2a6-00505686a51c` — *Elliot's improved New York **Double Directory**…
  Printed and sold by William Elliot, at the Tontine Coffee-House. 1812.*

Visually sampled 2026-06-29.

**Scope:** Residential persons directory, Manhattan (KEEP shape). Long front matter (commercial laws,
duties/rates tables, alphabetical list of streets, register of officials/societies) precedes the
listing — the persons section starts deep:
- 1811: listing A-start **printed p.90 = canvas 95**, `page_offset` **+5**. `column_count = 1`.
- 1812: listing A-start **printed p.41 = canvas 36**, `page_offset` **−5**. `column_count = 2`.

> **⚠️ Master-list correction:** the master tagged the 1812 "Double Directory" as `column_count=1`;
> the persons listing is clearly **2 columns** of names divided by a vertical rule (observed on
> canvases 36/37/38). Corrected to col=2. (The 1811 volume is genuinely 1-column.) The 1812 scan is
> water-damaged/torn through the front matter, but the listing pages are legible.

## Key page — explanation of marks (on the A-listing-start page) — GROUND TRUTH

Both volumes print the legend at the **head of the A-listing** (canvas 95 in 1811, canvas 36 in 1812).
Verbatim (1811; 1812 matches, with damage-reduced legibility):

> The word Street is always to be understood after the name, though not expressed, i.e. Pearl, is
> Pearl-street, &c. The lanes, alleys, slips, &c. are always named. **h. for house; n. for near;
> c. for corner.**

- This is the **"street-implied" convention** — a bare number after a name means *that street*; only
  non-street locales (lanes/alleys/slips) are spelled out. Longworth 1818/19 states the same rule
  ([longworth_manhattan_1830s.md]); it's the Manhattan house-style of the 1810s.
- `h.` = house (home address) · `n.` = near · `c.` = corner. All verbatim in gold.

## Entry format

`Surname Given[, occupation] [number][ street-relation]`

Verbatim samples:
```
Aaron Henry, 35 Murray                          (1811; "Murray" = Murray-street, implied)
Abbatt Moses, morocco dryer. Orange c. Cross    (1811; c. = corner)
Ackerman John, accountant 57 N. Moore           (1811)
Allen Joseph, hair dresser 16 frankfort         (1812)
Adams John, sailmaker 24 Pump                   (1812)
```

- Street name implied after the house number unless a lane/alley/slip is named.
- Firms (`& Co`) → `is_business=True`.

## Genre
Residential persons directory — Manhattan (KEEP shape). Publisher: William Elliot (1811 w/ Crissy).
Same 1810s "street-implied" house-style as Longworth 1818/19.
