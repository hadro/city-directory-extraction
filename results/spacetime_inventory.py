"""What is in NYPL Space/Time's map datasets, and do they reach Brooklyn? (RENUMBERING_PLAN 0.1)

    python3 results/spacetime_inventory.py data/spacetime > results/spacetime_inventory.json

For each `<name>.zip` unpacked to `data/spacetime/x_<name>/`: the zip's sha256, objects by type,
borough, year and Map Warper layer (the layer's own title and year, from the mapwarper dataset),
the fields seen, five sample records, and the gate: the counts here against the data package's
own `stats`. Standard library only; the files are small.
"""
import collections
import hashlib
import json
import pathlib
import sys

NAMES = ["building-inspector", "addresses", "perris-atlas-footprints", "nyc-streets", "mapwarper",
         "nyc-wards"]


def ndjson(path):
    with open(path) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def main(root):
    root = pathlib.Path(root)
    layers = {o["id"].removeprefix("layer-"): o for o in
              ndjson(root / "x_mapwarper/mapwarper.objects.ndjson") if str(o["id"]).startswith("layer-")}
    out = {}
    for name in NAMES:
        d = root / f"x_{name}"
        objects = list(ndjson(d / f"{name}.objects.ndjson"))
        rel = d / f"{name}.relations.ndjson"
        relations = sum(1 for _ in ndjson(rel)) if rel.exists() else 0
        package = json.load(open(d / "datapackage.json"))
        said = {r["path"]: r.get("stats", {}) for r in package["resources"]}
        types = collections.Counter(o["type"] for o in objects)
        by_layer = collections.Counter()
        for o in objects:
            layer = str(o.get("data", {}).get("layerId", ""))
            if layer:
                by_layer[(layer, o["type"])] += 1
        said_objects = said.get(f"{name}.objects.ndjson", {})
        said_relations = said.get(f"{name}.relations.ndjson", {}).get("count", 0)
        out[name] = {
            "sha256": hashlib.sha256((root / f"{name}.zip").read_bytes()).hexdigest(),
            "version": package.get("version"), "created": package.get("created"),
            "objects": len(objects), "relations": relations, "types": dict(types),
            "gate_counts_match_package": (len(objects) == said_objects.get("count")
                                          and dict(types) == said_objects.get("types")
                                          and relations == said_relations),
            "with_geometry": sum(1 for o in objects if o.get("geometry")),
            "boroughs": dict(collections.Counter(o.get("data", {}).get("borough", "(none)")
                                                 for o in objects)),
            "years": dict(sorted(collections.Counter(o.get("validSince") for o in objects
                                                     ).items(), key=lambda kv: str(kv[0]))),
            "layers": [{"layer": layer, "type": kind, "objects": n,
                        "title": layers.get(layer, {}).get("name"),
                        "year": layers.get(layer, {}).get("validSince"),
                        "bbox": layers.get(layer, {}).get("data", {}).get("bbox")}
                       for (layer, kind), n in by_layer.most_common()],
            "fields": sorted({k for o in objects for k in o} |
                             {"data." + k for o in objects for k in o.get("data", {})}),
            "samples": [{k: (v if k != "geometry" else {"type": v["type"]})
                         for k, v in o.items()} for o in objects[:: max(1, len(objects) // 5)][:5]],
        }
    if "mapwarper" in out:  # the layers themselves: which atlases are georectified at all
        out["mapwarper"]["layer_list"] = sorted(
            ({"layer": k, "title": o["name"], "year": o.get("validSince"),
              "maps": o["data"].get("mapCount"), "bbox": o["data"].get("bbox")}
             for k, o in layers.items()), key=lambda r: (r["year"] or 0, r["title"] or ""))
    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
