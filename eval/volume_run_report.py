#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Check a whole-volume prediction run (hpc/35_volumes.sbatch) with everything that needs no new
labels: the checks pre-registered in the five-volume run plan (2026-09-24).

    python3 eval/volume_run_report.py                        # every volume under data/volumes
    python3 eval/volume_run_report.py --run 4b-100k --out results/volume_run_4b-100k.json
    python3 eval/volume_run_report.py --self-test

Reads data/volumes/<id>/chunk_NNN.jsonl and the matching chunk_NNN.preds_<run>.txt (one YAML
record per line, in line order; a count mismatch is fatal, never truncated).

THE CHECKS
    entry rates   per volume x section x ad band x LAYOUT ROLE. The role comes from geometry alone
                  (layout_roles): 'start' at the column margin, 'runover' at the hanging indent,
                  'other' for centred headings and ad copy. The model never declines a line, so a
                  runover line comes back as a person named after whatever it holds ('Bleecker',
                  '191 Duane'). The role separates those from real entries without the model.
    printed count Doggett 1845's title page claims 61,333 names. Records per printed name, raw and
                  with runover and 'other' lines removed. Pre-registered band 0.9-1.05.
    2B vs 4B      the 500 1906BPL lines the 2B already predicted, found in the volume by leaf+bbox.
                  Agreement, not accuracy: the diffs go to --diffs for a human.
    entry labels  the 140 hand labels (data/entry_labels_1906BPL.jsonl): which were removed by the
                  survey's section scoping, and how the model treated the ones that remained.
    panel pages   the gold pages inside hearne1852, mercein1820 and smith1856, located by the leaf
                  in the gold image name. Gold rows are aligned to OCR lines by fuzzy text (a gold
                  entry may span two lines), then scored end to end against the panel's own
                  prediction on the gold text. Holdout leaves: measurement only, never training.
    invented text name tokens with no near match anywhere in the line ('Holith Thaddeus' from
                  'Hol lith , 26 N. Y.').
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO / "eval"), str(REPO / "data_prep")]
from entry_rate import is_entry  # noqa: E402
from evaluate import FIELDS, load_pred, metrics, norm, score  # noqa: E402
from ia_volume_to_jsonl import INDENT_RATIO  # noqa: E402  the wrap-join threshold the lines saw

VOL = REPO / "data" / "volumes"
PANEL_PREDS = REPO / "results" / "runs" / "scale-runs" / "preds"
PANEL_SETS = {"micro_IABROOKLYN_0030": "hearne1852", "merceinscitydire00merc": "mercein1820",
              "micro_IABROOKLYN_0036": "smith1856"}
# title page: "CONTAINS SIXTY-ONE THOUSAND THREE HUNDRED & THIRTY-THREE NAMES"
PRINTED_COUNT = {"doggettsnewyorkc1845dogg": 61333}
RECALL_BAND = (0.9, 1.05)
EXCLUDE = {"spouse_name", "race_designation", "is_business"}   # regex-derived gold, SCALE_RUNS.md
BPL = "1906BPL"
BPL_SAMPLE = REPO / "data" / "1906BPL_sample500_norm_eval.jsonl"
BPL_SAMPLE_2B = REPO / "data" / "preds_2b-100k_1906BPL_sample500_norm.txt"
BPL_LABELS = REPO / "data" / "entry_labels_1906BPL.jsonl"

# Indent from the fitted column margin, in thousandths of page width. Doggett 1845 (64,580 lines):
# starts sit at 0-15, runovers at 30-45 with a trough between; ad copy and centred headings beyond.
START_MAX, RUNOVER_MAX, OUTDENT = 18, 60, -25
MATCH_MIN = 0.6                     # fuzzy ratio for a gold row to claim an OCR line (or pair)


# ---------------------------------------------------------------- loading

def load_volume(ident: str, run: str) -> list:
    """[(line, pred)] in volume order. Every chunk must carry exactly one record per line."""
    out = []
    chunks = sorted((VOL / ident).glob("chunk_*.jsonl"))
    if not chunks:
        raise SystemExit(f"no chunks under {VOL / ident}")
    for c in chunks:
        lines = [json.loads(x) for x in c.read_text(encoding="utf-8").splitlines() if x.strip()]
        p = c.with_name(f"{c.stem}.preds_{run}.txt")
        if not p.exists():
            raise SystemExit(f"missing predictions {p}")
        preds = load_pred(str(p), "yaml")
        if len(preds) != len(lines):
            raise SystemExit(f"{p.name}: {len(preds)} records for {len(lines)} lines -- they must "
                             f"align 1:1 or every number below is silently wrong")
        out += list(zip(lines, preds))
    return out


def volumes(run: str) -> list:
    return sorted(d.name for d in VOL.iterdir()
                  if d.is_dir() and any(d.glob(f"chunk_*.preds_{run}.txt")))


# ---------------------------------------------------------------- layout

def _fit(pts):
    """Least-squares x = a + b*y. Microfilm pages are skewed: the margin drifts ~1% of the page
    width top to bottom, half the gap between a start and a runover, so a flat margin misfiles."""
    n = len(pts)
    my, mx = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    vy = sum((p[0] - my) ** 2 for p in pts)
    b = sum((p[0] - my) * (p[1] - mx) for p in pts) / vy if vy else 0.0
    if abs(b) > 0.05:
        b = 0.0
    return mx - b * my, b


def layout_roles(lines: list) -> list:
    """Role of each line from its box alone: start | runover | other | thin (too few lines on the
    leaf or in the column to fit a margin)."""
    roles = ["thin"] * len(lines)
    by_leaf = defaultdict(list)
    for i, ln in enumerate(lines):
        by_leaf[ln["context"]["leaf"]].append(i)
    for ix in by_leaf.values():
        W, H = lines[ix[0]]["context"]["page_size"]
        if len(ix) < 8:
            continue
        x = {i: lines[i]["context"]["bbox"][0] / W for i in ix}
        y = {i: (lines[i]["context"]["bbox"][1] + lines[i]["context"]["bbox"][3]) / 2 / H
             for i in ix}
        # column left edges: 2%-of-width bins holding >= 12% of the leaf's lines, merged within 6%
        bins = Counter(int(v * 50) for v in x.values())
        peaks = sorted(b for b, c in bins.items() if c >= max(3, 0.12 * len(ix)))
        groups = []
        for b in peaks:
            if groups and b - groups[-1][1] <= 3:
                groups[-1][1] = b
            else:
                groups.append([b, b])
        lefts = [g[0] / 50 - 0.02 for g in groups] or [0.0]
        cols = defaultdict(list)
        for i in ix:
            cols[max((k for k, e in enumerate(lefts) if e <= x[i]), default=0)].append(i)
        for grp in cols.values():
            if len(grp) < 5:
                continue
            xs = sorted(x[i] for i in grp)
            p10 = xs[len(xs) // 10]
            keep = [(y[i], x[i]) for i in grp if p10 - 0.02 <= x[i] <= p10 + 0.015]
            a, b = _fit(keep or [(y[i], x[i]) for i in grp])
            for _ in range(2):
                near = [(y[i], x[i]) for i in grp if abs(x[i] - (a + b * y[i])) <= 0.012]
                if len(near) >= 3:
                    a, b = _fit(near)
            for i in grp:
                d = (x[i] - (a + b * y[i])) * 1000
                roles[i] = ("start" if OUTDENT <= d <= START_MAX else
                            "runover" if START_MAX < d <= RUNOVER_MAX else "other")
    return roles


# ---------------------------------------------------------------- text helpers

def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def invented_tokens(name: str, raw: str) -> list:
    """Name words (3+ letters) with no near match in the line. OCR repair ('M irgaret' ->
    'Margaret') passes; a first name conjured from nothing does not."""
    flat = re.sub(r"[^a-z]", "", raw.lower())
    out = []
    for t in re.findall(r"[A-Za-z]{3,}", name):
        t = t.lower()
        if t in flat:
            continue
        L = len(t)
        best = max((_ratio(t, flat[k:k + L]) for k in range(max(1, len(flat) - L + 1))),
                   default=0.0)
        if best < 0.6:
            out.append(t)
    return out


def named(p: dict) -> bool:
    return bool(p["name"].strip())


def _toks(s: str) -> list:
    return re.findall(r"[a-z0-9]+", s.lower().replace("’", "'"))


SUB_FIELDS = ("address", "home_address", "occupation_role", "employer")
BOOK_WORD = 20          # a word the volume's OCR holds this often is part of its vocabulary
BOOK_RATIO = 10         # ...and this many times more often than the word the model wrote instead


def substitutions(rows: list, top: int = 30) -> dict:
    """Field words absent from their own line, traced to the line word they replaced.

    The volume's own OCR vocabulary sorts each pair, with no labels needed. `Degraw` occurs
    thousands of times in 1906BPL and `Delaware` almost never, so `Degraw -> Delaware` REPLACES A
    COMMON WORD. `cartmaa -> cartman` moves a rare string to one the volume uses constantly: TOWARD
    A COMMON WORD, almost always an OCR repair. The first class is an upper bound on corruption,
    not a count of it: an OCR error systematic enough to be 'common' lands there too (1906BPL reads
    its `clk` as `elk` ~15,000 times, and `elk -> clk` is a correct repair). Read its top pairs."""
    vocab = Counter(t for ln, _ in rows for t in _toks(ln["raw_line"]))
    pairs, recs = Counter(), defaultdict(set)
    n_tok = 0
    for k, (ln, p) in enumerate(rows):
        rs = set(_toks(ln["raw_line"]))
        for f in SUB_FIELDS:
            pt = _toks(p.get(f, ""))
            ps = set(pt)
            for t in pt:
                n_tok += 1
                if t in rs or len(t) < 2:
                    continue
                cand = [r for r in rs if r not in ps and len(r) >= 2]
                best = get_close_matches(t, cand, 1, 0.5)
                pairs[(best[0] if best else "", t)] += 1
                recs[(best[0] if best else "", t)].add(k)

    def kind(s, t):
        fs, ft = vocab[s], vocab[t]
        if s and fs >= BOOK_WORD and fs >= BOOK_RATIO * max(ft, 1):
            return "replaces_common_word"
        if ft >= BOOK_WORD and ft >= BOOK_RATIO * max(fs, 1):
            return "toward_common_word"
        return "unclear"
    by_kind, by_kind_recs = Counter(), defaultdict(set)
    for (s, t), n in pairs.items():
        by_kind[kind(s, t)] += n
        by_kind_recs[kind(s, t)] |= recs[(s, t)]
    return {"field_tokens": n_tok, "not_in_line": sum(pairs.values()),
            "by_kind_tokens": dict(by_kind),
            "by_kind_records": {k: len(v) for k, v in by_kind_recs.items()},
            "replaces_common_word_record_rate":
                round(len(by_kind_recs["replaces_common_word"]) / len(rows), 4),
            "top_pairs": [{"line": s, "wrote": t, "n": n, "book_freq_line": vocab[s],
                           "book_freq_wrote": vocab[t], "kind": kind(s, t)}
                          for (s, t), n in pairs.most_common(top)],
            "top_replacements": [{"line": s, "wrote": t, "n": n, "book_freq_line": vocab[s],
                               "book_freq_wrote": vocab[t]}
                              for (s, t), n in pairs.most_common()
                              if kind(s, t) == "replaces_common_word"][:top]}


def layout_checks(rows: list, roles: list) -> dict:
    """Two input faults the model cannot fix, both measured from boxes alone.

    Runovers left unjoined: join_wraps joins a line indented >= INDENT_RATIO median line heights,
    a figure calibrated on 1906BPL. Where a book's hanging indent is shallower, every runover
    arrives as its own line: the entry loses its tail and the tail becomes a person.
    Columns merged: microfilm tesseract sometimes reads straight across the gutter, so one line
    holds a left-column entry and a right-column entry, and the model returns only the first."""
    by_leaf = defaultdict(list)
    for i, (ln, _) in enumerate(rows):
        by_leaf[ln["context"]["leaf"]].append(i)
    # two-column volume: on a typical leaf a quarter or more of the lines start right of centre
    right = sorted(sum(rows[i][0]["context"]["bbox"][0] > 0.45 * rows[i][0]["context"]["page_size"][0]
                       for i in ix) / len(ix) for ix in by_leaf.values() if len(ix) >= 10)
    two_col = bool(right) and right[len(right) // 2] >= 0.25
    ind, cross, merged_leaves, merged_lines = [], 0, [], 0
    for L, ix in by_leaf.items():
        hs = sorted(rows[i][0]["context"]["bbox"][3] - rows[i][0]["context"]["bbox"][1] for i in ix)
        mh = hs[len(hs) // 2] or 1
        for a, b in zip(ix, ix[1:]):
            if roles[a] == "start" and roles[b] == "runover":
                ind.append((rows[b][0]["context"]["bbox"][0] - rows[a][0]["context"]["bbox"][0]) / mh)
        W = rows[ix[0]][0]["context"]["page_size"][0]
        c = sum(1 for i in ix if rows[i][0]["context"]["bbox"][0] < 0.4 * W
                and rows[i][0]["context"]["bbox"][2] > 0.6 * W)
        cross += c
        if two_col and len(ix) >= 10 and c / len(ix) > 0.5:
            merged_leaves.append(L)
            merged_lines += len(ix)
    ind.sort()
    q = (lambda p: round(ind[int(p * (len(ind) - 1))], 2)) if ind else (lambda p: None)
    return {"runover_after_start": len(ind),
            "runover_indent_in_line_heights": {"p10": q(.1), "p50": q(.5), "p90": q(.9)},
            "join_threshold": INDENT_RATIO,
            "runovers_below_threshold": sum(r < INDENT_RATIO for r in ind),
            "two_column": two_col, "lines_crossing_gutter": cross if two_col else None,
            "column_merged_leaves": len(merged_leaves), "lines_on_merged_leaves": merged_lines,
            "column_merged_leaf_list": sorted(merged_leaves)}


WIDOW = re.compile(r"^[A-Z][a-z]+,? (widow|wid)\b")


def widow_names(rows: list) -> dict:
    """`Ackerman widow, 47 Elizabeth` prints no given name. Gold keeps the surname alone
    (`Duggan widow of Thomas` -> name `Duggan`); a given name in the record was conjured."""
    w = [(ln["raw_line"], p["name"]) for ln, p in rows if WIDOW.match(ln["raw_line"])]
    inv = [(r, n) for r, n in w if invented_tokens(n, r)]
    return {"lines": len(w), "given_name_invented": len(inv),
            "given_names": dict(Counter(n.split()[-1] for _, n in inv).most_common(8)),
            "examples": inv[:10]}


# ---------------------------------------------------------------- checks

def entry_rates(rows: list, roles: list) -> dict:
    """lines / named / entry-shaped / business, by section, band and layout role."""
    def tally(keyf):
        t = defaultdict(lambda: Counter())
        for (ln, p), r in zip(rows, roles):
            c = t[keyf(ln, r)]
            c["lines"] += 1
            c["named"] += named(p)
            c["entry_shaped"] += is_entry(p)
            c["business"] += p["is_business"] in (True, "true", "True")
        return {k: dict(v) for k, v in sorted(t.items(), key=lambda kv: -kv[1]["lines"])}
    out = {"all": tally(lambda ln, r: "all")["all"],
           "by_section": tally(lambda ln, r: ln["context"].get("section") or "?"),
           "by_role": tally(lambda ln, r: r)}
    if any(ln["context"].get("band") for ln, _ in rows):
        out["by_band"] = tally(lambda ln, r: ln["context"].get("band") or "unbanded")
    return out


def printed_count_check(rows: list, roles: list, printed: int) -> dict:
    n_named = sum(named(p) for _, p in rows)
    by_role = Counter(r for (_, p), r in zip(rows, roles) if named(p))
    real = n_named - by_role["runover"] - by_role["other"]
    split = sum(1 for i in range(len(rows) - 1)
                if roles[i] == "start" and roles[i + 1] == "runover")
    lost = [ln["raw_line"] for (ln, p), r in zip(rows, roles) if r == "start" and not named(p)]
    ex_run = [(ln["raw_line"], p["name"]) for (ln, p), r in zip(rows, roles)
              if r == "runover" and named(p)]
    lo, hi = RECALL_BAND
    ratio, ratio_adj = n_named / printed, real / printed
    return {"printed": printed, "band": [lo, hi],
            "named": n_named, "ratio": round(ratio, 4),
            "named_by_role": dict(by_role),
            "named_starts_and_thin": real, "ratio_adjusted": round(ratio_adj, 4),
            "verdict": "pass" if lo <= ratio <= hi else "fail",
            "verdict_adjusted": "pass" if lo <= ratio_adj <= hi else "fail",
            "entries_split_over_runover": split,
            "start_lines_unnamed": len(lost), "start_lines_unnamed_examples": lost[:12],
            "runover_named_examples": ex_run[:12]}


def bpl_2b_vs_4b(rows: list, diffs_path) -> dict:
    sample = [json.loads(x) for x in BPL_SAMPLE.read_text(encoding="utf-8").splitlines()
              if x.strip()]
    p2 = load_pred(str(BPL_SAMPLE_2B), "yaml")
    assert len(sample) == len(p2), (len(sample), len(p2))
    at = {(ln["context"]["leaf"], tuple(ln["context"]["bbox"])): i for i, (ln, _) in enumerate(rows)}
    agree = Counter()
    n = same_input = row_agree = row_agree_same = 0
    counts = Counter()
    diffs = []
    for s, a in zip(sample, p2):
        j = at.get((s["context"]["leaf"], tuple(s["context"]["bbox"])))
        if j is None:
            continue
        ln, b = rows[j]
        n += 1
        same = ln["raw_line"] == s["raw_line"]
        same_input += same
        counts["named_2b"] += named(a)
        counts["named_4b"] += named(b)
        counts["entry_2b"] += is_entry(a)
        counts["entry_4b"] += is_entry(b)
        all_eq = True
        for f in FIELDS:
            eq = norm(a.get(f, ""), False) == norm(b.get(f, ""), False)
            agree[f] += eq
            all_eq &= eq
            if not eq:
                diffs.append({"leaf": s["context"]["leaf"], "bbox": s["context"]["bbox"],
                              "raw_line_2b": s["raw_line"], "raw_line_4b": ln["raw_line"],
                              "field": f, "2b": a.get(f, ""), "4b": b.get(f, "")})
        row_agree += all_eq
        row_agree_same += all_eq and same
    if diffs_path:
        Path(diffs_path).parent.mkdir(parents=True, exist_ok=True)
        # csv quoting, not bare tabs: a 1906BPL line may open with a ditto `"` or hold a tab
        with open(diffs_path, "w", encoding="utf-8", newline="") as fh:
            cols = ["leaf", "field", "2b", "4b", "raw_line_2b", "raw_line_4b"]
            w = csv.writer(fh, delimiter="\t")
            w.writerow(cols)
            for d in diffs:
                w.writerow([d[c] for c in cols])
    return {"sample": len(sample), "found_by_leaf_bbox": n, "identical_input": same_input,
            "row_agreement": round(row_agree / max(n, 1), 4),
            "row_agreement_identical_input": round(row_agree_same / max(same_input, 1), 4),
            "field_agreement": {f: round(agree[f] / max(n, 1), 4) for f in FIELDS},
            **dict(counts), "field_diffs": len(diffs),
            "diff_by_field": dict(Counter(d["field"] for d in diffs).most_common()),
            "diffs_file": str(Path(diffs_path).relative_to(REPO)) if diffs_path else None}


def bpl_labels(rows: list) -> dict:
    labels = [json.loads(x) for x in BPL_LABELS.read_text(encoding="utf-8").splitlines()
              if x.strip()]
    by_leaf = defaultdict(list)
    for i, (ln, _) in enumerate(rows):
        by_leaf[ln["context"]["leaf"]].append(i)
    out = {"labels": len(labels), "in_scope": Counter(), "out_of_scope": Counter(),
           "in_scope_named": Counter(), "in_scope_entry_shaped": Counter(),
           "out_of_scope_entries": [], "in_scope_not_entry_named": []}
    for lab in labels:
        if lab["label"] == "unsure":
            continue
        cands = by_leaf.get(lab["leaf"], [])
        best = max(cands, key=lambda i: _ratio(_key(rows[i][0]["raw_line"]), _key(lab["raw_line"])),
                   default=None)
        hit = best is not None and _ratio(_key(rows[best][0]["raw_line"]),
                                          _key(lab["raw_line"])) >= 0.9
        tag = f'{lab["label"]}/{lab["category"] or "-"}'
        if not hit:
            out["out_of_scope"][tag] += 1
            if lab["label"] == "entry":
                out["out_of_scope_entries"].append((lab["leaf"], lab["raw_line"]))
            continue
        p = rows[best][1]
        out["in_scope"][tag] += 1
        out["in_scope_named"][tag] += named(p)
        out["in_scope_entry_shaped"][tag] += is_entry(p)
        if lab["label"] == "not-entry" and named(p):
            out["in_scope_not_entry_named"].append((lab["leaf"], lab["band"], lab["raw_line"],
                                                    p["name"]))
    for k in ("in_scope", "out_of_scope", "in_scope_named", "in_scope_entry_shaped"):
        out[k] = dict(sorted(out[k].items()))
    return out


def align(gold_rows: list, cand_idx: list, rows: list) -> list:
    """Greedy one-to-one match of gold rows to an OCR line or a line + the next one (a gold entry
    typed as one row may be two printed lines). Returns [(gold i, (line j, ...), ratio)]."""
    cands = [(j,) for j in cand_idx] + [(a, b) for a, b in zip(cand_idx, cand_idx[1:])]
    text = {c: _key(" ".join(rows[j][0]["raw_line"] for j in c)) for c in cands}
    scored = []
    for gi, g in enumerate(gold_rows):
        gk = _key(g["raw_line"])
        for c in cands:
            if abs(len(text[c]) - len(gk)) <= max(12, 0.6 * len(gk)):
                r = _ratio(gk, text[c])
                if r >= MATCH_MIN:
                    scored.append((r, len(c) == 1, gi, c))
    scored.sort(key=lambda t: (-t[0], not t[1]))
    used_g, used_l, out = set(), set(), []
    for r, _, gi, c in scored:
        if gi in used_g or used_l & set(c):
            continue
        used_g.add(gi)
        used_l |= set(c)
        out.append((gi, c, r))
    return sorted(out)


def _m(gold, pred) -> dict:
    m = metrics(score(gold, pred, False, EXCLUDE), EXCLUDE)
    return {"n": m["n"], "row_exact_pct": m["row_exact_pct"], "macro_f1": m["macro_f1"],
            "field_em": {f: m["per_field"][f]["em"] for f in FIELDS if f not in EXCLUDE}}


def panel_pages(ident: str, rows: list, roles: list, run: str) -> dict:
    set_ = PANEL_SETS[ident]
    gold = [json.loads(x) for x in (REPO / "data" / f"{set_}_eval.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    pp = PANEL_PREDS / f"preds_{run}_{set_}.txt"
    panel = load_pred(str(pp), "yaml") if pp.exists() else None
    if panel is not None and len(panel) != len(gold):
        raise SystemExit(f"{pp.name}: {len(panel)} records for {len(gold)} gold rows")
    leaf_of = [int(re.search(r"_(\d{4})\.jp2", g["context"]["image"]).group(1)) for g in gold]
    by_leaf = defaultdict(list)
    for i, (ln, _) in enumerate(rows):
        by_leaf[ln["context"]["leaf"]].append(i)
    matches, extras = [], []
    per_leaf = {}
    for L in sorted(set(leaf_of)):
        gi = [i for i, x in enumerate(leaf_of) if x == L]
        m = align([gold[i] for i in gi], by_leaf.get(L, []), rows)
        matches += [(gi[a], c, r) for a, c, r in m]
        used = {j for _, c, _ in m for j in c}
        ex = [j for j in by_leaf.get(L, []) if j not in used]
        extras += ex
        per_leaf[L] = {"gold_rows": len(gi), "ocr_lines": len(by_leaf.get(L, [])),
                       "matched": len(m), "pairs": sum(len(c) == 2 for _, c, _ in m),
                       "unmatched_ocr_lines": len(ex)}
    g_m = [gold[i]["record"] for i, _, _ in matches]
    v_m = [rows[c[0]][1] for _, c, _ in matches]
    single = [k for k, (_, c, _) in enumerate(matches) if len(c) == 1]
    exact = [k for k, (i, c, _) in enumerate(matches)
             if len(c) == 1 and _key(rows[c[0]][0]["raw_line"]) == _key(gold[i]["raw_line"])]
    out = {"set": set_, "gold_rows": len(gold), "per_leaf": per_leaf,
           "matched": len(matches), "matched_pct": round(100 * len(matches) / len(gold), 1),
           "match_ratio_median": round(sorted(r for *_, r in matches)[len(matches) // 2], 3)
           if matches else None,
           "volume_on_matched": _m(g_m, v_m),
           "volume_on_single_line_matches": _m([g_m[k] for k in single], [v_m[k] for k in single]),
           "volume_on_identical_text": _m([g_m[k] for k in exact], [v_m[k] for k in exact]),
           "extras": len(extras), "extras_named": sum(named(rows[j][1]) for j in extras),
           "extras_by_role": dict(Counter(roles[j] for j in extras)),
           "extras_examples": [(rows[j][0]["raw_line"], rows[j][1]["name"], roles[j])
                               for j in extras[:15]],
           "unmatched_gold_examples": [gold[i]["raw_line"] for i in range(len(gold))
                                       if i not in {m[0] for m in matches}][:15]}
    if panel is not None:
        p_m = [panel[i] for i, _, _ in matches]
        out["panel_on_matched"] = _m(g_m, p_m)
        out["panel_on_all_gold"] = _m([g["record"] for g in gold], panel)
        out["panel_on_identical_text"] = _m([g_m[k] for k in exact], [p_m[k] for k in exact])
        worse = []
        for k, (i, c, _) in enumerate(matches):
            for f in ("name", "occupation_role", "address", "home_address"):
                gv = norm(gold[i]["record"].get(f, ""), False)
                if norm(p_m[k].get(f, ""), False) == gv != norm(v_m[k].get(f, ""), False):
                    worse.append({"gold_text": gold[i]["raw_line"],
                                  "ocr_text": " / ".join(rows[j][0]["raw_line"] for j in c),
                                  "field": f, "gold": gold[i]["record"].get(f, ""),
                                  "volume": v_m[k].get(f, "")})
        out["panel_right_volume_wrong"] = len(worse)
        out["panel_right_volume_wrong_examples"] = worse[:15]
    return out


def invented(rows: list) -> dict:
    hits = []
    for ln, p in rows:
        if named(p):
            t = invented_tokens(p["name"], ln["raw_line"])
            if t:
                hits.append((ln["raw_line"], p["name"], t))
    n = sum(named(p) for _, p in rows)
    return {"named": n, "with_invented_token": len(hits),
            "rate": round(len(hits) / max(n, 1), 4), "examples": hits[:15]}


# ---------------------------------------------------------------- report

def run_all(run: str, diffs_path) -> dict:
    out = {"run": run, "volumes": {}}
    for ident in volumes(run):
        rows = load_volume(ident, run)
        roles = layout_roles([ln for ln, _ in rows])
        v = {"lines": len(rows), "entry_rates": entry_rates(rows, roles),
             "layout": layout_checks(rows, roles),
             "invented_name_tokens": invented(rows), "widow_names": widow_names(rows),
             "substitutions": substitutions(rows)}
        if ident in PRINTED_COUNT:
            v["printed_count"] = printed_count_check(rows, roles, PRINTED_COUNT[ident])
        if ident in PANEL_SETS:
            v["panel_pages"] = panel_pages(ident, rows, roles, run)
        if ident == BPL:
            v["2b_vs_4b_sample500"] = bpl_2b_vs_4b(rows, diffs_path)
            v["entry_labels"] = bpl_labels(rows)
        out["volumes"][ident] = v
        print(f"  {ident}: {len(rows):,} lines", file=sys.stderr)
    return out


def _pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "   - "


def print_report(rep: dict) -> None:
    P = print
    for ident, v in rep["volumes"].items():
        er = v["entry_rates"]
        a = er["all"]
        P(f"\n=== {ident}  {a['lines']:,} lines  named {_pct(a['named'], a['lines'])}  "
          f"entry-shaped {_pct(a['entry_shaped'], a['lines'])}")
        for dim in ("by_section", "by_band", "by_role"):
            for k, c in er.get(dim, {}).items():
                P(f"    {dim[3:]:8s} {k[:32]:32s} {c['lines']:>7,}  named {_pct(c['named'], c['lines'])}"
                  f"  entry-shaped {_pct(c['entry_shaped'], c['lines'])}")
        lo = v["layout"]
        P(f"    runovers after a start: {lo['runover_after_start']:,}, indent "
          f"{lo['runover_indent_in_line_heights']} line heights, {lo['runovers_below_threshold']:,} "
          f"below the join threshold {lo['join_threshold']};  column-merged leaves "
          f"{lo['column_merged_leaves']} ({lo['lines_on_merged_leaves']:,} lines)")
        inv = v["invented_name_tokens"]
        P(f"    invented name tokens: {inv['with_invented_token']:,} of {inv['named']:,} named "
          f"({100 * inv['rate']:.2f}%)  e.g. " +
          "; ".join(f"{r[:28]!r}->{n!r}" for r, n, _ in inv["examples"][:3]))
        wn = v["widow_names"]
        if wn["lines"]:
            P(f"    widow lines with no given name printed: {wn['lines']:,}, given name invented "
              f"on {wn['given_name_invented']:,} {wn['given_names']}")
        sb = v["substitutions"]
        P(f"    field words not in their line: {sb['not_in_line']:,} of {sb['field_tokens']:,}  "
          f"{sb['by_kind_tokens']};  records replacing a common word: "
          f"{sb['by_kind_records'].get('replaces_common_word', 0):,} "
          f"({100 * sb['replaces_common_word_record_rate']:.2f}%)")
        P("      top replacements: " + ", ".join(f"{d['line']}->{d['wrote']} {d['n']}"
                                                 for d in sb["top_replacements"][:12]))
        if "printed_count" in v:
            pc = v["printed_count"]
            P(f"  PRINTED COUNT {pc['printed']:,}: named {pc['named']:,} = {pc['ratio']:.3f} "
              f"[{pc['verdict']}];  minus runover/other {pc['named_starts_and_thin']:,} = "
              f"{pc['ratio_adjusted']:.3f} [{pc['verdict_adjusted']}]")
            P(f"    named by role {pc['named_by_role']};  entries split over a runover "
              f"{pc['entries_split_over_runover']:,};  unnamed start lines "
              f"{pc['start_lines_unnamed']:,}")
        if "panel_pages" in v:
            pp = v["panel_pages"]
            P(f"  PANEL PAGES ({pp['set']}): {pp['matched']}/{pp['gold_rows']} gold rows found in "
              f"the OCR ({pp['matched_pct']}%), median match {pp['match_ratio_median']}")
            for L, d in pp["per_leaf"].items():
                P(f"    leaf {L}: {d}")
            for k in ("volume_on_matched", "panel_on_matched", "volume_on_identical_text",
                      "panel_on_identical_text", "panel_on_all_gold"):
                if k in pp:
                    m = pp[k]
                    P(f"    {k:26s} n={m['n']:>4}  row EM {m['row_exact_pct']:5.1f}  "
                      f"macro-F1 {m['macro_f1']:.3f}  " +
                      " ".join(f"{f[:4]}={e}" for f, e in m["field_em"].items()))
            P(f"    extra OCR lines on gold leaves: {pp['extras']} ({pp['extras_named']} named) "
              f"{pp['extras_by_role']}")
        if "2b_vs_4b_sample500" in v:
            c = v["2b_vs_4b_sample500"]
            P(f"  2B vs 4B: {c['found_by_leaf_bbox']}/{c['sample']} found, "
              f"{c['identical_input']} identical input; row agreement {c['row_agreement']:.3f}; "
              f"named 2B {c.get('named_2b')} 4B {c.get('named_4b')}; entry-shaped 2B "
              f"{c.get('entry_2b')} 4B {c.get('entry_4b')}")
            P(f"    field agreement {c['field_agreement']}")
        if "entry_labels" in v:
            el = v["entry_labels"]
            P(f"  ENTRY LABELS: out of scope {el['out_of_scope']}")
            P(f"    in scope {el['in_scope']}  named {el['in_scope_named']}  "
              f"entry-shaped {el['in_scope_entry_shaped']}")


def _self_test() -> int:
    # layout: a skewed column of starts with two runovers and a centred heading
    lines = []
    for k in range(20):
        x0 = 200 - k * 2                                  # skew: margin drifts left down the page
        lines.append({"raw_line": f"Abbott {k}, 1 Main", "context": {
            "leaf": 1, "page_size": [2000, 3000], "bbox": [x0, 100 + 120 * k, 900, 150 + 120 * k]}})
    lines[5]["context"]["bbox"][0] += 70                  # runover: 35/1000 of width
    lines[12]["context"]["bbox"][0] += 70
    lines[17]["context"]["bbox"][0] = 800                 # centred heading
    roles = layout_roles(lines)
    assert roles[5] == roles[12] == "runover", roles
    assert roles[17] == "other", roles
    assert roles.count("start") == 17, roles
    # align: a gold entry typed as one row matches a start + runover pair
    rows = [({"raw_line": t}, {}) for t in
            ["Holmes James M. fish, 42 Water, N. V. bh. Wash-", "ington av. n. Lafayette av",
             "Holmes Jane, colored widow, r. 83 Carll"]]
    gold = [{"raw_line": "Holmes Jane, colored widow, r. 83 Carll"},
            {"raw_line": "Holmes James M. fish, 42 Water, N. Y. h. Washington av. n. Lafayette av"}]
    m = align(gold, [0, 1, 2], rows)
    assert [(g, c) for g, c, _ in m] == [(0, (2,)), (1, (0, 1))], m
    # invented tokens: repair passes, conjured first names do not
    assert invented_tokens("Lane Margaret", "Lane M irgaret, widow of Joseph, 201 Varick") == []
    assert invented_tokens("Holith Thaddeus", "Hol lith , 26 N. Y.") == ["thaddeus"]
    assert invented_tokens("Court Anne", "Court, n. ueer") == ["anne"]
    # substitutions: the book's vocabulary referees
    book = [({"raw_line": f"Smith {k} h {k} Degraw"}, {"address": f"h {k} Degraw"})
            for k in range(30)]
    book += [({"raw_line": f"Jones {k} cartman 5 Pearl"}, {"occupation_role": "cartman",
                                                          "address": "5 Pearl"}) for k in range(30)]
    book += [({"raw_line": "Brown h 9 Degraw"}, {"address": "h 9 Delaware"}),
             ({"raw_line": "Green cartmaa 7 Pearl"}, {"occupation_role": "cartman",
                                                     "address": "7 Pearl"})]
    kinds = {(d["line"], d["wrote"]): d["kind"] for d in substitutions(book)["top_pairs"]}
    assert kinds[("degraw", "delaware")] == "replaces_common_word", kinds
    assert kinds[("cartmaa", "cartman")] == "toward_common_word", kinds
    w = widow_names([({"raw_line": "Ackerman widow, 47 Elizabeth"}, {"name": "Ackerman Sarah"}),
                     ({"raw_line": "Duggan widow of Thomas, 10 Canal"}, {"name": "Duggan"})])
    assert (w["lines"], w["given_name_invented"]) == (2, 1), w
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="4b-100k")
    ap.add_argument("--out", help="write the full report as JSON")
    ap.add_argument("--diffs", default=str(REPO / "results" / "volume_run_1906BPL_2b_vs_4b.tsv"),
                    help="2B-vs-4B field diffs for human review ('' to skip)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()
    rep = run_all(args.run, args.diffs or None)
    print_report(rep)
    if args.out:
        Path(args.out).write_text(json.dumps(rep, indent=1, ensure_ascii=False, default=list),
                                  encoding="utf-8")
        print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
