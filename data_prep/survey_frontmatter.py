#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Phase 0b of the corpus survey: what the BOOK says, cited to the leaf that says it.

See docs/SURVEY_PLAN.md. `survey_census.py` recorded what IA's catalog claims. This reads the
volume's own front matter and writes `book_says` -- and every single claim carries the leaf it
came from, the image URL a human can open, and the verbatim quote. A claim with no leaf is not
a claim; it stays in `catalog_says`.

    python3 data_prep/survey_frontmatter.py                    # every censused ia volume
    python3 data_prep/survey_frontmatter.py --ident 1906BPL -v # one volume, show the leaves
    python3 data_prep/survey_frontmatter.py --self-test        # offline; no network

Why this is cheap
-----------------
The title page is IN the hOCR, so confirming publisher/year/title needs no image read for most
volumes. And the front matter is reachable WITHOUT the 21.7 GB phase-1 sweep: the pageindex gives
per-leaf byte offsets, and leaves 0..N are one CONTIGUOUS range, so it is a single HTTP Range
request per volume. Measured: 1906BPL's first 30 leaves are 5.75 MB of a 305 MB file (1.9%);
longworthsameric1798newy 0.73 MB of 14.3 MB. Front matter begins at byte ~583, i.e. essentially
the head of the file, which is why the 200-instead-of-206 fallback below is safe to truncate.

The evidence hierarchy (measured; see the plan doc)
--------------------------------------------------
1. the printed title page and its copyright line -- the volume's own claim
2. a microfilm target card -- the filming library's cataloging, not the book. BPL's Brooklyn
   microfilm run opens with one, and it OCRs cleanly even where the book does not:
   `Spooner's Brooklyn Directory, for the year 1826 ... Published by Alden Spooner ... June, 1826.`
3. TOC / section heads / an inline legend at the listing head
X  modern scan cover sheets, bookplates, `Digitized by the Internet Archive in 2013`, collection
   stamps -- NOISE. 1906BPL leaf 0 is a Brooklyn Public Library PDF-instructions sheet, and taking
   it for the title page would attribute the volume to the wrong century of institution.

Years get attested three ways, on purpose. Digits are the fragile channel -- early volumes OCR
them badly -- so the spelled-out copyright year ("IN THE YEAR NINETEEN HUNDRED AND SIX") and the
regnal formula ("Twenty-third Year of American Independence" = 1775 + 23 = 1798) are extracted as
independent confirmations. longworthsameric1798newy is the case that motivated it: its title page
reads `ATSD- CITY DIRECTORY* 70R THE ?. TivrtHy-thlrd` and the only clean date on the page is the
independence formula.

What this deliberately does NOT do: guess. Where the front matter yields nothing, the volume is
marked `needs-image-read` with the candidate leaves already chosen, and phase 3 spends ONE image
on it. Silence is reported, never filled in.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIDECAR = HERE / "survey"
CACHE = REPO / "data" / "ia_cache"

sys.path.insert(0, str(HERE))
from ia_volume_to_jsonl import Item, hocr_lines         # noqa: E402
from survey_report import year_agrees                   # noqa: E402  (the conflict gate)

UA = {"User-Agent": "Mozilla/5.0 (research; city-directory corpus survey; +josh)"}
DL = "https://archive.org/download"

FRONT_LEAVES = 30          # measured: deep enough for ad-heavy volumes (Trow's key page ~c14)
IMG_WIDTH = 1400           # the width a phase-3 agent gets; keeps the citation and the read equal


# ---------------------------------------------------------------------------- citations

def page_image(ident: str, leaf: int, width: int = IMG_WIDTH) -> str:
    """The citable image for a leaf. Verified against the hOCR leaf index, visually, on
    1906BPL leaf 1 -- `page/n1` IS hOCR leaf 1 (the Upington title page). Leaf-indexed, 0-based,
    same integer as the hOCR pageindex and the IIIF canvas."""
    return f"{DL}/{ident}/page/n{leaf}_w{width}.jpg"


def canvas(ident: str, leaf: int) -> str:
    return f"https://iiif.archive.org/iiif/{ident}${leaf}/canvas"


def cite(ident, leaf, value, quote, evidence_type, confidence="medium", method="hocr-text"):
    return {"value": value, "leaf": leaf, "canvas": canvas(ident, leaf),
            "image": page_image(ident, leaf), "evidence_type": evidence_type,
            "quote": quote.strip()[:200], "method": method, "confidence": confidence}


# ---------------------------------------------------------------------------- leaf classes

# Order matters: noise is tested FIRST, so a Durst bookplate that happens to name a directory
# cannot be promoted to a title page.
NOISE = [
    (re.compile(r"digitized by the internet archive", re.I), "ia-digitization-notice"),
    (re.compile(r"archive\.org/details/", re.I), "ia-digitization-notice"),
    (re.compile(r"seymour\s+durst|old\s+york\s+library|avery architectural", re.I), "bookplate"),
    (re.compile(r"reynolds historical|genealogy collection", re.I), "collection-stamp"),
    (re.compile(r"allen county public library", re.I), "collection-stamp"),
    (re.compile(r"search bar|keyword search|type keywords|\.org\b.*\bemail|bcref@", re.I),
     "modern-scan-coversheet"),
    (re.compile(r"please leave this book|loaned book", re.I), "bookplate"),
]

DIRECTORY_WORD = re.compile(r"\b(directory|register|almanac[k]?)\b", re.I)
PUBLISHER_CUE = re.compile(r"\b(published|printed|publisher|proprietor)\b", re.I)
COPYRIGHT_CUE = re.compile(r"entered according to act|copyright|librarian of congress", re.I)
# What a title page says when OCR has eaten the display type that says "DIRECTORY".
TITLE_CUE = re.compile(r"compiled by|for the year ending|containing\b.{0,30}\bnames", re.I)
TOC_CUE = re.compile(r"^\s*(table of )?contents\b|^\s*index to\b", re.I)
LEGEND_CUE = re.compile(
    r"\bstands? for\b|\bsignifies\b|abbreviation|explanation of|\bexplanations?\b", re.I)
# One gloss: an abbreviation followed by its expansion, semicolon-delimited. Three or more of
# these on a leaf means a dedicated key page rather than a one-line note at the listing head.
GLOSS_RX = re.compile(r"\b[a-z]{1,6}\.?\s+[a-z]{3,}\s*;\s*[a-z]{1,6}\.?\s+[a-z]{3,}", re.I)
# A microfilm target card: a short leaf that states place + year + imprint, filmed ahead of p.1.
TARGET_CUE = re.compile(r"\b(published|printed)\s+by\b", re.I)


def classify(text: str, n_lines: int) -> str:
    low = text.lower()
    for rx, name in NOISE:
        if rx.search(low):
            return name
    # The copyright statement is usually on its OWN leaf -- the title-page verso -- and it never
    # says "directory". Requiring the word there cost 1862BPL its best evidence: leaf 2 reads
    # "Entered according to Act of Congress, in the year one thousand eight hundred and sixty-two,
    # By J. LAIN AND COMPANY" and scored `other`. It carries the year in words, the publisher AND
    # the printer, so it is first-class evidence in its own right.
    if COPYRIGHT_CUE.search(low):
        return "title_page" if DIRECTORY_WORD.search(low) else "copyright_page"
    # A title page need not print the word "directory" in readable type -- it is the largest
    # display type on the page, which is exactly what OCR drops. 1862BPL leaf 1 OCR'd as
    # "THE / BROOKLYN CITY / ... / FOR / THE YEAR ENDING MAY 1st, / COMPILED BY J. LAIN. /
    # PUBLISHED BY J. LAIN AND COMPANY." -- no "DIRECTORY" anywhere, unmistakably a title page.
    if TITLE_CUE.search(low) and PUBLISHER_CUE.search(low):
        return "title_page"
    if DIRECTORY_WORD.search(low) and PUBLISHER_CUE.search(low):
        # A target card is short and telegraphic; a title page is set as display type but the
        # hOCR of one still runs longer once the imprint and price lines are counted.
        return "target_card" if n_lines <= 12 else "title_page"
    if TOC_CUE.search(low):
        return "contents"
    if LEGEND_CUE.search(low):
        return "legend"
    if DIRECTORY_WORD.search(low):
        return "front_matter"
    return "other"


# ---------------------------------------------------------------------------- year extraction

UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
         "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
            "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
            "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
            "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
            "thirtieth": 30, "fortieth": 40, "fiftieth": 50, "sixtieth": 60}

YEAR_DIGITS = re.compile(r"\b(1[78]\d\d|19[0-4]\d)\b")
INDEPENDENCE = re.compile(
    r"([a-z]+(?:[-\s][a-z]+)?)\s+year\s+of\s+(?:american\s+)?independence", re.I)


def words_to_number(phrase: str):
    """'nineteen hundred and six' -> 1906; 'twenty-third' -> 23. None when it does not parse.

    Deliberately strict about what it will accept: OCR on a copyright line is noisy, and a
    lenient accumulator will happily turn garbage into a plausible year. Every token must be a
    known number word or one of `hundred`/`thousand`/`and`.
    """
    toks = re.split(r"[\s\-]+", phrase.lower().strip())
    total, cur, seen = 0, 0, False
    for t in toks:
        t = t.strip(".,")
        if not t or t == "and":
            continue
        if t in ORDINALS:
            cur += ORDINALS[t]; seen = True
        elif t in UNITS:
            cur += UNITS[t]; seen = True
        elif t == "hundred":
            cur = (cur or 1) * 100; seen = True
        elif t == "thousand":
            total += (cur or 1) * 1000; cur = 0; seen = True
        else:
            return None
    return (total + cur) if seen else None


def years_from(text: str):
    """-> [(year, method, quote)] -- every independent attestation on this leaf."""
    out = []
    for m in YEAR_DIGITS.finditer(text):
        out.append((int(m.group(1)), "digits", text[max(0, m.start() - 40):m.end() + 40]))

    # Spelled out, as in a copyright line. Anchored on `in the year` so a stray "eighteen" in
    # prose cannot become a date.
    for m in re.finditer(r"in the year\s+([a-z][a-z\s\-]{3,60}?)\s*(?:,|\bby\b|$)", text, re.I):
        n = words_to_number(m.group(1))
        if n and 1780 <= n <= 1945:
            out.append((n, "words", m.group(0)))

    for m in INDEPENDENCE.finditer(text):
        n = words_to_number(m.group(1))
        # The Nth year of independence runs from 4 July 1775+N. 23rd -> 1798, and that is the
        # only clean date on longworthsameric1798newy's title page.
        if n and 1 <= n <= 170:
            out.append((1775 + n, "independence-formula", m.group(0)))
    return out


# The keyword half of each pattern is case-insensitive; the captured NAME is not. A blanket re.I
# would let `[A-Z]` match a lowercase word, so these use scoped `(?i:...)` groups instead and the
# name must still start with a capital -- which is what distinguishes an imprint from prose.
PUBLISHED_BY = re.compile(
    r"(?i:(?:published|printed)\s+(?:and\s+\w+\s+)?by)\s+"
    r"([A-Z][\w'&.\- ]{2,50}?)(?:[,.]|\s+at\s|\s+in\s|$)")
PUBLISHER_SUFFIX = re.compile(r"^([A-Z][\w'&.\- ]{2,50}?),\s*(?i:publisher|proprietor)\b", re.M)
ENTERED_BY = re.compile(
    r"(?i:act of congress[^,]*,?\s*in the year[^,]*,\s*by)\s+([A-Z][\w'&.\- ]{2,60})")
VOLUME_RX = re.compile(r"\bvol(?:ume)?\.?\s+([IVXLC]{1,8})\b", re.I)
ANNUAL_RX = re.compile(r"\b(\w+(?:[-\s]\w+)?)\s+annual\b", re.I)
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


ADVERTISER_RX = re.compile(r"advertiser|advertisements?\b", re.I)
PROSE_CHARS = 55           # a line longer than this is running prose, not display type
PROSE_SHARE = 0.35         # measured: 1857BPL's ad leaf runs 0.38, its title page 0.00
MIN_STRENGTH = 4           # below this the best candidate is a guess, not a reading


def title_strength(kind: str, text: str, lines) -> int:
    """How much this leaf looks like the volume's own title statement.

    The competition is not other title pages, it is ADVERTISING. These volumes front-load ads and
    ad copy carries every cue a title page has. 1857BPL leaf 4 opens
    "BROOKLYN DIRECTORY ADVERTISER. / ON BROOKLYN HEIGHTS ... Established May, 1837" -- it beat
    the real title page (leaf 27, "SMITH'S / BROOKLYN DIRECTORY, / FOR THE YEAR ENDING /
    MAY 1st, 1857") and dated the volume 1837.

    Two things separate them, and the line COUNT is not one of them (23 vs 16, the wrong way
    round). An ad section head names itself "advertiser", and ad copy is PROSE where a title page
    is display type in short lines.

    Target cards are scored on the same scale rather than exempted: the microfilm tier is 49
    volumes and a blanket "only title_page counts" would escalate every one to an image read. A
    genuine card clears the bar on its own merits -- micro_IABROOKLYN_0005 scores 6.
    """
    if kind not in ("title_page", "target_card", "copyright_page"):
        return 0
    head = " ".join(lines[:3]).lower()
    copyright_ = bool(COPYRIGHT_CUE.search(text))
    prose = (sum(1 for ln in lines if len(ln) > PROSE_CHARS) / len(lines)) if lines else 0
    return (4 * copyright_
            + 3 * bool(DIRECTORY_WORD.search(head))
            + 2 * bool(VOLUME_RX.search(text))
            # ANY attestation counts, not just digits. A copyright page states its year in words
            # ("one thousand eight hundred and sixty-two") and would otherwise score zero here.
            + 2 * bool(years_from(text))
            + bool(PUBLISHER_CUE.search(text))
            - 5 * bool(ADVERTISER_RX.search(head))
            # The prose penalty targets ADVERTISING COPY. A copyright statement is a long legal
            # sentence by nature, so the penalty must not apply once the formula has identified
            # the leaf -- it scored 1862BPL's copyright verso down to 1 and escalated it.
            - 3 * (prose > PROSE_SHARE and not copyright_))


def roman_to_int(s: str):
    s = s.upper()
    if not s or any(c not in ROMAN for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = ROMAN[c]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total or None


# ---------------------------------------------------------------------------- hOCR fetch

def front_hocr(ident: str, n_leaves: int = FRONT_LEAVES, cache: Path = CACHE):
    """-> [(leaf, [line, ...]), ...] for leaves 0..n-1, in ONE http Range request.

    Item.hocr_page() would issue one request per leaf; at 30 leaves x 184 volumes that is 5,520
    requests against IA for data that is contiguous on disk. The pageindex gives the byte span,
    so this asks for it once.

    IA's storage node sometimes ignores Range and answers 200 with the whole file -- 1.6 GB for
    trowsgeneraldire1917trow. The read is therefore bounded: at most `end` bytes are pulled off
    the socket and the connection is dropped. That is safe precisely because the front matter
    starts at byte ~583, so the first `end` bytes of the whole file contain the same span.
    """
    item = Item(ident, cache)
    idx = item.index
    n = min(n_leaves, len(idx))
    if n == 0:
        return []
    start, end = idx[0][2], idx[n - 1][3]

    whole = cache / f"{ident}_hocr.html"
    if whole.exists() and whole.stat().st_size > end:
        blob = whole.open("rb")
        blob.seek(0)
        buf = blob.read(end)
        blob.close()
        base = 0
    else:
        req = urllib.request.Request(f"{DL}/{ident}/{ident}_hocr.html", headers=dict(UA))
        req.add_header("Range", f"bytes={start}-{end - 1}")
        with urllib.request.urlopen(req, timeout=300) as r:
            partial = r.status == 206
            buf = r.read(end if not partial else end - start)
        base = start if partial else 0

    out = []
    for leaf in range(n):
        a, b = idx[leaf][2] - base, idx[leaf][3] - base
        if a < 0 or b > len(buf):
            continue
        markup = buf[a:b].decode("utf-8", "replace")
        lines = [t.strip() for _box, t in hocr_lines(markup) if t.strip()]
        out.append((leaf, lines))
    return out


# ---------------------------------------------------------------------------- the survey

def survey_volume(ident: str, n_leaves: int = FRONT_LEAVES, verbose: bool = False):
    leaves = front_hocr(ident, n_leaves)
    classes, evidence = {}, []
    for leaf, lines in leaves:
        text = "\n".join(lines)
        kind = classify(text, len(lines)) if lines else "blank"
        classes[leaf] = {"class": kind, "lines": len(lines), "chars": len(text)}
        if verbose:
            print(f"  leaf {leaf:3d}  {kind:24s} {len(lines):4d} lines  "
                  f"{(lines[0][:54] if lines else '')}", file=sys.stderr)
        if kind in ("title_page", "target_card", "copyright_page", "legend",
                    "contents"):
            evidence.append((leaf, kind, text, lines))

    # Claims are taken from the STRONGEST title page, not the first one. 1906BPL leaf 3 is an
    # Association of American Directory Publishers page that names the directory and its
    # publisher, so it classifies as a title page and sits before nothing -- but on a volume where
    # such a leaf came first, taking "the first title_page" would cite the wrong page and inherit
    # its year (leaf 3's is 1898, the association's founding). Score the real thing higher.
    # The competition is not other title pages, it is ADVERTISING. These volumes front-load ads,
    # and ad copy contains every cue a title page has. 1857BPL leaf 4 opens
    # "BROOKLYN DIRECTORY ADVERTISER. / ON BROOKLYN HEIGHTS ... Established May, 1837" -- it
    # scored as a title page and reported the volume's year as 1837 (it is 1857; the real title
    # page is leaf 27, "SMITH'S / BROOKLYN DIRECTORY, / FOR THE YEAR ENDING / MAY 1st, 1857").
    # Two things separate them and neither is the line count: an ad section head SAYS
    # "advertiser", and ad copy is PROSE while a title page is display type in short lines.
    evidence.sort(key=lambda it: (-title_strength(*it[1:]), it[0]))
    best_strength = title_strength(*evidence[0][1:]) if evidence else 0

    book: dict = {}
    # A copyright page is the strongest source there is for year and publisher: it is a legal
    # formula, set in small consistent type, and it states the year in words.
    conf_for = {"title_page": "high", "copyright_page": "high", "target_card": "medium"}

    # --- year, from every channel that speaks, on the best-ranked leaf that carries one
    year_claims = []
    for leaf, kind, text, _lines in evidence:
        if kind not in ("title_page", "target_card", "copyright_page"):
            continue
        for yr, how, quote in years_from(text):
            if 1780 <= yr <= 1945:
                year_claims.append((leaf, kind, yr, how, quote))
    if year_claims:
        # Two preferences, in order. First the page: a year must come from the page the other
        # claims came from, or a volume inherits a date printed in someone else's advertisement.
        # Then the channel: prefer a non-digit attestation, because on a degraded early title page
        # the digits are exactly what OCR mangles.
        primary = evidence[0][0] if evidence else None
        rank = {"words": 0, "independence-formula": 0, "digits": 1}
        best = sorted(year_claims, key=lambda c: (c[0] != primary, rank[c[3]], c[0]))[0]
        leaf, kind, yr, how, quote = best
        book["year"] = cite(ident, leaf, yr, quote, kind,
                            "high" if how != "digits" else conf_for.get(kind, "medium"),
                            method="hocr-text")
        book["year"]["attestation"] = how
        others = sorted({c[2] for c in year_claims})
        if len(others) > 1:
            book["year"]["other_years_on_page"] = others
        book["year_attestations"] = [
            {"year": y, "how": h, "leaf": lf, "quote": q.strip()[:120]}
            for lf, _k, y, h, q in year_claims]

        # year_published vs year_covered. These are genuinely different and the corpus disagrees
        # with itself about which one `year` means. 1862BPL is copyrighted 1861 and covers "THE
        # YEAR ENDING MAY 1st, 1862"; the CSV says 1862. Collapsing them to one number would make
        # a correct catalog cell look wrong and invite someone to "fix" it.
        pub = next((c for c in year_claims if c[1] == "copyright_page"), None)
        cov = next((c for c in year_claims
                    if c[1] in ("title_page", "target_card")
                    and re.search(r"for the year", c[4], re.I)), None)
        if pub:
            book["year_published"] = cite(ident, pub[0], pub[2], pub[4], pub[1], "high")
        if cov:
            book["year_covered"] = cite(ident, cov[0], cov[2], cov[4], cov[1], "high")
        if pub and cov and pub[2] != cov[2]:
            book["year"]["note"] = (
                f"published {pub[2]} (leaf {pub[0]}), covers {cov[2]} (leaf {cov[0]}) "
                f"-- not a conflict")

    # --- publisher / printer, title, volume number
    for leaf, kind, text, lines in evidence:
        if kind not in ("title_page", "target_card", "copyright_page"):
            continue
        flat = re.sub(r"\s+", " ", text)
        if "publisher" not in book:
            for rx, ev in ((ENTERED_BY, "copyright-line"), (PUBLISHED_BY, "imprint"),
                           (PUBLISHER_SUFFIX, "imprint")):
                m = rx.search(flat if rx is not PUBLISHER_SUFFIX else text)
                if m:
                    book["publisher"] = cite(ident, leaf, m.group(1).strip(" .,"), m.group(0),
                                             kind, conf_for.get(kind, "medium"))
                    book["publisher"]["evidence_detail"] = ev
                    break
        if "volume_number" not in book:
            m = VOLUME_RX.search(flat)
            if m and roman_to_int(m.group(1)):
                book["volume_number"] = cite(ident, leaf, roman_to_int(m.group(1)), m.group(0),
                                             kind, conf_for.get(kind, "medium"))
            else:
                m = ANNUAL_RX.search(flat)
                n = words_to_number(m.group(1)) if m else None
                if n:
                    book["volume_number"] = cite(ident, leaf, n, m.group(0), kind, "medium")
        if "title" not in book and kind == "title_page":
            # The title is the display type: the run of leading lines before the imprint. Stop at
            # the volume statement too -- "VOLUME LXXXIII / FOR THE YEAR" is edition metadata that
            # is captured separately, and letting it run makes every title in the corpus different
            # from the next year's for no reason.
            head = []
            for ln in lines[:10]:
                if (PUBLISHER_CUE.search(ln) or COPYRIGHT_CUE.search(ln)
                        or YEAR_DIGITS.search(ln) or VOLUME_RX.search(ln)
                        or re.match(r"\s*for the year\b", ln, re.I)):
                    break
                head.append(ln)
            if head and any(DIRECTORY_WORD.search(h) for h in head):
                book["title"] = cite(ident, leaf, " ".join(head)[:160], " / ".join(head),
                                     kind, "medium")

    structure = {
        "front_leaves_read": len(leaves),
        "classes": classes,
        "title_page_leaf": next((l for l, k, *_ in evidence if k == "title_page"), None),
        "copyright_page_leaf": next((l for l, k, *_ in evidence if k == "copyright_page"), None),
        "target_card_leaf": next((l for l, k, *_ in evidence if k == "target_card"), None),
        "contents_leaf": next((l for l, k, *_ in evidence if k == "contents"), None),
        # key_page is NOT always a separate page: micro_IABROOKLYN_0005 prints
        # "N. B. h. stands for house, n. for near, and c. for corner." inline at the listing head.
        "legend_leaves": [l for l, k, *_ in evidence if k == "legend"],
    }
    if structure["legend_leaves"]:
        leaf = structure["legend_leaves"][0]
        text, lns = next((t, ln) for l, _k, t, ln in evidence if l == leaf)
        m = LEGEND_CUE.search(text)
        quote = text[max(0, m.start() - 60):m.start() + 160] if m else text[:200]
        book["legend"] = cite(ident, leaf, "present", quote, "legend", "medium")
        # A dedicated key page runs a dense list of glosses ("av avenue; bldg building; ..."); an
        # inline legend is one sentence at the listing head ("h. stands for house, n. for near")
        # followed by entries. Line COUNT does not separate them -- 1906BPL's key page carries an
        # ad banner and 68 lines, which the count rule called inline. Gloss density does.
        defs = sum(1 for ln in lns if ln.count(";") >= 2 or GLOSS_RX.search(ln))
        book["legend"]["gloss_lines"] = defs
        book["legend"]["legend_location"] = (
            "dedicated-page" if defs >= 3 else "inline-at-listing-head")

    got = [k for k in ("year", "publisher", "title") if k in book]
    status = "frontmatter-done" if len(got) >= 2 else "needs-image-read"

    # A weak best candidate is not a reading, it is a guess with a citation attached.
    if evidence and best_strength < 4:
        status = "needs-image-read"
        structure["weak_title_page"] = best_strength
        for k in ("year", "publisher", "title", "volume_number"):
            if k in book:
                book[k]["confidence"] = "low"
    if status == "needs-image-read":
        # Choose the leaves phase 3 should spend its one image on, now, while the text is in hand.
        cands = [l for l, k, *_ in evidence
                 if k in ("title_page", "target_card", "copyright_page")]
        if not cands:
            cands = [l for l, c in sorted(classes.items())
                     if c["class"] not in ("blank",) + tuple(n for _r, n in NOISE)
                     and c["chars"] > 80][:3]
        structure["image_read_candidates"] = cands[:3]
        structure["image_read_urls"] = [page_image(ident, l) for l in cands[:3]]
    return book, structure, status


def _self_test():
    """Offline. Pins the two things that would silently corrupt the survey: mistaking a modern
    insert for the title page, and inventing a year out of noisy OCR."""
    # -- the noise that sits where a title page should be
    assert classify("Digitized by the Internet Archive in 2013", 3) == "ia-digitization-notice"
    assert classify("SEYMOUR DURST\nOld York Library\nAvery Architectural", 5) == "bookplate"
    assert classify("REYNOLDS HISTORICAL\nGENEALOGY COLLECTION", 4) == "collection-stamp"
    # 1906BPL leaf 0 -- a BPL PDF-instructions sheet that names the directory AND its publisher.
    # Noise must win over the directory/publisher cues or the volume gets the wrong attribution.
    assert classify("Upington's General Directory of the Borough of Brooklyn, 1906\n"
                    "Published by George Upington\nBrooklyn Public Library\n"
                    "To search for specific names, type keywords into the search bar", 12) \
        == "modern-scan-coversheet", "noise must be tested before the title-page cues"

    # -- 1906BPL leaf 1, the real title page
    tp = ("UPINGTON'S\nGENERAL DIRECTORY\nOF THE BOROUGH OF\nBROOKLYN\nCITY OF NEW YORK\n"
          "VOLUME LXXXIII\nFOR THE YEAR\n1906\nGEORGE UPINGTON, Publisher\n"
          "ENTERED ACCORDING TO ACT OF CONGRESS IN THE YEAR NINETEEN HUNDRED AND SIX, BY "
          "GEORGE UPINGTON, IN THE OFFICE OF THE LIBRARIAN OF CONGRESS AT WASHINGTON.")
    assert classify(tp, 15) == "title_page"
    ys = years_from(tp)
    assert (1906, "digits") in [(y, h) for y, h, _q in ys], "the printed year must be read"
    assert (1906, "words") in [(y, h) for y, h, _q in ys], "the copyright year must be read too"
    assert roman_to_int("LXXXIII") == 83, "Upington 1906 is volume 83"
    m = ENTERED_BY.search(re.sub(r"\s+", " ", tp))
    assert m and m.group(1).strip() == "GEORGE UPINGTON", f"got {m and m.group(1)!r}"

    # -- 1857BPL: an ad section head that beat the real title page and dated the volume 1837.
    # Both leaves classify as title_page; the SCORE has to separate them.
    ad = ["BROOKLYN DIRECTORY ADVERTISER.", "ON BROOKLYN HEIGHTS,",
          "106 Pierrepont street, corner of Clinton.",
          "ALPEED GREENLEAF, A.M., Proprietor and Principal.",
          "Established May, 1837, at an outlay of 130,000.",
          "Has two Departments, Junior and Senior, each consisting of three classes",
          "aided by Ten competent and thoroughly qualified teachers, beside lecture",
          "embraces all the branches of a thorough English Education, Mathematics,"]
    real = ["SMITH'S", "BROOKLYN DIRECTORY,", "FOR THE YEAR ENDING", "MAY 1st, 1857.",
            "GENERAL DIRECTORY OF THE INHABITANTS,", "AVENUE AND STREET GUIDE,", "AND AN",
            "APPENDIX."]
    assert classify("\n".join(ad), 23) == "title_page", "the ad DOES classify as one"
    s_ad = title_strength("title_page", "\n".join(ad), ad)
    s_real = title_strength("title_page", "\n".join(real), real)
    assert s_real > s_ad, f"the real title page must outscore the ad ({s_real} vs {s_ad})"
    assert s_ad < MIN_STRENGTH, f"the ad must fall below the escalation bar (scored {s_ad})"
    assert s_real >= MIN_STRENGTH, f"the real title page must clear it (scored {s_real})"
    # A target card must clear the bar on its own merits, or the 49-volume microfilm tier all
    # escalates to image reads.
    card = ["BROOKLYN, NEW YORK", "1826", "Spooner's Brooklyn Directory, for the year 1826.",
            "Brooklyn, N.Y. Published by Alden Spooner, at the office of the Star, "
            "No. 55 Fulton-street. June, 1826."]
    assert title_strength("target_card", "\n".join(card), card) >= MIN_STRENGTH, \
        "a genuine microfilm target card must not need an image read"
    assert title_strength("legend", "anything", ["anything"]) == 0, "only the two kinds score"

    # -- 1862BPL: the two leaves that a "must contain the word DIRECTORY" rule threw away.
    # Leaf 1 is the title page with the display type eaten by OCR; leaf 2 is the copyright verso,
    # which never says "directory" and is the strongest evidence in the whole volume.
    lain_title = ("THE\nBROOKLYN CITY\nFOR\nTHE YEAR ENDING MAY 1st,\nCOMPILED BY J. LAIN.\n"
                  "PUBLISHED BY J. LAIN AND COMPANY.\n"
                  "OFFICES: POST OFFICE BUILDING, MONTAGUE STREET")
    assert "directory" not in lain_title.lower(), "the premise: OCR dropped the display type"
    assert classify(lain_title, 11) == "title_page", "compiled-by + published-by is a title page"
    lain_copy = ("Entered according to Act of Congress, in the year one thousand eight hundred "
                 "and sixty-two,\nBy J. LAIN AND COMPANY,\nIn the Clerk's Office of the District "
                 "Court of the United States, for New York.\n"
                 "1TYHKOOP, HA1XEKBBCK * THOKAS, PBISTSBS,")
    assert classify(lain_copy, 6) == "copyright_page", "a copyright verso is its own class"
    assert title_strength("copyright_page", lain_copy, lain_copy.split("\n")) >= MIN_STRENGTH, \
        "a copyright page must be usable evidence, not an escalation"
    assert [y for y, h, _q in years_from(lain_copy) if h == "words"] == [1862], \
        "one thousand eight hundred and sixty-two"
    m = ENTERED_BY.search(re.sub(r"\s+", " ", lain_copy))
    assert m and m.group(1).strip().startswith("J. LAIN"), f"got {m and m.group(1)!r}"

    # -- micro_IABROOKLYN_0005 leaf 1, a microfilm target card (short, telegraphic)
    tc = ("BROOKLYN, NEW YORK\n1826\nSpooner's Brooklyn Directory, for the year 1826.\n"
          "Brooklyn, N.Y. Published by Alden Spooner, at the office of the Star, "
          "No. 55 Fulton-street. June, 1826.")
    assert classify(tc, 6) == "target_card", "a short imprint leaf is a target card"
    m = PUBLISHED_BY.search(re.sub(r"\s+", " ", tc))
    assert m and m.group(1).strip() == "Alden Spooner", f"got {m and m.group(1)!r}"

    # -- longworthsameric1798newy leaf 7: digits unreadable, the regnal formula is not
    lw = "AMERICAN ALMANACK, NEW-YORK REGISTER, CITY DIRECTORY, FOR THE " \
         "Twenty-third Year of American Independence"
    assert [y for y, h, _q in years_from(lw) if h == "independence-formula"] == [1798], \
        "1775 + 23 = 1798"

    # -- the word parser must refuse garbage rather than produce a plausible year
    assert words_to_number("nineteen hundred and six") == 1906
    assert words_to_number("one thousand eight hundred and fifty") == 1850
    assert words_to_number("twenty-third") == 23
    assert words_to_number("TivrtHy-thlrd") is None, "mangled OCR must not parse"
    assert words_to_number("in the office of") is None, "prose must not parse"
    assert words_to_number("") is None

    assert roman_to_int("XC") == 90 and roman_to_int("IV") == 4
    assert roman_to_int("ABBYY") is None, "non-roman must not parse"

    # -- a dedicated key page vs a one-line note. 1906BPL leaf 9 is a real ABBREVIATIONS key
    # sitting UNDER an ad banner, 68 lines long; a line-count rule called it "inline".
    key = "ABBREVIATIONS\nAcct. accountant; agl. agricultural; agt. agent; Ala. Alabama; al alley"
    assert GLOSS_RX.search(key), "a semicolon-delimited gloss run marks a dedicated key page"
    assert not GLOSS_RX.search("N. B. h. stands for house, n. for near, and c. for corner."), \
        "a one-sentence inline note is not a gloss run"
    assert LEGEND_CUE.search(key) and LEGEND_CUE.search("h. stands for house"), \
        "both legend forms must still be FOUND; only their location differs"

    # -- a citation is only a citation if it carries the leaf and a resolvable image
    c = cite("1906BPL", 1, 1906, "FOR THE YEAR 1906", "title_page")
    assert c["leaf"] == 1 and c["image"].endswith("/page/n1_w1400.jpg")
    assert c["canvas"] == "https://iiif.archive.org/iiif/1906BPL$1/canvas"
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true", help="offline; no network")
    ap.add_argument("--ident", help="one IA identifier")
    ap.add_argument("--leaves", type=int, default=FRONT_LEAVES)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", action="store_true", help="re-read volumes already done")
    ap.add_argument("--sleep", type=float, default=0.5, help="pause between volumes (politeness)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print each leaf's class")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    paths = sorted(SIDECAR.glob("ia_*.json"))
    if not paths:
        ap.error(f"no sidecars in {SIDECAR} -- run survey_census.py first")

    todo = []
    for p in paths:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if args.ident and doc["id"] != args.ident:
            continue
        if not (doc.get("derivatives") or {}).get("has_pageindex"):
            continue
        if doc.get("survey_status") in ("frontmatter-done", "needs-image-read") and not args.redo:
            continue
        todo.append((p, doc))
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} volumes to read", file=sys.stderr)

    done = failed = 0
    for i, (p, doc) in enumerate(todo, 1):
        ident = doc["id"]
        try:
            book, structure, status = survey_volume(ident, args.leaves, args.verbose)
        except Exception as e:                           # noqa: BLE001 - recorded, keeps going
            doc["survey_status"] = "frontmatter-failed"
            doc["error"] = f"{type(e).__name__}: {e}"[:200]
            p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            print(f"[{i}/{len(todo)}] {ident}: FAILED {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1
            continue
        # Conflict gate. Two independent catalogs (the CSV and IA) agreeing AGAINST the page is
        # far more often an ad page misread as a title page than a genuine catalog error -- so it
        # escalates to an image read rather than being promoted. The claim and its citation are
        # kept either way; what changes is that nothing silently overwrites a correct cell.
        cat = (doc.get("catalog_says") or {}).get("csv") or {}
        ia_md = (doc.get("catalog_says") or {}).get("ia") or {}
        if "year" in book:
            srcs = [s for s in (cat.get("year"), ia_md.get("date") or ia_md.get("year")) if s]
            if srcs and not any(year_agrees(s, book["year"]["value"]) for s in srcs):
                book["year"]["confidence"] = "low"
                book["year"]["conflicts_with_catalog"] = srcs
                status = "needs-image-read"
                structure.setdefault("image_read_candidates", [book["year"]["leaf"]])
                structure.setdefault("image_read_urls", [book["year"]["image"]])

        doc["book_says"] = book
        doc["structure"] = structure
        doc["survey_status"] = status
        doc["frontmatter_read"] = time.strftime("%Y-%m-%d")
        p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        got = ",".join(k for k in ("year", "publisher", "title", "legend") if k in book)
        print(f"[{i}/{len(todo)}] {ident}: {status} [{got or 'nothing'}]", file=sys.stderr)
        done += 1
        time.sleep(args.sleep)

    print(f"\nread {done}, failed {failed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
