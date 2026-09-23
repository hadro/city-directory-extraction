#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Survey Phase 2 -- free derivation. No agents, no network: everything here reads the Phase 1
word dumps (data/survey_ocr/, survey_harvest.py) and writes blocks into the committed sidecars.
See docs/SURVEY_PLAN.md "Phase 2".

    python3 data_prep/survey_derive.py bounds              # listing bounds + section inventory
    python3 data_prep/survey_derive.py bounds --ids 1856BPL
    python3 data_prep/survey_derive.py report              # what the sidecars now say
    python3 data_prep/survey_derive.py --self-test

`bounds` -> sidecar `listing`
-----------------------------
detect_listing_bounds.detect() over the word dump, which is the hOCR path exactly (verified
identical on 1906BPL, 1856BPL and micro_IABROOKLYN_0013). The volume is split into ascending
alphabets; the largest is the listing and every alphabet is recorded under `sections`.

The same detector is also run over the FILTERED lines (`_lines.jsonl.gz`) as a cross-check, and a
disagreement of more than 2 leaves at either edge is flagged. The dump is primary because, on
every disagreement opened by eye on 2026-09-22 (1897BPL, micro_IABROOKLYN_0037 and _0042,
trowsgeneraldire19142trow), it was the closer one: the filters drop lines, and on a thin or
ad-banded page a handful of drops moves the modal letter.

Flags, each a reason to distrust the bounds rather than a verdict:

    no-structure        no alphabet found at all
    sparse              < 20% of the listing's span votes. Nine volumes, a clean break in the
                        distribution (next is 0.26). Eight are ABBYY-8 1900s Trow/Brooklyn, where
                        a dash ditto leads most lines and abstains.
    edge-disagreement   dump and filtered lines differ by > 2 leaves at an edge
    multi-section       more than one alphabet -- a second directory, or a supplement
    partial-alphabet    the listing starts after B or ends before W: usually a PART of a
                        multi-volume set, which is right, but check against the title page

The bounds are LEAVES. Printed start_page/end_page are a separate step, because the leaf->page
join is its own evidence problem (survey_pagenumbers.py, and the bottom-margin reader).
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from detect_listing_bounds import (FIRST_WORD_RE, detect, leaf_letters_from_dump,  # noqa: E402
                                   leaf_letters_from_jsonl)
from ia_volume_to_jsonl import words_to_lines  # noqa: E402
from survey_frontmatter import page_image  # noqa: E402
from survey_harvest import OUT, git_rev, load_volumes  # noqa: E402

MIN_CHARS, MIN_LINES = 400, 5          # detect_listing_bounds' CLI defaults
SPARSE = 0.20
EDGE_TOL = 2


def edge_quote(dump_path: Path, leaf: int, letter: str, last: bool) -> str | None:
    """The first (or last) line on `leaf` whose sort key is `letter`: what a reader opening the
    cited image should see at the top (or foot) of the listing."""
    with gzip.open(dump_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["leaf"] != leaf:
                continue
            # the sort key uppercases what it reads, so "arrangement." votes A (1856BPL leaf 65's
            # legend); a surname is capitalised, so the quote insists on it
            hits = [t for _b, t in words_to_lines(rec["lines"])
                    if (m := FIRST_WORD_RE.match(t.strip())) and m.group(1) == letter]
            return (hits[-1] if last else hits[0])[:120] if hits else None
    return None


def bounds(v: dict) -> dict:
    ident = v["id"]
    words = OUT / f"{ident}_words.jsonl.gz"
    lines = OUT / f"{ident}_lines.jsonl.gz"
    n_leaves = v["doc"]["harvest"]["dump"]["leaves"]
    res, _bm, _kept = detect(leaf_letters_from_dump(words, MIN_CHARS, MIN_LINES), n_leaves,
                             "dump", params={"min_chars": MIN_CHARS, "min_lines": MIN_LINES})
    out = {"method": "letter-votes", "source": "dump", "derived": _dt.date.today().isoformat(),
           "code_at": git_rev()}
    if res is None:
        return {**out, "flags": ["no-structure"]}
    x, _bm, _kept = detect(leaf_letters_from_jsonl(lines, MIN_LINES), n_leaves, "lines")

    s, e = res["start_leaf"], res["end_leaf"]
    main = next(sec for sec in res["sections"] if sec["is_listing"])
    density = main["voting_leaves"] / (e - s + 1)
    flags = []
    if density < SPARSE:
        flags.append("sparse")
    if x is None or abs(x["start_leaf"] - s) > EDGE_TOL or abs(x["end_leaf"] - e) > EDGE_TOL:
        flags.append("edge-disagreement")
    if len(res["sections"]) > 1:
        flags.append("multi-section")
    if main["first_letter"] > "B" or main["last_letter"] < "W":
        flags.append("partial-alphabet")

    def cite(leaf, letter, last):
        return {"leaf": leaf, "image": page_image(ident, leaf),
                "quote": edge_quote(words, leaf, letter, last)}

    return {
        **out,
        "start_leaf": s, "end_leaf": e,
        "first_letter": main["first_letter"], "last_letter": main["last_letter"],
        "letters_present": "".join(res["letters_present"]),
        "missing_letters": "".join(res["missing_letters"]),
        "voting_density": round(density, 3),
        "flags": flags,
        "start": cite(s, main["first_letter"], False),
        "end": cite(e, main["last_letter"], True),
        "sections": res["sections"],
        "gaps": res["gaps"],
        "letter_blocks": {L: [b["start_leaf"], b["end_leaf"], b["leaves"]]
                          for L, b in sorted(res["blocks"].items())},
        "skipped_votes": len(res["skipped_votes"]),
        "cross_check": ({"source": "lines", "start_leaf": x["start_leaf"],
                         "end_leaf": x["end_leaf"]} if x else {"source": "lines", "none": True}),
        "params": res["params"],
    }


def save(v: dict, key: str, block: dict):
    doc = json.loads(v["path"].read_text(encoding="utf-8"))   # re-read: never clobber others
    doc[key] = block
    v["path"].write_text(json.dumps(doc, indent=1), encoding="utf-8")
    v["doc"] = doc


def report(vols: list) -> int:
    got = [(v["id"], v["doc"].get("listing")) for v in vols]
    have = [(i, b) for i, b in got if b]
    print(f"{len(have)}/{len(vols)} volumes have a `listing` block")
    flags = collections.Counter(f for _, b in have for f in b.get("flags", []))
    clean = [i for i, b in have if not b.get("flags") and "start_leaf" in b]
    print(f"  clean (no flags): {len(clean)}")
    for f, n in flags.most_common():
        print(f"  {f:18} {n}")
    return 0


def _self_test() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    p = tmp / "x_words.jsonl.gz"
    with gzip.open(p, "wt") as f:
        f.write(json.dumps({"leaf": 7, "page_size": None, "chars": 900, "lines": [
            [[0, 0, 9, 9, 90, "ABE—ACK"]],
            [[0, 5, 9, 9, 90, "arrangement."]],
            [[0, 10, 9, 19, 90, "Abbott"], [10, 10, 19, 19, 90, "John"]],
            [[0, 20, 9, 29, 90, "Ackerman"], [10, 20, 19, 29, 90, "Ann"]]]}) + "\n")
    assert edge_quote(p, 7, "A", False) == "Abbott John", "the first entry, not the running head"
    assert edge_quote(p, 7, "A", True) == "Ackerman Ann"
    assert edge_quote(p, 8, "A", False) is None
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", nargs="?", choices=["bounds", "report"])
    ap.add_argument("--ids", default=None, help="comma list of IA identifiers (default: all)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if not args.step:
        ap.error("a step is required: bounds | report")

    vols = [v for v in load_volumes()
            if (v["doc"].get("harvest") or {}).get("status") == "ok"]
    if args.ids:
        want = set(args.ids.split(","))
        vols = [v for v in vols if v["id"] in want]
    if args.step == "report":
        return report(vols)

    for i, v in enumerate(vols, 1):
        b = bounds(v)
        save(v, "listing", b)
        print(f"[{i}/{len(vols)}] {v['id']:40} "
              f"{b.get('start_leaf', '-')}..{b.get('end_leaf', '-')} "
              f"{b.get('first_letter', '')}-{b.get('last_letter', '')} "
              f"{','.join(b['flags'])}", file=sys.stderr)
    return report(vols)


if __name__ == "__main__":
    raise SystemExit(main())
