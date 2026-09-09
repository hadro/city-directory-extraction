#!/usr/bin/env python3
"""Backfill blank `publisher` in master_directories.csv, and audit the column against
the publisher vocabulary the model was actually trained on.

Why this exists: 136 of the 291 `source=ia` rows have a blank `publisher`, so
ia_volume_to_jsonl.py falls back to `trow` and tags the volume `[publisher=trow; ...]`.
That is silently wrong for, say, an 1830s Brooklyn directory. But nearly every blank row
already carries the answer in its own `title` and `notes` — this fills those in from the
CSV itself, with no network and no model calls.

Two things that look like one thing, and are not:

  1. `publisher` is CATALOG TRUTH. The catalog ships as a standalone community reference
     (cf. backfill_contributor.py), so this column should say `spooner` when Spooner
     published it, whether or not any model has heard of Spooner.

  2. The `[publisher=X]` TRAINING TAG is a closed set of 17 tokens (see TRAINED_VOCAB,
     extracted from data/synth_train_250k.jsonl). Writing an out-of-vocabulary publisher
     into the tag is not a fix — it swaps a wrong-but-learned token for one the model has
     never seen. eval/qwen_predict.py interpolates the tag as free text, so both pass
     silently. Which is better is an empirical question, not an obvious one.

So this script fills column (1) and *reports* on (2). It deliberately does not decide the
OOV -> trained-token mapping; that needs an A/B, and the report is the candidate list.

Attribution rules are conservative, because the notes distinguish assertions from hedges:

    "Spooner-era Brooklyn"                        -> assert spooner
    "Hearnes' Brooklyn City Directory" (title)    -> assert hearne
    "Lain-era Consolidated; publisher unverified" -> HEDGE, leave blank, flag for sampling
    "Williamsburgh, pre-Lain"                     -> NEGATIVE, never fill lain
    "likely Trow" / "Trow-era?" / "matches X-era"  -> HEDGE, leave blank

Anything not asserted is reported as NEEDS SAMPLE rather than guessed. Idempotent.

    python3 data_prep/backfill_publisher.py             # dry run: unified diff + audit
    python3 data_prep/backfill_publisher.py --write     # apply to the CSV
    python3 data_prep/backfill_publisher.py --all       # include telephone directories
"""

import argparse
import csv
import difflib
import io
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASTER = HERE / "master_directories.csv"

# The `[publisher=X]` tokens present in data/synth_train_250k.jsonl. Anything outside this set is
# out-of-vocabulary at tag time no matter how correct it is as catalog metadata. Imported rather
# than copied: ia_volume_to_jsonl.py is what actually builds the tag, so it owns the list.
sys.path.insert(0, str(HERE))
from ia_volume_to_jsonl import TRAINED_VOCAB  # noqa: E402

# Notes phrases that mark a publisher mention as a guess rather than an attribution.
HEDGE_RE = re.compile(
    r"publisher\s+(?:unverified|unidentified|not\s+identified)"
    r"|not\s+a\s+city\s+directory"
    r"|needs\s+sample\s*\(publisher",
    re.I,
)

# Hedge words that neutralise an otherwise-assertive publisher mention.
QUALIFIER_RE = re.compile(r"\b(?:likely|poss(?:ibly)?|probably|matches|overlaps|maybe)\b", re.I)

# `pre-Lain` asserts the opposite of Lain. Captured names are suppressed outright.
NEGATIVE_RE = re.compile(r"\bpre-([A-Za-z&]+)", re.I)

# Publisher spellings in the wild -> the catalog's canonical form.
CANONICAL = {
    "hearnes": "hearne",
    "doggetts": "doggett",
    "hope & henderson": "hopehenderson",
    "hope&henderson": "hopehenderson",
}


def known_publishers(rows):
    """Publisher atoms the catalog already uses, plus the trained vocabulary.

    Built from the data rather than hardcoded so the rules keep up as rows are curated.
    Compound values ("trow/wilson", "elliot & crissy") contribute each atom separately.
    """
    atoms = set(TRAINED_VOCAB)
    for row in rows:
        value = (row.get("publisher") or "").strip().lower()
        for atom in re.split(r"[/&]", value):
            atom = atom.strip()
            # Skip corporate names ("ny telephone co.", "manhattan & bronx directory co.")
            # and bare initials; they never appear as "X-era" or "X's" in the notes.
            if len(atom) >= 4 and " " not in atom and not atom.endswith("."):
                atoms.add(CANONICAL.get(atom, atom))
    return atoms


def canonical(name):
    # Strip only apostrophe-possessives ("doggett's", "hearnes'"). A bare trailing "s" is
    # part of the name -- `franks` must not become `frank`, which is not a trained token.
    name = re.sub(r"['’]s$|s['’]$|['’]$", "", name.strip().lower())
    return CANONICAL.get(name, name)


def infer(row, known):
    """-> (publisher, evidence) or (None, reason_it_was_not_filled)."""
    title = (row.get("title") or "").strip()
    notes = (row.get("notes") or "").strip()
    blob = f"{title} {notes}"

    if HEDGE_RE.search(notes):
        return None, "notes hedge the publisher"

    suppressed = {canonical(m) for m in NEGATIVE_RE.findall(blob)}

    # Strongest evidence: a possessive in the title. "Hearnes' Brooklyn City Directory".
    for name in sorted(known, key=len, reverse=True):
        if name in suppressed:
            continue
        if re.search(rf"\b{re.escape(name)}(?:'s|s'|')\s", title, re.I):
            return name, f"title possessive: {title[:44]!r}"

    # Curator's era attribution in the notes, e.g. "Spooner-era Brooklyn".
    for name in sorted(known, key=len, reverse=True):
        if name in suppressed:
            continue
        match = re.search(rf"\b{re.escape(name)}-era\b", notes, re.I)
        if not match:
            continue
        # "matches Upington-era" / "Trow-era?" are guesses, not attributions.
        window = notes[max(0, match.start() - 40):match.end() + 2]
        if QUALIFIER_RE.search(window) or window.rstrip().endswith("?"):
            return None, f"era mention is qualified: {window.strip()[:44]!r}"
        return name, f"notes era: {match.group(0)}"

    return None, "no publisher named in title or notes"


def classify_oov(publisher):
    """-> (kind, trained_stand_in). Not every OOV value is equally out.

    `hearnes` is the trained `hearne` with a stray possessive; `trow/wilson` is a
    partnership whose senior partner is trained. Only values with no trained relation
    at all genuinely need an experiment to choose a stand-in.
    """
    if canonical(publisher) in TRAINED_VOCAB:
        return "variant", canonical(publisher)

    atoms = [canonical(a) for a in re.split(r"[/&]", publisher)]
    trained = [a for a in atoms if a in TRAINED_VOCAB]
    if trained:
        return "compound", trained[0]

    return "unseen", None


def render(fieldnames, rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="apply changes (default: diff only)")
    ap.add_argument("--all", action="store_true",
                    help="include telephone directories (skipped by default: different genre)")
    args = ap.parse_args()

    with MASTER.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    before = render(fieldnames, rows)
    known = known_publishers(rows)

    blank = [r for r in rows if not (r.get("publisher") or "").strip()]
    phone = [r for r in blank if "telephone" in (r.get("title") or "").lower()]
    targets = blank if args.all else [r for r in blank if r not in phone]

    print(f"{len(rows)} rows | {len(blank)} blank publisher | "
          f"{len(phone)} telephone (skipped unless --all) | {len(targets)} in scope\n")

    filled, needs_sample = [], []
    for row in targets:
        publisher, why = infer(row, known)
        if publisher:
            row["publisher"] = publisher
            filled.append((row, publisher, why))
        else:
            needs_sample.append((row, why))

    if filled:
        print(f"FILLED ({len(filled)}):")
        for row, publisher, why in sorted(filled, key=lambda t: t[0]["year"]):
            flag = "" if publisher in TRAINED_VOCAB else "  [OOV at tag time]"
            print(f"  {row['id'][:32]:34} {row['year']:8} -> {publisher:<14} {why}{flag}")

    if needs_sample:
        print(f"\nNEEDS SAMPLE ({len(needs_sample)}) — a page read, not a metadata lookup:")
        for row, why in sorted(needs_sample, key=lambda t: t[0]["year"]):
            print(f"  {row['id'][:32]:34} {row['year']:8}    {why}")

    # Audit the whole column against what the model can actually condition on.
    oov = Counter()
    for row in rows:
        publisher = (row.get("publisher") or "").strip().lower()
        if publisher and publisher not in TRAINED_VOCAB:
            oov[publisher] += 1
    if oov:
        buckets = {"variant": [], "compound": [], "unseen": []}
        for publisher, n in oov.most_common():
            kind, stand_in = classify_oov(publisher)
            buckets[kind].append((n, publisher, stand_in))

        total = sum(oov.values())
        print(f"\nOUT-OF-VOCABULARY publishers ({total} rows, {len(oov)} distinct). All correct"
              f"\nas catalog metadata; none can be tagged as-is. Today all fall back to `trow`.")

        if buckets["variant"]:
            print("\n  SPELLING VARIANT of a trained token — free fix, just normalise the tag:")
            for n, publisher, stand_in in buckets["variant"]:
                print(f"    {n:4d}  {publisher:<32} -> {stand_in}")
        if buckets["compound"]:
            print("\n  COMPOUND containing a trained token — tag with the trained atom:")
            for n, publisher, stand_in in buckets["compound"]:
                print(f"    {n:4d}  {publisher:<32} -> {stand_in}")
        if buckets["unseen"]:
            print("\n  GENUINELY UNSEEN — no trained relation. These are the only ones that need"
                  "\n  an A/B to pick a stand-in; guessing here is what `--publisher spooner` does:")
            for n, publisher, _ in buckets["unseen"]:
                print(f"    {n:4d}  {publisher}")

    after = render(fieldnames, rows)
    if before == after:
        print("\nno changes")
        return 0

    diff = difflib.unified_diff(before.splitlines(keepends=True),
                               after.splitlines(keepends=True),
                               fromfile="master_directories.csv",
                               tofile="master_directories.csv (proposed)", n=0)
    print("\n" + "".join(diff))

    if not args.write:
        print("dry run: nothing written. re-run with --write to apply.")
        return 0

    with MASTER.open("w", newline="", encoding="utf-8") as fh:
        fh.write(after)
    print(f"wrote {MASTER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
