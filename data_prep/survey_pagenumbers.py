#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Leaf -> printed page, from IA's own `_page_numbers.json`. Phase 2's first prerequisite.

`survey_census.py`'s docstring has named this file since 2026-09-12; it did not exist until
2026-09-20, which made the tier-C/D fallback read as built when it was not. This is the tier-A/B
half: the free, direct lookup. The bottom-margin regression for C/D is still unwritten.

    python3 data_prep/survey_pagenumbers.py --measure   # fetch, cache, report; writes nothing
    python3 data_prep/survey_pagenumbers.py --write     # emit key_page claims into the sidecars
    python3 data_prep/survey_pagenumbers.py --self-test # offline

Its first job is `key_page`. `apply_survey.py` refuses to write that column from a legend LEAF,
because the column holds a printed PAGE; this is the converter that makes the claim writable, and
the claim it emits carries `method: ia-page-numbers` so the two units never meet again.

THE JOIN, AND THE OFF-BY-ONE (docs/SURVEY_PLAN.md, verified on 1906BPL against seven margin reads)

    hOCR pageindex leaf L (0-based) == IIIF canvas index L == entry with leafNum == L

**`leafNum - 1` looks right and is wrong by exactly one printed page.** 1906BPL has 1254 hOCR
leaves and 1253 entries because leaf 0 has no entry, and that gap is the whole trap. This module
indexes by `leafNum` and never by position in the array.

WHAT THE PROBE FOUND, AND WHY THE YIELD IS NOT 40

Of the 40 tier-A/B volumes that have a `legend_leaf` and an empty `key_page`, the naive assumption
is that each leaf carries a printed number. It does not. Front matter is frequently unnumbered:

    1906BPL              leaf  9 -> '21'   conf 100     direct hit
    1864BPL              leaf  8 -> '1'    conf 0       value present, IA has no confidence in it
    micro_IABROOKLYN_0002 leaf  5 -> ''                 leaves 3-7 all blank; numbering starts at 8
    1879BPL              leaf 27 -> ''                  leaves 25-28 blank; numbering starts at 29

**An unnumbered leaf is not a missing value; it is a page that has no printed number**, and the
survey's founding principle is that a field is confirmed only by something printed in the volume.
Extrapolating (1879BPL leaf 29 = page 3, so leaf 27 "=" page 1) would manufacture a number that is
not on the page, in the region where the offset is least stable -- front matter routinely carries
its own roman sequence, or restarts at the listing head. So a blank leaf yields NO claim and is
reported as `unnumbered`, which is the true answer and is useful: it tells Phase 3 that this
volume's key page must be cited by leaf, not by page.

CONFIDENCE, AND THE ONE THAT IS NOT A CONFIDENCE AT ALL

IA scores each leaf 0-100, and `1864BPL` leaf 8 carries a value at confidence **0** -- not the
same kind of fact as 1906BPL's 100. Claims inherit it: >= 90 and monotone -> high, >= 50 ->
medium, else low.

**`confidence: null` is not a low score, it is a different thing: IA INTERPOLATED that number.**
Verified on `hearnesbrooklync1852unse`, whose leaves read 24->'14' and 25->'15' at confidence 100,
then 26/27/28 -> '16'/'17'/'18' at null, then 29->'19' and 30->'20' at 100 again. The nulls are
arithmetic between confident anchors. Leaf 27 is the directory's opening page -- caption title,
the NOTE about `*`, then the A listings -- and it **prints no folio at all** (the `2` at its foot
is a printer's signature mark). IA asserts 17 for a page that prints nothing.

So an interpolated number is marked `attestation: interpolated` and is **never CSV-grade**,
however coherent its volume. It is weaker evidence than a read number, not neutral, and the
survey's founding rule is that a field is confirmed only by something printed in the volume. A
volume whose legend leaf is interpolated cites its key page by LEAF.

An earlier cut of this module read null as "unscored, so fall back to the volume's coherence" and
graded it `medium`. That put 8 interpolated folios into `master_directories.csv`; they were
retracted by `apply_survey.py --retract`.

⚠️ SEPARATE, STILL OPEN: **the `page/nNN` image-URL index is not globally aligned with `leafNum`.**
1906BPL's `n9` is leafNum 9 (verified by eye: its ABBREVIATIONS page prints 21), but Hearne's
`n27` is leafNum 28. SURVEY_PLAN.md asserts one global join verified on a single volume; the
alignment is per-volume. Every `image` URL in every sidecar is therefore suspect by one leaf.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MASTER = HERE / "master_directories.csv"
SIDECAR = HERE / "survey"
CACHE = REPO / "data" / "survey_pagenumbers"

UA = {"User-Agent": "Mozilla/5.0 (research; city-directory corpus survey; +josh)"}
META = "https://archive.org/metadata/{ident}"
PN_SUFFIX = "_page_numbers.json"

sys.path.insert(0, str(HERE))
# One definition of the citable image URL, for the reason recorded in its docstring: the
# `page/nNN` scheme this module used to build is a separate numbering whose alignment with the
# leaf index is per-volume.
from survey_frontmatter import page_image  # noqa: E402  (same-dir sibling)


def _get(url: str, timeout: int = 90, retries: int = 3) -> bytes:
    """Same retry shape as survey_census: IA returns transient 500s, and 4 of 184 volumes failed
    one sweep and all four succeeded on a plain retry. Without this, live volumes land in the
    failure register as dead."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                              # noqa: BLE001 - network, surfaced below
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def fetch_pages(ident: str, refresh: bool = False) -> dict:
    """-> the raw `_page_numbers.json` for one item. Cached; a cache hit costs no network.

    The census fetched this file and kept only counts, discarding every per-leaf number -- which
    is why this refetches rather than reading `data/survey_census/`.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{ident}.json"
    if cached.exists() and not refresh:
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except Exception:                                   # noqa: BLE001 - corrupt, refetch
            pass
    try:
        m = json.loads(_get(META.format(ident=ident)))
        names = {f.get("name") for f in m.get("files", [])}
        pn = f"{ident}{PN_SUFFIX}"
        if pn not in names:
            doc = {"id": ident, "error": "no _page_numbers.json"}
        else:
            doc = json.loads(_get(f"https://{m['server']}{m['dir']}/{pn}"))
            doc["id"] = ident
    except Exception as e:                                  # noqa: BLE001 - recorded, not raised
        doc = {"id": ident, "error": f"{type(e).__name__}: {e}"[:200]}
    cached.write_text(json.dumps(doc), encoding="utf-8")
    return doc


def leaf_map(doc: dict) -> dict:
    """-> {leafNum: entry} for entries carrying a non-empty pageNumber.

    Indexed by the entry's OWN `leafNum`, never by array position: leaf 0 has no entry, so
    position would be off by one for the whole volume.
    """
    out = {}
    for p in doc.get("pages") or []:
        leaf = p.get("leafNum")
        if leaf is None:
            continue
        if str(p.get("pageNumber") or "").strip():
            out[int(leaf)] = p
    return out


def monotone_breaks(lm: dict) -> int:
    """How many times the printed number goes BACKWARDS as the leaf advances.

    Tier B is defined as "verify monotone", and this is the verification. A handful of breaks is
    normal (a volume with several alphabets restarts its numbering); a flood means the join is
    wrong and no claim from that volume should be trusted.
    """
    breaks = 0
    prev = None
    for leaf in sorted(lm):
        try:
            n = int(str(lm[leaf].get("pageNumber")).strip())
        except (TypeError, ValueError):
            continue
        if prev is not None and n < prev:
            breaks += 1
        prev = n
    return breaks


def claim_for(ident: str, leaf: int, doc: dict) -> tuple:
    """-> (outcome, claim|None). Outcomes: hit / unnumbered / no-data / non-monotone."""
    if doc.get("error"):
        return "no-data", None
    lm = leaf_map(doc)
    if not lm:
        return "no-data", None

    filled = len(lm)
    breaks = monotone_breaks(lm)
    # A quarter of the numbered leaves going backwards is not "several alphabets", it is a broken
    # join. Refuse the whole volume rather than emit a plausible wrong page.
    if filled and breaks / filled > 0.25:
        return "non-monotone", None

    entry = lm.get(int(leaf))
    if entry is None:
        return "unnumbered", None

    try:
        page = int(str(entry.get("pageNumber")).strip())
    except (TypeError, ValueError):
        return "unnumbered", None

    # `confidence: None` means IA INTERPOLATED this number, not that it declined to score a
    # number it read. Proven on hearnesbrooklync1852unse, whose leaves run
    #
    #     24 -> '14' conf 100   25 -> '15' conf 100   <- read
    #     26 -> '16' conf None  27 -> '17' conf None  28 -> '18' conf None   <- filled in
    #     29 -> '19' conf 100   30 -> '20' conf 100   <- read
    #
    # -- arithmetic between confident anchors. Leaf 27 is the directory's opening page: caption
    # title, the NOTE, then the A listings, and it PRINTS NO FOLIO AT ALL (the `2` at its foot is
    # a printer's signature mark). IA asserts 17 for a page that prints nothing.
    #
    # An earlier cut of this read `None` as "unscored, so fall back to the volume's coherence"
    # and graded it `medium`, which is CSV-grade; that put 8 interpolated numbers into the CSV.
    # An interpolated folio is WEAKER evidence than a read one, not neutral, and the survey's
    # founding rule is that a field is confirmed only by something printed in the volume. So it
    # is recorded, marked, and never CSV-grade.
    #
    # The other half of the rule is real: breaks must be a RATE. These volumes hold several
    # alphabets and legitimately restart their numbering, so 1906BPL shows 11 backward steps in
    # 1,245 numbered leaves (0.9%) at leaf confidence 100 -- verified by eye as a genuine printed
    # `21` at the foot of its ABBREVIATIONS page. Gating `high` on zero breaks downgraded every
    # dense volume in the corpus.
    rate = breaks / filled if filled else 1.0
    conf = entry.get("confidence")
    if not isinstance(conf, (int, float)):
        attestation, level = "interpolated", "low"
    elif conf >= 90 and rate <= 0.05:
        attestation, level = "read", "high"
    elif conf >= 50:
        attestation, level = "read", "medium"
    else:
        attestation, level = "read", "low"

    return "hit", {
        "value": page,
        "leaf": int(leaf),
        "canvas": f"https://iiif.archive.org/iiif/{ident}${leaf}/canvas",
        "image": page_image(ident, int(leaf)),
        "evidence_type": "legend",
        "quote": (f"printed page number {page} on leaf {leaf}" if attestation == "read"
                  else f"page {page} INTERPOLATED by IA for leaf {leaf}; not read from the page"),
        "method": "ia-page-numbers",
        "confidence": level,
        "attestation": attestation,
        "ia_leaf_confidence": conf,
        "volume_monotone_breaks": breaks,
        "volume_numbered_leaves": filled,
    }


def candidates():
    """-> [(row, sidecar_path, doc, legend_leaf)] for every volume this can serve."""
    with open(MASTER, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        p = SIDECAR / f"{r['source']}_{r['id']}.json"
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            continue
        legend = (d.get("book_says") or {}).get("legend") or {}
        if legend.get("leaf") is None:
            continue
        if (d.get("page_numbers") or {}).get("tier") not in ("A", "B"):
            continue
        out.append((r, p, d, int(legend["leaf"])))
    return out


def run(write: bool, refresh: bool):
    cands = candidates()
    print(f"tier A/B volumes with a legend leaf: {len(cands)}")
    outcomes = Counter()
    wrote = 0
    detail = []

    for r, path, doc, leaf in cands:
        pages = fetch_pages(r["id"], refresh=refresh)
        outcome, claim = claim_for(r["id"], leaf, pages)
        outcomes[outcome] += 1
        already = (r.get("key_page") or "").strip()
        if outcome == "hit":
            outcomes[f"  confidence {claim['confidence']}"] += 1
            detail.append((r["id"], leaf, claim["value"], claim["confidence"], already))
        if write and claim is not None:
            doc.setdefault("book_says", {})["key_page"] = claim
            # `indent=1`, ASCII-escaped, no trailing newline -- matching survey_census.py and
            # survey_frontmatter.py exactly, so the diff shows the added claim and nothing else.
            path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            wrote += 1

    print("\noutcomes:")
    for k, n in outcomes.most_common():
        print(f"  {n:4d}  {k}")

    if detail:
        print(f"\nconverted ({len(detail)}):")
        for ident, leaf, page, level, already in detail:
            flag = f"   (csv already has key_page={already})" if already else ""
            print(f"  {ident[:34]:34} leaf {leaf:>4} -> printed page {page:>4}  {level}{flag}")

    if write:
        print(f"\nwrote {wrote} key_page claims into sidecars")
        print("now run: python3 data_prep/apply_survey.py --write")
    else:
        print("\n(measure only -- nothing written; pass --write)")
    return 0


def self_test():
    doc = {"pages": [
        {"leafNum": 1, "pageNumber": "", "confidence": None},
        {"leafNum": 9, "pageNumber": "21", "confidence": 100},
        {"leafNum": 10, "pageNumber": "22", "confidence": 95},
        {"leafNum": 11, "pageNumber": "23", "confidence": 40},
    ]}
    lm = leaf_map(doc)
    assert set(lm) == {9, 10, 11}, "blank pageNumbers are not entries"
    assert monotone_breaks(lm) == 0

    # The join is by leafNum, NOT by array position -- leaf 0 has no entry, so position would be
    # off by exactly one printed page for the whole volume.
    o, c = claim_for("1906BPL", 9, doc)
    assert o == "hit" and c["value"] == 21, (o, c)
    assert c["leaf"] == 9 and c["method"] == "ia-page-numbers"
    assert c["confidence"] == "high"

    # A leaf with no printed number yields NO claim. This is the measured common case in front
    # matter (micro_IABROOKLYN_0002 leaf 5, 1879BPL leaf 27) and must never be extrapolated.
    assert claim_for("x", 5, doc) == ("unnumbered", None)

    # IA's own confidence rides through: a value at confidence 0 is not a high-confidence claim.
    low = {"pages": [{"leafNum": 8, "pageNumber": "1", "confidence": 0}]}
    o, c = claim_for("1864BPL", 8, low)
    assert o == "hit" and c["confidence"] == "low", c

    # `None` means IA INTERPOLATED the number. Never CSV-grade, however coherent the volume --
    # hearnesbrooklync1852unse leaf 27 is interpolated '17' on a page that prints no folio at all.
    interp = {"pages": [{"leafNum": i, "pageNumber": str(i), "confidence": None}
                        for i in range(1, 60)]}
    o, c = claim_for("x", 14, interp)
    assert c["attestation"] == "interpolated" and c["confidence"] == "low", c
    assert "INTERPOLATED" in c["quote"], "the quote must not claim the page prints this"

    # breaks are a RATE: 1906BPL is leaf-confidence 100 with 11 backward steps in 1,245 numbered
    # leaves, because the volume holds several alphabets. That is high, not medium.
    dense = {"pages": [{"leafNum": i, "pageNumber": str(i), "confidence": 100}
                       for i in range(1, 200)]
             + [{"leafNum": 200 + i, "pageNumber": str(i), "confidence": 100} for i in range(1, 6)]}
    d = claim_for("x", 9, dense)[1]
    assert d["confidence"] == "high" and d["attestation"] == "read", d
    assert "printed page number" in d["quote"]

    # A badly non-monotone volume is refused whole rather than emitting a plausible wrong page.
    scrambled = {"pages": [{"leafNum": i, "pageNumber": str(100 - i), "confidence": 99}
                           for i in range(1, 21)]}
    assert claim_for("x", 5, scrambled)[0] == "non-monotone"

    # A few restarts are normal (volumes hold several alphabets) and must still convert.
    twoalpha = {"pages": [{"leafNum": i, "pageNumber": str(i), "confidence": 99}
                          for i in range(1, 20)]
                + [{"leafNum": i, "pageNumber": str(i - 19), "confidence": 99}
                   for i in range(20, 40)]}
    assert claim_for("x", 5, twoalpha)[0] == "hit", "one restart is not a broken join"

    assert claim_for("x", 5, {"error": "no _page_numbers.json"}) == ("no-data", None)
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measure", action="store_true", help="fetch and report, write nothing")
    ap.add_argument("--write", action="store_true", help="emit key_page claims into the sidecars")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    return run(args.write, args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
