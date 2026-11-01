"""Does a small adapter stop after one record? Usage: stop_test.py <repo> <base model> <adapter> <label>

Two decodings per line, greedy, batch 1:
  card     stop on <|im_end|> or <|endoftext|> (what the model card tells users to pass)
  default  the base model's own generation config (what a user gets passing nothing)
A line is CLEAN when generation ends on a stop token before the token cap, and the text holds
exactly one record (nothing after it). Also scores row exact match against the gold, to show the
adapter is applied."""
import json
import random
import sys
import time
from pathlib import Path

REPO = Path(sys.argv[1])
BASE, ADAPTER, LABEL = sys.argv[2], sys.argv[3], sys.argv[4]
sys.path[:0] = [str(REPO / "eval")]
import torch  # noqa: E402
from evaluate import FIELDS, _cell, norm, parse_yaml  # noqa: E402
from qwen_predict import load, parse_completion, system_for, user_prompt  # noqa: E402

SETS = ["franks1786", "longworth1818", "ogden1839", "doggett1846", "hearne1852", "trowwilson1865",
        "lain1876", "boyd1890", "trow1907", "polk1917", "mb1931", "queens1933"]
CAP = 160
random.seed(7)
examples = []
for s in SETS:
    rows = [json.loads(x) for x in open(REPO / "data" / f"{s}_eval.jsonl") if x.strip()]
    examples += [(s, r) for r in random.sample(rows, 2)]

net, tok = load(ADAPTER, BASE)
im_end = tok.convert_tokens_to_ids("<|im_end|>")
stops_card = [t for t in {im_end, tok.eos_token_id, tok.pad_token_id} if t is not None]
print(f"{LABEL}: generation_config.eos_token_id={net.generation_config.eos_token_id} "
      f"tok.eos={tok.eos_token} im_end={im_end}", file=sys.stderr)

out = {"card": [], "default": []}
t0 = time.time()
for s, ex in examples:
    text = tok.apply_chat_template([{"role": "system", "content": system_for("yaml")},
                                    {"role": "user", "content": user_prompt(ex)}],
                                   tokenize=False, add_generation_prompt=True, enable_thinking=False)
    enc = tok(text, return_tensors="pt").to(net.device)
    for mode in ("card", "default"):
        kw = {"eos_token_id": stops_card} if mode == "card" else {}
        with torch.no_grad():
            g = net.generate(**enc, max_new_tokens=CAP, do_sample=False,
                             pad_token_id=tok.pad_token_id, **kw)
        new = g[0, enc["input_ids"].shape[1]:].tolist()
        stopped = bool(new) and new[-1] in (stops_card if mode == "card" else
                                            ([net.generation_config.eos_token_id]
                                             if isinstance(net.generation_config.eos_token_id, int)
                                             else net.generation_config.eos_token_id or []))
        body = tok.decode(new, skip_special_tokens=True).strip()
        rec = parse_completion(body, "yaml")
        trailing = body[len(rec):].strip() if body.startswith(rec) else body
        gold = ex["record"]
        exact = all(norm(_cell(gold, f), False) == norm(_cell(parse_yaml(rec), f), False) for f in FIELDS)
        out[mode].append({"set": s, "line": ex["raw_line"], "tokens": len(new), "stopped": stopped,
                          "hit_cap": len(new) >= CAP, "trailing": trailing[:120], "exact": exact,
                          "last": tok.decode(new[-1:]) if new else ""})
secs = time.time() - t0
for mode, rows in out.items():
    clean = sum(r["stopped"] and not r["trailing"] for r in rows)
    print(f"{LABEL} [{mode:7s}] clean {clean}/{len(rows)}  hit cap {sum(r['hit_cap'] for r in rows)}  "
          f"median tokens {sorted(r['tokens'] for r in rows)[len(rows) // 2]}  "
          f"row exact {sum(r['exact'] for r in rows)}/{len(rows)}")
    for r in rows:
        if not (r["stopped"] and not r["trailing"]):
            print(f"   not clean: [{r['set']}] {r['line'][:60]!r} tokens={r['tokens']} last={r['last']!r} "
                  f"trailing={r['trailing'][:80]!r}")
print(f"{LABEL}: {len(examples)} lines x 2 decodings in {secs:.0f}s")
json.dump(out, open(Path(__file__).with_name(f"stop_test_{LABEL}.json"), "w"), indent=1)
