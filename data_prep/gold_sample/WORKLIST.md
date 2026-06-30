# Gold-creation worklist

41 representative volumes selected from `master_directories.csv`.
Work top-to-bottom; check each off as its `gold.jsonl` lands in `data/`.

> **Removed 2026-06-29:** `ia/newyorkdirectory00durs` — front-matter sampling found it is an
> illustrated NYC **guidebook**, not a city directory (no persons listing anywhere, no readable title
> page; IA lists publisher "not identified"). Dropped from the panel. See its `master_directories.csv`
> notes. Panel is now **41**.

**Depth:** aim ~40 gold lines per volume; go deeper (~100) on the **14 `deep`-flagged** rows below (Lain's synth→real gap + column-transition publishers, where layout change breaks the model). Pass the target to the editor with `--max-lines`.

## Run once — sample pages for the whole set
```bash
PY=/Users/joshhadro/github/directory-pipeline/.venv/bin/python
cd /Users/joshhadro/github/directory-pipeline
$PY sources/sample_directories.py "/Users/joshhadro/github/city-directory-extraction/data_prep/gold_sample/worklist.csv" --front 20 -k 2 --width 1800
```

## Then per volume — OCR + build the editor
```bash
# surya needs the gpu env (uv sync --extra gpu); see VISUAL_SAMPLING_HANDOFF.md
$PY pipeline/run_surya_ocr.py output/<slug>            # 1) line OCR + bboxes
$PY ../city-directory-extraction/data_prep/make_gold_tool.py \
      output/<slug> -o gold_<slug>.html --max-lines 40   # use the row's target below
# 3) open gold_<slug>.html, correct fields, Export -> drop in city-directory-extraction/data/
# 4) validate:  python3 data_prep/validate_gold.py data/gold_<slug>.jsonl
```

## Volumes

| ☐ | depth | target | source/id | publisher | year | col | borough | stratum / why |
|---|---|---|---|---|---|---|---|---|
| ☐ | std | ~40 | `ia/flushingnewyorkc00boyd` | Boyd | 1890 | 1 | Queens | publisher=Boyd · column_count=1 |
| ☐ | std | ~40 | `ia/doggettsnewyorkc1846dogg` | Doggett | 1846 | 2 | Manhattan | publisher=Doggett · column_count=2 |
| ☐ | std | ~40 | `nypl/4adf9ec0-317a-0134-03ad-00505686a51c` | Doggett's | 1850/51 | 2 | Manhattan | publisher=Doggett's · column_count=2 |
| ☐ | std | ~40 | `ia/newyorkdirectory00dunc` | Duncan | 1794 | 1 | Manhattan | publisher=Duncan · column_count=1 |
| ☐ | std | ~40 | `nypl/f554e950-81ae-0134-b4cf-00505686a51c` | Duncan/Greenleaf | 1791 | 1 | Manhattan | publisher=Duncan/Greenleaf · column_count=1 |
| ☐ | std | ~40 | `nypl/dc1b4800-81b3-0134-cf90-00505686a51c` | Duncan/McComb | 1794 | 1 | Manhattan | publisher=Duncan/McComb · column_count=1 |
| ☐ | std | ~40 | `nypl/e9592bb0-5d82-0134-f2a6-00505686a51c` | Elliot | 1812 | 1 | Manhattan | publisher=Elliot · column_count=1 |
| ☐ | std | ~40 | `nypl/7cd3acc0-5d7f-0134-12ab-00505686a51c` | Elliot & Crissy | 1811 | 1 | Manhattan | publisher=Elliot & Crissy · column_count=1 |
| ☐ | std | ~40 | `ia/newyorkdirectory00fran_0` | Franks | 1786 | 1 | Manhattan | publisher=Franks · column_count=1 |
| ☐ | std | ~40 | `nypl/b14662b0-81a8-0134-2a18-00505686a51c` | Franks/Kollock | 1786 | 1 | Manhattan | publisher=Franks/Kollock · column_count=1 |
| ☐ | std | ~40 | `nypl/5ba77660-5dac-0134-3427-00505686a51c` | Groot & Elston | 1845/46 | 1 | Manhattan | publisher=Groot & Elston · column_count=1 |
| ☐ | std | ~40 | `ia/micro_IABROOKLYN_0030` | Hearnes | 1852/53 | 1 | Brooklyn | publisher=Hearnes · column_count=1 |
| ☐ | std | ~40 | `nypl/614e2e50-81ad-0134-e971-00505686a51c` | Hodge/Allen | 1790 | 1 | Manhattan | publisher=Hodge/Allen · column_count=1 |
| ☐ | std | ~40 | `ia/micro_IABROOKLYN_0035` | Hope & Henderson | 1856/57 | 2 | Brooklyn | publisher=Hope & Henderson · column_count=2 |
| ☐ | **deep** | ~100 | `ia/1876BPL` | Lain | 1876 | 2 | Brooklyn | synth→real gap (Lain) |
| ☐ | std | ~40 | `nypl/6d811c30-5d84-0134-6f98-00505686a51c` | Long | 1814 | 1 | Manhattan | publisher=Long · column_count=1 |
| ☐ | std | ~40 | `nypl/69fdfa80-5d88-0134-e574-00505686a51c` | Longworth | 1818/19 | 1 | Manhattan | publisher=Longworth · column_count=1 |
| ☐ | std | ~40 | `nypl/2dfca400-81bd-0134-7dee-00505686a51c` | Low/Buell/Bull | 1796 | 1 | Manhattan | publisher=Low/Buell/Bull · column_count=1 |
| ☐ | std | ~40 | `nypl/b97ce630-644a-0137-0b6f-0fb82113de91` | Manhattan & Bronx Directory Co. | 1931 | 4 |  | publisher=Manhattan & Bronx Directory Co. · column_count=4 |
| ☐ | std | ~40 | `ia/merceinscitydire00merc` | Mercein | 1820 | 1 | Manhattan | publisher=Mercein · column_count=1 |
| ☐ | std | ~40 | `ia/brooklyndirector00ogde` | Ogden | 1839 | 1 | Brooklyn | publisher=Ogden · column_count=1 |
| ☐ | **deep** | ~100 | `nypl/4c08ab00-317a-0134-ec38-00505686a51c` | Polk | 1917 | 5 | Manhattan | col-transition (2→3→4→5→6) |
| ☐ | **deep** | ~100 | `nypl/bf529e00-6449-0137-6597-6bbbb43fc75b` | Polk | 1925 | 6 |  | col-transition (2→3→4→5→6) |
| ☐ | **deep** | ~100 | `nypl/c2afe390-6447-0137-72be-4f41c312305b` | Polk | 1933/34 | 4 |  | col-transition (2→3→4→5→6) |
| ☐ | **deep** | ~100 | `nypl/bc958330-63af-0137-d037-03db0a2a574b` | Polk | 1933/34 | 2 | Staten Island | col-transition (2→3→4→5→6) |
| ☐ | **deep** | ~100 | `nypl/e9621e80-63b6-0137-ce16-0cdb3adbb8ea` | Polk | 1933/34 | 3 | Brooklyn | col-transition (2→3→4→5→6) |
| ☐ | std | ~40 | `nypl/4c11d740-317a-0134-5877-00505686a51c` | Polk/Trow | 1920/21 | 5 | Manhattan | publisher=Polk/Trow · column_count=5 |
| ☐ | std | ~40 | `ia/micro_IABROOKLYN_0046` | Reynolds | 1852 | 1 | Brooklyn | publisher=Reynolds · column_count=1 |
| ☐ | std | ~40 | `ia/newyorkcitydirec00rode` | Rode | 1851 | 1 | Manhattan | publisher=Rode · column_count=1 |
| ☐ | **deep** | ~100 | `ia/micro_IABROOKLYN_0033` | Smith | 1854 | 1 | Brooklyn | col-transition (1→2) |
| ☐ | **deep** | ~100 | `ia/micro_IABROOKLYN_0034` | Smith | 1855 |  | Brooklyn | col-transition (1→2) |
| ☐ | **deep** | ~100 | `ia/micro_IABROOKLYN_0036` | Smith | 1856 | 2 | Brooklyn | col-transition (1→2) |
| ☐ | **deep** | ~100 | `loc/01015253` | Spooner |  | 2 | Brooklyn | col-transition (1→2) |
| ☐ | **deep** | ~100 | `ia/micro_IABROOKLYN_0005` | Spooner | 1826 | 1 | Brooklyn | col-transition (1→2) |
| ☐ | **deep** | ~100 | `nypl/4b69a410-317a-0134-a570-00505686a51c` | Trow | 1884/85 | 2 | Manhattan | col-transition (2→3→4) |
| ☐ | **deep** | ~100 | `ia/trowsgeneraldir1907p2trow` | Trow | 1907 | 3 |  | col-transition (2→3→4) |
| ☐ | **deep** | ~100 | `nypl/4bfc3730-317a-0134-db31-00505686a51c` | Trow | 1913/14 | 4 | Manhattan | col-transition (2→3→4) |
| ☐ | std | ~40 | `nypl/4b119360-317a-0134-9131-00505686a51c` | Trow/Wilson | 1865/66 | 2 | Manhattan | publisher=Trow/Wilson · column_count=2 |
| ☐ | std | ~40 | `ia/brooklynnewyorkc19062geor` | Upington | 1906 | 2 | Brooklyn | publisher=Upington · column_count=2 |
| ☐ | std | ~40 | `ia/micro_IABROOKLYN_0017` |  | 1840/41 | 1 | Brooklyn | publisher=unknown · column_count=1 |
| ☐ | std | ~40 | `ia/brooklynnewyor1912p3broo` |  | 1912 | 2 | Brooklyn | publisher=unknown · column_count=2 |
