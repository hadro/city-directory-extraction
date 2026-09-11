#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Phase 0 of docs/PAGE_TYPE_CLASSIFIER.md — turn a volume's hOCR into one document per leaf.

    python3 data_prep/build_leaf_docs.py --ident 1906BPL --out data/1906BPL_leafdocs.jsonl
    python3 data_prep/build_leaf_docs.py --self-test

Each output row is one leaf: its full PRE-FILTER text in hOCR emission order, plus the cheap
per-leaf features a logistic-regression ablation runs on. No model, no network beyond the hOCR
the ingest stage already caches, no images.

WHY PRE-FILTER TEXT, AND THIS IS THE ONE THING THAT IS EASY TO GET SILENTLY WRONG
--------------------------------------------------------------------------------
`ia_volume_to_jsonl.py` drops running heads, banners, big display type and page furniture -- 93,781
of 1906BPL's 292,793 candidate lines. Those are exactly the tokens that say "this leaf is not a
listing". Building leaf documents from the *kept* lines would hide the signal from the classifier
and then report that page type is hard to detect.

So this reads `hocr_lines()` directly and keeps everything, which also gives true emission order
for free. `--lines` is optional and additive: when supplied, the kept-line count per leaf becomes a
feature (`share_kept`), which is the ingest filter's own opinion offered to the model as evidence
rather than imposed on it as a cut.

WHAT THE FEATURES ARE FOR
-------------------------
They are not a proposed classifier. They are the ABLATION the encoder has to beat, and they
deliberately include `modal_letter_share` -- the statistic `detect_listing_bounds.py` already
measured as NOT separating interior ad leaves (genuine listing leaf 13 = 34%, ad leaf 819 = 38%,
the ad page scoring higher). Carrying it lets the writeup state whether reading the leaf's words
adds anything over counting its first letters, instead of assuming it does.

`first_letter` is imported from `alpha_run_filter.py` rather than reimplemented, so the ditto
abstention rule (a dittoed entry must not vote its GIVEN name -- 1,724 lines of 1906BPL were cut
by getting this wrong) is the same code that stages 2 and 3 use.
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alpha_run_filter import first_letter                       # noqa: E402
from ia_volume_to_jsonl import Item, hocr_lines, page_dims      # noqa: E402

CACHE = Path(__file__).resolve().parent.parent / "data" / "ia_cache"

# A line longer than this reads as prose or ad copy, not as a directory entry. Entries in this
# corpus are short: 1906BPL's median kept line is well under half of it.
PROSE_CHARS = 60


def _share(pred, seq):
    return round(sum(1 for x in seq if pred(x)) / len(seq), 4) if seq else 0.0


def leaf_features(boxes, texts, page_size):
    """Cheap per-leaf statistics. Stdlib only, no tuning, no thresholds that decide anything."""
    n = len(texts)
    if not n:
        return {"n_lines": 0}

    heights = [b[3] - b[1] for b in boxes]
    widths = [b[2] - b[0] for b in boxes]
    lefts = [b[0] for b in boxes]
    med_h = statistics.median(heights)
    med_w = statistics.median(widths)
    page_w = page_size[0] if page_size else max(b[2] for b in boxes)

    # Sort-key vote, with ditto lines abstaining (see alpha_run_filter.first_letter).
    votes = [ln for ln in (first_letter(t) for t in texts) if ln]
    modal_letter, modal_n = (Counter(votes).most_common(1)[0] if votes else ("", 0))

    # Left-margin modes at 2% of page width: a crude column-count proxy. Recorded, NOT used to
    # cut -- column detection from hOCR boxes is one of the measured failures (it inverted and
    # dropped 64% of a page), so this is evidence for a model, never a rule.
    bucket = max(1, int(page_w * 0.02))
    margin_hist = Counter(x // bucket for x in lefts)
    margin_modes = sum(1 for _, c in margin_hist.items() if c >= 0.04 * n)

    return {
        "n_lines": n,
        "med_line_chars": round(statistics.median(len(t) for t in texts), 1),
        "med_line_words": round(statistics.median(len(t.split()) for t in texts), 1),
        "share_digit": _share(lambda t: any(c.isdigit() for c in t), texts),
        "share_allcaps": _share(lambda t: t.isupper() and len(t) > 3, texts),
        "share_prose": _share(lambda t: len(t) > PROSE_CHARS, texts),
        "share_bigtype": _share(lambda h: h > 2.0 * med_h, heights),
        "share_banner": _share(lambda w: w > 1.5 * med_w, widths),
        "modal_letter": modal_letter,
        "modal_letter_share": round(modal_n / n, 4),
        "n_voting_lines": len(votes),
        "n_distinct_letters": len(set(votes)),
        "margin_modes": margin_modes,
        "med_line_height": round(med_h, 1),
    }


def kept_counts(lines_path: Path):
    """{leaf: kept-line count} from an ia_volume_to_jsonl.py JSONL, or {} if not supplied."""
    counts = Counter()
    with open(lines_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                counts[json.loads(line)["context"]["leaf"]] += 1
    return counts


def build(ident, out_path, lines_path=None, cache=CACHE, leaves=None, progress=sys.stderr):
    item = Item(ident, cache)
    item.prefetch_hocr()
    n_leaves = len(item.index)
    targets = range(n_leaves) if leaves is None else leaves
    kept = kept_counts(lines_path) if lines_path else {}

    written = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for leaf in targets:
            markup = item.hocr_page(leaf)
            if markup is None:
                continue
            pairs = hocr_lines(markup)
            boxes = [b for b, _ in pairs]
            texts = [t for _, t in pairs]
            size = page_dims(markup)

            feats = leaf_features(boxes, texts, size)
            feats["leaf_frac"] = round(leaf / max(1, n_leaves - 1), 4)
            if kept:
                # The ingest filter's own verdict, as a feature. 0.0 on a leaf it emptied.
                feats["share_kept"] = round(kept.get(leaf, 0) / len(texts), 4) if texts else 0.0

            out.write(json.dumps({
                "ident": ident,
                "leaf": leaf,
                "page_size": size,
                "text": "\n".join(texts),
                "features": feats,
            }, ensure_ascii=False) + "\n")
            written += 1
            if progress and written % 100 == 0:
                print(f"  ... {written}/{len(list(targets)) if leaves else n_leaves} leaves",
                      file=progress)
    return written, n_leaves


def _self_test() -> int:
    """Assert the two properties that would silently corrupt the corpus if they broke."""
    markup = (
        '<div class="ocr_page" title="bbox 0 0 2000 3000">'
        '<p><span class="ocr_line" title="bbox 100 100 400 118">'
        '<span class="ocrx_word" title="bbox 100 100 200 118; x_wconf 90">Ackerman</span> '
        '<span class="ocrx_word" title="bbox 210 100 400 118; x_wconf 90">Anna</span></span></p>'
        '<p><span class="ocr_line" title="bbox 100 130 400 148">'
        '<span class="ocrx_word" title="bbox 100 130 200 148; x_wconf 90">44</span> '
        '<span class="ocrx_word" title="bbox 210 130 400 148; x_wconf 90">Bella</span></span></p>'
    )
    pairs = hocr_lines(markup)
    boxes = [b for b, _ in pairs]
    texts = [t for _, t in pairs]
    assert texts == ["Ackerman Anna", "44 Bella"], texts

    f = leaf_features(boxes, texts, page_dims(markup))

    # 1. The ditto line abstains. If it voted, it would vote "B" for its GIVEN name and the
    #    modal share would read 0.5 across two letters instead of 1.0 across one.
    assert f["n_voting_lines"] == 1, f
    assert f["modal_letter"] == "A" and f["modal_letter_share"] == 0.5, f
    assert f["n_distinct_letters"] == 1, f

    # 2. Every line reaches the document, including ones the ingest filter would drop.
    assert f["n_lines"] == 2, f

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ident", help="IA identifier, e.g. 1906BPL")
    ap.add_argument("--out", help="output JSONL, one row per leaf")
    ap.add_argument("--lines", help="optional ia_volume_to_jsonl.py JSONL; adds share_kept")
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--leaves", help="inspection only, e.g. 13,26,130,145,200,819")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.ident or not args.out:
        ap.error("--ident and --out are required (or use --self-test)")

    leaves = [int(x) for x in args.leaves.split(",")] if args.leaves else None
    written, n_leaves = build(args.ident, Path(args.out),
                              Path(args.lines) if args.lines else None,
                              Path(args.cache), leaves)
    print(f"{args.ident}: wrote {written} leaf documents of {n_leaves} → {args.out}",
          file=sys.stderr)
    if leaves:
        print("NOTE: --leaves is an inspection subset. Only whole-volume runs ship.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
