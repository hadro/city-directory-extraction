# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "gliner>=0.2.27",
# ]
# ///
"""
GLiNER baseline predictor for the city-directory extractor.

A cheap, span-based ALTERNATIVE to the Qwen SFT: the original urchade/GLiNER (v0.2.27 --
Apache-2.0, ~200-340M DeBERTa encoder, CPU-servable, no fine-tune required) extracts the
schema fields zero-shot, which we assemble into one record per line and serialize as the SAME
pipe rows train/sft_qwen.py emits. Score it with the existing harness:

    # produce predictions (one pipe row per gold line, same order)
    python3 eval/gliner_baseline.py --gold data/nyu_eval.jsonl --out preds.gliner.txt
    # ...or no local install needed:
    #   uv run eval/gliner_baseline.py --gold data/nyu_eval.jsonl --out preds.gliner.txt
    python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred preds.gliner.txt

    python3 eval/gliner_baseline.py --self-test     # assembly logic only; stdlib, no model

Why this is a BASELINE, not the plan's headline model (see docs/plan.md):
* GLiNER is EXTRACTIVE -- it labels spans that appear verbatim in the line. That fits 7/8
  fields (values are stored as-printed), with two seams:
    - `is_business` isn't a span -> we set it with the same heuristic the data converters use.
    - inherited surnames aren't on the continuation line ("Jacob H" -> "Cook Jacob H"); a span
      model can't emit the absent "Cook". Carry the run surname into `raw_line` upstream if you
      need it (the harvest_minneapolis.py surname logic), or accept the lower `name` recall here.
* Multi-person lines: this flat baseline takes the top-scoring span per field (these dialects
  are one-person-per-line). GLiNER-relex (v0.2.26) is the refinement that BINDS fields to the
  right person -- a natural next step if a denser source needs it.

Default model is English; for the French FTD transfer eval pass --model urchade/gliner_multi-v2.1.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional

# Must match eval/evaluate.py + data_prep/synth_persons.py FIELDS (and pipe serialization).
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

# Zero-shot GLiNER labels -> our schema fields. Natural-language labels help GLiNER's zero-shot
# head; order is the prompt order. `is_business` is derived, not labeled (see below).
LABEL2FIELD = {
    "person name": "name",
    "spouse": "spouse_name",
    "race designation": "race_designation",
    "occupation": "occupation_role",
    "employer": "employer",
    "address": "address",
    "home address": "home_address",
}

# Same business heuristic as the data_prep converters, applied to the extracted name.
_BIZ = re.compile(r"&|\bCo\b|\bBros\b|\bSons\b|\bestate of\b", re.IGNORECASE)


def _cell(record, f):
    """Mirror eval/evaluate.py._cell so scoring lines up (bool is_business -> 'True'/'False')."""
    v = record.get(f, "")
    return ("True" if v else "False") if isinstance(v, bool) else (v or "")


def to_pipe(record) -> str:
    return "|".join(_cell(record, f) for f in FIELDS)


def assemble_record(spans, context: Optional[dict] = None) -> dict:
    """spans: list of {label, text, score} from GLiNER -> one union-schema record.
    Top-scoring span wins each field; is_business is derived from the assembled name."""
    best: dict = {}                               # field -> (text, score)
    for s in spans:
        field = LABEL2FIELD.get(s.get("label", ""))
        text = (s.get("text") or "").strip()
        score = float(s.get("score", 1.0))
        if not field or not text:
            continue
        if field not in best or score > best[field][1]:
            best[field] = (text, score)
    rec = {f: "" for f in FIELDS}
    for f, (text, _) in best.items():
        rec[f] = text
    rec["is_business"] = bool(rec["name"] and _BIZ.search(rec["name"]))
    return rec


def predict(model, examples, threshold: float):
    """Yield an assembled record per example, in input order (the harness needs same order)."""
    labels = list(LABEL2FIELD.keys())
    for ex in examples:
        spans = model.predict_entities(ex["raw_line"], labels, threshold=threshold)
        yield assemble_record(spans, ex.get("context"))


# --- offline self-test: exercises assembly + serialization with NO model / heavy deps ---------
SELF_TEST = [
    ("Smith John, clerk, 12 Pine, h 34 Elm",
     [{"label": "person name", "text": "Smith John", "score": 0.99},
      {"label": "occupation", "text": "clerk", "score": 0.95},
      {"label": "address", "text": "12 Pine", "score": 0.90},
      {"label": "home address", "text": "34 Elm", "score": 0.92}],
     "Smith John|False|||clerk||12 Pine|34 Elm"),
    ("Murphy & Sons, grocers, 5 Main",
     [{"label": "person name", "text": "Murphy & Sons", "score": 0.98},
      {"label": "occupation", "text": "grocers", "score": 0.90},
      {"label": "address", "text": "5 Main", "score": 0.88}],
     "Murphy & Sons|True|||grocers||5 Main|"),
    ("Mary (wid John), b 1231 s 9th",
     [{"label": "person name", "text": "Mary", "score": 0.90},
      {"label": "spouse", "text": "wid John", "score": 0.80},
      {"label": "address", "text": "b 1231 s 9th", "score": 0.85},
      {"label": "address", "text": "1231", "score": 0.40}],          # lower-scoring dup ignored
     "Mary|False|wid John||||b 1231 s 9th|"),
]


def _self_test() -> int:
    for raw, spans, expected in SELF_TEST:
        got = to_pipe(assemble_record(spans))
        print(f"  IN : {raw!r}", file=sys.stderr)
        print(f"  OUT: {got}", file=sys.stderr)
        assert got == expected, f"\n  got     : {got}\n  expected: {expected}"
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", help="eval JSONL ({raw_line, context, record}) to predict on")
    ap.add_argument("--out", default="data/preds_gliner.txt",
                    help="predictions file, one pipe row per gold line (default under git-ignored data/)")
    ap.add_argument("--model", default="urchade/gliner_medium-v2.1",
                    help="GLiNER checkpoint (use urchade/gliner_multi-v2.1 for the French FTD eval)")
    ap.add_argument("--threshold", type=float, default=0.5, help="GLiNER span confidence cutoff")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--self-test", action="store_true", help="check assembly/serialization; no model")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.gold:
        ap.error("--gold is required (or use --self-test)")

    with open(args.gold, encoding="utf-8") as f:
        examples = [json.loads(ln) for ln in f if ln.strip()]
    if args.limit:
        examples = examples[:args.limit]

    from gliner import GLiNER                      # heavy import: only on the real path
    model = GLiNER.from_pretrained(args.model)

    n = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for rec in predict(model, examples, args.threshold):
            out.write(to_pipe(rec) + "\n")
            n += 1

    print(f"wrote {n} predictions ({args.model}) -> {args.out}", file=sys.stderr)
    print(f"score with: python3 eval/evaluate.py --gold {args.gold} --pred {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
