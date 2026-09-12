#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Phase 1 labelling UI for docs/PAGE_TYPE_CLASSIFIER.md — drag the listing body's top and bottom.

    # training set: prefilled from the ditto extent, hOCR boxes overlaid
    python3 data_prep/label_leaf_bands.py --ident 1906BPL --n 200 --seed 20260910 \
        --out data/bands_1906BPL_train.jsonl

    # evaluation set: NO prefill, NO overlay, disjoint from the training sample
    python3 data_prep/label_leaf_bands.py --ident 1906BPL --n 50 --seed 20260911 --blind \
        --exclude data/bands_1906BPL_train.jsonl --out data/bands_1906BPL_eval.jsonl

    python3 data_prep/label_leaf_bands.py --self-test

Opens a local page: the leaf image with two draggable edges. The label is where the listing body
starts and stops, plus what the strips above and below it are. Phase 0
(`results/leaf_band_structure_1906BPL.py`) measured that 94% of 1906BPL's listing-span leaves have
exactly this shape, which is why the unit is a band and not a page type.

WHY `--blind` EXISTS, AND WHY THE EVALUATION SET MUST USE IT
-----------------------------------------------------------
Prefilling the edges from ditto extent and overlaying the hOCR boxes makes labelling perhaps 5x
faster, and for TRAINING data that is a free win. For EVALUATION it is not: the model is scored
against a ditto-derived baseline, so a human nudged by a ditto-derived prefill would be scoring the
baseline against itself. That is this project's recurring failure -- selecting on what a filter
kept -- in a new costume.

`--blind` therefore drops the prefill to a flat 0.10/0.90 and hides the box overlay entirely. The
mode is written into **every row** as `blind: true|false` so a mixed file cannot silently be
analysed as one thing.

WHAT A ROW RECORDS
------------------
`has_body` + `body_top` / `body_bottom` (fractions of THIS leaf's page height), and then either:

  * body present -> `head_contents` and `foot_contents`, each a LIST, from
    {advertising, furniture, empty}
  * no body      -> `page_type`, one of
    {advertising, front-matter, index-or-back-matter, blank-or-plate}

**The strips are lists because they are routinely more than one thing, and a single-select label
was simply wrong.** Measured on the two leaves this plan keeps citing: leaf 13's foot carries the
Joseph Ryan advertisement AND the page number `25`; leaf 200's carries an Upington advertisement,
the running head `Brooklyn Street Directory,` AND the page number `202`. Forcing one class would
have thrown away whichever the labeller did not pick, and the class that matters -- advertising,
the one that becomes fabricated people -- is exactly the one a page number would mask.

Contents default to `["advertising"]` because that is the common case, and each row records
`head_touched` / `foot_touched`. A default a labeller never looked at is weaker evidence than one
they chose, and the analysis gets to know which is which.

The prefill is also biased in a known direction, which the in-app instructions state: it is the
extent of ditto lines, but a surname block OPENS with the un-dittoed surname (`ACME`, `ADAMS`)
sitting above the first ditto, so the top edge starts a line or two low. Leaf 13 has a real entry
at y=0.870 below the prefilled bottom, too. Labellers are told to nudge rather than confirm.

IMAGES
------
The pipeline proper downloads no images (PIPELINE.md stage 1). This tool does, for the ~250 sampled
leaves only, into `data/ia_cache/pageimg/<ident>/`. **The classifier never sees an image** -- the
picture is the fast path for a human eye, nothing more.

The hOCR page box and the IA page JPEG share a pixel space *per leaf* (verified: leaf 13 of 1906BPL
is 2016x3048 in both), so a y-fraction maps to both without scaling. They are NOT constant across
leaves -- leaf 0 of the same volume is 2550x3301 -- so everything here is a fraction of that leaf's
own `page_dims`, never an absolute pixel. PIPELINE.md's warning about unscaled boxes applies.
"""

import argparse
import functools
import http.server
import json
import random
import re
import socketserver
import sys
import threading
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ia_volume_to_jsonl import Item, hocr_lines, page_dims     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ia_cache"
TEMPLATE = Path(__file__).with_suffix(".html")
IMG_URL = "https://archive.org/download/{ident}/page/n{leaf}_w{width}.jpg"

# Same per-volume caveat as results/leaf_band_structure_1906BPL.py: these are 1906BPL's admitted
# marks. The prefill is a convenience, never a label -- a volume whose marks differ just gets a
# worse starting guess, and in --blind mode it is not used at all.
DITTO = re.compile(r'^\s*(44|"|“|”|\*\*|«)\s')


# ==============================================================================================
# Leaf payload
# ==============================================================================================
def leaf_payload(item, leaf, blind):
    """One leaf's boxes, dims and ditto-derived prefill, or None if it has no hOCR lines."""
    markup = item.hocr_page(leaf)
    if not markup:
        return None
    pairs, dims = hocr_lines(markup), page_dims(markup)
    if not pairs or not dims:
        return None

    height = dims[1]
    boxes, ditto_ys = [], []
    for (x0, y0, x1, y1), text in pairs:
        is_ditto = bool(DITTO.match(text))
        if not blind:
            boxes.append([x0, y0, x1, y1, 1 if is_ditto else 0])
        if is_ditto:
            ditto_ys.append(y0 / height)

    # Prefill only where the extent is meaningful. Fewer than 20 ditto lines on a leaf means
    # either a full-page ad or a volume whose marks this regex misses; both deserve a human
    # starting from scratch rather than from a guess built on five lines.
    prefill = (round(min(ditto_ys), 4), round(max(ditto_ys), 4)) \
        if (not blind and len(ditto_ys) >= 20) else (None, None)

    return {"leaf": leaf, "n_lines": len(pairs), "page_size": list(dims),
            "boxes": boxes, "prefill_top": prefill[0], "prefill_bottom": prefill[1]}


def cache_image(ident, leaf, width, cache_dir, retries=3):
    dest = cache_dir / f"n{leaf}_w{width}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = IMG_URL.format(ident=ident, leaf=leaf, width=width)
    last = None
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                dest.write_bytes(r.read())
            return dest
        except Exception as e:                              # noqa: BLE001 - surfaced below
            last = e
    raise RuntimeError(f"could not fetch leaf {leaf} image: {last}")


def pick_leaves(item, n, seed, span, exclude):
    lo, hi = span
    hi = min(hi, len(item.index))
    pool = [x for x in range(lo, hi) if x not in exclude]
    if n >= len(pool):
        return pool
    random.seed(seed)
    return sorted(random.sample(pool, n))


def read_excluded(paths):
    """Leaves already labelled elsewhere. Keeps train and eval samples disjoint by construction."""
    out = set()
    for p in paths or []:
        path = Path(p)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.add(json.loads(line)["leaf"])
    return out


# ==============================================================================================
# Server
# ==============================================================================================
class _Handler(http.server.BaseHTTPRequestHandler):
    render_args: dict
    images: dict
    out_path: Path
    done: "threading.Event"

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        cls = type(self)
        if self.path in ("/", "/index.html"):
            # Re-render from the template on every load, so editing the HTML and hitting reload
            # is enough -- no restart, and no re-fetching 250 page images to see a CSS change.
            return self._send(200, "text/html; charset=utf-8",
                              build_html(**cls.render_args).encode("utf-8"))
        m = re.fullmatch(r"/img/(\d+)\.jpg", self.path)
        if m and int(m.group(1)) in cls.images:
            return self._send(200, "image/jpeg", cls.images[int(m.group(1))].read_bytes())
        self.send_error(404)

    def do_POST(self):
        cls = type(self)
        if self.path == "/save":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                rows = [r for r in body["rows"] if r.get("visited")]
                with open(cls.out_path, "w", encoding="utf-8") as fh:
                    for r in rows:
                        r["labeled_at"] = stamp
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                print(f"  saved {len(rows)} rows → {cls.out_path}", file=sys.stderr)
                return self._send(200, "application/json",
                                  json.dumps({"n": len(rows),
                                              "path": str(cls.out_path)}).encode())
            except Exception as exc:                        # noqa: BLE001 - reported to the page
                return self.send_error(500, str(exc))
        if self.path == "/done":
            self._send(200, "application/json", b'{"ok":true}')
            cls.done.set()
            return
        self.send_error(404)

    def log_message(self, *_):
        pass


def build_html(ident, leaves, blind, save_url):
    payload = {"ident": ident, "blind": blind, "leaves": leaves,
               "img_base": "/img/", "save_url": save_url}
    tmpl = TEMPLATE.read_text(encoding="utf-8")
    if "__PAYLOAD__" not in tmpl:
        raise RuntimeError(f"{TEMPLATE} has no __PAYLOAD__ token")
    # Token substitution, not str.format: the template is mostly CSS and JS braces, and doubling
    # every one of them to satisfy format() is a standing invitation to a silent syntax error.
    return tmpl.replace("__PAYLOAD__", json.dumps(payload))


# ==============================================================================================
def _self_test() -> int:
    markup = (
        '<div class="ocr_page" title="bbox 0 0 2000 3000">'
        + "".join(
            f'<p><span class="ocr_line" title="bbox 100 {y} 400 {y + 18}">'
            f'<span class="ocrx_word" title="bbox 100 {y} 400 {y + 18}; x_wconf 90">'
            f'{"44" if 300 <= y <= 2700 else "HEADLINE"}</span>'
            f'<span class="ocrx_word" title="bbox 410 {y} 500 {y + 18}; x_wconf 90">Wm</span>'
            '</span></p>'
            for y in range(100, 2900, 40))
        + '</div>')

    class _Stub:
        def hocr_page(self, _leaf):
            return markup

    ys = list(range(100, 2900, 40))
    n_ditto = sum(1 for y in ys if 300 <= y <= 2700)

    p = leaf_payload(_Stub(), 7, blind=False)
    assert p["n_lines"] == len(ys) == 70, p["n_lines"]
    # Prefill tracks the DITTO extent (0.100-0.900), not the page extent (0.033-0.953).
    assert p["prefill_top"] == 0.1, p["prefill_top"]
    assert p["prefill_bottom"] == 0.9, p["prefill_bottom"]
    assert len(p["boxes"]) == len(ys), "every line reaches the overlay"
    assert sum(b[4] for b in p["boxes"]) == n_ditto == 61, "ditto flags"

    # Blind mode must leak neither the prefill nor the overlay.
    b = leaf_payload(_Stub(), 7, blind=True)
    assert b["prefill_top"] is None and b["prefill_bottom"] is None, b
    assert b["boxes"] == [], "blind payload must carry no boxes"

    # The template must still accept a payload.
    html = build_html("X", [p], False, "/save")
    assert "__PAYLOAD__" not in html and '"ident": "X"' in html

    # The vocabularies live in the template; assert they match this docstring rather than let
    # the two drift silently apart.
    for v in ("advertising", "furniture", "empty",
              "front-matter", "index-or-back-matter", "blank-or-plate"):
        assert f'"{v}"' in html, f"template is missing the {v} option"
    assert "head_contents" in html and "page_type" in html, "template/save schema drift"

    print("self-test OK", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ident")
    ap.add_argument("--out")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--span", default="9,1216", help="leaf range to sample, lo,hi")
    ap.add_argument("--leaves", help="explicit leaf list, overrides --n/--seed/--span")
    ap.add_argument("--exclude", action="append",
                    help="a previous bands JSONL whose leaves must not be re-sampled")
    ap.add_argument("--blind", action="store_true",
                    help="REQUIRED for evaluation sets: no prefill, no box overlay")
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.ident or not args.out:
        ap.error("--ident and --out are required (or use --self-test)")

    cache = Path(args.cache)
    item = Item(args.ident, cache)
    item.prefetch_hocr()

    if args.leaves:
        leaf_ids = [int(x) for x in args.leaves.split(",")]
    else:
        lo, hi = (int(x) for x in args.span.split(","))
        excluded = read_excluded(args.exclude)
        if excluded:
            print(f"  excluding {len(excluded)} already-labelled leaves", file=sys.stderr)
        leaf_ids = pick_leaves(item, args.n, args.seed, (lo, hi), excluded)

    print(f"{args.ident}: preparing {len(leaf_ids)} leaves"
          f"{' (BLIND)' if args.blind else ''}", file=sys.stderr)

    leaves, images = [], {}
    for k, leaf in enumerate(leaf_ids, 1):
        payload = leaf_payload(item, leaf, args.blind)
        if payload is None:
            print(f"  leaf {leaf}: no hOCR lines, skipped", file=sys.stderr)
            continue
        images[leaf] = cache_image(args.ident, leaf, args.width,
                                   cache / "pageimg" / args.ident)
        leaves.append(payload)
        if k % 25 == 0 or k == len(leaf_ids):
            print(f"  ... {k}/{len(leaf_ids)}", file=sys.stderr)

    if not leaves:
        print("no labellable leaves", file=sys.stderr)
        return 1

    _Handler.images = images
    _Handler.out_path = Path(args.out)
    _Handler.done = threading.Event()

    with socketserver.TCPServer(("127.0.0.1", 0), functools.partial(_Handler)) as server:
        port = server.server_address[1]
        _Handler.render_args = {"ident": args.ident, "leaves": leaves, "blind": args.blind,
                                "save_url": f"http://127.0.0.1:{port}/save"}
        build_html(**_Handler.render_args)          # fail loudly here, not in the browser
        url = f"http://127.0.0.1:{port}/"
        print(f"\nServing {url}  ({len(leaves)} leaves)", file=sys.stderr)
        print("Instructions open on first visit; '?' reopens them.", file=sys.stderr)
        print("Save writes only VISITED leaves, so saving part-way is safe. Ctrl+C when done.",
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
