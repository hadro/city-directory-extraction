#!/usr/bin/env python3
"""
Does NYPL Space/Time's CC0 parse of Doggett 1850/51 agree with NYU's CC-BY-SA-NC one?

The NYU external eval set (data/nyu_eval.jsonl, data_prep/nyu_to_eval.py) is the reason the eval
panel is gated. NYU's release continues Space/Time's 2017 extraction of the same NYPL volume
(4adf9ec0-317a-0134-03ad-00505686a51c) with the same CRF parser, over a later OCR run. If the two
agree on the four fields NYU is scored on (name, occupation_role, address, home_address), a CC0
twin built from Space/Time can replace it.

Pairs lines by NYPL page uuid, then by text: identical first, then the closest unpaired line on
the page (difflib ratio >= NEAR). Space/Time records map through nyu_to_eval's own rules.

    python3 results/spacetime_nyu_agreement.py     # -> results/spacetime_nyu_agreement.json

Inputs (gitignored):
    data/spacetime/doggett1850_51.objects.ndjson   grep 4adf9ec0 of city-directories.objects.ndjson
        from http://s3.amazonaws.com/spacetime-nypl-org/datasets/city-directories/city-directories.zip
        (sha256 5f3b781b7170ba2fe7bc321d63337137d329f171b75662cf2e3ccd7bb156db2c, 984,791,909 bytes)
    data/nyu_1850_head.ndjson                      NYU's 1850 file, whole (78,016 lines)
    data/nyu_eval.jsonl                            the 3,000-row eval set built from it
"""
import collections
import difflib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "data_prep"))
from nyu_to_eval import _locations, _scores_ok, to_record  # noqa: E402

NEAR = 0.9
SCORED = ["name", "occupation_role", "address", "home_address"]


def detok(s):
    """Space/Time stores its parser's tokens joined by spaces (`244 W . 18th`, `Child , Day & Co`);
    NYU closes them up. Close them here, so the comparison is of labels and not of spacing."""
    return re.sub(r"\s+([.,])", r"\1", s or "").strip()


def st_record(d):
    """A Space/Time object in the union schema's four scored fields, by nyu_to_eval's rules."""
    address, home = _locations(d["data"])
    return {"name": detok(d.get("name")), "occupation_role": detok(d["data"].get("occupation")),
            "address": detok(address), "home_address": detok(home)}


def agreement(pairs):
    n = len(pairs)
    out = {"n": n}
    if not n:
        return out
    for f in SCORED:
        out[f] = round(sum(a[f] == b[f] for a, b in pairs) / n, 4)
    out["all_four"] = round(sum(all(a[f] == b[f] for f in SCORED) for a, b in pairs) / n, 4)
    return out


def main():
    st_pages = collections.defaultdict(list)
    for line in open(REPO / "data/spacetime/doggett1850_51.objects.ndjson"):
        d = json.loads(line)
        st_pages[d["data"]["pageUuid"]].append(d)
    ny_pages = collections.defaultdict(list)
    n_ny = 0
    for line in open(REPO / "data/nyu_1850_head.ndjson"):
        r = json.loads(line)
        ny_pages[r["page_uuid"].split(".")[-1]].append(r)
        n_ny += 1

    exact, near, unpaired_ny = [], [], 0
    for page, nys in ny_pages.items():
        by_text = collections.defaultdict(list)
        for d in st_pages.get(page, []):
            by_text[d["data"]["text"]].append(d)
        left = []
        for r in nys:
            hit = by_text.get(r["complete_entry"])
            if hit:
                exact.append((r, hit.pop()))
            else:
                left.append(r)
        rest = [d for ds in by_text.values() for d in ds]
        for r in left:
            best, score = None, NEAR
            for d in rest:
                s = difflib.SequenceMatcher(None, r["complete_entry"], d["data"]["text"]).ratio()
                if s >= score:
                    best, score = d, s
            if best is None:
                unpaired_ny += 1
            else:
                rest.remove(best)
                near.append((r, best))

    def fields(pairs):
        out = []
        for r, d in pairs:
            ex = to_record(r, False)
            if ex:
                out.append((ex["record"], st_record(d)))
        return out

    def gated(pairs):          # the rows nyu_to_eval's default gate keeps
        return [(r, d) for r, d in pairs
                if str(r.get("low_entry_caution", "0")) != "1"
                and _scores_ok(r.get("corrected_entry") or {}, 15)]

    # the 3,000 eval rows themselves
    eval_lines = [json.loads(l) for l in open(REPO / "data/nyu_eval.jsonl")]
    twin = {}
    for kind, pairs in (("exact", exact), ("near", near)):
        for r, d in pairs:
            twin.setdefault(r["complete_entry"], (kind, d))
    ev = collections.Counter()
    ev_pairs = []
    for e in eval_lines:
        kind, d = twin.get(e["raw_line"], ("none", None))
        ev[kind] += 1
        if d is not None:
            ev_pairs.append((e["record"], st_record(d)))

    res = {
        "volume": "4adf9ec0-317a-0134-03ad-00505686a51c (Doggett 1850/51)",
        "lines": {"nyu": n_ny, "spacetime": sum(map(len, st_pages.values()))},
        "pages": {"nyu": len(ny_pages), "spacetime": len(st_pages),
                  "both": len(set(ny_pages) & set(st_pages))},
        "nyu_lines_paired": {"identical_text": len(exact), f"near_text_ge_{NEAR}": len(near),
                             "unpaired": unpaired_ny},
        "field_agreement_identical_text": agreement(fields(exact)),
        "field_agreement_identical_text_gated": agreement(fields(gated(exact))),
        "field_agreement_near_text": agreement(fields(near)),
        "eval_rows": {"n": len(eval_lines), "twin": dict(ev),
                      "field_agreement_with_twin": agreement(ev_pairs)},
    }
    out = REPO / "results/spacetime_nyu_agreement.json"
    out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))

    # a few disagreements on identical text, to read
    shown = 0
    for r, d in gated(exact):
        ex = to_record(r, False)
        if not ex:
            continue
        a, b = ex["record"], st_record(d)
        bad = [f for f in SCORED if a[f] != b[f]]
        if bad and shown < 25:
            shown += 1
            print("\n", r["complete_entry"])
            for f in bad:
                print(f"   {f}: nyu={a[f]!r}  spacetime={b[f]!r}")


if __name__ == "__main__":
    main()
