#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Survey Phase 1 -- the OCR harvest. Every IA volume's hOCR, fetched once, reduced to a
word dump, filtered into candidate lines, and deleted. See docs/SURVEY_PLAN.md "Phase 1".

    python3 data_prep/survey_harvest.py --plan              # what would run, and the byte budget
    python3 data_prep/survey_harvest.py                     # harvest everything not yet done
    python3 data_prep/survey_harvest.py --ids 1857BPL       # one volume
    python3 data_prep/survey_harvest.py --rederive          # re-filter from the dumps, no network
    python3 data_prep/survey_harvest.py --report            # summary + dead-ocr flags
    python3 data_prep/survey_harvest.py --self-test         # offline

Serial, one volume at a time, resumable: a volume whose sidecar says `harvest.status == ok`
and whose dump is on disk is skipped. Kill it at any point and re-run.

Per volume, under data/survey_ocr/ (gitignored):

    <id>_words.jsonl.gz     THE ASSET. One record per hOCR leaf, every word with its box and
                            x_wconf, grouped by ocr_line. Lossless for everything this repo reads
                            out of hOCR (`hocr_lines` is derived from `hocr_words` and nothing
                            else), at ~7.6% of the hOCR's bytes -- measured on 1857BPL, 60.5 MB
                            of hOCR -> 4.6 MB gzipped, so ~1.6 GB for the 21.7 GB corpus.
    <id>_lines.jsonl.gz     ia_volume_to_jsonl.sweep() over the dump, default settings: the
                            `{raw_line, context, record}` file eval/qwen_predict.py reads.
    <id>_dropped.txt.gz     every line the filters rejected, with its reason. Together with
                            _lines it accounts for every candidate line.

Why a word dump and not just the filtered lines the plan first named: the filters are not
finished. The banner normalizer changed 1906BPL's kept count by 6,091 lines on 2026-09-13, and
the [publisher=] tag in every line comes from a CSV column the survey is actively correcting
(the Spooner series). A harvest of filtered lines would have to re-download 21.7 GB the next time
either moves. From the dump, `--rederive` redoes all 184 volumes offline.

Deliberately NOT written to data/<id>_lines.jsonl: several of those files are pinned artifacts
that published figures were measured against (docs/BANNER_CORRECTION.md). The harvest never
touches them.

Eval holdout. A full-volume harvest contains every gold page by construction. Rather than cut
those leaves -- Phase 2 needs whole volumes to find listing bounds -- they are MARKED, in the
dump record and in every emitted line (`context.eval_holdout`: "gold", "adjacent", or "volume"
for a whole held-out volume such as 1897BPL), so no
consumer has to remember to filter. The gold leaf is not trusted from the jp2 filename: the
gold lines are matched against the dump text and the best-matching leaf wins, with both numbers
recorded. HANDOFF.md: "never trust canvas arithmetic to exclude a gold page; verify after
downloading." The neighbours of the verified leaf are marked "adjacent" as a margin.

The sidecar (data_prep/survey/ia_<id>.json) gets a `harvest` block: status, hOCR sha1 as
downloaded vs as censused (a mismatch means IA re-derived the OCR since 2026-09-12), counts,
filter outcome, and the git commit the filters ran at. Status codes are the failure register's:
ok · no-hocr · fetch-failed · derive-failed; `--report` adds dead-ocr (chars per content leaf an order of
magnitude below the volume's OCR-engine class).
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import gzip
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

from ia_volume_to_jsonl import (MIN_CHARS_LEAF, Item, hocr_words, lookup_master,  # noqa: E402
                                page_dims, sweep, tag_publisher, words_to_lines)
from verify_harvest_leakage import BANNED_IA_ITEMS, gold_pages, page_id  # noqa: E402

SIDECARS = HERE / "survey"
OUT = REPO / "data" / "survey_ocr"
CACHE = REPO / "data" / "ia_cache"
DL = "https://archive.org/download"
UA = "city-directory-survey/1.0 (+research; serial, one volume at a time)"

DEAD_OCR_RATIO = 0.1     # chars/content-leaf below this share of the engine-class median
HOLDOUT_WINDOW = 3       # search this many leaves either side of the jp2 number for the gold leaf


# ==============================================================================================
# The dump
# ==============================================================================================
class WordDump:
    """Stands in for ia_volume_to_jsonl.Item inside sweep(): same `page_lines(leaf)` contract.

    Reads the gzip SEQUENTIALLY -- sweep walks leaves in ascending order, so a forward cursor
    keeps memory at one leaf rather than a whole 2,480-leaf Trow. A backwards request reopens.
    """

    def __init__(self, path: Path, ident: str = ""):
        self.path, self.ident = path, ident
        self._fh = None
        self._rec = None

    def _open(self):
        if self._fh:
            self._fh.close()
        self._fh = gzip.open(self.path, "rt", encoding="utf-8")
        self._rec = None

    def records(self):
        with gzip.open(self.path, "rt", encoding="utf-8") as fh:
            for line in fh:
                yield json.loads(line)

    def page_lines(self, leaf: int):
        if self._fh is None or (self._rec is not None and self._rec["leaf"] > leaf):
            self._open()
        while self._rec is None or self._rec["leaf"] < leaf:
            line = self._fh.readline()
            if not line:
                return None, None
            self._rec = json.loads(line)
        if self._rec["leaf"] != leaf:
            return None, None
        dims = tuple(self._rec["page_size"]) if self._rec["page_size"] else None
        return words_to_lines(self._rec["lines"]), dims

    def close(self):
        if self._fh:
            self._fh.close()


def replica_urls(ident: str, filename: str) -> list:
    """Direct URLs on each server holding the item, from IA's metadata endpoint.

    Needed because the archive.org/download redirector can pick a storage node that answers 500
    for one item for many minutes on end, while the item's own replicas serve it fine. Measured
    2026-09-22: micro_IABROOKLYN_0003 failed 4/4 through the redirector over ~8 minutes, while a
    curl to ia601602.us.archive.org returned all 2,010,792 bytes at the same time.
    """
    try:
        req = urllib.request.Request(f"https://archive.org/metadata/{ident}",
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            m = json.load(r)
        servers = m.get("workable_servers") or [s for s in (m.get("d1"), m.get("d2")) if s]
        return [f"https://{s}{m['dir']}/{filename}" for s in servers]
    except Exception:                                      # noqa: BLE001 - fallback only
        return []


def download(url: str, dest: Path, retries: int = 4, fallbacks=()) -> tuple[str, int]:
    """Stream `url` to `dest` via a .part file; return (sha1, bytes). Never holds it in memory:
    the largest volume is 1.6 GB. Each attempt tries `url` and then every fallback (replica)
    before backing off."""
    urls = [url, *fallbacks]
    last = None
    for attempt in range(retries * len(urls)):
        url = urls[attempt % len(urls)]
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            h, n = hashlib.sha1(), 0
            with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as out:
                want = int(r.headers.get("Content-Length") or 0)
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
            if want and n != want:
                raise IOError(f"short read: {n} of {want} bytes")
            part.rename(dest)
            return h.hexdigest(), n
        except Exception as e:                             # noqa: BLE001 - retried, then surfaced
            last = e
            part.unlink(missing_ok=True)
            host = url.split("/")[2]
            if (attempt + 1) % len(urls):
                print(f"    ! {e} from {host} -- trying the next replica", file=sys.stderr)
                continue
            wait = 30 * (2 ** (attempt // len(urls)))
            print(f"    ! {e} from {host} -- round {attempt // len(urls) + 1}/{retries} "
                  f"failed on all {len(urls)} sources, retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"fetch failed after {retries} rounds of {len(urls)} sources: "
                       f"{urls[0]} ({last})")


def sha1_file(p: Path) -> tuple[str, int]:
    h, n = hashlib.sha1(), 0
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def write_dump(item: Item, hocr: Path, dest: Path) -> dict:
    """One JSON record per pageindex leaf, in leaf order, empty leaves included -- so the dump's
    leaf count IS the volume's, and leaf L here is hOCR pageindex L is IIIF canvas L."""
    idx = item.index
    tmp = dest.with_suffix(".tmp")
    st = collections.Counter()
    confs = []
    with open(hocr, "rb") as src, gzip.open(tmp, "wt", encoding="utf-8") as out:
        for leaf, (a0, a1, b0, b1) in enumerate(idx):
            src.seek(b0)
            markup = src.read(b1 - b0).decode("utf-8", "replace")
            lines = hocr_words(markup)
            dims = page_dims(markup)
            rec = {"leaf": leaf, "page_size": list(dims) if dims else None,
                   "chars": a1 - a0, "lines": lines}
            out.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            nw = sum(len(ws) for ws in lines)
            st["leaves"] += 1
            st["leaves_with_text"] += bool(lines)
            st["content_leaves"] += (a1 - a0) > MIN_CHARS_LEAF
            st["lines"] += len(lines)
            st["words"] += nw
            st["chars"] += sum(len(w[5]) for ws in lines for w in ws)
            st["no_page_size"] += dims is None and bool(lines)
            confs.extend(w[4] for ws in lines for w in ws)
    tmp.rename(dest)
    out = dict(st)
    out["mean_wconf"] = round(statistics.fmean(confs), 1) if confs else None
    out["chars_per_content_leaf"] = round(st["chars"] / st["content_leaves"]) \
        if st["content_leaves"] else 0
    return out


# ==============================================================================================
# Eval holdout
# ==============================================================================================
_TOK = re.compile(r"[A-Za-z]{3,}")


def gold_by_volume() -> dict:
    """{ia id (lowercase): {jp2 number: [gold raw_line, ...]}, plus the eval files naming each}."""
    pages = gold_pages()
    want = {pid for pid in pages if pid[0] == "ia"}
    lines = collections.defaultdict(lambda: collections.defaultdict(list))
    sets = collections.defaultdict(set)
    data = REPO / "data"
    for path in sorted(data.glob("*_eval.jsonl")):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                ctx = d.get("context") or {}
                img = ctx.get("image")
                if img and img != "?":
                    pid = page_id(img)
                    if pid not in want:
                        continue
                    ident, leaf = pid[1], int(pid[2])
                elif ctx.get("ia_id") and isinstance(ctx.get("leaf"), int):
                    # built by ia_volume_to_jsonl itself (micro13_*, 1906BPL_sample500): already
                    # an hOCR leaf, and verification should find it at offset 0
                    ident, leaf = ctx["ia_id"].lower(), ctx["leaf"]
                else:
                    continue
                lines[ident][leaf].append(d.get("raw_line") or "")
                sets[ident].add(path.name)
    return {k: {"leaves": dict(v), "sets": sorted(sets[k])} for k, v in lines.items()}


def locate_holdout(dump: WordDump, gold: dict) -> tuple[dict, list]:
    """Verify each gold jp2 number against the dump text. Returns ({leaf: tag}, evidence)."""
    want = {}
    for jp2, glines in gold["leaves"].items():
        toks = [set(_TOK.findall(g.lower())) for g in glines]
        want[jp2] = [t for t in toks if t]
    lo = min(want) - HOLDOUT_WINDOW
    hi = max(want) + HOLDOUT_WINDOW
    text = {}
    for rec in dump.records():
        if lo <= rec["leaf"] <= hi:
            text[rec["leaf"]] = set(_TOK.findall(
                " ".join(w[5] for ws in rec["lines"] for w in ws).lower()))
    tags, evidence = {}, []
    for jp2, toks in sorted(want.items()):
        def score(leaf):
            vocab = text.get(leaf, set())
            return sum(len(t & vocab) / len(t) >= 0.5 for t in toks) / max(len(toks), 1)
        cands = range(jp2 - HOLDOUT_WINDOW, jp2 + HOLDOUT_WINDOW + 1)
        best = max(cands, key=lambda L: (score(L), -abs(L - jp2)))
        s = score(best)
        # An unconvincing match marks the jp2 number itself as well: a false "gold" costs one
        # leaf of training data, a missed one is a leak.
        chosen = {best} if s >= 0.5 else {best, jp2}
        for L in chosen:
            tags[L] = "gold"
        evidence.append({"jp2": jp2, "leaf": best, "match": round(s, 2),
                         "gold_lines": len(toks), "offset": best - jp2})
    for L in list(tags):
        for n in (L - 1, L + 1):
            tags.setdefault(n, "adjacent")
    return tags, evidence


# ==============================================================================================
# Per volume
# ==============================================================================================
def sidecar_path(ident: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in ident)[:90]
    return SIDECARS / f"ia_{safe}.json"


def load_volumes() -> list:
    vols = []
    for p in sorted(SIDECARS.glob("ia_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        dv = d.get("derivatives") or {}
        vols.append({"id": d["id"], "path": p, "doc": d,
                     "bytes": dv.get("hocr_bytes") or 0, "sha1": dv.get("hocr_sha1"),
                     "engine": ((d.get("catalog_says") or {}).get("ia") or {}).get("ocr")})
    return sorted(vols, key=lambda v: (v["bytes"], v["id"]))


def git_rev() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                             capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "data_prep/"], cwd=REPO,
                               capture_output=True, text=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except Exception:                                      # noqa: BLE001
        return "unknown"


def paths(ident: str) -> dict:
    return {k: OUT / f"{ident}_{k}" for k in
            ("words.jsonl.gz", "lines.jsonl.gz", "dropped.txt.gz")}


def derive(ident: str, holdout: dict) -> dict:
    """Filter the dump into candidate lines. Offline; the same code path as a live harvest."""
    p = paths(ident)
    dump = WordDump(p["words.jsonl.gz"], ident)
    content = [r["leaf"] for r in dump.records() if r["chars"] > MIN_CHARS_LEAF]
    catalog_pub, year = lookup_master(ident)
    publisher, why = tag_publisher(catalog_pub)
    tmp_l = p["lines.jsonl.gz"].with_suffix(".tmp")
    tmp_d = p["dropped.txt.gz"].with_suffix(".tmp")
    with gzip.open(tmp_l, "wt", encoding="utf-8") as out_fh, \
            gzip.open(tmp_d, "wt", encoding="utf-8") as dropped_fh:
        stats, reasons, ad_scores, ditto, band = sweep(
            dump, publisher, year, content, True, None, True, dropped_fh, out_fh,
            holdout=holdout)
    dump.close()
    tmp_l.rename(p["lines.jsonl.gz"])
    tmp_d.rename(p["dropped.txt.gz"])
    cand = stats["raw"] - stats["joins"]
    return {
        "publisher_tag": publisher, "publisher_tag_note": why or None, "year_tag": year or None,
        "hocr_lines": stats["raw"], "wrap_joins": stats["joins"], "candidates": cand,
        "kept": stats["kept"], "keep_rate": round(stats["kept"] / cand, 4) if cand else None,
        "dropped": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "ditto_marks": ditto["marks"] if ditto else [],
        "ditto_applied": ditto["applied"] if ditto else 0,
        "band": band,
        "top_ad_leaves": [leaf for leaf, _ in sorted(ad_scores, key=lambda kv: -kv[1])[:10]],
        "filters_at": git_rev(),
        "derived": _dt.date.today().isoformat(),
    }


def harvest_one(v: dict, gold: dict, keep_hocr: bool) -> dict:
    ident = v["id"]
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    p = paths(ident)
    item = Item(ident, CACHE)
    hocr = CACHE / f"{ident}_hocr.html"
    preexisting = hocr.exists() and hocr.stat().st_size > 0
    h = {"fetched": _dt.date.today().isoformat()}
    t0 = time.time()
    try:
        _ = item.index                                     # pageindex first: small, and required
        if preexisting:
            sha, n = sha1_file(hocr)
            h["hocr_source"] = "cache"
        else:
            sha, n = download(f"{DL}/{ident}/{ident}_hocr.html", hocr,
                              fallbacks=replica_urls(ident, f"{ident}_hocr.html"))
            h["hocr_source"] = "download"
    except Exception as e:                                 # noqa: BLE001
        return {"status": "fetch-failed", "error": str(e)[:300], **h}
    h.update({"hocr_sha1": sha, "hocr_bytes": n,
              "sha1_matches_census": (sha == v["sha1"]) if v["sha1"] else None,
              "fetch_s": round(time.time() - t0)})
    if v["sha1"] and sha != v["sha1"]:
        print(f"    ! sha1 differs from the 2026-09-12 census -- IA re-derived this hOCR",
              file=sys.stderr)

    try:
        h["dump"] = write_dump(item, hocr, p["words.jsonl.gz"])
        h["status"] = "no-hocr" if h["dump"]["words"] == 0 else "ok"
        holdout, evidence = {}, []
        g = gold.get(ident.lower())
        if g:
            holdout, evidence = locate_holdout(WordDump(p["words.jsonl.gz"]), g)
        if ident.lower() in BANNED_IA_ITEMS:
            # a held-out VOLUME (verify_harvest_leakage.BANNED_IA_ITEMS): every leaf is off
            # limits, and the verified gold leaves keep their sharper tag
            g = g or {"sets": [], "leaves": {}}

            for L in range(h["dump"]["leaves"]):
                holdout.setdefault(L, "volume")
        if holdout:
            _tag_dump(p["words.jsonl.gz"], holdout)
            h["eval_holdout"] = {
                "sets": g["sets"], "evidence": evidence,
                "gold_leaves": sorted(L for L, t in holdout.items() if t == "gold"),
                "adjacent_leaves": sorted(L for L, t in holdout.items() if t == "adjacent"),
                "whole_volume": ident.lower() in BANNED_IA_ITEMS}
        if h["status"] == "ok":
            h["filtered"] = derive(ident, holdout)
        h["words_gz_bytes"] = p["words.jsonl.gz"].stat().st_size
    except Exception as e:                                 # noqa: BLE001 - a bug, not the network
        h.update({"status": "derive-failed", "error": f"{type(e).__name__}: {e}"[:300]})
    finally:
        if not preexisting and not keep_hocr and hocr.exists():
            hocr.unlink()                                  # peak disk stays at one volume
            h["hocr_deleted"] = True
    h["elapsed_s"] = round(time.time() - t0)
    return h


def _tag_dump(path: Path, holdout: dict):
    """Stamp `eval_holdout` into the dump's own leaf records, so the raw asset carries the mark
    too and not only the filtered lines derived from it."""
    tmp = path.with_suffix(".tmp")
    with gzip.open(path, "rt", encoding="utf-8") as src, \
            gzip.open(tmp, "wt", encoding="utf-8") as out:
        for line in src:
            rec = json.loads(line)
            if rec["leaf"] in holdout:
                rec["eval_holdout"] = holdout[rec["leaf"]]
                line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
            out.write(line)
    tmp.rename(path)


def save(v: dict, harvest: dict):
    doc = json.loads(v["path"].read_text(encoding="utf-8"))   # re-read: never clobber others
    doc["harvest"] = harvest
    v["path"].write_text(json.dumps(doc, indent=1), encoding="utf-8")
    v["doc"] = doc


def done(v: dict) -> bool:
    h = v["doc"].get("harvest") or {}
    return h.get("status") in ("ok", "no-hocr") and paths(v["id"])["words.jsonl.gz"].exists()


# ==============================================================================================
# Report
# ==============================================================================================
def engine_class(engine) -> str:
    e = (engine or "none").lower()
    if "tesseract" in e:
        return "tesseract"
    m = re.search(r"abbyy finereader (\d+)", e)
    return f"abbyy-{m.group(1)}" if m else e


def report(vols: list) -> int:
    rows = [(v, v["doc"].get("harvest") or {}) for v in vols]
    st = collections.Counter(h.get("status", "pending") for _, h in rows)
    print(f"{len(vols)} IA volumes: " + ", ".join(f"{k} {n}" for k, n in st.most_common()))
    ok = [(v, h) for v, h in rows if h.get("status") == "ok"]
    if not ok:
        return 0
    by_class = collections.defaultdict(list)
    for v, h in ok:
        by_class[engine_class(v["engine"])].append(h["dump"]["chars_per_content_leaf"])
    med = {c: statistics.median(xs) for c, xs in by_class.items()}
    print("\nchars per content leaf, by OCR engine class (median, n):")
    for c, xs in sorted(by_class.items()):
        print(f"  {c:12} {med[c]:>7,.0f}  n={len(xs)}")
    dead = [(v["id"], h["dump"]["chars_per_content_leaf"], engine_class(v["engine"]))
            for v, h in ok
            if h["dump"]["chars_per_content_leaf"] < DEAD_OCR_RATIO * med[engine_class(v["engine"])]]
    print(f"\ndead-ocr (< {DEAD_OCR_RATIO:.0%} of class median): {len(dead)}")
    for d in dead:
        print(f"  {d[0]:40} {d[1]:>6} chars/leaf  ({d[2]})")
    words = sum(h["dump"]["words"] for _, h in ok)
    kept = sum(h["filtered"]["kept"] for _, h in ok if h.get("filtered"))
    gz = sum(h.get("words_gz_bytes", 0) for _, h in ok)
    hb = sum(h.get("hocr_bytes", 0) for _, h in ok)
    print(f"\n{words:,} words, {kept:,} candidate lines kept; dumps {gz / 1e9:.2f} GB "
          f"from {hb / 1e9:.2f} GB of hOCR ({gz / hb:.1%})")
    changed = [v["id"] for v, h in ok if h.get("sha1_matches_census") is False]
    print(f"hOCR re-derived by IA since the census: {len(changed)} {changed[:10]}")
    held = [(v["id"], h["eval_holdout"]) for v, h in ok if h.get("eval_holdout")]
    print(f"\neval holdout marked on {len(held)} volumes:")
    for ident, e in held:
        offs = collections.Counter(x["offset"] for x in e["evidence"])
        weak = [x for x in e["evidence"] if x["match"] < 0.5]
        print(f"  {ident:40} gold leaves {len(e['gold_leaves']):>3}  jp2->leaf offsets "
              f"{dict(offs)}{'  ⚠ weak match ' + str(len(weak)) if weak else ''}")
    failed = [(v["id"], h.get("error")) for v, h in rows if h.get("status") == "fetch-failed"]
    for f in failed:
        print(f"  fetch-failed {f[0]}: {f[1]}")
    return 0


# ==============================================================================================
def _self_test() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    recs = [{"leaf": 0, "page_size": None, "chars": 0, "lines": []},
            {"leaf": 1, "page_size": [2000, 3000], "chars": 900,
             "lines": [[[100, 100, 200, 118, 90, "Smith"], [210, 100, 400, 118, 80, "John"]]]},
            {"leaf": 3, "page_size": [2000, 3000], "chars": 900,
             "lines": [[[100, 100, 200, 118, 90, "Jones"], [210, 102, 400, 120, 80, "Ann"]]]}]
    p = tmp / "x_words.jsonl.gz"
    with gzip.open(p, "wt") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    d = WordDump(p)
    assert d.page_lines(1) == ([((100, 100, 400, 118), "Smith John")], (2000, 3000))
    assert d.page_lines(2) == (None, None), "a missing leaf is empty, not the next leaf"
    assert d.page_lines(3)[0] == [((100, 100, 400, 120), "Jones Ann")]
    assert d.page_lines(1)[0][0][1] == "Smith John", "a backwards request reopens"
    assert d.page_lines(9) == (None, None)

    # holdout: the jp2 number says 2, the text is on leaf 3 -- the text wins, both neighbours
    # of the verified leaf are marked adjacent, and the jp2 number is NOT gold
    tags, ev = locate_holdout(WordDump(p), {"leaves": {2: ["Jones Ann, cartman"]}, "sets": []})
    assert tags == {3: "gold", 2: "adjacent", 4: "adjacent"}, tags
    assert ev[0]["offset"] == 1 and ev[0]["match"] == 1.0, ev
    # no convincing match anywhere -> the jp2 number is marked too, rather than trusting a guess
    tags, _ = locate_holdout(WordDump(p), {"leaves": {1: ["Zebedee Quux, cartman"]}, "sets": []})
    assert tags[1] == "gold", tags

    _tag_dump(p, {3: "gold"})
    assert [r.get("eval_holdout") for r in WordDump(p).records()] == [None, None, "gold"]
    assert engine_class("ABBYY FineReader 8.0") == "abbyy-8"
    assert engine_class("tesseract 5.3.0-6-g76ae") == "tesseract"
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", default=None, help="comma list of IA identifiers (default: all)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N volumes this run")
    ap.add_argument("--max-mb", type=float, default=None,
                    help="skip volumes whose hOCR exceeds this (the four >500 MB Trows)")
    ap.add_argument("--redo", action="store_true", help="re-harvest volumes already done")
    ap.add_argument("--keep-hocr", action="store_true", help="do not delete downloaded hOCR")
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between volumes")
    ap.add_argument("--rederive", action="store_true",
                    help="re-run the filters over existing dumps; no network")
    ap.add_argument("--plan", action="store_true", help="list what would run and stop")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return _self_test()

    vols = load_volumes()
    if args.ids:
        want = set(args.ids.split(","))
        vols = [v for v in vols if v["id"] in want]
        missing = want - {v["id"] for v in vols}
        if missing:
            print(f"no IA sidecar for: {sorted(missing)}", file=sys.stderr)
    if args.report:
        return report(vols)

    if args.rederive:
        # derive-failed is included: its dump was written before the filters broke, so fixing
        # the bug and re-deriving costs no download
        todo = [v for v in vols if (v["doc"].get("harvest") or {}).get("status")
                in ("ok", "derive-failed") and paths(v["id"])["words.jsonl.gz"].exists()]
        for i, v in enumerate(todo, 1):
            h = v["doc"]["harvest"]
            held = h.get("eval_holdout") or {}
            holdout = {L: "gold" for L in held.get("gold_leaves", [])}
            holdout.update({L: "adjacent" for L in held.get("adjacent_leaves", [])})
            if held.get("whole_volume"):
                for L in range(h["dump"]["leaves"]):
                    holdout.setdefault(L, "volume")
            h["filtered"] = derive(v["id"], holdout)
            h["status"] = "ok"
            h["words_gz_bytes"] = paths(v["id"])["words.jsonl.gz"].stat().st_size
            h.pop("error", None)
            save(v, h)
            print(f"[{i}/{len(todo)}] {v['id']}: kept {h['filtered']['kept']:,}", file=sys.stderr)
        return 0

    todo = [v for v in vols if args.redo or not done(v)]
    if args.max_mb:
        big = [v["id"] for v in todo if v["bytes"] > args.max_mb * 1e6]
        todo = [v for v in todo if v["bytes"] <= args.max_mb * 1e6]
        if big:
            print(f"deferred (> {args.max_mb:.0f} MB): {big}", file=sys.stderr)
    if args.limit:
        todo = todo[:args.limit]
    total = sum(v["bytes"] for v in todo)
    print(f"{len(todo)} volumes to harvest, {total / 1e9:.2f} GB of hOCR "
          f"({len(vols) - len(todo)} done or deferred)", file=sys.stderr)
    if args.plan:
        for v in todo:
            print(f"  {v['bytes'] / 1e6:>8.1f} MB  {v['id']}")
        return 0

    gold = gold_by_volume()
    got = 0
    for i, v in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {v['id']}  {v['bytes'] / 1e6:.0f} MB  "
              f"(done {got / 1e9:.2f} of {total / 1e9:.2f} GB)", file=sys.stderr)
        try:
            h = harvest_one(v, gold, args.keep_hocr)
        except Exception as e:                             # noqa: BLE001 - register, move on
            h = {"status": "fetch-failed", "error": f"{type(e).__name__}: {e}"[:300],
                 "fetched": _dt.date.today().isoformat()}
        save(v, h)
        got += v["bytes"]
        f = h.get("filtered") or {}
        print(f"    {h['status']}  {h.get('dump', {}).get('words', 0):,} words  "
              f"kept {f.get('kept', 0):,} ({f.get('keep_rate') or 0:.1%})  "
              f"{h.get('elapsed_s', 0)}s{'  HOLDOUT' if h.get('eval_holdout') else ''}"
              f"{'  ' + h['error'] if h.get('error') else ''}", file=sys.stderr)
        time.sleep(args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
