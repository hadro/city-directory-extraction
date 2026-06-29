# Rode — The New-York City Directory, 1854–55

**Representative volume:** `ia/newyorkcitydirec00rode` — *The New-York City Directory, for 1854–1855.
Thirteenth Publication. Established in 1842. New-York: Charles R. Rode, 161 Broadway, late Doggett &
Rode.* Visually sampled 2026-06-29 (front matter + listing-start canvas 24/printed p.25).

> **⚠️ Master-list correction (REVIEW):** the master row tags this volume `year=1851, column_count=1`.
> The **title page (canvas 17) reads "for 1854–1855"** and the listing is plainly **2-column**, so both
> are wrong; the gold set labeled `rode1851` is mislabeled by ~3 years. Treat as **Rode 1854–55, col 2**.

**Scope:** Residential + business persons directory, **Manhattan** (KEEP shape). `column_count = 2`.
Standard mid-century NYC structure: front advertising block (canvases 0–15) → title page (c17) → "To the
Public" preface (c19) → almanac/calendar (c19–20) → **persons listing begins at printed p.25 (canvas 24)**.
`page_offset` ≈ **−1** in the front region (canvas 24 = printed p.25; drifts to +8 by p.291).

## Key page — ABBREVIATIONS (canvas 24, head of the A-listing) — GROUND TRUTH

Quoted verbatim:

> NOTICE. The names received too late for regular insertion on the page following names.
> **ABBREVIATIONS.** al. for alley, b. between, bldgs buildings, c. corner, com. commission, ct. court,
> e. east river, ex. exchange, frwrg. forwarding, h. house, la. lane, mer. merchant, mkr. maker,
> manf. manufacturer, n.r. north river, op. opposite, pl. place, shpg. shipping, sq. square.

- The **`e.`/`n.r.` = east river / north river** dock-side address abbreviations are the distinctive
  NYC-commercial markers of this era — a richer address vocabulary than the Brooklyn `n/c/r` grammar.
- `h.` = house → the **home address** (`home_address` when a work address also appears).
- All marks stay **verbatim** in gold per the contract (no expansion of `h.`→house, `c.`→corner, etc.).

## Entry format

`Surname Given[, occupation] [work-address][, h. home-address[, Brooklyn]]`

Verbatim samples (canvas 24, A-start):
```
Aackbrunsch Ferdinand, printer 162 E 16th
Aaronson John, clerk 192 W 17th
Abbott Benjamin N. lawyer, 129 Nassau, h 154 Adams, Brooklyn   [work + h home, cross-river commuter]
Abbott Charles, cooper 69 Wall, h 783 Broadway
```

- Two addresses → first is workplace, `h` home (→ `home_address`); a `Brooklyn`/other-city tag on the
  home address marks a cross-river commuter.
- Firms (`& Co.`) → `is_business=True`.

## Status

First pass from front matter + the listing-start page. Legend is the volume's printed ground truth.
Carries the **master-list year/column correction** above — surface before using `rode1851` gold labels.
