#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Resolve ditto marks in extracted records -- WITHIN-LINE channel only (step 1 of 3).

    python3 postprocess/resolve_dittos.py --records data/polk1933bk_eval.jsonl
    python3 postprocess/resolve_dittos.py --preds data/preds_2b-100k_1906BPL_sample500.txt
    python3 postprocess/resolve_dittos.py --self-test          # offline, stdlib only

The model emits dittos VERBATIM by contract (conventions 11/12 in GROUND_TRUTH_HANDOFF.md), and
that contract is load-bearing: it governs synth_persons.py, all 21 gold volumes and evaluate.py
at once, so resolution has to happen downstream or the panel stops being a measuring stick.
This is the downstream step. It NEVER overwrites a field -- it adds `*_resolved` alongside.

THREE SCOPES, AND ONLY ONE OF THEM IS LINE-LOCAL
------------------------------------------------
Measured across every `data/*_eval.jsonl` in this repo:

  scope                          example              antecedent                   needs order?
  within-line  address->home     `h do`, `h910 do`    the SAME record's `address`  NO   <- HERE
  cross-line   name prefix       `" Jos`, `44 John C` previous entry's surname     yes
  cross-line   address slots     `71 do. do.`         previous line's address      yes

Only the within-line channel is deterministic from one record. It needs no reading order, no
leaf/column boundary handling, no interaction with alpha_run_filter, and it cannot orphan -- so
it is separated from the sequential pass deliberately, not incidentally. The cross-line channels
carry a ~23% dispute rate against an independent check (see the module for step 3); this one does
not, and merging them would hide that difference behind a single accuracy number.

THE FORM INVENTORY IS DRAWN FROM THE CORPUS, NOT FROM MEMORY
------------------------------------------------------------
Every `home_address` ditto in the corpus, by grep rather than by recall:

    x16  home_address='do'      address='3 1-2 Jaggar ave'   `... laundry, 3 1-2 Jaggar ave, h do`
    x1   home_address='910 do'  address='908, 6th av'        `" Mary E (wid Chas E) dairy 908, 6th av h910 do`

Two forms, and the second one matters more than its count: `910 do` is a PARTIAL ditto -- house
number given, street inherited -- so a resolver that only handles the full copy silently drops
the case where the answer is not simply the other field.

**The grep also caught a false positive, which is the point of running it.** `\bdo\b` matches
`12 Do-minick` (nyu_eval: `Drummond Samuel, druggist, 52 Reade, h. 12 Do-minick`) -- Dominick
Street, hyphenated across a column break. A hyphen is a word boundary, so the naive pattern reads
a real address as a ditto and replaces it with a different street entirely. DITTO_TOKEN below
requires the token to be free-standing and not glued to a hyphen. This is the same discipline the
curly-apostrophe post-mortem in HANDOFF.md arrived at: grep the corpus for the character class you
just wrote, before trusting it.

WHAT IS NOT HERE
----------------
The Duncan/early-volume address dittos are a positional SLOT GRAMMAR, not a suffix rule, and they
are cross-line -- so they belong to step 3. Recorded here because the shape was mis-read once:

    13 Warren do.     do. = the street TYPE        ("13 Warren street")
    30 do.            do. = street NAME + type     (inherits "Warren street")
    71 do. do.        TWO independent slots        (row 53 of duncan1794, after "73 Roosevelt-street")
    do.               the ENTIRE address           (row 51, after "Bowery-lane")

`71 do. do.` is the decisive case: one `do.` cannot mean two things, so the slots resolve
separately and a single "strip the trailing do." rule is wrong on 44 of duncan1794's 58 rows.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

# A free-standing ditto word. The ANCHORS are what matter: the pattern is matched against the
# whole stripped field, never searched inside it, so `12 Do-minick` / `14 Dover` / `9 Dodge av`
# cannot match. A `\bdo\b` SEARCH does match `Do-minick`, because a hyphen is a word boundary --
# that is the false positive the corpus grep turned up, and anchoring is the fix.
# Trailing period optional; the corpus prints both `do` and `do.`.
DITTO_TOKEN = re.compile(r"^do\.?$", re.IGNORECASE)

# `910 do` -- a house number, then the ditto. The number keeps its printed form, including the
# fraction and hyphen shapes this corpus uses (`3 1-2`, `18-06`, `10-54`).
NUM_DITTO = re.compile(r"^(?P<num>\d+(?:[ -]\d+)*)\s+do\.?$", re.IGNORECASE)

# Leading house number to strip when inheriting only the STREET half of an address.
# Mirrors the shapes above, plus the optional comma Polk prints (`908, 6th av`).
LEADING_NUM = re.compile(r"^\d+(?:[ -]\d+)*\s*,?\s+")


def street_part(address: str) -> str:
    """The street half of an address -- what a partial ditto (`910 do`) inherits.

    `908, 6th av` -> `6th av`;  `633 E169th` -> `E169th`;  `3 1-2 Jaggar ave` -> `Jaggar ave`.
    An address with no leading number is already all street (`Bowery-lane`), so it passes through.
    """
    return LEADING_NUM.sub("", address.strip()).strip()


def resolve_within_line(rec: dict) -> tuple:
    """Resolve `home_address` against this record's own `address`.

    Returns `(resolved_value, status)`. Status is one of:
      not_ditto      -- the field is absent or is a real address; nothing to do
      resolved       -- full copy (`do` -> the address)
      resolved_part  -- partial (`910 do` -> `910` + the address's street half)
      no_antecedent  -- it IS a ditto, but `address` is empty, so it cannot be resolved

    `no_antecedent` is reported rather than guessed. A ditto with nothing to point at is a real
    signal -- usually a dropped or mis-parsed sibling field -- and inventing a value would put a
    confident wrong address on the record, which is the failure mode this whole pipeline is
    trying not to have.
    """
    home = (rec.get("home_address") or "").strip()
    addr = (rec.get("address") or "").strip()
    if not home:
        return "", "not_ditto"

    if DITTO_TOKEN.match(home):
        return (addr, "resolved") if addr else ("", "no_antecedent")

    m = NUM_DITTO.match(home)
    if m:
        street = street_part(addr)
        if not street:
            return "", "no_antecedent"
        return f"{m.group('num')} {street}", "resolved_part"

    return home, "not_ditto"


def annotate(rec: dict) -> dict:
    """Non-destructive: copy the record, add the resolution and its provenance.

    `home_address` keeps the model's verbatim output. `home_address_resolved` is the expansion,
    and `ditto_status` says how it got there -- so a wrong resolution is inspectable rather than
    baked in. Records that carry no ditto get the fields too (resolved == verbatim), so a
    consumer never has to branch on presence.
    """
    out = dict(rec)
    value, status = resolve_within_line(rec)
    out["home_address_resolved"] = value
    out["ditto_status"] = status
    out["ditto_scope"] = "within_line" if status.startswith("resolved") else ""
    return out


# --------------------------------------------------------------------------------------------
# CROSS-LINE: the name channel (step 3)
#
# 67% of 1906BPL's 199,012 lines are ditto-lead -- only 50,225 carry a surname of their own. So
# this pass decides the `name` field for two thirds of a dense volume, and a wrong antecedent
# poisons a whole run (mean 7.1 rows, p90 15, max 180).
#
# READING ORDER: use hOCR EMISSION order, do not reconstruct columns. Measured on 1906BPL, the
# surname sequence in emission order is 93.6% alphabetically non-decreasing within a leaf, and the
# 6.4% backward jumps run ~2.6 per leaf -- about what legitimate column wraps predict on a
# multi-column page. Emission order IS reading order here. This is also the finding HANDOFF #2
# arrived at from the other side: column detection from hOCR line boxes actively fails, because
# wrapped-line indents make left edges multi-modal. Sorting by leaf is stable, so within-leaf
# emission order survives.
#
# THE CARRY IS NOT FREE, AND THE NUMBERS SAY SO. Walking back to the nearest surname-shaped line
# finds an antecedent for 84.9% of dittos within the leaf and 100% if the carry crosses leaves --
# but "found" is not "correct". Two independent checks each dispute ~20k of the 133,781 dittos:
#
#     cross-leaf carry (structural, page boundary)          20,257
#     carried surname != the leaf's own modal letter        20,179
#     overlap                                                8,953   <- only 28% of the union
#
# They are NOT the same rows. That is the whole reason both are computed: ~31.5k rows (23% of all
# dittos) are disputed by at least one check, and either check alone would miss about half of it.
# Nothing here silently picks a winner -- disputed rows are flagged and the caller decides.

try:                                                   # single source of truth for the sort key
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "data_prep"))
    from alpha_run_filter import first_letter as _first_letter
except Exception:                                      # pragma: no cover - fallback keeps this runnable
    _SORT_KEY_RE = re.compile(r"([A-Za-z])(?:[a-z]{2,}|['’][A-Z][a-z])")

    def _first_letter(raw_line: str):
        w = raw_line.split()[0] if raw_line.split() else ""
        m = _SORT_KEY_RE.match(w)
        return m.group(1).upper() if m else None


def surname_token(raw_line: str):
    """The leading token if it is a real sortable surname, else None.

    Delegates the decision to `alpha_run_filter.first_letter`, which is the anchored rule this
    project already paid for twice: it abstains on `"`, `44` and `do.`, AND on the abbreviated
    given names (`H'y`, `Wm`) that appear where OCR dropped the ditto mark entirely -- 664 lines
    of 1906BPL. Re-deriving it here would mean re-deriving both bugs.
    """
    if _first_letter(raw_line) is None:
        return None
    return raw_line.split()[0]


# Ditto leaders, drawn by grep from 1906BPL's 199,012 lines rather than from memory. Counts:
#   44 (84,053)  “ (44,230)  " (2,478)  ** (1,221)  * (417)  '* (316)  *' (279)
#   — (254)  ‘ (199)  4‘ (133)  ” (91)  4 (1,386)  41 (519)  14 (510)
# `44` is ABBYY's reading of `"` and is the single most common leading token in the book.
# `**` is a FOURTH rendering and appears in none of this repo's existing ditto lists -- it was
# found only by dumping the distribution (`** Edwin eom'l trav h 588 11th` is a real entry).
#
# THE DIGIT FORMS ARE DELIBERATELY NOT DEFAULTED ON except 44. `4`, `41` and `14` are also real
# house numbers, and a line may legitimately begin with one. `44` earns its place on frequency
# (42% of all lines) and because `44 Anna costumes 760 B'way` is documented in two other modules
# as an OCR'd ditto. Use --inventory on a NEW volume before trusting any of this: the forms are a
# property of one OCR engine on one book, not of the corpus.
DITTO_LEADERS = re.compile(r"^(?:44|[\"“”'‘’]+|\*+|['’]\*|\*['’]|4['‘]|〃|—|-|do\.?)$", re.IGNORECASE)


def is_ditto_lead(raw_line: str) -> bool:
    toks = raw_line.split()
    return bool(toks) and bool(DITTO_LEADERS.match(toks[0]))


def inventory(rows, top=30):
    """Report the leading-token distribution for a volume, split by the sort-key rule.

    Run this on any new volume BEFORE a production pass. The ditto glyphs above are what one OCR
    engine produced on one book; a different engine or era prints different garbage, and the cost
    of guessing is a whole run of records attributed to the wrong surname. This is the cheap
    version of the habit the HANDOFF post-mortems keep arriving at: look at the actual characters
    before writing the character class.
    """
    counts = {}
    for raw in rows:
        toks = raw.split()
        tok = toks[0] if toks else ""
        key = "<SURNAME-SHAPED>" if surname_token(raw) else tok
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:top]


def modal_letters(rows):
    """Per-leaf dominant sort letter, and whether the leaf legitimately spans more than one.

    A leaf that straddles a letter transition (end of A, start of B) will hold dittos under the
    minority letter perfectly correctly, so `multi` exists to stop those being reported as errors.
    Threshold 0.15 for the runner-up share; below that a second letter is noise, not a transition.
    """
    counts, out = {}, {}
    for leaf, raw in rows:
        letter = _first_letter(raw)
        if letter:
            counts.setdefault(leaf, {})
            counts[leaf][letter] = counts[leaf].get(letter, 0) + 1
    for leaf, c in counts.items():
        ordered = sorted(c.values(), reverse=True)
        share = ordered[1] / sum(ordered) if len(ordered) > 1 else 0.0
        out[leaf] = (max(c, key=c.get), share > 0.15)
    return out


def resolve_cross_line(rows):
    """Sequential surname carry over `rows` = [(leaf, raw_line), ...] in reading order.

    Yields one dict per row: the verbatim leading token, the resolved surname, and FLAGS. It
    never drops a row and never silently picks between candidates.

    Flags, any of which may be set together:
      cross_leaf      the antecedent came from a previous leaf -- a page boundary was crossed
      letter_conflict the carried surname disagrees with this leaf's own modal letter, on a leaf
                      that does not legitimately span two letters
      orphan          no antecedent exists yet (nothing to carry); resolved is left empty

    Callers should treat `cross_leaf` and `letter_conflict` as review queues, not as errors --
    on 1906BPL they are 15.1% and 15.1% of dittos respectively and overlap only 28%, so together
    they cover ~23% of dittos. That is the honest precision of a carry on this volume, and it is
    the number to drive down with better column handling, not to hide.
    """
    modal = modal_letters(rows)
    prev, prev_leaf = None, None
    for leaf, raw in rows:
        sur = surname_token(raw)
        if sur is not None:
            prev, prev_leaf = sur, leaf
            yield {"leaf": leaf, "raw_line": raw, "lead": sur, "resolved": sur,
                   "status": "not_ditto", "flags": []}
            continue
        if not is_ditto_lead(raw):
            yield {"leaf": leaf, "raw_line": raw, "lead": raw.split()[0] if raw.split() else "",
                   "resolved": "", "status": "not_ditto", "flags": []}
            continue

        lead = raw.split()[0]
        flags = []
        if prev is None:
            yield {"leaf": leaf, "raw_line": raw, "lead": lead, "resolved": "",
                   "status": "orphan", "flags": ["orphan"]}
            continue
        if prev_leaf != leaf:
            flags.append("cross_leaf")
        m = modal.get(leaf)
        if m and not m[1] and prev[0].upper() != m[0]:
            flags.append("letter_conflict")
        yield {"leaf": leaf, "raw_line": raw, "lead": lead, "resolved": prev,
               "status": "resolved", "flags": flags}


# --------------------------------------------------------------------------------------------
# loaders -- mirror eval/evaluate.py so the same files work here without conversion


def parse_yaml_block(block: str) -> dict:
    """Minimal `key: "value"` reader for a qwen_predict.py YAML block.

    Deliberately first-key-wins on duplicates, the mirror of evaluate.py's fix: a runaway
    completion emits a truncated SECOND copy of the record, and last-key-wins silently let that
    copy overwrite correct values (HANDOFF: it cost ~12 points of EM and read as a model
    regression). Nothing here should re-introduce that.
    """
    rec = {f: "" for f in FIELDS}
    seen = set()
    for line in block.splitlines():
        m = re.match(r'^\s*([a-z_]+):\s*"(.*)"\s*$', line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key in rec and key not in seen:
            rec[key] = val.replace('\\"', '"')
            seen.add(key)
    return rec


def load_records(records_path=None, preds_path=None) -> list:
    if records_path:
        return [json.loads(ln)["record"] for ln in open(records_path, encoding="utf-8") if ln.strip()]
    text = open(preds_path, encoding="utf-8").read()
    return [parse_yaml_block(b) for b in re.split(r"\n\s*\n", text) if b.strip()]


# --------------------------------------------------------------------------------------------


def self_test() -> int:
    """Cases drawn from the corpus, NOT invented.

    The HANDOFF post-mortem on the apostrophe regex is explicit about why: a test written from
    imagination confirms the imagined case. `Do-minick` and `910 do` are here because grepping
    the eval files turned them up; neither would have occurred to me.
    """
    fails = []

    def check(label, got, want):
        if got != want:
            fails.append(f"  {label}\n     got  {got!r}\n     want {want!r}")

    # full copy -- boyd1890, the x16 form
    check("full copy",
          resolve_within_line({"address": "3 1-2 Jaggar ave", "home_address": "do"}),
          ("3 1-2 Jaggar ave", "resolved"))
    # polk1925 / polk1933bk / queens1933 all take this path
    check("full copy (polk)",
          resolve_within_line({"address": "633 E169th", "home_address": "do"}),
          ("633 E169th", "resolved"))
    # partial -- polk1917, `h910 do` against `908, 6th av`
    check("partial ditto",
          resolve_within_line({"address": "908, 6th av", "home_address": "910 do"}),
          ("910 6th av", "resolved_part"))
    # THE FALSE POSITIVE the grep caught. Dominick St, hyphenated across a column break.
    check("Do-minick is NOT a ditto",
          resolve_within_line({"address": "52 Reade", "home_address": "12 Do-minick"}),
          ("12 Do-minick", "not_ditto"))
    # ordinary streets that start with the letters d-o must survive untouched
    for street in ("14 Dover", "9 Dodge av", "22 Dougherty"):
        check(f"{street} untouched",
              resolve_within_line({"address": "1 Main", "home_address": street}),
              (street, "not_ditto"))
    # a ditto with nothing to point at is reported, never invented
    check("no antecedent",
          resolve_within_line({"address": "", "home_address": "do"}),
          ("", "no_antecedent"))
    check("no antecedent (partial)",
          resolve_within_line({"address": "", "home_address": "910 do"}),
          ("", "no_antecedent"))
    # empty field
    check("empty", resolve_within_line({"address": "1 Main", "home_address": ""}), ("", "not_ditto"))
    # street_part shapes seen in the corpus
    check("street_part fraction", street_part("3 1-2 Jaggar ave"), "Jaggar ave")
    check("street_part comma", street_part("908, 6th av"), "6th av")
    check("street_part hyphen no", street_part("18-06 Stephen av Rdgwd"), "Stephen av Rdgwd")
    check("street_part no number", street_part("Bowery-lane"), "Bowery-lane")
    # annotate is non-destructive
    a = annotate({"address": "633 E169th", "home_address": "do"})
    check("verbatim preserved", a["home_address"], "do")
    check("resolved added", a["home_address_resolved"], "633 E169th")

    # ---- cross-line, name channel. Lines lifted from 1906BPL and from the assertions in
    # detect_listing_bounds.py, so the two modules cannot drift apart silently.
    check("surname passes", surname_token("Ackerman And'w J foreman h 460 Ralph av"), "Ackerman")
    check("curly apostrophe surname", surname_token("D’Ambra Jos lab h 12 Union"), "D’Ambra")
    for line in ('"        Ann C wid David h 518 Madison',
                 "44       Anna costumes 760 B'way",
                 "do. Ann C wid",
                 "H'y grocer 213 Prince",
                 "Wm elk h 149 Division av"):
        check(f"abstains: {line[:18]}", surname_token(line), None)
    # the four OCR renderings of the same mark, all real lines from the volume
    for line in ('44 John C elk h Webster av n E 3d', '“ Jas W ins h 576 10th',
                 '** Edwin eom’l trav h 588 11th', '" Julius r 131 Av A'):
        check(f"ditto lead: {line[:14]}", is_ditto_lead(line), True)
    check("real entry is not a ditto lead", is_ditto_lead("Ackerman Jos lab h 12 Union"), False)
    check("house number is not a ditto lead", is_ditto_lead("140 Broadway, Borough of Manhattan"), False)

    seq = [(1, "Ackerman And'w J foreman h 460 Ralph av"),
           (1, '"        Ann C wid David h 518 Madison'),
           (1, "44       Anna costumes 760 B'way"),
           (2, '44 Bertha dressmaker h 9 Grand')]        # carries across the leaf boundary
    got = list(resolve_cross_line(seq))
    check("row0 anchors", (got[0]["status"], got[0]["resolved"]), ("not_ditto", "Ackerman"))
    check("row1 resolves", (got[1]["status"], got[1]["resolved"], got[1]["flags"]),
          ("resolved", "Ackerman", []))
    check("row2 resolves", (got[2]["resolved"], got[2]["flags"]), ("Ackerman", []))
    check("row3 flags cross_leaf", (got[3]["resolved"], got[3]["flags"]),
          ("Ackerman", ["cross_leaf"]))
    # a ditto with nothing before it is an orphan, never a guess
    orph = list(resolve_cross_line([(1, '" Ann C wid David h 518 Madison')]))
    check("orphan", (orph[0]["status"], orph[0]["resolved"]), ("orphan", ""))

    if fails:
        print("SELF-TEST FAILED\n" + "\n".join(fails), file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def cross_line_report(lines_path: str, want_inventory: bool, out_path=None) -> int:
    """Run the name carry over a whole volume and report what it did, honestly.

    Prints the two dispute rates side by side rather than a single accuracy number, because on
    1906BPL they disagree about which rows are wrong (28% overlap) and an aggregate would hide
    that. Nothing is written back into a record here -- this stage produces a review queue.
    """
    rows = []
    with open(lines_path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                r = json.loads(ln)
                rows.append((r["context"]["leaf"], r["raw_line"]))
    rows.sort(key=lambda lr: lr[0])                    # stable: emission order survives in-leaf

    if want_inventory:
        print(f"{len(rows):,} lines — leading-token distribution:\n")
        for tok, n in inventory([r for _, r in rows]):
            mark = "  <- ditto?" if tok != "<SURNAME-SHAPED>" and DITTO_LEADERS.match(tok) else ""
            print(f"  {n:>8,}  {tok!r}{mark}")
        return 0

    res = list(resolve_cross_line(rows))
    dittos = [r for r in res if r["status"] in ("resolved", "orphan")]
    cross = [r for r in dittos if "cross_leaf" in r["flags"]]
    conflict = [r for r in dittos if "letter_conflict" in r["flags"]]
    both = [r for r in dittos if len(r["flags"]) >= 2 and "orphan" not in r["flags"]]
    orphan = [r for r in dittos if r["status"] == "orphan"]
    disputed = [r for r in dittos if r["flags"]]

    print(f"{len(rows):,} lines, {len(dittos):,} ditto-lead ({len(dittos)/len(rows):.1%})")
    print(f"  carried to an antecedent : {len(dittos)-len(orphan):,}")
    print(f"  orphan (no antecedent)   : {len(orphan):,}")
    print(f"\n  DISPUTED by at least one check : {len(disputed):,} ({len(disputed)/len(dittos):.1%} of dittos)")
    print(f"    cross_leaf     : {len(cross):,}")
    print(f"    letter_conflict: {len(conflict):,}")
    print(f"    both           : {len(both):,}   <- the two checks are NOT redundant")
    print("\n  sample of clean resolutions:")
    for r in [x for x in dittos if not x["flags"]][:5]:
        print(f"    leaf {r['leaf']:<5} {r['lead']!r:6} -> {r['resolved']!r:14} {r['raw_line'][:44]!r}")
    print("\n  sample of DISPUTED (review queue):")
    for r in disputed[:5]:
        print(f"    leaf {r['leaf']:<5} {r['lead']!r:6} -> {r['resolved']!r:14} {','.join(r['flags'])}")
        print(f"       {r['raw_line'][:66]!r}")

    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            for r in res:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\nwrote {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--records", help="JSONL with a `record` key (any data/*_eval.jsonl)")
    ap.add_argument("--preds", help="qwen_predict.py YAML predictions")
    ap.add_argument("--lines", help="a *_lines.jsonl (raw_line + context.leaf) for the CROSS-LINE pass")
    ap.add_argument("--inventory", action="store_true",
                    help="with --lines: dump the leading-token distribution and exit. Run this on "
                         "any new volume before trusting DITTO_LEADERS.")
    ap.add_argument("--out", help="write annotated records as JSONL")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.lines:
        return cross_line_report(args.lines, args.inventory, args.out)
    if not (args.records or args.preds):
        ap.error("need --records, --preds, --lines or --self-test")

    recs = load_records(args.records, args.preds)
    ann = [annotate(r) for r in recs]

    counts = {}
    for a in ann:
        counts[a["ditto_status"]] = counts.get(a["ditto_status"], 0) + 1
    total = len(ann)
    print(f"{total:,} records")
    for status in ("resolved", "resolved_part", "no_antecedent", "not_ditto"):
        n = counts.get(status, 0)
        if n:
            print(f"  {status:<14} {n:>7,}  ({n/total:.2%})")

    shown = 0
    for a in ann:
        if a["ditto_status"].startswith("resolved") and shown < 8:
            print(f"    {a.get('name','')!r:22} address={a.get('address','')!r} "
                  f"home={a['home_address']!r} -> {a['home_address_resolved']!r}")
            shown += 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            for a in ann:
                fh.write(json.dumps(a, ensure_ascii=False) + "\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
