#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
A panel on the model's REAL input: the gold records, paired with the line the pipeline actually
produces for each from IA's OCR, instead of the hand-corrected text the panel feeds it.

    python3 eval/ia_panel.py build                   # -> data/iapanel/iapanel_<set>.jsonl + manifest
    python3 eval/ia_panel.py score --run 4b-100k     # after a prediction run over those files
    python3 eval/ia_panel.py --self-test

WHY (the five-volume run, 2026-09-28): on the gold pages inside Mercein, Hearnes and Smith, the
same gold rows score 88 / 80 whole-row EM when the model reads the gold text and 63 / 39 / 12
when it reads IA's line, and the model's output is IDENTICAL wherever the two texts agree. The
panel measures the model on clean text; it cannot see what OCR, segmentation and scoping cost,
and it cannot score an OCR-facing change at all (docs/POST_OCR_CORRECTION.md). This can, with no
new labelling: the survey already verified which dump leaf each gold page is
(`harvest.eval_holdout.evidence`).

`build`: for every labelled gold set whose volume the survey harvested, each gold row is aligned
to the kept lines of its leaf (`data/survey_ocr/<id>_lines.jsonl.gz`, before section scoping, so
front-matter gold is not lost) with eval/volume_run_report.align: fuzzy text, one line or a line
and the next. A matched row becomes an eval row whose raw_line is the pipeline's line and whose
record is the gold record. Unmatched gold rows are not dropped silently: they are the part of the
page the pipeline never delivers, and the manifest counts them.

`score`: whole-row EM and macro-F1 per set on the matched rows, for the IA-input predictions, and,
where the panel has predictions for the same gold rows, the clean-text score beside it. The gap
between the two is what the OCR costs.

TWINS. Where the corpus holds the gold's edition in a second scan (survey_harvest.GOLD_TWINS:
smith1856 in 1857BPL, smith1855 in 1856BPL, hearne1852 in hearnesbrooklync1852unse, ogden1839 in
micro_IABROOKLYN_0016, franks1786 in two Durst reprints, polk1917 -- NYPL gold -- in Trow 1917),
the twin is built as its own set, `<set>__<ident>`, on the same gold rows. The microfilm-vs-book-scan gap on
identical gold is then a measurement, not a guess.

HOLDOUT. Every row carries context.eval_holdout = "gold". These files are for measurement only
and must never feed training.
"""
from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "eval"), str(REPO / "data_prep"), str(REPO / "postprocess")]
from evaluate import FIELDS, load_pred, metrics, norm, score  # noqa: E402
from survey_harvest import gold_page_key  # noqa: E402
from verify_harvest_leakage import page_id  # noqa: E402
from volume_run_report import EXCLUDE, _key, align  # noqa: E402

SIDECARS = REPO / "data_prep" / "survey"
DATA = REPO / "data"
OCR = DATA / "survey_ocr"
PANEL_PREDS = REPO / "results" / "runs" / "scale-runs" / "preds"
MANIFEST = REPO / "results" / "ia_panel_manifest.json"
PANEL_DIR = DATA / "iapanel"
LEAF_WINDOW = 3          # leaves either side of the survey's placement tried for each gold page


def _labelled(rows: list) -> bool:
    """1906BPL_sample500 carries empty records: lines to predict on, not gold."""
    return any(r["record"].get("name") for r in rows)


def gold_leaf(row: dict, jp2_to_leaf: dict, key_to_leaf: dict = None):
    ctx = row.get("context") or {}
    if key_to_leaf and gold_page_key(ctx) in key_to_leaf:
        return key_to_leaf[gold_page_key(ctx)]     # a twin: located by page, IA or NYPL
    img = ctx.get("image")
    if img and img != "?":
        pid = page_id(img)
        if pid[0] == "ia":
            n = int(pid[2])
            return jp2_to_leaf.get(n, n)
    if isinstance(ctx.get("leaf"), int):
        return ctx["leaf"]
    return None


def build_set(ident: str, set_file: str, evidence: list, lines: list, scoped: set):
    gold = [json.loads(x) for x in (DATA / set_file).read_text(encoding="utf-8").splitlines()
            if x.strip()]
    if not _labelled(gold):
        return None, None
    jp2_to_leaf = {e["jp2"]: e["leaf"] for e in evidence if "page" not in e}
    key_to_leaf = {e["page"]: e["leaf"] for e in evidence if "page" in e and e.get("leaf") is not None}
    rows = [({"raw_line": ln["raw_line"], "context": ln["context"]}, None) for ln in lines]
    by_leaf = defaultdict(list)
    for i, ln in enumerate(lines):
        by_leaf[ln["context"]["leaf"]].append(i)
    leaf_of = [gold_leaf(g, jp2_to_leaf, key_to_leaf) for g in gold]
    out, matched = [], {}
    for L in sorted({x for x in leaf_of if x is not None}):
        gi = [i for i, x in enumerate(leaf_of) if x == L]
        # The survey's placement is evidence, not proof: below a 0.5 match it tags both the jp2
        # number and its best guess (hopehenderson1856: jp2 205 -> leaf 207 at 0.4, and 207 opens
        # at `Hallams` where the gold opens at `Haffen`). Take whichever nearby leaf the gold
        # rows actually align to best.
        best = max((align([gold[i] for i in gi], by_leaf.get(c, []), rows)
                    for c in range(L - LEAF_WINDOW, L + LEAF_WINDOW + 1)),
                   key=lambda m: (len(m), sum(r for *_, r in m)))
        for a, c, r in best:
            matched[gi[a]] = (c, r)
    for i, g in enumerate(gold):
        if i not in matched:
            continue
        c, r = matched[i]
        first = lines[c[0]]
        text = " ".join(lines[j]["raw_line"] for j in c)
        ctx = dict(g.get("context") or {})
        ctx.update({"ia_id": ident, "leaf": first["context"]["leaf"],
                    "bbox": first["context"]["bbox"], "page_size": first["context"].get("page_size"),
                    "gold_row": i, "gold_raw_line": g["raw_line"], "match": round(r, 3),
                    "pair": len(c) == 2, "in_scope": (first["context"]["leaf"],
                                                      tuple(first["context"]["bbox"])) in scoped,
                    "eval_holdout": "gold"})
        out.append({"raw_line": text, "context": ctx, "record": g["record"]})
    ratios = [m[1] for m in matched.values()]
    stats = {"volume": ident, "gold_rows": len(gold), "matched": len(out),
             "matched_pct": round(100 * len(out) / len(gold), 1),
             "pairs": sum(r["context"]["pair"] for r in out),
             "identical_text": sum(_key(r["raw_line"]) == _key(r["context"]["gold_raw_line"])
                                   for r in out),
             "in_scope": sum(r["context"]["in_scope"] for r in out),
             "median_match": round(statistics.median(ratios), 3) if ratios else None,
             "leaves_unlocated": sum(x is None for x in leaf_of),
             "unmatched_examples": [gold[i]["raw_line"] for i in range(len(gold))
                                    if i not in matched][:8]}
    return out, stats


def _read_gz(path: Path) -> list:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(x) for x in fh if x.strip()]


def build() -> dict:
    manifest = {}
    for p in sorted(SIDECARS.glob("ia_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        held = ((d.get("harvest") or {}).get("eval_holdout")) or {}
        if not held.get("sets"):
            continue
        ident = p.stem[3:]
        lines_path, scoped_path = OCR / f"{ident}_lines.jsonl.gz", OCR / f"{ident}_listing.jsonl.gz"
        if not lines_path.exists():
            continue
        leaves = {e["leaf"] + k for e in held.get("evidence", []) if e.get("leaf") is not None
                  for k in range(-LEAF_WINDOW, LEAF_WINDOW + 1)} | \
                 {e["jp2"] + k for e in held.get("evidence", [])
                  for k in range(-LEAF_WINDOW, LEAF_WINDOW + 1)}
        lines = [ln for ln in _read_gz(lines_path) if ln["context"]["leaf"] in leaves]
        scoped = ({(ln["context"]["leaf"], tuple(ln["context"]["bbox"])) for ln in
                   _read_gz(scoped_path) if ln["context"]["leaf"] in leaves}
                  if scoped_path.exists() else set())
        for set_file in held["sets"]:
            rows, stats = build_set(ident, set_file, held.get("evidence", []), lines, scoped)
            if rows is None:
                continue
            base = set_file[:-len("_eval.jsonl")]
            # a twin (the same edition in another scan) scores the same gold beside its sibling
            name = f"{base}__{ident}" if held.get("twin_of") else base
            # NOT data/*_eval.jsonl: that glob means "hand-built gold" to survey_harvest,
            # verify_harvest_leakage, survey_twins and make_bundle, and these rows would be
            # mistaken for new gold sets
            PANEL_DIR.mkdir(parents=True, exist_ok=True)
            out = PANEL_DIR / f"iapanel_{name}.jsonl"
            out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                           encoding="utf-8")
            manifest[name] = {**stats, "set": base, "twin_of": held.get("twin_of"),
                              "file": str(out.relative_to(REPO))}
            print(f"{name:22s} {ident:28s} {stats['matched']:>4}/{stats['gold_rows']:<4} "
                  f"({stats['matched_pct']:5.1f}%)  identical text {stats['identical_text']:>4}  "
                  f"pairs {stats['pairs']:>3}  in scope {stats['in_scope']:>4}", file=sys.stderr)
    MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    tot = sum(m["gold_rows"] for m in manifest.values())
    got = sum(m["matched"] for m in manifest.values())
    print(f"\n{len(manifest)} sets, {got:,} of {tot:,} gold rows paired with an IA line "
          f"({100 * got / max(tot, 1):.1f}%) -> {MANIFEST.relative_to(REPO)}", file=sys.stderr)
    return manifest


def _m(gold, pred) -> dict:
    m = metrics(score(gold, pred, False, EXCLUDE), EXCLUDE)
    return {"n": m["n"], "row_exact_pct": m["row_exact_pct"], "macro_f1": m["macro_f1"]}


def _fixed_broken(gold, a, b):
    """Scored fields the guard turned right (fixed) and wrong (broken), a -> b."""
    fixed = broken = 0
    for g, x, y in zip(gold, a, b):
        for f in FIELDS:
            if f in EXCLUDE:
                continue
            gv, xv, yv = (norm(str(r.get(f, "")), False) for r in (g, x, y))
            if xv != yv:
                fixed += yv == gv
                broken += xv == gv
    return fixed, broken


def _load_set(name, m, run, preds_dir):
    rows = [json.loads(x) for x in (REPO / m["file"]).read_text(encoding="utf-8").splitlines()
            if x.strip()]
    out = {}
    for r in (run, run + "+guard"):
        pf = preds_dir / f"iapanel_{name}" / f"chunk_000.preds_{r}.txt"
        if pf.exists():
            p = load_pred(str(pf), "yaml")
            if len(p) != len(rows):
                raise SystemExit(f"{pf}: {len(p)} predictions for {len(rows)} rows")
            out[r] = p
    return rows, out


def score_run(run: str, preds_dir: Path) -> dict:
    """IA-input predictions live where hpc/35_volumes.sbatch writes them:
    <preds_dir>/iapanel_<set>/chunk_000.preds_<run>.txt, and the copy guard's beside them as
    <run>+guard. Per set: whole-row EM on IA input, raw and guarded; the guard's fields fixed and
    broken against gold (its first test on gold it was never tuned on); and the panel's
    clean-text prediction on the same gold rows, raw and guarded. Then each twin against its
    sibling scan, on the gold rows both deliver."""
    from copy_guard import build_vocab, guard_file
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out, loaded = {"sets": {}, "twins": {}}, {}
    for name, m in manifest.items():
        rows, preds = _load_set(name, m, run, preds_dir)
        if run not in preds:
            continue
        loaded[name] = (rows, preds)
        gold = [r["record"] for r in rows]
        res = {"rows": len(rows), "gold_rows": m["gold_rows"], "twin_of": m.get("twin_of"),
               "ia_input": _m(gold, preds[run])}
        if run + "+guard" in preds:
            res["ia_input_guard"] = _m(gold, preds[run + "+guard"])
            res["guard_fixed"], res["guard_broken"] = _fixed_broken(gold, preds[run],
                                                                    preds[run + "+guard"])
        clean = PANEL_PREDS / f"preds_{run}_{m.get('set', name)}.txt"
        if clean.exists():
            src = [json.loads(x) for x in (DATA / f"{m.get('set', name)}_eval.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
            cp = load_pred(str(clean), "yaml")
            cg, _ = guard_file(src, cp, build_vocab(x["raw_line"] for x in src))
            idx = [r["context"]["gold_row"] for r in rows]
            res["clean_text"] = _m(gold, [cp[i] for i in idx])
            res["clean_text_guard"] = _m(gold, [cg[i] for i in idx])
        out["sets"][name] = res
    for name, (rows, preds) in loaded.items():
        base = manifest[name].get("set")
        if not manifest[name].get("twin_of") or base not in loaded:
            continue
        brows, bpreds = loaded[base]
        bi = {r["context"]["gold_row"]: k for k, r in enumerate(brows)}
        both = [(k, bi[r["context"]["gold_row"]]) for k, r in enumerate(rows)
                if r["context"]["gold_row"] in bi]
        gold = [rows[k]["record"] for k, _ in both]
        t = {"microfilm_or_own": base, "twin": name, "both_deliver": len(both),
             "own_delivers": len(brows), "twin_delivers": len(rows),
             "gold_rows": manifest[name]["gold_rows"]}
        for r in (run, run + "+guard"):
            if r in preds and r in bpreds:
                t[f"own_{r}"] = _m(gold, [bpreds[r][b] for _, b in both])
                t[f"twin_{r}"] = _m(gold, [preds[r][k] for k, _ in both])
        out["twins"][name] = t
    return out


def print_score(res: dict, run: str) -> None:
    P = lambda *a: print(*a, file=sys.stderr)
    P(f"{'set':42s} {'n':>4} {'IA':>6} {'IA+g':>6} {'fix':>4} {'brk':>4} {'clean':>6} {'cl+g':>6}")
    for name, r in res["sets"].items():
        c, cg = r.get("clean_text", {}), r.get("clean_text_guard", {})
        P(f"{name:42s} {r['rows']:>4} {r['ia_input']['row_exact_pct']:6.1f} "
          f"{r.get('ia_input_guard', {}).get('row_exact_pct', float('nan')):6.1f} "
          f"{r.get('guard_fixed', 0):>4} {r.get('guard_broken', 0):>4} "
          f"{c.get('row_exact_pct', float('nan')):6.1f} {cg.get('row_exact_pct', float('nan')):6.1f}")
    P("")
    for name, t in res["twins"].items():
        a, b = t.get(f"own_{run}+guard", t.get(f"own_{run}")), t.get(f"twin_{run}+guard", t.get(f"twin_{run}"))
        P(f"{t['microfilm_or_own']:18s} own delivers {t['own_delivers']:>3}  twin {t['twin_delivers']:>3} "
          f"of {t['gold_rows']:>3} | on {t['both_deliver']:>3} rows both deliver, guarded row EM: own "
          f"{a['row_exact_pct']:5.1f}  twin {b['row_exact_pct']:5.1f}   ({name.split('__')[1]})")


def _self_test() -> int:
    ev = [{"jp2": 174, "leaf": 175}]
    g = {"raw_line": "Farden John, 278 Pearl", "context": {
        "image": "0021_micro_IABROOKLYN_0030%2Fmicro_IABROOKLYN_0030_jp2.zip%2F"
                 "micro_IABROOKLYN_0030_jp2%2Fmicro_IABROOKLYN_0030_0174.jp2.jpg"}}
    assert gold_leaf(g, {e["jp2"]: e["leaf"] for e in ev}) == 175, "the verified leaf, not the jp2"
    assert gold_leaf({"context": {"ia_id": "x", "leaf": 9}}, {}) == 9
    assert gold_leaf({"context": {"image": "0021_56855258.jpg"}}, {}, {"nypl:56855258": 688}) == 688
    assert not _labelled([{"record": {"name": ""}}])
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["build", "score"])
    ap.add_argument("--run", default="4b-100k")
    ap.add_argument("--preds-dir", default=str(DATA / "volumes"))
    ap.add_argument("--out", help="score: write the result as JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.cmd == "build":
        build()
    elif args.cmd == "score":
        res = score_run(args.run, Path(args.preds_dir))
        print_score(res, args.run)
        if args.out:
            Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    else:
        ap.error("build or score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
