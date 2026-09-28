#!/usr/bin/env python3
"""
Name a directory's sections from the titles it prints. Used by survey_derive.py `sections`.

A directory binds several things between two covers: the residential alphabet, a second district's
alphabet, "names too late", a street guide, a classified business directory, a municipal register,
an index to advertisers, advertising. The letter vote (detect_listing_bounds) finds the ALPHABETS
and nothing else, and the parts that matter most for a business-directory reader are the ones it
cannot see at all -- a classified directory sorts names within each TRADE, so it forms no alphabet.
Measured 2026-09-23: 1883BPL's business directory (leaves 1347-1578, running heads like
"CLOTHING-- COAL AND WOOD.", "MACHINISTS-- MARBLE & GRANITE WORKERS") produced no section at all.

What every one of those parts does have is a TITLE PAGE: "LAIN'S BROOKLYN BUSINESS DIRECTORY"
(1883BPL leaf 1347), "BUSINESS DIRECTORY ... CITY OF BROOKLYN 1868-69" (1869BPL leaf 741),
"SMITH'S BROOKLYN DIRECTORY, EASTERN DISTRICT" (micro_IABROOKLYN_0036 leaf 355). So a page's kind is
read from the display lines at its top, and a section runs from a title page to the next.

Guards, each a measured false positive:
  * "CITY AND BUSINESS DIRECTORY" is the whole VOLUME's title (Lain 1869-1883), printed as the
    listing's own caption on 1883BPL leaf 27 -- not a business section.
  * "... and BUSINESS ADVERTISER" (Reynolds' Williamsburgh) is the volume's advertising.
  * "INDEX TO BUSINESS DIRECTORY" is an index, and comes before the business kind.
  * OCR spells DISTRICT "DISTRIOT" (micro_IABROOKLYN_0036 leaf 355).
"""
from __future__ import annotations

import re

TOP_LINES = 10           # display lines searched for a title
CAPS_SHARE = 0.6         # a title line is mostly capitals
TITLE_WORDS = 6          # ...or a short line of capitalised words
# words a title-case heading leaves in lower case: "Names too Late for Classification"
SMALL_WORDS = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "the", "to", "too"}
CONTENTS_RX = re.compile(r"(?:[-.·]{2,}|\s-)\s*\d+\s*$")   # a contents line ends in its page

# (kind, pattern) -- first match wins, so the order is part of the rule
KINDS = [
    # the "&" OCRs as anything: "CITY i. BUSINESS" (1875BPL), "CITY A BUSINESS" (1884BPL),
    # "CITY 1 BUSINESS", "CITY 4 BUSINESS" -- all the running head of the ADVERTISING pages
    ("volume_title", re.compile(r"CITY\s*(AND|\S{0,2})\s*BUSINESS\s+DIRECTORY|BUSINESS\s+ADVERTISER",
                                re.I)),
    # "Classified Business Lists ... Furnished at Short Notice" is an addressing-service ad that
    # recurs across Lain (1886BPL leaf 10) and Trow (1922/23) -- advertising, not a section
    ("advertiser", re.compile(r"CLASSIFIED\s+BUSINESS\s+LISTS", re.I)),
    # ...but an index TO THE BUSINESS DIRECTORY is part of that section: Hope & Henderson 1856
    # (micro_IABROOKLYN_0035) titles its business directory at leaf 537 and prints its index at
    # 541, and an index kind there cut a real section off after four leaves
    ("index", re.compile(r"INDEX\s+TO\b(?!.*BUSINESS)", re.I)),
    ("late_names", re.compile(r"TOO\s+LATE|ADDITIONAL\s+NAMES|NEW\s+NAMES|REMOVALS|OMISSIONS", re.I)),
    ("street_guide", re.compile(r"STREET\s+(AND\s+AVENUE\s+)?DIRECTORY|STREET\s+GUIDE|AVENUE\s+AND\s+STREET",
                                re.I)),
    ("business", re.compile(r"BUSINESS\s+DIRECTORY|CLASSIFIED|BUSINESS\s+CLASSIFICATION", re.I)),
    ("nurses", re.compile(r"\bNURSES\b", re.I)),
    ("register", re.compile(r"\bREGISTER\b|CHURCHES|CIVIL\s+LIST|MUNICIPAL", re.I)),
    ("appendix", re.compile(r"\bAPP?ENDIX\b", re.I)),
    # EA8TEEN DISTRICT (1856BPL leaf 405) and DISTRIOT (micro_IABROOKLYN_0036 leaf 355): the
    # OCR of these display lines is poor, so the direction word is only loosely required
    ("district", re.compile(r"\b(WEST\w*|EA\w{3,6}|NORTH\w*|SOUTH\w*)\s+DIS\w*|"
                            r"WILLIAMSBURGH?\s+DIRECTORY", re.I)),
    ("advertiser", re.compile(r"\bADVERTISER\b", re.I)),
    # "<PLACE> DIRECTORY" as a whole line: a village or district with a listing of its own. The
    # Morrisania and Tremont volume (bronxboroughdire1871) binds three -- Morrisania, then
    # HIGHBRIDGEVILLE DIRECTORY, then Tremont -- and the second and third are too short to form
    # an alphabet the letter vote can see. Only a candidate: survey_derive.sections() keeps it
    # when the page is a page of entries AND the place is not the main listing's own
    # ("BROOKLYN DIRECTORY" is the running head of half the corpus's ad pages).
    # OCR-tolerant at both ends: a mangled folio in front ("IT'i", "2") and DIRECTORY itself
    # misread ("DIEECTORY", "DlllECTuJIY") -- any D.......Y word of that length
    ("place_directory", re.compile(r"^(?:\S{1,5}\s+)?([A-Z][A-Z'.]{3,}(?:\s+[A-Z][A-Z'.]+)?)\s+"
                                   r"D[A-Za-z]{6,8}Y\W*$")),
]
PLACE_RX = KINDS[-1][1]
# kinds that are someone's residence or a supplement to the residential list
RESIDENTIAL = {"district", "late_names"}
# kinds that do not END the section they appear inside: ad pages are bound through everything
TRANSPARENT = {"advertiser", "volume_title"}


def page_title(lines_by_y: list) -> tuple:
    """-> (kind, text) for the first title-like line among a page's top lines, or (None, None).
    `lines_by_y` is the page's line texts in top-to-bottom order."""
    seen, fallback = 0, None
    for t in lines_by_y:
        letters = [c for c in t if c.isalpha()]
        # only lines with some text count toward the window: OCR crumbs from a side banner
        # (`O`, `>`, `2`) pushed Flushing 1891/92's "Business Directory," to the 11th line
        if len(letters) < 3:
            continue
        seen += 1
        if seen > TOP_LINES:
            break
        words = [w for w in t.split() if any(c.isalpha() for c in w)]
        # Display type is either mostly capitals, or a SHORT line of capitalised words: Boyd's
        # Flushing 1891/92 opens its business section (leaf 199) with "Business Directory,"
        # in title case, which the capitals rule alone missed. Title case keeps its small words
        # in lower case: 1906BPL's leaf 8 is "Names too Late for Classification", ~80 real
        # entries the survey filed as front matter while the rule wanted every word capitalised.
        caps = [w for w in words if w.lstrip("\"'(")[:1].isupper()]
        titled = 0 < len(words) <= 4 and len(caps) == len(words)
        # ...and ONLY for "names too late": letting small words through for every kind read a
        # copyright notice ("the Southern District of New York") as a residential `district`
        # title on 8 volumes. A contents line ("Additional Names and Removals ---- 731") is not a
        # title either.
        loose = (0 < len(words) <= TITLE_WORDS and len(caps) >= min(2, len(words))
                 and all(w in caps or w.lower().strip(".,") in SMALL_WORDS for w in words)
                 and not CONTENTS_RX.search(t))
        if len(letters) < 6 or (sum(c.isupper() for c in letters) < CAPS_SHARE * len(letters)
                                and not titled and not loose):
            continue
        shouting = sum(c.isupper() for c in letters) >= CAPS_SHARE * len(letters)
        for kind, rx in KINDS:
            if rx.search(t):
                if not (shouting or titled) and kind != "late_names":
                    break
                if kind != "place_directory":
                    return kind, t.strip()[:90]
                fallback = fallback or (kind, t.strip()[:90])
                break
    # a bare "<PLACE> DIRECTORY" yields to anything more specific in the window: Smith 1856
    # prints "BROOKLYN DIRECTORY," ABOVE "EASTERN DISTRICT,"
    return fallback or (None, None)


def _self_test():
    assert page_title(["LAIN'S", "BEOOKL YN", "BUSINESS DIRECTORY."])[0] == "business"
    assert page_title(["BROOKLYN CITY AND BUSINESS DIRECTORY. Alphabetical"])[0] == "volume_title"
    assert page_title(["INDEX TO BUSINESS DIRECTORY."])[0] == "business"
    assert page_title(["INDEX TO ADVERTISEMENTS."])[0] == "index"
    assert page_title(["BROOKLYN CITY i. BUSINESS DIRECTORY."])[0] == "volume_title"
    assert page_title(["WM. KNABE", "BUSINESS DIRECTORY", "FOR THE", "CITY OF BROOKLYN."])[0] == "business"
    assert page_title(["SMITH'S", "BROOKLYN DIRECTORY,", "EASTERN DISTRIOT,"])[0] == "district"
    assert page_title(["BROOKLYN DIRECTORY,", "EA8TEEN DISTRICT,"])[0] == "district"
    assert page_title(["NAMES TOO LATE FOR INSERTION IN REGULAR ORDER"])[0] == "late_names"
    assert page_title(["Names too Late for Classification",
                       "Adams Arthur D syrup 759 Park pi h 1031"])[0] == "late_names"
    assert page_title(["Bay Ridge Outfitter 5101 3d av"]) == (None, None), "an entry, not a title"
    assert page_title(["the Southern District of New York"]) == (None, None), "copyright notice"
    assert page_title(["Additional Names and Removals ------ 731"]) == (None, None), "contents"
    assert page_title(["Ahman Gustav steward h 421 50th"]) == (None, None)
    assert page_title(["STREET AND AVENUE DIRECTORY"])[0] == "street_guide"
    assert page_title(["Abbott John, grocer, 12 Pine"]) == (None, None), "entries are not titles"
    assert page_title(["FLUSHING DIRECTORY.", "125", "Business Directory,"])[0] == "business"
    assert page_title(["LUMDER, LIME", "Geo. B. Roe & Co.,", "WOOD. Ottlce", "Yard, Ft. of", "125",
                       "FLUSHING DIRECTORY.", "O", ">", "2", "Business Directory,"])[0] == "business"
    assert page_title(["Lain & Co. business directory publishers, 213 Montague"]) == (None, None)
    assert page_title(["Classified Business Lists", "OF ANY"])[0] == "advertiser"
    assert page_title(["IT'i HIOUBKIDGEVILLE DIEECTORY"])[0] == "place_directory"
    assert PLACE_RX.match("2 MOREISANIA DIRECTORY.").group(1) == "MOREISANIA"
    assert page_title(["LAIN'S BROOKLYN DIRECTORY ADVERTISER."])[0] == "advertiser"
    assert page_title(["REYNOLDS' CITY DIRECTORY AND BUSINESS ADVERTISER"])[0] == "volume_title"
    print("self-test OK")


if __name__ == "__main__":
    _self_test()
