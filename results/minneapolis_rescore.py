#!/usr/bin/env python3
"""
Minneapolis 1900 before and after its gold was checked against the page (2026-11-09).

    python3 results/minneapolis_rescore.py --label 4b-100k \
        --new-preds results/runs/scale-runs/preds/preds_4b-100k-laptop_minneapolis_corrected.txt
    python3 results/minneapolis_rescore.py --label 2b-100k \
        --stored results/runs/scale-runs/preds/preds_2b-100k_minneapolis.txt \
        --new-preds results/runs/scale-runs/preds/preds_2b-100k-laptop_minneapolis_corrected.txt
    python3 results/minneapolis_rescore.py --label v7 \
        --stored results/runs/scale-runs/preds/preds_v7_minneapolis.txt \
        --new-preds results/runs/scale-runs/preds/preds_v7-laptop_minneapolis_corrected.txt

data_prep/minneapolis_page_check.py put back the ditto marks DirCity's transcription dropped, fixed
fourteen misread words and rebuilt one row whose headline it had lost, on all three pages. This
scores, the way panel_error_kinds.py scores the New York panel (abbreviation periods ignored):

  before   the old gold (data/_gold_backup/minneapolis_eval.2026-11-09.jsonl) with the model's
           stored predictions on it (--stored; default the 4b-100k GPU run)
  after    the corrected gold with --new-preds (the same adapter, run on a laptop; one or more
           files in row order, together covering all 230 rows)

per page and over all 230 rows. The rows whose line did not change are a parity check: the laptop
run should reproduce the stored GPU predictions there. Writes results/minneapolis_rescore_<label>.json.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import panel_error_kinds as pk  # noqa: E402

OLD = REPO / "data" / "_gold_backup" / "minneapolis_eval.2026-11-09.jsonl"
NEW = REPO / "data" / "minneapolis_eval.jsonl"
STORED = Path(str(pk.PREDS).format("minneapolis"))
PAGES = {"page 0113": range(0, 76), "page 0362": range(76, 154), "page 0562": range(154, 230)}


def jsonl(p):
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def tally(rows, gold, pred):
    t = pk.tally([("minneapolis", r["raw_line"], g, p) for r, g, p in zip(rows, gold, pred)], 3)
    G, P = [pk.normed(x) for x in gold], [pk.normed(x) for x in pred]
    padded = [i for i in range(len(rows)) if P[i]["name"] != G[i]["name"]
              and P[i]["name"].startswith(G[i]["name"] + " ")]
    keep = ("rows", "exact_normalized", "exact_normalized_pct", "field_accuracy_pct", "field_accuracy_filled_pct",
            "filled_cells", "wrong_rows", "wrong_by_kind", "content_fields")
    out = {k: t[k] for k in keep}
    out["name_padded_rows"] = len(padded)
    return out


def evaluate(gold_path, pred_text):
    """evaluate.py's whole-row EM, verbatim and normalized, as the model card reports it."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "pred.txt"
        p.write_text(pred_text, encoding="utf-8")
        out = subprocess.run([sys.executable, str(REPO / "eval" / "evaluate.py"), "--gold", str(gold_path), "--pred", str(p),
                              "--target", "yaml", "--report-normalized"], capture_output=True, text=True, check=True).stdout
    em = [line for line in out.splitlines() if "whole-row EM" in line]
    # "rows=N  whole-row EM=x%", then the --report-normalized table's "whole-row EM  strict  normalized  delta"
    return {"verbatim": float(em[0].split("=")[-1].rstrip("%")), "normalized": float(em[-1].split()[3])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new-preds", nargs="+", required=True, help="YAML prediction files, in row order, covering all 230 rows")
    ap.add_argument("--new-guarded", nargs="+", help="the same, after postprocess/copy_guard.py")
    ap.add_argument("--stored", default=str(STORED), help="the model's predictions on the old gold (the before)")
    ap.add_argument("--label", required=True, help="the model, for the output file name")
    a = ap.parse_args()

    old_rows, new_rows = jsonl(OLD), jsonl(NEW)
    old_gold, new_gold = pk.load_gold(str(OLD)), pk.load_gold(str(NEW))
    stored = pk.load_pred(a.stored, "yaml")
    new_pred = [p for f in a.new_preds for p in pk.load_pred(f, "yaml")]
    assert len(old_rows) == len(new_rows) == len(stored) == len(new_pred) == 230, len(new_pred)

    same = [i for i in range(230) if old_rows[i]["raw_line"] == new_rows[i]["raw_line"]]
    res = {"parity": {"unchanged_rows": len(same), "laptop_equals_stored_gpu": sum(stored[i] == new_pred[i] for i in same),
                      "differing_rows": [i for i in same if stored[i] != new_pred[i]]}}
    for label, rng in [("all 230", range(230))] + list(PAGES.items()):
        idx = list(rng)
        res[f"before, {label}"] = tally([old_rows[i] for i in idx], [old_gold[i] for i in idx], [stored[i] for i in idx])
        res[f"after, {label}"] = tally([new_rows[i] for i in idx], [new_gold[i] for i in idx], [new_pred[i] for i in idx])
    if a.new_guarded:
        guarded = [p for f in a.new_guarded for p in pk.load_pred(f, "yaml")]
        res["after + copy guard, all 230"] = tally(new_rows, new_gold, guarded)
    res["evaluate.py, after, all 230"] = evaluate(NEW, "".join(Path(f).read_text(encoding="utf-8") for f in a.new_preds))
    res["evaluate.py, before, all 230"] = evaluate(OLD, Path(a.stored).read_text(encoding="utf-8"))
    out = HERE / f"minneapolis_rescore_{a.label}.json"
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    for k, v in res.items():
        if k == "parity":
            print(f"parity: laptop == stored GPU on {v['laptop_equals_stored_gpu']} of {v['unchanged_rows']} unchanged rows")
        elif k.startswith("evaluate"):
            print(f"{k}: {v}")
        else:
            print(f"{k:28} rows {v['rows']:3}  exact {v['exact_normalized_pct']:5.1f}%  fields {v['field_accuracy_pct']['ALL']:5.1f}% "
                  f"(non-blank {v['field_accuracy_filled_pct']['ALL']:5.1f}%)  padded names {v['name_padded_rows']}")
    print("wrote", out.relative_to(REPO))


if __name__ == "__main__":
    main()
