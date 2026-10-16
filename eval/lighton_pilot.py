#!/usr/bin/env python3
"""
The LightOn pilot on the real-OCR panel's book-scan pages (docs/PIPELINE.md #27), through the
production path, with line-level scores beside IA's OCR.

    python3 eval/lighton_pilot.py                          # import, derive, build, score
    python3 eval/lighton_pilot.py --skip-derive            # rebuild the panel and score only
    python3 eval/lighton_pilot.py --diff-against D         # ...and list rows that changed vs D

WHAT IT RUNS. The pilot pages of the panel's 16 IA book-scan volumes were staged on 2026-10-15
(scratch tools, not in the repo) and read by LightOn on the M2:
    data/reocr_pilot/            half tiles, boxes.json, answers under lightonocr-3-1b-greedy-m2
    data/reocr_pilot_pages/      each page as staged (upright), with fresh tesseract words
Each volume's word dump gets its pilot leaves replaced (`reocr_pair.py dump --out-dir`, so the
production dumps and sidecars are untouched), then the survey's filters (`survey_harvest.derive`),
into --work. Hope & Henderson 1856 (micro_IABROOKLYN_0035) was read whole by the Torch run, so
its production lines are copied in. `eval/ia_panel.build` then pairs gold rows with lines into
--panel-dir: the panel the 4B is run on (hpc/prep_volumes.py --files <panel-dir>/iapanel_*.jsonl).

SCORES are per printed entry, against the gold raw_line: exact match and CER, after typography
(curly quotes as straight, one leading ditto form, since the survey normalises an admitted ditto
before the model reads it), beside IA's OCR on the same pages (data/iapanel). They measure the
OCR and line assembly; the 4B's end-to-end row EM needs a Torch run (`ia_panel.score_run`).

--diff-against compares the rebuilt panel with a saved copy of a panel dir, row by row by gold
row, so a change to the import or the survey shows exactly which entries it moved.

⚠️ Stage a panel for Torch into a NEW directory. Predictions align with their chunk by line,
and the `.sha1` beside each one is the only check: restaging a sent package in place cost a
rebuild from git history (PIPELINE #27, 2026-10-16).
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
sys.path[:0] = [str(REPO / "data_prep"), str(REPO / "eval")]
SLUG = "lightonocr-3-1b-greedy-m2"
TORCH_READ = ["micro_IABROOKLYN_0035"]     # whole volumes the Torch run re-read: production lines

_LEAD = re.compile(r'^\s*(?:-+|—+|–+|["“”„«»]|,,|\'\')\s*')


def canon(t: str) -> str:
    """Typography only: curly quotes and apostrophes as straight ones, and every leading ditto
    form ("-Emerson", "—Emerson", '" Emerson') as one."""
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = " ".join(t.split())
    return _LEAD.sub('" ', t) if _LEAD.match(t) else t


def cer(a: str, b: str) -> float:
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return 1 - sum(m.size for m in sm.get_matching_blocks()) / max(len(b), 1)


def pilot_volumes() -> list:
    boxes = json.loads((DATA / "reocr_pilot/boxes.json").read_text(encoding="utf-8"))
    return sorted({k.split("/")[0] for k in boxes if not k.startswith("nypl_")})


def derive(work: Path) -> None:
    vols = pilot_volumes()
    subprocess.run([sys.executable, str(REPO / "data_prep/reocr_pair.py"), "dump", SLUG,
                    "--root", str(DATA / "reocr_pilot"), "--page-dir", str(DATA / "reocr_pilot_pages"),
                    "--ids", ",".join(vols), "--out-dir", str(work)], check=True, cwd=REPO)
    import survey_harvest as sh
    sh.OUT = work
    for ident in vols:
        # the holdout tags as `survey_harvest.py --rederive` applies them
        doc = json.loads((sh.SIDECARS / f"ia_{ident}.json").read_text(encoding="utf-8"))
        held = (doc.get("harvest") or {}).get("eval_holdout") or {}
        holdout = {L: "gold" for L in held.get("gold_leaves", [])}
        holdout.update({L: "adjacent" for L in held.get("adjacent_leaves", [])})
        if held.get("whole_volume"):
            for L in range(doc["harvest"]["dump"]["leaves"]):
                holdout.setdefault(L, "volume")
        f = sh.derive(ident, holdout)
        print(f"derived {ident}: kept {f['kept']:,}", file=sys.stderr)
    for ident in TORCH_READ:
        for kind in ("lines", "listing"):
            src = DATA / "survey_ocr" / f"{ident}_{kind}.jsonl.gz"
            if src.exists():
                shutil.copy2(src, work / src.name)


def load(p: Path) -> list:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if p.exists() else []


def report(panel_dir: Path) -> None:
    print(f"\n{'set':40s} {'rows':>4s} | {'IA: matched':>11s} {'exact':>6s} {'CER':>6s} | "
          f"{'LightOn: matched':>16s} {'exact':>6s} {'CER':>6s}")
    tot = collections.Counter()
    for p in sorted(panel_dir.glob("iapanel_*.jsonl")):
        name = p.name[len("iapanel_"):-len(".jsonl")]
        gold_rows = len(load(DATA / f"{name.split('__')[0]}_eval.jsonl"))
        out = []
        for kind, rows in (("ia", load(DATA / "iapanel" / p.name)), ("lo", load(p))):
            ex = sum(canon(r["raw_line"]) == canon(r["context"]["gold_raw_line"]) for r in rows)
            c = sum(cer(canon(r["raw_line"]), canon(r["context"]["gold_raw_line"])) for r in rows)
            out.append((len(rows), ex, c))
            tot[kind + "_n"] += len(rows)
            tot[kind + "_ex"] += ex
            tot[kind + "_c"] += c
        (ni, ei, ci), (nl, el, cl) = out
        print(f"{name:40s} {gold_rows:4d} | {ni:11d} {100 * ei / max(ni, 1):5.1f}% {ci / max(ni, 1):6.3f} | "
              f"{nl:16d} {100 * el / max(nl, 1):5.1f}% {cl / max(nl, 1):6.3f}")
    print(f"{'POOLED':40s} {'':4s} | {tot['ia_n']:11d} {100 * tot['ia_ex'] / max(tot['ia_n'], 1):5.1f}% "
          f"{tot['ia_c'] / max(tot['ia_n'], 1):6.3f} | {tot['lo_n']:16d} "
          f"{100 * tot['lo_ex'] / max(tot['lo_n'], 1):5.1f}% {tot['lo_c'] / max(tot['lo_n'], 1):6.3f}")
    print("(exact and CER after typography: straight quotes, one leading ditto form)")


def diff(old_dir: Path, new_dir: Path) -> None:
    """Rows whose text or exactness changed, by gold row: + now exact, - no longer, ~ changed."""
    for p in sorted(new_dir.glob("iapanel_*.jsonl")):
        a = {r["context"]["gold_row"]: r for r in load(old_dir / p.name)}
        b = {r["context"]["gold_row"]: r for r in load(p)}
        out = []
        for g in sorted(set(a) | set(b)):
            ra, rb = a.get(g), b.get(g)
            ea = ra is not None and canon(ra["raw_line"]) == canon(ra["context"]["gold_raw_line"])
            eb = rb is not None and canon(rb["raw_line"]) == canon(rb["context"]["gold_raw_line"])
            ta, tb = (ra or {}).get("raw_line"), (rb or {}).get("raw_line")
            if ea != eb or ta != tb:
                mark = "+" if eb and not ea else "-" if ea and not eb else "~"
                out.append(f"  row {g:3d} {mark}  gold {(ra or rb)['context']['gold_raw_line']!r}\n"
                           f"            was  {ta!r}\n            now  {tb!r}")
        if out:
            print(f"== {p.name[len('iapanel_'):-len('.jsonl')]}")
            print("\n".join(out))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=str(DATA / "lighton_pilot"),
                    help="the pilot volumes' word dumps and derived lines (gitignored)")
    ap.add_argument("--panel-dir", default=str(DATA / "iapanel_lighton"),
                    help="inside the repo: ia_panel records each set's file relative to it")
    ap.add_argument("--skip-derive", action="store_true",
                    help="reuse --work as it is: rebuild the panel and score")
    ap.add_argument("--diff-against", help="a saved copy of a panel dir to compare row by row")
    args = ap.parse_args(argv)
    work, panel_dir = Path(args.work).resolve(), Path(args.panel_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if not args.skip_derive:
        derive(work)
    import ia_panel
    ia_panel.OCR, ia_panel.PANEL_DIR, ia_panel.MANIFEST = work, panel_dir, panel_dir / "manifest.json"
    ia_panel.build()
    report(panel_dir)
    if args.diff_against:
        print()
        diff(Path(args.diff_against).resolve(), panel_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
