#!/usr/bin/env python3
"""Pick the next N un-backfilled Trow volumes, sample them (front matter + 2 listing
pages), and emit a read-packet JSON for the gated Sonnet fan-out
(data_prep/trow_fanout.workflow.js).

Usage:  trow_fanout_prep.py [N]   ->   prints packet JSON (list) to stdout.

Idempotent: selects only Trow rows with a BLANK column_count (skips finished ones),
and skips the REVIEW-flagged 1853 volume, blank-id rows, and held-out/NYU eval volumes.
Sampling failures (e.g. IIIF timeouts) are skipped and reported on stderr so the batch
can be re-run to pick them up next time. The companion workflow reads this packet via `args`.

KNOWN LIMITATION: the sampler slugifies its output dir by source/publisher/year, so
same-year "part" volumes (…p1/p2/p3…) collide on one output dir and overwrite each other.
Read distinct (non-part) volumes here; reliable per-part reads need a sampler slugify fix
that includes the id. (Post-1900 Trow parts are uniformly col=3, so col-count needs no read.)
"""
import csv, glob, json, os, re, subprocess, sys

REPO_CD = "/Users/joshhadro/github/city-directory-extraction"
REPO_DP = "/Users/joshhadro/github/directory-pipeline"
MASTER  = f"{REPO_CD}/data_prep/master_directories.csv"
SAMPLER = f"{REPO_DP}/sources/sample_directories.py"
PY      = f"{REPO_DP}/.venv/bin/python"
OUT     = f"{REPO_DP}/output"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10

rows = list(csv.DictReader(open(MASTER)))

def eligible(r):
    if not (r.get("id") or "").strip():                         return False   # malformed row (blank id)
    if "trow" not in (r.get("publisher", "") or "").lower():    return False
    if (r.get("column_count", "") or "").strip():               return False   # already done
    n = (r.get("notes", "") or "").lower(); inst = (r.get("holding_institution", "") or "").lower()
    if "review" in n or "nyu" in inst or "held" in n or "eval" in n: return False
    return True

batch = [r for r in rows if eligible(r)][:N]
if not batch:
    print("[]"); sys.exit(0)

tmp = "/tmp/trow_fanout_batch.csv"
with open(tmp, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(batch)

# Sample (the sampler resumes, so re-runs are cheap). Capture stderr for total canvas counts.
log = subprocess.run([PY, SAMPLER, tmp, "--front", "20", "-k", "2", "--width", "1800"],
                     capture_output=True, text=True).stderr
totals = {m.group(1): int(m.group(2))
          for m in (re.match(r"\[(\S+)\]\s+(\d+)\s+canvases", ln) for ln in log.splitlines()) if m}

packet, failed = [], []
for r in batch:
    vid = r["id"]
    dirs = [d for d in glob.glob(f"{OUT}/*") if os.path.isdir(d) and glob.glob(f"{d}/0021_*{vid}*")]
    if not dirs:
        failed.append(vid); continue                       # sampling failed -> retry next batch
    d = dirs[0]; slug = os.path.basename(d)
    def listing(seq):
        g = glob.glob(f"{d}/{seq}_*")
        if not g: return None, None
        return g[0], int(re.search(r"_(\d+)\.jp2", g[0]).group(1))
    p1, l1 = listing("0021"); p2, l2 = listing("0022")
    if not p1: failed.append(vid); continue
    packet.append({"id": vid, "year": r.get("year", ""), "dir": slug,
                   "total": totals.get(slug), "p1": p1, "l1": l1, "p2": p2, "l2": l2})

if failed:
    print(f"[prep] {len(failed)} volumes failed sampling (retry next batch): {failed}", file=sys.stderr)
print(json.dumps(packet))
