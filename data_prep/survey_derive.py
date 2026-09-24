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
    python3 data_prep/survey_derive.py pages               # leaf -> printed page; start/end_page
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
    small-listing       the listing spans < 10% of the volume's leaves. Every volume under that
                        line is stamped not-residential except trowsgeneraldire1853trow, whose
                        own title page reads WILSON'S BUSINESS DIRECTORY -- the same catalog
                        error as the 1913 Trow set. The largest of its scattered alphabets was
                        27 leaves of 948, and its page claims had been graded high.

The bounds are LEAVES. Printed start_page/end_page are a separate step, because the leaf->page
join is its own evidence problem (survey_pagenumbers.py, and the bottom-margin reader).

`pages` -> sidecar `folios`, and `book_says.start_page` / `end_page`
--------------------------------------------------------------------
survey_folios.fit() over the dump: the page's own margins, fitted to a piecewise-constant
sequence. Calibrated 2026-09-22 against IA's READ numbers (confidence >= 90) on the 86 tier-A/B
volumes: 99.5% agreement (18,209/18,301 leaves) outside 1904BPL, where IA -- not this -- is wrong
on 381 leaves (it sets page = leaf; the margins print otherwise).

The claims take the printed page at the listing's first and last leaf, cited like every other
claim (leaf, canvas, IIIF image, the folio token verbatim). Confidence is the conjunction of the
two things a start_page depends on:

    high     the leaf's own margin prints the number, IA's read number (if any) agrees, the
             listing bounds carry no sparse / edge-disagreement flag, and the sequence it
             belongs to is read on >= SEG_MIN_READ leaves
    medium   printed on the leaf, but the bounds are flagged, IA disagrees, or the sequence is
             short
    low      `inferred` -- the leaf prints no folio and the number comes from the sequence --
             or a `doubts` check says the number cannot be the listing's page (a sequence
             break, or an end page below the listing's own leaf count). Never CSV-grade, the
             rule survey_pagenumbers.py enforces on IA's interpolations.

A listing edge outside every fitted segment gets no claim at all: its opening page often prints
no folio (hearnesbrooklync1852unse leaf 27), and extrapolating one is the error that was
retracted from the CSV on 2026-09-21.
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

from detect_listing_bounds import (FIRST_WORD_RE, detect, extend_edges,  # noqa: E402
                                   leaf_letters_from_dump, leaf_letters_from_jsonl)
from ia_volume_to_jsonl import words_to_lines  # noqa: E402
from survey_frontmatter import page_image  # noqa: E402
from survey_folios import compare, fit, folio_token, ia_read, load as load_folios  # noqa: E402
from survey_folios import segments as folio_segments  # noqa: E402
from survey_harvest import OUT, git_rev, load_volumes  # noqa: E402

MIN_CHARS, MIN_LINES = 400, 5          # detect_listing_bounds' CLI defaults
SPARSE = 0.20
EDGE_TOL = 2
SMALL_LISTING = 0.10    # a listing spanning less of the volume than this is not its directory
SEG_MIN_READ = 10       # a page claim is `high` only from a sequence read on this many leaves


EDGE_WINDOW = 40         # leaves either side of each voted edge that extension may reach


def edge_pages(dump_path: Path, start: int, end: int) -> dict:
    """{leaf: [line texts]} for text leaves within EDGE_WINDOW of either edge."""
    out = {}
    with gzip.open(dump_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            leaf = rec["leaf"]
            if rec["chars"] >= 50 and (abs(leaf - start) <= EDGE_WINDOW
                                       or abs(leaf - end) <= EDGE_WINDOW):
                out[leaf] = [t for _b, t in words_to_lines(rec["lines"])]
    return out


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

    main = next(sec for sec in res["sections"] if sec["is_listing"])
    # Pull each edge out across caption / tail pages the vote cannot see (detect_listing_bounds
    # .extend_edges, measured on 292 image-read edges). The voted bounds are kept alongside.
    voted = (res["start_leaf"], res["end_leaf"])
    s, e, add_s, add_e = extend_edges(voted[0], voted[1], main["first_letter"],
                                      main["last_letter"],
                                      edge_pages(words, voted[0], voted[1]))
    res["start_leaf"], res["end_leaf"] = s, e
    density = main["voting_leaves"] / (voted[1] - voted[0] + 1)
    flags = []
    if density < SPARSE:
        flags.append("sparse")
    if (x is None or abs(x["start_leaf"] - voted[0]) > EDGE_TOL
            or abs(x["end_leaf"] - voted[1]) > EDGE_TOL):
        flags.append("edge-disagreement")
    if len(res["sections"]) > 1:
        flags.append("multi-section")
    if main["first_letter"] > "B" or main["last_letter"] < "W":
        flags.append("partial-alphabet")
    if (e - s + 1) / n_leaves < SMALL_LISTING:
        flags.append("small-listing")

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
        "voted_bounds": list(voted),
        "extended": {"start": add_s, "end": add_e},
        "cross_check": ({"source": "lines", "start_leaf": x["start_leaf"],
                         "end_leaf": x["end_leaf"]} if x else {"source": "lines", "none": True}),
        "params": res["params"],
    }


def leaf_record(dump_path: Path, leaf: int):
    with gzip.open(dump_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["leaf"] == leaf:
                return rec
    return None


def pages(v: dict) -> tuple[dict, dict]:
    """-> (folios block, {"start_page": claim, "end_page": claim}) for one volume."""
    ident = v["id"]
    words = OUT / f"{ident}_words.jsonl.gz"
    leaves, cands = load_folios(ident)
    f = fit(leaves, cands)
    ia = ia_read(ident)
    cmp_ = compare(f, ia)
    listing = v["doc"].get("listing") or {}
    block = {"method": "margin-fit", "derived": _dt.date.today().isoformat(),
             "code_at": git_rev(),
             "content_leaves": len(leaves), "fitted_leaves": len(f),
             "read_leaves": sum(a == "read" for _p, a in f.values()),
             "segments": folio_segments(f), "ia_comparison": cmp_, "flags": []}
    if cmp_["both"] >= 20 and cmp_["agree_rate"] is not None and cmp_["agree_rate"] < 0.9:
        block["flags"].append("ia-disagrees")
    if not f:
        block["flags"].append("no-folios")

    claims = {}
    if "start_leaf" not in listing:
        return block, claims
    weak_bounds = {"sparse", "edge-disagreement", "small-listing"} & set(listing.get("flags", []))
    if v["doc"].get("survey_status") == "not-residential":
        weak_bounds.add("not-residential")
    lo, hi = listing["start_leaf"], listing["end_leaf"]
    span_pages = sum(lo <= leaf <= hi for leaf in leaves)
    segs = [sg for sg in block["segments"] if sg["last_leaf"] >= lo and sg["first_leaf"] <= hi]

    def doubts(key, leaf, page):
        """Reasons a margin read at a listing edge is not the listing's page. Each was a claim
        graded `high` on the first run: the OCR drops or mangles a folio's LEADING digit, and
        a few truncated folios in a row fit a sequence of their own -- brooklynnewyorkc1912broo
        reads 120..153 where its main sequence runs on to 1153, trowsgeneraldir1911p1trow ends
        on `003` (603), trowsgeneraldir1912p2trow on `6`."""
        seg = next(sg for sg in segs if sg["first_leaf"] <= leaf <= sg["last_leaf"])
        why = []
        if seg["read"] < SEG_MIN_READ:
            why.append(f"sequence read on only {seg['read']} leaves")
        if any(sg["last_leaf"] < seg["first_leaf"] and sg["last_page"] > seg["first_page"]
               and sg["read"] >= SEG_MIN_READ for sg in segs):
            why.append("sequence-break: an earlier sequence in this listing ran higher")
        if key == "end_page" and page < 0.9 * span_pages:
            why.append(f"page {page} is below the listing's {span_pages} text leaves")
        return why

    for key, leaf in (("start_page", lo), ("end_page", hi)):
        if leaf not in f:
            continue
        page, att = f[leaf]
        ia_page = ia.get(leaf)
        why = doubts(key, leaf, page)
        if att == "inferred" or any(w.startswith(("sequence-break", "page ")) for w in why):
            level = "low"
        elif weak_bounds or why or (ia_page is not None and ia_page != page):
            level = "medium"
        else:
            level = "high"
        token, zone = folio_token(leaf_record(words, leaf), page) if att == "read" else (None, None)
        claims[key] = {
            "value": page, "leaf": leaf,
            "canvas": f"https://iiif.archive.org/iiif/{ident}${leaf}/canvas",
            "image": page_image(ident, leaf),
            "evidence_type": "folio",
            "quote": (f"{token!r} in the {zone} margin" if token
                      else f"no folio printed on leaf {leaf}; page {page} INFERRED from the "
                           f"sequence of folios around it"),
            "method": "hocr-geometry",
            "confidence": level,
            "attestation": att,
            "ia_page": ia_page,
            "page_offset": leaf - page,
            "listing_flags": sorted(weak_bounds),
            "doubts": why,
        }
    return block, claims


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
    fol = [v["doc"].get("folios") for v in vols if v["doc"].get("folios")]
    if fol:
        print(f"\n{len(fol)} volumes have a `folios` block")
        for f, n in collections.Counter(x for b in fol for x in b["flags"]).most_common():
            print(f"  {f:18} {n}")
        for key in ("start_page", "end_page"):
            c = collections.Counter((v["doc"].get("book_says", {}).get(key) or {}).get("confidence")
                                    for v in vols)
            print(f"  {key:12} " + ", ".join(f"{k or 'none'} {n}" for k, n in c.most_common()))
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
    ap.add_argument("step", nargs="?", choices=["bounds", "pages", "report"])
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

    if args.step == "pages":
        for i, v in enumerate(vols, 1):
            block, claims = pages(v)
            doc = json.loads(v["path"].read_text(encoding="utf-8"))
            doc["folios"] = block
            book = doc.setdefault("book_says", {})
            for key in ("start_page", "end_page"):
                # this step owns these two claims and nothing else in book_says -- and not even
                # these once someone has LOOKED: an agent-read page claim (survey_readpackets.py
                # --record-pages) outranks the fit, exactly as a read outranks an hOCR regex in
                # survey_frontmatter.merge_book()
                # ...but a read speaks only for the leaf it read. One that CONFIRMED an edge
                # still wins; one that said "not the edge", or that sits on a leaf the bounds
                # have since moved away from, gives way, and is kept under superseded_read.
                prior = book.get(key) or {}
                edge_leaf = (doc.get("listing") or {}).get(
                    "start_leaf" if key == "start_page" else "end_leaf")
                if prior.get("method") == "agent-read":
                    if prior.get("edge_confirmed") or prior.get("leaf") == edge_leaf:
                        continue
                    if key in claims:
                        claims[key]["superseded_read"] = prior
                    else:
                        # a stale "not the edge" read with nothing to replace it: set it aside
                        # rather than leave it standing as the volume's answer
                        book.setdefault("_superseded_page_reads", []).append({key: prior})
                        del book[key]
                        continue
                if key in claims:
                    book[key] = claims[key]
                elif (book.get(key) or {}).get("method") == "hocr-geometry":
                    del book[key]
            v["path"].write_text(json.dumps(doc, indent=1), encoding="utf-8")
            v["doc"] = doc
            sp, ep = claims.get("start_page"), claims.get("end_page")
            print(f"[{i}/{len(vols)}] {v['id']:40} fitted {block['fitted_leaves']:5} "
                  f"start {sp and (sp['value'], sp['confidence'])} "
                  f"end {ep and (ep['value'], ep['confidence'])} {','.join(block['flags'])}",
                  file=sys.stderr)
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
