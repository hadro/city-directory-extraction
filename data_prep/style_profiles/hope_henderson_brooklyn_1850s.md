# Hope & Henderson — (Consolidated) Brooklyn City Directory, 1856–57

**Representative volume:** `ia/micro_IABROOKLYN_0035` — *Hope & Henderson's (Consolidated) Brooklyn City Directory for 1856–1857* (microfilm scan). Visually sampled 2026-06-25 (front matter, listing-start canvas 38, body canvases 205/479).

**Scope:** Residential + business persons directory, **Brooklyn** (KEEP shape). `column_count = 2`. `page_offset` +31 @ leaf 205 / printed p.174. Dense 2-column micro scan, good contrast.

## Key page — abbreviations + marks (canvas 0038, top of the alphabetical body) — GROUND TRUTH

Title block: *"Hope & Henderson's (Consolidated) Brooklyn City Directory. 1856–7."* with:

> **NOTE.—Names marked thus `*` are persons residing or doing business in the Eastern District.**
>
> ABBREVIATIONS, ETC.—al. alley; av. avenue; **col'd colored**; com. commission; cor./c. corner;
> ct. court; E. east; ex. exchange; forwd. forwarding; h. house; la. lane; manf. manufacturing;
> mer. merchant; mkr. maker; N. north; n. near; opp. opposite; pl. place; rd. road; S. south;
> sq. square; st. street; W. west; Rev. clergyman.
>
> (Also: "Names received too late for regular insertion follow immediately after the general
> alphabetical arrangement.")

### ⚠️ Volume-specific marks (do NOT carry over from other volumes)

- **`*` (leading) = Eastern District** (Williamsburgh/ED Brooklyn) — a *geographic* marker, **NOT
  race**. The 8-field schema has no district field, so **drop the `*`** (remove from `name`, store
  nowhere). race_designation stays empty for starred entries.
- **`col'd` = colored** → this is the race marker here → `race_designation` = `col'd` (verbatim).
- Contrast with Ogden 1839 Brooklyn, where `*` = colored. **Same symbol, different meaning — always
  read the volume's own key** (this is the cautionary case for that rule).
- `h` house · `n` near · `c`/`cor.` corner · `mer.` merchant · `Rev.` clergyman (→ title in `name`).

## Entry format

`[*]Surname First[,] [occupation] [number] Street [, N. Y.] [h. number Street]`

- Dense 2-column. Two-address common: a work address (often `, N. Y.` = Manhattan) + an `h.` Brooklyn
  home (`Hague Joseph, cutlery, 12 Gold, N. Y. h. …`). Bare-city work address (`New York`) → `address`.
- Role vs employer per the standard rule (`pastor of 1st Unitarian Church` → occ `pastor`, employer
  `1st Unitarian Church`).

Verbatim samples (canvas 38, A-listing):
```
*Abbey Horatio G. teacher, h. 56 Willow         [* = Eastern District, dropped; not race]
Abbott Charles W. clerk, h. 38 Gold
Abbott M. teacher, Maspeth av. n. Bushwick
Abeel Edwin S. sugarmaker, h. 116 Ewen
```

## Structure note (micro canvas order is messy)

Front: long **"Brooklyn Directory Advertiser"** ad section (canvas ~2–35), a **City Hall plate**
(canvas 36) + **City Hall office directory** (canvas 37), then the **alphabetical body starts canvas
38**. Canvas↔printed-page is non-monotonic on this microfilm — use the key at canvas 38, not canvas
arithmetic. Ads / City Hall directory are NOT persons-listing training targets.

## Status

Building `data/hopehenderson1856_eval.jsonl`. Per the gold contract, expansion of marks
(`n`→near, `col'd`→colored) is downstream — keep verbatim; the `*` Eastern-District mark is dropped
(no field).
