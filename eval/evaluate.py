# /// script
# requires-python = ">=3.9"
# dependencies = ["huggingface_hub"]   # only used to resolve hf:// paths; local files need no network
# ///
"""
Field-level evaluation for the city-directory extractor.

Compares model predictions to a gold JSONL (synth_persons.py or nyu_to_eval.py format)
and reports, per field: exact-match accuracy, and non-empty precision / recall / F1
(so empty-field agreement doesn't inflate the score). Also reports whole-row exact match.

This is the SCORING half — pure Python, no ML deps. Generate predictions however you like
(a fine-tuned model, the Gemini baseline, NuExtract...) as one serialized row per gold line,
in the same order, then:

    python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred preds.pipe.txt
    python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred preds.yaml.txt --target yaml
    python3 eval/evaluate.py --gold data/synth_dev.jsonl --self-test   # sanity-check the harness

"Eval realism" rule (van Strien): score predictions produced the SAME way the model will
actually run (same prompt, same serialization), not training-checkpoint metrics.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# Must match data_prep/synth_persons.py FIELDS
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]


def _cell(record, f):
    v = record.get(f, "")
    return ("True" if v else "False") if isinstance(v, bool) else (v or "")


def to_pipe(record):
    return "|".join(_cell(record, f) for f in FIELDS)


def parse_pipe(line: str) -> dict:
    parts = line.rstrip("\n").split("|")
    parts += [""] * (len(FIELDS) - len(parts))     # tolerate truncated output
    return {f: parts[i].strip() for i, f in enumerate(FIELDS)}


def parse_yaml(block: str) -> dict:
    """First-key-wins. Was last-key-wins, which silently corrupted scores when a model failed to
    stop generating: the block then held the correct record followed by a TRUNCATED second copy,
    and the truncated copy overwrote good values (`"117 Front do"` -> `"11"`, `"shoe-maker"` ->
    `"sh"`). On the v5 run that cost ~12 points of whole-row EM and looked exactly like a model
    regression. The first occurrence is the model's actual answer; anything after it is overrun."""
    rec = {f: "" for f in FIELDS}
    seen = set()
    for ln in block.splitlines():
        m = re.match(r'\s*([a-z_]+):\s*(.*?)\s*$', ln)
        if not (m and m.group(1) in rec and m.group(1) not in seen):
            continue
        seen.add(m.group(1))
        val = m.group(2)
        # UNESCAPE, and only for a genuinely quoted scalar. This is the exact inverse of
        # train/sft_qwen.py to_yaml.q(), which writes '"' + v.replace("\\","\\\\").replace('"','\\"') + '"'.
        # Without it the round trip is ASYMMETRIC: Polk NYC gold keeps the printed ditto marker
        # (a leading double-quote, '" Jno H'), so the training target is  name: "\" Jno H"  and the
        # model reproduces it correctly -- but stripping the outer quotes without unescaping left
        # '\" Jno H', which never matches the gold. That scored 60-90% of the rows in all five NYC
        # Polk volumes as name failures and WAS the "Polk floor" (polk1925 EM 7.5%). Found on the
        # v6 run, 2026-09-01. It has depressed every YAML run since those volumes joined the panel.
        if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
            val = re.sub(r'\\(.)', r'\1', val[1:-1])   # single pass: \" -> " and \\ -> \
        rec[m.group(1)] = val
    return rec


def norm(s: str, strict: bool) -> str:
    s = _cell({}, "") if s is None else str(s)
    if strict:
        return s
    return re.sub(r"\s+", " ", s).strip().rstrip(".").strip().lower()


def score(gold: list, pred: list, strict: bool = False, exclude: Optional[set] = None) -> dict:
    """`exclude` also removes fields from WHOLE-ROW EM — a row must not be marked wrong over a
    field we've decided isn't real ground truth (see metrics())."""
    exclude = exclude or set()
    n = min(len(gold), len(pred))
    per = {f: {"em": 0, "gold_ne": 0, "pred_ne": 0, "correct_ne": 0} for f in FIELDS}
    row_exact = 0
    for i in range(n):
        g = {f: _cell(gold[i], f) for f in FIELDS}
        p = {f: _cell(pred[i], f) for f in FIELDS}
        all_eq = True
        for f in FIELDS:
            gv, pv = norm(g[f], strict), norm(p[f], strict)
            eq = gv == pv
            per[f]["em"] += eq
            if f not in exclude:
                all_eq &= eq
            if g[f].strip():
                per[f]["gold_ne"] += 1
            if p[f].strip():
                per[f]["pred_ne"] += 1
            if g[f].strip() and eq:
                per[f]["correct_ne"] += 1
        row_exact += all_eq
    return {"n": n, "row_exact": row_exact, "per": per}


def metrics(res: dict, exclude: Optional[set] = None) -> dict:
    """Turn the raw score() tallies into a machine-readable metrics dict (used by both the
    printed report and --save, so they can never diverge).

    macro_f1 averages F1 ONLY over fields the gold actually contains (gold_ne > 0) — a field
    absent from this gold (e.g. employer in NYU) isn't a failure, so it shouldn't drag the score
    to 0. micro_f1 pools TP/FP/FN across fields (frequency-weighted overall number). A field that
    is absent from gold but still PREDICTED is flagged 'spurious' so dropping it from macro can't
    hide a hallucination (it still costs precision in micro_f1).

    `exclude` drops fields from scoring ENTIRELY — not counted in macro, micro, whole-row EM, or
    'spurious'. Use it when a gold set has no real ground truth for a field. The motivating case is
    NYU: its source has no race/spouse/business labels at all (only 0/1 flags), so
    nyu_to_eval.py SYNTHESIZES those three with regexes/heuristics. Scoring against them measures
    agreement with our own heuristic, not accuracy — and because the heuristic normalizes while the
    task contract says copy verbatim, a model that got MORE faithful scored WORSE. That misfired
    twice (v2 spouse, v5 race). See docs/GROUND_TRUTH_HANDOFF.md "Derived vs transcribed gold"."""
    exclude = exclude or set()
    n = res["n"] or 1
    per, applic_f1s, spurious = {}, [], []
    tot_correct = tot_pred = tot_gold = 0
    for f in FIELDS:
        if f in exclude:
            per[f] = {"em": None, "p": None, "r": None, "f1": None,
                      "gold_ne": res["per"][f]["gold_ne"], "pred_ne": res["per"][f]["pred_ne"],
                      "applicable": False, "excluded": True}
            continue
        d = res["per"][f]
        prec = d["correct_ne"] / d["pred_ne"] if d["pred_ne"] else 0.0
        rec = d["correct_ne"] / d["gold_ne"] if d["gold_ne"] else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        applicable = d["gold_ne"] > 0
        if applicable:
            applic_f1s.append(f1)
        elif d["pred_ne"]:
            spurious.append(f)                          # never in gold, yet predicted
        tot_correct += d["correct_ne"]; tot_pred += d["pred_ne"]; tot_gold += d["gold_ne"]
        per[f] = {"em": round(100 * d["em"] / n, 1), "p": round(prec, 3), "r": round(rec, 3),
                  "f1": round(f1, 3), "gold_ne": d["gold_ne"], "pred_ne": d["pred_ne"],
                  "applicable": applicable}
    mp = tot_correct / tot_pred if tot_pred else 0.0
    mr = tot_correct / tot_gold if tot_gold else 0.0
    micro = 2 * mp * mr / (mp + mr) if (mp + mr) else 0.0
    out = {"n": res["n"], "row_exact_pct": round(100 * res["row_exact"] / n, 1),
           "macro_f1": round(sum(applic_f1s) / len(applic_f1s), 3) if applic_f1s else 0.0,
           "micro_f1": round(micro, 3), "fields_scored": len(applic_f1s),
           "spurious_fields": spurious, "per_field": per}
    if exclude:
        out["excluded_fields"] = sorted(exclude)      # recorded in --save so a number is never
    return out                                        # silently comparable to an unrestricted one


def _bar(x: float) -> str:
    """5-cell visual bar so good/bad reads at a glance: 0.66 -> '###..'"""
    k = max(0, min(5, round(x * 5)))
    return "#" * k + "." * (5 - k)


def report(res: dict, exclude=None) -> dict:
    m = metrics(res, exclude)
    print(f"\n{'field':<18} {'EM%':>6} {'P':>6} {'R':>6} {'F1':>6}  {'':<5}  gold")
    print("-" * 60)
    for f in FIELDS:
        pf = m["per_field"][f]
        if pf["applicable"]:
            print(f"{f:<18} {pf['em']:>6.1f} {pf['p']:>6.2f} {pf['r']:>6.2f} {pf['f1']:>6.2f}  "
                  f"{_bar(pf['f1'])}  {pf['gold_ne']}")
        elif pf.get("excluded"):
            print(f"{f:<18} {'':>6} {'':>6} {'':>6} {'':>6}  EXCLUDED (no real ground truth; "
                  f"gold_ne={pf['gold_ne']})")
        else:
            tag = f"n/a (spurious: {pf['pred_ne']} pred)" if pf["pred_ne"] else "n/a (not in gold)"
            print(f"{f:<18} {'':>6} {'':>6} {'':>6} {'':>6}  {tag}")
    print("-" * 60)
    print(f"rows={m['n']}  whole-row EM={m['row_exact_pct']:.1f}%")
    print(f"OVERALL  macro-F1={m['macro_f1']:.3f} (over {m['fields_scored']} present fields)   "
          f"micro-F1={m['micro_f1']:.3f}")
    if m["spurious_fields"]:
        print(f"  note: model predicted fields absent from this gold: {', '.join(m['spurious_fields'])}")
    if m.get("excluded_fields"):
        print(f"  note: EXCLUDED from all metrics: {', '.join(m['excluded_fields'])} "
              f"— not comparable to an unrestricted score on this set")
    return m


def save_run(path: str, args, res: dict) -> None:
    """Append one JSON line per run so the comparison table builds itself across runs."""
    rec = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "label": args.label or (os.path.basename(args.pred) if args.pred else ""),
        "gold": args.gold, "pred": args.pred, "strict": bool(args.strict),
        **metrics(res, set(getattr(args, "exclude_fields", "").split(",")) - {""}),
    }
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"saved metrics ({rec['label']}) -> {path}", file=sys.stderr)


def _read_text(path: str) -> str:
    """Read a local path, http(s) URL, or hf://datasets/<repo>/<file>. Mirrors qwen_predict.py's
    loader so the 'score with:' hint it prints (which may reference an hf:// --push-out file) works
    verbatim. The huggingface_hub import is lazy — local files need no network or that dep."""
    if path.startswith("hf://datasets/"):
        from huggingface_hub import hf_hub_download
        parts = path[len("hf://datasets/"):].split("/")
        path = hf_hub_download(repo_id="/".join(parts[:2]), filename="/".join(parts[2:]), repo_type="dataset")
    elif path.startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(path) as r:
            return r.read().decode("utf-8")
    return open(path, encoding="utf-8").read()


def load_gold(path: str) -> list:
    return [json.loads(ln)["record"] for ln in _read_text(path).splitlines() if ln.strip()]


def load_pred(path: str, target: str) -> list:
    text = _read_text(path)
    if target == "yaml":
        blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
        return [parse_yaml(b) for b in blocks]
    return [parse_pipe(ln) for ln in text.splitlines() if ln.strip()]


# WHY VERBATIM STAYS THE SCORE (2026-08-31). `norm()` above already ignores TRAILING periods and
# case, so `clk.` == `clk`. Internal periods stay strict, and that is deliberate:
#   - Convention #1 makes expansion a separate downstream step keyed off style_profiles/. Internal
#     periods are part of what it keys on - `st.` after a trade is a STORE, after a street name it
#     is STREET.
#   - The bar is demonstrably fair: Gemini reproduced the printed form on 52 of 57 affected NYU
#     fields and dropped it 0 times; qwen-v5 kept 3 and dropped 33. That gap is real model quality.
#   - Internal periods are meaning-bearing across the gold: `N. J.`/`R. I.` (132 rows), `h.` = House
#     inside a value (72), `do.` ditto (44), `st.` store-vs-street (22). Relaxing would hide a model
#     that started mangling them.
#   - Relaxing retroactively would require re-scoring every board entry back to v2.
# So: report BOTH, score ONE. The gap is the diagnostic - it showed the trow1884 address F1 of 0.50
# was ~90% a missing period, not a comprehension failure. See docs/HANDOFF.md CYCLE-SIX WORKLIST.
_INNER_DOT = re.compile(r"\.(?=\s)")


def report_normalized(gold, pred, strict, excl, verbatim_res) -> None:
    """Diagnostic: re-score with internal abbreviation periods stripped from BOTH sides."""
    strip = lambda r: {f: _INNER_DOT.sub("", str(_cell(r, f))) for f in FIELDS}
    nres = score([strip(g) for g in gold], [strip(p) for p in pred], strict, excl)
    a, b = metrics(verbatim_res, excl), metrics(nres, excl)
    print()
    print("  punctuation-normalized (DIAGNOSTIC - not saved, not board-comparable):")
    print(f"    {'':14s} {'verbatim':>9s} {'normalized':>11s} {'gap':>8s}")
    for k, lbl in (("macro_f1", "macro-F1"), ("micro_f1", "micro-F1"), ("row_exact_pct", "whole-row EM")):
        av, bv = a[k], b[k]
        print(f"    {lbl:14s} {av:9.3f} {bv:11.3f} {bv - av:+8.3f}")
    print("    large gap = CONVENTION error (fix the generator); small gap = SEMANTIC error.")


def _roundtrip_check(gold: list, target: str) -> int:
    """SERIALIZE THE GOLD AND READ IT BACK. Anything that does not survive is a score the model
    can never earn, no matter how right it is.

    This project has now hit FOUR silent serialization/scoring artifacts, every one of which
    looked exactly like a model failure:
      2026-06-18  eval loaded AutoModelForCausalLM vs training's multimodal class -> adapter
                  silently not applied; NYU macro read 0.358 instead of 0.760.
      2026-08-04  parse_yaml was last-key-wins, so a runaway completion's truncated second copy
                  overwrote good values; ~12 points of whole-row EM.
      2026-09-01  parse_yaml stripped quotes but never UNESCAPED, so the correctly-escaped ditto
                  marker in Polk gold ('" Jno H') could not match; 60-90% of the rows in five
                  volumes, and it read as a "Polk floor" in the model.
      2026-09-01  pipe target: a gold value containing the '|' delimiter is truncated on read.
    The old --self-test compared gold against gold as PYTHON DICTS, so it never exercised a
    serializer at all -- which is precisely why three of the four survived it. This does.

    Returns 0 if the gold survives a round trip in `target`, 1 otherwise (non-fatal for the other
    format, which is reported but does not fail the run)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "train"))
        from sft_qwen import to_yaml                  # the REAL training serializer
    except Exception as e:                            # keep the check honest about what it skipped
        print(f"[self-test] round trip SKIPPED (cannot import train/sft_qwen.to_yaml: {e})",
              file=sys.stderr)
        return 0

    def to_pipe(rec):                                 # what every pipe emitter does
        return "|".join(_cell(rec, f) for f in FIELDS)

    rc = 0
    for fmt, enc, dec in (("yaml", to_yaml, parse_yaml), ("pipe", to_pipe, parse_pipe)):
        bad = []
        for g in gold:
            back = dec(enc(g))
            diff = [f for f in FIELDS if back[f] != _cell(g, f)]
            if diff:
                bad.append((diff[0], _cell(g, diff[0]), back[diff[0]]))
        if not bad:
            print(f"[self-test] {fmt} round trip OK — all {len(gold)} gold rows survive")
            continue
        marker = "FAIL" if fmt == target else "warn"
        print(f"[self-test] {marker}: {fmt} round trip LOSES {len(bad)}/{len(gold)} gold rows — "
              f"these can never be scored correctly", file=sys.stderr)
        for f, want, got in bad[:3]:
            print(f"    {f}: gold={want!r} -> read back {got!r}", file=sys.stderr)
        if fmt == target:
            rc = 1
    return rc


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", required=True, help="gold JSONL ({record:...} per line)")
    ap.add_argument("--pred", default=None, help="predictions file (one serialized row per gold line)")
    ap.add_argument("--target", choices=["pipe", "yaml"], default="pipe")
    ap.add_argument("--strict", action="store_true", help="exact string match (default: case/space/period-insensitive)")
    ap.add_argument("--save", default=None, help="append run metrics as one JSON line to this file "
                    "(e.g. results/scores.jsonl) -> feeds eval/results_table.py")
    ap.add_argument("--label", default=None, help="run label for --save (e.g. gliner-medium, "
                    "gemini-3.1-flash-lite, qwen-0.8b); defaults to the --pred filename")
    ap.add_argument("--exclude-fields", default="",
                    help="comma-separated fields to drop from scoring entirely (macro, micro, "
                         "whole-row EM and 'spurious'). Use where a gold set has no real ground "
                         "truth for a field. REQUIRED FOR NYU: pass "
                         "--exclude-fields spouse_name,race_designation,is_business (those three "
                         "are synthesized by nyu_to_eval.py regexes, not transcribed — see "
                         "docs/GROUND_TRUTH_HANDOFF.md).")
    ap.add_argument("--report-normalized", action="store_true",
                    help="ALSO print a punctuation-normalized score (internal abbreviation periods "
                         "stripped from both sides: 'E. 79th' == 'E 79th'). DIAGNOSTIC ONLY - never "
                         "written by --save and must not go on the board. The gap between the two "
                         "numbers separates CONVENTION error from SEMANTIC error.")
    ap.add_argument("--self-test", action="store_true", help="score gold-vs-gold and a corrupted copy to verify the harness")
    args = ap.parse_args(argv)

    gold = load_gold(args.gold)

    if args.self_test:
        rc = _roundtrip_check(gold, args.target)
        print(f"[self-test] perfect predictions (expect ~100% everywhere), n={len(gold)}")
        report(score(gold, [dict(g) for g in gold], args.strict))
        corrupted = []
        for i, g in enumerate(gold):
            c = dict(g)
            if i % 2 == 0:
                c["occupation_role"] = ""      # blank occupation in half -> recall ~0.5
            corrupted.append(c)
        print("\n[self-test] occupation blanked in half (expect occupation R~0.50):")
        report(score(gold, corrupted, args.strict))
        if rc:
            return rc
        return 0

    if not args.pred:
        ap.error("provide --pred FILE or use --self-test")
    pred = load_pred(args.pred, args.target)
    if len(pred) != len(gold):
        print(f"WARNING: {len(pred)} predictions vs {len(gold)} gold rows; scoring first {min(len(pred), len(gold))}",
              file=sys.stderr)
    excl = set(args.exclude_fields.split(",")) - {""}
    bad = excl - set(FIELDS)
    if bad:
        sys.exit(f"--exclude-fields: unknown field(s) {sorted(bad)}; valid: {FIELDS}")
    # NYU's spouse_name / race_designation / is_business are synthesized by nyu_to_eval.py regexes,
    # not transcribed, in a form the model does not emit — they score a hard 0.00 and cost ~0.20
    # macro for reasons unrelated to the model. Every board entry carries this exclusion, so an
    # unrestricted NYU number is silently not comparable to any of them. This fired for real:
    # hpc/30_eval.sbatch shipped without the flag and wrote 0.608 where 0.817 belonged.
    if "nyu" in os.path.basename(args.gold).lower() and not excl:
        print("WARNING: scoring NYU without --exclude-fields. The board uses "
              "--exclude-fields spouse_name,race_designation,is_business; this number will NOT be "
              "comparable to it (expect ~0.20 lower macro). See docs/GROUND_TRUTH_HANDOFF.md.",
              file=sys.stderr)
    res = score(gold, pred, args.strict, excl)
    report(res, excl)
    if args.report_normalized:
        report_normalized(gold, pred, args.strict, excl, res)
    if args.save:
        save_run(args.save, args, res)          # verbatim only - the normalized pass never saves
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
