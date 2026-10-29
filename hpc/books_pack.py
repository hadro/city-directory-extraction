#!/usr/bin/env python3
"""
Pack each finished volume's LightOn answers into one tar, to send back (docs/PIPELINE.md #27).
Standard library only; run on a login node while or after hpc/39_lightonocr.sbatch runs.

    python3 hpc/books_pack.py data/reocr_books_records/volumes_abbyy8-damaged.tsv
    python3 hpc/books_pack.py <TSV> --prune      # ...and delete the tiles of volumes packed before
    python3 hpc/books_pack.py <TSV> --slug lightonocr-3-1b-greedy-vllm-notables   # volumes read with tables banned

A volume is finished when every tile has its .meta.json (a tile LightOn left EMPTY has a meta and
no .txt, and counts as finished: the import keeps IA's words there). Its tar,
data/reocr_tiers/answers_<label>/<id>.tar, holds boxes.json, columns.json, STAGED and every answer
file (.txt, .raw.txt, .meta.json, .loop.raw.txt), paths relative to the checkout: tens of MB a
volume. A volume packed already is skipped. --prune deletes a packed volume's tiles (JPEGs only)
once Josh has confirmed its tar arrived; the answers and boxes stay.
"""
from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from books_shards import REPO, SLUG, TIERS, tiles_of  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vols", help="the volumes TSV (data_prep/reocr_books.py records)")
    ap.add_argument("--prune", action="store_true", help="delete the tiles of volumes packed before")
    ap.add_argument("--slug", default=SLUG, help="the answers to pack (a volume is finished when each "
                                                 "tile has this slug's .meta.json)")
    args = ap.parse_args(argv)
    vols = Path(args.vols)
    label = vols.stem.removeprefix("volumes_")
    out = TIERS / f"answers_{label}"
    out.mkdir(parents=True, exist_ok=True)
    idents = [line.split("\t")[0] for line in vols.read_text(encoding="utf-8").splitlines()[1:] if line]
    counts = {"packed now": 0, "packed before": 0, "reading": 0, "not cut": 0}
    for ident in idents:
        root, tar = TIERS / ident, out / f"{ident}.tar"
        if tar.exists():
            counts["packed before"] += 1
            if args.prune:
                for jpg in (root / ident).glob("*.jpg"):
                    jpg.unlink()
            continue
        if not (root / "STAGED").exists():
            counts["not cut"] += 1
            continue
        tiles, left = tiles_of(ident, args.slug)
        if left:
            counts["reading"] += 1
            print(f"{ident:32s} {len(tiles) - len(left):6,} of {len(tiles):6,} tiles answered")
            continue
        tmp = tar.with_name(tar.name + ".part")
        with tarfile.open(tmp, "w") as tf:
            for name in ("boxes.json", "columns.json", "STAGED"):
                if (root / name).exists():
                    tf.add(root / name, arcname=str((root / name).relative_to(REPO)))
            for f in sorted((root / ident).glob(f"*_{args.slug}.*")):
                tf.add(f, arcname=str(f.relative_to(REPO)))
        tmp.rename(tar)
        counts["packed now"] += 1
        print(f"{ident:32s} {len(tiles):6,} tiles -> {tar.relative_to(REPO)} "
              f"({tar.stat().st_size / 1e6:.0f} MB)")
    print(" | ".join(f"{k}: {v}" for k, v in counts.items()) + f"  ({len(idents)} volumes)")
    print(f"send: {out.relative_to(REPO)}/*.tar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
