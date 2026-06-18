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
    rec = {f: "" for f in FIELDS}
    for ln in block.splitlines():
        m = re.match(r'\s*([a-z_]+):\s*"?(.*?)"?\s*$', ln)
        if m and m.group(1) in rec:
            rec[m.group(1)] = m.group(2)
    return rec


def norm(s: str, strict: bool) -> str:
    s = _cell({}, "") if s is None else str(s)
    if strict:
        return s
    return re.sub(r"\s+", " ", s).strip().rstrip(".").strip().lower()


def score(gold: list, pred: list, strict: bool = False) -> dict:
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
            all_eq &= eq
            if g[f].strip():
                per[f]["gold_ne"] += 1
            if p[f].strip():
                per[f]["pred_ne"] += 1
            if g[f].strip() and eq:
                per[f]["correct_ne"] += 1
        row_exact += all_eq
    return {"n": n, "row_exact": row_exact, "per": per}


def metrics(res: dict) -> dict:
    """Turn the raw score() tallies into a machine-readable metrics dict (used by both the
    printed report and --save, so they can never diverge).

    macro_f1 averages F1 ONLY over fields the gold actually contains (gold_ne > 0) — a field
    absent from this gold (e.g. employer in NYU) isn't a failure, so it shouldn't drag the score
    to 0. micro_f1 pools TP/FP/FN across fields (frequency-weighted overall number). A field that
    is absent from gold but still PREDICTED is flagged 'spurious' so dropping it from macro can't
    hide a hallucination (it still costs precision in micro_f1)."""
    n = res["n"] or 1
    per, applic_f1s, spurious = {}, [], []
    tot_correct = tot_pred = tot_gold = 0
    for f in FIELDS:
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
    return {"n": res["n"], "row_exact_pct": round(100 * res["row_exact"] / n, 1),
            "macro_f1": round(sum(applic_f1s) / len(applic_f1s), 3) if applic_f1s else 0.0,
            "micro_f1": round(micro, 3), "fields_scored": len(applic_f1s),
            "spurious_fields": spurious, "per_field": per}


def _bar(x: float) -> str:
    """5-cell visual bar so good/bad reads at a glance: 0.66 -> '###..'"""
    k = max(0, min(5, round(x * 5)))
    return "#" * k + "." * (5 - k)


def report(res: dict) -> dict:
    m = metrics(res)
    print(f"\n{'field':<18} {'EM%':>6} {'P':>6} {'R':>6} {'F1':>6}  {'':<5}  gold")
    print("-" * 60)
    for f in FIELDS:
        pf = m["per_field"][f]
        if pf["applicable"]:
            print(f"{f:<18} {pf['em']:>6.1f} {pf['p']:>6.2f} {pf['r']:>6.2f} {pf['f1']:>6.2f}  "
                  f"{_bar(pf['f1'])}  {pf['gold_ne']}")
        else:
            tag = f"n/a (spurious: {pf['pred_ne']} pred)" if pf["pred_ne"] else "n/a (not in gold)"
            print(f"{f:<18} {'':>6} {'':>6} {'':>6} {'':>6}  {tag}")
    print("-" * 60)
    print(f"rows={m['n']}  whole-row EM={m['row_exact_pct']:.1f}%")
    print(f"OVERALL  macro-F1={m['macro_f1']:.3f} (over {m['fields_scored']} present fields)   "
          f"micro-F1={m['micro_f1']:.3f}")
    if m["spurious_fields"]:
        print(f"  note: model predicted fields absent from this gold: {', '.join(m['spurious_fields'])}")
    return m


def save_run(path: str, args, res: dict) -> None:
    """Append one JSON line per run so the comparison table builds itself across runs."""
    rec = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "label": args.label or (os.path.basename(args.pred) if args.pred else ""),
        "gold": args.gold, "pred": args.pred, "strict": bool(args.strict),
        **metrics(res),
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
    ap.add_argument("--self-test", action="store_true", help="score gold-vs-gold and a corrupted copy to verify the harness")
    args = ap.parse_args(argv)

    gold = load_gold(args.gold)

    if args.self_test:
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
        return 0

    if not args.pred:
        ap.error("provide --pred FILE or use --self-test")
    pred = load_pred(args.pred, args.target)
    if len(pred) != len(gold):
        print(f"WARNING: {len(pred)} predictions vs {len(gold)} gold rows; scoring first {min(len(pred), len(gold))}",
              file=sys.stderr)
    res = score(gold, pred, args.strict)
    report(res)
    if args.save:
        save_run(args.save, args, res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
