# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "google-genai>=1.0",
# ]
# ///
"""
Gemini baseline predictor for the city-directory extractor -- the "bar" the fine-tuned small
model must reach (docs/plan.md go/no-go gate).

It asks Gemini the EXACT same question the SFT model is trained on: one OCR directory line ->
one union-schema record, serialized as the same pipe row, scored by the same eval/evaluate.py.
Holding the task + schema + scorer constant and varying only the model is what makes the
GLiNER / Gemini / Qwen numbers comparable.

    export GEMINI_API_KEY=...                       # same key the directory-pipeline uses
    uv run eval/gemini_baseline.py --gold data/nyu_eval.jsonl --limit 500           # YAML (robust) by default
    python3 eval/evaluate.py --gold data/nyu_eval.jsonl --pred data/preds_gemini.txt --target yaml \
        --save results/scores.jsonl --label gemini-3.1-flash-lite

    python3 eval/gemini_baseline.py --self-test     # prompt/parse logic only; stdlib, no API

NOTE on format: pipe is positional, so a model that omits an *empty* field shifts every later
column -- on this NYU set that silently broke ~54% of gemini-3.1-flash-lite's rows. YAML names
each key, so the default here is --target yaml. (This is the plan's §2 pipe-vs-YAML A/B.)

Why NOT the directory-pipeline NER prompts (canonical or per-volume in output/):
* They are PAGE-level (full page + prior-page context) and emit JSON in each VOLUME's *native*
  schema. This benchmark is LINE-level and uses the *union* schema. Feeding Gemini a page/JSON
  prompt would have it answer a different question in a different schema than GLiNER and Qwen --
  an unfair, non-comparable bar, plus JSON-parse + line-alignment noise.
* So we reuse train/sft_qwen.py's SYSTEM_PIPE + user_prompt verbatim (identical task/format),
  and append a compact FIELD GUIDE so Gemini knows the union-schema conventions the SFT model
  learned from data (e.g. NYC folds employer into occupation; address is kept as-printed). The
  per-volume prompts were only ever needed as a *reference* for those conventions, which are
  already pinned in synth_persons.py / nyu_to_eval.py. (A separate "production pipeline quality"
  measurement -- page prompt, native schema, mapped back -- is a different question, not this one.)

Default model = gemini-3.1-flash-lite (the pipeline's DEFAULT_NER_MODEL); override with --model.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Optional

# Must match eval/evaluate.py + train/sft_qwen.py (FIELDS, SYSTEM_PIPE, user_prompt, to_pipe).
FIELDS = ["name", "is_business", "spouse_name", "race_designation",
          "occupation_role", "employer", "address", "home_address"]

# Verbatim from train/sft_qwen.py so Gemini gets the SAME instruction as the fine-tuned model.
SYSTEM_PIPE = (
    "You convert ONE line from a historical US city directory into structured fields. "
    "Output exactly one row of pipe-separated values in this order:\n"
    + "|".join(FIELDS) + "\n"
    "Copy values verbatim from the line. Use True/False for is_business. Leave a field "
    "empty (nothing between the pipes) when the line does not contain it. Output only the row."
)

# Union-schema conventions the SFT model learns from training data; given to Gemini in-prompt so
# the comparison is of capability, not of who-knows-the-schema. Updated 2026-07-19 to the CURRENT
# gold contract (GROUND_TRUTH_HANDOFF conventions + synth_persons.py v2) -- the earlier guide
# taught the stale NYU-era rules (notably "drop the NYC h. label"), penalizing Gemini on the panel.
FIELD_GUIDE = (
    "Field guide:\n"
    "- The line starts with a metadata prefix like '[publisher=trow; year=1913/14]' naming the "
    "directory volume it came from. Use it to interpret the volume's conventions; never copy it "
    "into any field.\n"
    "- name: person or business name as printed (surname-first). A leading surname-repeat "
    "ditto mark stays in name verbatim ('-Michl', '\" Jno H') -- do NOT resolve it to the "
    "surname above. ALL-CAPS entries can be persons, not firms.\n"
    "- is_business: True only when the NAME is a firm ('& Co', 'Bros'); never from typography.\n"
    "- spouse_name: the widow/wife marker as printed ('wid John', 'wid. John', 'widow of John'). "
    "'widow Ann' with no 'of' means Ann is her OWN name (put it in name); spouse_name keeps "
    "the bare marker.\n"
    "- race_designation: period marker as printed ('(c)', \"col'd\", \"(co'd)\"); else empty.\n"
    "- occupation_role: occupation/trade as printed (abbreviations and periods kept; a "
    "work-borough tag like '(Mhn)' stays here).\n"
    "- employer: the institution/company worked at/of, when the line names one (drop the "
    "connecting 'of'); else empty.\n"
    "- address: the printed address verbatim, INCLUDING a leading residency marker "
    "(h/r/b/bds/rms/rear) when it is the line's only address; keep 'do'/'do.' dittos as printed.\n"
    "- home_address: ONLY a second, separate 'h.'-marked home when the line lists two "
    "addresses (that marker itself is dropped)."
)
# Verbatim from train/sft_qwen.py. YAML names every key, so a model that drops an *empty* field
# can't column-shift the rest -- which is exactly how the pipe format loses ~half of Gemini's
# rows here (see docs/plan.md §2). YAML is the robust serialization for generative output.
SYSTEM_YAML = (
    "You convert ONE line from a historical US city directory into structured fields. "
    "Output YAML with exactly these keys: " + ", ".join(FIELDS) + ". "
    "Copy values verbatim; use True/False for is_business; use an empty string for absent "
    "fields. Output only the YAML."
)


def system_for(target: str) -> str:
    return (SYSTEM_YAML if target == "yaml" else SYSTEM_PIPE) + "\n\n" + FIELD_GUIDE


def user_prompt(ex: dict) -> str:
    """Verbatim from train/sft_qwen.py: page-level context is fed in, not predicted."""
    ctx = ex.get("context", {})
    tag = f"[publisher={ctx.get('publisher', '?')}; year={ctx.get('directory_year', '?')}]"
    return f"{tag} {ex['raw_line']}"


def parse_response(text: str, target: str = "pipe") -> str:
    """Extract the serialized record from Gemini's reply (tolerate fences / stray prose).
    pipe -> the single pipe row; yaml -> the non-blank key:value lines as one block."""
    if not text:
        return ""
    t = re.sub(r"^```[a-zA-Z]*\n?|\n?```\s*$", "", text.strip()).strip()
    if target == "yaml":
        return "\n".join(ln for ln in t.splitlines() if ln.strip())
    for line in t.splitlines():
        if "|" in line:
            return line.strip()
    return t.splitlines()[0].strip() if t.splitlines() else ""


def predict(client, model, examples, target, sleep, retries=4):
    """Yield one serialized record per example, in input order (the harness needs same order)."""
    from google.genai import types
    cfg = types.GenerateContentConfig(system_instruction=system_for(target), temperature=0.0)
    for ex in examples:
        text = ""
        for attempt in range(retries):
            try:
                resp = client.models.generate_content(
                    model=model, contents=user_prompt(ex), config=cfg)
                text = resp.text or ""
                break
            except Exception as e:                      # transient API / rate-limit errors
                if attempt == retries - 1:
                    print(f"  ! giving up on a line: {e}", file=sys.stderr)
                else:
                    time.sleep(2 ** attempt)
        yield parse_response(text, target)
        if sleep:
            time.sleep(sleep)


# --- offline self-test: prompt construction + response parsing, NO API / heavy deps -----------
def _self_test() -> int:
    up = user_prompt({"raw_line": "Smith John, clk, 12 Pine, h 34 Elm",
                      "context": {"publisher": "trow", "directory_year": "1860"}})
    assert up == "[publisher=trow; year=1860] Smith John, clk, 12 Pine, h 34 Elm", up
    row = "Smith John|False|||clk||12 Pine|34 Elm"
    cases = [row, f"```\n{row}\n```", f"Here is the row:\n{row}", f"```text\n{row}```"]
    for c in cases:
        got = parse_response(c)
        print(f"  {c!r}\n   -> {got!r}", file=sys.stderr)
        assert got == row, f"\n  got     : {got}\n  expected: {row}"
    assert parse_response("") == "" and parse_response("no pipes here") == "no pipes here"
    # yaml: fences stripped, blank lines dropped -> a clean key:value block (no column shift)
    yblock = 'name: "Smith John"\noccupation_role: "clk"\naddress: "12 Pine"'
    assert parse_response(f"```yaml\nname: \"Smith John\"\n\noccupation_role: \"clk\"\naddress: \"12 Pine\"\n```",
                          "yaml") == yblock
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gold", help="eval JSONL ({raw_line, context, record}) to predict on")
    ap.add_argument("--out", default="data/preds_gemini.txt",
                    help="predictions file, one record per gold line (default under git-ignored data/)")
    ap.add_argument("--model", default="gemini-3.1-flash-lite",
                    help="Gemini model (pipeline default; fallback gemini-3-flash-preview)")
    ap.add_argument("--target", choices=["pipe", "yaml"], default="yaml",
                    help="output format; YAML (default) is robust to dropped empty fields -- "
                         "pipe loses ~half of generative rows to column-shift. Score with the "
                         "matching `evaluate.py --target`.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.0, help="seconds between calls (rate-limit cushion)")
    ap.add_argument("--self-test", action="store_true", help="check prompt/parse logic; no API")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.gold:
        ap.error("--gold is required (or use --self-test)")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set (same key the directory-pipeline uses).")

    with open(args.gold, encoding="utf-8") as f:
        examples = [json.loads(ln) for ln in f if ln.strip()]
    if args.limit:
        examples = examples[:args.limit]

    from google import genai
    client = genai.Client(api_key=api_key)

    sep = "\n\n" if args.target == "yaml" else "\n"     # yaml blocks are blank-line separated
    n = 0
    with open(args.out, "w", encoding="utf-8") as out:
        for rec in predict(client, args.model, examples, args.target, args.sleep):
            out.write(rec + sep)
            n += 1
            if n % 50 == 0:
                print(f"  ... {n}/{len(examples)}", file=sys.stderr)

    print(f"wrote {n} predictions ({args.model}, {args.target}) -> {args.out}", file=sys.stderr)
    print(f"score with: python3 eval/evaluate.py --gold {args.gold} --pred {args.out} --target {args.target}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
