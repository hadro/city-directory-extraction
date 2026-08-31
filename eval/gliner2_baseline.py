# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "gliner2[local]>=2.0.0",
#   "protobuf",
#   "sentencepiece",
# ]
# ///
"""
GLiNER2 baseline predictor — a REFRESHED FLOOR for the panel. Not a contender.

    uv run eval/gliner2_baseline.py --gold data/lain1876_eval.jsonl --out preds.g2.txt
    python3 eval/evaluate.py --gold data/lain1876_eval.jsonl --pred preds.g2.txt --target pipe

GLiNER2 (`gliner2` 2.0.0, 2026-08-24, Apache-2.0, github.com/fastino-ai/GLiNER2) is a DIFFERENT
lineage from urchade/GLiNER — a schema-driven multi-task extractor rather than a span labeller.
That matters here because `eval/gliner_baseline.py` documents two seams that exist only because
GLiNER1 is span-only (`is_business` isn't a span; inherited surnames aren't in the line). GLiNER2
takes a record schema directly, so it removes those seams and gives a FAIRER floor.

STATUS 2026-08-31: PROBED, MEASURED, DEFERRED until after cycle six. Kept here so the work is not
redone. Nothing from this script is on the board — it was never written to results/scores.jsonl.

MEASURED on lain1876 (n=103 — the same set as the board's `gliner-lain1876` entry):

    | model                            | macro | micro |    EM |
    |----------------------------------|-------|-------|-------|
    | GLiNER1 (board: gliner-lain1876) | 0.331 | 0.546 |  3.9% |
    | gliner2.5-base-v1   (194M)       | 0.421 | 0.608 |  5.8% |
    | gliner2-large-v1    (340M)       | 0.491 | 0.675 |  2.9% |
    | qwen-0.8b-yaml-v5   (fine-tune)  | 0.796 |     — |     — |
    | Gemini 3.1-flash-lite primed     | 0.826 |     — |     — |

So: **+0.09 to +0.16 macro over GLiNER1 — a real floor correction — and still ~0.30 behind the
fine-tune.** Fast and cheap: 103 rows in 18 s on an M2 (MPS), CPU-servable, no fine-tune.

WHY IT PLATEAUS — structural, not tuning. Thresholds 0.5 / 0.3 / 0.15 were flat
(0.421 / 0.420 / 0.417). The larger model lifted `name` 0.78→0.84 and `occupation_role` 0.57→0.69
but not the field that decides the score:

  * `address` F1 **0.12** (base) / **0.27** (large), whole-row EM under 6%. It cannot split work
    from home on the `h` marker:
        raw : Gibbs John, painter, 870 1/2 De Kalb av. h 343 Kosciusko
        gold: address='870 1/2 De Kalb av.'   home_address='343 Kosciusko'
        pred: address='870 1/2 De Kalb av. h 343 Kosciusko'   home_address=''
  * `spouse_name` F1 0.11 — drops the `wid.` marker the conventions keep verbatim (conv #9).
  * It also drops the marker from a lone `h`-address, which conv #8a keeps.

`evaluate.py --report-normalized` shows a **+0.000 gap**, so — unlike the qwen directional-period
problem — none of this is a convention artifact. It is genuine failure to segment. Splitting on
`h`, keeping `wid.` verbatim, the lone-`h` rule: these are volume-specific conventions a fine-tune
absorbs from 100k examples and a zero-shot schema model has no way to guess.

WHEN YOU COME BACK TO IT:
  1. Add `gliner2-large-v1` as the floor column, replacing or beside `gliner-medium`. A more honest
     floor strengthens the fine-tune's value claim rather than weakening it.
  2. Run it across the whole panel in one pass — it is minutes on CPU, no cluster time.
  3. **The schema below was written quickly. 0.49 is NOT GLiNER2's ceiling.** Before concluding
     anything, try describing the `h` split explicitly, and try `entity_attributes`/`relations`
     (see `Schema` in the package) instead of one flat structure — binding fields to a person is
     exactly what the flat form fails at.
  4. `gliner` (urchade) is also at 0.2.28 now; `eval/gliner_baseline.py` pins >=0.2.27. Minor.

Repro notes: needs its own venv (it pulls transformers 4.57.x, which CANNOT load Qwen3.5 — do not
install it next to the eval stack). `protobuf`/`sentencepiece` are required for the DeBERTa
tokenizer and are NOT pulled by `gliner2[local]`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Reuse the repo's own field order, pipe serialization and is_business heuristic so the two GLiNER
# baselines are scored on identical terms.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gliner_baseline import FIELDS, to_pipe, _BIZ  # noqa: E402

MODEL = "fastino/gliner2.5-base-v1"      # 194M, recommended English; -large-v1 (340M) scores higher


def build_schema():
    from gliner2 import Schema
    return (Schema().structure("entry")
            .field("name", dtype="str",
                   description="person or business name, surname first, exactly as printed")
            .field("occupation_role", dtype="str", description="trade or occupation")
            .field("employer", dtype="str", description="employer name if given")
            .field("address", dtype="str", description="work or primary street address")
            .field("home_address", dtype="str",
                   description="home address, the part following the h marker")
            .field("spouse_name", dtype="str",
                   description="widow marker with husband name, e.g. wid. John")
            .field("race_designation", dtype="str",
                   description="race marker such as (c) or col'd")
            .build())


def _first(v) -> str:
    if isinstance(v, list):
        return (v[0] if v else "").strip()
    return v.strip() if isinstance(v, str) else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", help="gold jsonl (not needed for --self-test)")
    ap.add_argument("--out", help="pipe rows, one per gold line, same order")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="measured flat over 0.15-0.5 on lain1876; recall is not the limiter")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--self-test", action="store_true",
                    help="assembly logic only; stdlib, no model download")
    args = ap.parse_args(argv)

    if args.self_test:
        rec = {f: "" for f in FIELDS}
        rec["name"] = "Smith & Co."
        rec["is_business"] = bool(_BIZ.search(rec["name"]))
        row = to_pipe(rec)
        assert row.split("|")[0] == "Smith & Co.", row
        assert row.split("|")[1] == "True", row          # & Co. -> business
        assert _first(["a", "b"]) == "a" and _first([]) == "" and _first("x") == "x"
        print("[self-test] assembly OK")
        return 0

    if not (args.gold and args.out):
        ap.error("--gold and --out are required (or use --self-test)")

    import torch
    from gliner2 import AutoExtractor

    model = AutoExtractor.from_pretrained(args.model)
    dev = "mps" if torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(dev)
    print(f"  {args.model} on {dev}", file=sys.stderr)

    rows = [json.loads(ln) for ln in open(args.gold, encoding="utf-8") if ln.strip()]
    if args.limit:
        rows = rows[:args.limit]
    outs = model.batch_extract([r["raw_line"] for r in rows], build_schema(),
                               batch_size=args.batch_size, threshold=args.threshold)

    n = 0
    with open(args.out, "w", encoding="utf-8") as fh:
        for o in outs:
            entry = (o.get("entry") or [{}])[0]
            rec = {f: ("" if f != "is_business" else False) for f in FIELDS}
            for f in FIELDS:
                if f != "is_business":
                    rec[f] = _first(entry.get(f, []))
            rec["is_business"] = bool(rec["name"] and _BIZ.search(rec["name"]))
            fh.write(to_pipe(rec) + "\n")
            n += 1
    print(f"  wrote {n} predictions ({args.model}) -> {args.out}", file=sys.stderr)
    print(f"score with: python3 eval/evaluate.py --gold {args.gold} --pred {args.out} "
          f"--target pipe", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
