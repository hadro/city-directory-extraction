#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""One-time migration: re-point every survey citation's `image` from `page/nNN` to IIIF.

    python3 data_prep/survey_fix_image_urls.py            # report, write nothing
    python3 data_prep/survey_fix_image_urls.py --write    # rewrite the sidecars
    python3 data_prep/survey_fix_image_urls.py --verify --ident <id> --leaf <n>   # fetch both
    python3 data_prep/survey_fix_image_urls.py --self-test

WHY. Every claim carries both a `canvas` (IIIF, leaf-indexed) and an `image`. The image was built
as `archive.org/download/<id>/page/n<leaf>_w1400.jpg` on the strength of one visual check on
1906BPL leaf 1. The check was real; the generalisation was not.

**`page/nNN` is a FOURTH numbering and its alignment with the leaf index is per-volume.** Measured
2026-09-21 by opening pages in both schemes:

    1906BPL       leaf  9   page/n9  == IIIF $9    both the ABBREVIATIONS page, printing 21
    hearne 1852   leaf 27   page/n27 is the WRONG PAGE -- prints 18, and is not the legend
                            page/n26 IS the legend; IIIF $27 IS the legend
    micro_IABR_12 leaf  1   IIIF $1 == the target card ("Printed by Lewis Nichols, 112 Bridge-st")

Three volumes across three collections (BPL, Columbia, microfiche); IIIF correct on all three,
`page/nNN` correct on one of three. IIIF also uses the same integer as the hOCR pageindex, which
is the join docs/SURVEY_PLAN.md documents and verified on 1906BPL against seven margin reads. So
IIIF is not merely the safer choice, it is the one the rest of the survey is already indexed by.

WHY IT MATTERED. The `spooner` cluster -- 9 rows whose CSV publisher contradicts a target card --
is adjudicated by opening the cited image. Nine target cards cited one leaf off would have been
judged against the wrong page, which is the same class of error that put a LEAF in the printed-page
column `key_page` to begin with.

This migration is idempotent and lossless: it only rewrites an `image` whose value matches the old
`page/nNN` pattern for that claim's own leaf, and it derives the replacement from the leaf, not
from the old string. A claim without a leaf is not touched.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIDECAR = HERE / "survey"
IMG_WIDTH = 1400
UA = {"User-Agent": "Mozilla/5.0 (research; city-directory corpus survey; +josh)"}

OLD = re.compile(r"^https://archive\.org/download/(?P<ident>[^/]+)/page/n(?P<leaf>\d+)_w\d+\.jpg$"
                 r"|^https://iiif\.archive\.org/iiif/(?P<i2>[^/$]+)\$(?P<l2>\d+)/full/\d+,/0/default\.jpg$")

sys.path.insert(0, str(HERE))
# The canonical builder lives with the citation code that emits it, so the migration and the
# producers cannot drift apart.
from survey_frontmatter import page_image as iiif_image  # noqa: E402  (same-dir sibling)


def fix_claim(ident: str, claim: dict) -> bool:
    """Rewrite one claim's `image` in place. -> True if it changed.

    Conservative on purpose: the claim must carry a leaf, the existing URL must be the old scheme,
    and that URL's own leaf must match the claim's. Anything else is left alone and counted, so a
    surprise shows up in the report rather than being silently rewritten.
    """
    leaf = claim.get("leaf")
    img = claim.get("image")
    if leaf is None or not isinstance(img, str):
        return False
    m = OLD.match(img)
    if not m:
        return False
    got = m.group("leaf") or m.group("l2")
    if int(got) != int(leaf):
        return False
    claim["image"] = iiif_image(ident, int(leaf))
    return True


def walk_claims(doc: dict):
    """Yield every citation dict in a sidecar. `book_says` values are claims; `year_attestations`
    is a list of supporting reads that carry a leaf but no image, and is yielded for completeness
    so a future image field there is not missed."""
    book = doc.get("book_says") or {}
    for value in book.values():
        if isinstance(value, dict):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item


def run(write: bool):
    counts = Counter()
    touched = 0
    for path in sorted(SIDECAR.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                                   # noqa: BLE001 - report, don't die
            counts["unreadable sidecar"] += 1
            continue
        ident = doc.get("id")
        changed = False
        for claim in walk_claims(doc):
            img = claim.get("image")
            if not isinstance(img, str):
                continue
            counts["citations with an image"] += 1
            if fix_claim(ident, claim):
                counts["rewritten to IIIF"] += 1
                changed = True
            elif img.startswith("https://iiif.archive.org/"):
                counts["already IIIF"] += 1
            else:
                counts["LEFT ALONE (unexpected shape)"] += 1
        if changed:
            touched += 1
            if write:
                path.write_text(json.dumps(doc, indent=1), encoding="utf-8")

    for k, n in counts.most_common():
        print(f"  {n:5d}  {k}")
    print(f"\nsidecars touched: {touched}")
    print(f"wrote {touched} sidecars" if write else "\n(dry run -- nothing written; pass --write)")
    return 0


def verify(ident: str, leaf: int):
    """Fetch both schemes for one leaf so a human can compare them. Sizes differ even when the
    page is the same (different encoders), so this reports bytes and leaves the looking to you."""
    urls = [("IIIF      ", iiif_image(ident, leaf)),
            ("page/nNN  ", f"https://archive.org/download/{ident}/page/n{leaf}_w{IMG_WIDTH}.jpg"),
            ("page/nNN-1", f"https://archive.org/download/{ident}/page/n{leaf - 1}_w{IMG_WIDTH}.jpg")]
    for label, url in urls:
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            print(f"  {label}  {len(body):>9,} bytes  {url}")
        except Exception as e:                              # noqa: BLE001
            print(f"  {label}  FAILED {type(e).__name__}  {url}")
    print("\nOpen them and compare: if IIIF and page/nNN differ, this volume is misaligned.")
    return 0


def self_test():
    assert iiif_image("1906BPL", 9) == \
        "https://iiif.archive.org/iiif/1906BPL$9/full/!1400,1400/0/default.jpg"

    # The normal case: old scheme, leaf agrees, rewritten from the LEAF not the old string.
    c = {"leaf": 27, "image": "https://archive.org/download/hearne/page/n27_w1400.jpg"}
    assert fix_claim("hearne", c)
    assert c["image"] == "https://iiif.archive.org/iiif/hearne$27/full/!1400,1400/0/default.jpg"

    # ... and the earlier IIIF form migrates too: `full/1400,` 403s on a scan narrower than 1400.
    old_iiif = {"leaf": 9,
                "image": "https://iiif.archive.org/iiif/1906BPL$9/full/1400,/0/default.jpg"}
    assert fix_claim("1906BPL", old_iiif)
    assert old_iiif["image"].endswith("/full/!1400,1400/0/default.jpg")
    assert not fix_claim("1906BPL", old_iiif), "still idempotent"

    # Idempotent: a second pass leaves an already-migrated claim alone.
    assert not fix_claim("hearne", c), "migration must be idempotent"

    # A claim whose URL names a DIFFERENT leaf than the claim is not silently rewritten -- that
    # disagreement is a bug worth seeing, not papering over.
    odd = {"leaf": 27, "image": "https://archive.org/download/hearne/page/n26_w1400.jpg"}
    assert not fix_claim("hearne", odd)
    assert odd["image"].endswith("n26_w1400.jpg"), "left exactly as found"

    # No leaf is not a claim (the plan's citation rule); nothing to point at.
    assert not fix_claim("x", {"image": "https://archive.org/download/x/page/n1_w1400.jpg"})
    assert not fix_claim("x", {"leaf": 1})

    # walk_claims must reach list-valued entries too (year_attestations).
    doc = {"book_says": {"year": {"leaf": 1, "image": "i"},
                         "year_attestations": [{"leaf": 2, "image": "j"}]}}
    assert len(list(walk_claims(doc))) == 2

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify", action="store_true", help="fetch both schemes for one leaf")
    ap.add_argument("--ident")
    ap.add_argument("--leaf", type=int)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.verify:
        if not args.ident or args.leaf is None:
            ap.error("--verify needs --ident and --leaf")
        return verify(args.ident, args.leaf)
    return run(args.write)


if __name__ == "__main__":
    raise SystemExit(main())
