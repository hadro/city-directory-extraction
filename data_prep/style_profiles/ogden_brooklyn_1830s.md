# Ogden — Brooklyn Directory, 1839–40

**Representative volume:** `ia/brooklyndirector00ogde` — *Brooklyn Directory, for the years 1839–40. Compiled by Henry L. Ogden. Brooklyn: Arnold & Van Anden, Printers, 40 Fulton Street. 1839.* Visually sampled 2026-06-23 (front matter + canvases 0101, 0237).

**Scope:** Residential + business persons directory, **Brooklyn** (KEEP shape). `column_count = 1`. Short volume; the listing starts very early (≈ canvas 9 = printed p.1).

## Key page — explanation of marks (canvas 0009, top of p.1) — GROUND TRUTH

Quoted verbatim:

> **NOTE.—Names having an `*` are the names of colored people.** Abbreviations—h. stands for house, n. for near, c. for corner, op. for opposite, &c.

- **`*` (leading) → `race_designation`** — marks "colored" (Black) residents. This is the panel's first
  race-marked volume. Handle like Tulsa's `(c)`: **drop the `*` from `name`, store `*` verbatim in
  `race_designation`** (do NOT expand to "colored"); empty for unstarred entries.
  - ⚠️ **Volume-specific — do NOT generalize the `*`.** In **Hope & Henderson 1856** (also Brooklyn)
    the leading `*` means *Eastern District* (geographic, NOT race; dropped — no schema field), and
    colored is `col'd`. Same symbol, opposite meaning — always read each volume's own key page.
    See `hope_henderson_brooklyn_1850s.md`.
- `h` = house · `n` = near · `c` = corner · `op` = opposite (all verbatim in gold).

## Entry format

`[*]Surname First[,] [occupation] [number] Street [c/n cross-street]`

- Single address per entry; localities/cross-streets via `n` (near) / `c` (corner): `Jay c Myrtle`,
  `Livingston n Smith`, `Jay n Concord`.
- Widows per the standard rule: `widow of John` → John is husband (→ spouse_name); `widow Letitia` /
  `widow Henry` — *check whether the following name is the woman's own (→ name) or the husband*.
- Firms (`& Co`, `& Platt`) → `is_business=True`.

Verbatim samples (canvas 0009):
```
Abbot Daniel, 25 Front
Abbot John, merchant Livingston n Smith
*Abrams William, mariner 74 Jay              [* = colored -> race_designation "*"]
Acker widow Letitia, 263 Adams
Acker & Platt, carpenters, Jay c Myrtle      [firm -> is_business]
Adams Rosanna, widow of Hugh 247 John        [Hugh = husband -> spouse_name]
Akely Elizabeth widow of John, 88 Jackson
Adamson Samuel, tailor 40 Hicks
```

## Abbreviations / localities

`*` colored (race) · `h` house · `n` near · `c` corner · `op` opposite · `&c.` etc.
Field separator: comma (inconsistent — often dropped before occupation/address).

## Status

First pass from front matter + 2 listing pages; building `data/ogden1839_eval.jsonl`.
`page_offset`/`key_page` printed-number not measured (key note is at canvas 0009 = p.1).
Per the gold contract, expansion of marks (`*`→colored, `n`→near) is a downstream step — keep verbatim.
