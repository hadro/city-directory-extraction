#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Each volume's race-marker convention, as cited sidecar claims (PIPELINE #37, 2026-11-04).

    python3 data_prep/survey_race_markers.py            # what would change
    python3 data_prep/survey_race_markers.py --write    # write the claims into data_prep/survey/

What marks a colored person is a property of the VOLUME, not of the line: the same `*` means
colored in Ogden 1839, Eastern District in Hope & Henderson 1856 and an advertiser in Trow 1905.
The 4B sees one line, so it set race_designation on firms' stars and left it empty on half the
stars that were race (docs/RACE_MARKERS_HANDOFF.md). Two book_says claims record the convention,
and postprocess/assemble_records.race_resolved reads them:

  race_marker   the printed form that marks a colored person. `*` in 32 volumes (Spooner, Ogden
                and Hearnes, Brooklyn 1829-55, and Williamsburgh 1849-54: "NOTE.—Names having a *
                are the names of colored people"), a textual form in 31 (`(col'd)` Doggett, Rode,
                Trow 1857-65, Hope & Henderson, Lain 1871; `(col.)` Lain 1858-69 and the
                Consolidated microfilm; `(colored)` Longworth; `colored` Smith 1857). A volume
                with no claim prints none, or nothing the model can be held to.
  star_meaning  what a leading `*` means where it is NOT race. `eastern_district`: Hope & Henderson
                1856/57 prints a `*` for it, and the Consolidated microfilm (0039/0040/0042) and
                Lain 1866 print a small raised E that the OCR reads as `*` (crops read 2026-11-04:
                `ᴱLevy Mark, glazier, h. 522 Grand`). `advertiser`: Trow 1859-1914, Lain 1884-99,
                Upington 1902-10 (`*KRANICH & BACH, pianos`, `*BANK OF MONTREAL`).

Every claim cites a leaf and a verbatim quote (SURVEY_PLAN.md, the citation rule): the key page
where the film has one, else listing lines carrying the mark (`evidence_type` `listing`; Reynolds
0045/0047/0048 start mid-listing, the key is not on the film). `method` is `agent-read`, so a
front-matter re-read keeps them (survey_frontmatter.merge_book). `confidence` is `high` where the
line was read on the image, `medium` where read in the OCR text or inferred from the lines.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "data_prep"))
from survey_frontmatter import cite  # noqa: E402

SIDECARS = REPO / "data_prep" / "survey"
KEY = "NOTE.—Names having a * are the names of colored people."
ED_E = "the raised E reads as `*` in the OCR (crops read 2026-11-04)"

# (volume, leaf, evidence_type, quote, confidence)
STAR_IS_RACE = [
    ("micro_IABROOKLYN_0006", 5, "legend", "Names having an * are of colored persons.", "high"),
    ("micro_IABROOKLYN_0007", 5, "legend", "Names having an * are of colored persons.", "high"),
    ("micro_IABROOKLYN_0008", 6, "legend", "Names having an * are of colored persons.", "high"),
    ("micro_IABROOKLYN_0009", 5, "legend", "Names having an * are of colored persons.", "high"),
    ("micro_IABROOKLYN_0010", 4, "legend", "Names having an * are of colored persons.", "high"),
    ("micro_IABROOKLYN_0011", 5, "legend", "Names having an * are of colored persons.", "high"),
    ("micro_IABROOKLYN_0012", 14, "legend", "Names having an * are of colored people.", "high"),
    ("micro_IABROOKLYN_0013", 14, "legend", "Names having an * are of colored people.", "high"),
    ("micro_IABROOKLYN_0014", 8, "legend", "Names having an * are of colored people.", "high"),
    ("micro_IABROOKLYN_0015", 21, "legend", "Names having a » are the names of colored people.",
     "medium"),                                          # the OCR's reading of the star
    ("micro_IABROOKLYN_0017", 8, "legend", "NOTE.—Names having an * are the names of colored "
                                           "people.", "high"),
    ("micro_IABROOKLYN_0018", 10, "legend", "NOTE.—Names having an * are the names of colored "
                                            "people.", "high"),
    ("brooklyndirector00ogde", 9, "legend", "NOTE.—Names having an * are the names of colored "
                                            "people.", "high"),
    ("brooklynalphabet1843unse", 17, "legend", KEY, "high"),
    ("micro_IABROOKLYN_0020", 14, "legend", KEY, "high"),
    ("micro_IABROOKLYN_0021", 141, "listing", "*Mitchell Sam'l laborer Johnson's Alley; "
                                              "*Corporal Isaac, laborer 206 Jay (leaf 58)", "medium"),
    ("micro_IABROOKLYN_0023", 21, "legend", KEY, "medium"),
    ("micro_IABROOKLYN_0024", 23, "legend", KEY, "high"),
    ("brooklyncitydire1848teal", 11, "legend", "* are the names of COLORED PEOPLE.", "high"),
    ("micro_IABROOKLYN_0025", 21, "legend", KEY, "high"),
    ("micro_IABROOKLYN_0027", 18, "legend", KEY, "high"),
    ("micro_IABROOKLYN_0043", 4, "legend", KEY, "high"),     # Williamsburgh 1849-50
    ("hearnesbrooklync1850unse", 25, "legend", KEY, "medium"),
    ("micro_IABROOKLYN_0044", 16, "legend", "NOTE.—Names having a * are those of colored "
                                            "people.", "high"),   # Reynolds, Williamsburgh
    ("micro_IABROOKLYN_0029", 335, "listing", "*Richardson Edward, waiter 22 Talman; *Dixon Ann, "
                                              "widow 19 Chapel (leaf 139)", "medium"),
    ("micro_IABROOKLYN_0045", 193, "listing", "*Treadwell Lewis, whitewasher, North 1st c. Fighth; "
                                              "*Merritt Abraham, laborer, Marshall n. Leonard "
                                              "(leaf 139)", "medium"),
    ("hearnesbrooklync1852unse", 27, "legend", KEY, "high"),
    ("micro_IABROOKLYN_0046", 162, "listing", "*Merritt John, gasfitter, Marshall n. Leonard; "
                                              "*Jackson Percy, cook, 26 Montrose avenue (leaf 123)",
     "medium"),
    ("micro_IABROOKLYN_0047", 33, "listing", "*Brister Robert, waiter, 258 South 2d; *Dorrell "
                                             "Susan, seamstress, 74 South 6th (leaf 64)", "medium"),
    ("micro_IABROOKLYN_0031", 22, "listing", "*Abrahams Michael, carpenter 5 Stryker's court; "
                                             "*Abrahams Thomas, whitewasher 64 Jay", "high"),
    ("micro_IABROOKLYN_0048", 65, "listing", "*Corprew Sarah, widow, South 6th n. Eleventh; "
                                             "*Treadwell R. laborer, 26 Montrose av. (leaf 279)",
     "medium"),
    ("micro_IABROOKLYN_0032", 29, "listing", "*Bagwell George, superintendent of No. 1 colored "
                                             "school", "medium"),
]

# (volume, form, leaf, evidence_type, quote, confidence): the form is the volume's commonest
# reading of it (round 13's records); the quote is the key where it lists the form, else a line
TEXTUAL = [
    ("longworthsameric00newy", "(col'd)", 64, "listing", "Allen William, oysters (col'd) 435 "
                                                         "Broadway", "medium"),
    ("longworthsameric1826newy", "(colored)", 345, "listing", "Crawford Abigail, (colored) "
                                                              "mantuamaker 66 Beekman", "medium"),
    ("longworthsameric6018long", "(colored)", 64, "listing", "Aldrich Daniel, (colored) huckster "
                                                             "3 Leonard", "medium"),
    ("longworthsameric6118long", "(colored)", 70, "listing", "Barnes Mary, (colored) fruiterer "
                                                             "58 King", "medium"),
    ("longworthsameric6518long", "(col'd)", 56, "listing", "Allen William M. oysters (col'd) 435 "
                                                           "Broadway", "medium"),
    ("doggettsnewyorkc1845dogg", "(col'd)", 22, "listing", "Aldrich Edward, (col'd) steward, 14 "
                                                           "Thomas", "medium"),
    ("doggettsnewyorkc1846dogg", "(col'd)", 26, "listing", "Alexander Cesar, (col'd) waiter, r. 74 "
                                                           "Reade", "medium"),
    ("doggettsnewyorkc1847dogg", "(col'd)", 28, "listing", "Aldrich Samuel, (col'd) waiter, r. 156 "
                                                           "Laurens", "medium"),
    ("doggettsnewyorkc1848dogg", "(col'd)", 29, "listing", "Addison Charles, (col'd) barber, 102 "
                                                           "Lewis", "medium"),
    ("micro_IABROOKLYN_0022", "(col.)", 5, "listing", "Ashton George, (col.) cooper, Bridge c. "
                                                      "York", "medium"),
    ("newyorkcitydirec00rode", "(col'd)", 25, "listing", "Abbott William, (col'd), laborer, r. 17 "
                                                         "Laurens", "medium"),
    ("1856BPL", "(col.)", 67, "listing", "Allboy Samuel H. (col.) seaman, h. Troy av. n. Dean",
     "medium"),
    ("micro_IABROOKLYN_0035", "(col'd)", 38, "legend", "col'd colored", "high"),
    ("1857BPL", "colored", 32, "listing", "Abrams M. A. colored laundress, r. 283 Adams", "medium"),
    ("trowsnewyorkcity1857trow", "(col'd)", 21, "listing", "Alford Lydia (col'd), wid. Benjamin, "
                                                           "r 174 Essex", "medium"),
    ("1858BPL", "(col.)", 8, "listing", "Adams Catharine (col.) h. r. 143 Prospect", "medium"),
    ("micro_IABROOKLYN_0039", "(col.)", 11, "legend", "col. colored", "high"),
    ("micro_IABROOKLYN_0040", "(col.)", 11, "listing", "E Ackiss L. wid. (col.), washwoman, h. 7 "
                                                       "Varet", "medium"),
    ("trowsnewyorkcity1859trow", "(col'd)", 24, "listing", "Adams Caroline R. wid. Wm. (col'd), h "
                                                           "71 Thompson", "medium"),
    ("micro_IABROOKLYN_0042", "(col.)", 15, "listing", "Amos Wm. (col.) carman, h. r. 101 Nassau",
     "medium"),
    ("1862BPL", "col.", 10, "listing", "Anderson Betsey, col. wid. laundress, h. 44 Talman",
     "medium"),
    ("1863BPL", "(col.)", 6, "listing", "Abrams Mary A. wid. (col.) laundress, 46 De Kalb av",
     "medium"),
    ("trowsnewyorkcity1863trow", "(col'd)", 21, "listing", "Abbott Keziah (col'd), wid. Jacob, h r "
                                                           "68 Third av.", "medium"),
    ("1864BPL", "(col.)", 9, "listing", "Abet Stephen, (col.) lab. h. Wyckoff n. Troy av",
     "medium"),
    ("1865BPL", "(col.)", 14, "listing", "Adams, Elizabeth, (col.) wid. laundress, h. 194 Pearl",
     "medium"),
    ("bub_gb_hY4tAAAAYAAJ", "(col'd)", 24, "listing", "Adams Ann (col'd), laundress, h 66 "
                                                      "Sullivan", "medium"),
    ("1866BPL", "(col.)", 24, "listing", "Abess Gardner (col.) h. r. 99 Nassau", "medium"),
    ("1867BPL", "(col.)", 10, "listing", "Abrams Mary A. wid. (col.) laundress, h 44 De Kalb av",
     "medium"),
    ("1868BPL", "(col.)", 11, "listing", "Abrams Thomas, (col.) butcher, h 30 Boerum", "medium"),
    ("1869BPL", "(col.)", 13, "listing", "Abrahams Susan (col.) laundress, 262 Gold", "medium"),
    ("1871BPL", "(col'd)", 44, "listing", "Bates Henry (col'd) lab. h 65 Middagh", "medium"),
]

# (volume, leaf, evidence_type, quote, confidence, note)
EASTERN_DISTRICT = [
    ("micro_IABROOKLYN_0035", 38, "legend", "NOTE.—Names marked thus * are persons residing or "
                                            "doing business in the Eastern District.", "high", None),
    ("micro_IABROOKLYN_0039", 11, "legend", "NOTE—Names marked thus (ᴱ) are persons residing or "
                                            "doing business in the Eastern District.", "high",
     ED_E + ": leaves 252, 369, 395"),
    ("micro_IABROOKLYN_0040", 10, "legend", "NOTE—Names marked thus (ᴱ) are persons residing",
     "high", ED_E),
    ("micro_IABROOKLYN_0042", 10, "legend", "NOTE—Names marked thus (ᴱ) are persons residing or "
                                            "doing business in the Eastern District.", "high",
     ED_E),
    ("1866BPL", 332, "listing", "ᴱKuphal Mina, wid. h 44 Lorimer; ᴱKuntz Lewis, clerk, h 186 "
                                "Montrose av", "high", ED_E + "; the volume prints E on 8,431 lines"),
]

# (volume, leaf, quote): a firm's or an advertiser's star, read on listing lines 2026-11-04 in
# every volume where the 4B set race_designation="*" on 15 or more usable lines. Lain 1858-71
# (other than 1866) star a handful of Eastern District lines the same way, too few for the mark
# classifier; they get no claim, and so no race.
ADVERTISER = [
    ("trowsnewyorkcity1859trow", 902, "*WATERBURY BRASS AGENCY, 52 Beekman"),
    ("trowsnewyorkcity1863trow", 759, "*ROGER, FILS & CO. millstones, 21 Pearl"),
    ("bub_gb_hY4tAAAAYAAJ", 243, "*DOLPHIN MANUF. CO., FLAX, HEMP AND JUTE GOODS, 171 Water"),
    ("trowsnewyorkcity1876trow", 958, "*MERCANTILE INS. CO. (of Boston) Bigelow, Coit & Peck, "
                                      "agent"),
    ("1884BPL", 742, "*KRANICH & BACH, pianos, 233 E. 23d N.Y."),
    ("1886BPL", 1249, "*YALE & TOWNE MF’G CO (The), locks, 62 Reade N Y"),
    ("1887BPL", 593, "*Howe Scales, 325 B'way N.Y."),
    ("1889BPL", 1356, "*WILLIAMS H. P. & Co. matting, etc. 250 Canal N. Y."),
    ("1899xBPL", 614, "*HEIDELBERG CHARLES, detective agency, 320 Broadway N. Y."),
    ("1902BPL", 790, "*REEDY ELEVATOR CO. 407 W. 14th Mhtn"),
    ("1903BPL", 844, "*SALAMANDER GRATE BAR CO. 126 Liberty Mhtn"),
    ("1904BPL", 336, "*FULLER’S N Y DETECTIVE BUREAU 866 Bway n 17th Mhtn"),
    ("brooklynnewyork1905p1geor", 821, "*GRINNELL JOHN C & CO paints 19 & 21 Flatbush av"),
    ("brooklynnewyorkc1905geor", 749, "*SELLEW T G office furniture 111 Fulton Mhtn"),
    ("1906BPL", 1178, "*WILCOX & GIBBS SEWING MACHINE CO 602 Fulton"),
    ("1907BPL", 1042, "*WEBB C WATSON REALTY CO 3510 Jamacia av Richmond Hill N Y"),
    ("1908BPL", 525, "*KEYES & WILSON Carriage and Auto Body Builders"),
    ("brooklynnewyorkc1910geor", 761, "*FORGOTSTON MORRIS A diamonds 1432 Broadway"),
    ("trowsgeneraldir1903p1trow", 791, "*Empire City Electrotype Co., 251 William."),
    ("trowsgeneraldir1903p2trow", 169, "*HOWE'S SCALES, 341 Bway, repair shop, 88 1/2 Leonard."),
    ("trowsgeneraldir1903p3trow", 377, "*Star Lyceum Bureau, Alonzo Foster, manager, 83 Tribune "
                                       "bldg"),
    ("trowsgeneraldir1904p1trow", 613, "*Consolidated Safety Pin Co 353 Bway"),
    ("trowsgeneraldir1904p2trow", 979, "*PRIESTLEY B. & CO. dress goods and Cravenettes 73 Grand."),
    ("trowsgeneraldir1904p3trow", 147, "*Sherman & Sterling lawyers 44 Wall."),
    ("trowsgeneraldir1905p1trow", 1015, "*GADE HENRY paper and twine, 349 Broome."),
    ("trowsgeneraldir1905p2trow", 521, "*Lindsay Type Foundry (The) 75 Fulton."),
    ("trowsgeneraldir1905p3trow", 537, "*Transatlantic Express, 33 Bway."),
    ("trowsgeneraldir1906p1trow", 625, "*COMPRESSED AIR CARPET CLEANING CO 540 W 23d (tel)."),
    ("trowsgeneraldir1906p2trow", 9, "*Gossweiler Cafe & Assembly Hall 350 1st av"),
    ("trowsgeneraldir1906p3trow", 689, "*Vermont Clock Co 45 Malden la R 24."),
    ("trowsgeneraldir1907p1trow", 519, "*Camden Fire Ins Assn of Camden N J 72 William."),
    ("trowsgeneraldir1907p2trow", 1217, "*Patrick, Wilder & Lillie safes 55 Maiden la."),
    ("trowsgeneraldir1907p3trow", 291, "*Seaman’s Stables, Park av c E 76th."),
    ("trowsgeneraldire19073trow", 177, "*St Paul F. & M Ins. Co. 77 Beaver Wm H. McGee, marine "
                                       "agent"),
    ("trowsgeneraldir1908p1trow", 339, "*BERKSHIRE LIFE INS CO. John H. Robinson, general agent"),
    ("trowsgeneraldir1908p2trow", 907, "*Lambert men’s outfitter 41 Cortlandt & 183 Bway."),
    ("trowsgeneraldir1908p3trow", 707, "*Raisbeck Electrotype Co 24 Vandewater."),
    ("trowsgeneraldir1908p4trow", 449, "*Virginia, Tennessee & Georgia Air Line 398 Bway."),
    ("trowsgeneraldir1909p1trow", 377, "*Boston Clock Co 45 Maiden la R 24."),
    ("trowsgeneraldir1909p2trow", 291, "*JULIEN EMPLOYMENT BUREAU 47 W 42d."),
    ("trowsgeneraldir1909p3trow", 417, "*Stag Brand Neckwear (The) 32 Union sq E, R 601."),
    ("trowsgeneraldire19091trow", 375, "*Boulevard Floral Co 2391 Bway."),
    ("trowsgeneraldir1910p1trow", 331, "*Borgia Contracting Co 1133 Bway R1603."),
    ("trowsgeneraldir1910p2trow", 281, "*Interboro Polishing & Plating Works 332 7th av."),
    ("trowsgeneraldir1910p3trow", 747, "*Vermont Clock Co 45 Maiden la R24"),
    ("trowsgeneraldir1911p1trow", 251, "*Bergstein & Son jewelers 102 Fulton R302."),
    ("trowsgeneraldir1911p2trow", 633, "*MacLevy Farm training 47 W42d R402"),
    ("trowsgeneraldir1911p3trow", 657, "*Vineta Paper Mills 349 Broome"),
    ("trowsgeneraldir1912p1trow", 613, "*Conservatory of Music 57 W 93d."),
    ("trowsgeneraldir1912p2trow", 1113, "*PARQUET FLOORS William G. Reid & Co. proprietors 2 W 33d."),
    ("trowsgeneraldir1912p3trow", 197, "*Savoy Film Exchange 221 6th av."),
    ("trowsgeneraldir1914p1trow", 129, "*BANK OF MONTREAL 64 Wall Street. Tel. John 5680."),
    ("trowsgeneraldir1914p2trow", 1023, "*Poulson & Eger (Hecla Iron Works) 118 N 11th st "
                                        "Brooklyn."),
    ("trowsgeneraldir1914p3trow", 363, "*Smith & Wesson 88 White Street (by M. W. Robinson Co.)"),
    ("trowsgeneraldire19142trow", 141, "*Holbrook Mfg Co soap 18th c Coles J C."),
]


def claims() -> dict:
    """{volume: {claim key: claim}}"""
    out = {}

    def put(v, key, leaf, value, quote, etype, conf, note=None):
        c = cite(v, leaf, value, quote, etype, confidence=conf, method="agent-read")
        if note:
            c["note"] = note
        c["derived"] = "2026-11-04 (PIPELINE #37)"
        assert key not in out.setdefault(v, {}), f"{v}: {key} twice"
        out[v][key] = c

    for v, leaf, etype, quote, conf in STAR_IS_RACE:
        put(v, "race_marker", leaf, "*", quote, etype, conf)
    for v, form, leaf, etype, quote, conf in TEXTUAL:
        put(v, "race_marker", leaf, form, quote, etype, conf)
    for v, leaf, etype, quote, conf, note in EASTERN_DISTRICT:
        put(v, "star_meaning", leaf, "eastern_district", quote, etype, conf, note)
    for v, leaf, quote in ADVERTISER:
        put(v, "star_meaning", leaf, "advertiser", quote, "listing", "medium")
    for v, cs in out.items():
        assert not (cs.get("race_marker", {}).get("value") == "*" and "star_meaning" in cs), \
            f"{v}: a star that is race cannot also mean something else"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    todo = claims()
    changed = 0
    for v, cs in sorted(todo.items()):
        path = SIDECARS / f"ia_{v}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        book = doc.setdefault("book_says", {})
        # an earlier reading of the same value stays: Ogden's and Trow 1859's were read on the
        # image, with a note. One that disagrees is a question, not something to overwrite
        for k, c in cs.items():
            old = book.get(k)
            if old and old.get("value") != c["value"] and not old.get("derived", "").endswith(
                    "(PIPELINE #37)"):
                raise SystemExit(f"{v}: {k} is {old.get('value')!r} in the sidecar, {c['value']!r} "
                                 f"here -- settle which before writing")
        diff = [k for k, c in cs.items() if book.get(k) != c
                and not (book.get(k) and "derived" not in book[k])]
        if not diff:
            continue
        changed += 1
        print(f"{v:30s} " + "  ".join(f"{k}={cs[k]['value']!r} (leaf {cs[k]['leaf']}, "
                                      f"{cs[k]['confidence']})" for k in diff))
        if args.write:
            book.update({k: cs[k] for k in diff})
            path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    race = sum(1 for cs in todo.values() if "race_marker" in cs)
    stars = sum(1 for cs in todo.values() if cs.get("race_marker", {}).get("value") == "*")
    print(f"{len(todo)} volumes: race_marker on {race} ({stars} `*`, {race - stars} textual), "
          f"star_meaning on {sum(1 for cs in todo.values() if 'star_meaning' in cs)}; "
          f"{changed} sidecars {'written' if args.write else 'would change (--write)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
