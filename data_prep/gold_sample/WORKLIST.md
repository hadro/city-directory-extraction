# Gold-creation worklist

42 representative volumes selected from `master_directories.csv`.
Work top-to-bottom; check each off as its `gold.jsonl` lands in `data/`.

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
      output/<slug> -o gold_<slug>.html                 # 2) cols auto-read from master CSV
# 3) open gold_<slug>.html, correct fields, Export -> drop in city-directory-extraction/data/
# 4) validate:  python3 data_prep/validate_gold.py data/gold_<slug>.jsonl
```

## Volumes

| ☐ | source/id | publisher | year | col | borough | stratum |
|---|---|---|---|---|---|---|
| ☐ | `ia/flushingnewyorkc00boyd` | Boyd | 1890 | 1 | Queens | publisher=Boyd · column_count=1 |
| ☐ | `ia/doggettsnewyorkc1846dogg` | Doggett | 1846 | 2 | Manhattan | publisher=Doggett · column_count=2 |
| ☐ | `nypl/4adf9ec0-317a-0134-03ad-00505686a51c` | Doggett's | 1850/51 | 2 | Manhattan | publisher=Doggett's · column_count=2 |
| ☐ | `ia/newyorkdirectory00dunc` | Duncan | 1794 | 1 | Manhattan | publisher=Duncan · column_count=1 |
| ☐ | `nypl/f554e950-81ae-0134-b4cf-00505686a51c` | Duncan/Greenleaf | 1791 | 1 | Manhattan | publisher=Duncan/Greenleaf · column_count=1 |
| ☐ | `nypl/dc1b4800-81b3-0134-cf90-00505686a51c` | Duncan/McComb | 1794 | 1 | Manhattan | publisher=Duncan/McComb · column_count=1 |
| ☐ | `nypl/e9592bb0-5d82-0134-f2a6-00505686a51c` | Elliot | 1812 | 1 | Manhattan | publisher=Elliot · column_count=1 |
| ☐ | `nypl/7cd3acc0-5d7f-0134-12ab-00505686a51c` | Elliot & Crissy | 1811 | 1 | Manhattan | publisher=Elliot & Crissy · column_count=1 |
| ☐ | `ia/newyorkdirectory00fran_0` | Franks | 1786 | 1 | Manhattan | publisher=Franks · column_count=1 |
| ☐ | `nypl/b14662b0-81a8-0134-2a18-00505686a51c` | Franks/Kollock | 1786 | 1 | Manhattan | publisher=Franks/Kollock · column_count=1 |
| ☐ | `nypl/5ba77660-5dac-0134-3427-00505686a51c` | Groot & Elston | 1845/46 | 1 | Manhattan | publisher=Groot & Elston · column_count=1 |
| ☐ | `ia/micro_IABROOKLYN_0030` | Hearnes | 1852/53 | 1 | Brooklyn | publisher=Hearnes · column_count=1 |
| ☐ | `nypl/614e2e50-81ad-0134-e971-00505686a51c` | Hodge/Allen | 1790 | 1 | Manhattan | publisher=Hodge/Allen · column_count=1 |
| ☐ | `ia/micro_IABROOKLYN_0035` | Hope & Henderson | 1856/57 | 2 | Brooklyn | publisher=Hope & Henderson · column_count=2 |
| ☐ | `ia/1876BPL` | Lain | 1876 | 2 | Brooklyn | publisher=Lain · column_count=2 |
| ☐ | `nypl/6d811c30-5d84-0134-6f98-00505686a51c` | Long | 1814 | 1 | Manhattan | publisher=Long · column_count=1 |
| ☐ | `nypl/69fdfa80-5d88-0134-e574-00505686a51c` | Longworth | 1818/19 | 1 | Manhattan | publisher=Longworth · column_count=1 |
| ☐ | `nypl/2dfca400-81bd-0134-7dee-00505686a51c` | Low/Buell/Bull | 1796 | 1 | Manhattan | publisher=Low/Buell/Bull · column_count=1 |
| ☐ | `nypl/b97ce630-644a-0137-0b6f-0fb82113de91` | Manhattan & Bronx Directory Co. | 1931 | 4 |  | publisher=Manhattan & Bronx Directory Co. · column_count=4 |
| ☐ | `ia/merceinscitydire00merc` | Mercein | 1820 | 1 | Manhattan | publisher=Mercein · column_count=1 |
| ☐ | `ia/brooklyndirector00ogde` | Ogden | 1839 | 1 | Brooklyn | publisher=Ogden · column_count=1 |
| ☐ | `nypl/4c08ab00-317a-0134-ec38-00505686a51c` | Polk | 1917 | 5 | Manhattan | publisher=Polk · column_count=5 |
| ☐ | `nypl/bf529e00-6449-0137-6597-6bbbb43fc75b` | Polk | 1925 | 6 |  | publisher=Polk · column_count=6 |
| ☐ | `nypl/c2afe390-6447-0137-72be-4f41c312305b` | Polk | 1933/34 | 4 |  | publisher=Polk · column_count=4 |
| ☐ | `nypl/bc958330-63af-0137-d037-03db0a2a574b` | Polk | 1933/34 | 2 | Staten Island | publisher=Polk · column_count=2 |
| ☐ | `nypl/e9621e80-63b6-0137-ce16-0cdb3adbb8ea` | Polk | 1933/34 | 3 | Brooklyn | publisher=Polk · column_count=3 |
| ☐ | `nypl/4c11d740-317a-0134-5877-00505686a51c` | Polk/Trow | 1920/21 | 5 | Manhattan | publisher=Polk/Trow · column_count=5 |
| ☐ | `ia/micro_IABROOKLYN_0046` | Reynolds | 1852 | 1 | Brooklyn | publisher=Reynolds · column_count=1 |
| ☐ | `ia/newyorkcitydirec00rode` | Rode | 1851 | 1 | Manhattan | publisher=Rode · column_count=1 |
| ☐ | `ia/micro_IABROOKLYN_0033` | Smith | 1854 | 1 | Brooklyn | publisher=Smith · column_count=1 |
| ☐ | `ia/micro_IABROOKLYN_0034` | Smith | 1855 |  | Brooklyn | publisher=Smith · column_count=∅ |
| ☐ | `ia/micro_IABROOKLYN_0036` | Smith | 1856 | 2 | Brooklyn | publisher=Smith · column_count=2 |
| ☐ | `loc/01015253` | Spooner |  | 2 | Brooklyn | publisher=Spooner · column_count=2 |
| ☐ | `ia/micro_IABROOKLYN_0005` | Spooner | 1826 | 1 | Brooklyn | publisher=Spooner · column_count=1 |
| ☐ | `nypl/4b69a410-317a-0134-a570-00505686a51c` | Trow | 1884/85 | 2 | Manhattan | publisher=Trow · column_count=2 |
| ☐ | `ia/trowsgeneraldir1907p2trow` | Trow | 1907 | 3 |  | publisher=Trow · column_count=3 |
| ☐ | `nypl/4bfc3730-317a-0134-db31-00505686a51c` | Trow | 1913/14 | 4 | Manhattan | publisher=Trow · column_count=4 |
| ☐ | `nypl/4b119360-317a-0134-9131-00505686a51c` | Trow/Wilson | 1865/66 | 2 | Manhattan | publisher=Trow/Wilson · column_count=2 |
| ☐ | `ia/brooklynnewyorkc19062geor` | Upington | 1906 | 2 | Brooklyn | publisher=Upington · column_count=2 |
| ☐ | `ia/micro_IABROOKLYN_0017` |  | 1840/41 | 1 | Brooklyn | publisher=unknown · column_count=1 |
| ☐ | `ia/newyorkdirectory00durs` |  | 1910 |  | Manhattan | publisher=unknown · column_count=∅ |
| ☐ | `ia/brooklynnewyor1912p3broo` |  | 1912 | 2 | Brooklyn | publisher=unknown · column_count=2 |
