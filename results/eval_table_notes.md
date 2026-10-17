---

## Caveats on cells above

`eval/results_table.py` appends this file verbatim, so a note here survives the next regeneration.

**minneapolis — most of the row is measured against gold that no longer exists (2026-10-17).**
Minneapolis 1900 prints a surname once and drops it from the entries beneath, and
`harvest_minneapolis.py` had resolved that inherited surname into the `name` field — asking the
model for a word absent from its input, against the contract that a repeat mark is emitted
verbatim and expanded downstream. 95 of 230 rows were affected and scored a structural 0%.

The gold was corrected (the surname stripped to what the page prints, the dropped one kept in
`context.inherited_surname`). **Only the four models with stored predictions could be re-scored:**

| | before | after |
|---|---|---|
| v7 | 31.3 | **63.0** |
| 2b-100k | 34.8 | **65.7** |
| 4b-100k | 35.2 | **64.8** |
| v8-250k | 21.3 | **45.7** |

Every other minneapolis cell — `v-fixed`, `v2`, `v3`, `v4`, `v5`, `v5-torch`, `v6` — predates
the correction and is **not comparable** with the four above. Read down that row only among
cells of the same vintage, or re-run the older models to replace them. No other eval set is
affected; the rest of the table is on one footing.
