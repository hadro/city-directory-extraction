#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Hand-label extracted records as real directory entries or not, to re-validate `entry_rate.py`.

    python3 eval/label_entries.py --n 80 --seed 20260914 \
        --out data/entry_labels_1906BPL.jsonl

    python3 eval/label_entries.py --n 80 --seed 20260914 --resume \
        --out data/entry_labels_1906BPL.jsonl        # carry on where you stopped

    python3 eval/label_entries.py --self-test

WHY THIS EXISTS
---------------
`entry_rate.py`'s `is_entry` is the function every fabrication claim in this project passes
through, and its only validation is one sentence in that file's docstring: "Accuracy, against 40
lines from 1906BPL hand-labelled by reading them ... THIS (name + street-y address) 97.5%".

**Those 40 labels are not in the repo** (docs/FIGURE_AUDIT.md, finding 2). The number cannot be
re-checked, extended, or re-run after any change to `is_entry`. This tool produces a committed
replacement.

Two comparator figures in the same docstring -- surname-shape 67.5% and "raw line contains a
digit" 95.0% -- are **doubly unverifiable**: no labels, and their implementations are no longer in
the file either. Rebuild them from these labels or stop quoting them.

WHAT THE LABELLER SEES, AND WHAT IS DELIBERATELY WITHHELD
----------------------------------------------------------
Shown: the raw OCR line, and the model's predicted record.

**Withheld from the browser entirely -- not merely hidden in the UI:**

* `is_entry`'s verdict. Labelling against the thing being validated would measure agreement with a
  prompt, not accuracy.
* the line's `band`. It is the stratifier and it correlates with the answer, so showing it would
  anchor exactly the judgement being collected.

The band IS written into each saved row, by the server, at save time -- the analysis needs it and
the labeller must not have it. Same separation the `--blind` mode of `data_prep/label_leaf_bands.py`
enforces, and for the same reason.

SAMPLING
--------
`--n` rows split evenly across the four bands, seeded, drawn from the 600 already-scored
predictions in `results/ab_band_fabrication_1906BPL_preds/`.

**Stratified by band, never by `is_entry`.** Selecting on the metric is this project's recurring
failure. Band is correlated with the answer but independent of the metric, which is what makes it
a usable stratifier.

A uniform draw would be 94% body, so ~75 of 80 items would be real entries and accuracy would be
dominated by the easy class while saying nothing about ads-called-entries -- the error that
matters. Balanced strata give both classes in quantity; report per-class rates, and re-weight by
the volume band mix for a volume-wide figure rather than quoting the balanced accuracy as one.
"""

import argparse
import functools
import http.server
import json
import os
import random
import re
import socketserver
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).with_suffix(".html")
DEFAULT_PREDS = ROOT / "results" / "ab_band_fabrication_1906BPL_preds"

LABELS = ["entry", "not-entry", "unsure"]
CATEGORIES = ["advertising", "business-directory", "ocr-garbage", "page-furniture"]


def load_pool(preds_dir):
    """[(row_index, raw_line, predicted_fields, band)] — band kept server-side only."""
    d = Path(preds_dir)
    rows = [json.loads(l) for l in (d / "inputs.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    blocks = [b for b in re.split(r"\n\s*\n", (d / "preds.txt").read_text(encoding="utf-8"))
              if b.strip()]
    if len(blocks) != len(rows):
        raise SystemExit(f"{len(blocks)} predictions vs {len(rows)} inputs in {d}")
    out = []
    for i, (blk, r) in enumerate(zip(blocks, rows)):
        f = {}
        for ln in blk.splitlines():
            k, _, v = ln.partition(":")
            f[k.strip()] = v.strip().strip('"')
        out.append((i, r["raw_line"], f, r["context"]["_stratum"], r["context"]["leaf"]))
    return out


def pick(pool, n, seed, exclude=()):
    """n rows split evenly across bands, seeded. Never consults is_entry."""
    by_band = {}
    for item in pool:
        if item[0] not in exclude:
            by_band.setdefault(item[3], []).append(item)
    random.seed(seed)
    per = max(1, n // max(len(by_band), 1))
    picked = []
    for band in sorted(by_band):
        ids = by_band[band]
        picked += random.sample(ids, min(per, len(ids)))
    picked.sort(key=lambda t: t[0])
    return picked


def build_html(items, save_url, prior=None):
    """Payload carries raw line and predicted fields ONLY — no band, no is_entry verdict."""
    payload = {
        "items": [{"row": i, "raw_line": raw, "fields": f} for i, raw, f, _band, _leaf in items],
        "labels": LABELS, "categories": CATEGORIES,
        "save_url": save_url, "prior": prior or {},
    }
    blob = json.dumps(payload)
    for leaked in ('"band"', '"_stratum"', '"is_entry"'):
        if leaked in blob:
            raise RuntimeError(f"payload leaks {leaked} to the labeller")
    tmpl = TEMPLATE.read_text(encoding="utf-8")
    if "__PAYLOAD__" not in tmpl:
        raise RuntimeError(f"{TEMPLATE} has no __PAYLOAD__ token")
    return tmpl.replace("__PAYLOAD__", blob)


def load_prior(out_path):
    p = Path(out_path)
    if not p.exists():
        return {}
    prior = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            prior[str(r["row"])] = r
    return prior


class _Handler(http.server.BaseHTTPRequestHandler):
    render_args: dict
    out_path: Path
    meta: dict          # row -> (band, leaf, raw_line) — server-side, never sent to the page
    done: "threading.Event"

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, "text/html; charset=utf-8",
                              build_html(**type(self).render_args).encode("utf-8"))
        self.send_error(404)

    def do_POST(self):
        cls = type(self)
        if self.path == "/save":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                rows = [r for r in body["rows"] if r.get("label")]
                tmp = cls.out_path.with_suffix(cls.out_path.suffix + ".tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    for r in rows:
                        band, leaf, raw = cls.meta[r["row"]]
                        # The band is attached HERE, by the server. The labeller never saw it.
                        r.update({"band": band, "leaf": leaf, "raw_line": raw,
                                  "ident": "1906BPL", "labeled_at": stamp})
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, cls.out_path)
                print(f"  saved {len(rows)} labels → {cls.out_path}", file=sys.stderr)
                return self._send(200, "application/json",
                                  json.dumps({"n": len(rows), "path": str(cls.out_path)}).encode())
            except Exception as exc:                     # noqa: BLE001 — surfaced to the page
                return self.send_error(500, str(exc))
        if self.path == "/done":
            self._send(200, "application/json", b'{"ok":true}')
            cls.done.set()
            return
        self.send_error(404)

    def log_message(self, *_):
        pass


def _self_test() -> int:
    items = [(7, "44 Wm elk h 86 Laf av",
              {"name": '" Wm', "occupation_role": "clk", "address": "86 Laf av"}, "body", 13)]
    html = build_html(items, "/save")

    # 1. The two things that would invalidate the labels must not reach the page.
    assert "__PAYLOAD__" not in html
    assert "is_entry" not in html, "is_entry's verdict must never be shown"
    body = html[html.index("const CFG"):html.index("</script>")]
    assert '"body"' not in body, "the band leaked into the payload"
    assert "_stratum" not in body, "the stratum leaked into the payload"

    # 2. What the labeller does need is present.
    assert "44 Wm elk h 86 Laf av" in html and "86 Laf av" in html

    # 3. The vocabularies match this module rather than drifting from it.
    for v in LABELS + CATEGORIES:
        assert f'"{v}"' in html, f"template is missing {v}"

    # 4. Stratified picking is balanced and never looks at is_entry.
    pool = [(i, f"line {i}", {}, ["body", "head", "foot", "None"][i % 4], 0) for i in range(40)]
    got = pick(pool, 8, seed=1)
    from collections import Counter
    assert Counter(b for _, _, _, b, _ in got) == {"body": 2, "head": 2, "foot": 2, "None": 2}, got

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preds", default=str(DEFAULT_PREDS))
    ap.add_argument("--out", default="data/entry_labels_1906BPL.jsonl")
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=20260914)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    pool = load_pool(args.preds)
    items = pick(pool, args.n, args.seed)
    prior = load_prior(args.out) if args.resume else {}
    if prior:
        print(f"  resuming: {len(prior)} already labelled", file=sys.stderr)

    from collections import Counter
    print(f"{len(items)} items, {dict(Counter(b for _, _, _, b, _ in items))}", file=sys.stderr)

    _Handler.out_path = Path(args.out)
    _Handler.meta = {i: (band, leaf, raw) for i, raw, _f, band, leaf in items}
    _Handler.done = threading.Event()

    with socketserver.TCPServer(("127.0.0.1", 0), functools.partial(_Handler)) as server:
        port = server.server_address[1]
        _Handler.render_args = {"items": items, "save_url": f"http://127.0.0.1:{port}/save",
                                "prior": prior}
        build_html(**_Handler.render_args)       # fail here, not in the browser
        url = f"http://127.0.0.1:{port}/"
        print(f"\nServing {url}", file=sys.stderr)
        print("1 = real entry · 2 = not an entry · then pick what it is. Autosaves.",
              file=sys.stderr)
        if args.no_open:
            return 0
        threading.Thread(target=server.serve_forever, daemon=True).start()
        webbrowser.open(url)
        try:
            while not _Handler.done.wait(1):
                pass
        except KeyboardInterrupt:
            print("", file=sys.stderr)
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
