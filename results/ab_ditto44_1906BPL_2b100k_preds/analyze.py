#!/usr/bin/env python3
"""Analyse the powered 44-vs-" paired run, exactly as pre-registered. No metric switching."""
import json, math, re, sys
sys.path.insert(0, "/Users/joshhadro/github/city-directory-extraction/postprocess")
from resolve_dittos import load_records, FIELDS

SP = "/private/tmp/claude-501/-Users-joshhadro-github-city-directory-extraction/465fc10b-b771-4002-85e3-3f0b879736fa/scratchpad"
LEX = set(json.load(open(f"{SP}/occ_lexicon.json")))
LEX |= {"elk", "eom", "lah", "earp", "tailoi"}          # pre-registered OCR variants

TOK = re.compile(r"[^A-Za-z’']+")


def has_occ(raw):
    return any(t.lower() in LEX for t in TOK.split(raw))


def swallowed(raw, rec):
    return has_occ(raw) and not rec["occupation_role"].strip()


def binom_exact_two_sided(b, c):
    """McNemar exact: binomial(b, b+c, 0.5), two-sided by doubling the smaller tail."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main():
    A = load_records(preds_path=f"{SP}/predsPowA.txt")
    B = load_records(preds_path=f"{SP}/predsPowB.txt")
    rawA = [json.loads(l)["raw_line"] for l in open(f"{SP}/powA_raw.jsonl")]
    rawB = [json.loads(l)["raw_line"] for l in open(f"{SP}/powB_norm.jsonl")]
    n = min(len(A), len(B), len(rawA))
    print(f"n = {n} paired rows (arm A raw `44`, arm B substituted `\"`)\n")

    sA = [swallowed(rawA[i], A[i]) for i in range(n)]
    sB = [swallowed(rawB[i], B[i]) for i in range(n)]
    both = sum(1 for i in range(n) if sA[i] and sB[i])
    b = sum(1 for i in range(n) if sA[i] and not sB[i])       # A swallows, B does not
    c = sum(1 for i in range(n) if sB[i] and not sA[i])       # B swallows, A does not
    neither = n - both - b - c
    p = binom_exact_two_sided(b, c)

    print("PRIMARY — occupation swallow (pre-registered)")
    print(f"  swallowed in BOTH arms      : {both}")
    print(f"  swallowed in A only (44)    : {b}   <- 44 hurts")
    print(f"  swallowed in B only (\")     : {c}   <- \" hurts")
    print(f"  neither                     : {neither}")
    print(f"  rate A = {(both+b)/n:.2%}   rate B = {(both+c)/n:.2%}")
    print(f"\n  McNemar exact (two-sided) on {b} vs {c} discordant pairs: p = {p:.4f}")
    verdict = ("NORMALIZE AT INGEST" if p < 0.05 and b > c else
               "NOT ESTABLISHED — keep it downstream only")
    print(f"  DECISION (pre-registered rule): {verdict}")

    OTHER = [f for f in FIELDS if f != "name"]
    other = [i for i in range(n) if any(A[i][f] != B[i][f] for f in OTHER)]
    namediff = sum(1 for i in range(n) if A[i]["name"] != B[i]["name"])
    print(f"\nSECONDARY (not decision-bearing)")
    print(f"  differ in `name`            : {namediff}/{n}")
    print(f"  differ in a non-name field  : {len(other)}/{n} ({len(other)/n:.1%})")
    fc = {}
    for i in other:
        for f in OTHER:
            if A[i][f] != B[i][f]:
                fc[f] = fc.get(f, 0) + 1
    print(f"  fields that move            : {fc}")

    print("\n  discordant rows where 44 swallowed and \" did not:")
    for i in range(n):
        if sA[i] and not sB[i]:
            print(f"    A: {rawA[i][:64]!r}")
            print(f"       name={A[i]['name']!r} occ={A[i]['occupation_role']!r}")
            print(f"       -> name={B[i]['name']!r} occ={B[i]['occupation_role']!r}")
    if c:
        print("\n  discordant the OTHER way (\" swallowed, 44 did not):")
        for i in range(n):
            if sB[i] and not sA[i]:
                print(f"    {rawA[i][:64]!r}")
                print(f"       A name={A[i]['name']!r} occ={A[i]['occupation_role']!r}")
                print(f"       B name={B[i]['name']!r} occ={B[i]['occupation_role']!r}")

    json.dump({"n": n, "both": both, "a_only": b, "b_only": c, "neither": neither,
               "mcnemar_exact_p": p, "verdict": verdict,
               "nonname_diff": len(other), "fields_moved": fc},
              open("/Users/joshhadro/github/city-directory-extraction/results/"
                   "ab_ditto44_1906BPL_2b100k.json", "w"), indent=2)
    print("\nwrote results/ab_ditto44_1906BPL_2b100k.json")


if __name__ == "__main__":
    main()
