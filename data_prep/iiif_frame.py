#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Where an hOCR box is on the IIIF image: the region and the rotation that shows it upright.

    from iiif_frame import crop_url, xywh
    crop_url("trowsgeneraldire1915trow", 470, [1380, 1626, 1966, 1651])
    python3 data_prep/iiif_frame.py --self-test

WHY (2026-10-04). Every crop the repo builds puts the hOCR box straight onto the IIIF image, on
the stated assumption that the hOCR's pixel space "is the scan's" (assemble_records.py). That holds
on 182 of 184 volumes and fails on the two largest: Trow 1915 and 1917. IIIF serves their camera
images, 5616x3744 landscape, two book pages photographed per frame. IA OCR'd each page after
cropping it out and turning it upright, so their hOCR pages are about 3300x4500 portrait. A box
used as-is lands elsewhere on the photograph, sideways: the first ditto review page showed
rotated fragments of the wrong lines.

The cropping and turning are in `<id>_scandata.xml`, per page: `cropBox` (x, y, w, h) in the
upright frame, and `rotateDegree`, alternating -90 and 90 as the camera met left and right
pages. -90 means the camera image was turned counter-clockwise. Both directions were checked
by eye on leaf 470 (-90) and leaf 1145 (90). The upright frame is the camera image with its
sides swapped, which `origWidth` x `origHeight` (3744x5616) records.

Which volumes need it is measured, not assumed: results/iiif_frames.json compares one leaf's
hOCR page size with the IIIF image per volume. Every other volume maps identically, and nothing
is downloaded for it. Scandata is cached in data/scandata/ (gitignored, re-fetchable).
"""
from __future__ import annotations

import argparse
import functools
import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
FRAMES = REPO / "results" / "iiif_frames.json"
CACHE = REPO / "data" / "scandata"
IIIF = "https://iiif.archive.org/iiif"
UA = {"User-Agent": "Mozilla/5.0 (research; city-directory corpus survey)"}


@functools.lru_cache(maxsize=None)
def mismatched() -> frozenset:
    if not FRAMES.exists():
        return frozenset()
    return frozenset(json.loads(FRAMES.read_text(encoding="utf-8"))["mismatched"])


@functools.lru_cache(maxsize=8)
def pages(ident: str) -> dict:
    """leaf -> (crop x, crop y, rotateDegree, camera width, camera height), from scandata."""
    path = CACHE / f"{ident}_scandata.xml.gz"
    if not path.exists():
        url = f"https://archive.org/download/{ident}/{ident}_scandata.xml"
        data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(data))
    text = gzip.decompress(path.read_bytes()).decode("utf-8", "replace")
    out = {}
    for num, body in re.findall(r'<page leafNum="(\d+)">(.*?)</page>', text, re.S):
        def num_of(tag, default=0):
            m = re.search(rf"<{tag}>\s*(-?\d+)\s*</{tag}>", body)
            return int(m.group(1)) if m else default
        crop = re.search(r"<cropBox>(.*?)</cropBox>", body, re.S)
        cx = cy = 0
        if crop:
            cx = int(re.search(r"<x>\s*(-?\d+)", crop.group(1)).group(1))
            cy = int(re.search(r"<y>\s*(-?\d+)", crop.group(1)).group(1))
        rot = num_of("rotateDegree")
        ow, oh = num_of("origWidth"), num_of("origHeight")
        cam_w, cam_h = (oh, ow) if rot % 180 else (ow, oh)
        out[int(num)] = (cx, cy, rot, cam_w, cam_h)
    return out


def to_camera(box, crop_x, crop_y, rot, cam_w, cam_h):
    """An upright-page box (x0, y0, x1, y1) -> ((x, y, w, h) on the camera image, the IIIF
    rotation that shows it upright)."""
    X0, Y0, X1, Y1 = box[0] + crop_x, box[1] + crop_y, box[2] + crop_x, box[3] + crop_y
    r = rot % 360
    if r == 0:
        x, y, w, h, show = X0, Y0, X1 - X0, Y1 - Y0, 0
    elif r == 270:                       # rotateDegree -90: the camera image turned anticlockwise
        x, y, w, h, show = cam_w - Y1, X0, Y1 - Y0, X1 - X0, 270
    elif r == 90:
        x, y, w, h, show = Y0, cam_h - X1, Y1 - Y0, X1 - X0, 90
    else:
        x, y, w, h, show = cam_w - X1, cam_h - Y1, X1 - X0, Y1 - Y0, 180
    x0, y0 = max(0, x), max(0, y)          # clamp: a padded box may reach past the photograph
    x1, y1 = min(cam_w or x + w, x + w), min(cam_h or y + h, y + h)
    return (x0, y0, x1 - x0, y1 - y0), show


def region(ident: str, leaf: int, box, pad=(0, 0, 0, 0)):
    """((x, y, w, h), rotation) for an hOCR box, padded (left, top, right, bottom) in the
    upright page's pixels."""
    b = [box[0] - pad[0], box[1] - pad[1], box[2] + pad[2], box[3] + pad[3]]
    if ident in mismatched():
        page = pages(ident).get(leaf)
        if page:
            return to_camera(b, *page)
    b = [max(0, b[0]), max(0, b[1]), b[2], b[3]]
    return (b[0], b[1], b[2] - b[0], b[3] - b[1]), 0


def xywh(ident: str, leaf: int, box) -> str:
    """The box as a IIIF canvas fragment (`#xywh=`): on the camera image, unrotated."""
    return ",".join(map(str, region(ident, leaf, box)[0]))


def crop_url(ident: str, leaf: int, box, size: str = "full", pad=(0, 0, 0, 0)) -> str:
    (x, y, w, h), rot = region(ident, leaf, box, pad)
    return f"{IIIF}/{ident}${leaf}/{x},{y},{w},{h}/{size}/{rot}/default.jpg"


def _self_test() -> int:
    # the two cases read off the image on 2026-10-04 (trowsgeneraldire1915trow)
    assert to_camera((1112, 140, 1870, 250), 433, 832, -90, 5616, 3744) == \
        ((4534, 1545, 110, 758), 270), "leaf 470: '50 & 52 Stone Street', upright"
    assert to_camera((0, 0, 10, 20), 0, 0, 0, 100, 100) == ((0, 0, 10, 20), 0)
    (x, y, w, h), r = to_camera((10, 20, 110, 40), 256, 621, 90, 5616, 3744)
    assert (x, y, w, h, r) == (641, 3378, 20, 100, 90), "leaf 1145's direction"
    assert to_camera((-50, -50, 10, 10), 0, 0, 0, 100, 100)[0] == (0, 0, 10, 10), "clamped"
    print("self-test ok")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    if ap.parse_args().self_test:
        sys.exit(_self_test())
    ap.print_help()
