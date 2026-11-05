# Reynolds — Williamsburgh City Directory, 1852

**Representative volume:** `ia/micro_IABROOKLYN_0046` — *Reynolds' Williamsburgh City Directory and
Business Advertiser, for 1852. Third Annual Publication. Samuel & T. F. Reynolds.* (microfilm scan).
Visually sampled 2026-06-29 (front matter + listing-start canvas 13 / printed p.15).

**Scope:** Residential + business persons directory, **Williamsburgh** (then an independent city;
consolidated into Brooklyn in 1855 — KEEP shape, Brooklyn dialect). `column_count = 1`.
Ad-heavy front: a title page (canvas 4) is followed by a wall of advertisements and reference matter
(Post Office, banks, "Statistics of the Population of Williamsburgh", Publishers' Notice) before the
listing. **Persons listing begins at printed p.15 (canvas 13)**, right after the Collegiate Institute
ad. `page_offset` = **−2** (canvas 13 = printed p.15).

## Key page

**No explicit "Abbreviations" legend page found** in the sampled front matter — the listing begins
directly after the ads with no head-note (unlike Ogden / the Spooner-era Brooklyn volumes). The
abbreviation grammar is inferred from the entries and follows the standard Brooklyn/Williamsburgh
street-relation conventions.

**But the run does print one, and `*` = colored (read 2026-11-04, PIPELINE #37).** The 1850-51
volume (micro 0044, leaf 16) heads its listing with "NOTE.—Names having a * are those of colored
people. *Abbreviations.*—av. stands for avenue, b. for between, c. for corner, carp. for
carpenter, com. for commission, h. for house, manf. for manufacturer, lab. for laborer, mert. for
merchant, mkr. for maker, n. for near, op. for opposite, N. for north, and S. for [...]", and the
1849-50 Williamsburgh directory (micro 0043, leaf 4) prints the same note. 0045, 0047 and 0048
start mid-listing on the film; 0046's starred lines (`*Merritt John, gasfitter, Marshall n.
Leonard`, `*Jackson Percy, cook`) are the same households as 0045's. So the `*` is the Ogden /
Spooner / Hearnes sense, a race marker (`race_designation` = `*`), and **not** the Eastern
District sense of Hope & Henderson 1856, although Williamsburgh became the Eastern District.
The sidecars' `book_says.race_marker` records it (data_prep/survey_race_markers.py).

## Entry format

`Surname Given, occupation, [N.Y. h.] address`

Verbatim samples (canvas 13, listing start):
```
Acheson Joseph, physician, 6 North 3d
Adams Dan'l, leather business, N.Y. h. 140 South 8th    [works in NY, h home in W'burgh]
Adams James, carpenter, 76 Tenth
Adams John, tailor, 99 Montrose avenue
Aitken Caroline, widow of Alexander, 58 Remsen          [Alexander = husband -> spouse_name]
```

- **`N.Y. h.`** = the resident works/trades across the river in New York (Manhattan) and **h**ouses in
  Williamsburgh — the cross-river commuter notation (cf. Brooklyn `N Y` = works-in-Manhattan).
- Comma after the given name AND after the occupation (more consistent punctuation than Ogden).
- Widows: `widow of Alexander` → Alexander is the husband (→ `spouse_name`).
- Numbered cross streets are common (`North 3d`, `South 8th`, `Tenth`) — Williamsburgh's grid.

## Abbreviations / localities

`h.` house · `n.` near · `c.` corner · `N.Y.` works-in-New-York (commuter). All verbatim in gold.

## Status

First pass from front matter + the listing-start page. No printed key page; legend inferred.
`page_offset` −2 measured at the listing start.
