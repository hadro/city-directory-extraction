#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Measure what `synth_persons.add_noise` actually does to the training input.

    python3 data_prep/measure_synth_noise.py
    python3 data_prep/measure_synth_noise.py -n 50000 --noise 0.35 0.6 1.0
    python3 data_prep/measure_synth_noise.py --self-test

Why this exists
---------------
The generator's noise is the ONLY thing that teaches the model to read damaged OCR -- per the
copying-vs-sampling mechanism, a substitution is never a substring copy, so the model corrects
exactly what the generator demonstrates and nothing else. `--noise` is a per-line probability,
which is not comparable to anything: OCR quality is reported as CER, and `historical-ocr-eval`
put the production IA hOCR at CER-all 0.067.

This converts the knob into that unit, so train-time and production input quality can be put on
one axis. Findings as of 2026-09-15 are written up in docs/POST_OCR_CORRECTION.md; the headline
is that the shipped default produces CER 0.0101, about 6.6x cleaner than production.

It also reports two things that are easy to miss by reading `add_noise`:

  * the gap between the nominal rate and the share of lines that actually change (a chosen
    confusion pair no-ops when it is not applicable to the line), and
  * per-pair applicability -- how often each hand-written pair could fire at all. This is how
    ("ii", "n") was caught at 0.0% and removed, taking the list from eleven pairs to ten.

Run it before and after any change to `add_noise` or `_NOISE_SUBS`; the numbers in
POST_OCR_CORRECTION.md are its output and should be updated from it, not by hand.
"""

import argparse
import importlib.util
import random
import statistics
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path


def load_generator(path=None):
    p = Path(path) if path else Path(__file__).resolve().parent / "synth_persons.py"
    spec = importlib.util.spec_from_file_location("synth_persons", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def edit_positions(clean, noisy):
    """Relative position in the clean line of each edit -- 0.0 is line start, 1.0 is line end."""
    out = []
    for tag, i1, _i2, _j1, _j2 in SequenceMatcher(None, clean, noisy, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append(i1 / max(len(clean), 1))
    return out


def measure(sp, n, p, profile="mix", seed=13):
    rng = random.Random(seed)
    chars = edits = touched = length = 0
    positions = []
    for _ in range(n):
        clean = sp.make_record(rng, profile)["raw_line"]
        noisy = sp.add_noise(rng, clean, p)
        d = levenshtein(clean, noisy)
        chars += len(clean)
        length += len(clean)
        edits += d
        if d:
            touched += 1
            positions.extend(edit_positions(clean, noisy))
    return {"n": n, "noise": p, "mean_len": length / n, "touched": touched / n,
            "edits_per_line": edits / n, "cer": edits / chars if chars else 0.0,
            "positions": positions}


def applicability(sp, n, profile="mix", seed=13):
    """Share of generated lines that even CONTAIN the left side of each confusion pair."""
    rng = random.Random(seed)
    hits = Counter()
    for _ in range(n):
        line = sp.make_record(rng, profile)["raw_line"]
        for pair in sp._NOISE_SUBS:
            if pair[0] in line:
                hits[pair] += 1
    return [(pair, hits.get(pair, 0) / n) for pair in sp._NOISE_SUBS]


def _self_test():
    assert levenshtein("", "") == 0
    assert levenshtein("Brewsler", "Brewster") == 1
    assert levenshtein("abc", "") == 3
    pos = edit_positions("abcdefghij", "abXdefghij")
    assert pos and 0.0 <= pos[0] <= 1.0 and abs(pos[0] - 0.2) < 1e-9, pos
    assert edit_positions("same", "same") == []

    sp = load_generator()
    # noise 0 must be inert -- otherwise every CER below is measuring the wrong thing
    z = measure(sp, 400, 0.0)
    assert z["cer"] == 0.0 and z["touched"] == 0.0, z
    # and the knob must be monotone in the direction it claims
    lo, hi = measure(sp, 1200, 0.2), measure(sp, 1200, 1.0)
    assert lo["cer"] < hi["cer"], (lo["cer"], hi["cer"])
    print("measure_synth_noise self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", type=int, default=20000, help="lines per noise level (default 20000)")
    ap.add_argument("--noise", type=float, nargs="+", default=[0.35, 0.6, 1.0])
    ap.add_argument("--profile", default="mix", choices=["mix", "nyc", "tulsa"])
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--generator", help="path to synth_persons.py (default: alongside this file)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return _self_test()

    sp = load_generator(a.generator)
    w = sys.stderr
    print(f"\nprofile={a.profile}  n={a.n:,} per level  seed={a.seed}", file=w)
    print(f"\n{'--noise':>8} {'lines touched':>14} {'edits/line':>11} {'input CER':>10}", file=w)
    print("-" * 47, file=w)
    all_pos = []
    for p in a.noise:
        m = measure(sp, a.n, p, a.profile, a.seed)
        all_pos = m["positions"] or all_pos
        print(f"{p:>8} {100 * m['touched']:>13.1f}% {m['edits_per_line']:>11.3f} "
              f"{m['cer']:>10.4f}", file=w)
    print(f"\nmean generated line length: {m['mean_len']:.1f} chars", file=w)
    print("production reference: IA hOCR CER-all 0.067 (historical-ocr-eval, see HANDOFF.md)",
          file=w)

    print("\nconfusion-pair applicability (share of lines containing the left side):", file=w)
    for (frm, to), share in sorted(applicability(sp, a.n, a.profile, a.seed),
                                   key=lambda kv: -kv[1]):
        flag = "   <- cannot fire" if share == 0 else ""
        print(f"  {frm!r:>6} -> {to!r:<6} {100 * share:>5.1f}%{flag}", file=w)

    if all_pos:
        first = 100 * sum(x < 0.25 for x in all_pos) / len(all_pos)
        last = 100 * sum(x >= 0.75 for x in all_pos) / len(all_pos)
        print(f"\nedit position in line: mean {statistics.mean(all_pos):.3f}, "
              f"{first:.1f}% in the first quarter vs {last:.1f}% in the last", file=w)
        print("  (since 2026-09-20 every edit picks a RANDOM occurrence, so what is left is\n"
              "   where the substitutable characters actually sit -- a property of the line,\n"
              "   not of the implementation. Before the fix this read 27.0% vs 16.8%.)", file=w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
