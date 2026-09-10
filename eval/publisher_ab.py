#!/usr/bin/env python3
"""Measure what a wrong `[publisher=X]` tag costs, and which trained token is the least-bad
stand-in for a publisher the model has never seen.

Why this exists: the tag is a closed set of 17 tokens (ia_volume_to_jsonl.TRAINED_VOCAB), but the
catalog records real publishers, and ~30 IA rows are `spooner` -- a Brooklyn house the SFT data
never mentions. Those volumes currently fall back to `trow`, which is wrong but trained. Nobody
has measured whether that beats tagging them `spooner` outright (correct, but a token the model
has never conditioned on) or borrowing a trained contemporary like `hearne` or `lain`. Until it
is measured, `--publisher spooner` is a guess wearing the costume of a fix.

There is no Spooner gold to measure on. So instead of guessing at the unmeasurable, this measures
the *cost of a wrong tag* on a volume that HAS gold and is structurally comparable -- mid-century
single-column Brooklyn -- by re-tagging it and re-scoring. `hearne1852` is the natural probe:
`hearne` is in vocabulary, so the correct tag gives a measurable ceiling and every other tag is a
controlled degradation from it. Two readings come out of one sweep:

    how much a wrong-but-trained tag costs at all   (hearne -> trow)
    whether an out-of-vocabulary tag costs more     (trow   -> spooner)

If OOV lands at or above the wrong-but-trained tags, `spooner` is safe to write into the tag and
the fallback should go. If it lands below them, the fallback is right and the open question is
only which trained contemporary to borrow.

Everything but the publisher token is held constant: same lines, same adapter, same greedy
decode, same batch order. The model is loaded once and reused across tags.

    python3 eval/publisher_ab.py --gold data/hearne1852_eval.jsonl \
        --base-model Qwen/Qwen3.5-4B --model ~/Downloads/scale-runs/adapters/4b-100k \
        --target yaml --tags hearne,trow,lain,smith,longworth,spooner

    python3 eval/publisher_ab.py --gold ... --dry-run    # show the prompts, load no model
"""

import argparse
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "data_prep"))

import evaluate as ev                                    # noqa: E402
import qwen_predict as qp                                # noqa: E402
from ia_volume_to_jsonl import TRAINED_VOCAB             # noqa: E402


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def retag(rows, tag):
    """Copy the eval rows with a different publisher in the prompt context. Nothing else moves."""
    out = copy.deepcopy(rows)
    for row in out:
        row.setdefault("context", {})["publisher"] = tag
    return out


def run_tag(net, tok, rows, tag, target, batch_size, max_new_tokens):
    tagged = retag(rows, tag)
    parse = ev.parse_yaml if target == "yaml" else ev.parse_pipe
    preds = [parse(p) for p in qp.predict(net, tok, tagged, target, batch_size, max_new_tokens)]
    gold = [row.get("record", {}) for row in rows]
    return ev.metrics(ev.score(gold, preds)), preds


def save_run(args, rows, tags, truth, results, preds_by_tag, distinct, max_diff, material):
    """Write metrics AND per-tag predictions. Called before any interpretation, unconditionally.

    SCALE_RUNS.md: "Keep the prediction files, not just the adapter... stored predictions let you
    re-score against a metric you think of later, on CPU, in seconds" -- v6/v7 not keeping theirs
    cost a 3.5 h regeneration. This project has now paid for that rule twice more: once by
    writing preds to a scratch dir that did not travel with the result, and once by returning
    early on the null path so a 4.16 h run persisted nothing at all.
    """
    if not (args.save or args.save_preds):
        return
    out = Path(args.save) if args.save else None
    preds_dir = Path(args.save_preds) if args.save_preds else out.with_name(out.stem + "_preds")
    preds_dir.mkdir(parents=True, exist_ok=True)
    for tag in tags:
        (preds_dir / f"preds_{tag}.txt").write_text("\n".join(preds_by_tag[tag]) + "\n",
                                                    encoding="utf-8")
    if out is None:
        print(f"\nwrote {len(tags)} prediction files to {preds_dir}/")
        return
    out.write_text(json.dumps(
        {"gold": args.gold, "n": len(rows), "truth": truth, "model": args.model,
         "base_model": args.base_model, "target": args.target,
         "distinct_outputs": len(distinct), "max_rows_differing": max_diff,
         "material": material, "preds_dir": str(preds_dir),
         "identical_groups": [g for g in distinct.values() if len(g) > 1],
         "results": results}, indent=1), encoding="utf-8")
    print(f"\nwrote {out} and {len(tags)} prediction files to {preds_dir}/")


def _self_test():
    """Pin the materiality guard. This is the logic that was WRONG in the first version: it
    ranked six tags by macro F1 when they had produced two distinct outputs differing on one row
    out of 52, and printed 'drop the fallback' off that. Offline, no model."""
    assert retag([{"raw_line": "x", "context": {"publisher": "trow"}}], "spooner"
                 )[0]["context"]["publisher"] == "spooner", "retag must replace the publisher"
    src = [{"raw_line": "x", "context": {"publisher": "trow"}}]
    assert src[0]["context"]["publisher"] == "trow", "retag must not mutate its input"

    def guard(n_rows, max_diff):
        return max_diff >= max(3, 0.05 * n_rows)

    # The real hearne1852 run: 52 rows, one row differed. Must NOT be called material.
    assert not guard(52, 1), "52 rows / 1 differing is noise and must not be ranked"
    assert not guard(52, 2), "two rows in 52 is still under the floor"
    assert guard(52, 3), "the absolute floor is 3 rows"
    assert not guard(1000, 40), "40/1000 is under the 5% relative floor"
    assert guard(1000, 50), "50/1000 meets the 5% relative floor"

    # Identical outputs must collapse into one group regardless of tag count.
    preds = {"a": ["1", "2"], "b": ["1", "2"], "c": ["1", "3"]}
    distinct = {}
    for t in ("a", "b", "c"):
        distinct.setdefault(tuple(preds[t]), []).append(t)
    assert len(distinct) == 2, "a and b are identical and must group"
    assert ["a", "b"] in distinct.values(), "grouping must name the identical tags"

    # The null path must still persist. This is the case that wrote nothing after 4.16 h of GPU:
    # the save sat downstream of the interpretation, and the interpretation returned early.
    import argparse as _ap
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fake = _ap.Namespace(save=str(Path(td) / "r.json"), save_preds=None, gold="g",
                             model="m", base_model="b", target="yaml")
        preds = {"hearne": ["a"], "trow": ["a"]}          # identical -> the null path
        save_run(fake, [{}], ["hearne", "trow"], "hearne", {"hearne": {}, "trow": {}},
                 preds, {("a",): ["hearne", "trow"]}, 0, False)
        saved = json.loads((Path(td) / "r.json").read_text())
        assert saved["material"] is False, "a null must be recorded as a null, not omitted"
        assert saved["max_rows_differing"] == 0
        for tag in ("hearne", "trow"):
            assert (Path(td) / "r_preds" / f"preds_{tag}.txt").exists(), \
                f"{tag} predictions must be written even when the result is null"

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if argv is not None and "--self-test" in argv or "--self-test" in sys.argv[1:]:
        return _self_test()
    ap.add_argument("--self-test", action="store_true", help="offline; no model")
    ap.add_argument("--gold", required=True, help="eval JSONL ({raw_line, context, record})")
    ap.add_argument("--tags", required=True,
                    help="comma-separated publisher tags to sweep. Include the volume's true "
                         "publisher to get a ceiling to measure the others against.")
    ap.add_argument("--truth", default=None,
                    help="the volume's real publisher (default: the gold file's own context)")
    ap.add_argument("--model", help="fine-tuned checkpoint, or a LoRA adapter with --base-model")
    ap.add_argument("--base-model", default=None)
    ap.add_argument("--target", choices=["pipe", "yaml"], default="yaml")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--limit", type=int, default=0, help="first N rows only (smoke runs)")
    ap.add_argument("--save-preds", default=None, help="directory to write preds_<tag>.txt into")
    ap.add_argument("--save", default=None, help="write the comparison table as JSON")
    ap.add_argument("--dry-run", action="store_true",
                    help="print one prompt per tag and exit; loads no model")
    args = ap.parse_args(argv)

    rows = load_rows(args.gold)
    if args.limit:
        rows = rows[:args.limit]
    tags = [t.strip().lower() for t in args.tags.split(",") if t.strip()]
    truth = (args.truth or (rows[0].get("context", {}).get("publisher") if rows else "")).lower()

    print(f"{args.gold}: {len(rows)} rows | true publisher = {truth or '?'} | "
          f"sweeping {len(tags)} tags", file=sys.stderr)
    for tag in tags:
        note = []
        if tag == truth:
            note.append("TRUE TAG -- ceiling")
        if tag not in TRAINED_VOCAB:
            note.append("OUT OF VOCABULARY -- never trained")
        print(f"  {tag:<12} {'; '.join(note)}", file=sys.stderr)

    if args.dry_run:
        for tag in tags:
            print(f"\n--- {tag} " + "-" * 60)
            print(qp.user_prompt(retag(rows, tag)[0]))
        return 0

    if not args.model:
        ap.error("--model is required unless --dry-run")

    net, tok = qp.load(args.model, args.base_model)

    results, preds_by_tag = {}, {}
    for tag in tags:
        print(f"\n[{tag}] predicting {len(rows)} rows...", file=sys.stderr)
        m, preds = run_tag(net, tok, rows, tag, args.target, args.batch_size, args.max_new_tokens)
        results[tag] = m
        preds_by_tag[tag] = [json.dumps(p, sort_keys=True) for p in preds]
        print(f"[{tag}] row EM {m['row_exact_pct']}%  macro F1 {m['macro_f1']}  "
              f"micro F1 {m['micro_f1']}", file=sys.stderr)

    base = results.get(truth)
    print(f"\n{'tag':<14} {'row EM':>8} {'macro F1':>9} {'micro F1':>9}  "
          f"{'vs true':>8}  note")
    for tag in sorted(tags, key=lambda t: -results[t]["macro_f1"]):
        m = results[tag]
        delta = f"{m['macro_f1'] - base['macro_f1']:+.3f}" if base else "--"
        note = []
        if tag == truth:
            note.append("TRUE")
        if tag not in TRAINED_VOCAB:
            note.append("OOV")
        print(f"{tag:<14} {m['row_exact_pct']:>7}% {m['macro_f1']:>9.3f} {m['micro_f1']:>9.3f}  "
              f"{delta:>8}  {' '.join(note)}")

    # Before ranking anything, ask whether the tag moved the model at all. Ranking six tags by
    # macro F1 is meaningless if they produced the same text: the ordering would be one or two
    # lines of noise dressed up as a finding. Greedy decode makes this an exact check.
    distinct = {}
    for tag in tags:
        distinct.setdefault(tuple(preds_by_tag[tag]), []).append(tag)
    n_rows = len(rows)
    max_diff = max(
        sum(1 for x, y in zip(preds_by_tag[a], preds_by_tag[b]) if x != y)
        for a in tags for b in tags) if len(tags) > 1 else 0

    print(f"\n{len(distinct)} distinct output(s) across {len(tags)} tags; at most "
          f"{max_diff}/{n_rows} rows differ between any two.")
    for outs, group in distinct.items():
        if len(group) > 1:
            print(f"  identical: {', '.join(group)}")

    material = max_diff >= max(3, 0.05 * n_rows)

    # SAVE BEFORE READING, and never behind a branch. The first version returned early on the
    # null path, so a 4.16 h 4B run printed its result and wrote nothing -- the null being
    # exactly the case worth keeping, and the guard added to prevent overclaiming being what
    # discarded it. Persisting the artifact is not part of the interpretation and must not sit
    # downstream of it.
    save_run(args, rows, tags, truth, results, preds_by_tag, distinct, max_diff, material)

    if not material:
        print("\nreading: NO MEASURABLE EFFECT. The publisher tag did not change this model's\n"
              "output on this volume, so the table above ranks noise -- do not read an ordering\n"
              "into it, and do not use it to justify changing the fallback. What this does say is\n"
              "that a wrong tag is cheap here, which is itself the answer to 'how bad is trow on a\n"
              "Spooner volume': on this model, not measurably bad. Before concluding the tag never\n"
              "matters, re-run on a stronger model and on a volume whose publisher style is\n"
              "distinctive -- a null on one 52-row volume is not a null everywhere.")
        return 0

    oov = [t for t in tags if t not in TRAINED_VOCAB]
    trained_wrong = [t for t in tags if t in TRAINED_VOCAB and t != truth]
    if oov and trained_wrong:
        best_oov = max(results[t]["macro_f1"] for t in oov)
        worst_trained = min(results[t]["macro_f1"] for t in trained_wrong)
        best_trained = max(results[t]["macro_f1"] for t in trained_wrong)
        print(f"\nOOV best        {best_oov:.3f}")
        print(f"wrong-but-trained {worst_trained:.3f} .. {best_trained:.3f}")
        print("reading: " + (
            "an OOV tag beats the worst trained tag -- writing the true publisher into the tag "
            "is defensible; drop the fallback."
            if best_oov >= worst_trained else
            "an OOV tag is worse than every wrong-but-trained tag -- keep the fallback, and pick "
            "the stand-in by borrowing the best trained contemporary."))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
