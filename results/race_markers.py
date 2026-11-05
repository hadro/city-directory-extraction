"""PIPELINE #37: how race markers were printed, volume by volume, over the round-13 records.

SUPERSEDED for the count (2026-11-04, later the same day): this is the dig that found the problem,
and it counts the model's raw field. The fix is built: the sidecars' race_marker / star_meaning
claims (data_prep/survey_race_markers.py) and assemble_records' race_designation_resolved, measured
by results/race_rule.py -- 26,107 usable rows in 63 volumes. The sets below are the dig's first
guesses and are wrong in two places: Reynolds' Williamsburgh star (0044-0048) and micro 0043 are
RACE (their key pages say so), and 0039/0040/0042's "star" is the OCR's reading of a raised E.

Two steps. `tally` reads every tier's usable rows (slow, ~6 min) and writes the per-volume counts of
each distinct `race_designation` value to results/race_markers_tally.json. `report` classifies them
from that file and writes results/race_markers.json.

    python3 -I results/race_markers.py tally
    python3 -I results/race_markers.py report

The classification is by the volume's own evidence, not by the model's field alone:
- TEXT: a textual form of "colored" ((col'd), (col.), colored, ...), strict regex below. Printed that
  way by Doggett, Trow 1857-65, Rode, Lain 1858-71, Smith, Longworth, and the Consolidated
  microfilm.
- STAR_LEGEND: a bare `*` in a volume whose own printed key says `*` = colored people (read from the
  sidecar's front-matter text): Ogden 1839, Spooner 1843/1848, Hearnes 1850/1852 and the Spooner-run
  microfilm that carry the NOTE.
- STAR_UNREAD: a bare `*` in a volume of the same publisher run, key page not read.
  (STAR_* count the model's `race_designation`; the headline estimate in `report` counts `name_mark`
  instead, because the model leaves the field empty on about half the stars in the star-is-race run.)
- STAR_OTHER: every other bare `*`. Read on lines in Trow 1876 and 1903-1914 and Lain 1884-89 it
  marks FIRMS (an advertiser's star: `*Boston Clock Co`), and in the Consolidated microfilm
  (micro_IABROOKLYN_0039/0040/0042) it sits on Eastern District addresses (Calyer, Metropolitan av):
  Eastern District, not race.
- NOISE: whatever else (`(Ill)`, `collr`, `(German)`, `wid Max`, surnames that start with Col...).
"""
import collections
import glob
import gzip
import json
import re
import sys

TIERS = [
    ("reocr", "data/records/4b-100k+guard", "results/records_4b-100k+guard.json"),
    ("damaged", "data/records_books_damaged/4b-100k+guard", "results/records_books_damaged.json"),
    ("first_clean", "data/records_books_first_clean/4b-100k+guard", "results/records_books_first_clean.json"),
]
TALLY = "results/race_markers_tally.json"

TEXT = re.compile(r"^\(?\s*(col(or(ed|'d)?|oured|'d\.?|d\.?|r|l)?|co'd|color'd|cold)\s*\.?\s*\)?$", re.I)
STARS = {"*", "•", "»", "+"}

# Volumes whose own printed key says `*` = colored (sidecar front-matter reads, 2026-09 to 2026-10).
STAR_LEGEND = {
    "brooklyndirector00ogde", "brooklynalphabet1843unse", "brooklyncitydire1848teal",
    "hearnesbrooklync1850unse", "hearnesbrooklync1852unse",
    "micro_IABROOKLYN_0007", "micro_IABROOKLYN_0009", "micro_IABROOKLYN_0010",
    "micro_IABROOKLYN_0011", "micro_IABROOKLYN_0012", "micro_IABROOKLYN_0015",
    "micro_IABROOKLYN_0017", "micro_IABROOKLYN_0025", "micro_IABROOKLYN_0028",
}
# Same Spooner/Hearnes run, star-only volumes, legend not read.
STAR_UNREAD = {
    "micro_IABROOKLYN_0006", "micro_IABROOKLYN_0008", "micro_IABROOKLYN_0020", "micro_IABROOKLYN_0021",
    "micro_IABROOKLYN_0023", "micro_IABROOKLYN_0024", "micro_IABROOKLYN_0027",
}


# Consolidated 1858-60 microfilm and Hope & Henderson: `*` = Eastern District, race is (col'd)/(col.).
EASTERN_DISTRICT_STAR = {"micro_IABROOKLYN_0035", "micro_IABROOKLYN_0039", "micro_IABROOKLYN_0040",
                         "micro_IABROOKLYN_0042"}


def tally():
    out = {}
    for tier, d, summ in TIERS:
        for v, s in json.load(open(summ))["volumes"].items():
            marks = collections.Counter()
            nm = collections.Counter()  # the assembly's own read of a leading mark, vs the model's field
            with gzip.open(f"{d}/{v}.jsonl.gz", "rt") as fh:
                for line in fh:
                    r = json.loads(line)
                    if r.get("usable"):
                        rd = (r.get("race_designation") or "").strip()
                        if rd:
                            marks[rd] += 1
                        if "*" in (r.get("name_mark") or ""):
                            nm["star_in_name_mark"] += 1
                            nm["...and_race_empty" if not rd else "...and_race_set"] += 1
            out[v] = {"tier": tier, "usable": s["usable"], "marks": dict(marks), "name_mark": dict(nm)}
    json.dump(out, open(TALLY, "w"))


def classify(v, m):
    if TEXT.match(m):
        return "TEXT"
    if m in STARS:
        return "STAR_LEGEND" if v in STAR_LEGEND else "STAR_UNREAD" if v in STAR_UNREAD else "STAR_OTHER"
    return "NOISE"


def report():
    d = json.load(open(TALLY))
    total = collections.Counter()
    by_vol = {}
    for v, x in d.items():
        c = collections.Counter()
        for m, n in x["marks"].items():
            c[classify(v, m)] += n
        total.update(c)
        try:
            cat = json.load(open(f"data_prep/survey/ia_{v}.json"))["catalog_says"]["csv"]
            pub, yr = cat.get("publisher"), cat.get("year")
        except Exception:
            pub, yr = None, None
        by_vol[v] = {"tier": x["tier"], "publisher": pub, "year": yr, "usable": x["usable"], **c,
                     "name_mark": x.get("name_mark", {})}
    vols = lambda k: sum(1 for x in by_vol.values() if x.get(k))
    # What a leading `*` means is a property of the volume, not of the model's field: the model sets
    # race_designation="*" wherever it sees one in some volumes and not in others. `name_mark` is the
    # assembly's own read of the printed mark, so the families below count it.
    fam = collections.defaultdict(collections.Counter)
    for v, x in by_vol.items():
        pub = str(x["publisher"]).lower()
        if pub in ("ogden", "spooner", "hearnes"):
            k = "star_is_race_run"  # Ogden/Spooner/Hearnes: key page read in 14 volumes, see STAR_LEGEND
        elif pub == "reynolds":
            k = "star_unknown_reynolds"
        elif v in EASTERN_DISTRICT_STAR:
            k = "star_is_eastern_district"
        elif v.startswith("trowsgeneraldir") or v == "trowsnewyorkcity1876trow":
            k = "star_is_firm_or_advertiser"
        else:
            k = "no_star_convention"
        nm = x["name_mark"]
        fam[k]["volumes"] += 1
        fam[k]["star_in_name_mark"] += nm.get("star_in_name_mark", 0)
        fam[k]["model_set_race_on_them"] += nm.get("...and_race_set", 0)
        fam[k]["TEXT_rows"] += x.get("TEXT", 0)
    race_vols = sum(1 for x in by_vol.values() if x.get("TEXT", 0) >= 5) 
    out = {
        "derived": "2026-11-04", "records": "round 13 (+ #38), 4b-100k+guard",
        "star_families": {k: dict(c) for k, c in fam.items()},
        "volumes_with_5plus_textual_markers": race_vols,
        "totals": dict(total), "volumes_with": {k: vols(k) for k in total},
        # headline: textual forms (all volumes) + stars in the volumes where a star is race (name_mark,
        # not the model's field, which set it on only about half of them)
        "race_marker_rows_estimate": total["TEXT"] + fam["star_is_race_run"]["star_in_name_mark"],
        "race_marker_volumes_estimate": len(
            {v for v, x in by_vol.items() if x.get("TEXT", 0) >= 5}
            | {v for v, x in by_vol.items()
               if str(x["publisher"]).lower() in ("ogden", "spooner", "hearnes")
               and x["name_mark"].get("star_in_name_mark", 0) >= 5}),
        "volumes": by_vol,
    }
    json.dump(out, open("results/race_markers.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "volumes"}, indent=1))


if __name__ == "__main__":
    {"tally": tally, "report": report}[sys.argv[1]]()
