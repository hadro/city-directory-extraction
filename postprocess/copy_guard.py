#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Put back the printed word when the model replaced it with a familiar one -- a post-check on
predictions. No model, no gold.

    python3 postprocess/copy_guard.py --volumes data/volumes --run 4b-100k
    python3 postprocess/copy_guard.py --lines data/mercein1820_eval.jsonl \\
        --preds results/runs/scale-runs/preds/preds_4b-100k_mercein1820.txt --out guarded.txt
    python3 postprocess/copy_guard.py --check-panel 4b-100k     # regression test, clean panel
    python3 postprocess/copy_guard.py --self-test

--volumes writes chunk_NNN.preds_<run>+guard.txt beside every chunk_NNN.preds_<run>.txt, and an
audit (guard_audit.tsv) of every word it changed, per volume. The model's own predictions are
never touched, the rule resolve_dittos.py keeps for the same reason: the unguarded file is what
the panel and every published number measured.

WHAT IT FIXES (measured on the five-volume 4B run, 2026-09-28)
--------------------------------------------------------------
The model is trained to repair OCR: synth_persons.py corrupts 35% of training inputs and keeps
the targets clean. Most of what that buys is right -- 1906BPL's `elk -> clk` 14,900 times,
`pi -> pl`, `cartmaa -> cartman`. The same habit rewrites words that were printed and read
correctly, because they are unfamiliar: `Mhtn -> Mthn` 13,707 times (4B only), `Degraw ->
Delaware`, `Bancker -> Banker`, `Goerck -> George`, `Meserole -> Moseley`, `rd -> dr`. And where a
name prints no given name (`Ackerman widow, 47 Elizabeth`), it adds one: Mary or Sarah on 15%
of Mercein's 1,391 widows.

The model cannot tell the two apart, because it does not know which words THIS book prints. The
guard does. Each field is aligned to its own line word by word, and every word the model changed
is judged:

    kept      spacing or punctuation only                     `realestate -> real estate`
    kept      made only of classical OCR misreadings          `elk -> clk`, `pi -> pl`, `8 -> B`
    kept      a piece of a word the OCR glued to its neighbour `boardingh` -> `h`
    kept      a rare printed word moved to one this volume    `cartmaa -> cartman`
              prints often, within MAX_EDIT characters
    RESTORED  anything else: the printed word goes back       `Degraw -> Delaware -> Degraw`
    DROPPED   a name word with no near match anywhere in      `Ackerman Sarah -> Ackerman`
              the line: a given name that was never printed

The volume's own vocabulary is what makes the third rule safe: `Goerck` is printed 148+ times
in Doggett 1845, so it is not an OCR error for `George`, however common George is as a given
name. The rule that keeps a repair is also what limits the guard. A rare REAL word moved to a
common one within two characters is kept, so a street printed a handful of times can still be
lost.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
from evaluate import FIELDS, _cell, load_pred  # noqa: E402

TEXT_FIELDS = ("name", "spouse_name", "race_designation", "occupation_role", "employer",
               "address", "home_address")
PUNCT = set(".,;:'\"-*|()[]!?/\\`’‘“”„—–_~^«»•■")
# Classical OCR misreadings, either direction, lower case. An edit made only of these is a repair.
CONFUSIONS = {frozenset(p) for p in [
    ("e", "c"), ("e", "o"), ("c", "o"), ("a", "o"), ("i", "l"), ("i", "1"), ("l", "1"),
    ("l", "t"), ("f", "t"), ("0", "o"), ("8", "b"), ("b", "h"), ("h", "k"), ("n", "u"),
    ("5", "s"), ("rn", "m"), ("ii", "u"), ("li", "h"), ("cl", "d"), ("vv", "w"), ("ri", "n"),
    ("in", "m"), ("ni", "m"), ("t", "i"), ("6", "b"), ("8", "s"), ("v", "y"),
    ("f", "s"), ("l", "s"), ("i", "s"), ("j", "s"),   # the long s, read as f, l, i or J:
    # `Jofeph`, `Water-ftreet`, `William-ltreet`, `Wall-itreet`, `Han. Jquare`, `Auguflus` (fl = st)
    ("c", "t"), ("o", "q"), ("a", "u")]}   # old type: `ftreec`, `Oueen`, `Qaincey`
# Punctuation that is a misread letter or digit. Checked on the unsquashed text, because
# squashing drops the punctuation before it can be compared: `Genera)` is `General`, `10!` is 101.
GLYPHS = {frozenset(p) for p in [(")", "l"), ("|", "l"), ("!", "l"), ("!", "1"), ("|", "1"),
                                 ("]", "l"), ("(", "c"), ("(", "s")]}   # `Cherry-(t.`
# a residence marker glued to its neighbour: `N. Y.h 107 Willow`, `hl701, 86th`
MARKER = re.compile(r"^[hrb]\.?(?=[\dlio])|(?<=\.)[hrb]$")
BOOK_WORD = 20       # the replacement must occur this often in the volume's OCR...
BOOK_RATIO = 10      # ...and this many times more often than the printed word it replaced
MAX_EDIT = 2         # ...and be this close to it, in characters
NAME_MATCH = 0.6     # a name word below this similarity to every window of its line was invented


def _norm(tok: str) -> str:
    return re.sub(r"[^a-z0-9]", "", tok.lower())


def _squash(s: str) -> str:
    return "".join(c for c in s.lower() if c not in PUNCT and not c.isspace())


_FOLD = str.maketrans("1i!|05$8", "lllloss" + "b")


def _fold(s: str) -> str:
    """_squash with look-alike characters folded together, for choosing which printed words a
    rewritten block came from (not for judging whether the rewrite was allowed)."""
    return _squash(s.lower().translate(_FOLD))


def _dist(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def build_vocab(raw_lines) -> Counter:
    return Counter(n for line in raw_lines for n in map(_norm, line.split()) if n)


def volume_vocab(lines: list) -> Counter:
    """The vocabulary of the WHOLE volume these lines come from -- its survey-scoped lines --
    when they all name one IA volume that has them. A staged panel set (50-800 lines) would
    otherwise judge `toward-book` against a sliver of the book. Falls back to the lines."""
    ids = {(ln.get("context") or {}).get("ia_id") for ln in lines}
    src = REPO / "data" / "survey_ocr" / f"{next(iter(ids))}_listing.jsonl.gz" if len(ids) == 1 \
        and None not in ids else None
    if src is not None and src.exists():
        import gzip
        with gzip.open(src, "rt", encoding="utf-8") as fh:
            return build_vocab(json.loads(x)["raw_line"] for x in fh if x.strip())
    return build_vocab(ln["raw_line"] for ln in lines)


def judge(printed: str, wrote: str, vocab: Counter) -> str | None:
    """Why the model's `wrote` may stand in for `printed`, or None if it may not."""
    p, w = _squash(printed), _squash(wrote)
    if re.search(r"\d\s+\d+\.", printed) and \
            re.findall(r"\d+", printed) != re.findall(r"\d+", wrote):
        return None                  # `76 8. 7th -> 768 7th`: the `8.` is a misread `S.` (South),
                                     # not the tail of the number. `1 1 Murray -> 11` stays joined.
    if p == w:
        return "spacing"
    if w and len(p) - len(w) >= 3 and (p.startswith(w) or p.endswith(w)):
        return "glued-part"          # `boardingh` printed; the model took `h` for the address
    if _misreadings(p, w) or _misreadings(*(re.sub(r"[\s,;:]", "", x.lower()) for x in (printed, wrote))):
        return "ocr-confusion"       # `II -> 11` is two misreadings, not one
    unmarked = MARKER.sub("", re.sub(r"\s", "", printed.lower()))
    if unmarked != re.sub(r"\s", "", printed.lower()) and judge(unmarked, wrote, vocab):
        return "glued-marker"        # `Y.h -> Y.` and `hl701 -> 1701`: the h went to home_address
    fp, fw = vocab.get(p, 0), vocab.get(w, 0)
    if fw >= BOOK_WORD and fw >= BOOK_RATIO * max(fp, 1) and _dist(p, w) <= MAX_EDIT:
        return "toward-book"
    return None


def _misreadings(p: str, w: str) -> bool:
    """True when every difference between p and w is a known misreading or punctuation."""
    def ok(a, b):
        if frozenset((a, b)) in CONFUSIONS or frozenset((a, b)) in GLYPHS:
            return True
        if all(c in PUNCT for c in a + b):
            return True
        return len(a) == len(b) > 1 and all(ok(x, y) for x, y in zip(a, b))
    if len(p) == len(w) and all(a == b or ok(a, b) for a, b in zip(p, w)):
        return True      # letter by letter: the aligner may split `Congrefs -> Congress` into a
                         # deletion and an insertion rather than one f -> s
    return all(ok(p[i1:i2], w[j1:j2]) for op, i1, i2, j1, j2 in
               SequenceMatcher(None, p, w, autojunk=False).get_opcodes() if op != "equal")


def _clean(tok: str) -> str:
    return tok.rstrip(",;:")


def guard_field(value: str, raw: str, vocab: Counter, field: str):
    """(guarded value, [(rule, before, after)]). Aligns the field's words to the line's words and
    judges every replaced block. Unanchored fields -- no word in common with the line -- are left
    alone: nothing says which printed words they came from."""
    # a comma glues words the OCR ran together (`Hugb,mercht.`); split them before aligning
    ftoks, rtoks = value.split(), re.sub(r",(?=[A-Za-z])", ", ", raw).split()
    fk = [(n, i) for i, t in enumerate(ftoks) if (n := _norm(t))]
    rk = [(n, i) for i, t in enumerate(rtoks) if (n := _norm(t))]
    changes = []
    aligned = [False] * len(ftoks)   # tokens tied to a printed word: never "invented"
    if fk and rk:
        sm = SequenceMatcher(None, [n for n, _ in rk], [n for n, _ in fk], autojunk=False)
        if any(b.size for b in sm.get_matching_blocks()):
            out = list(ftoks)
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op == "equal":
                    for j in range(j1, j2):
                        aligned[fk[j][1]] = True
                if op != "replace":
                    continue
                wrote = " ".join(ftoks[fk[j][1]] for j in range(j1, j2))
                head, tail = j1 == 0, j2 == len(fk)
                if head or tail:
                    # A block at either end of the field is not bounded by an anchor on that
                    # side, so the line words it replaced are unknown. Borrow the 1-3 words next
                    # to the anchor that read most like what the model wrote (`M irgaret` for
                    # `Margaret`), never everything to the start or end of the line.
                    # Any run of 1..k+2 words inside the block, not only those touching the
                    # anchor: `Fleet Jane` <- `Fieet widow Jane` pairs `Fleet` with `Fieet`,
                    # and the dropped `widow` is a status word, not a misread.
                    k = j2 - j1
                    spans = [(a, b) for a in range(i1, i2) for b in range(a + 1, i2 + 1)
                             if b - a <= k + 2] or [(i1, i2)]
                    lo_, hi_ = i1, i2
                    # similarity after folding look-alike characters (`II` vs `11` share none
                    # as written); ties go to the run next to the anchor, then the shorter
                    i1, i2 = max(spans, key=lambda s: (SequenceMatcher(
                        None, _fold(" ".join(rtoks[rk[i][1]] for i in range(*s))),
                        _fold(wrote)).ratio(), s[1] == hi_ if head else s[0] == lo_, s[0] - s[1]))
                    # a name's trailing word with nothing like it in the line was appended, not
                    # misread: leave it to the invented-word pass below rather than pair it with
                    # whatever the book printed next (`Ackerman Sarah` <- `Ackerman widow`)
                    if field == "name" and tail and _invented(wrote, raw):
                        continue
                printed = " ".join(rtoks[rk[i][1]] for i in range(i1, i2))
                # the model's words are IN the line: copied, not rewritten. Covers a marker glued
                # to its number (`h180 E64th` -> `180 E64th`, as gold writes it) and an anchor the
                # aligner took from the wrong copy (`300 E24th h302 E24th`)
                for j in range(j1, j2):
                    aligned[fk[j][1]] = True
                if _in_line(wrote, raw):
                    continue
                if judge(printed, wrote, vocab):
                    continue
                lo, hi = fk[j1][1], fk[j2 - 1][1]
                out[lo:hi + 1] = [_clean(rtoks[rk[i][1]]) for i in range(i1, i2)] + \
                    [None] * (hi + 1 - lo - (i2 - i1))
                changes.append(("restored", wrote, printed))
            aligned = [a for a, t in zip(aligned, out) if t is not None]
            ftoks = [t for t in out if t is not None]
    if field == "name":
        kept = []
        for t, a in zip(ftoks, aligned):
            # only words the alignment could not tie to a printed word: `Chas` for OCR `Clias`
            # is a judged repair, not an invention
            if not a and _invented(t, raw):
                changes.append(("dropped", t, ""))
                continue
            kept.append(t)
        ftoks = kept
    return " ".join(ftoks), changes


def _in_line(wrote: str, raw: str) -> bool:
    """True when `wrote` occurs in the line as whole words, once a residence marker glued to its
    number is split off (`h180` -> `h 180`). Whole words, so `Douglas` is not found in
    `Douglass`."""
    w = [n for n in map(_norm, wrote.split()) if n]
    unglued = re.sub(r"\b([hrb])\.?(\d)", r"\1 \2", re.sub(r"([,;])(?=\S)", r"\1 ", raw), flags=re.I)
    r = [n for n in map(_norm, unglued.split()) if n]
    return bool(w) and any(r[i:i + len(w)] == w for i in range(len(r) - len(w) + 1))


def _invented(text: str, raw: str) -> bool:
    """True when some word of `text` (3+ letters) has no near match anywhere in the line."""
    flat = re.sub(r"[^a-z]", "", raw.lower())
    heads = {re.sub(r"[^a-z]", "", x.lower()) for x in raw.split()}
    for t in text.split():
        w = re.sub(r"[^a-z]", "", t.lower())
        # a printed word that begins it was cut short or abbreviated, not conjured: `Brid`
        if any(len(h) >= 3 and w.startswith(h) for h in heads):
            continue
        if len(w) >= 3 and w not in flat and max(
                (SequenceMatcher(None, w, flat[k:k + len(w)]).ratio()
                 for k in range(max(1, len(flat) - len(w) + 1))), default=0.0) < NAME_MATCH:
            return True
    return False


def guard_record(rec: dict, raw: str, vocab: Counter):
    out, changes = dict(rec), []
    for f in TEXT_FIELDS:
        v = rec.get(f, "")
        if isinstance(v, str) and v.strip():
            nv, ch = guard_field(v, raw, vocab, f)
            if ch:
                out[f] = nv
                changes += [(f, *c) for c in ch]
    return out, changes


def to_yaml(record) -> str:
    """The training serializer's format (train/sft_qwen.py to_yaml), which parse_yaml inverts."""
    q = lambda v: '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "\n".join(f"{f}: {q(_cell(record, f))}" for f in FIELDS)


def guard_file(lines: list, preds: list, vocab: Counter):
    if len(lines) != len(preds):
        raise SystemExit(f"{len(preds)} predictions for {len(lines)} lines -- they must align 1:1")
    out, audit = [], []
    for ln, p in zip(lines, preds):
        g, ch = guard_record(p, ln["raw_line"], vocab)
        out.append(g)
        audit += [(ln.get("context", {}).get("leaf"), ln["raw_line"], *c) for c in ch]
    return out, audit


def _read_jsonl(path: Path) -> list:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def run_volumes(root: Path, run: str) -> dict:
    summary = {}
    for vdir in sorted(d for d in root.iterdir() if d.is_dir()):
        chunks = sorted(vdir.glob("chunk_*.jsonl"))
        pairs = [(c, c.with_name(f"{c.stem}.preds_{run}.txt")) for c in chunks]
        pairs = [(c, p) for c, p in pairs if p.exists()]
        if not pairs:
            continue
        lines = {c: _read_jsonl(c) for c, _ in pairs}
        vocab = volume_vocab([ln for c in lines for ln in lines[c]])
        audit, n = [], 0
        for c, p in pairs:
            guarded, a = guard_file(lines[c], load_pred(str(p), "yaml"), vocab)
            c.with_name(f"{c.stem}.preds_{run}+guard.txt").write_text(
                "\n\n".join(to_yaml(r) for r in guarded) + "\n", encoding="utf-8")
            audit += a
            n += len(guarded)
        with open(vdir / "guard_audit.tsv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["leaf", "raw_line", "field", "rule", "model_wrote", "printed"])
            w.writerows(audit)
        recs = len({(a[0], a[1]) for a in audit})
        summary[vdir.name] = {"records": n, "records_changed": recs,
                              "by_rule": dict(Counter(a[3] for a in audit)),
                              "top": Counter((a[4], a[5]) for a in audit).most_common(12)}
        print(f"{vdir.name}: {recs:,} of {n:,} records changed {summary[vdir.name]['by_rule']}",
              file=sys.stderr)
    return summary


def check_panel(run: str) -> dict:
    """The guard's regression test on the clean-text gold panel: for every gold set with panel
    predictions for `run`, the scored fields the guard fixes and breaks against gold, and
    whole-row EM before and after. `broken` must stay 0 on clean text."""
    from evaluate import metrics, norm, score
    excl = {"spouse_name", "race_designation", "is_business"}
    out = {}
    for pf in sorted((REPO / "results" / "runs" / "scale-runs" / "preds").glob(f"preds_{run}_*.txt")):
        name = pf.stem[len(f"preds_{run}_"):]
        gf = REPO / "data" / f"{name}_eval.jsonl"
        if not gf.exists() or name == "synth_dev":
            continue
        lines = _read_jsonl(gf)
        preds = load_pred(str(pf), "yaml")
        lines = lines[:len(preds)]            # nyu: the panel predicted its first 500 rows
        guarded, _ = guard_file(lines, preds, build_vocab(ln["raw_line"] for ln in lines))
        gold = [ln["record"] for ln in lines]
        fixed = broken = 0
        for g, x, y in zip(gold, preds, guarded):
            for f in FIELDS:
                if f in excl:
                    continue
                gv, xv, yv = (norm(str(r.get(f, "")), False) for r in (g, x, y))
                if xv != yv:
                    fixed += yv == gv
                    broken += xv == gv
        a = metrics(score(gold, preds, False, excl), excl)["row_exact_pct"]
        b = metrics(score(gold, guarded, False, excl), excl)["row_exact_pct"]
        out[name] = {"rows": len(lines), "row_em": a, "row_em_guard": b, "fixed": fixed,
                     "broken": broken}
        print(f"{name:22s} n={len(lines):>4}  row EM {a:5.1f} -> {b:5.1f}  fixed {fixed:>3}  "
              f"broken {broken:>3}", file=sys.stderr)
    t = {k: sum(v[k] for v in out.values()) for k in ("rows", "fixed", "broken")}
    print(f"total: {t}", file=sys.stderr)
    return out


def _self_test() -> int:
    vocab = Counter({"degraw": 813, "cartman": 400, "cartmaa": 1, "george": 900, "goerck": 148,
                     "clk": 8, "elk": 15669, "mhtn": 14281, "pl": 855, "pi": 11340,
                     "margaret": 300})
    g = lambda v, raw, f="address": guard_field(v, raw, vocab, f)[0]
    assert g("h 675 Delaware", "Aarvig Gabriel carp'r h 675 Degraw") == "h 675 Degraw"
    assert g("52 B'way Mthn", "Beales Albert broker 52 B'way Mhtn h 153 Rugby rd") == "52 B'way Mhtn"
    assert g("45 George", "Abraams Isaac, shoemaker, 45 Goerck") == "45 Goerck", "a street, not a name"
    assert g("clk", "Abry Louis E elk h 480 Westminster rd", "occupation_role") == "clk", "repair"
    assert g("h 120 3d pl", '" Hy elk h 120 3d pi') == "h 120 3d pl", "pi -> pl is OCR"
    assert g("cartman", "Belden Samuel, cartmaa Eldridge", "occupation_role") == "cartman"
    assert g("11 Water", "Smith John, II Water") == "11 Water", "two misreadings in one block"
    assert g("h 47 Pearl", "Adams Mary, boardingh 47 Pearl") == "h 47 Pearl", "a glued word split"
    assert g("h 9 Douglas", "Smith John h 9 Douglass") == "h 9 Douglass", "a lost letter is no split"
    assert g("768 7th", "Bundick Elijah R tailor 76 8. 7th, h.") == "76 8. 7th", "fused numbers"
    assert g("11 Murray", "Morton gen Jacob, 1 1 Murray") == "11 Murray", "an OCR-split number"
    # the real-OCR panel's breaks (run 2): long s, glyph punctuation, glued markers, alignment
    assert g("95 Water-street", "Srower N. merchant, 95, Water-flreet") == "95 Water-street"
    assert g("Green Joseph", "Green, Jofeph, taylor, 76 James do.", "name") == "Green Joseph"
    assert g("Howe General", "Howe Genera), 156, Water-ftreet", "name") == "Howe General"
    assert g("101 Willow", "Suliman Gold S. office 44 Wall N. Y.h 10! Willow") == "101 Willow"
    assert g("44 Wall N. Y.", "Silliman Benjamin D. 44 Wall N. Y.h 101 Willow") == "44 Wall N. Y."
    assert g("1701, 86th Bkn", "ii Grant coal 1 Bway 203 hl701, 86th Bkn") == "1701, 86th Bkn"
    assert g("Fleet Jane", "Fieet widow Jane, York n Washington", "name") == "Fleet Jane"
    assert g("Henderson Hugh", "Henderson Hugb,mercht. 24,Qneen-street", "name") == "Henderson Hugh"
    assert g("Inslee Chas F.", "Inslee Clias F. ins. h 47 HeTkimer", "name") == "Inslee Chas F."
    assert g("Farrell Bridget", "Farrell Brid wid. Christy, laundress", "name") == "Farrell Brid"
    assert g("18 Congress do.", "Wetmore. Hezekiah phyfician, 18 Congrefs do.") == "18 Congress do."
    for bad in ("Cherry-ftreec", "William-ltreet", "Wall-itreet", "Oueen-ftreet", "Water-ftrecc"):
        assert g(f"5 {bad.split('-')[0]}-street", f"Smith J. merchant, 5, {bad}") == \
            f"5 {bad.split('-')[0]}-street", bad
    assert g("180 E64th", "-Adolph v pres 15 W28th h180 E64th") == "180 E64th", "glued h marker"
    assert g("9 University pl", "Chester William W. 150 Nassau, h.9 University pl") == \
        "9 University pl", "a marker glued with its period"
    assert g("211 Greene", "Chichester John B. coal, 211 Greene,h. 120 Perry") == "211 Greene"
    assert g("302 E24th", "-Chas shoes 300 E24th h302 E24th") == "302 E24th", "two copies"
    assert g("h 263 Grand", "Gavey Wm. S. realestate, h 623 Grand") == "h 623 Grand", "transposed"
    assert g("Mortimer Rev Benj.", "Mortimer RevBcnj. 104 Fulton", "name") == \
        "Mortimer Rev Benj.", "the OCR glued two words: borrow one"
    assert g("real estate", '" Wm realestate h 412 Grove', "occupation_role") == "real estate"
    assert g("h 480 Westminster dr", "Abry Louis E clk h 480 Westminster rd") == \
        "h 480 Westminster rd"
    assert g("80 Pine", "Arnold D. H. & Co. com. mers. 08 Pine, h. Brooklyn") == "08 Pine"
    # names: a conjured given name goes; an OCR-garbled one is restored, not dropped
    assert g("Ackerman Sarah", "Ackerman widow, 47 Elizabeth", "name") == "Ackerman"
    assert g("Holith Thaddeus", "Hol lith , 26 N. Y.", "name") == "Holith"
    assert g("Achuff Oscar E", "Achuff Ohas E bookkpr h 1443", "name") == "Achuff Ohas E"
    assert g('" Jas W', '" Jas W ins h 576 10th', "name") == '" Jas W', "dittos pass through"
    assert g("Dugan Mary", "Dugan widow Mary of James, 3 Beaver-lane", "name") == "Dugan Mary"
    # an end block borrows only its own width from the line
    assert g("Hart Peer", "Hart Pe er, tailor, 3 Avenue 3", "name") == "Hart Peer", "spacing"
    assert g("Lane Margaret", "Lane M irgaret, widow of Joseph, 201 Varick", "name") == \
        "Lane Margaret", "a split, misread given name repaired toward the book is kept"
    rec = {f: "" for f in FIELDS}
    rec.update(name="Ackerman Sarah", is_business="False", address="47 Elizabeth")
    out, ch = guard_record(rec, "Ackerman widow, 47 Elizabeth", vocab)
    assert out["name"] == "Ackerman" and ch == [("name", "dropped", "Sarah", "")], ch
    text = to_yaml(out)
    from evaluate import parse_yaml
    assert parse_yaml(text)["name"] == "Ackerman" and 'is_business: "False"' in text
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--volumes", help="a data/volumes directory: guard every chunk's predictions")
    ap.add_argument("--run", default="4b-100k")
    ap.add_argument("--lines", help="one JSONL of lines (raw_line per row)")
    ap.add_argument("--preds", help="its YAML predictions")
    ap.add_argument("--out", help="guarded predictions (with --lines/--preds)")
    ap.add_argument("--audit", help="TSV of every change (with --lines/--preds)")
    ap.add_argument("--summary", help="write the --volumes summary as JSON")
    ap.add_argument("--check-panel", metavar="RUN",
                    help="regression test on the clean-text gold panel (e.g. 4b-100k)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.check_panel:
        check_panel(args.check_panel)
        return 0
    if args.volumes:
        s = run_volumes(Path(args.volumes), args.run)
        if args.summary:
            Path(args.summary).write_text(json.dumps(s, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
        return 0
    if not (args.lines and args.preds and args.out):
        ap.error("--volumes, or --lines with --preds and --out")
    lines = _read_jsonl(Path(args.lines))
    guarded, audit = guard_file(lines, load_pred(args.preds, "yaml"),
                                build_vocab(ln["raw_line"] for ln in lines))
    Path(args.out).write_text("\n\n".join(to_yaml(r) for r in guarded) + "\n", encoding="utf-8")
    if args.audit:
        with open(args.audit, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["leaf", "raw_line", "field", "rule", "model_wrote", "printed"])
            w.writerows(audit)
    print(f"{len({(a[0], a[1]) for a in audit})} of {len(guarded)} records changed "
          f"{dict(Counter(a[3] for a in audit))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
