#!/usr/bin/env python3
"""Paired comparison of entry_rate on the SAME 500 lines, un-normalized vs normalized.

Aggregate percentages are the weak reading here. These are identical lines, so the informative
number is how many records CHANGED classification and in which direction.
"""
import json, math, sys
sys.path.insert(0, "/Users/joshhadro/github/city-directory-extraction/eval")
sys.path.insert(0, "/Users/joshhadro/github/city-directory-extraction/postprocess")
from entry_rate import fields, is_entry
from resolve_dittos import FIELDS

R = "/Users/joshhadro/github/city-directory-extraction"


def load(p):
    return [b for b in open(p, encoding="utf-8").read().split("\n\n") if b.strip()]


def binom_two_sided(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


old_rows = [json.loads(l) for l in open(f"{R}/data/1906BPL_sample500_eval.jsonl")]
new_rows = [json.loads(l) for l in open(f"{R}/data/1906BPL_sample500_norm_eval.jsonl")]
old_p = load(f"{R}/data/preds_2b-100k_1906BPL_sample500.txt")
new_p = load(f"{R}/data/preds_2b-100k_1906BPL_sample500_norm.txt")
n = len(old_rows)
assert len(new_rows) == len(old_p) == len(new_p) == n, (len(new_rows), len(old_p), len(new_p), n)

oldf = [fields(p) for p in old_p]
newf = [fields(p) for p in new_p]
oe = [is_entry(f) for f in oldf]
ne = [is_entry(f) for f in newf]

gained = [i for i in range(n) if ne[i] and not oe[i]]
lost = [i for i in range(n) if oe[i] and not ne[i]]
p = binom_two_sided(len(gained), len(lost))

print(f"PAIRED entry_rate on the same {n} lines\n")
print(f"  un-normalized : {sum(oe)}/{n} real = {sum(oe)/n:.1%}   (NOT entries {1-sum(oe)/n:.1%})")
print(f"  normalized    : {sum(ne)}/{n} real = {sum(ne)/n:.1%}   (NOT entries {1-sum(ne)/n:.1%})")
print(f"\n  became an entry : {len(gained)}")
print(f"  stopped being   : {len(lost)}")
print(f"  unchanged       : {n - len(gained) - len(lost)}")
print(f"  exact binomial two-sided on {len(gained)} vs {len(lost)}: p = {p:.4f}")

changed_rows = sum(1 for i in range(n)
                   if old_rows[i]["raw_line"] != new_rows[i]["raw_line"])
print(f"\n  (input differed on {changed_rows}/{n} rows; the rest are identical input)")

print("\n  records whose CLASSIFICATION flipped:")
for i in gained + lost:
    tag = "GAINED" if i in gained else "LOST  "
    print(f"    [{tag}] {old_rows[i]['raw_line'][:60]!r}")
    print(f"        old name={oldf[i].get('name','')!r} addr={oldf[i].get('address','')!r} "
          f"home={oldf[i].get('home_address','')!r}")
    print(f"        new name={newf[i].get('name','')!r} addr={newf[i].get('address','')!r} "
          f"home={newf[i].get('home_address','')!r}")

# how much did the records move at all, beyond the entry/not-entry call
FLD = [f for f in FIELDS if f != "name"]
anydiff = sum(1 for i in range(n) if any(oldf[i].get(f, "") != newf[i].get(f, "") for f in FLD))
occ_recovered = sum(1 for i in range(n)
                    if not oldf[i].get("occupation_role") and newf[i].get("occupation_role"))
occ_lost = sum(1 for i in range(n)
               if oldf[i].get("occupation_role") and not newf[i].get("occupation_role"))
print(f"\n  SEPARATELY (what entry_rate does not measure):")
print(f"    records differing in a non-name field : {anydiff}/{n}")
print(f"    occupation_role empty -> populated    : {occ_recovered}")
print(f"    occupation_role populated -> empty    : {occ_lost}")

json.dump({"n": n, "old_real": sum(oe), "new_real": sum(ne),
           "old_not_entry_pct": round(100 * (1 - sum(oe) / n), 2),
           "new_not_entry_pct": round(100 * (1 - sum(ne) / n), 2),
           "gained": len(gained), "lost": len(lost), "binomial_p": p,
           "input_differed_rows": changed_rows, "nonname_field_diff": anydiff,
           "occupation_recovered": occ_recovered, "occupation_lost": occ_lost},
          open(f"{R}/results/entry_rate_1906BPL_norm_vs_prenorm.json", "w"), indent=2)
print("\nwrote results/entry_rate_1906BPL_norm_vs_prenorm.json")
