#!/usr/bin/env python3
"""
Correct the Minneapolis 1900 gold against the page images (2026-11-09).

    python3 data_prep/minneapolis_page_check.py            # writes the gold, backup and change log
    python3 data_prep/minneapolis_page_check.py --dry-run  # prints the changes only

data/minneapolis_eval.jsonl's lines are DirCity's transcriptions (harvest_minneapolis.py), not the
page. Read against scans of its three pages -- 0113 and 0362 from github.com/adamrangwala/
Minneapolis-1900-directory-ocr @3f84ebb (data/raw_images/, MIT), and 0562 stitched from Hennepin
County Library's viewer tiles (pg_seq 562) by hadro in the browser, saved as
data/minneapolis/scans_hcl/1900_0562.jpg -- the transcription differs from the page in four ways:

  * DITTO MARKS. The page prints a ditto mark before every line that repeats the surname above
    (`" Arthur R`), as polk1917 and trow1913 do; the transcription drops all of them. Per the
    labelling contract (GROUND_TRUTH_HANDOFF), the line and `name` keep the mark verbatim, written
    `" ` as in polk1917's gold.
  * WORDS. Fourteen differences, among them two house numbers (521 for 527, 924 for 224), a
    whole street (`Riverside av` for `13th av s`), and `llth` for `11th` twice.
  * A LOST HEADLINE. Row 171 began mid-entry (`Novelty Mnfg Co 202 Washn av s, ...`): the page
    prints `GOLLING BENJAMIN C, PROPR PHOTO Novelty Mnfg Co ...`, so the line and its record are
    rebuilt (labelled as this set labels its other capitals entries, rows 220 and 224).
  * Six `name`s still holding a surname the line does not print (missed by the 2026-10-17 fix),
    or out of printed order (`Lena Mrs`).

Where the page itself is damaged or clipped (row 177's house number, row 206's `3__2`, row 183's
`262` at the column rule) the transcription is left as it was.

The reading behind NO_MARK and TEXT_FIXES was done by eye from the scans, column band by band,
with every uncertain word zoomed at full resolution (2026-11-09). A person should re-check it
against the scans before anything is published.

The script always starts from the untouched backup (data/_gold_backup/minneapolis_eval.2026-11-09.jsonl),
so re-running it after a change here rebuilds the whole correction.
"""
import argparse
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "data" / "minneapolis_eval.jsonl"
BACKUP = REPO / "data" / "_gold_backup" / "minneapolis_eval.2026-11-09.jsonl"     # the transcription as harvested
SCANS = {"1900_0113.txt": "github.com/adamrangwala/Minneapolis-1900-directory-ocr@3f84ebb data/raw_images/1900_0113.jpg",
         "1900_0362.txt": "github.com/adamrangwala/Minneapolis-1900-directory-ocr@3f84ebb data/raw_images/1900_0362.jpg",
         "1900_0562.txt": "Hennepin County Library viewer, pg_seq 562, tiles stitched: data/minneapolis/scans_hcl/1900_0562.jpg"}

# rows (0-based, file order) that open with a surname on the page, so carry no mark; every other
# row of the checked pages opens with a ditto mark
CHECKED = {"1900_0113.txt": range(0, 76), "1900_0362.txt": range(76, 154), "1900_0562.txt": range(154, 230)}
NO_MARK = {0, 3, 5, 7, 14, 30, 31, 32, 33, 38, 47, 48, 52, 54, 57, 59, 60, 62, 64, 66, 67,   # page 0113
           76, 118, 149,                                                                       # page 0362
           154, 163, 166, 168, 169, 171, 178, 179, 180, 181, 182, 183, 186, 189, 191, 194,      # page 0562
           206, 220, 224, 228, 229}

# (row, transcribed, printed): replaced in raw_line and in every record field that holds it
TEXT_FIXES = [
    (19, "Master In Chancery", "Master in Chancery"),
    (23, "mfgrs agt", "mnfrs agt"),
    (45, "1430 n 6th", "1430 n e 6th"),
    (63, "521 Humboldt", "527 Humboldt"),
    (76, "802 2d av n", "802 2d av s"),
    (90, "1911 s 25½", "1911 e 25½"),
    (94, "Lella", "Lelia"),
    (103, "Mary L, (wid Wm)", "Mary L (wid Wm)"),
    (110, "1611 n e 14th", "1611 n e 5th"),
    (129, "2535 Riverside av", "2535 13th av s"),
    (140, "924 s 8th", "224 s 8th"),
    (142, "trav agt r 2746", "trav agt, r 2746"),
    (154, "507 llth av s", "507 11th av s"),
    (221, "513 llth av n", "513 11th av n"),
]

# names that still hold a surname the line does not print, or not in printed order (before the mark goes on)
NAME_FIXES = {58: "A & Co (Archibald Abercromby)", 96: "L E estate of", 138: "Charles E",
              155: "Jacob W (Harris & Goldstein)", 190: "Frederick (Gonnella & Balestra)", 201: "Mrs Lena"}

# whole rows rebuilt from the page
ROW_FIXES = {171: ("GOLLING BENJAMIN C, PROPR PHOTO Novelty Mnfg Co 202 Washn av s, b 630 Lyndale pl. "
                   "(See adv under Photographers.)",
                   {"name": "GOLLING BENJAMIN C", "is_business": False,
                    "address": "PROPR PHOTO Novelty Mnfg Co 202 Washn av s",
                    "home_address": "630 Lyndale pl. (See adv under Photographers.)"})}

MARK = '" '


def correct(rows):
    """-> (rows, [(row, field, before, after)])"""
    out, log = [json.loads(json.dumps(r)) for r in rows], []
    for i, old, new in TEXT_FIXES:
        r = out[i]
        assert r["raw_line"].count(old) == 1, (i, old, r["raw_line"])
        r["raw_line"] = r["raw_line"].replace(old, new)
        log.append((i, "raw_line", old, new))
        for k, v in r["record"].items():
            if isinstance(v, str) and old in v:
                r["record"][k] = v.replace(old, new)
                log.append((i, k, v, r["record"][k]))
    for i, name in NAME_FIXES.items():
        log.append((i, "name", out[i]["record"]["name"], name))
        out[i]["record"]["name"] = name
    for i, (line, fields) in ROW_FIXES.items():
        r = out[i]
        log.append((i, "raw_line", r["raw_line"], line))
        r["raw_line"] = line
        for k in r["record"]:
            new = fields.get(k, False if k == "is_business" else "")
            if r["record"][k] != new:
                log.append((i, k, r["record"][k], new))
                r["record"][k] = new
    for page, rng in CHECKED.items():
        for i in rng:
            r = out[i]
            assert r["context"]["source"] == page, (i, r["context"]["source"])
            r["context"]["checked_against_page"] = SCANS[page]
            if i in NO_MARK:
                continue
            assert r["record"]["name"] and r["raw_line"].startswith(r["record"]["name"]), (i, r["record"]["name"])
            r["raw_line"] = MARK + r["raw_line"]
            r["record"]["name"] = MARK + r["record"]["name"]
            log.append((i, "mark", "", MARK.strip()))
    for r in out:
        r["context"].setdefault("checked_against_page", None)
    return out, log


def transcription():
    """The rows as harvested, before any of this: the backup, made on the first run."""
    if not BACKUP.exists():
        shutil.copy(GOLD, BACKUP)
    rows = [json.loads(line) for line in open(BACKUP, encoding="utf-8") if line.strip()]
    assert not rows[1]["raw_line"].startswith(MARK), "the backup must be the uncorrected transcription"
    return rows


def self_test():
    out, log = correct(transcription())
    assert out[1]["raw_line"] == '" Smith, driver Wells, Fargo & Co Express, b 2915 Clinton av'
    assert out[1]["record"]["name"] == '" Smith' and out[0]["record"]["name"] == "Abbett Minnie"
    assert out[63]["raw_line"] == '" Mathias, tmstr, r 527 Humboldt av n'
    assert out[58]["record"]["name"] == '" A & Co (Archibald Abercromby)'
    assert out[171]["raw_line"].startswith("GOLLING BENJAMIN C, PROPR PHOTO Novelty")
    assert out[172]["record"]["name"] == '" Rev Charles H' and out[201]["record"]["name"] == '" Mrs Lena'
    assert all(r["context"]["checked_against_page"] for r in out)
    print("self-test ok:", sum(1 for x in log if x[1] == "mark"), "marks,", len(TEXT_FIXES), "text fixes")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    out, log = correct(transcription())
    for i, field, before, after in log:
        if field != "mark":
            print(f"{i:4} {field:16} {before!r} -> {after!r}")
    print(sum(1 for x in log if x[1] == "mark"), "ditto marks put back;",
          sum(1 for r in out if r["context"]["checked_against_page"]), "rows checked against the page")
    if a.dry_run:
        return
    with open(GOLD, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tsv = REPO / "results" / "minneapolis_page_check_2026-11-09.tsv"
    with open(tsv, "w", encoding="utf-8") as fh:
        fh.write("row\tfield\tbefore\tafter\n")
        for i, field, before, after in log:
            fh.write(f"{i}\t{field}\t{before}\t{after}\n")
    print("wrote", GOLD.relative_to(REPO), "from", BACKUP.relative_to(REPO), "| log", tsv.relative_to(REPO))


if __name__ == "__main__":
    main()
