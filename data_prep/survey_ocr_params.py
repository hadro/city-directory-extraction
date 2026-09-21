#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Flag volumes where IA ran tesseract with a NON-ENGLISH model, before they reach ingest.

IA's tesseract derive (`ocr_module_version` >= 0.0.2x) runs a script detector per item and,
above a confidence threshold, appends that script's model to the invocation. It records what it
did in three metadata fields that nothing in this repo was reading:

    ocr_detected_script       e.g. "Fraktur"        <- what the detector GUESSED
    ocr_detected_script_conf  e.g. "0.8219"
    ocr_parameters            e.g. "-l eng+Fraktur" <- what tesseract was ACTUALLY RUN WITH

**Read `ocr_parameters`, not `ocr_detected_script`.** Measured over the 48 `micro_IABROOKLYN_*`
volumes (2024 microfiche scans of English-language Brooklyn directories), 43 were detected as
Fraktur -- but only 29 were actually OCR'd with the Fraktur model. The split is a clean
confidence threshold: every volume at conf >= 0.7533 got `-l eng+Fraktur`, every volume at
conf <= 0.7433 got `-l eng` despite the same Fraktur guess. Grouping by the detector's guess
mixes the two and washes the effect out; that mistake is why this file reads the invocation.

WHAT THE CONTAMINATION ACTUALLY IS (measured on all 48, full `_djvu.txt`):

    invocation        n    German diacritics    dict-hit    median chars/leaf
    -l eng+Fraktur    29     29/29 nonzero        67.1%           1284
    -l eng            19      0/19 nonzero        64.9%           1345

Diacritics separate the two groups PERFECTLY (29/29 vs 0/19) -- ä ö ü ß ſ cannot come from
`eng.traineddata`, so their presence is proof the Fraktur model was loaded. But quality does
NOT collapse: dict-hit is marginally HIGHER in the Fraktur group (high detector confidence
tracks a cleaner scan), and text yield is identical. So this is a CHARACTER-SET CONTAMINATION
with a known fix, not a re-OCR job. Two distinct failure shapes, from reading the contexts:

  * `ſ` (long s) substitutes for **f** inside real words, and is worth correcting:
    `ſerrymaster` -> ferrymaster, `ſruit store` -> fruit store, `Bunſord` -> Bunford.
  * `ä ö ü ß Ä Ü` are NOT in-word substitutions. They are stray single tokens hallucinated onto
    page noise, column rules and marginal specks, almost always trailing an entry
    ("63 Main ö", "99 Prospect ä", "198 York ü"). Strip, do not transliterate.

Nothing else in the corpus is affected: the field only exists on tesseract derives, and every
ABBYY and legacy item returns `n/a`. See [[ia-ocr-engine-confound]] for why the `ocr` engine
label itself cannot be used to rank quality -- it is collinear with scan source.

    python3 data_prep/survey_ocr_params.py                  # fetch + report, resumable
    python3 data_prep/survey_ocr_params.py --report         # re-print from cache, no network
    python3 data_prep/survey_ocr_params.py --measure        # + confirm on the flagged volumes
    python3 data_prep/survey_ocr_params.py --write-sidecars # persist an `ocr_detect` block
    python3 data_prep/survey_ocr_params.py --self-test      # offline

Report-only by default: the sidecars under `data_prep/survey/` are committed, so writing 184 of
them is opt-in rather than a side effect of asking a question.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RAWCACHE = REPO / "data" / "survey_ocr_params"

sys.path.insert(0, str(HERE))
from survey_census import load_rows, sidecar_path         # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (research; city-directory corpus survey; +josh)"}
# The `/metadata` sub-endpoint returns the metadata dict alone -- no file listing, which is the
# bulky half. ~2 KB per volume against ~200 KB for the full item record.
META = "https://archive.org/metadata/{ident}/metadata"
DJVU = "https://archive.org/download/{ident}/{ident}_djvu.txt"

# Models that are not evidence of contamination. `osd` is orientation/script detection, not a
# recognition model, and carries no charset of its own.
BENIGN_MODELS = {"eng", "osd"}

# Characters `eng.traineddata` cannot emit. Presence => a non-English model was loaded.
FOREIGN_CHARS = set("ÄÖÜäöüßſ")

CACHE_V = 1


def _get(url: str, timeout: int = 90, retries: int = 3, cap: int = 0) -> bytes:
    """Fetch with the survey's usual backoff. `cap` bounds the read for large derivatives."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(cap) if cap else r.read()
        except Exception as e:                           # noqa: BLE001 - network, surfaced below
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def models(params) -> list:
    """-> the recognition models named in an `ocr_parameters` string, lowercased.

    Tesseract spells this `-l a+b+c`. Returns [] when the field is absent or unparseable, which
    is NOT the same as "English only" -- callers must distinguish, or every ABBYY item in the
    corpus reads as clean when the truth is that the question does not apply to it.
    """
    if not params:
        return []
    m = re.search(r"-l\s+(\S+)", str(params))
    if not m:
        return []
    return [p.strip().lower() for p in m.group(1).split("+") if p.strip()]


def classify(rec: dict) -> tuple:
    """-> (status, note). The one judgement call in this file; pinned by _self_test.

    contaminated   a non-English model was actually loaded -- expect foreign characters
    detected-only  the detector guessed non-Latin but was below IA's threshold and NOT applied
    clean          English-only invocation
    n/a            no tesseract OCR fields at all (ABBYY, or a derive predating them)
    """
    params = rec.get("ocr_parameters")
    script = rec.get("ocr_detected_script")
    if not params and not script:
        return "n/a", (rec.get("ocr") or "no ocr field")
    foreign = [m for m in models(params) if m not in BENIGN_MODELS]
    if foreign:
        return "contaminated", f"ran -l {'+'.join(models(params))}"
    if script and script.lower() != "latin":
        conf = rec.get("ocr_detected_script_conf")
        return "detected-only", f"guessed {script} @ {conf}, not applied"
    return "clean", f"ran -l {'+'.join(models(params))}" if params else "latin"


def probe(ident: str, refresh: bool = False) -> dict:
    """-> the OCR-invocation distillate for one IA item. Cached; a hit costs no network."""
    RAWCACHE.mkdir(parents=True, exist_ok=True)
    cached = RAWCACHE / f"{ident}.json"
    if cached.exists() and not refresh:
        try:
            doc = json.loads(cached.read_text(encoding="utf-8"))
            if doc.get("_v") == CACHE_V:
                return doc
        except Exception:                                # noqa: BLE001 - corrupt cache, refetch
            pass

    out = {"id": ident, "_v": CACHE_V}
    try:
        md = json.loads(_get(META.format(ident=ident))).get("result", {}) or {}
        out.update({k: md.get(k) for k in (
            "ocr", "ocr_module_version", "ocr_parameters", "ocr_detected_script",
            "ocr_detected_script_conf", "ocr_detected_lang", "ocr_detected_lang_conf",
            "language", "date", "imagecount")})
    except Exception as e:                               # noqa: BLE001 - recorded, not raised
        out["error"] = f"{type(e).__name__}: {e}"[:200]

    cached.write_text(json.dumps(out), encoding="utf-8")
    return out


def _lexicon():
    for p in ("/usr/share/dict/words", "/usr/dict/words"):
        if Path(p).exists():
            return {w.strip().lower() for w in open(p, encoding="utf-8", errors="ignore")
                    if len(w.strip()) >= 4}
    return None


TOKEN = re.compile(r"[A-Za-z]{4,}")


def measure(ident: str, lex, cap: int) -> dict:
    """Confirm a flag against the volume's own text. Costs one `_djvu.txt` fetch.

    Reads the word layer, not the line layer, so the multi-column flattening that makes djvu.txt
    useless for ingest (see [[ia-ocr-usability]]) does not matter here -- the two derivatives
    carry the same words, and this counts characters.
    """
    try:
        text = _get(DJVU.format(ident=ident), timeout=120, cap=cap).decode("utf-8", "replace")
    except Exception as e:                               # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:120]}
    if not text:
        return {"error": "empty djvu.txt"}
    toks = TOKEN.findall(text)
    out = {
        "chars": len(text),
        "truncated": bool(cap) and len(text) >= cap,
        "foreign_per_10k": round(10000 * sum(c in FOREIGN_CHARS for c in text) / len(text), 3),
        "long_s": text.count("ſ"),
    }
    if lex and len(toks) >= 500:
        out["dict_hit"] = round(100 * sum(1 for t in toks if t.lower() in lex) / len(toks), 1)
    return out


def report(recs: dict, measured: dict | None = None):
    """Print the flag list. Cache-only; no network."""
    rows = []
    for ident, rec in sorted(recs.items()):
        if rec.get("error"):
            rows.append(("error", ident, rec["error"], rec))
            continue
        status, note = classify(rec)
        rows.append((status, ident, note, rec))

    counts = Counter(s for s, _, _, _ in rows)
    print(f"{len(rows)} IA volumes\n")
    for s in ("contaminated", "detected-only", "clean", "n/a", "error"):
        if counts.get(s):
            print(f"  {counts[s]:4d}  {s}")

    flagged = [r for r in rows if r[0] == "contaminated"]
    if not flagged:
        print("\nNothing flagged.")
        return
    print(f"\n--- {len(flagged)} volumes ran a non-English model; normalise before ingest ---")
    print(f"{'IDENT':<26} {'YEAR':<10} {'SCRIPT':<9} {'CONF':<7} INVOCATION")
    for _, ident, note, rec in flagged:
        print(f"{ident:<26} {str(rec.get('date') or '?'):<10} "
              f"{str(rec.get('ocr_detected_script') or '?'):<9} "
              f"{str(rec.get('ocr_detected_script_conf') or '?'):<7} {note}")
        m = (measured or {}).get(ident)
        if m:
            if m.get("error"):
                print(f"{'':<26} measure failed: {m['error']}")
            else:
                print(f"{'':<26} foreign/10k {m['foreign_per_10k']:<6} "
                      f"long-s {m['long_s']:<5} "
                      f"dict-hit {m.get('dict_hit', '-')}%"
                      + ("  [truncated]" if m.get("truncated") else ""))

    quiet = [i for _, i, _, _ in flagged
             if measured and measured.get(i, {}).get("foreign_per_10k") == 0]
    if quiet:
        print(f"\n  note: {len(quiet)} flagged volume(s) show no foreign characters in the text. "
              "The model was loaded but left no trace; they are safe as-is.")
    print("\nFix: map ſ -> f inside words, then strip stray äöüßÄÖÜ "
          "tokens. Do NOT transliterate the diacritics -- they are hallucinated onto page noise, "
          "not substitutions for real letters.")


def _self_test():
    """Offline. Pins the invocation-vs-guess rule, which is the whole point of this file."""
    assert models("-l eng+Fraktur") == ["eng", "fraktur"]
    assert models("-l eng") == ["eng"]
    assert models(None) == [] and models("") == [], "absent field must not read as English"
    assert models("--psm 6") == [], "a params string with no -l names no models"

    # The measured reality: same guess, different invocation, and only one is contaminated.
    frak = {"ocr_parameters": "-l eng+Fraktur", "ocr_detected_script": "Fraktur",
            "ocr_detected_script_conf": "0.8219"}
    below = {"ocr_parameters": "-l eng", "ocr_detected_script": "Fraktur",
             "ocr_detected_script_conf": "0.4806"}
    assert classify(frak)[0] == "contaminated", "micro_IABROOKLYN_0035 is the reference flag"
    assert classify(below)[0] == "detected-only", "micro_IABROOKLYN_0013: guessed, not applied"
    assert classify({"ocr_parameters": "-l eng", "ocr_detected_script": "Latin"})[0] == "clean"

    # ABBYY items carry none of these fields; they must never read as clean.
    assert classify({"ocr": "ABBYY FineReader 8.0"})[0] == "n/a", "ABBYY is not in scope"
    assert classify({})[0] == "n/a"

    # Generalises past Fraktur -- the corpus may yet turn up a German or French invocation.
    assert classify({"ocr_parameters": "-l eng+deu"})[0] == "contaminated"
    assert classify({"ocr_parameters": "-l Fraktur"})[0] == "contaminated", "case-insensitive"
    # osd is a detector, not a recognition model, and must not raise a flag on its own.
    assert classify({"ocr_parameters": "-l eng+osd"})[0] == "clean"

    assert FOREIGN_CHARS.isdisjoint(set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")), \
        "the foreign set must not overlap plain ASCII or every volume flags"
    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true", help="offline; no network")
    ap.add_argument("--report", action="store_true", help="summarise from cache; no network")
    ap.add_argument("--ident", help="probe a single IA identifier")
    ap.add_argument("--refresh", action="store_true", help="ignore the raw cache")
    ap.add_argument("--measure", action="store_true",
                    help="confirm flags against each volume's own text (one fetch per flag)")
    ap.add_argument("--measure-bytes", type=int, default=4_000_000,
                    help="cap per djvu.txt read; 0 for no cap (default 4MB)")
    ap.add_argument("--write-sidecars", action="store_true",
                    help="persist an `ocr_detect` block into data_prep/survey/")
    ap.add_argument("--workers", type=int, default=6, help="concurrent IA requests (be polite)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N volumes (smoke test)")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    rows = [r for r in load_rows() if r["source"] == "ia"]
    if args.ident:
        rows = [r for r in rows if r["id"] == args.ident]
        if not rows:
            ap.error(f"{args.ident} is not a non-phonebook ia row in master_directories.csv")
    if args.limit:
        rows = rows[:args.limit]

    if args.report:
        recs = {}
        for r in rows:
            p = RAWCACHE / f"{r['id']}.json"
            if p.exists():
                try:
                    recs[r["id"]] = json.loads(p.read_text(encoding="utf-8"))
                except Exception:                        # noqa: BLE001
                    pass
        if not recs:
            ap.error("nothing cached yet -- run without --report first")
        report(recs)
        return 0

    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        recs = {r["id"]: rec for r, rec in zip(rows, ex.map(
            lambda r: probe(r["id"], args.refresh), rows))}
    n_err = sum(1 for v in recs.values() if v.get("error"))
    print(f"probed {len(recs)} ia volumes in {time.time() - t0:.0f}s ({n_err} errors)",
          file=sys.stderr)

    measured = {}
    if args.measure:
        lex = _lexicon()
        if lex is None:
            print("no system word list; reporting foreign characters only", file=sys.stderr)
        targets = [i for i, rec in recs.items()
                   if not rec.get("error") and classify(rec)[0] == "contaminated"]
        t0 = time.time()
        with ThreadPoolExecutor(min(args.workers, 4)) as ex:
            measured = dict(zip(targets, ex.map(
                lambda i: measure(i, lex, args.measure_bytes), targets)))
        print(f"measured {len(targets)} flagged volumes in {time.time() - t0:.0f}s",
              file=sys.stderr)

    if args.write_sidecars:
        n = 0
        for r in rows:
            rec = recs.get(r["id"], {})
            if rec.get("error"):
                continue
            p = sidecar_path(r)
            if not p.exists():
                continue
            doc = json.loads(p.read_text(encoding="utf-8"))
            status, note = classify(rec)
            block = {
                "status": status, "note": note,
                "ocr_parameters": rec.get("ocr_parameters"),
                "detected_script": rec.get("ocr_detected_script"),
                "detected_script_conf": rec.get("ocr_detected_script_conf"),
                "ocr_module_version": rec.get("ocr_module_version"),
                "checked": time.strftime("%Y-%m-%d"),
            }
            if measured.get(r["id"]):
                block["measured"] = measured[r["id"]]
            doc["ocr_detect"] = block
            p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            n += 1
        print(f"wrote ocr_detect into {n} sidecars", file=sys.stderr)

    report(recs, measured)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
