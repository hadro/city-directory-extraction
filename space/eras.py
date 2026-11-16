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
Without the file the finder works as it did: `load` gives {} and `forms` None; a file from before
its `old_street` and `keys` columns reads as old numbers under the street's own key and no other
keys.

The crosswalk's street is the registry's id (addresses/registry.py), which is not always a key as
printed. A chain's old numbers were printed under `old_street` ("fulton av" for some of Fulton's,
"e baltic" and "w baltic" for the two halves of Baltic, each numbered from 1 at Court st until 1875):
that is what its group is titled with and searched under. `keys` are the other printed keys of
the id, so a typed "Elliott pl" reaches "s elliott pl" and a line printed "E. Baltic" in 1875-89 is
the new number's, not another street's (measured: Hirsh 303 E. Baltic 1875 is 303 Baltic 1876-78).

fit.py is imported, not copied: it holds across/back/graded and needs only the standard library,
so a Space takes it beside this file as it takes find_address.py. A typed range, "644-696 Court
st, before 1871-75", is the link's form: it searches every other number of the range in the old
years.
"""
from __future__ import annotations

import csv
import re
import sys
import tempfile
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
KINDS = {"av", "pl", "rd", "ct", "sq", "te", "al", "la", "dr", "bl", "ro", "co"}   # registry.KIND
RANGE = re.compile(r"(\d+)-(\d+)\s+(.+?)(?:,?\s+before\s+(\d{4})(?:-\d+)?)?")
NOTE = ("{street} was renumbered between the {y0} and {y1} directories, and this number is past "
        "what the mapping reaches (or on a side it has no answer for): a line from before {y1} "
        "may be about another house.")


def load(path) -> dict:
    """{(place, street): (y0, y1, [chain, ...], [old_street, ...], [other key, ...])}, a chain
    [(old, new, corner), ...] and its old_street; {} if the file is not there."""
    if not Path(path).exists():
        return {}
    events, chains, olds, keys = {}, {}, {}, {}
    for r in csv.DictReader(open(path)):
        key = (r["place"], r["street"])
        events[key] = (int(r["y0"]), int(r["y1"]))
        chains.setdefault(key, {}).setdefault(int(r["chain"]), []).append(
            (int(r["old"]), int(r["new"]), r["corner"] == "true"))
        olds.setdefault(key, {})[int(r["chain"])] = r.get("old_street") or r["street"]
        keys[key] = (r.get("keys") or "").split(";") if r.get("keys") else []
    return {k: (*events[k], list(chains[k].values()), list(olds[k].values()), keys[k]) for k in events}


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
    # else the id this printed key is another name of (Elliott pl: s elliott pl)
    return key if (place, key) in cw else next((s for (p, s), v in cw.items()
                                                if p == place and key in v[4]), None)


def printed(key: str) -> str:
    """The street as a person types it, from a key: 'e baltic' -> 'E Baltic st', 'fulton av' ->
    'Fulton av' (a key leaves the st off)."""
    words = key.split()
    kind = words.pop() if len(words) > 1 and words[-1] in KINDS else "st"
    return " ".join([w.capitalize() for w in words] + [kind])


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
    on). The new number is the first form: searched as typed; its `same` is the directions its lines may lead the
    street with and still be the street ("E", "W" for Baltic). An old form's street is the key
    its chain's old numbers were printed under (`old_street`), as a person types it."""
    address, district = split_district(address)
    if (m := RANGE.fullmatch(address)):
        lo, hi, rest = int(m[1]), int(m[2]), m[3]
        street = street_of(cw, place, *fa.parse(f"1 {rest}")[1:], district)
        if not street or not lo < hi or (hi - lo) // 2 + 1 > RANGE_MAX:
            return None
        y0, y1 = cw[(place, street)][:2]
        when = f"{y0}-{str(y1)[2:]}"
        return {"forms": [dict(old_form(list(range(lo, hi + 1, 2)), rest, when,
                                        {"years": (None, y0), "era": f"before {when}",
                                         "grade": "", "rests": "A range you asked for."}),
                               title=f"As {lo}-{hi} {rest}, before {when}")], "note": "",
                "range": True}
    number, words, kind = fa.parse(address)
    rest = address.split(None, 1)[1]
    typed = street_key(words, kind, district)
    street = street_of(cw, place, words, kind, district)
    # "13 E Baltic st" is a half's old form, not a new number: no groups, as before
    if not street or (typed != street and typed.partition(" ")[2] == street):
        return None
    y0, y1, chains, olds, others = cw[(place, street)]
    when = f"{y0}-{str(y1)[2:]}"
    old = []
    for chain, old_key in zip(chains, olds):
        g = fit.graded(chain, int(number), 1)
        if g and g[2] in "AB":
            lo, hi, grade = g
            # the street the old numbers were printed under: what was typed unless that is another
            at = rest if old_key == typed else printed(old_key)
            base = {"years": (None, y0), "era": f"before {when}", "grade": grade,
                    "rests": rests_on(chain, int(number), grade)}
            if hi - lo > WIDE:
                form = old_form([lo, hi], at, when, base)
                form.update(numbers=[], span=(lo, hi), link=f"{lo}-{hi} {at}, before {when}")
            else:
                form = old_form(list(range(lo, hi + 1, 2)), at, when, base)
            old.append(form)
    if not old:
        return {"forms": [], "note": NOTE.format(street=street.title(), y0=y0, y1=y1)}
    # the directions the id's other keys lead the typed one with: "E. Baltic" lines are Baltic's
    same = sorted({k[:-len(typed)].strip().upper() for k in [street, *others]
                   if k.endswith(" " + typed)})
    new = {"title": f"As {number} {rest}, {y1} on", "street": rest, "numbers": [int(number)],
           "years": (y1, None), "only": False, "era": f"{y1} on", "same": same,
           "grade": "", "rests": "Brooklyn's lines from before the change are not here: they used the "
                                  "old numbers, below. Other places' lines are here in every year."}
    return {"forms": [new, *old], "note": ""}


def five(cw: dict) -> dict:
    """The test entries as `load` gives them: old numbers under the street's own key, no other keys."""
    return {k: (*v, [k[1]] * len(v[2]), []) for k, v in cw.items()}


def self_test():
    cw = five({("Brooklyn", "court"): (1871, 1875, [
              [(216, 294, False), (222, 296, False), (210, 288, False), (230, 300, True)],
              [(643, 459, False), (651, 467, False), (647, 463, True), (660, 470, False)]]),
          ("Brooklyn", "myrtle av"): (1871, 1875, [[(687, 677, False), (731, 679, False)],
                                                  [(893, 673, False), (967, 681, False)]])})
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
    wide = five({("Brooklyn", "x"): (1871, 1875, [[(100, 10, False), (160, 20, False), (200, 40, False)]])})
    f = forms(wide, "30 X st")["forms"][1]
    assert f["numbers"] == [] and f["link"] == "160-200 X st, before 1871-75", f
    narrow = five({("Brooklyn", "x"): (1871, 1875, [[(100, 10, False), (110, 20, False)]])})
    assert forms(narrow, "14 X st")["forms"][1]["numbers"] == [100, 102, 104, 106, 108, 110]
    # the link's form: every other number of the range, in the old years
    r = forms(wide, "100-120 X st, before 1871-75")["forms"][0]
    assert r["numbers"] == list(range(100, 121, 2)) and r["years"] == (None, 1871)
    assert forms(wide, "100-9000 X st") is None
    # the renamed and merged streets, made up: each of old_street's numbers is the new number's,
    # one chain per old street, as export_crosswalk.py writes them (id, [(old_street, old)], new, keys)
    shapes = [("fulton", [("fulton", 52), ("fulton av", 1174)], 100, "fulton av"),
              ("baltic", [("e baltic", 13), ("w baltic", 13)], 13, "e baltic;w baltic"),
              ("warren", [("e warren", 13), ("w warren", 13)], 13, "e warren;w warren"),
              ("atlantic av", [("atlantic", 37), ("atlantic av", 107)], 43, "atlantic"),
              ("carroll", [("carroll park", 5)], 9, "carroll park;carroll pl"),
              ("duffield", [("stanton", 5)], 9, "stanton"),
              ("fleet pl", [("carll", 5), ("fleet pl", 7)], 9, "carll"),
              ("s elliott pl", [("elliott pl", 20)], 30, "elliott pl")]
    with tempfile.TemporaryDirectory() as d:
        new = Path(d) / "new.csv"
        new.write_text("place,street,y0,y1,chain,old,new,corner,old_street,keys\n" + "".join(
            f"Brooklyn,{i},1871,1875,{c},{old},{n},false,{o},{keys}\n"
            for i, chains, n, keys in shapes for c, (o, old) in enumerate(chains)))
        was = Path(d) / "was.csv"                 # a file from before old_street and keys
        was.write_text("place,street,y0,y1,chain,old,new,corner\n" + "".join(
            f"Brooklyn,{i},1871,1875,{c},{old},{n},false\n"
            for i, chains, n, _ in shapes for c, (o, old) in enumerate(chains)))
        cw8, cw0 = load(new), load(was)
    assert load(Path(new).parent / "none.csv") == {}
    assert cw0[("Brooklyn", "baltic")][3:] == (["baltic"] * 2, []), "no columns: as before"
    assert cw8[("Brooklyn", "baltic")][3:] == (["e baltic", "w baltic"], ["e baltic", "w baltic"])

    def heads(cw, text):
        p = forms(cw, text)
        return p and [f["title"].split(", before")[0] for f in p["forms"][1:]], p and p["forms"][0]
    when = "before 1871-75 (renumbered between those directories)"
    # a Fulton av number is searched on Fulton av; a typed Fulton st keeps its own old numbers
    assert forms(cw8, "100 Fulton st")["forms"][1]["title"] == f"As 52 Fulton st, {when}"
    assert forms(cw8, "100 Fulton st")["forms"][2]["title"] == f"As 1174 Fulton av, {when}"
    assert forms(cw8, "100 Fulton st")["forms"][2]["street"] == "Fulton av"
    assert heads(cw8, "100 Fulton av")[0] == ["As 52 Fulton st", "As 1174 Fulton av"], "typed av reaches fulton"
    # Baltic: "13 Baltic" was two houses; "E. Baltic" lines after 1875 are the new number's
    h, new_form = heads(cw8, "13 Baltic st")
    assert h == ["As 13 E Baltic st", "As 13 W Baltic st"] and new_form["same"] == ["E", "W"], h
    assert heads(cw8, "13 Warren st")[0] == ["As 13 E Warren st", "As 13 W Warren st"]
    assert forms(cw8, "13 E Baltic st") is None, "an old form typed is not a new number"
    r = forms(cw8, "1-9 E Baltic st, before 1871-75")["forms"][0]
    assert r["street"] == "E Baltic st" and r["numbers"] == [1, 3, 5, 7, 9], r
    # Atlantic av: old numbers on Atlantic st and on Atlantic av, two streets; Atlantic st finds it
    assert heads(cw8, "43 Atlantic av")[0] == ["As 37 Atlantic st", "As 107 Atlantic av"]
    assert heads(cw8, "43 Atlantic")[0] == ["As 37 Atlantic", "As 107 Atlantic av"]   # typed as typed
    assert heads(cw8, "9 Carroll pl")[0] == ["As 5 Carroll Park st"]
    assert heads(cw8, "9 Duffield st")[0] == ["As 5 Stanton st"]
    assert heads(cw8, "9 Fleet pl")[0] == ["As 5 Carll st", "As 7 Fleet pl"]
    # Elliott pl is S Elliott pl: typed either way, one old street, no direction to forgive in the
    # typed street's own key
    assert heads(cw8, "30 Elliott pl")[0] == heads(cw8, "30 S Elliott pl")[0] == ["As 20 Elliott pl"]
    assert heads(cw8, "30 Elliott pl")[1]["same"] == ["S"] and heads(cw8, "30 S Elliott pl")[1]["same"] == []
    assert forms(cw0, "13 Baltic st")["forms"][1]["title"] == f"As 13 Baltic st, {when}", "old file"
    assert forms(cw0, "13 E Baltic st") is None
    assert printed("e baltic") == "E Baltic st" and printed("fulton av") == "Fulton av"
    assert fa.parse("13 " + printed("e baltic")) == ("13", ["e", "baltic"], "st")
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
