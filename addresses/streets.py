"""Reading an address as a directory prints it (RENUMBERING_PLAN 1.1).

    python3 addresses/streets.py --self-test
    uv run --with duckdb==2.0.0 python addresses/streets.py data/space/records.parquet

`read("h 462 Court")` -> number 462, street "court". The street is a key: the name's words,
lowercased, then the type, with "st" left off (Court and Court st are one street; Franklin and
Franklin av are two), numbered streets as digits ("h 72 5th av" -> "5 av", "338 N. 2d" ->
"n 2"), B'way spelled out. Also read: the district a line prints (E. D., W. D.), a place marker
(Bklyn, N. Y.), a half number, and a leading r (rear in Brooklyn's directories, rooms in
Trow's later ones). None for a line with no number
("Hamilton n Gates av") or with more after the street than a street has.

With a records file: the share of address lines read, per place, and the commonest strings that
are not, so a re-run on a larger records file shows what the new volumes bring.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "browse"))
import find_address as fa  # noqa: E402

SPELLED = {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
           "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "eleventh": "11",
           "twelfth": "12", "thirteenth": "13"}
DISTRICT = re.compile(r"[, ]+([ew])\.? ?d\.?$")
PLACE = re.compile(r"[, ]+(n\.? ?y\.?|b'?kl?yn\.?|brooklyn|wmsburgh?|l\.? ?i\.?|n\.? ?j\.?)$")
LEAD = re.compile(r"^(?:h\.? ?)?(r\.? ?)?(?:nos?\.? )?(?=[0-9])")   # h, r, "No."; Trow's later "h436"
STUCK = re.compile(r"\b([ewns])([0-9]+(?:st|d|nd|rd|th))\b")         # Trow's later "E138th"
NUMBER = re.compile(r"^([0-9]{1,4})(?: ?(1/2|½))?[a-d]? +")
LETTER_AV = re.compile(r"^(?:av|ave|avenue)\.? ([a-d])$")   # Avenue B: the type comes first
ONE_WORD = {"b'way": "broadway", "bway": "broadway", "broadway": "broadway", "bowery": "bowery"}
SHORT = {"mhtn": "manhattan", "lex": "lexington", "amsterdam": "amsterdam"}


def read(address: str) -> dict | None:
    s = re.sub(r"\s+", " ", (address or "").lower().replace("’", "'")).strip(" .,;")
    lead = LEAD.match(s)
    if not lead:
        return None
    rear, s = bool(lead.group(1)), s[lead.end():]
    number = NUMBER.match(s)
    if not number:
        return None
    s = STUCK.sub(r"\1 \2", s[number.end():].strip(" .,;"))
    district = place = ""
    for _ in range(2):                         # "56 Bedford av, E. D." and "107 Fulton, N. Y."
        if (m := DISTRICT.search(s)):
            district, s = m.group(1), s[:m.start()]
        elif (m := PLACE.search(s)):
            place, s = re.sub(r"[^a-z]", "", m.group(1)), s[:m.start()]
    s = s.strip(" .,;")
    if (m := LETTER_AV.match(s)):
        words, kind = [m.group(1)], "av"
    elif s in ONE_WORD:
        words, kind = [ONE_WORD[s]], ""
    else:
        toks = s.split()
        kind = fa.street_type(toks[-1]) if len(toks) > 1 and len(toks[-1].strip(".")) > 1 else ""
        words = [re.sub(r"[^a-z0-9]", "", t) for t in (toks[:-1] if kind else toks)]
        words = [SPELLED.get(w, fa.ordinal(w) or SHORT.get(w, w)) for w in words if w]
        if len(words) > 1 and words[0] in fa.DIRECTIONS:
            words[0] = fa.DIRECTIONS[words[0]]
    if not words or len(words) > 3 or not all(re.fullmatch(r"[a-z]+|[0-9]{1,3}", w) for w in words) \
            or (len(words) == 1 and len(words[0]) == 1 and words[0].isalpha() and kind != "av"):
        return None
    return {"number": int(number.group(1)), "half": bool(number.group(2)), "r": rear,
            "street": " ".join(words + ([kind] if kind and kind != "st" else [])),
            "district": district, "place": place}


CASES = [   # real lines from the records, and the plan's own
    ("h 462 Court", (462, "court", "")),
    ("141 Court st", (141, "court", "")),
    ("29 4th E.D.", (29, "4", "e")),
    ("h 204 1st E. D.", (204, "1", "e")),
    ("404 E. 75th", (404, "e 75", "")),
    ("h 338 N. 2d", (338, "n 2", "")),
    ("112 1/2 Park av", (112, "park av", "")),
    ("h 902 1/2 Gates av", (902, "gates av", "")),
    ("h 72 5th av", (72, "5 av", "")),
    ("107 5th", (107, "5", "")),
    ("14 1st pl", (14, "1 pl", "")),
    ("66 W. Baltic", (66, "w baltic", "")),
    ("h r 461 Baltic", (461, "baltic", "")),
    ("h 1108 De Kalb av", (1108, "de kalb av", "")),
    ("h 52 St. James' pl", (52, "st james pl", "")),
    ("170 Franklin", (170, "franklin", "")),
    ("282 Franklin av", (282, "franklin av", "")),
    ("h 12 fleet", (12, "fleet", "")),
    ("46 Columbia pl", (46, "columbia pl", "")),
    ("h 16 Debevoise pl", (16, "debevoise pl", "")),
    ("15 Maiden la.", (15, "maiden la", "")),
    ("320 B'way", (320, "broadway", "")),
    ("320 b'way", (320, "broadway", "")),
    ("12 Avenue B", (12, "b av", "")),
    ("h 12 av. B", (12, "b av", "")),
    ("107 Fulton, N. Y.", (107, "fulton", "")),
    ("h 168 Lefferts pl Bklyn", (168, "lefferts pl", "")),
    ("56 Bedford av, E. D.", (56, "bedford av", "e")),
    ("h 258 Fourth", (258, "4", "")),
    ("h436 E138th", (436, "e 138", "")),
    ("r161 W36th", (161, "w 36", "")),
    ("125 E43d", (125, "e 43", "")),
    ("h4241 Bway", (4241, "broadway", "")),
    ("h400 Mhtn av", (400, "manhattan av", "")),
    ("h790 Riverside dr", (790, "riverside dr", "")),
    ("h old No. 263 Kent av", None),
    ("Hamilton n Gates av", None),
    ("Park av c Cumberland", None),
    ("h Throop av", None),
    ("h r Bergen n Vanderbilt av", None),
    ("No. 153 Montague St. LOV—LOW 431", None),
    ("", None),
]


def self_test():
    for line, want in CASES:
        got = read(line)
        got = got and (got["number"], got["street"], got["district"])
        assert got == want, (line, got, want)
    assert read("h r 461 Baltic")["r"] and read("112 1/2 Park av")["half"]
    assert read("107 Fulton, N. Y.")["place"] == "ny"
    print(f"{len(CASES)} cases pass")


def coverage(parquet: str):
    import duckdb
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "results"))
    from renumbering import CITY            # the two places' SQL
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT CASE {' '.join(f"WHEN {sql} THEN '{p}'" for p, sql in CITY.items())} END AS place,
               coalesce(nullif(home_address_resolved, ''), address_resolved) AS a, count(*) AS n
        FROM read_parquet('{parquet}') WHERE a IS NOT NULL AND a <> '' GROUP BY ALL""").fetchall()
    for place in CITY:
        mine = [(a, n) for p, a, n in rows if p == place]
        numbered = [(a, n) for a, n in mine if re.search(r"[0-9]", a)]
        unread = sorted(((n, a) for a, n in numbered if read(a) is None), reverse=True)
        total, lost = sum(n for _, n in numbered), sum(n for n, _ in unread)
        print(f"{place}: {sum(n for _, n in mine):,} address lines, {total:,} with a digit, "
              f"{(total - lost) / total:.1%} of those read")
        print("  commonest not read: " + " | ".join(f"{a} ({n})" for n, a in unread[:25]))


if __name__ == "__main__":
    self_test() if sys.argv[1] == "--self-test" else coverage(sys.argv[1])
