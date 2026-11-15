# Lain's Brooklyn "Street and Avenue Directory": what an entry prints

Dated 2026-11-15. Volumes: 1869BPL, 1871BPL, 1875BPL (Lain & Co.). Source files are in
`data/addresses/work/guide_format/`. Every reading below was made from a 2x or 3x crop of the page image
(crop boxes are given in pixels of the full-size image, as x0-x1 / y0-y1), except where it says "OCR only".
`[?]` marks a character that is worn or smudged in the print; I did not guess a digit. A number written
without `[?]` was read clearly (or clearly enough that the neighbouring rows' sequence agrees).

Scratch files (not part of the repo): `/tmp/guide_crops/` (crops, `score.py`, `final.py`), `/tmp/crop.py`, `/tmp/crop3.py`.

## 1. What a guide entry is

### Layout

The guide is an alphabetical list of every street, avenue, place, lane, court and alley. Pages have a running
head "STREET DIRECTORY." and four narrow columns. One entry is:

1. **Heading, in bold, run in with a few lines of roman text**: the name, an optional "(E. D.)" (Eastern
   District), where the street starts, the two cross streets that bracket the start ("bet. X and Y"), the
   compass direction, and where it ends. Example (1869BPL_861, Court): "**Court**, from Fulton at City Hall
   sq., S. to Gowanus bay". Others: "Dean, from Court, bet. Pacific and Bergen, E. to City line";
   "Adelphi, from Flushing av., bet. Carlton av. and Clermont av., S. to Atlantic av."; "(one block)" for
   one-block streets. The heading is hyphen-wrapped over 2-4 lines ("Gow-/anus bay").
2. **The column header "Left. Rt."** in italics (Rt. = Right).
3. **One row per cross street, in the order you meet them walking from the "from" end to the "to" end.**
   The first row is the starting street (Court begins "Fulton") and the last row is the terminal
   (Court ends "Gowanus bay"). Every row has three cells: a **left-side number**, a **right-side number**,
   and the **name of the cross street** (the street that crosses or meets this one).

   Each number is the house number of the building at that corner on that side of the street under the
   heading. Rows are for crossings, not for houses: the guide lists every crossing, including those where
   nothing is built.

Other entry types: one-line cross-references, e.g. 1871 "Mill (See Garnet)", "Leonard (See Loraine)",
"Hudson av. (See Kingston)", "Powers (See 3d av.)", "Jefferson (See Spruce)". In 1875 a renamed street carries
"(late X)" in its heading, e.g. "Garnet (late Mill)", "Lorraine (late Leonard)", "Hamburg (late Johnson)".

### The printed explanatory note, 1869 and 1871

Both volumes print the same note on the first guide leaf. Read from 1869BPL_855.jpg (crop x100-1400 / y975-1450,
2x; the crop cut the right edge, the line ends are taken from the OCR) and checked against 1871BPL_936.jpg (crop
x110-1400 / y1105-1400, 2x):

> Showing the position, commencement, and termination of each Street, Avenue, Place, Lane, Court, Alley, etc.,
> in the City, with the junctions and crossings of the intersecting streets; also the number of the building at the
> corner of the street, avenue, etc., where there is any.
>
> When there is no house on the corner, or where the corner house fronts on the crossing street, the number
> nearest the corner is given, and a * placed before it, to denote that the number is not to be looked for on the corner
> of the street or avenue above named.
>
> A — denotes that there is no number on the corner.
>
> A † placed in the right or left column denotes that the street does not extend to that side of the one under whose
> heading it is found.
>
> As a rule the numbers will be found to commence westward, and northward from the opening of the street or
> avenue, even numbers occurring generally on the right-hand side.

Then "EXPLANATIONS.": "If you wish to find the location of any number - for instance, 115 Bridge street - on
consulting the Directory you will observe that 105 Bridge is on the left-hand of that street, and on the corner
of Prospect, and 129 Bridge is on the left-hand corner of Sands; hence the desired location of 115 Bridge is
between Prospect and Sands, on the left-hand side." And: "The capitals E. D., when placed after a street, avenue,
&c., denote that it is in the Eastern District." Then an abbreviations table (al., av., bk., B'way, cem., Ch.
for Church, ct., la., mkt., opp., pk. for Park, pl., rt., rd., sq., st., wf.).

### The printed explanatory note, 1875 (OCR only, leaf 1146 has no image)

Read from `1875BPL_1146.ocr.txt` (OCR has typos; letters I am sure of are normalised):

> Showing the commencement and termination of each Street, Avenue, Place, Lane, Court, etc., in the City,
> together with corner numbers of every intersecting street or avenue.
>
> If you desire to ascertain the location of any number - for instance No. 250 Nevins street - you will observe
> that No. 240 Nevins is on the corner of Douglass, right side, and No. 256 Nevins is on the corner of Degraw, hence
> the desired location of No. 250 Nevins street is between Douglass and Degraw, on the right side.
> [a second example, Willoughby avenue 511 / 551, "both on the left side"]
>
> Even numbers will be found on the right side, odd numbers on the left.
>
> A [dagger; OCR reads "^"] placed in the right or left column denotes that the street or avenue does not extend to that side.
>
> A - denotes that there is no number on the corner.

**The asterisk paragraph is gone in 1875.** The title page also says "COMPILED FROM THE OFFICIAL RECORDS ADOPTED BY THE
COMMON COUNCIL" and carries "Entered, according to act of Congress, in the year 1873, by Lain & Co." (both OCR only).
Only 32 of ~13,000 OCR lines in the 1875 guide leaves contain a `*`, against 837 (1869) and 804 (1871), and I saw
none in the Court or Dean entries on the image. So the 1875 guide does not use "nearest number" stars.

### Marks, one by one

| Mark | Where | Meaning |
|---|---|---|
| number | either column | house number at that corner on that side |
| `*` before a number | 1869, 1871 | no house on the corner, or the corner house fronts the crossing street; this is the nearest number, not on the corner |
| `—` (dash) | either column | "no number on the corner" (nothing built or no number) |
| `†` (dagger) | either column | the street does not extend to that side of the street under the heading (e.g. Court has `†` on the left where Dean meets it: Dean starts at Court and goes east) |
| `Ch.` / `Ch` | a number cell | not explained in the note; read as "Church" (the abbreviation list has Ch. = Church): a church stands at that corner |
| `Pk.` printed sideways | 1869, 1871 Court, left, spanning Montague and Remsen | not explained; read as "Park" (the City Hall park); one rotated label spanning both rows |
| blank | none seen | every row has something in both cells |

### Which side is "Left"?

The note does not say. By its own rule (numbers "commence westward, and northward from the opening of the street",
odd on the left, even on the right) the numbering starts at the "from" end of the heading. The simplest reading is
that Left and Right are as you face the other way along the street, but I could not check this offline against a
map, and the one outside hint I have (the park sits west of Court Street; the guide puts `Pk.` in the Left column
of a street whose heading runs "S.") would point to Left = west for Court. **Left/Right orientation is unverified**;
it does not matter for matching one volume to another, because all three use the same convention.

### Numbers at every cross street or only some?

Every crossing gets a row. 1869 and 1871 print a number only where a house exists (otherwise `—`), so streets
that are not built up are columns of dashes: Dean east of 5th av. is `— —` all the way to the city line, 27 rows.
1875 prints a number at **every** crossing that is on the street's own side, including unbuilt stretches: Dean has a pair
of numbers at all 36 crossings, to 2077/2094 at the city line. So the 1875 guide is a recomputed grid of numbers, not just
the houses that existed.

## 2. `1871BPL_935.jpg`: "STREET DIRECTORY CHANGES."

It is a table of **street name changes only. It contains no house numbers.** Columns: **NEW NAME. / OLD NAME. / LOCATION.**
It is a one-leaf list of 31 rows, alphabetical by new name from Hamburg to West (no entries for A-G on this leaf;
the leaf before is outside the files I was given). Read from crops x100-1500 / y40-700 and y650-1400, 2x.
First ten rows:

| New name | Old name | Location |
|---|---|---|
| Hamburg st | Johnson av | Morgan av. to Evergreen Cemetery |
| Harrison pl | Harrison st (E. D.) | Bogart to Jefferson |
| Henry pl | Henry st (E. D.) | Bridge av. to Newtown creek |
| Humboldt st | Smith st (E. D.) | Flushing av. to Meeker av |
| Johnson av | Johnson st (E. D.) | B'way to Bogart |
| Kingston av | Hudson av | Fulton av. to City line |
| Le Grange st | Lafayette st (E. D.) | Mauger to Grand |
| Lexington av | Hickory st | Grand av. to B'way |
| Loraine st | Leonard st | Otsego to Gowanus bay |
| Mauger st | Remsen st (E. D.) | Union av. to Morrell |

Remaining rows (new / old): Melrose / Centre; Monitor / William; Montleth / Monroe (E. D.); River / Water (E. D.),
S. 1st to N. 3d; Rockaway av / Paca av; President st / Secor pl ("is President st"); Seigel / Marshall (E. D.);
Skillman av / Skillman st (E. D.); Spruce / Jefferson (E. D.); Stanhope / Conselyea (E. D.); Duffield / Stanton
("is Duffield st"); St. James' pl / Hall st; St. John's pl / Douglass st; St. Mark's av / Wyckoff st (east of Flatbush av);
Ten Eyck / Wyckoff st (E. D.); Third av / Powers st (Flatbush av. to City line); Troutman / Madison (E. D.);
Union pl / Union av; Verona / Ewen; Vigelius / John (E. D.); Wallabout / River; West / Washington.

Of these, Hudson av to Kingston av and Powers to Third av show up directly in the 1871 Dean entry (section 3 below),
and Rockaway av (for Paca av) in the 1875 Dean entry. Leaves **936 onward are an ordinary guide**: 936 is the title page
"STREET AND AVENUE DIRECTORY OF THE CITY OF BROOKLYN. LAIN & CO., PUBLISHERS, 161 MONTAGUE ST." with the explanatory note
(I read the note on the image; the entries "Aberdeen" and "Adams, from East river" at its foot are OCR only);
937 starts with an "Alios (E. D.)" entry (OCR) with Left. Rt. tables. 940 and 942 are the same format (read from the images).

## 3. Transcriptions

Court and Dean are both on one leaf in each volume. In each volume the Court entry sits on one leaf and ends on the
same leaf (1869: wholly in column 1; 1871 and 1875: column 1, continuing at the top of column 2). No continuation on an unseen leaf.
Dean is a long street of 36-37 rows in all three; it was chosen because it begins at Court (so it ties to the Court
tables) and because 1869/71 print dashes where 1875 prints numbers.

Cells are shown as printed, with the `*` or `†` in the cell. "Marks" notes anything else.

### 3.1 Court, 1869BPL_861.jpg

Crops: x100-600 / y1140-1700, y1680-2300, y2250-2729 (2x); smudged numbers rechecked at 3x (x110-330 / y1480-1900 and
x110-400 / y1270-1560). Heading: "Court, from Fulton at City Hall sq., S. to Gowanus bay". Left. Rt.

| Left | Right | Cross street | Marks |
|---|---|---|---|
| — | — | Fulton | |
| Pk. | 1 | Montague | `Pk.` printed sideways, one label spanning this row and the next |
| Pk. | 10 | Remsen | |
| 18 | 17 | Joralemon | |
| 57 | *56 | Livingston | |
| *65 | 68 | Schermerhorn | |
| 83 | — | State | |
| *69 | *96 | Atlantic | left side reads 69 and 75 below 83: not increasing; printed so (also in 1871) |
| *75 | 128 | Pacific | |
| 141 | † | Dean | |
| † | 144 | Amity | |
| 113 | † | Bergen | 113 after 141: printed so (also in 1871); last digit smudged |
| † | Ch. | Congress | |
| *129 | † | Wyckoff | |
| † | 136 | W. Warren | |
| 149 | † | E. Warren | last digit smudged, reads 9 |
| † | 154 | W. Baltic | |
| 165 | † | E. Baltic | last digit smudged |
| † | 174 | Harrison | |
| Ch.[?] | † | Butler | black blot over the left cell; "Ch." partly visible; 1871 prints "Cn" here |
| 199 | † | Douglass | last digit smudged |
| *225 | 226 | Degraw | |
| *245 | *244 | Sackett | |
| 265 | 269 | Union | first digit smudged |
| *284 | — | President | |
| — | *299 | Carroll | |
| — | — | 1st pl | |
| — | — | 2d pl | |
| — | — | 3d pl | |
| — | — | 4th pl | |
| Ch. | — | Luqueer | |
| — | — | Nelson | |
| — | — | Huntington | |
| — | — | Church | |
| — | — | Mill | |
| — | — | Hamilton av | |
| — | — | Centre | |
| — | — | Bush | |
| — | — | Leonard | |
| — | — | Grinnell | |
| — | — | Bay | |
| — | — | Sigourney | |
| — | — | Haleck [printed "Hal eck"] | |
| — | — | Percival | |
| — | — | Bryant | |
| † | — | Oregon | |
| † | — | Cuba | |
| — | — | Gowanus bay | end of entry |

### 3.2 Court, 1871BPL_942.jpg

Crops: column 1 x100-600 / y1700-2300 and y2150-2705; column 2 x440-940 / y100-700 and y650-1250 (2x).
Heading: "Court, from Fulton, at City Hall sq., S. to Gowanus bay". Starts at the foot of column 1 (Fulton row at y~1838)
and continues from "Butler" row at the foot of column 1 to "Douglass" at the top of column 2 (y~153). Same 48 rows
and same 48 pairs of cells as 1869, with only these differences in text:

| Row | 1869 | 1871 |
|---|---|---|
| Atlantic | "Atlantic" | "Atlantic av" |
| Congress, right cell | "Ch." | "Ch" |
| Butler, left cell | blotted, "Ch.[?]" | "Cn" |
| Luqueer, left cell | "Ch." | "Ch" |
| Halleck | "Haleck" | "Halleck" |

Every number, `*`, `†` and `—` cell is the same as in 3.1 (checked row by row against the crops, including
the odd `*69`, `*75`, `113`). Cross streets Mill and Leonard are still listed under their old names in 1871,
although the 1871 guide has cross-reference entries "Mill (See Garnet)" and "Leonard (See Loraine)".

### 3.3 Court, 1875BPL_1152.jpg

Crops: x120-620 / y1440-2000, y1950-2600; x470-970 / y250-900 (2x); 3x checks at x130-480 / y1680-2530 and
x480-800 / y310-800; 6x on the worn right-hand numbers. Heading: "Court, from Fulton, at City Hall sq., S. to
Gowanus bay"; column 1 from y1594 to the "Garnet" row at the foot, continuing at the top of column 2 with "Hamilton av".
Left. Rt.

| Left | Right | Cross street | Marks |
|---|---|---|---|
| — | 2 | Fulton | |
| † | 10 | Montague | |
| † | 32 | Remsen | |
| 45 | 46 | Joralemon | |
| 77 | 76 | Livingston | |
| 101 | 94 | Schermerhorn | |
| 121 | 112 | State | |
| 137 | 12[8?] | Atlantic av | right: middle and last digit worn |
| 149 | 142 | Pacific | |
| 167 | † | Dean | |
| † | 160 | Amity | |
| 185 | † | Bergen | |
| † | 17[8?] | Congress | last digit worn |
| 203 | † | Wyckoff | |
| 221 | 210 | Warren | one row; 1869/71 have W. Warren and E. Warren |
| 241 | 230 | Baltic | one row; 1869/71 have W. Baltic and E. Baltic |
| † | 24[8?] | Harrison | last digit worn |
| 261 | † | Butler | |
| 283 | † | Douglass | |
| 303 | 304 | Degraw | |
| 323 | 324 | Sackett | |
| 343 | 346 | Union | |
| 361 | 366 | President | |
| 363 | 38[6?] | Carroll | left 363 follows 361: printed so; right last digit worn |
| 383 | 406 | 1st pl | |
| 405 | 426 | 2d pl | |
| 425 | 446 | 3d pl | |
| 447 | 470 | 4th pl | |
| 463 | 490 | Luquer | |
| 479 | 508 | Nelson | |
| 497 | 524 | Huntington | |
| 515 | 544 | Church | |
| 535 | 564 | Garnet | was "Mill" in 1869/71 |
| 553 | 582 | Hamilton av | |
| 551 | 584 | Centre | 551 after 553: printed so |
| 561 | 598 | Bush | |
| 577 | 614 | Lorraine | was "Leonard" |
| 59[3?] | 630 | Grinnell | last digit of left worn |
| 609 | 64[6?] | Bay | last digit of right worn |
| 625 | 666 | Sigourney | |
| 641 | 686 | Halleck | |
| 657 | 706 | Percival | |
| 677 | 726 | Bryant | |
| — | 746 | Oregon | |
| — | 766 | Gowanus bay | end of entry. No `*` and no `Ch.`/`Pk.` anywhere in the entry |

### 3.4 Dean, 1869BPL_861.jpg

Crops: x800-1300 / y400-1000 and y950-1500 (2x). Heading: "Dean, from Court, bet. Pacific and Bergen, E. to City
line". Left. Rt. 37 rows. Rows 1-10 as printed, then all dashes.

| Left | Right | Cross street |
|---|---|---|
| *1 | *2 | Court |
| *21 | *32 | Boerum |
| *51 | *50 | Smith |
| *97 | 107 | Hoyt |
| 175 | 174 | Bond |
| 233 | 234 | Nevins |
| *267 | 268 | Powers |
| 311 | *314 | 4th av |
| — | — | 5th av |
| — | *400 | Flatbush av |

`— —` in both cells for the other 27 cross streets, in this order: Pearsall, Carlton av, Vanderbilt av, Underhill av,
Washington av, Grand av, Classon av, Franklin av, Rogers av, Clove rd, Nostrand av, New York av, Brooklyn av,
Hudson av, Albany av, Troy av, Schenectady av, Utica av, Rochester av, Hunterfly rd, Buffalo av, Ralph av, Howard av,
Saratoga av, Hopkinson av, Paca av, City line.

### 3.5 Dean, 1871BPL_942.jpg

Crops: x820-1320 / y1170-1750 and y1700-2260 (2x), column 3 of the leaf. Same numbers, stars and dashes in all 37 rows as 1869
(3.4). Only the names differ: **"Powers" is now "3d av"** and **"Hudson av" is now "Kingston av"** (both are in the
1871 changes table). Everything else, the other 35 cross streets, is spelled as in 1869.

### 3.6 Dean, 1875BPL_1152.jpg

Crops: x830-1330 / y840-1400 and y1380-1880 (2x). Same heading. Left. Rt. 36 rows. Every row has both numbers; no `*`, no `—`, no `†`.

| Left | Right | Cross street |
|---|---|---|
| 1 | 2 | Court |
| 37 | 34 | Boerum pl |
| 77 | 74 | Smith |
| 141 | 134 | Hoyt |
| 199 | 190 | Bond |
| 259 | 250 | Nevins |
| 309[?] | 304 | 3d av |
| 369 | 366 | 4th av |
| 443 | 438 | 5th av |
| 453 | 456 | Flatbush av |
| 485 | 484 | Pearsall |
| 571 | 572 | Carlton av |
| 659 | 650 | Vanderbilt av |
| 725 | 726 | Underhill av |
| 749 | 750 | Washington av |
| 795 | 800 | Grand av |
| 881 | 874 | Clason av |
| 961 | 958 | Franklin av |
| 1027 | 1028 | Perry av |
| 1029 | 1030 | Rogers av |
| 1093 | 1092 | Nostrand av |
| 1151 | 1164 | New York av |
| 1229 | 1236 | Brooklyn av |
| 1301 | 1308 | Kingston av |
| 1371 | 1376 | Albany av |
| 1443 | 1450 | Troy av |
| 1511 | 1520 | Schenectady av |
| 1585 | 1588 | Utica av |
| 1651 | 1660 | Rochester av |
| 1717 | 1724 | Buffalo av |
| 1779 | 1786 | Ralph av |
| 1841 | 1854 | Howard av |
| 1902[?] | 1924 | Saratoga av |
| 1981 | 1[?]98 | Hopkinson av |
| 2049 | 2066 | Rockaway av |
| 2077 | 2094 | City line |

1902 is even on the left, which breaks the rule; it may be a misprint or a misread. The "[?]" on 309 means the first digit is worn.
Cross streets changed since 1871: Boerum pl (was Boerum), Perry av is new between Franklin and Rogers, Clove rd and Hunterfly rd are gone,
Rockaway av replaces Paca av (per the 1871 changes table), Clason av (spelling).

## 4. Court street, 1869 vs 1871 vs 1875, at the same cross streets

**1869 and 1871 agree in every cell.** The 48 rows of left and right numbers and marks are identical, including the odd printed values
(`*69` and `*75` below `83`; `113` below `141`). Only cross-street spellings changed (3.2). The 1871 guide is a re-set of the 1869 guide with
names updated; it has not been renumbered. (Dean agrees the same way, apart from the two renamed crossings.) The 1871 Fulton avenue note (section 6)
says the new numbers "are not ready", which fits.

**1875 differs at every corner that has a number.** None of the 1875 numbers on Court equals the same cell in 1869/71.

| Cross street | 1869 = 1871 (L / R) | 1875 (L / R) |
|---|---|---|
| Fulton | — / — | — / 2 |
| Montague | Pk. / 1 | † / 10 |
| Remsen | Pk. / 10 | † / 32 |
| Joralemon | 18 / 17 | 45 / 46 |
| Livingston | 57 / *56 | 77 / 76 |
| Schermerhorn | *65 / 68 | 101 / 94 |
| State | 83 / — | 121 / 112 |
| Atlantic (av) | *69 / *96 | 137 / 12[8?] |
| Pacific | *75 / 128 | 149 / 142 |
| Dean | 141 / † | 167 / † |
| Amity | † / 144 | † / 160 |
| Bergen | 113 / † | 185 / † |
| Congress | † / Ch. | † / 17[8?] |
| Wyckoff | *129 / † | 203 / † |
| W. Warren, E. Warren | † / 136, 149 / † | Warren: 221 / 210 |
| W. Baltic, E. Baltic | † / 154, 165 / † | Baltic: 241 / 230 |
| Harrison | † / 174 | † / 24[8?] |
| Butler | Ch.[?] (1871: Cn) / † | 261 / † |
| Douglass | 199 / † | 283 / † |
| Degraw | *225 / 226 | 303 / 304 |
| Sackett | *245 / *244 | 323 / 324 |
| Union | 265 / 269 | 343 / 346 |
| President | *284 / — | 361 / 366 |
| Carroll | — / *299 | 363 / 38[6?] |
| 1st pl to 4th pl, Luqueer, Nelson, Huntington, Church | all — / —, Ch. at Luqueer | 383/406 ... 535/564 (Garnet) |
| Mill/Garnet to Bryant | — / — | 535 ... 677 / 564 ... 726 |
| Oregon, Cuba, Gowanus bay | † / —, † / —, — / — | — / 746, (Cuba not listed), — / 766 |

Three clean corners (no stars in 1869/71, no worn digits in 1875) for old to new on Court:
Joralemon 18 / 17 to 45 / 46; Union 265 / 269 to 343 / 346 (1869 first digit of 265 is smudged); State 83 / — to 121 / 112.

What the pair also shows: 1875 pairs left and right at each corner more tightly (odd and even sit a few numbers apart), 1869/71 sometimes
have a star or a dash on one side, and **1875 continues numbering where 1869/71 print dashes**: Court has numbers all the way from Garnet
(535 / 564) to Gowanus bay (766), where 1869/71 gave no numbers south of Carroll. The ratio of new to old is not constant
(Joralemon 18 to 45, Union 265 to 343), so there is no formula; the guide gives the corners.

Caution: the 1869/71 numbers with `*` are not on the corner, and a few look misprinted (`*69`, `*75`, `113`). A match table built from this guide should keep the star flag.

## 5. How good is the existing OCR on these entries?

Method: my transcription (section 3) against the OCR lines of the same rows, aligned row by row (by position when the OCR has the same number
of lines, otherwise by a monotone name alignment). **(a) both numbers right** = the digits in the OCR line, ignoring marks, equal the digits I read
for that row (a row with only dashes/daggers counts right if the OCR has no spurious digit). **(b) name** = cross-street name, "exact" after lower-casing
and dropping punctuation and digits, "close" if letter similarity of at least 0.70 (the "close" figures are from the script and are an estimate;
a few rows at 0.5-0.7 are still recognisable by eye, e.g. "8d pi" for 3d pl).
Sample: Court and Dean only (85 rows in 1869 and 1871, 81 in 1875), so the figures are for these two entries, not the whole guide.

| Volume | (a) both numbers right | (a) on rows that have a number | (b) name exact | (b) name close |
|---|---|---|---|---|
| 1869 | 79 / 85 = 93% (Court 42/48, Dean 37/37) | 27 / 32 = 84% | 75 / 85 = 88% | 83 / 85 = 98% |
| 1871 | 81 / 85 = 95% (Court 46/48, Dean 35/37)* | 28 / 32 = 88% | 70 / 85 = 82% | 83 / 85 = 98% |
| 1875 | 69 / 81 = 85% (Court 37/45, Dean 32/36) | 69 / 81 = 85% | 50 / 81 = 62% | 74 / 81 = 91% |

\* The script scored Court 45/48; one of those misses ("1'ercival") is a letter read as a digit in a name, not a wrong number, so I count 46/48.
The dash-only rows make 1869/71 look better on "all rows"; the third column is the fairer number for houses.

Typical errors, with examples from the files:

- **1869**: smudged digits misread (113 as 118, 165 as 166, 199 as 198, 265 as 185, `*245` as `*24o`); the blotted Butler cell read "91.";
  `Pk.` (sideways) read "^" and "a."; `†` read as `f`, `t`, `+`, `|`, "■(•"; "3d pl" read "8d pl". Rows stay one per line, in order.
- **1871**: `*56` as "*5t>", `*69` as "*89", `*32` as "*J2", `*1` as "*L"; `†` as `f`, `t`, "gf", "•j-"; "Cn" for "Ch"; letter noise in names ("NeviDS", "GrinneU").
- **1875**: the number columns and the name are often **separate OCR lines**: 1,826 of ~13,100 lines in the 1875 guide leaves (14%) are number-only lines
  (against ~220-250 in 1869/71). In Court's second column the numbers (x~496) and the names (x~608) are separate lines; on leaf 1147 a left number
  ("1") and "2 Decatur" come as two lines. Worn digits are wrong more often (`346` as "316", `426` as "428", `544` as "644", `593` as "693", `646` as "648", `38[6?]` as "38!i"); the number "10" on Montague was lost ("Hi").
  Names get worse (exact 62%): "Jo;aicinon", "Gi iencll", "Hillock", "Sackclt".

**Could a script parse these files into rows? Yes, with care.** Each row is mostly one line "left right name" with the
x coordinate of the name stable inside a column, and every entry has an anchor line "Left. Rt." (OCR variants seen: "Left. St.", "Left. Bt.", "Left. lit.", "Left. Et.",
"Left. Mt.", "Left. Jit.", "Left Rt", "Left." alone with Rt. on another line: 549/557/536 such lines in 1869/1871/1875). What would trip it:

1. Columns are not separated; four columns per page, and an entry runs from the foot of one column to the top of the next (Court in 1871 and 1875) with no new header. The script must cluster by x and join across the column break.
2. Marks are garbled: `†` becomes `f`, `t`, `+`, `|`, "•j-", "gf"; dashes become `_`, `-`, `.`, or are fused to the next token ("—Fulton", "—President", "*245*244", "311*314", "157*154"). A row can therefore have 1, 2 or 3 tokens before the name.
3. In 1875 the left number is often a separate line from the right number and name: group by y (within about 12 px) after x-clustering.
4. Cross-street names that begin with a digit (1st pl, 2d pl, 3d av, 4th av) put digits where a number is expected.
5. Worn digits and dropped digits give wrong numbers silently ("38!i", "Hi"); there is no check digit. The print itself has non-monotone numbers (`*69` after 83; 553 then 551), so monotonicity checks cannot flag OCR errors reliably.
6. Heading lines wrap over 2-4 lines with hyphens ("Gow-/anus bay") and "(E. D.)", "(late X)", "(See Y)" are inside the name; one-line "See" entries have no table.
7. Names change between volumes (Powers/3d av, Hudson/Kingston, Mill/Garnet, Paca/Rockaway, Leonard/Loraine/Lorraine), so cross-volume joins need the changes table.

## 6. Other statements about old and new numbers, or when streets were renumbered

- **1871BPL_946 (OCR only, no image; leaf not in the image set).** The entry "Fulton av., from termination of Fulton, at Pearl and Red Hook lane,
  S. E. and E. to City line" carries a bracketed note: **"(This is now Fulton st. The av. is inserted as the new numbers are not ready)"**.
  That is the only printed statement I found about numbering. It says that in 1871 Fulton was being renumbered or merged into Fulton street, and that the 1871 guide still
  gave the avenue's old numbers because the new ones were not ready. It supports reading the 1871 guide as the last "old numbers" guide.
- Nothing on the leaves I read prints old and new numbers side by side, and no leaf says that all of Brooklyn is being renumbered or when.
  I grepped all 127 OCR files for "renumber", "new number", "old number", "numbering": only the Fulton note matches.
- **Name changes** (not numbers): the 1871 "STREET DIRECTORY CHANGES" table (section 2); "See" cross-references in the 1871 alphabetical list ("Mill (See Garnet)",
  "Leonard (See Loraine)", "Hudson av. (See ...)", "Powers (See 3d av.)", "Hickory (See Lexington)", "Jefferson (See Spruce)", "Ewen (See Verona)", "John (See Vigelius)",
  "Middle (See Prospect)"); and "(late X)" headings in 1875 for the same streets and more (Garnet late Mill, Lorraine late Leonard, Hamburg late Johnson, Melrose late Centre, River late Water, Seigel late Marshall, Spruce late Jefferson, Stanhope late Conselyea, Troutman late Madison, Ten Eyck late Wyckoff, Wallabout late River, Union pl late Union, Monitor late William, Montleth late Monroe, Mauger late Remsen). Garnet and Lorraine are in 1871 as cross-references but Garnet is not in the 935 table. Court's own cross-street list in 1871 still used Mill and Leonard.
- 1869BPL_855 and 1871BPL_936 print the same explanation (no mention of renumbering).
- **1875** title page (OCR only): "COMPILED FROM THE OFFICIAL RECORDS ADOPTED BY THE COMMON COUNCIL", copyright "in the year 1873". The 1875 guide's numbers differ from 1871 at every corner on Court and Dean (sections 3-4), and the 1875 guide drops the star rule and prints numbers at every crossing.
  So the renumbering is visible in the numbers, but is not announced in the 1875 front matter that I could read.
- Dean's 1869 to 1875 first rows are equal at the start of the street (Court: *1 / *2 to 1 / 2), so a street's first corner keeps its numbers; the numbers diverge from there.
