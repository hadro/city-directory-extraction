#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Pair a vision model's text with tesseract's printed lines (docs/PIPELINE.md #27).

    python3 data_prep/reocr_pair.py bench <slug> [--kind halves|columns|page] [--raw]
    python3 data_prep/reocr_pair.py score <run> [<run> ...] [--pages a_0001,b_0002]
    python3 data_prep/reocr_pair.py post <run>        # turnovers and fractions -> <run>-post
    python3 data_prep/reocr_pair.py screen <slug> [--root data/reocr_screen]   # no-gold checks
    python3 data_prep/reocr_pair.py dump <slug> --root data/reocr_halves [--ids a,b] [--out-dir D]
    python3 data_prep/reocr_pair.py --self-test

WHY (2026-10-13). The hybrid (reocr_bench.hybrid_page) gives each tesseract line the model line
that matches it at >= 0.6, which assumes the model writes printed lines. LightOnOCR-3 writes
ENTRIES (run-overs joined, hyphen breaks closed up), the convention of our gold and of the
wrap-joined book references. And even with Churro's printed lines the hybrid's continuation
lines keep tesseract's text: on the gold page 0036_0391, with every engine's run-overs joined,
the hybrid read 87.6% of entries exactly against Churro's 92.6%. Here each model line is
aligned, in order, to a RUN of 1-RUN consecutive tesseract lines of the same tile. Its words
are split back over those printed lines at the boundaries that fit best, with tesseract's
hyphen kept where the print broke a word ("Mar-" / "shall"). Printed lines keep tesseract's
word boxes, so the downstream wrap-joiner sees what it always sees.

E MARKS. The 1857-58 and 1858-59 Brooklyn directories set a small "E" (Eastern District) before
a name. LightOn drops it. Tesseract sees it, either as a small separate token ("©", "E", "€",
about 2/3 of a word's height) or glued to the name ("EHess", "€Hess", "&Hess"). Where the
model's line begins with that same name, the mark goes back as a separate "E". It stays in the
raw line and out of the record, as the ground-truth conventions treat Hope & Henderson's "*"
(conv #16).

SCORING (`score`). Every engine's lines are joined into entries the way the references are,
guided by the reference: a line takes the next while the join matches some reference entry
better than either alone, never changing a character. E marks are written one way ("EHess",
"© Hess" -> "E Hess") in candidates and references alike. Without the join, a printed-line
engine pays for every run-over and an entry engine never does.
"""
from __future__ import annotations

import argparse
import collections
import difflib
import html
import itertools
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DATA = REPO / "data"
BENCH = DATA / "reocr_benchcols"
RUNS = DATA / "reocr_runs"
sys.path.insert(0, str(HERE))

from survey_twins import eligible, norm  # noqa: E402

PAIR = 0.6              # a model line and a run of printed lines are one entry at this similarity
RUN = 3                 # ...a run of at most this many printed lines
RUN_COST = 0.01         # what each printed line past the first costs a run
MARKS = set("E€©&ᴱ®")   # what tesseract makes of the small E
MARK_H = 0.8            # a separate mark is shorter than this share of the page's median word
HYPHENS = "-—–¬"
CLOSE = 0.8             # as reocr_bench: a reference line is found at this similarity
# the mark as tesseract or a book scan's OCR reads it: "EHess", "© Hess", "sBowron", "eBoyd",
# "£Boyd", ".EWittsdeldt" (a lowercase letter or symbol cannot open a name, so these are marks)
LEAD_MARK = re.compile(r"^\s*[.,'‘]?\s*(?:[E€©&ᴱ®£]\s*|[es])(?=[A-Z][a-z])")


def sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if a and b else 0.0


def fast_sim(a: str, b: str, floor: float = PAIR) -> float:
    """sim, or 0.0 when it cannot reach `floor` (quick_ratio is an upper bound)."""
    if not a or not b:
        return 0.0
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return m.ratio() if m.real_quick_ratio() >= floor and m.quick_ratio() >= floor else 0.0


def joint(parts: list) -> str:
    """Printed lines read as one entry: "Mar-" + "shall" -> "Marshall"."""
    out = ""
    for p in parts:
        p = p.strip()
        if not out:
            out = p
        elif out[-1] in HYPHENS:
            out = out[:-1] + p
        else:
            out = f"{out} {p}"
    return out


def strip_mark(text: str) -> str:
    """A model line without its own leading mark (Churro's <Initial>E</Initial> -> "E Hess")."""
    return re.sub(r"^\s*[E€©&ᴱ®]\s+(?=[A-Z])", "", text)


def canon(text: str) -> str:
    """E marks written one way, for scoring: "EHess", "© Hess", "E Hess" -> "E Hess"."""
    return LEAD_MARK.sub("E ", text)


def align(tess: list, model: list, floor: float = PAIR) -> list:
    """[(i0, i1, j)] in order: model line j covers tesseract lines i0..i1-1. j None: a tesseract
    line no model line covers; i0 == i1: a model line with no printed line found. The monotone
    alignment of greatest total similarity, every pair at least PAIR."""
    n, m = len(tess), len(model)
    runs = {(i, k): norm(joint(tess[i:i + k])) for i in range(n) for k in range(1, RUN + 1)
            if i + k <= n}
    nm = [norm(strip_mark(t)) for t in model]
    neg = float("-inf")
    best = [[neg] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            s = best[i][j]
            if s == neg:
                continue
            if i < n and s > best[i + 1][j]:
                best[i + 1][j], back[i + 1][j] = s, (i, j, 0)
            if j < m and s > best[i][j + 1]:
                best[i][j + 1], back[i][j + 1] = s, (i, j, -1)
            if j < m:
                for k in range(1, RUN + 1):
                    if i + k > n:
                        break
                    r = fast_sim(nm[j], runs[(i, k)], floor)
                    # each extra printed line costs a little, so a run takes a line only when
                    # it reads better with it (a junk line normalises to "" and ties otherwise)
                    if r >= floor and s + r - RUN_COST * (k - 1) > best[i + k][j + 1]:
                        best[i + k][j + 1], back[i + k][j + 1] = s + r - RUN_COST * (k - 1), (i, j, k)
    out, i, j = [], n, m
    while (i, j) != (0, 0):
        pi, pj, k = back[i][j]
        out.append((pi, pi + 1, None) if k == 0 else (pi, pi, pj) if k == -1 else (pi, pi + k, pj))
        i, j = pi, pj
    return out[::-1]


GAP_FLOOR = 0.25        # inside a gap between paired lines, a weaker likeness still pairs


def fill_gaps(segs: list, tess: list, model: list) -> list:
    """align()'s segments with the gaps between paired lines filled. Where tesseract's reading of
    a line is garbage ("Glacken Mic clad Hirer 26°8 eT" for "Glacken Michael, laborer, 125 Stagg",
    bleed-through on micro_IABROOKLYN_0047 leaf 90), the model's line falls under PAIR and both
    would be kept: the junk as a line of its own, the model's text as a model-only line with a
    made-up box. Between two paired lines, unpaired tesseract lines and unpaired model lines
    are the same printed lines read twice: paired one to one, in order, when they are as many;
    otherwise by align() at GAP_FLOOR, within the gap."""
    out, run = [], []
    for seg in segs + [None]:
        if seg is not None and (seg[2] is None or seg[0] == seg[1]):
            run.append(seg)
            continue
        if run:
            tl = [r[0] for r in run if r[2] is None]
            ml = [r[2] for r in run if r[0] == r[1]]
            if tl and ml and len(tl) == len(ml):
                out += [(t, t + 1, m) for t, m in zip(tl, ml)]
            elif tl and ml:
                sub = align([tess[t] for t in tl], [model[m] for m in ml], GAP_FLOOR)
                for i0, i1, j in sub:
                    if j is None:
                        out.append((tl[i0], tl[i0] + 1, None))
                    elif i0 == i1:
                        out.append((tl[i0] if i0 < len(tl) else tl[-1] + 1,) * 2 + (ml[j],))
                    else:
                        out.append((tl[i0], tl[i1 - 1] + 1, ml[j]))
            else:
                out += run
            run = []
        if seg is not None:
            out.append(seg)
    return out


def split(text: str, parts: list) -> list:
    """A model entry spread back over the k printed lines it covers: the word boundaries that
    make each piece most like its line, then tesseract's hyphen where the print broke a word.
    None where the entry has too few words to give that line any (tesseract's text stays)."""
    k, words = len(parts), text.split()
    if k == 1:
        return [text]
    if len(words) < k:
        return [text] + [None] * (k - 1)
    nparts = [norm(p) for p in parts]
    best = None
    for cuts in itertools.combinations(range(1, len(words)), k - 1):
        b = (0,) + cuts + (len(words),)
        pieces = [" ".join(words[b[t]:b[t + 1]]) for t in range(k)]
        s = sum(sim(norm(p), q) for p, q in zip(pieces, nparts))
        if best is None or s > best[0]:
            best = (s, pieces)
    pieces = best[1]
    for t in range(k - 1):
        m = re.search(r"(\w+)[" + HYPHENS + r"]$", parts[t].strip())
        if not m or not pieces[t + 1]:
            continue
        stem = m.group(1)
        head, _, rest = pieces[t + 1].partition(" ")
        cut = len(stem)
        if cut < len(head) and sim(norm(head[:cut]), norm(stem)) >= PAIR:
            pieces[t] = f"{pieces[t]} {head[:cut]}-"
            pieces[t + 1] = (head[cut:] + (f" {rest}" if rest else "")).strip()
    return pieces


def mark_of(words: list, median_h: float, name: str) -> bool:
    """Whether tesseract's line opens with a district mark before `name` (the model's first
    word): a small separate mark-like token followed by the name, or a mark glued to it."""
    if not words or not name:
        return False
    t0 = words[0][5]
    if (len(t0) == 1 and t0 in MARKS and len(words) > 1
            and words[0][3] - words[0][1] < MARK_H * median_h):
        return sim(norm(words[1][5]), norm(name)) >= PAIR
    if len(t0) > 2 and t0[0] in MARKS and t0[1].isupper() and t0[0].lower() != name[0].lower():
        return sim(norm(t0[1:]), norm(name)) >= CLOSE
    return False


# What LightOn makes of the small "E" (Eastern District) set before a name: on the full run,
# 4,567 lines of 0039, 0040 and 0042 open "^Butler", "£Ford", "=Cooney", "≡Flynn", "†Taylor" or
# "■Blumberg", each the printed mark on the page images (2026-10-15). Glued to a capitalised
# name it is the mark, and goes back as tesseract's are: "E Butler Edward".
EGLYPH = re.compile(r"^\s*[\^£=≡■†€©®ᴱ](?=[A-Z][a-z])")


def pair_tile(tess: list, model: list, median_h: float, model_marks: bool = False) -> list:
    """One tile: tesseract's printed lines (word lists, top to bottom) and the model's lines.
    -> [{"text", "words", "source", "mark", "start", "bullet"}] in printed order, model-only
    lines in place. model_marks: the model writes E marks itself (Churro), so a leading "E " is
    one."""
    texts = [" ".join(w[5] for w in ws) for ws in tess]
    out = []
    for i0, i1, j in fill_gaps(align(texts, model), texts, model):
        if j is None:
            out.append({"text": texts[i0], "words": tess[i0], "source": "tesseract", "mark": False})
            continue
        bullet = BULLET.match(model[j]) is not None
        line = BULLET.sub("", model[j], count=1)
        glyph = None if model_marks else EGLYPH.match(line)
        if glyph:
            line = line[glyph.end():]
        if i0 == i1:
            out.append({"text": f"E {line}" if glyph else line, "words": [], "source": "model-only",
                        "mark": bool(glyph), "start": True, "bullet": bullet})
            continue
        # Churro writes the mark itself (<Initial>E</Initial>). LightOn's leading "E " is an
        # initial ("E A cigars"), so its marks are the glyphs it reads them as (EGLYPH) and
        # tesseract's
        body = strip_mark(line) if model_marks else line
        first = re.sub(r"[^\w'-]", "", body.split()[0]) if body.split() else ""
        mark = bool(glyph) or body != line or mark_of(tess[i0], median_h, first)
        for t, piece in enumerate(split(body, texts[i0:i1])):
            text = piece if piece is not None else texts[i0 + t]
            if t == 0 and mark:
                text = f"E {text}"
            out.append({"text": text, "words": tess[i0 + t], "source": "model",
                        "mark": mark and t == 0, "start": t == 0, "bullet": bullet and t == 0})
    return out


BULLET = re.compile(r"^\s*-\s+")
DASH = re.compile(r"^[~\-—–‒―_=]+")


def name_key(text: str, marked: bool = False) -> str:
    """The first word's letters, lowercase: what a directory's alphabetical order runs on (after
    the "E " mark, where the pairing put one)."""
    words = (text[2:] if marked and text.startswith("E ") else text).split()
    if not words:
        return ""
    chunk = re.split(r"[—–\-]", words[0])[0] or words[0]      # "HES—HEW" -> "HES"
    return re.sub(r"[^a-z]", "", chunk.lower())


BULLET_AGREE = 0.2      # bullets are dash evidence on a page where this share of them meet a dash
DASH_W = 0.15           # a dash token standing alone is evidence if at least this share of the
DASH_FLAT = 1.5         # page's median word height wide and this many times wider than tall
LONE_LETTER = re.compile(r"^[A-Z]\.?$")      # a section's letter ("D"), never an entry
AMPERSAND = re.compile(r"^&\s+\S")            # "& Oest grocers": a firm under the surname above
QUOTE_MARK = re.compile(r"^(?:[\"“”„«»]|''|,,)")  # a printed `"` ditto as tesseract reads it
QUOTE_ONLY = re.compile(r"^(?:[\"“”„«»]+|''|,,)$")   # ...as a token of its own
QUOTE_DITTO = re.compile(r"^\s*[\"“”„]\s+[A-Z]")      # LightOn's own `" Chas P r10 W43d`
QUOTE_SHARE = 0.2
_GIVEN = None


def given_names() -> set:
    """Given names and their abbreviations seen at least twice in the corpus (names/
    given_harvested.tsv: John, Jos, Wm, Chas, ...), lowercase letters only."""
    global _GIVEN
    if _GIVEN is None:
        _GIVEN = set()
        f = HERE / "names" / "given_harvested.tsv"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                name, _tab, n = line.partition("\t")
                if n.strip().isdigit() and int(n) >= 2:
                    _GIVEN.add(re.sub(r"[^a-z]", "", name.lower()))
    return _GIVEN


def dittos(rows: list, median_h: float = 0.0) -> list:
    """A page's paired rows (reading order) with each entry's ditto decided and written as a
    leading "— " (r["ditto"]; r["ambiguous"] marks the lines worth a look). LightOn's leading
    "- " is Markdown list markup, not the printed dash: it bullets whole runs of entries, new
    surname heads included ("- Smalldone Giacomo" and "- Smalley Arthur" print no dash on 1912
    p3 leaf 291), and whole lists in volumes with no dash dittos at all (0001, 0003, 0004, 0009,
    0042). Tesseract alone misses real dashes ("- E A cigars" read "I A cigars"). Both mistakes
    cascade under the downstream surname carry: a false ditto hands the head's entry the surname
    above, a false head hands its given name to the dittos below.

    So a prefix chain, after historical-ocr-eval (2026-10-14): walking the page, an entry is a
    head when its first word sorts at or after the current head and shares its first two letters
    (Small, Smalldone, Smalley, Smart; given names span A-Z and fail), or its first letter and
    is no known given name (the next two-letter run: Abel -> Ackerman), and it becomes the
    current head. An entry with dash evidence that fails is a ditto: tesseract's first token a
    dash, or LightOn's bullet on a page where bullets meet tesseract dashes (BULLET_AGREE; 68% on
    1912, 0-5% where LightOn bulleted plain lists). An entry with no evidence is a head, as the
    downstream carry will take it, and moves the chain unless it is a known given name that
    fails the test: that one is ambiguous (counted for a look), and the chain stays put, so a
    ditto both readings missed cannot turn the next real head into a ditto.

    Two kinds of line are never dittos (2026-10-14, the plain-list volumes' false ones). A first
    word in capitals (a running head, "BROOKLYN DIRECTORY.", a banner, an ad, a guide word) is a
    head whatever stands before it, so a speck over a running head no longer makes it a ditto;
    it moves the chain as before, which is how 1912's banner and then its guide word ("SMALL")
    start the chain above a column's first, bulleted, entries. A lone letter (a section's "D", a
    neighbour column's sliver, or an initial LightOn cut short, "- G" for "—G A h") is a ditto
    on evidence and never moves the chain; a line that starts in lowercase (a run-over the model
    wrote as a line of its own) is skipped. A bullet alone does not make a ditto of a word
    tesseract read as it is, with nothing before it, that is no given name: checked by eye on
    1912 leaves 291 and 671, that was the one false ditto ("Smeloft", set after "Smeltzer"), and
    9 of the 10 bullet-only dittos tesseract read cleanly were given names or initials, the
    tenth being it. And tesseract's dash, where it stands alone, is
    evidence only if it is a dash: DASH_W of a word's height wide and DASH_FLAT times wider than
    tall. Measured on standalone dash tokens before a capitalised word: 96.7% of 1912's pass,
    13.1% of the specks ("-", "_", "~" off the film) in six plain-list volumes (0013, 0018, 0021,
    0029, 0032, 0047), whose long "——" dittos ("—— Michael, butcher" under Donnally, 0035;
    also read "= Samuel") pass too. Glued to the given name ("—John H", 1912's usual form) it
    counts as it is, but not as "_" or "=": glued so, they lead 73 of 22,199 glued tokens in 1912
    and 268 of 718 in nine plain-list volumes ("_Storan" under "Storm", 0006)."""
    starts = [r for r in rows if r.get("start")]

    def tlead(r):
        """Tesseract's first token as dash evidence: "glued" to the word, "alone", or None."""
        ws = sorted(r["words"], key=lambda w: w[0]) if r["words"] else []
        lead = DASH.match(ws[0][5]) if ws else None
        if lead is None:
            return None
        if ws[0][5][lead.end():lead.end() + 1].isalpha():
            return None if set(lead.group(0)) & set("_=") else "glued"
        w, h = ws[0][2] - ws[0][0], max(ws[0][3] - ws[0][1], 1)
        return "alone" if w >= DASH_W * median_h and w >= DASH_FLAT * h else None

    def tdash(r):
        return tlead(r) is not None

    def tquote_token(r):
        """Tesseract's first token is a quote mark standing alone, as a `"` ditto reads (Trow
        and Polk from the 1910s: `"`, `«`, `»`, `|"`), not glued to a word as a quotation is."""
        ws = sorted(r["words"], key=lambda w: w[0]) if r["words"] else []
        return bool(ws) and QUOTE_ONLY.match(ws[0][5].lstrip("|")) is not None

    def mquote(r):
        """LightOn wrote the `"` ditto itself: a quote mark, a space, a capitalised word."""
        return QUOTE_DITTO.match(r["text"]) is not None
    # quote marks are this page's ditto only where they lead a fifth of its entries: 0.49 of
    # Trow 1917 leaf 688's lines, under 0.1 on 7,840 of the 7,926 re-read pages, where a quote
    # opens an advertisement's testimonial (0039 leaf 286) or is the small E misread (0040)
    quote_page = sum(tquote_token(r) or mquote(r) for r in starts) >= max(5, QUOTE_SHARE * len(starts))

    def tquote(r):
        return quote_page and tquote_token(r)

    def tmark(r):
        return tdash(r) or tquote(r)
    bulleted = [r for r in starts if r.get("bullet")]
    bullets_mean_marks = (len(bulleted) < 5
                          or sum(tmark(r) for r in bulleted) >= BULLET_AGREE * len(bulleted))
    # the page's own ditto mark, written back as it prints: `"` on a quote page (Trow 1917 leaf
    # 688: LightOn bulleted 281 dittos and wrote 66 as `"`; tesseract read `"`, «, », |"), the
    # dash elsewhere (1912 Brooklyn)
    dashes = sum(tdash(r) or DASH.match(r["text"].lstrip()) is not None for r in starts)
    glyph = '"' if quote_page and sum(tquote(r) or mquote(r) for r in starts) > dashes else "—"
    given = given_names()
    head = None
    for r in starts:
        k = name_key(r["text"], r.get("mark"))
        r["ditto"] = r["ambiguous"] = False
        body = r["text"][2:] if r.get("mark") and r["text"].startswith("E ") else r["text"]
        if AMPERSAND.match(body):
            # A firm under the surname above, which 1912 prints "— & Oest grocers 1508 Bway" and
            # LightOn reads without its dash. On evidence the dash goes back; left bare, the
            # survey's gate admitted "&" itself as the ditto (424 lines), turning "[Surname] &
            # Oest" into "[Surname] Oest", the firm-name loss hadro rejected "&" for in Trow 1915
            r["ditto"] = tmark(r) or bool(bullets_mean_marks and r.get("bullet"))
        elif not k or DASH.match(body) or body.lstrip()[:1].islower():
            continue                 # (a dash the model wrote itself stays as it wrote it; a
                                     # lowercase start is a run-over, "h. Rutledge n. Bedford av")
        caps = len(k) > 1 and body.split()[0].isupper()
        evidence = not caps and (tmark(r) or bool(bullets_mean_marks and r.get("bullet")))
        if AMPERSAND.match(body):
            pass                     # decided above; a firm never moves the chain
        elif LONE_LETTER.match(body.strip()):
            # an initial under a dash (LightOn's "- G" for "—G A h", tesseract's "—G"), or a
            # section's letter, which a speck beside it ("- D", 0003 leaf 23) does not make a
            # ditto; the chain stays either way
            r["ditto"] = not caps and (tlead(r) == "glued" or tquote(r)
                                       or bool(bullets_mean_marks and r.get("bullet")))
        else:
            follows = head is not None and k >= head and (
                k[:2] == head[:2] or (k[0] == head[0] and len(k) > 1 and k not in given))
            # a bullet alone against a word tesseract read as it is, with nothing before it, and
            # no given name: a head the page sets out of order ("Smeloft" after "Smeltzer")
            clean = (evidence and not tmark(r) and bool(r["words"]) and len(k) > 1 and k not in given
                     and sorted(r["words"], key=lambda w: w[0])[0][5] == body.split()[0])
            if evidence and not clean:
                if follows or (head is None and not tmark(r)):
                    head = k         # a head after all (bulleted Smalley; a page's first line)
                else:
                    r["ditto"] = True
            elif follows or clean or k not in given:
                head = k             # no dash evidence: downstream will take it as a head too
            else:
                r["ambiguous"] = True    # a given name with no dash: a ditto both readings
                                         # missed, or a head; kept a head, the chain stays put
        if r["ditto"]:
            r["text"] = (f"E {glyph} {r['text'][2:]}" if r["text"].startswith("E ") and r.get("mark")
                         else f"{glyph} {r['text']}")
    return rows


# ---------------------------------------------------------------- page post-passes

TURNOVER = re.compile(r"\s\[\s*([^\[\]]+?)\s*$")
TURNOVER_MAX = 3        # tokens a turnover carries ("[Hicks", "[45 Front")
STANDALONE = re.compile(r"^\s*\[\s*([^\[\]\s][^\[\]]*?)\s*$")    # a turnover on a line of its own
FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8", "⅜": "3/8",
             "⅝": "5/8", "⅞": "7/8"}
FRACTION_RX = re.compile(r"(\d)\s*([" + "".join(FRACTIONS) + r"])")


def turnovers(lines: list) -> list:
    """A page's lines in reading order, each TURNOVER put back. 1840s printers set the last words
    of an entry that would not fit at the right end of the next printed line, after a "["
    ("Fletcher James, grocer Nassau c Pearl [Hicks", where "Hicks" ends the entry above); the gold
    puts them back, and on the bench they were 15 of LightOn's 45 non-exact gold lines. Only a
    final "[" with 1-TURNOVER_MAX tokens and no closing bracket moves, to the end of the line
    above in reading order, which may sit in the previous tile or column. A hyphen there closes
    up as the gold does ("Skill-" + "[man" -> "Skillman")."""
    out = list(lines)
    for i in range(1, len(out)):
        s = STANDALONE.match(out[i] or "")
        if s:
            # LightOn sometimes writes the turnover as a line of its own, after the entry it
            # completes ("…merchant, 75 Washington, store 10" / "[Cedar-street New-York"; ~300
            # lines in the full run, mostly 1840s volumes). It goes to the nearest line above,
            # or a word's second half to the nearest hyphenated line up to 3 above ("[pect").
            frag, above = s.group(1), [j for j in range(i - 1, -1, -1) if (out[j] or "").strip()]
            target = above[0] if above else None
            if frag[0].islower() and frag.isalpha():
                target = next((j for j in above[:3] if out[j].rstrip()[-1] in HYPHENS), target)
            if target is not None:
                prev = out[target].rstrip()
                out[target] = prev[:-1] + frag if prev[-1] in HYPHENS else f"{prev} {frag}"
                out[i] = ""
            continue
        m = TURNOVER.search(out[i] or "")
        if not m or len(m.group(1).split()) > TURNOVER_MAX or not out[i][:m.start()].strip():
            continue
        frag, rest = m.group(1), out[i][:m.start()].rstrip()
        if frag[0].islower():
            # A word's second half ("[ington", "[apple") closes up with the nearest hyphenated
            # line up to 3 above ("Pine-" -> "Pineapple"), which need not be the line just above.
            # Other lowercase turnovers ("[h 98 Jay") can belong above or below (the bench has
            # both), so they stay where they are printed.
            if frag.isalpha() and len(frag) >= 3:
                for j in range(i - 1, max(-1, i - 4), -1):
                    prev = (out[j] or "").rstrip()
                    if prev and prev[-1] in HYPHENS:
                        out[j], out[i] = prev[:-1] + frag, rest
                        break
            continue
        prev = (out[i - 1] or "").rstrip()
        out[i] = rest
        out[i - 1] = prev[:-1] + frag if prev and prev[-1] in HYPHENS else f"{prev} {frag}".strip()
    return out


def fractions(text: str) -> str:
    """A fraction glyph after a digit as the gold writes it: "165½" -> "165 1/2" (4 of LightOn's
    45 non-exact gold lines). A glyph with no digit before it is left alone."""
    return FRACTION_RX.sub(lambda m: f"{m.group(1)} {FRACTIONS[m.group(2)]}", text)


def post(lines: list) -> list:
    """Both post-passes, on one page's lines in reading order."""
    return [fractions(t) for t in turnovers(lines)]


def post_run(args) -> int:
    """<run>.jsonl -> <run>-post.jsonl: the post-passes on every page (any engine's run)."""
    from reocr_bench import load_candidate
    rows = load_candidate(RUNS / f"{args.run}.jsonl")
    out = [dict(r, lines=post(r["lines"])) for _k, r in sorted(rows.items())]
    (RUNS / f"{args.run}-post.jsonl").write_text("".join(json.dumps(r) + "\n" for r in out),
                                                 encoding="utf-8")
    moved = sum(a != b for _k, r in rows.items() for a, b in zip(r["lines"], post(r["lines"])))
    print(f"{len(out)} pages, {moved} lines changed -> data/reocr_runs/{args.run}-post.jsonl",
          file=sys.stderr)
    return 0


# ---------------------------------------------------------------- the word dump (production)

LOOP_LOOK = 0.02        # a volume is worth a look past this share of looped tiles (task 0: 1 in 326)
TABLE_LOOK = 0.15       # ...or this share in table mode (twice the bench's 10 of 138)
CONF_MODEL = 90         # a word the vision model read: well above CRUMB_CONF (5), where a word
CONF_BLEED = 30         # ...with an odd character is taken for banner crumbs; a bleed_retry tile's
                        # words are less sure (house numbers off by a digit on 0047 leaf 90)


def respell(words: list, text: str, conf: int) -> list:
    """Tesseract's words for one printed line, spelled as `text` (the model's piece of the line,
    after the post-passes). Each tesseract word is paired, in order, with the model token most
    like it (similarity >= 0.5; the in-order pairing of greatest total similarity, so "capmker"
    still anchors "capmaker"), and a paired token takes that word's box, its confidence at least
    `conf`. Unpaired tokens fill the gap between their paired neighbours, by length: an "E" mark
    before the name goes just left of it, words tesseract never read ("60 Ewen") run on past its
    last word at the line's character width. A word the model did not read is dropped. Boxes
    stay tesseract's, so the line keeps its place and its indent."""
    toks = text.split()
    if not words or not toks:
        return []
    ws = sorted(words, key=lambda w: w[0])
    nw, nt = [norm(w[5]) for w in ws], [norm(t) for t in toks]
    n, m = len(ws), len(toks)
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            r = 1.0 if nw[i] == nt[j] else sim(nw[i], nt[j])
            best[i][j] = max(best[i + 1][j], best[i][j + 1], best[i + 1][j + 1] + r if r >= 0.5 else 0.0)
    pair, i, j = {}, 0, 0
    while i < n and j < m:
        r = 1.0 if nw[i] == nt[j] else sim(nw[i], nt[j])
        if r >= 0.5 and best[i][j] == best[i + 1][j + 1] + r:
            pair[j] = i
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    y0, y1 = min(w[1] for w in ws), max(w[3] for w in ws)
    cw = sorted((w[2] - w[0]) / max(len(w[5]), 1) for w in ws)[len(ws) // 2]
    out, j = [], 0
    while j < m:
        if j in pair:
            w = ws[pair[j]]
            out.append([*w[:4], max(w[4], conf), toks[j]])
            j += 1
            continue
        k = j
        while k < m and k not in pair:
            k += 1
        run = toks[j:k]
        need = cw * (sum(len(t) for t in run) + len(run))
        prev = ws[pair[j - 1]] if j > 0 else None
        nxt = ws[pair[k]] if k < m else None
        left = prev[2] + cw / 2 if prev else (nxt[0] - need if nxt else ws[0][0])
        right = nxt[0] - cw / 2 if nxt else max(left + need, ws[-1][2] if not prev else left + need)
        right = max(right, left + 4)
        total, x = sum(len(t) + 1 for t in run), left
        for t in run:
            nx = x + (right - left) * (len(t) + 1) / total
            out.append([round(x), y0, max(round(x) + 1, round(nx - cw / 2)), y1, conf, t])
            x = nx
        j = k
    return out


def synth_line(text: str, above, below, x0: int, char_w: float, line_h: int, conf: int) -> list:
    """Word boxes for a line the model read and tesseract did not: under the line above (or
    over the line below), at the column's margin, each word as wide as its characters."""
    if above is not None:
        top = above[3] + max(2, line_h // 4)
    elif below is not None:
        top = below[1] - line_h - max(2, line_h // 4)
    else:
        top = 0
    out, x = [], x0
    for t in text.split():
        w = max(4, round(char_w * len(t)))
        out.append([round(x), round(top), round(x) + w, round(top) + line_h, conf, t])
        x += w + char_w
    return out


def page_rows(rec: dict, tiles: dict, answers: dict) -> tuple:
    """A page's paired rows in reading order, dittos decided: (rows, median_h, char_w). `tiles`
    maps a tile name (c0_h0, ...) to its box; `answers` maps it to (model lines, bleed) or to None
    where the model has no answer (that tile keeps tesseract's lines)."""
    from reocr_volumes import column_lines
    keyed = column_lines(rec["lines"], rec["page_size"], keyed=True)
    hs = sorted(w[3] - w[1] for _k, _y, ws in keyed for w in ws)
    median_h = hs[len(hs) // 2] if hs else 30
    widths = sorted((w[2] - w[0]) / max(len(w[5]), 1) for _k, _y, ws in keyed for w in ws if len(w[5]) >= 3)
    char_w = widths[len(widths) // 2] if widths else 0.5 * median_h
    rows = []
    for name in sorted(tiles, key=lambda n: (int(n[1:].split("_")[0]), n)):
        k = int(name[1:].split("_")[0])
        j = int(name.split("_h")[1]) if "_h" in name else None
        cut = tiles.get(f"c{k}_h0", [0, 0, 0, 0])[3]
        tess = [ws for kk, y, ws in keyed if kk == k and (j is None or (j == 0) == (y < cut))]
        got = answers.get(name)
        if got is None:
            rows += [{"text": " ".join(w[5] for w in ws), "words": ws, "source": "tesseract",
                      "x0": tiles[name][0]} for ws in tess]
            continue
        model, bleed = got
        for r in pair_tile(tess, model, median_h):
            r["source"] = "bleed" if bleed and r["source"] != "tesseract" else r["source"]
            r["x0"] = tiles[name][0]
            rows.append(r)
    return dittos(rows, median_h), median_h, char_w


def page_dump(rec: dict, tiles: dict, answers: dict) -> tuple:
    """One re-OCR'd page as a word-dump record's lines: (lines, sources). The page's rows
    (page_rows) put through the post-passes in reading order, then every line's text spread over
    its tesseract words (respell), or given boxes where tesseract never saw it (synth_line)."""
    rows, median_h, char_w = page_rows(rec, tiles, answers)
    texts = post([r["text"] for r in rows])
    lines, sources = [], []
    for i, (r, text) in enumerate(zip(rows, texts)):
        conf = CONF_BLEED if r["source"] == "bleed" else CONF_MODEL
        if r["source"] == "tesseract":
            ws = respell(r["words"], text, 0) if text != r["text"] else r["words"]
        elif r["words"]:
            ws = respell(r["words"], text, conf)
        else:
            above = next((_box(rows[q]["words"]) for q in range(i - 1, -1, -1) if rows[q]["words"]), None)
            below = next((_box(rows[q]["words"]) for q in range(i + 1, len(rows)) if rows[q]["words"]), None)
            ws = synth_line(text, above, below, r["x0"] + int(0.01 * rec["page_size"][0]), char_w,
                            int(median_h), conf)
        if ws:
            lines.append(ws)
            sources.append(r["source"])
    return lines, sources


def _box(words: list):
    return [min(w[0] for w in words), min(w[1] for w in words), max(w[2] for w in words),
            max(w[3] for w in words)]


def dump(args) -> int:
    """Swap the re-OCR into a volume's word dump. IA's dump is kept as <id>_words.ia.jsonl.gz
    (once; it is always the source of the leaves not re-read), and <id>_words.jsonl.gz becomes
    IA's records with every re-OCR'd leaf's lines replaced: tesseract's word boxes carrying the
    model's text, model-only lines given boxes, a tile without an answer kept as tesseract read
    it. Each replaced record gains "ocr" and per-line "sources" (model / tesseract / model-only
    / bleed, a bleed_retry tile's line); consumers that read only "lines" are unaffected. The
    sidecar gains a `reocr` block. Then `survey_harvest.py --rederive --ids <id>` and
    `survey_derive.py` re-read the volume from it."""
    import gzip
    root = Path(args.root).resolve()
    page_dir = Path(getattr(args, "page_dir", None) or DATA / "reocr").resolve()
    boxes = json.loads((root / "boxes.json").read_text(encoding="utf-8"))
    pages = collections.defaultdict(dict)
    for key, entry in boxes.items():
        vol, fname = key.split("/")
        stem, name = fname[:-4].rsplit("_c", 1)
        pages[(vol, stem)][f"c{name}"] = entry
    vols = sorted({v for v, _s in pages} if not args.ids else set(args.ids.split(",")))
    survey_ocr = Path(args.out_dir).resolve() if args.out_dir else DATA / "survey_ocr"
    survey_ocr.mkdir(parents=True, exist_ok=True)
    for vol in vols:
        src = DATA / "survey_ocr" / f"{vol}_words.ia.jsonl.gz"
        if not src.exists():
            src = DATA / "survey_ocr" / f"{vol}_words.jsonl.gz"
        dst = survey_ocr / f"{vol}_words.jsonl.gz"
        stats = collections.Counter()
        replaced = {}
        for (v, stem), tiles in pages.items():
            if v != vol:
                continue
            rec = json.loads((page_dir / vol / f"{stem}.json").read_text(encoding="utf-8"))
            if not rec["lines"]:
                continue
            answers = {}
            for name in tiles:
                base = root / vol / f"{stem}_{name}"
                lines = model_lines(base, args.slug, False)
                meta_f = base.with_name(f"{base.name}_{args.slug}.meta.json")
                meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
                answers[name] = None if lines is None else (lines, bool(meta.get("bleed_retry")))
                stats["tiles"] += 1
                stats["tiles_answered"] += lines is not None
                stats["bleed_retry"] += bool(meta.get("bleed_retry"))
                stats["loop_truncated"] += bool(meta.get("loop_truncated"))
                stats["table_mode"] += bool(meta.get("table_mode"))
            lines, sources = page_dump(rec, tiles, answers)
            replaced[rec["leaf"]] = (lines, sources, rec["page_size"])
            stats["pages"] += 1
            stats.update(f"lines_{s}" for s in sources)
        if not replaced:
            print(f"{vol}: no re-OCR'd pages under {root}", file=sys.stderr)
            continue
        tmp = dst.with_name(dst.name + ".tmp")
        with gzip.open(src, "rt", encoding="utf-8") as fh, gzip.open(tmp, "wt", encoding="utf-8") as out:
            for line in fh:
                r = json.loads(line)
                if r["leaf"] in replaced:
                    lines, sources, size = replaced[r["leaf"]]
                    r.update(lines=lines, sources=sources, page_size=size,
                             chars=sum(len(w[5]) for ws in lines for w in ws),
                             ocr=f"reocr: tesseract-5.5 merge + {args.slug}")
                    stats["leaves_replaced"] += 1
                out.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        if args.out_dir is None and src.name.endswith("_words.jsonl.gz"):
            src.rename(src.with_name(f"{vol}_words.ia.jsonl.gz"))   # keep IA's, once
        tmp.rename(dst)
        if args.out_dir is None:
            side = HERE / "survey" / f"ia_{vol}.json"
            doc = json.loads(side.read_text(encoding="utf-8"))
            doc["reocr"] = {"engine": f"tesseract-5.5 merge + {args.slug}", "root": str(root.relative_to(REPO)),
                            "ia_dump": f"data/survey_ocr/{vol}_words.ia.jsonl.gz", **dict(stats),
                            "dumped": __import__("datetime").date.today().isoformat()}
            side.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print(f"{vol}: {stats['leaves_replaced']} leaves replaced ({stats['tiles_answered']}/"
              f"{stats['tiles']} tiles answered; lines: {stats['lines_model']} model, "
              f"{stats['lines_tesseract']} tesseract, {stats['lines_model-only']} model-only, "
              f"{stats['lines_bleed']} bleed) -> {dst.relative_to(REPO) if dst.is_relative_to(REPO) else dst}",
              file=sys.stderr)
        # Per volume, as historical-ocr-eval asked of the full run (2026-10-15): bleed-through
        # clusters by volume, and a table-mode rate far above the bench's (10 of 138 tiles; 4 of
        # 188 on the screen pages) would mean a layout no one has looked at.
        n = max(stats["tiles_answered"], 1)
        looped, table = stats["bleed_retry"] + stats["loop_truncated"], stats["table_mode"]
        warn = looped > LOOP_LOOK * n or table > TABLE_LOOK * n
        print(f"    looped {looped} ({stats['bleed_retry']} bleed-retried, {stats['loop_truncated']} "
              f"truncated), table mode {table} of {n} tiles"
              + ("  <- look at this volume's pages" if warn else ""), file=sys.stderr)
    return 0


# ---------------------------------------------------------------- the bench (reocr_benchcols)

PLACEHOLDER = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# An entry's printed mark, glued to the name as the page sets it and the gold writes it
# ("*Simmons Aaron", conv #16). LightOn sometimes spaces it ("* Dixon William", "• White Anna" for
# a star, micro_IABROOKLYN_0035 leaf 143 and 0048 leaf 296), and a separate leading "*" is a
# ditto candidate to the survey's gate: on the screen pages it admitted "*" for 0035, which would
# have handed every starred entry the surname above.
MARK_GLUE = re.compile(r"^([*•†‡§✱])\s+(?=[A-Z])")


def demarkdown(text: str) -> list:
    """A Markdown answer as plain lines: placeholders, table rules, tags, heading markers and
    emphasis dropped, table cells joined in order; list markers kept (see below)."""
    out = []
    for t in text.splitlines():
        t = PLACEHOLDER.sub("", t)
        if re.fullmatch(r"\s*\|?\s*:?-{2,}.*", t):
            continue
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"^\s*#{1,6}\s+", "", t)
        # No list markers are stripped: LightOn writes 1912 Brooklyn's ditto dash ("same surname
        # as above") as a Markdown bullet, "- LeGrand T h 453 Washn av", but bullets plain lists
        # too, so pair_tile takes the bullet off and dittos() weighs it as evidence. The runner's
        # markdown_to_lines keeps it too.
        t = t.replace("**", "").replace("__", "")
        if "|" in t:
            t = " ".join(c.strip() for c in t.strip().strip("|").split("|"))
        t = MARK_GLUE.sub(r"\1", " ".join(html.unescape(t).split()))
        if t:
            out.append(t)
    return out


def tiles_of(stem: str, page: dict, kind: str) -> list:
    """[(tile path stem, column k, half j or None, cut)] in reading order."""
    ident = stem.rsplit("_", 1)[0]
    out = []
    for c in page["columns"]:
        if kind == "columns":
            out.append((BENCH / "columns" / ident / f"{stem}_c{c['k']}", c["k"], None, c["cut"]))
        else:
            out += [(BENCH / "halves" / ident / f"{stem}_c{c['k']}_h{j}", c["k"], j, c["cut"])
                    for j in (0, 1)]
    return out


_RUNNER = None


def runner():
    """hpc/lightonocr_tiles.py as a module: its to_lines is how an answer becomes lines."""
    global _RUNNER
    if _RUNNER is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("lightonocr_tiles", REPO / "hpc" / "lightonocr_tiles.py")
        _RUNNER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_RUNNER)
    return _RUNNER


def model_lines(path_stem: Path, slug: str, raw: bool):
    """A tile's answer as lines, or None where there is none. `raw`: Churro's raw XML. Otherwise
    the .txt marks a finished tile (the runner writes none for one that ran out of clock), and a
    LightOn answer is flattened again from its .raw.txt by the runner's own to_lines, so a fix
    there (the HTML tables, 2026-10-14) reaches answers already made without a rerun. The .raw.txt
    is what the runner flattened: a bleed retry's answer, or a looped one already cut back."""
    f = path_stem.with_name(f"{path_stem.name}_{slug}.raw.txt" if raw else f"{path_stem.name}_{slug}.txt")
    if not f.exists():
        return None
    text = f.read_text(encoding="utf-8")
    if raw:
        from reocr_bench import body_lines
        return body_lines(text)
    raw_f = path_stem.with_name(f"{path_stem.name}_{slug}.raw.txt")
    if "lightonocr" in slug and raw_f.exists():
        text = "\n".join(runner().to_lines(raw_f.read_text(encoding="utf-8"))[0])
    return demarkdown(text)


def bench(args) -> int:
    """Pair a slug's per-tile answers with the bench pages' tesseract lines; also writes the
    plain tesseract run (column-cut, reading order) the pairing starts from."""
    from reocr_volumes import column_lines
    manifest = json.loads((BENCH / "manifest.json").read_text(encoding="utf-8"))
    page_runs = {}
    if args.kind == "page":
        from reocr_bench import load_candidate
        page_runs = load_candidate(RUNS / f"{args.slug}.jsonl")
    paired, plain, marks, sources = [], [], 0, collections.Counter()
    for stem, page in sorted(manifest.items()):
        vol, leaf = stem.rsplit("_", 1)
        rec = json.loads((BENCH / "pages" / vol / f"{stem}.json").read_text(encoding="utf-8"))
        if not rec["lines"]:
            continue
        size = rec["page_size"]
        keyed = column_lines(rec["lines"], size, keyed=True)
        hs = sorted(w[3] - w[1] for _k, _y, ws in keyed for w in ws)
        median_h = hs[len(hs) // 2]
        plain.append({"volume": vol, "leaf": int(leaf),
                      "lines": [" ".join(w[5] for w in ws) for _k, _y, ws in keyed]})
        if args.kind == "page":
            got = page_runs.get((vol, int(leaf)))
            if got is None:
                continue
            tiles = [([ws for _k, _y, ws in keyed], got["lines"])]
        else:
            tiles = []
            for tstem, k, j, cut in tiles_of(stem, page, args.kind):
                lines = model_lines(tstem, args.slug, args.raw)
                if lines is None:
                    tiles = None
                    break
                tess = [ws for kk, y, ws in keyed if kk == k and
                        (j is None or (j == 0) == (y < cut))]
                tiles.append((tess, lines))
            if tiles is None:
                continue
        rows = dittos([r for tess, lines in tiles
                       for r in pair_tile(tess, lines, median_h, model_marks=args.raw)], median_h)
        marks += sum(r["mark"] for r in rows)
        sources.update(r["source"] for r in rows)
        paired.append({"volume": vol, "leaf": int(leaf), "lines": [r["text"] for r in rows],
                       "boxes": [[min(w[0] for w in r["words"]), min(w[1] for w in r["words"]),
                                  max(w[2] for w in r["words"]), max(w[3] for w in r["words"])]
                                 if r["words"] else None for r in rows],
                       "sources": [r["source"] for r in rows]})
    name = f"{args.slug}-{args.kind}-paired"
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in paired), encoding="utf-8")
    (RUNS / "tesseract-benchcols.jsonl").write_text("".join(json.dumps(r) + "\n" for r in plain),
                                                   encoding="utf-8")
    print(f"{len(paired)} pages -> data/reocr_runs/{name}.jsonl; lines by source {dict(sources)}; "
          f"{marks} E marks written", file=sys.stderr)
    return 0


def screen(args) -> int:
    """No-gold checks of a model's answers on staged half tiles (reocr_columns.py stage --tiles
    halves --out <root>), per tile against tesseract's lines in the same tile: lines and
    characters, empty/looped/timed-out tiles, Markdown or table output, lines run together into
    paragraphs, and what the pairing leaves unmatched. The 39 deferred volumes are none of the
    bench's, so this is the model's first look at their layouts (1820s single columns, 1912)."""
    from reocr_volumes import column_lines
    root = Path(args.root).resolve()
    page_dir = Path(getattr(args, "page_dir", None) or DATA / "reocr").resolve()
    boxes = json.loads((root / "boxes.json").read_text(encoding="utf-8"))
    pages = collections.defaultdict(dict)
    for key, entry in boxes.items():
        vol, fname = key.split("/")
        stem, name = fname[:-4].rsplit("_c", 1)
        pages[(vol, stem)][f"c{name}"] = entry
    tiles, by_vol = [], collections.defaultdict(list)
    for (vol, stem), named in sorted(pages.items()):
        rec = json.loads((page_dir / vol / f"{stem}.json").read_text(encoding="utf-8"))
        keyed = column_lines(rec["lines"], rec["page_size"], keyed=True)
        hs = sorted(w[3] - w[1] for _k, _y, ws in keyed for w in ws)
        median_h = hs[len(hs) // 2] if hs else 1
        for name in sorted(named):
            k, j = int(name[1:].split("_h")[0]), int(name.split("_h")[1])
            cut = named.get(f"c{k}_h0", [0, 0, 0, 0])[3]
            tess = [ws for kk, y, ws in keyed if kk == k and (j == 0) == (y < cut)]
            base = root / vol / f"{stem}_{name}"
            meta_f = base.with_name(f"{base.name}_{args.slug}.meta.json")
            meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
            raw_f = base.with_name(f"{base.name}_{args.slug}.raw.txt")
            raw = raw_f.read_text(encoding="utf-8") if raw_f.exists() else ""
            model = model_lines(base, args.slug, False)
            t_lines = [" ".join(w[5] for w in ws) for ws in tess]
            t_chars = sum(len(t) for t in t_lines)
            row = {"tile": f"{stem}_{name}", "volume": vol, "tess_lines": len(t_lines),
                   "looped": bool(meta.get("looped")), "timed_out": bool(meta.get("timed_out")),
                   "missing": model is None}
            if model is not None:
                pr = pair_tile(tess, model, median_h)
                src = collections.Counter(r["source"] for r in pr)
                m_chars = sum(len(t) for t in model)
                t_med = sorted(len(t) for t in t_lines)[len(t_lines) // 2] if t_lines else 0
                row.update(model_lines=len(model), line_ratio=len(model) / max(len(t_lines), 1),
                           char_ratio=m_chars / max(t_chars, 1), empty=not model,
                           markdown=bool(re.search(r"^\s*(#|\||[-*] |\*\*)", raw, re.M)),
                           paragraphs=sum(len(t) > 3 * max(t_med, 20) for t in model),
                           tess_unpaired=src["tesseract"] / max(len(t_lines), 1),
                           model_only=src["model-only"])
            tiles.append(row)
            by_vol[vol].append(row)
    print(f"{len(tiles)} tiles on {len(pages)} pages in {len(by_vol)} volumes")
    print(f"{'volume':28s} {'tiles':>5s} {'lines/tess':>10s} {'chars/tess':>10s} {'unpaired':>8s} flags")
    flagged = 0
    for vol, rows in sorted(by_vol.items()):
        done = [r for r in rows if not r["missing"]]
        if not done:
            print(f"{vol:28s} {len(rows):5d}   (no answers)")
            continue
        lr = sorted(r["line_ratio"] for r in done)[len(done) // 2]
        cr = sorted(r["char_ratio"] for r in done)[len(done) // 2]
        un = sum(r["tess_unpaired"] for r in done) / len(done)
        flags = [f"{n} {what}" for what, n in (
            ("empty", sum(r["empty"] for r in done)), ("looped", sum(r["looped"] for r in rows)),
            ("timed out", sum(r["timed_out"] for r in rows)), ("markdown", sum(r["markdown"] for r in done)),
            ("paragraph lines", sum(r["paragraphs"] for r in done)),
            ("low chars", sum(r["char_ratio"] < 0.7 for r in done)),
            ("high chars", sum(r["char_ratio"] > 1.3 for r in done))) if n]
        flagged += bool(flags)
        print(f"{vol:28s} {len(rows):5d} {lr:10.2f} {cr:10.2f} {un:8.1%} {', '.join(flags)}")
    (DATA / "reocr_runs").mkdir(parents=True, exist_ok=True)
    out = DATA / "reocr_runs" / f"screen-{args.slug}.json"
    out.write_text(json.dumps(tiles, indent=0) + "\n", encoding="utf-8")
    print(f"{flagged} volumes flagged; per tile -> {out.relative_to(REPO)}")
    return 0


def joined(lines: list, reference: list) -> list:
    """Candidate lines joined into entries the way the references are (see SCORING above)."""
    refs = [norm(canon(r)) for r in reference]
    exact, memo = set(refs), {}

    def best(t):
        """The best similarity of t to any reference, memoised; references whose upper bound
        cannot beat the best so far are skipped (seq2 is fixed, so difflib caches its index)."""
        n = norm(canon(t))
        if n not in memo:
            top = 1.0 if n in exact else 0.0
            if top < 1.0 and n:
                m = difflib.SequenceMatcher(None, autojunk=False)
                m.set_seq2(n)
                for r in refs:
                    m.set_seq1(r)
                    if m.real_quick_ratio() > top and m.quick_ratio() > top:
                        top = max(top, m.ratio())
            memo[n] = top
        return memo[n]
    out, i = [], 0
    while i < len(lines):
        cur, score_ = lines[i], best(lines[i])
        while i + 1 < len(lines):
            nxt = lines[i + 1]
            merged = joint([cur, nxt])
            s = best(merged)
            if s >= CLOSE and s > score_ and s > best(nxt):
                cur, score_, i = merged, s, i + 1
            else:
                break
        out.append(cur)
        i += 1
    return out


def entry_score(candidate: list, reference: list) -> dict:
    """reocr_bench.page_score on entries: E marks canonical, run-overs joined. Plus per-line
    exactness (for paired comparisons) and E-mark recall and precision against the reference."""
    from reocr_bench import page_score
    ref = [canon(r) for r in reference]
    cand = joined([canon(c) for c in candidate], ref)
    s = page_score(cand, ref)
    cset = {norm(c) for c in cand}
    s["exact_lines"] = {norm(r): norm(r) in cset for r in ref if eligible(norm(r))}
    rmark = [r for r in ref if r.startswith("E ")]
    cn = [norm(c) for c in cand]
    hit = 0
    for r in rmark:
        nr = norm(r)
        j = max(range(len(cn)), key=lambda i: sim(nr, cn[i]), default=None)
        hit += j is not None and sim(nr, cn[j]) >= CLOSE and cand[j].startswith("E ")
    s["marks"] = (hit, len(rmark), sum(c.startswith("E ") for c in cand))
    return s


def score(args) -> int:
    from reocr_bench import OUT, load_candidate
    bench_pages = {(p["volume"], p["leaf"]): p for p in json.loads(OUT.read_text())["pages"]}
    runs = {n: load_candidate(RUNS / f"{n}.jsonl") for n in args.runs}
    keys = sorted(set.intersection(*(set(r) for r in runs.values())) & set(bench_pages))
    if args.pages:
        want = {(s.rsplit("_", 1)[0], int(s.rsplit("_", 1)[1])) for s in args.pages.split(",")}
        keys = [k for k in keys if k in want]
    print(f"{len(keys)} pages every run covers")
    pooled = {n: collections.defaultdict(lambda: [0, 0, 0]) for n in runs}
    exact = {n: {} for n in runs}
    marks = {n: [0, 0, 0] for n in runs}
    for k in keys:
        p = bench_pages[k]
        for n, run in runs.items():
            for kind in ("book", "gold"):
                ref = p["reference"] if kind == "book" else p["gold"]
                if not ref:
                    continue
                s = entry_score(run[k]["lines"], ref)
                agg = pooled[n][kind]
                agg[0] += s["ref"]
                agg[1] += round(s["exact"] * s["ref"])
                agg[2] += round(s["close"] * s["ref"])
                if kind == "gold":
                    exact[n].update({(k, line): v for line, v in s["exact_lines"].items()})
                else:
                    marks[n] = [a + b for a, b in zip(marks[n], s["marks"])]
    for n in runs:
        b, g, m = pooled[n]["book"], pooled[n]["gold"], marks[n]
        print(f"  {n:38s} book exact {b[1] / max(b[0], 1):6.1%} close {b[2] / max(b[0], 1):6.1%}"
              f" ({b[0]}) | gold exact {g[1] / max(g[0], 1):6.1%} close {g[2] / max(g[0], 1):6.1%}"
              f" ({g[0]}) | E marks {m[0]}/{m[1]} found, {m[2]} written")
    names = list(runs)
    for a, b in itertools.combinations(names, 2):
        both = set(exact[a]) & set(exact[b])
        a_only = sum(exact[a][x] and not exact[b][x] for x in both)
        b_only = sum(exact[b][x] and not exact[a][x] for x in both)
        print(f"  gold, line by line: {a} right where {b} wrong {a_only}; the reverse {b_only}"
              f" (of {len(both)})")
    return 0


def _self_test() -> int:
    tess = ["Eplen Mathias, shoemaker, Graham av. n. Mar-", "shall",
            "Esdaile Joseph M. H. capmaker, 157 Water, N.Y.", "h. 188 S. 6th",
            "Ewing Isaac, mariner, 91 N. 5th", "| ~~ ."]
    model = ["Eplen Mathias, shoemaker, Graham av. n. Marshall",
             "Esdaile Joseph M. H. capmaker, 157 Water, N.Y. h. 188 S. 6th",
             "Ewing Isaac, mariner, 91 N. 5th"]
    assert align(tess, model) == [(0, 2, 0), (2, 4, 1), (4, 5, 2), (5, 6, None)], align(tess, model)
    assert split(model[0], tess[0:2]) == ["Eplen Mathias, shoemaker, Graham av. n. Mar-", "shall"]
    assert split(model[1], tess[2:4]) == ["Esdaile Joseph M. H. capmaker, 157 Water, N.Y.",
                                          "h. 188 S. 6th"]
    assert joint(["n. Mar-", "shall"]) == "n. Marshall"
    w = lambda t, h=48: [0, 0, 10 * len(t), h, 90, t]               # noqa: E731 - a word box
    assert mark_of([w("©", 30), w("Hess"), w("Christian")], 48, "Hess")
    assert mark_of([w("EHess"), w("George")], 48, "Hess")
    assert mark_of([w("&Hess"), w("John")], 48, "Hess")
    assert not mark_of([w("EVANS")], 48, "EVANS"), "a capitalised E name is not a mark"
    assert not mark_of([w("Eplen"), w("Mathias")], 48, "Eplen")
    assert not mark_of([w("E", 48), w("Hess")], 48, "Hess"), "a full-height E is a letter"
    rows = pair_tile([[w("€Hess"), w("George,"), w("capmaker,")]], ["Hess George, capmaker"], 48)
    assert rows[0]["text"] == "E Hess George, capmaker" and rows[0]["mark"]
    # LightOn's glyph for the mark, with or without tesseract's: one "E", never "E £Ford"
    for tess_first in ("EFord", "Ford"):
        rows = pair_tile([[w(tess_first), w("George,"), w("engineer")]], ["£Ford George, engineer"], 48)
        assert rows[0]["text"] == "E Ford George, engineer" and rows[0]["mark"], rows[0]
    rows = pair_tile([[w("FORSTER"), w("JAMES,")]], ["=FORSTER JAMES, feathers"], 48)
    assert rows[0]["text"].startswith("=FORSTER") and not rows[0]["mark"], "not before capitals"
    assert turnovers(["Napier John, merchant, 75 Washington, store 10", "[Cedar-street New-York",
                      "Nassau Whiting Factory"]) == [
        "Napier John, merchant, 75 Washington, store 10 Cedar-street New-York", "",
        "Nassau Whiting Factory"]
    assert turnovers(["Smith J, 27 Pros-", "Antonio, cigars, 15 High", "[pect"]) == [
        "Smith J, 27 Prospect", "Antonio, cigars, 15 High", ""]
    assert canon("EHess John") == "E Hess John" and canon("Ebert John") == "Ebert John"
    assert canon("© Hess John") == "E Hess John"
    assert canon("sBowron Josiah") == "E Bowron Josiah" and canon(".EWittsdeldt M") == "E Wittsdeldt M"
    assert canon("Eplen Mathias") == "Eplen Mathias" and canon("Shute Wm") == "Shute Wm"
    assert strip_mark("E Agar James, h. Pacific") == "Agar James, h. Pacific"
    ref = ["Eplen Mathias, shoemaker, Graham av. n. Marshall"]
    assert joined(tess[0:2], ref) == ["Eplen Mathias, shoemaker, Graham av. n. Marshall"]
    assert joined(["Ewing Isaac, mariner, 91 N. 5th", "Eplen Mathias, shoemaker"],
                  ["Ewing Isaac, mariner, 91 N. 5th", "Eplen Mathias, shoemaker"]) == \
        ["Ewing Isaac, mariner, 91 N. 5th", "Eplen Mathias, shoemaker"], "a standing line is kept"
    assert demarkdown("# HES—HEW\n- **Hess** John, h. 5 Ewen  \n| a | b |\n|---|---|") == \
        ["HES—HEW", "- Hess John, h. 5 Ewen", "a b"], "a bullet is 1912's ditto dash: kept"
    page = ["Fletcher G. merchant 104 Maiden Lane N. Y. h 135", "Fletcher James, grocer Nassau c Pearl [Hicks",
            "Smith Jacob, h. Myrtle av. n. Skill-", "Jones Wm. 86 Prince [man", "Brown A. [col'd] 5 Main",
            "Rogers G. F. fishmonger h 80 Pine-", "Rogers F. carpenter 154 Johnson",
            "Rogers J. builder 90 Classon [apple", "Rogers Joshua, grocer 36 Willoughby [h 98 Jay"]
    assert post(page) == ["Fletcher G. merchant 104 Maiden Lane N. Y. h 135 Hicks",
                          "Fletcher James, grocer Nassau c Pearl", "Smith Jacob, h. Myrtle av. n. Skillman",
                          "Jones Wm. 86 Prince", "Brown A. [col'd] 5 Main",
                          "Rogers G. F. fishmonger h 80 Pineapple", "Rogers F. carpenter 154 Johnson",
                          "Rogers J. builder 90 Classon",
                          "Rogers Joshua, grocer 36 Willoughby [h 98 Jay"], post(page)
    assert fractions("Force Harvey, mason 165½ Jackson") == "Force Harvey, mason 165 1/2 Jackson"
    assert fractions("½ Main") == "½ Main" and fractions("12 ¾ Pearl") == "12 3/4 Pearl"
    w = lambda t, x=100: [x, 0, x + 10 * len(t), 30, 90, t]        # noqa: E731 - a word box
    rows = [{"text": t, "words": [w(f)] if f else [], "start": True, "bullet": b, "mark": False}
            for t, f, b in [("Small Wm h 5 Ewen", "Small", False),
                            ("Smalldone Giacomo carpr h 478 Prest", "Smalidone", True),
                            ("E A cigars 445 DeKalb", "I", True),
                            ("Chas lab h 34 4th", "—Chas", False),
                            ("Smalley Arthur chocolates h 1430 35th", "Smalley", True),
                            ("Thos h 104 Koscko", "“Thins", True),
                            ("Smallman John driver h 1024 Prest", "Smallman", False)]]
    got = [r["text"].split(" ")[0] for r in dittos(rows)]
    assert got == ["Small", "Smalldone", "—", "—", "Smalley", "—", "Smallman"], got
    rows = [{"text": t, "words": [], "start": True, "bullet": True, "mark": False}
            for t in ("Abbott Jane, widow", "Abel John, cartman", "Ackerman Wm, grocer")]
    assert not any(r["ditto"] for r in dittos(rows)), "a bulleted list of heads has no dittos"
    junk = ["Gittens Josiah, clerk, 130 Grand", "Glacken Mic clad Hirer 26 8 eT fopirne",
            "Glass John, cartman, 18 Sobwrot"]
    good = ["Gittens Josiah, clerk, 130 Grand", "Glacken Michael, laborer, 125 Stagg",
            "Glass John, cartman, 18 Schols"]
    assert fill_gaps(align(junk, good), junk, good) == [(0, 1, 0), (1, 2, 1), (2, 3, 2)], \
        "a garbled line between two pairs takes the model's reading"
    words = [[100, 10, 180, 40, 80, "€Hess"], [190, 10, 290, 40, 85, "George,"], [300, 10, 420, 40, 20, "capmker,"]]
    rs = respell(words, "E Hess George, capmaker, 60 Ewen", 90)
    assert [w[5] for w in rs] == ["E", "Hess", "George,", "capmaker,", "60", "Ewen"], rs
    assert rs[2][:4] == [190, 10, 290, 40] and rs[2][4] == 90, "a matched word keeps its box"
    assert rs[0][2] <= 100 and rs[1][:4] == [100, 10, 180, 40], "E left of the name, Hess keeps its box"
    assert rs[3][:4] == [300, 10, 420, 40] and rs[3][4] == 90, "capmker anchors capmaker"
    assert rs[4][0] > 420 and rs[5][0] > rs[4][0], "words tesseract never read run on after it"
    assert respell(words, "", 90) == [] and respell([], "Hess", 90) == []
    sl = synth_line("Hess Peter, h. 3", [100, 10, 400, 40], None, 100, 12.0, 30, 90)
    assert [w[5] for w in sl] == ["Hess", "Peter,", "h.", "3"] and sl[0][1] > 40 and sl[0][0] == 100
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["bench", "score", "post", "screen", "dump"])
    ap.add_argument("names", nargs="*", help="bench: the model slug; score: run names")
    ap.add_argument("--kind", default="halves", choices=["halves", "columns", "page"])
    ap.add_argument("--raw", action="store_true", help="read <tile>_<slug>.raw.txt as Churro XML")
    ap.add_argument("--pages", help="score: only these pages, as <volume>_<leaf>")
    ap.add_argument("--root", default="data/reocr_screen", help="screen/dump: the staged half tiles")
    ap.add_argument("--ids", help="dump: only these volumes")
    ap.add_argument("--out-dir", help="dump: write here instead (a dry run: no swap, no sidecar)")
    ap.add_argument("--page-dir", default="data/reocr",
                    help="screen/dump: the pages' tesseract records, <dir>/<id>/<id>_<leaf>.json")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "bench" and len(args.names) == 1:
        args.slug = args.names[0]
        return bench(args)
    if args.cmd == "dump" and len(args.names) == 1:
        args.slug = args.names[0]
        return dump(args)
    if args.cmd == "screen" and len(args.names) == 1:
        args.slug = args.names[0]
        return screen(args)
    if args.cmd == "post" and len(args.names) == 1:
        args.run = args.names[0]
        return post_run(args)
    if args.cmd == "score" and args.names:
        args.runs = args.names
        return score(args)
    ap.error("bench <slug> | score <run> [<run> ...]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
