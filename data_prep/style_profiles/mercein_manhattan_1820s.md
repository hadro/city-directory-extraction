# Mercein — Mercein's City Directory, New-York, 1820

**Representative volume:** `ia/merceinscitydire00merc` — *Mercein's city directory, New-York register, and almanac, for the forty-fifth year of American independence…* (William A. Mercein, New York, 1820). Visually sampled 2026-06-23 (canvases 138, 320).

**Scope:** Residential + business persons directory, Manhattan (KEEP shape). `column_count = 1`. Like other early-19th-c. volumes it bundles an **almanac / register** section (duties, banks, officials) before the persons listing — that section is NOT a training target. Building the real-OCR eval gold from this volume (`data/mercein1820_eval.jsonl`).

## Entry format

`Surname Firstname[,] [occupation] [number] Street [h number Street]`

- Loose punctuation: a comma usually follows the name, occupation/address commas are inconsistent.
- **Two addresses are common** — a work address then an `h`-marked home: `Morss Amos, mer. 161 Broadway h 46 Dey` → address `161 Broadway`, home_address `h 46 Dey`.
- Many entries have **no occupation**: `Brooks James, 520 Pearl`.
- **Locality-only addresses** (no number) occur: `Grand C. hook`, `Broome n Norfolk`.
- **Firm entries** lead with the firm name + principal and are `is_business=True`: `Brooks and Co. Thomas, tanyard, Collect n Pearl`.

Verbatim samples:
```
Brooks James, 520 Pearl
Morss Amos, mer. 161 Broadway h 46 Dey
Brooks and Co. Thos. leather st. 60 Vesey h 58 Barclay
Brooks and Co. Thomas, tanyard, Collect n Pearl
Broughton John, tallow chandler Grand C. hook
Brouer Adolphus, cartman Broome n Norfolk
```

## Abbreviations / localities (inferred — no explicit key page yet)

- `mer.` / `merch.` — merchant
- `h` — house (home-address marker; the second, `h`-marked address → `home_address`)
- `n` — near (`Broome n Norfolk` = Broome St near Norfolk; `Collect n Pearl`)
- `C. hook` — **Corlears Hook** (East River locality, Lower East Side; trades like tallow chandlers clustered there)
- `st.` — store, in trade phrases (`leather st.` = leather store) — *tentative; confirm with more samples*
- `and Co.` — firm marker → `is_business=True`
- occupations seen (keep verbatim, no expansion): `tallow chandler`, `tanyard`, `cartman`, `leather st.`

Field separator: comma (inconsistent). Per the gold contract, expansion of these (`C. hook`→Corlears Hook, `mer.`→merchant) is a downstream step — keep verbatim in gold.

## Status

First pass from 2 sampled listing pages — extend the abbreviation/locality list as more entries are labeled. `page_offset`/`key_page` not measured.
