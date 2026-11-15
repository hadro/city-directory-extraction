"""Street guides as rows: the house number at each cross street (RENUMBERING_PLAN 2C, step 1-2).

    python3 addresses/guides.py 1869BPL 1871BPL 1875BPL 1876BPL
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
falls and keeps its odd or even; a misread digit does not), and ok: every number on the street does. Prints, per volume, streets, rows and the share passing.
"""
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import streets  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
COLUMNS = 4
HEADER = re.compile(r"^(left|lef[a-z]|l[ec]ft)\b", re.I)
HEADING = re.compile(r"^([A-Z][^,(]*?)\s*(?:\(([^)]*)\)?)?[\s,.*„]*(?:from|irom|fr0m|see)\b")
RUNS = re.compile(r"\b(from|irom|fr0m|see)\b")
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
    if k == 0 or not re.search(r"[A-Za-z]{2}", name):      # no number or mark: not a crossing
        return None
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


def parse(volume: str) -> list:
    """Row by row, in one of two states: under a "Left. Rt." header, where a row is a crossing,
    or in a heading, which runs from a row that is not a crossing to the next header. A heading
    counts once it says where the street runs ("from", "see"): until then a row that reads as
    a crossing puts things back (a cross street whose marks the OCR lost looks like a start)."""
    want = set(guide_leaves(volume))
    out, entry = [], []
    street = printed = header = None
    heading = None                        # the open heading's lines

    def close():
        if entry:
            ok = gate(entry)
            out.extend(dict(r, seq=i, ok=ok) for i, r in enumerate(entry))
        entry.clear()

    def row_of(c, page, column, y):
        return dict(c, volume=volume, leaf=page["leaf"], column=column, y=round(y),
                    street=street, street_printed=printed, cross=key(c["cross_printed"]))

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
                    m = next((m for i in reversed(range(len(heading or [])))
                              if (m := HEADING.match(" ".join(heading[i:])))), None)
                    printed = m.group(1).strip(" .") if m else None
                    street = None if not m else key(printed) + (
                        " (e.d.)" if re.match(r"E\. ?[DPp!>]", m.group(2) or "") else "")
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
                    elif not c and re.match(r"[A-Z][a-z']", text):
                        heading = [text]
                elif c and not RUNS.search(" ".join(heading)):
                    heading = None                               # it was a cross street after all
                    if street:
                        entry.append(row_of(c, page, column, y))
                else:
                    heading.append(text)
    close()
    return out


def page_width(page: dict) -> float:
    xs = [x for line in page["lines"] for w in line for x in (w[0], w[2])]
    return max(xs) - min(xs)


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
    assert key("Court") == "court" and key("Atlantic av") == "atlantic av"
    print("guides self-test passes")


if __name__ == "__main__":
    if sys.argv[1] == "--self-test":
        self_test()
    else:
        (REPO / "data/addresses/guides").mkdir(parents=True, exist_ok=True)
        for volume in sys.argv[1:]:
            rows = parse(volume)
            with open(REPO / f"data/addresses/guides/{volume}.jsonl", "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
            names = {r["street"] for r in rows}
            good = {r["street"] for r in rows if r["ok"]}
            print(f"{volume}: {len(names)} streets with rows, {len(rows)} rows, "
                  f"{len(good) / max(1, len(names)):.0%} of streets pass the gate, "
                  f"{sum(r['left'] is not None or r['right'] is not None for r in rows)} rows "
                  f"with a number")
