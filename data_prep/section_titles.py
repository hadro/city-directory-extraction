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

# (kind, pattern) -- first match wins, so the order is part of the rule
KINDS = [
    # the "&" OCRs as anything: "CITY i. BUSINESS" (1875BPL), "CITY A BUSINESS" (1884BPL),
    # "CITY 1 BUSINESS", "CITY 4 BUSINESS" -- all the running head of the ADVERTISING pages
    ("volume_title", re.compile(r"CITY\s*(AND|\S{0,2})\s*BUSINESS\s+DIRECTORY|BUSINESS\s+ADVERTISER",
                                re.I)),
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
]
# kinds that are someone's residence or a supplement to the residential list
RESIDENTIAL = {"district", "late_names"}
# kinds that do not END the section they appear inside: ad pages are bound through everything
TRANSPARENT = {"advertiser", "volume_title"}


def page_title(lines_by_y: list) -> tuple:
    """-> (kind, text) for the first title-like line among a page's top lines, or (None, None).
    `lines_by_y` is the page's line texts in top-to-bottom order."""
    for t in lines_by_y[:TOP_LINES]:
        letters = [c for c in t if c.isalpha()]
        if len(letters) < 6 or sum(c.isupper() for c in letters) < CAPS_SHARE * len(letters):
            continue
        for kind, rx in KINDS:
            if rx.search(t):
                return kind, t.strip()[:90]
    return None, None


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
    assert page_title(["STREET AND AVENUE DIRECTORY"])[0] == "street_guide"
    assert page_title(["Abbott John, grocer, 12 Pine"]) == (None, None), "entries are not titles"
    assert page_title(["REYNOLDS' CITY DIRECTORY AND BUSINESS ADVERTISER"])[0] == "volume_title"
    print("self-test OK")


if __name__ == "__main__":
    _self_test()
