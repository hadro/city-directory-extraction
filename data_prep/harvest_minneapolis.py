# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Build a small IN-DOMAIN US eval set from the Minneapolis 1900 city-directory ground truth
published by adamrangwala/DirCity ("Directory Crop-out with Key Lines"), mapped into this
project's union schema.

Why this source: it is a *US* directory (Minneapolis, 1900) -- a third real dialect/era
between NYC Trow/Doggett 1850-1890 and Tulsa 1921 -- and it is **MIT licensed**, so unlike the
CC-BY-SA-NC NYU set it could even seed a permissive, image-paired US benchmark (the "key gap"
in docs/plan.md). But what ships in that repo is line-level OCR *transcription* gold
(~832 lines / 10 pages, `ground_truth/*.txt`), NOT parsed records -- the repo's own
`*_enhanced_template.json` is an empty annotation scaffold. So this converter does the
pre-fill the repo never did: it parses each transcribed line into the union schema as a
**silver** draft, to be hand-reviewed into gold (same silver->review pattern as
harvest_own.py). The parse is rule-based and conservative; the two things most needing review
are flagged inline below.

Get the data (MIT):
    git clone https://github.com/adamrangwala/DirCity_Directory_Crop-out-with-Key-Lines data/minneapolis
    python3 harvest_minneapolis.py --dir data/minneapolis/ground_truth --out data/minneapolis_eval.jsonl

Dialect notes (Minneapolis 1900), grounded on the real `ground_truth/*.txt` lines:
  * surname-first with INHERITANCE [review item #1]: a surname is printed once ("Cook Ira M")
    and following entries drop it ("Jacob H, ...", "Mary (wid George A), ..."), inheriting the
    run's surname. Recovering that from plain text is lossy -- pass --surname for single-surname
    pages (the bundled pages are mostly one surname each) or review the `name` field after.
  * residency codes r / b / bds / rms / res / h / rear (like Tulsa's r/b/rms), kept verbatim in
    the address value to match how Tulsa is stored.
  * widow spouse marker "(wid George A)"; titles "Mrs"/"Miss"; employer embedded in the
    occupation clause ("clk P J Kinnane", "bkpr G C Christian"). No race markers in this set.

Schema mapping (silver; [review item #2] = occupation/employer/work-vs-home split):
    name            <- inherited surname + given/initials (+ title)
    spouse_name     <- "wid X"  from "(wid X)"
    occupation_role <- leading abbrev of the occupation clause   ("bkpr", "clk", "lawyer")
    employer        <- capitalized remainder that isn't a street ("G C Christian", "Soo Shops")
    address         <- the printed work address if any, else the residency-coded residence
    home_address    <- the residency-coded residence when a separate work address is present
    is_business     <- light heuristic ("& Co", "Bros", "estate of")
    race_designation<- "" (absent in this source)

Usage
-----
    python3 harvest_minneapolis.py --dir data/minneapolis/ground_truth --out data/minneapolis_eval.jsonl
    python3 harvest_minneapolis.py --dir data/minneapolis/ground_truth --surname Cook   # single-surname page
    python3 harvest_minneapolis.py --self-test                                          # offline, no data needed
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from typing import Optional

# Must match data_prep/synth_persons.py FIELDS
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

TITLES = {"Mrs", "Miss", "Mr", "Rev", "Dr", "Capt", "Col", "Gen", "Prof", "Hon"}

# Given-name lexicon biases the inheritance call toward "continuation" (a line that starts with
# a known given name keeps the run's surname). Not exhaustive -- a name not listed just falls
# back to the new-surname branch, which review/--surname fixes.
GIVEN = {
    "John", "William", "James", "Charles", "George", "Henry", "Patrick", "Michael", "Thomas",
    "Edward", "Frederick", "Joseph", "Samuel", "Frank", "Jacob", "Peter", "Daniel", "Robert",
    "Walter", "Earl", "Lester", "Leonard", "Otis", "Clarence", "Roy", "Ernest", "Louis", "Paul",
    "Noah", "Rudolph", "Ira", "Judson", "Lawrence", "Nereus", "Albert", "Arthur", "Harry",
    "Mary", "Margaret", "Catherine", "Anna", "Elizabeth", "Sarah", "Ellen", "Hannah", "Julia",
    "Emma", "Jane", "Carrie", "Ada", "Fannie", "Nettie", "Laura", "Jennie", "Juliette", "Lella",
    "Mabelle", "Myra", "Nora", "Bessie", "Pearl", "Hattie", "Lula", "Grace", "Florence", "Alice",
}

# residency-coded clause: r / b / bds / rms / res / h / rear  (longest-first so 'rms' wins over 'r')
_RESID = re.compile(r"^(rms|bds|res|rear|r|b|h)\b", re.I)
# street-ish tokens that mark an *address* rather than an employer
_ADDRISH = re.compile(r"\d|\b(av|ave|st|bldg|cor|flat|blk|ter|pl|sq|blvd|road|rd|home)\b", re.I)
_BIZ = re.compile(r"&|\bCo\b|\bBros\b|\bestate of\b|\bSons\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" ,.")


def _split_first_comma(s: str):
    """Split on the first top-level comma (commas inside '(wid ...)' don't count)."""
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            return s[:i].strip(), s[i + 1:].strip()
    return s.strip(), ""


def _is_noise(ln: str) -> bool:
    """Skip page/column headers, page numbers, and ALL-CAPS banners -- keep entry lines."""
    if len(ln) < 6:
        return True
    if not any(c.islower() for c in ln):       # ALL-CAPS header banner
        return True
    if re.fullmatch(r"[\dIVXLC.\s-]+", ln):     # bare page/section numbers
        return True
    return False


def _split_occ(clause: str):
    """occupation = leading lowercase abbrev tokens; remainder = employer or work-address.
    Stop at the first capitalized token (employer) OR address-ish token (digit / 'flat' / 'av'
    / 'cor' ...) so a lowercase street word like 'flat' isn't eaten as an occupation."""
    toks = clause.split()
    i = 0
    while i < len(toks) and toks[i][:1].islower() and not _ADDRISH.search(toks[i]):
        i += 1
    return " ".join(toks[:i]).strip(), " ".join(toks[i:]).strip()


def to_record(name_seg: str, rest: str, current_surname: str, forced: bool):
    """Return (record, new_surname). new_surname carries the run's surname to the next line."""
    # --- spouse "(wid X)" + title, then surname inheritance -> name -----------------------
    spouse = ""
    m = re.search(r"\(wid\s+([^)]+)\)", name_seg, re.I)
    if m:
        spouse = "wid " + _norm(m.group(1))
        name_seg = (name_seg[:m.start()] + name_seg[m.end():])
    toks = _norm(name_seg).split()
    title = toks.pop(0) if (toks and toks[0].strip(".") in TITLES) else ""
    if not toks:
        return None, current_surname
    head = toks[0].strip(".")
    if forced and current_surname:
        surname = current_surname
        given = toks[1:] if head == current_surname else toks
    elif current_surname and (head in GIVEN or (len(head) == 1 and head.isalpha())):
        surname, given = current_surname, toks            # continuation: inherit
    else:
        surname, given = head, toks[1:]                   # new surname run starts here
    name = _norm(" ".join(([surname] if surname else []) + ([title] if title else []) + given))
    if not name:
        return None, current_surname

    # --- occupation / employer / work-vs-residence address --------------------------------
    clauses = [c for c in (x.strip() for x in rest.rstrip(". ").split(",")) if c]
    res_i = next((i for i in range(len(clauses) - 1, -1, -1) if _RESID.match(clauses[i])), None)
    residence = clauses[res_i] if res_i is not None else ""
    nonres = [c for i, c in enumerate(clauses) if i != res_i]

    occ = employer = work = ""
    if nonres:
        occ, rem = _split_occ(nonres[0])
        bucket = [rem] + nonres[1:] if rem else nonres[1:]
        for c in bucket:
            if _ADDRISH.search(c):
                work = _norm((work + " " + c).strip())
            else:
                employer = _norm((employer + " " + c).strip())

    if work:
        address, home_address = work, _norm(residence)
    else:
        address, home_address = _norm(residence), ""

    record = {
        "name": name,
        "is_business": bool(_BIZ.search(name)),
        "spouse_name": spouse,
        "race_designation": "",
        "occupation_role": _norm(occ),
        "employer": employer,
        "address": address,
        "home_address": home_address,
    }
    return record, surname


def iter_examples(lines, surname0: str, forced: bool, year: str, source: str):
    surname = surname0
    for ln in lines:
        ln = ln.strip()
        if not ln or _is_noise(ln):
            continue
        name_seg, rest = _split_first_comma(ln)
        rec, surname = to_record(name_seg, rest, surname, forced)
        if rec is None or not rec["address"]:
            continue
        yield {
            "raw_line": _norm(ln),
            "context": {"dialect": "minneapolis", "alphabetical_range": "",
                        "directory_year": year, "source": source},
            "record": rec,
        }


SELF_TEST = [
    "Cook Ira M, bkpr G C Christian, rms 802 2d av n.",
    "Jacob H, lawyer 507 Kasota bldg, r 1318 Mt Curve av.",
    "James, clk P J Kinnane, b 1607 n 4th.",
    "James W, b Soldiers' Home.",
    "Mrs Laura W, stenogr Am Bridge Co, b 1016 s e 7th.",
    "Mary (wid George A), b 1231 s 9th.",
    "Nora M (wid Joseph), dressmkr flat 8 728 Nicollet av, r same.",
]


def _self_test() -> int:
    rows = list(iter_examples(SELF_TEST, "Cook", True, "1900", "self-test"))
    for ex in rows:
        print(f"  IN : {ex['raw_line']!r}", file=sys.stderr)
        print(f"  OUT: {'|'.join(str(ex['record'][f]) for f in FIELDS)}", file=sys.stderr)
    assert len(rows) == len(SELF_TEST), f"dropped rows: {len(rows)}/{len(SELF_TEST)}"
    assert all(r["record"]["name"].startswith("Cook ") for r in rows), "surname inheritance failed"
    two = next(r for r in rows if r["raw_line"].startswith("Jacob"))
    assert two["record"]["address"] == "507 Kasota bldg" and two["record"]["home_address"] == "r 1318 Mt Curve av", two
    wid = next(r for r in rows if r["raw_line"].startswith("Mary"))
    assert wid["record"]["spouse_name"] == "wid George A", wid
    nora = next(r for r in rows if r["raw_line"].startswith("Nora"))
    assert nora["record"]["occupation_role"] == "dressmkr" and nora["record"]["address"].startswith("flat"), nora
    print("self-test OK", file=sys.stderr)
    return 0


def _collect_txt(d: str):
    for pat in (os.path.join(d, "*.txt"), os.path.join(d, "ground_truth", "*.txt")):
        hits = sorted(p for p in glob.glob(pat) if "template" not in os.path.basename(p).lower())
        if hits:
            return hits
    return []


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="folder with ground_truth/*.txt (or the repo root)")
    ap.add_argument("--out", default=None, help="output .jsonl (default: stdout)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--year", default="1900")
    ap.add_argument("--surname", default="", help="force the run's surname (best for single-surname pages)")
    ap.add_argument("--self-test", action="store_true", help="run on built-in samples; no data needed")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.dir:
        ap.error("--dir is required (or use --self-test)")

    files = _collect_txt(args.dir)
    if not files:
        sys.exit(f"no ground_truth *.txt found under {args.dir}")

    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    kept = 0
    samples = []
    try:
        for path in files:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            for ex in iter_examples(lines, args.surname, bool(args.surname), args.year,
                                    os.path.basename(path)):
                out.write(json.dumps(ex, ensure_ascii=False) + "\n")
                kept += 1
                if len(samples) < 4:
                    samples.append(ex)
                if args.limit and kept >= args.limit:
                    raise StopIteration
    except StopIteration:
        pass
    finally:
        if args.out:
            out.close()

    print(f"kept={kept} (SILVER -- review name-inheritance + occ/employer split) "
          f"from {len(files)} file(s) -> {args.out or 'stdout'}", file=sys.stderr)
    for s in samples:
        print(f"  IN : {s['raw_line']!r}", file=sys.stderr)
        print(f"  OUT: {'|'.join(str(s['record'][f]) for f in FIELDS)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
