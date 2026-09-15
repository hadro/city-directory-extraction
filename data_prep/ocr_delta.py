#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Recover the post-OCR parallel corpus this project already built by accident, and measure it.

    python3 data_prep/ocr_delta.py --gold data/trow1884_eval.jsonl \
        --surya-dir ../directory-pipeline/output/trow1884
    python3 data_prep/ocr_delta.py --gold 'data/*_eval.jsonl' --surya-root ../directory-pipeline/output
    python3 data_prep/ocr_delta.py --self-test

Why this exists
---------------
Labelling convention #2 says `raw_line` is the **corrected** page: the labeller fixed Surya's
misreads (`fexton`->`sexton`, `Brewsler`->`Brewster`) in `raw_line` as well as in the fields. The
tool pre-filled `raw_line` from `{stem}_surya.json` and the human edited it in place.

So every hand-labelled gold line is one half of a post-OCR correction pair, and the other half is
still sitting in the Surya JSON. Nothing in the repo has ever put the two side by side. Doing so
gives three things that are otherwise guesswork:

1. **How much OCR error the gold panel silently removes.** The panel scores the model on cleaned
   input; `ia_volume_to_jsonl.py` feeds it uncleaned hOCR. That gap is a measurement blind spot,
   not a model property, and this prints its size.
2. **The confusion table this corpus actually produces.** `synth_persons.py:_NOISE_SUBS` is eleven
   hand-guessed pairs (`m`->`rn`, `l`->`1`, ...). `--noise-table` prints the measured ones,
   ranked, ready to replace it. The generator is this project's established lever, and it is
   currently being aimed by intuition.
3. **A domain-matched parallel corpus** (`--out`), which the post-OCR literature says is the
   scarce ingredient. ~2,300 lines of 1786-1933 NYC directory text, ours, no licence encumbrance.

What this does NOT establish
----------------------------
That correcting OCR would raise extraction scores. It measures the input-side damage only. The
panel cannot answer the output-side question at all, because its input is already clean -- that
experiment needs the pair, and the pair is what this writes.

It also cannot separate a labeller's OCR fix from a labeller's slip. Both look like an edit here.
`validate_gold.py`'s token-drift warnings are the cross-check; a confusion pair that appears once
is noise, one that appears eighty times is the OCR.

Alignment
---------
Gold rows carry `context.image`; Surya lines carry the text the labeller started from. Match
within an image by character-level similarity, greedily, best-first, each Surya line claimed once
-- the same shape as the editor's own `importGold` fuzzy match, tightened to characters because
here we are about to count character edits.

Wrapped entries (conventions 9a/15) are one gold row spanning two Surya lines. The matcher tries
adjacent pairs too; without that, every wrapped entry contributes a whole-line insertion and the
confusion table fills with garbage. `--report` prints how many matched as pairs, because that
count is also the wrapped-entry rate, which nothing else measures.
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

# A match below this character-similarity is not the same line. Chosen so that a badly-OCR'd line
# still matches its correction (they share most characters) while two different entries on the
# same page do not. --min-sim moves it; --report shows what fell out.
MIN_SIM = 0.55

# An edit longer than this is not a character confusion, it is a re-transcription. Counting those
# as "confusions" is how a table fills up with one-off junk.
MAX_CONFUSION_LEN = 4


# ======================================================================================
# loading
# ======================================================================================

def load_gold(path):
    """gold JSONL -> [{raw_line, image, record}]. Rows without an image cannot be aligned."""
    rows = []
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            print(f"  ! {path}:{i} not JSON, skipped", file=sys.stderr)
            continue
        ctx = obj.get("context") or {}
        rows.append({"raw_line": obj.get("raw_line", ""),
                     "image": ctx.get("image", ""),
                     "record": obj.get("record") or {}})
    return rows


def load_surya(surya_dir):
    """dir of {stem}_surya.json -> {image_filename: [line texts in reading order]}.

    Keyed on the *stem* as well as every plausible image extension, because the gold rows store
    whichever filename the sampler wrote and the JSON only knows the stem.
    """
    out = {}
    for sj in sorted(Path(surya_dir).glob("*_surya.json")):
        stem = sj.name[: -len("_surya.json")]
        try:
            data = json.load(open(sj, encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ! {sj}: {e}", file=sys.stderr)
            continue
        texts = [(ln.get("text") or "").strip() for ln in data.get("lines", [])]
        texts = [t for t in texts if t]
        for key in (stem, f"{stem}.jpg", f"{stem}.jpeg", f"{stem}.JPG", f"{stem}.png"):
            out[key] = texts
    return out


# ======================================================================================
# similarity + alignment
# ======================================================================================

def sim(a, b):
    """Character similarity in [0,1]. difflib, not Levenshtein: we only need a ranking here."""
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def levenshtein(a, b):
    """Edit distance. Directory lines are ~60 chars, so the quadratic DP is free."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def align_page(gold_rows, ocr_lines, min_sim=MIN_SIM):
    """Greedy best-first match of gold rows to OCR lines (or adjacent OCR line PAIRS).

    Returns (pairs, unmatched_gold), where each pair is
    (gold_index, ocr_text, [ocr_line_indices], similarity).

    Greedy-best-first rather than in-order because the tool's reading order and the labeller's
    row order agree on most pages and disagree on exactly the multi-column ones, which are the
    pages worth measuring.
    """
    cands = []
    for gi, g in enumerate(gold_rows):
        raw = g["raw_line"]
        for oi, o in enumerate(ocr_lines):
            s = sim(raw, o)
            if s >= min_sim:
                cands.append((s, gi, o, (oi,)))
            # wrapped entry: one printed entry, two OCR lines, joined in raw_line
            if oi + 1 < len(ocr_lines):
                joined = f"{o} {ocr_lines[oi + 1]}"
                sj = sim(raw, joined)
                # only prefer the join when it is genuinely better -- otherwise every short line
                # matches its neighbour-pair a little better just by having more characters
                if sj >= min_sim and sj > s + 0.05:
                    cands.append((sj, gi, joined, (oi, oi + 1)))

    cands.sort(key=lambda c: -c[0])
    used_g, used_o, pairs = set(), set(), []
    for s, gi, text, idxs in cands:
        if gi in used_g or any(i in used_o for i in idxs):
            continue
        used_g.add(gi)
        used_o.update(idxs)
        pairs.append((gi, text, list(idxs), s))
    unmatched = [gi for gi in range(len(gold_rows)) if gi not in used_g]
    return pairs, unmatched


# ======================================================================================
# what changed
# ======================================================================================

def confusions(ocr, gold):
    """Character-level edits turning OCR text into the corrected line.

    Yields (ocr_span, gold_span) with '' for a pure insert/delete. Spans longer than
    MAX_CONFUSION_LEN are dropped: they are re-transcriptions, not confusions.
    """
    out = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ocr, gold, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        a, b = ocr[i1:i2], gold[j1:j2]
        if len(a) <= MAX_CONFUSION_LEN and len(b) <= MAX_CONFUSION_LEN:
            out.append((a, b))
    return out


_WORD = re.compile(r"[^\s]+")


def field_hits(ocr, gold, record):
    """Which gold FIELDS contain a token the OCR got wrong.

    Per-character attribution would be more precise and less honest: the fields are stored
    canonically (commas dropped, and so on), so a character offset in `raw_line` does not index
    into a field. Token membership is what the schema actually supports -- and it answers the
    question that matters, which is whether OCR damage lands on `name`.
    """
    bad = {t for t in _WORD.findall(gold)} - {t for t in _WORD.findall(ocr)}
    if not bad:
        return []
    hits = []
    for f, v in record.items():
        if not isinstance(v, str) or not v.strip():
            continue
        if {t for t in _WORD.findall(v)} & bad:
            hits.append(f)
    return hits


# ======================================================================================
# the measurement
# ======================================================================================

def measure(gold_rows, pages, min_sim=MIN_SIM):
    """Align a volume and tally. Returns a stats dict; printing lives in main()."""
    st = {"gold": len(gold_rows), "matched": 0, "unmatched": 0, "wrapped": 0,
          "changed": 0, "gold_chars": 0, "edits": 0, "no_image": 0, "no_page": 0,
          "conf": Counter(), "fields": Counter(), "pairs": [], "examples": []}

    by_image = {}
    for i, g in enumerate(gold_rows):
        by_image.setdefault(g["image"], []).append(i)

    for image, idxs in by_image.items():
        if not image:
            st["no_image"] += len(idxs)
            continue
        ocr_lines = pages.get(image)
        if ocr_lines is None:
            st["no_page"] += len(idxs)
            continue
        sub = [gold_rows[i] for i in idxs]
        matched, unmatched = align_page(sub, ocr_lines, min_sim)
        st["unmatched"] += len(unmatched)
        for gi, ocr_text, oidx, s in matched:
            g = sub[gi]
            gold_line = g["raw_line"]
            st["matched"] += 1
            if len(oidx) > 1:
                st["wrapped"] += 1
            st["gold_chars"] += len(gold_line)
            d = levenshtein(ocr_text, gold_line)
            st["edits"] += d
            st["pairs"].append({"ocr": ocr_text, "gold": gold_line,
                                "image": image, "sim": round(s, 4),
                                "record": g["record"]})
            if d:
                st["changed"] += 1
                for a, b in confusions(ocr_text, gold_line):
                    st["conf"][(a, b)] += 1
                for f in field_hits(ocr_text, gold_line, g["record"]):
                    st["fields"][f] += 1
                if len(st["examples"]) < 12:
                    st["examples"].append((ocr_text, gold_line))
    return st


def cer(st):
    return st["edits"] / st["gold_chars"] if st["gold_chars"] else 0.0


def noise_table(conf, top=24):
    """Measured confusions as a paste-ready `_NOISE_SUBS` replacement.

    Direction matters and is easy to get backwards. `confusions()` reports (ocr, gold) -- what the
    scanner produced and what was actually printed. `synth_persons.add_noise` needs the opposite:
    it starts from clean text and corrupts it, so it wants (gold, ocr).
    """
    rows = [(a, b, n) for (a, b), n in conf.most_common() if a and b][:top]
    out = ["_NOISE_SUBS = [   # measured by data_prep/ocr_delta.py --noise-table; (clean, ocr)"]
    for ocr_span, gold_span, n in rows:
        out.append(f"    ({gold_span!r}, {ocr_span!r}),   # seen {n}x")
    out.append("]")
    return "\n".join(out)


# ======================================================================================
# self-test
# ======================================================================================

def _self_test():
    assert levenshtein("", "") == 0
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("Brewsler", "Brewster") == 1      # one substitution, l->t
    assert levenshtein("", "abc") == 3

    # a substitution is a confusion; a whole re-transcription is not
    assert ("l", "t") in confusions("Brewsler", "Brewster")
    assert confusions("x" * 40, "y" * 40) == []          # too long to be a confusion

    # long-s: the single most common fix in the pre-1830 volumes
    assert ("f", "s") in confusions("fexton", "sexton")

    # alignment: the right OCR line wins even when a similar one sits on the same page
    gold = [{"raw_line": "Brewster John carpenter 12 Pine", "image": "p1.jpg", "record": {}}]
    ocr = ["Brewsler John carpenter 12 Pine", "Brewer James mason 14 Pine"]
    pairs, un = align_page(gold, ocr)
    assert not un and pairs[0][1] == ocr[0], pairs

    # a wrapped entry: one gold row, two OCR lines, joined
    gold = [{"raw_line": "Smith Peter clerk 97 Chambers & 81 Reade", "image": "p1.jpg",
             "record": {}}]
    ocr = ["Smith Peter clerk 97 Chambers", "& 81 Reade"]
    pairs, un = align_page(gold, ocr)
    assert not un, un
    assert len(pairs[0][2]) == 2, pairs                  # claimed BOTH lines

    # ...and the second OCR line is then not available to a different gold row
    gold2 = [{"raw_line": "Smith Peter clerk 97 Chambers & 81 Reade", "image": "p1.jpg",
              "record": {}},
             {"raw_line": "& 81 Reade", "image": "p1.jpg", "record": {}}]
    pairs2, un2 = align_page(gold2, ocr)
    assert len(un2) == 1, (pairs2, un2)

    # a gold row with no counterpart on the page stays unmatched rather than matching something
    gold3 = [{"raw_line": "Zwicker Ludwig baker 4 Ave A", "image": "p1.jpg", "record": {}}]
    _, un3 = align_page(gold3, ocr)
    assert len(un3) == 1, un3

    # field attribution: the damaged token sits in `name`, not in `address`
    rec = {"name": "Brewster John", "occupation_role": "carpenter", "address": "12 Pine"}
    hits = field_hits("Brewsler John carpenter 12 Pine", "Brewster John carpenter 12 Pine", rec)
    assert hits == ["name"], hits

    # end to end
    pages = {"p1.jpg": ["Brewsler John carpenter 12 Pine", "fexton Mary wid 8 Bond"]}
    rows = [{"raw_line": "Brewster John carpenter 12 Pine", "image": "p1.jpg",
             "record": {"name": "Brewster John"}},
            {"raw_line": "sexton Mary wid 8 Bond", "image": "p1.jpg",
             "record": {"name": "sexton Mary"}}]
    st = measure(rows, pages)
    assert st["matched"] == 2 and st["changed"] == 2, st
    assert 0 < cer(st) < 0.15, cer(st)
    assert st["fields"]["name"] == 2, st["fields"]

    # the noise table is emitted in GENERATOR direction (clean -> ocr), the reverse of the tally
    tbl = noise_table(Counter({("l", "t"): 9}))
    assert "('t', 'l')" in tbl, tbl

    # a clean volume measures as clean, and does not crash on zero edits
    st0 = measure([{"raw_line": "Ross Ann milliner 3 Cedar", "image": "p1.jpg", "record": {}}],
                  {"p1.jpg": ["Ross Ann milliner 3 Cedar"]})
    assert st0["changed"] == 0 and cer(st0) == 0.0

    print("ocr_delta self-test OK", file=sys.stderr)
    return 0


# ======================================================================================
# cli
# ======================================================================================

def _volume_slug(gold_path):
    return Path(gold_path).name.replace("_eval.jsonl", "").replace(".jsonl", "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", help="gold JSONL, or a glob ('data/*_eval.jsonl')")
    ap.add_argument("--surya-dir", help="sampled volume dir holding *_surya.json")
    ap.add_argument("--surya-root", help="parent dir; per-volume subdir is matched by slug")
    ap.add_argument("--out", help="write the parallel corpus as JSONL {ocr, gold, ...}")
    ap.add_argument("--noise-table", action="store_true",
                    help="print a measured _NOISE_SUBS for synth_persons.py")
    ap.add_argument("--min-sim", type=float, default=MIN_SIM,
                    help=f"character similarity an alignment needs (default {MIN_SIM})")
    ap.add_argument("--examples", type=int, default=8, help="corrected lines to print per volume")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()
    if not a.gold:
        ap.error("--gold is required (or use --self-test)")
    if not (a.surya_dir or a.surya_root):
        ap.error("one of --surya-dir / --surya-root is required")

    gold_paths = sorted(glob.glob(a.gold)) or ([a.gold] if os.path.exists(a.gold) else [])
    if not gold_paths:
        ap.error(f"no gold files matched {a.gold!r}")

    total = {"gold": 0, "matched": 0, "unmatched": 0, "wrapped": 0, "changed": 0,
             "gold_chars": 0, "edits": 0, "no_image": 0, "no_page": 0,
             "conf": Counter(), "fields": Counter()}
    all_pairs, per_volume = [], []

    for gp in gold_paths:
        slug = _volume_slug(gp)
        sdir = a.surya_dir or str(Path(a.surya_root) / slug)
        if not Path(sdir).is_dir():
            print(f"  ! {slug}: no surya dir at {sdir}, skipped", file=sys.stderr)
            continue
        pages = load_surya(sdir)
        if not pages:
            print(f"  ! {slug}: no *_surya.json in {sdir}, skipped", file=sys.stderr)
            continue
        st = measure(load_gold(gp), pages, a.min_sim)
        per_volume.append((slug, st))
        for k in ("gold", "matched", "unmatched", "wrapped", "changed", "gold_chars",
                  "edits", "no_image", "no_page"):
            total[k] += st[k]
        total["conf"] += st["conf"]
        total["fields"] += st["fields"]
        all_pairs.extend(dict(p, volume=slug) for p in st["pairs"])

    if not per_volume:
        print("nothing aligned -- check --surya-root / slugs", file=sys.stderr)
        return 1

    w = sys.stderr
    print(f"\n{'volume':<20} {'gold':>6} {'align':>6} {'wrap':>5} {'changed':>8} {'CER':>7}", file=w)
    print("-" * 56, file=w)
    for slug, st in per_volume:
        pct = 100 * st["changed"] / max(st["matched"], 1)
        print(f"{slug:<20} {st['gold']:>6,} {st['matched']:>6,} {st['wrapped']:>5,} "
              f"{pct:>7.1f}% {cer(st):>7.4f}", file=w)
    pct = 100 * total["changed"] / max(total["matched"], 1)
    print("-" * 56, file=w)
    print(f"{'ALL':<20} {total['gold']:>6,} {total['matched']:>6,} {total['wrapped']:>5,} "
          f"{pct:>7.1f}% {cer(total):>7.4f}", file=w)

    lost = total["unmatched"] + total["no_image"] + total["no_page"]
    if lost:
        print(f"\nunaligned: {lost:,} gold rows "
              f"({total['unmatched']:,} no match >= {a.min_sim}, "
              f"{total['no_image']:,} no context.image, {total['no_page']:,} page not found)",
              file=w)
        print("  a high no-match count means the OCR is worse than --min-sim allows for, which "
              "BIASES\n  the CER downward -- the worst lines are the ones that drop out.", file=w)

    if total["fields"]:
        print("\nwhere the OCR damage lands (gold rows with a damaged token in that field):",
              file=w)
        for f, n in total["fields"].most_common():
            print(f"  {f:<18} {n:>6,}  {100 * n / max(total['changed'], 1):>5.1f}% of changed rows",
                  file=w)

    if total["conf"]:
        print("\ntop confusions (ocr -> printed):", file=w)
        for (o, g), n in total["conf"].most_common(20):
            print(f"  {o!r:>8} -> {g!r:<8} {n:>5,}", file=w)

    if a.examples:
        print("\ncorrections the labellers actually made:", file=w)
        shown = 0
        for slug, st in per_volume:
            for o, g in st["examples"]:
                if shown >= a.examples:
                    break
                print(f"  [{slug}]\n    ocr : {o}\n    page: {g}", file=w)
                shown += 1

    if a.noise_table:
        print("\n" + noise_table(total["conf"]))

    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            for p in all_pairs:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
        print(f"\nwrote {len(all_pairs):,} pairs -> {a.out}", file=w)
    else:
        print("\n(report only -- pass --out to write the parallel corpus)", file=w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
