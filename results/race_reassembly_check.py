"""PIPELINE #37: after a re-assembly, nothing but race_designation_resolved and district changed,
and district only None -> Eastern on a starred line of an eastern_district volume.

Take the copy BEFORE re-assembling (APFS clones, no extra disk):
    mkdir <B>; for t in records records_books_damaged records_books_first_clean; do
      mkdir -p <B>/$t && cp -c -R data/$t/4b-100k+guard <B>/$t/; done
    cp results/records_4b-100k+guard.json results/records_books_damaged.json \
       results/records_books_first_clean.json <B>/
then re-assemble the three tiers and run
    python3 -I results/race_reassembly_check.py <B>

Run 2026-11-04: "153 volumes {'rows': 15776206, 'row_count_mismatch': 0, 'district_added': 14560}",
no PROBLEM or SUMMARY DIFF lines. It checks the race change only: a re-assembly that also changes
other fields on purpose will report them.
"""
import collections, gzip, json, sys
from concurrent.futures import ProcessPoolExecutor
sys.path[:0] = ["postprocess", "eval", "data_prep"]
from assemble_records import race_resolved, starred

B = sys.argv[1]
T = [("records", "data/records/4b-100k+guard", "results/records_4b-100k+guard.json"),
     ("records_books_damaged", "data/records_books_damaged/4b-100k+guard", "results/records_books_damaged.json"),
     ("records_books_first_clean", "data/records_books_first_clean/4b-100k+guard", "results/records_books_first_clean.json")]


def one(job):
    sub, d, v = job
    book = json.load(open(f"data_prep/survey/ia_{v}.json")).get("book_says", {})
    form = (book.get("race_marker") or {}).get("value")
    east = (book.get("star_meaning") or {}).get("value") == "eastern_district"
    c = collections.Counter()
    old = gzip.open(f"{B}/{sub}/4b-100k+guard/{v}.jsonl.gz", "rt")
    new = gzip.open(f"{d}/{v}.jsonl.gz", "rt")
    for lo, ln in zip(old, new):
        a, b = json.loads(lo), json.loads(ln)
        c["rows"] += 1
        res = b.pop("race_designation_resolved")
        if res != race_resolved(b["race_designation"], b["name_mark"], b["raw_line"], form):
            c["resolved_mismatch"] += 1
        if a["district"] != b["district"]:
            ok = a["district"] is None and b["district"] == "Eastern" and east \
                and starred(b["name_mark"], b["raw_line"])
            c["district_added" if ok else "district_bad"] += 1
        a.pop("district"); b.pop("district")
        if a != b:
            c["other_field_changed"] += 1
            if c["other_field_changed"] <= 3:
                print(v, [k for k in set(a) | set(b) if a.get(k) != b.get(k)], file=sys.stderr)
    c["row_count_mismatch"] += bool(old.readline()) or bool(new.readline())
    return v, c


if __name__ == '__main__':
    # tiers by their summary's volume list: data/records/4b-100k+guard also holds stale run-1 files
    jobs = [(sub, d, v) for sub, d, s in T for v in json.load(open(s))["volumes"]]
    tot = collections.Counter()
    with ProcessPoolExecutor(6) as ex:
        for v, c in ex.map(one, jobs):
            tot.update(c)
            if c["district_bad"] or c["other_field_changed"] or c["resolved_mismatch"] or c["row_count_mismatch"]:
                print("PROBLEM", v, dict(c))
    print(len(jobs), "volumes", dict(tot))
    for sub, d, s in T:
        a, b = json.load(open(f"{B}/{s.split('/')[-1]}")), json.load(open(s))
        for v in b["volumes"]:
            x, y = dict(a["volumes"][v]), dict(b["volumes"][v])
            y.pop("race"); x["ditto"] = {k: w for k, w in x["ditto"].items() if k != "district_eastern"}
            y["ditto"] = {k: w for k, w in y["ditto"].items() if k != "district_eastern"}
            if x != y:
                print("SUMMARY DIFF", v, [k for k in y if x.get(k) != y.get(k)])
    print("summaries compared")
