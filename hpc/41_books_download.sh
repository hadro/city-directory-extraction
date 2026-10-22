#!/bin/bash
# STEP 41 -- on the DATA-TRANSFER NODE, not a login or compute node: each book-scan volume's page
# images from the Internet Archive, for hpc/42_books_tiles.sbatch (docs/PIPELINE.md #27).
#
#     ssh dtn012.torch.hpc.nyu.edu           # one node by name: the dtn alias rotates host keys
#     cd /scratch/$USER/city-directory-extraction
#     nohup bash hpc/41_books_download.sh data/reocr_books_records/volumes_abbyy8-damaged.tsv \
#         > logs/download-abbyy8-damaged.log 2>&1 &
#     tail -f logs/download-abbyy8-damaged.log
#
# The TSV (data_prep/reocr_books.py records, on the Mac) lists each volume's archive on IA,
# <id>_jp2.zip or <id>_jp2.tar, and its size in bytes. Files land in data/reocr_zips/. JOBS
# transfers run at once (default 4): archive.org gives one stream 3-6 MB/s on a first fetch
# (NYU, 2026-10-21), so a few in parallel is what fills the link.
#
# Resumable: a file already at its full size is skipped, and a partial one (<name>.part) resumes
# with curl -C -. Only a file of exactly the listed size is renamed into place, so the tile job
# never reads a partial archive. Re-run the same command after any interruption.
set -uo pipefail

cd "$(dirname "$0")/.."
VOLS="${1:?usage: bash hpc/41_books_download.sh <volumes TSV> [jobs]}"
JOBS="${2:-${JOBS:-4}}"
mkdir -p data/reocr_zips logs

size() { [ -f "$1" ] && wc -c < "$1" | tr -d " " || echo 0; }   # GNU or BSD: no stat -c
export -f size

fetch() {   # fetch <ident> <archive> <bytes>
    local id=$1 name=$2 bytes=$3 dst="data/reocr_zips/$2" got try
    if [ "$(size "$dst")" = "$bytes" ]; then
        echo "$(date +%T) $id: have it"; return 0
    fi
    for try in 1 2 3 4 5; do
        curl -sSL --retry 5 --retry-delay 20 --connect-timeout 60 -C - -o "$dst.part" \
            "https://archive.org/download/$id/$name"
        got=$(size "$dst.part")
        if [ "$got" = "$bytes" ]; then
            mv "$dst.part" "$dst"
            echo "$(date +%T) $id: $(( bytes / 1000000 )) MB ok"
            return 0
        fi
        [ "$got" -gt "$bytes" ] && rm -f "$dst.part"         # a resume gone wrong: start over
        echo "$(date +%T) $id: $got of $bytes bytes after try $try; retrying in 60s"
        sleep 60
    done
    echo "$(date +%T) $id: FAILED after 5 tries -- re-run this script to resume"
    return 1
}
export -f fetch

echo "$(date) | $(tail -n +2 "$VOLS" | wc -l) volumes from $VOLS | $JOBS at a time | $(hostname)"
tail -n +2 "$VOLS" | awk -F'\t' '{print $1, $3, $4}' | xargs -P "$JOBS" -n 3 bash -c 'fetch "$@"' _
status=$?
have=0; total=0
while IFS=$'\t' read -r id tier name bytes pages; do
    total=$((total + 1))
    [ "$(size "data/reocr_zips/$name")" = "$bytes" ] && have=$((have + 1))
done < <(tail -n +2 "$VOLS")
echo "$(date) | done: $have of $total archives complete in data/reocr_zips"
exit $status
