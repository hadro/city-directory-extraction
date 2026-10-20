#!/usr/bin/env bash
# Bring data/browse.db up to date with the record files, then browse it at
# http://127.0.0.1:8001/browse/records (browse/README.md).
#
#   bash browse/serve.sh              # build, then serve
#   bash browse/serve.sh --no-build   # serve the database as it is (a copy without the files)
#   bash browse/serve.sh --port 8002  # anything else goes to datasette
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "--no-build" ]]; then
  shift
else
  python3 browse/build_db.py
fi
# --reload restarts Datasette when metadata.yml changes (column order, facets, descriptions), so
# an edit shows on the next page load. It does not watch the plugin's code -- restart this for
# that -- nor the database, which Datasette reads live anyway. No `serve` subcommand: it is the default, and with --reload the
# restarter re-runs serve with that word as a database path. The limits: ~1 GB for 0.8M rows
# needs more than the defaults.
exec uvx datasette==0.65.5 data/browse.db \
  --metadata browse/metadata.yml --plugins-dir browse/plugins --reload \
  --setting sql_time_limit_ms 5000 \
  --setting facet_time_limit_ms 3000 \
  --setting suggest_facets off \
  --setting default_facet_size 12 \
  "$@"
