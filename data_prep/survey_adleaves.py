#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Which leaves inside a residential listing are not listing: the full-page ad inventory.

    python3 data_prep/survey_adleaves.py features             # -> data/survey_ocr/adleaf_features.jsonl.gz
    python3 data_prep/survey_adleaves.py inventory --write   # -> results/adleaf_inventory.json + sidecars
    python3 data_prep/survey_adleaves.py --self-test

WHY. `survey_derive.py scope` keeps every line on every leaf inside a residential run, and by
design an advertising page does not break a run (docs/SURVEY_PLAN.md, "Section inventory"). So a
full-page ad bound into the alphabet goes to the model, and the model, which never refuses,
returns its copy as people. PAGE_TYPE_CLASSIFIER.md phase 3 counts 166 such leaves in 1906BPL's
letter-block gaps alone, and calls them the easy case. This inventory finds them corpus-wide,
from the word dumps and without a model.

`features` records, for every text leaf inside a residential run:

    entry_share        the share of its lines with an entry's shape (ENTRY_RX): the one that
                       decides. Every other field is kept for reading, and none separated pages:
    lines, chars       the leaf's hOCR lines and the pageindex character count
    ad_score           ia_volume_to_jsonl.page_geometry: big-type area share + over-wide lines
    letter, share      the modal sort key of its lines (detect_listing_bounds.sort_keys) and its
                       share. A listing page of dittos hardly votes, so a low share is no proof
    local, fits        the nearest confident pages' letters, and whether this page's fits them
    scoped             how many of its lines `scope` passed to the model

`inventory` calls a page `non-entry` when its entry share is under max(ENTRY_FLOOR,
min(ENTRY_MIN, ENTRY_REL x the volume's median)). That covers full-page ads, and listing pages
whose OCR failed. Either way, the lines on it are not entries, and the model would make people
of them. Checked against the page images (2026-09-28):
- 1906BPL's four band-labelled no-body leaves: all four flagged (entry share 0.0).
- 11 pages read off the image: all 7 full-page ads flagged (0.0); both listing pages whose OCR
  had failed flagged (Trow 1910 p2 leaf 59 has 94 garbled lines from a dense three-column page;
  micro 0040 leaf 26 has 13); both 1906BPL listing pages under ad bands kept (0.41, 0.52).
- A line-count rule tried first flagged the two failed-OCR listing pages AND missed the
  *Brooklyn Eagle Almanac*'s 230-line price list (1906BPL leaf 130): dense text ads look busy.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import multiprocessing
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OCR = REPO / "data" / "survey_ocr"
SIDECARS = HERE / "survey"
RESULTS = REPO / "results"
sys.path.insert(0, str(HERE))

from detect_listing_bounds import sort_keys  # noqa: E402
from ia_volume_to_jsonl import page_geometry, words_to_lines  # noqa: E402

MIN_CHARS = 50          # below this a leaf is blank or a film frame
LOCAL = 4               # listing pages either side that set the local letter
ENTRY_MIN = 0.15        # entry-shaped lines a listing page carries at least (1906BPL: p10 0.44)
ENTRY_REL = 0.30        # ...or, in a volume whose narrow columns split entries across lines, this
                        # share of its median page: Trow 1922/23's five columns median 0.28-0.31
ENTRY_FLOOR = 0.05      # below this a page is never listing, whatever its volume: an ad reads 0.0,
                        # a page the OCR failed on 0.03-0.08 (Trow 1910 p2 leaf 59, micro 0040 leaf 26)
# An entry-shaped line, in any era. Needed because a listing page of dittos barely votes a
# letter: 1906BPL leaf 139 has 351 lines and 12 voters. Ad copy rarely has any of these shapes:
#  - a residence marker before a number or a street ("h 241 Hull", "r. 12 Pine", "bds 59
#    Duane"), glued to its number from the 1910s ("h180 E64th", "r205 W141st"; without the glued
#    form 1915, 1917 and 1922/23 scored no entries at all);
#  - a name, then a house number and a street ("Smith John, grocer, 12 Pine"), the number
#    followed by a comma in 1786-1796 ("Brower N. merchant, 95, Water-street");
#  - one street near another, with no number ("Orchard nr Anderson av", "Bridge n Fulton",
#    and after a trade: "Davis Samuel, engineer n Gold");
#  - the side of a street, the rural Bronx villages' way ("w s Clinton 2d h w Seventh", "n w c
#    Governeur & Morris av"); without it Morrisania's whole listing read as non-entry.
#  - a CORPORATION's entry, which has no residence marker and wraps over three or four narrow
#    lines (added 2026-10-04): an incorporation or trade-name tag ("Ukrainian Exch Inc (N Y)",
#    "Electric Novelty Co (RTN)"), a firm word opening its parties ("Co (", "Assn ("), an
#    officer ("Sol Kashman pres", "nett mgr 147 W23d", "sec131 Bowery"), or an address in the
#    directory's own form ("124 E14th", "Bway R309"). Without it, 82 of the 87 flagged pages in
#    Trow 1915, 1917 and 1922/23 were "AMERICAN ...", "NATIONAL ..." listing pages: Trow 1917
#    leaf 245 scored 0.03, and 0.65 with it. None of the four forms appears in ad copy, which
#    capitalises its firm ("ROOFING CO.") and spells out its street ("52 Stone Street").
TAGS = (r"N ?Y|RTN|TN|N ?J|Pa|Del|Conn|Mass|Me|Va|W ?Va|Ill|Ohio|Mich|R ?I|Md|Ind|Wis|Mo|Cal"
        r"|Ky|Tenn|Ga|N ?H|Vt|Minn|La|Tex|Can|Eng")
CORP_RX = re.compile(rf"[(<](?:{TAGS})\)"
                     r"|\b(?:Co|Inc|Corp|Corpn|Assn|Soc|Exch|Mfg|Bros|Cos|Ltd|Agcy)\b\.?\s*[(<]"
                     r"|\b(?:pres|v-pres|v-ps?|sec|treas|sec-treas|mgr|agt|supt)(?:\b|(?=\d))"
                     r"|\b\d{1,5}\s+[NSEW]\s?\d{1,3}(?:st|d|th)\b"
                     r"|\bR\d{3,4}\b")
ENTRY_RX = re.compile(r"\b(?:h|r|b|bds|res|rms|ho|house)\.?(?:\s+(?:\d|[A-Z][a-z])|\d)"
                      r"|^\W{0,3}[A-Z][A-Za-z'’]+,?\s+[A-Z][A-Za-z.]*[,.]?.*?\b\d{1,5},?\s+[A-Z][a-z]"
                      r"|[A-Za-z]{3,}\s+(?:nr|n|c|cor|near|bet)\.?\s+[A-Z][a-z]"
                      r"|\b(?:[nsew]\s){1,2}[sc]\s+[A-Z0-9]"
                      r"|" + CORP_RX.pattern)


def residential_leaves(doc: dict) -> set:
    runs = [r for r in (doc.get("sections") or {}).get("runs", []) if r.get("residential")]
    return {leaf for r in runs for leaf in range(r["start_leaf"], r["end_leaf"] + 1)}


def scoped_per_leaf(ident: str) -> collections.Counter:
    out = collections.Counter()
    path = OCR / f"{ident}_listing.jsonl.gz"
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                out[json.loads(line)["context"]["leaf"]] += 1
    return out


def leaf_features(ident: str) -> list:
    doc = json.loads((SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
    res = residential_leaves(doc)
    if not res:
        return []
    scoped = scoped_per_leaf(ident)
    rows = []
    with gzip.open(OCR / f"{ident}_words.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            leaf = rec["leaf"]
            if leaf not in res:
                continue
            raw = words_to_lines(rec["lines"]) if rec["lines"] else []
            if rec["chars"] < MIN_CHARS or not raw:
                rows.append({"leaf": leaf, "chars": rec["chars"], "lines": len(raw), "blank": True,
                             "scoped": scoped.get(leaf, 0)})
                continue
            _h, _w, ad = page_geometry([(b, t, b[3] - b[1]) for b, t in raw])
            keys = sort_keys(t for _b, t in raw)
            c = collections.Counter(keys)
            letter, n = c.most_common(1)[0] if c else (None, 0)
            entries = sum(1 for _b, t in raw if ENTRY_RX.search(t))
            rows.append({"leaf": leaf, "chars": rec["chars"], "lines": len(raw), "blank": False,
                         "ad_score": round(ad, 3), "voters": len(keys), "letter": letter,
                         "share": round(n / len(keys), 3) if keys else 0.0,
                         "entry_share": round(entries / len(raw), 3),
                         "scoped": scoped.get(leaf, 0)})
    # the local letter: the modal letter of the nearest confident pages on either side
    sure = [r for r in rows if not r["blank"] and r.get("share", 0) >= 0.5 and r["voters"] >= 10]
    for r in rows:
        if r["blank"]:
            continue
        before = [s["letter"] for s in sure if s["leaf"] < r["leaf"]][-LOCAL:]
        after = [s["letter"] for s in sure if s["leaf"] > r["leaf"]][:LOCAL]
        near = collections.Counter(before + after)
        r["local"] = "".join(sorted(near)) if near else None
        r["fits"] = bool(r["letter"]) and any(
            abs(ord(r["letter"]) - ord(x)) <= 1 for x in near) if near else None
    return rows


def page_kind(r: dict, median: float = 1.0) -> str:
    """blank / listing / non-entry, given the volume's median entry share over its text pages.

    A non-entry page's lines are not entries, whatever they are:
    a full-page ad, a table, prose, or OCR too garbled to hold an entry's shape. Telling the last
    apart from the others was tried with a clean-word share and failed: garbled microfilm
    (micro_IABROOKLYN_0047, "rapa Sete fe reer). ig seni mt") scored 0.55-0.60, the same as
    prose, because OCR noise makes plausible three-letter words. Which VOLUMES are unreadable is
    better read off the volume: its printed name count, or its twin (survey_counts, survey_twins)."""
    if r["blank"]:
        return "blank"
    bar = max(ENTRY_FLOOR, min(ENTRY_MIN, ENTRY_REL * median))
    return "listing" if r["entry_share"] >= bar else "non-entry"


def _features_one(ident: str):
    return ident, leaf_features(ident)


def inventory(args) -> int:
    """Per volume: its non-entry pages inside residential runs and the scoped lines on them.
    With --write, each volume that has any gets a sidecar block `non_entry_pages`."""
    import datetime as _dt
    rows = collections.defaultdict(list)
    with gzip.open(args.features, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            rows[r.pop("id")].append(r)
    report, total, flagged = {}, 0, 0
    for ident, rs in sorted(rows.items()):
        shares = sorted(r["entry_share"] for r in rs if not r["blank"])
        median = shares[len(shares) // 2] if shares else 0.0
        kinds = collections.Counter(page_kind(r, median) for r in rs)
        bad = [r for r in rs if page_kind(r, median) == "non-entry"]
        scoped = sum(r["scoped"] for r in rs)
        lost = sum(r["scoped"] for r in bad)
        total += scoped
        flagged += lost
        report[ident] = {"pages": dict(kinds), "median_entry_share": round(median, 3), "scoped_lines": scoped, "non_entry_lines": lost,
                         "non_entry_share": round(lost / scoped, 4) if scoped else None,
                         "leaves": [{k: r[k] for k in ("leaf", "lines", "entry_share",
                                                        "ad_score", "scoped")} for r in bad]}
        if args.write and not bad:
            # a volume whose last flagged page was cleared must lose the block, or its stale
            # leaves keep reaching the stager (it used to be left as it was)
            path = SIDECARS / f"ia_{ident}.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.pop("non_entry_pages", None) is not None:
                path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        if args.write and bad:
            path = SIDECARS / f"ia_{ident}.json"
            doc = json.loads(path.read_text(encoding="utf-8"))   # re-read: never clobber others
            doc["non_entry_pages"] = {
                "method": "entry-shape", "derived": _dt.date.today().isoformat(),
                "entry_min": ENTRY_MIN, "scoped_lines": lost,
                "note": "pages inside residential runs whose OCR lines are not entry-shaped: "
                        "full-page ads, blank pages read through the paper, or listing pages "
                        "the OCR failed on. scope keeps them; hpc/prep_volumes.py skips them "
                        "by default, and they are the re-OCR queue.",
                "leaves": [r["leaf"] for r in bad]}
            path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    out = RESULTS / "adleaf_inventory.json"
    out.write_text(json.dumps({"derived": _dt.date.today().isoformat(), "entry_min": ENTRY_MIN,
                               "scoped_lines": total, "non_entry_lines": flagged,
                               "volumes": report}, indent=1) + "\n", encoding="utf-8")
    print(f"{flagged:,} of {total:,} scoped lines ({flagged / total:.2%}) sit on non-entry pages")
    for ident, v in sorted(report.items(), key=lambda kv: -kv[1]["non_entry_lines"])[:15]:
        print(f"  {ident:30s} {v['pages'].get('non-entry', 0):4d} pages "
              f"{v['non_entry_lines']:7,d}/{v['scoped_lines']:9,d} lines "
              f"({(v['non_entry_share'] or 0):.1%})")
    print(f"-> {out.relative_to(REPO)}{' + sidecars' if args.write else ''}")
    return 0


def features(args) -> int:
    idents = sorted(p.stem[3:] for p in SIDECARS.glob("ia_*.json")
                    if (OCR / f"{p.stem[3:]}_words.jsonl.gz").exists())
    if args.ids:
        idents = [i for i in idents if i in set(args.ids.split(","))]
    out = Path(args.out)
    n = 0
    with multiprocessing.Pool(max(1, (os.cpu_count() or 2) - 1)) as pool, \
            gzip.open(out, "wt", encoding="utf-8") as fh:
        for ident, rows in pool.imap_unordered(_features_one, idents):
            for r in rows:
                fh.write(json.dumps({"id": ident, **r}) + "\n")
            n += len(rows)
    print(f"{n:,} residential leaves in {len(idents)} volumes -> {out}")
    return 0


def _self_test() -> int:
    assert page_kind({"blank": False, "entry_share": 0.10}, median=0.31) == "listing", \
        "Trow 1922/23: five narrow columns split entries across lines"
    assert page_kind({"blank": False, "entry_share": 0.10}, median=0.53) == "non-entry"
    assert page_kind({"blank": False, "entry_share": 0.03}, median=0.0) == "non-entry", \
        "a volume the OCR failed on does not lower the bar to nothing"
    assert ENTRY_RX.search("Brower N. merchant, 95, Water-street"), "1786 sets a comma after the number"
    assert sort_keys(["Smith John, 12 Pine", "Smyth Wm, 3 Oak", "MANUFACTURER OF"]) == ["S", "S"], \
        "display capitals do not vote"
    for entry in ("44 Clara L wid h 241 Hull", '" Peter mechanic h 668 DeKalb av',
                  "Holmes Isaac, policeman, 53 Butler", "Flood James, cartman 67 Tillary",
                  "Hyer Jane, b. Bridge n Fulton", '" Jno H r205 W141st',
                  "-Adolph v pres 15 W28th & pres 74 E92d h180 E64th",
                  "Baxter John, lbr., Orchard nr Anderson av",
                  "Sasche John, shoemkr, n s Milton 1st h e Courtland av",
                  "Eyan James, peddler, n w c Governeur & Morris av",
                  "Davis Samuel, engineer n Gold",
                  # corporations, Trow 1917 leaf 245 and 1922/23 p2 leaf 295 (2026-10-04)
                  "ii Ukrainian Exch Inc (N Y) Simon Vad-", "ii Star Line Inc <N Y) Moses Ginsberg",
                  '" Electric Novelty Co (RTN) (Sol Beid-', "11 Display Co (TN) (David BonSeld)",
                  "Sol Kashman pres Simon Kashman", "nett mgr 147 W23d", "124 E14th", "Bway R309"):
        assert ENTRY_RX.search(entry), entry
    for ad in ("No. 113— American Pulpit. Price. 10 cents.", "5 PARK PLACE - - - - MANHATTAN",
               "The Brooklyn Eagle Almanac", "Telephone 828 Bushwick"):
        assert not ENTRY_RX.search(ad), ad
    # ad copy that names a firm and an address, from flagged pages read off the image: the
    # corporate shapes must add none of it (the all-caps first line already matched the
    # name-then-address form before them; its page still scores 0.00)
    for ad in ("NEW YORK ROOF REPAIRING CO., 100 William Street, New York City",
               "50 & 52 Stone Street", "L. L.WALDORF CO.",
               "Conner's United States Type Foundry, Nos. 29, 31 & 33 Beekman Street",
               "Hugh McAtamney Co. Woolworth Building Phone 7760 Barclay",
               "PHONE — JOHN 31S1 See Advertisement in Roofers' Dept."):
        assert not CORP_RX.search(ad), ad
    print("self-test ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["features", "inventory"])
    ap.add_argument("--ids")
    ap.add_argument("--out", default=str(OCR / "adleaf_features.jsonl.gz"),
                    help="features: where to write (gitignored by default)")
    ap.add_argument("--features", default=str(OCR / "adleaf_features.jsonl.gz"),
                    help="inventory: the features file to read")
    ap.add_argument("--write", action="store_true", help="inventory: write sidecar blocks")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "features":
        return features(args)
    if args.cmd == "inventory":
        return inventory(args)
    ap.error("a command is required")
    return 2


if __name__ == "__main__":
    sys.exit(main())
