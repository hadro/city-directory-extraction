"""
A renumbered street's old numbers, for the finder (RENUMBERING_PLAN Phase 5). Brooklyn renumbered
most streets between the 1871 and 1875 directories, so 465 Court st before the change was about
no. 643-651, and a search for 465 alone misses everyone listed there.

    uv run --with duckdb==2.0.0 python space/eras.py        # the asserts

`load` reads crosswalk.csv, which addresses/export_crosswalk.py writes from the fitted chains
(data/space/, beside the records), and `forms` says, for a typed address, what to search: the new
number in the years after the change, and each run of old numbers in the years before it. Each run
is a bracket from fit.graded (new to old): its numbers searched together (search.find_numbers) on
the old side the chain is for, unless it is wider than WIDE, when it is a note and a link that runs
the search on the range.
Without the file the finder works as it did: `load` gives {} and `forms` None.

fit.py is imported, not copied: it holds across/back/graded and needs only the standard library,
so a Space takes it beside this file as it takes find_address.py. A typed range, "644-696 Court
st, before 1871-75", is the link's form: it searches every other number of the range in the old
years.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

try:
    import fit                                    # deployed: copied in beside this file
except ImportError:                               # in the repo: addresses/fit.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "addresses"))
    import fit

from search import fa

WIDE = 20          # a bracket of old numbers wider than this is a note and a link, not a search
AROUND = 5         # a longer one is searched at most this many numbers either side of its middle
RANGE_MAX = 60     # numbers in a typed range: one search, ~0.05-0.4 s a number (street size)
# addresses/streets.py's SPELLED: "Fourth av" is street "4 av"
SPELLED = {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
           "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "eleventh": "11",
           "twelfth": "12", "thirteenth": "13", "bway": "broadway"}     # fa.parse reads b'way as bway
# streets.py's: "56 Bedford av, E. D."
DISTRICT = re.compile(r"[, ]+([ew])\.? ?d\.?$", re.I)
RANGE = re.compile(r"(\d+)-(\d+)\s+(.+?)(?:,?\s+before\s+(\d{4})(?:-\d+)?)?")
NOTE = ("{street} was renumbered between the {y0} and {y1} directories, and this number is past "
        "what the mapping reaches (or on a side it has no answer for): a line from before {y1} "
        "may be about another house.")


def load(path) -> dict:
    """{(place, street): (y0, y1, [chain, ...])}, a chain [(old, new, corner), ...]; {} if the
    file is not there."""
    if not Path(path).exists():
        return {}
    events, chains = {}, {}
    for r in csv.DictReader(open(path)):
        key = (r["place"], r["street"])
        events[key] = (int(r["y0"]), int(r["y1"]))
        chains.setdefault(key, {}).setdefault(int(r["chain"]), []).append(
            (int(r["old"]), int(r["new"]), r["corner"] == "true"))
    return {k: (*events[k], list(chains[k].values())) for k in events}


def split_district(address: str) -> tuple:
    """('56 Bedford av', 'e') from '56 Bedford av, E. D.': fa.parse cannot read the district."""
    address = address.strip()
    return (address[:m.start()], m[1].lower()) if (m := DISTRICT.search(address)) else (address, "")


def street_key(words: list, kind: str, district: str = "") -> str:
    """The crosswalk's key (addresses/streets.py's, events.py's) from fa.parse's reading of what
    was typed: 'Court st' -> 'court', 'Myrtle av' -> 'myrtle av', '5th av' -> '5 av', 'N 2d' ->
    'n 2', "B'way" -> 'broadway'. A street printed with no type is a st, which the key leaves
    off ('Franklin' is 'franklin', not 'franklin av': two streets); an Eastern District street is
    another street than its namesake and its key says so ('bedford av (e.d.)'). The checks hold
    it to streets.read. It does not read a place after the street or a 1/2."""
    words = [SPELLED.get(w) or fa.ordinal(w) or w for w in words]
    return " ".join(words + ([kind] if kind not in ("", "st") else [])) + \
        (" (e.d.)" if district == "e" else "")


def street_of(cw: dict, place: str, words: list, kind: str, district: str = "") -> str | None:
    """The crosswalk's street for a typed one, or None. A bare name is the st, never the one
    street of that name and another type: in Brooklyn's records an avenue is printed with its
    type (Myrtle av 95%, Bedford av 96%; the rest is mostly another street, Union st, Columbia st),
    so '155 Franklin' is not Franklin av's."""
    key = street_key(words, kind, district)
    return key if (place, key) in cw else None


def rests_on(chain: list, number: int, grade: str) -> str:
    """What an answer rests on: the anchors of the chain's side within fit.NEAR of the number."""
    side = [p for p in chain if p[1] % 2 == number % 2]
    near = [p for p in side if abs(p[1] - number) <= fit.NEAR]
    people = sum(not p[2] for p in near)
    corners = len(near) - people
    text = f"Grade {grade}: rests on {people} {'person' if people == 1 else 'people'} followed " \
           f"across the change within {fit.NEAR} numbers"
    text += f" and {corners} street-guide corner{'s' * (corners != 1)}" if corners else ""
    if grade == "B":
        lo = max(p[1] for p in side if p[1] <= number)
        hi = min(p[1] for p in side if p[1] >= number)
        text += f"; the nearest on each side are at {lo} and {hi}"
    return text + "."


def old_form(numbers: list, rest: str, when: str, extra: dict) -> dict:
    """One group's search: the numbers (every other one of a bracket, at most 2 * AROUND + 1
    around its middle), or none with a link for one too wide."""
    lo, hi = numbers[0], numbers[-1]
    label = f"{lo}-{hi}" if lo != hi else str(lo)
    if len(numbers) > 2 * AROUND + 1:
        mid = (lo + hi) / 2
        numbers = sorted(sorted(numbers, key=lambda n: abs(n - mid))[:2 * AROUND + 1])
    return {"title": f"As {label} {rest}, before {when} (renumbered between those directories)",
            "street": rest, "numbers": numbers, "only": True, **extra}


def forms(cw: dict, address: str, place: str = "Brooklyn") -> dict | None:
    """What to search for a typed address on a street the crosswalk knows: {"forms": [...],
    "note": str}, or None. A form has title, street (as typed), numbers (the old numbers to
    search; none for a bracket wider than WIDE, which has its `span` and a `link`, the range as a
    typed address), years (low, high), only (old numbers are Brooklyn's lines only; the new
    number keeps every other place's lines of any year), era, grade and rests (what it stands
    on). The new number is the first form: searched as typed."""
    address, district = split_district(address)
    if (m := RANGE.fullmatch(address)):
        lo, hi, rest = int(m[1]), int(m[2]), m[3]
        street = street_of(cw, place, *fa.parse(f"1 {rest}")[1:], district)
        if not street or not lo < hi or (hi - lo) // 2 + 1 > RANGE_MAX:
            return None
        y0, y1, _ = cw[(place, street)]
        when = f"{y0}-{str(y1)[2:]}"
        return {"forms": [dict(old_form(list(range(lo, hi + 1, 2)), rest, when,
                                        {"years": (None, y0), "era": f"before {when}",
                                         "grade": "", "rests": "A range you asked for."}),
                               title=f"As {lo}-{hi} {rest}, before {when}")], "note": "",
                "range": True}
    number, words, kind = fa.parse(address)
    rest = address.split(None, 1)[1]
    if not (street := street_of(cw, place, words, kind, district)):
        return None
    y0, y1, chains = cw[(place, street)]
    when = f"{y0}-{str(y1)[2:]}"
    old = []
    answered = False
    for chain in chains:
        g = fit.graded(chain, int(number), 1)
        if g and g[2] in "AB":
            lo, hi, grade = g
            base = {"years": (None, y0), "era": f"before {when}", "grade": grade,
                    "rests": rests_on(chain, int(number), grade)}
            if hi - lo > WIDE:
                form = old_form([lo, hi], rest, when, base)
                form.update(numbers=[], span=(lo, hi), link=f"{lo}-{hi} {rest}, before {when}")
            else:
                form = old_form(list(range(lo, hi + 1, 2)), rest, when, base)
            old.append(form)
    if not old:
        return {"forms": [], "note": NOTE.format(street=street.title(), y0=y0, y1=y1)}
    new = {"title": f"As {number} {rest}, {y1} on", "street": rest, "numbers": [int(number)],
           "years": (y1, None), "only": False, "era": f"{y1} on",
           "grade": "", "rests": "Brooklyn's lines from before the change are not here: they used the "
                                  "old numbers, below. Other places' lines are here in every year."}
    return {"forms": [new, *old], "note": ""}


def self_test():
    cw = {("Brooklyn", "court"): (1871, 1875, [
              [(216, 294, False), (222, 296, False), (210, 288, False), (230, 300, True)],
              [(643, 459, False), (651, 467, False), (647, 463, True), (660, 470, False)]]),
          ("Brooklyn", "myrtle av"): (1871, 1875, [[(687, 677, False), (731, 679, False)],
                                                  [(893, 673, False), (967, 681, False)]])}
    p = forms(cw, "294 Court st")
    assert [f["title"] for f in p["forms"]] == [
        "As 294 Court st, 1875 on",
        "As 216 Court st, before 1871-75 (renumbered between those directories)"], p
    assert p["forms"][1]["numbers"] == [216] and p["forms"][1]["grade"] == "A"
    assert "followed across the change" in p["forms"][1]["rests"]
    assert forms(cw, "100 Fulton st") is None and forms({}, "294 Court st") is None
    assert forms(cw, "9999 Court st")["forms"] == [] and "past what the mapping reaches" in \
        forms(cw, "9999 Court st")["note"]
    # a bare name is the st, never the one other type there is; a typed type must match
    assert street_of(cw, "Brooklyn", ["myrtle"], "av") == "myrtle av"
    assert street_of(cw, "Brooklyn", ["myrtle"], "") is None
    assert street_of(cw, "Brooklyn", ["myrtle"], "st") is None
    assert street_of(cw, "Brooklyn", ["court"], "") == "court"
    assert street_of(cw, "Brooklyn", ["court"], "pl") is None
    # a district is part of the key, and its namesake is another street
    assert split_district("56 Bedford av, E. D.") == ("56 Bedford av", "e")
    assert split_district("56 Bedford av E.D.") == ("56 Bedford av", "e")
    assert split_district("56 Bedford av") == ("56 Bedford av", "")
    ed = {("Brooklyn", "myrtle av (e.d.)"): cw[("Brooklyn", "myrtle av")]}
    assert forms(ed, "677 Myrtle av, E. D.")["forms"][1]["street"] == "Myrtle av"
    assert forms(ed, "677 Myrtle av") is None and forms(cw, "677 Myrtle av, E. D.") is None
    # a wide bracket is a note with the link that searches the range
    wide = {("Brooklyn", "x"): (1871, 1875, [[(100, 10, False), (160, 20, False), (200, 40, False)]])}
    f = forms(wide, "30 X st")["forms"][1]
    assert f["numbers"] == [] and f["link"] == "160-200 X st, before 1871-75", f
    narrow = {("Brooklyn", "x"): (1871, 1875, [[(100, 10, False), (110, 20, False)]])}
    assert forms(narrow, "14 X st")["forms"][1]["numbers"] == [100, 102, 104, 106, 108, 110]
    # the link's form: every other number of the range, in the old years
    r = forms(wide, "100-120 X st, before 1871-75")["forms"][0]
    assert r["numbers"] == list(range(100, 121, 2)) and r["years"] == (None, 1871)
    assert forms(wide, "100-9000 X st") is None
    # the typed street to the crosswalk's key, as addresses/streets.py reads the same text
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "addresses"))
        import streets
    except ImportError:
        streets = None
    for text in ("465 Court st", "465 Court", "677 Myrtle av", "12 Myrtle Avenue", "5 Hicks street",
                 "14 Lefferts pl", "30 Clinton Place", "100 15th st", "100 5th av", "7 Fourth av",
                 "125 S 4th st", "125 South 4th", "338 N. 2d", "9 East 110th st", "12 De Kalb av",
                 "5 Broadway", "20 Montague court", "3 Atlantic ave", "155 Franklin",
                 "155 Franklin av", "56 Bedford av, E. D.", "29 4th E.D.", "320 B'way", "320 Bway"):
        number, words, kind = fa.parse(split_district(text)[0])
        if streets:
            read = streets.read(text)
            assert street_key(words, kind, split_district(text)[1]) == \
                read["street"] + " (e.d.)" * (read["district"] == "e"), text
    print("eras self-test passes" + ("" if streets else " (streets.py not found: keys unchecked)"))


if __name__ == "__main__":
    self_test()
