"""Are NYPL Map Warper's georectified sheets in Allmaps? (RENUMBERING_PLAN 0.6 / 6.2)

    python3 results/allmaps_coverage.py data/spacetime > results/allmaps_coverage.json

Space/Time's 2017 `mapwarper` dataset lists each rectified sheet with its NYPL image id and
control points. For every atlas (sheets sharing a description) of 1850-1925 with 10+ sheets and
a control point in New York City, five sheets (every n-th, so the same on a re-run) are asked of
annotations.allmaps.org by their IIIF image address. Per atlas: sheets, asked, found, and the
control points on each side. Answers are cached in data/spacetime/allmaps_cache.json, so a
re-run asks only for sheets not yet asked; one request at a time.
"""
import collections
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

NYC = (-74.27, 40.48, -73.68, 40.93)      # west, south, east, north
ASK = "https://annotations.allmaps.org/?url=https://iiif.nypl.org/iiif/3/{}"


def ask(image_id: str):
    """Control points Allmaps holds for the image (0: a map with none), None when it has no map."""
    try:
        request = urllib.request.Request(ASK.format(image_id),  # urllib's own agent gets a 403
                                         headers={"User-Agent": "city-directory-extraction"})
        for attempt in range(3):               # the service times out now and then
            try:
                with urllib.request.urlopen(request, timeout=30) as r:
                    page = json.load(r)
                break
            except TimeoutError:
                if attempt == 2:
                    raise
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return max((len(m["body"]["features"]) for m in page.get("items", [])), default=None)


def main(root):
    root = pathlib.Path(root)
    cache_path = root / "allmaps_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    atlases = collections.defaultdict(list)
    for line in open(root / "x_mapwarper/mapwarper.objects.ndjson"):
        o = json.loads(line)
        d = o["data"]
        gcps = d.get("gcps") or []
        if (d.get("imageId") and 1850 <= (o.get("validSince") or 0) <= 1925 and any(
                NYC[1] < g[2] < NYC[3] and NYC[0] < g[3] < NYC[2] for g in gcps)):
            atlases[(d.get("description") or "").strip()].append(
                (o["id"], d["imageId"], o["validSince"], len(gcps)))
    out = []
    for description, sheets in atlases.items():
        if len(sheets) < 10:
            continue
        sheets.sort()
        asked = sheets[:: max(1, len(sheets) // 5)][:5]
        for _, image, _, _ in asked:
            if image not in cache:
                cache[image] = ask(image)
                cache_path.write_text(json.dumps(cache))
                time.sleep(0.5)
        out.append({"atlas": description[:160], "year": sheets[0][2], "sheets": len(sheets),
                    "asked": len(asked),
                    "in_allmaps": sum(cache[image] is not None for _, image, _, _ in asked),
                    "gcps_mapwarper": [n for *_, n in asked],
                    "gcps_allmaps": [cache[image] for _, image, _, _ in asked]})
    out.sort(key=lambda r: (r["year"], r["atlas"]))
    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
