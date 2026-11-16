"""Street guides as rows: the house number at each cross street (RENUMBERING_PLAN 2C, step 1-2).

    python3 addresses/guides.py 1869BPL 1871BPL 1875BPL 1876BPL
    python3 addresses/guides.py --to-read 1871BPL      the off-run rows no one has re-read, as crops
    python3 addresses/guides.py --self-test

A guide entry, as Lain's Brooklyn directories print it (docs/STREET_GUIDES.md):

    Court, from Fulton, at          the street, then where it runs
      City Hall sq., S. to Gow-
      anus bay
    Left. Rt.
      45   46 Joralemon             the number on each side at each cross street, in walking
       †  160 Amity                 order; * the nearest number, — none, † no such side there

The leaves come from the survey (`data_prep/survey/ia_<volume>.json`, runs of kind street_guide
with 10+ leaves) and the words from `data/survey_ocr/<volume>_words.jsonl.gz`. The OCR's own
lines are not used: it splits a row's left number from the rest often enough (14% of 1875's
lines) that rows are rebuilt here from the words, by column (four to a page) and height. A
number is the left or the right one by which header word, "Left." or "Rt.", it sits under.

Writes data/addresses/guides/<volume>.jsonl, a row per crossing: volume, leaf, column, y, street
(streets.read's key), street_printed, seq, left, right, left_mark, right_mark, cross (key),
cross_printed, left_ok and right_ok (the number lies on its side's longest run that rises or
falls and keeps its odd or even; a misread digit does not), and ok: every number on the street does.
`late` is X when the heading says "(late X)" or "(formerly X)". Prints, per volume, headers met and
the ones with no street read (their rows are dropped), streets, rows, and the share off their run.

An off-run number is usually a misread digit, so those rows are read again from the page image
(by an agent, `--to-read` lists them) and the reading is kept in data/addresses/work/guide_read/
<volume>_<leaf>.json, which a re-run applies before the gate and never asks for again:

    {"reads": [{"column": 1, "y": 1612, "street": "court", "ocr": [343, 316], "read": [343, 346],
                "status": "read" | "as_printed" | "unread", "model": ..., "date": ...}]}

"read" changed a number; "as_printed" means the image shows the OCR right (the print is off its
run); "unread" means the digits could not be made out (the OCR's value stays, flagged). A reading
applies to the row at that column and y only while the OCR still gives the same numbers there.
"""
import collections
import gzip
import functools
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import streets  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
READS = REPO / "data/addresses/work/guide_read"
IIIF = "https://iiif.archive.org/iiif/{volume}${leaf}/{x},{y},{w},{h}/full/0/default.jpg"
COLUMNS = 4
HEADER = re.compile(r"^(left|lef[a-z]|l[ec]ft)\b", re.I)
NAME = re.compile(r"(?:[\W_]|[a-z]\s)*((?:[NSEW][.,]\s*)?[A-Za-z0-9][^,(]*)[\s,.]*(?:\(([^)}>\]]*))?")
LATE = re.compile(r"(?:late|lata|lale|formerly|now)\s+(.*?)[\s).,j]*$", re.I)
NUMBER = re.compile(r"^[*•♦#^~'\"-]*([0-9]{1,4})[.,]?$")
DASH = re.compile(r"^[—–_-]+$")
DAGGER = re.compile(r"^(†|[ftj|!]|[•*]?j-|gf|\+|tf|ft)$")


def guide_leaves(volume: str) -> list:
    survey = json.load(open(REPO / f"data_prep/survey/ia_{volume}.json"))
    return [leaf for run in survey["sections"]["runs"]
            if run["kind"] == "street_guide" and run.get("leaves", 0) >= 10
            for leaf in range(run["start_leaf"], run["end_leaf"] + 1)]


def page_rows(page: dict) -> list:
    """The page's words as rows in reading order: (column, y, [(x0, x1, text), ...])."""
    words = [w for line in page["lines"] for w in line if w[5].strip()]
    if not words:
        return []
    left, right = min(w[0] for w in words), max(w[2] for w in words)
    width = (right - left) / COLUMNS
    cols = [[] for _ in range(COLUMNS)]
    for x0, y0, x1, y1, _, text in words:
        cols[min(COLUMNS - 1, int(((x0 + x1) / 2 - left) / width))].append(
            ((y0 + y1) / 2, x0, x1, text, y1 - y0))
    rows = []
    for c, col in enumerate(cols):
        col.sort()
        row, row_y = [], None
        for y, x0, x1, text, h in col:
            if row and y - row_y > max(8, h * 0.6):
                rows.append((c, row_y, sorted(row)))
                row = []
            row.append((x0, x1, text))
            row_y = y if len(row) == 1 else (row_y * (len(row) - 1) + y) / len(row)
        if row:
            rows.append((c, row_y, sorted(row)))
    return rows


def crossing(words: list, x_left: float, x_right: float) -> dict | None:
    """A row under a Left/Rt header as a crossing; None when it holds no cross street."""
    out = {"left": None, "right": None, "left_mark": "", "right_mark": ""}
    k = 0
    for k, (x0, x1, text) in enumerate(words):
        centre = (x0 + x1) / 2
        side = "left" if abs(centre - x_left) <= abs(centre - x_right) else "right"
        parts = re.findall(r"[*•♦#^]*[0-9]{1,4}|[—–]+|†", text) if re.search(
            r"[0-9][*•♦—–†][0-9*]|^[—–]{2,}$", text) else [text]   # "*245*244", "——" run together
        if len(parts) == 2:
            for side, part in zip(("left", "right"), parts):
                _set(out, side, part)
            continue
        if not _set(out, side, text):
            break
    else:
        return None
    name = " ".join(t for _, _, t in words[k:]).strip(" .,")
    if k == 0 or not re.search(r"[A-Za-z]{2}", name) or re.search(r"\b(from|bet)\b", name):
        return None                          # no number or mark, or "1 Oth, from Gowanus": not a crossing
    return dict(out, cross_printed=name)


def _set(out: dict, side: str, text: str) -> bool:
    if (m := NUMBER.match(text)):
        if out[side] is not None:              # two numbers under one header: the second is the right
            side = "right"
        out[side] = int(m.group(1))
        out[side + "_mark"] = "*" if re.match(r"[*•♦#]", text) else ""
    elif DASH.match(text):
        out[side + "_mark"] = "-"
    elif DAGGER.match(text):
        out[side + "_mark"] = "+"
    else:
        return False
    return True


def key(name: str) -> str:
    """A street's key as streets.read gives it, from a printed name ("Court", "Atlantic av")."""
    r = streets.read("1 " + name)
    return r["street"] if r else re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def in_run(ns: list) -> list:
    """Which of the numbers lie on the longest run that only rises (or only falls) and keeps
    one parity: True for those, False for the rest (a misread digit, a stray token)."""
    best = []
    for sign in (1, -1):
        for parity in (0, 1):
            idx = [i for i, n in enumerate(ns) if n % 2 == parity]
            runs = []                                   # longest non-decreasing run ending at each
            for a, i in enumerate(idx):
                prev = max((runs[b] for b in range(a) if sign * ns[idx[b]] <= sign * ns[i]),
                           key=len, default=[])
                runs.append(prev + [i])
            best = max([best, *runs], key=len)
    return [i in set(best) for i in range(len(ns))]


def gate(rows: list) -> bool:
    """Every number on the street is on its side's run: the street needs no second reading.
    Sets left_ok and right_ok on each row (None where the side has no number)."""
    good = True
    for side in ("left", "right"):
        at = [i for i, r in enumerate(rows) if r[side] is not None]
        flags = in_run([rows[i][side] for i in at])
        for r in rows:
            r[side + "_ok"] = None
        for i, flag in zip(at, flags):
            rows[i][side + "_ok"] = flag
        good = good and all(flags)
    return good


def is_from(word: str) -> bool:
    """The word "from" as the OCR leaves it (froin, Irom, fVom), but not Front or Frost, streets."""
    return SequenceMatcher(None, word.lower(), "from").ratio() >= 0.6


def read_heading(lines: list) -> dict | None:
    """The street heading the lines end in: printed name, the "(E. D.)" mark and the "(late X)"
    name. It is the last run of lines that holds a "from" (the OCR's garbled ones too) after a
    name of at most 40 characters, which ends at the first comma or "(": a qualifier
    ("Lincoln pl., Degraw, from") and the "(late X)" lie between. An entry with no crossings
    ("Cottage row, E. side of Columbia (one block)") may lie before it."""
    for upper in (True, False):               # a lowercase name ("main") only when no other reads
        for i in reversed(range(len(lines))):
            text = re.sub(r"(?<=[a-z])- ", "", " ".join(lines[i:]))    # hyphen-wrapped lines
            at = next((p for p in range(1, min(len(text) - 3, 70)) if text[p - 1] in " .,;}]>'"
                       and is_from(text[p:p + 4])
                       and text[p:p + 5].lower() not in ("front", "frost")), None)
            m = at and NAME.match(text[:at])
            name = m and re.sub(r"^([NSEW]),", r"\1.", m.group(1).strip(" ."))    # "N, 5th"
            if (m and len(name) <= 40 and (name[0].isupper() or name[0].isdigit() or not upper)
                    and not re.search(r"\)|\b(from|bet|and|opp)\b", name)):
                paren = m.group(2) or ""
                late = LATE.search(paren)
                return {"printed": name, "late": late and late.group(1) or None,
                        "ed": bool(re.match(r"[EKI]\S?\. ?\S", paren))}   # "(E. D.)" as the OCR reads it
    return None


def one_off(a: str, b: str) -> bool:
    """b is a with one letter wrong, missing or added (not a direction: n oxford, s oxford)."""
    ops = [o for o in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != "equal"]
    return len(ops) == 1 and max(ops[0][2] - ops[0][1], ops[0][4] - ops[0][3]) == 1 \
        and len(a.split()[0]) > 1


def snap(rows: list, stats: dict) -> None:
    """A heading the OCR misspelled ("Conrt") takes the name of the cross street one letter off
    it that the guide prints at least 3 times, when its own name is not printed as one (a street
    crosses others, and each lists it)."""
    cross = collections.Counter(r["cross"] for r in rows)
    for r in rows:
        name, _, ed = r["street"].partition(" (e.d.)")
        if cross[name] < 2 and len(name) >= 5:
            if (best := next((c for c, n in cross.most_common() if n >= 3 and one_off(name, c)), 0)):
                stats.setdefault("snapped", set()).add((name, best))
                r["street"] = best + (" (e.d.)" if r["street"] != name else "")


@functools.lru_cache(maxsize=None)
def cached(volume: str, leaf: int) -> dict:
    """The readings kept for one leaf, by (column, y)."""
    path = READS / f"{volume}_{leaf}.json"
    return {(e["column"], e["y"]): e for e in json.load(open(path))["reads"]} if path.exists() else {}


def reread(rows: list) -> None:
    """Put the numbers read from the image in place of the OCR's, where it still reads the same."""
    for r in rows:
        e = cached(r["volume"], r["leaf"]).get((r["column"], r["y"]))
        if e and e["status"] != "unread" and e["ocr"] == [r["left"], r["right"]]:
            r["left"], r["right"] = e["read"]


def parse(volume: str, stats: dict | None = None) -> list:
    """Row by row, in one of two states: under a "Left. Rt." header, where a row is a crossing,
    or in a heading, which runs from a row that is not a crossing to the next header. A heading
    counts once it says where the street runs ("from", "see"): until then a row that reads as
    a crossing puts things back (a cross street whose marks the OCR lost looks like a start)."""
    want = set(guide_leaves(volume))
    out, entry = [], []
    street = printed = late = header = None
    heading = None                        # the open heading's lines
    stats = {} if stats is None else stats
    stats.update(headers=0, unread=[])    # headers met; the headings read as no street

    def close():
        if entry:
            reread(entry)
            ok = gate(entry)
            out.extend(dict(r, seq=i, ok=ok) for i, r in enumerate(entry))
        entry.clear()

    def row_of(c, page, column, y):
        return dict(c, volume=volume, leaf=page["leaf"], column=column, y=round(y),
                    street=street, street_printed=printed, late=late, cross=key(c["cross_printed"]))

    with gzip.open(REPO / f"data/survey_ocr/{volume}_words.jsonl.gz", "rt") as f:
        for line in f:
            page = json.loads(line)
            if page["leaf"] not in want:
                continue
            for column, y, words in page_rows(page):
                text = " ".join(t for _, _, t in words)
                if HEADER.match(text) and len(words) <= 3:
                    close()
                    # the heading is the last run of lines that reads as one: an entry with no
                    # crossings ("Cottage row, E. side of Columbia (one block)") may lie before it
                    m = read_heading(heading or [])
                    printed, late = m and m["printed"], m and m["late"]
                    stats["headers"] += 1
                    if not m:
                        stats["unread"].append((page["leaf"], column, round(y), heading))
                    street = None if not m else key(printed) + (" (e.d.)" if m["ed"] else "")
                    x_left = (words[0][0] + words[0][1]) / 2
                    x_right = (words[1][0] + words[1][1]) / 2 if len(words) > 1 else x_left + 75
                    header, heading = (column, x_left, x_right), None
                    continue
                c = None
                if header:
                    x_left, x_right = header[1], header[2]
                    if column != header[0]:   # the entry runs on in the next column
                        shift = (column - header[0]) * page_width(page) / COLUMNS
                        x_left, x_right = x_left + shift, x_right + shift
                    c = crossing(words, x_left, x_right)
                if heading is None:
                    if c and street:
                        entry.append(row_of(c, page, column, y))
                    elif not c:
                        heading = [text]
                elif c and not read_heading(heading):
                    heading = None                               # it was a cross street after all
                    if street:
                        entry.append(row_of(c, page, column, y))
                else:
                    heading.append(text)
    close()
    snap(out, stats)
    return out


def page_width(page: dict) -> float:
    xs = [x for line in page["lines"] for w in line for x in (w[0], w[2])]
    return max(xs) - min(xs)


def to_read(volume: str) -> None:
    """Print the off-run rows with no reading kept, in windows of a column (about 20 rows), each
    with the IIIF address of its crop. The page's pixels are the image's: the OCR's page size is
    the scan's (checked: the crop has the size asked for), so a region is the OCR's own box."""
    rows = [json.loads(line) for line in open(REPO / f"data/addresses/guides/{volume}.jsonl")]
    bad = [r for r in rows if (r["left_ok"] is False or r["right_ok"] is False)
           and (r["column"], r["y"]) not in cached(volume, r["leaf"])]
    leaves, geometry = {r["leaf"] for r in bad}, {}
    with gzip.open(REPO / f"data/survey_ocr/{volume}_words.jsonl.gz", "rt") as f:
        for line in f:
            if (page := json.loads(line))["leaf"] in leaves:
                xs = [x for l in page["lines"] for w in l for x in (w[0], w[2])]
                geometry[page["leaf"]] = (min(xs), (max(xs) - min(xs)) / COLUMNS, *page["page_size"])
    windows = []
    for r in sorted(bad, key=lambda r: (r["leaf"], r["column"], r["y"])):
        if windows and windows[-1][:2] == [r["leaf"], r["column"]] and r["y"] - windows[-1][2][0]["y"] < 450:
            windows[-1][2].append(r)
        else:
            windows.append([r["leaf"], r["column"], [r]])
    for leaf, column, rs in windows:
        left, width, page_w, page_h = geometry[leaf]
        x, y = max(0, round(left + column * width - 20)), max(0, rs[0]["y"] - 70)
        url = IIIF.format(volume=volume, leaf=leaf, x=x, y=y, w=round(min(page_w - x, width + 40)),
                          h=min(page_h - y, rs[-1]["y"] + 70 - y))
        print(f"{volume} {leaf} col {column} {url}")
        for r in rows:       # every row the crop shows, the flagged ones starred
            if r["leaf"] == leaf and r["column"] == column and rs[0]["y"] - 70 <= r["y"] <= rs[-1]["y"] + 70:
                off = [s for s in ("left", "right") if r[s + "_ok"] is False]
                print(f"    y {r['y']} {r['street']} / {r['cross_printed']}: {r['left']} {r['right']}"
                      + (f"  * off: {', '.join(off)}" if r in rs else ""))
    print(f"{len(bad)} rows in {len(windows)} windows on {len(leaves)} leaves", file=sys.stderr)


def self_test():
    c = crossing([(100, 130, "45"), (160, 190, "46"), (195, 280, "Joralemon")], 115, 175)
    assert (c["left"], c["right"], c["cross_printed"]) == (45, 46, "Joralemon")
    c = crossing([(110, 120, "f"), (150, 190, "160"), (195, 250, "Amity")], 115, 175)
    assert (c["left"], c["left_mark"], c["right"]) == (None, "+", 160)
    c = crossing([(100, 190, "*245*244"), (195, 250, "Sackett")], 115, 175)
    assert (c["left"], c["right"], c["left_mark"]) == (245, 244, "*")
    c = crossing([(150, 190, "10"), (195, 280, "Montague")], 115, 175)
    assert (c["left"], c["right"]) == (None, 10)
    assert crossing([(100, 190, "anus"), (195, 250, "bay")], 115, 175) is None
    assert gate([{"left": 1, "right": 2}, {"left": 45, "right": 46}])
    rows = [{"left": 343, "right": 316}, {"left": 361, "right": 366}, {"left": 383, "right": 406}]
    assert gate(rows) and in_run([323, 343, 316, 366]) == [False, False, True, True]
    rows = [{"left": 303, "right": 304}, {"left": 323, "right": 324}, {"left": 343, "right": 316},
            {"left": 361, "right": 366}]
    assert not gate(rows) and rows[2]["right_ok"] is False and rows[2]["left_ok"] is True
    assert crossing([(100, 110, "1"), (115, 200, "Oth, from Gowanus")], 105, 175) is None
    h = read_heading(["Lincoln pl., Degraw, from", "Franklin, S. to Fulton"])    # a qualifier
    assert (h["printed"], h["late"], h["ed"]) == ("Lincoln pl", None, False)
    h = read_heading(["STREET", "Fairfax (late Elizabeth), from", "Union av., bet. 3d and 5th"])
    assert (h["printed"], h["late"]) == ("Fairfax", "Elizabeth")
    h = read_heading(["Banzett, (late Dtbe-", "voise), from Maspeth av., bet."])   # wrapped line
    assert (h["printed"], h["late"]) == ("Banzett", "Dtbevoise")
    assert read_heading(["3d pl., from Henry, bet.", "2d pl. and 4th pl., S. E."])["printed"] == "3d pl"
    assert read_heading(["N, 5th (E. D), from E.", "river, bet. N. 4th"])["printed"] == "N. 5th"
    assert read_heading(["Prospect (E. I).)f from"])["ed"]
    assert read_heading(["Hanson pi., froin", "Fiatbush av., at Raymond"])["printed"] == "Hanson pi"
    assert read_heading(["main, from E. River, at"])["printed"] == "main"          # lowercase
    assert read_heading(["Hicks, from Fulton, bet.", "Henry and Front, S. W."])["printed"] == "Hicks"
    assert read_heading(["Eagle (late Division", "Street), from Fulton"])["printed"] == "Eagle"
    rows = [{"street": "conrt", "cross": c} for c in ("court",) * 3 + ("conrt",) * 0]
    snap(rows, {})
    assert rows[0]["street"] == "court" and one_off("conrt", "court") and not one_off("n oxford", "s oxford")
    assert key("Court") == "court" and key("Atlantic av") == "atlantic av"
    print("guides self-test passes")


if __name__ == "__main__":
    if sys.argv[1] == "--self-test":
        self_test()
    elif sys.argv[1] == "--to-read":
        to_read(sys.argv[2])
    else:
        (REPO / "data/addresses/guides").mkdir(parents=True, exist_ok=True)
        for volume in sys.argv[1:]:
            stats = {}
            rows = parse(volume, stats)
            with open(REPO / f"data/addresses/guides/{volume}.jsonl", "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
            names = {r["street"] for r in rows}
            good = {r["street"] for r in rows if r["ok"]}
            nums = [(r[s], r[s + "_ok"]) for r in rows for s in ("left", "right") if r[s] is not None]
            print(f"{volume}: {stats['headers']} headers, {len(stats['unread'])} with no street, "
                  f"{len(names)} streets with rows, {len(rows)} rows, "
                  f"{sum(r['left'] is not None or r['right'] is not None for r in rows)} with a "
                  f"number, {sum(ok is False for _, ok in nums) / max(1, len(nums)):.1%} of the "
                  f"numbers off their run, {len(good) / max(1, len(names)):.0%} of streets pass "
                  f"the gate")
