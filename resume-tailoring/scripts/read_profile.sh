#!/bin/sh
# Dump the LinkedIn data-export folder (CSVs — plain text) as one readable
# stream for the tailoring workflow. Resume tailoring cross-references this
# for content the master resume may have compressed away (sub-roles, extra
# bullets). The CSVs are plain text, so no pdftotext is needed.
#
# THIS WHOLE DUMP is the unit of work for SKILL Step 1 — run it once into a
# file and read the file. Do not hand-`cat` individual CSVs.
#
# Usage:
#   ./scripts/read_profile.sh                      # the default export folder
#   ./scripts/read_profile.sh <export-dir>         # a specific export folder
#   ./scripts/read_profile.sh > /tmp/profile.txt
#
# The default resolves the newest `Basic_LinkedInDataExport_*` folder in the
# skill root. Pass an explicit directory to target another export.

set -e
cd "$(dirname "$0")/.."   # skill root, where the LinkedIn export folder lives

EXPORT_DIR="${1:-}"
if [ -z "$EXPORT_DIR" ]; then
  # Resolve the newest Basic_LinkedInDataExport_* folder. The date in the
  # folder name changes with each export, so never hardcode a specific one.
  if ls -d Basic_LinkedInDataExport_* >/dev/null 2>&1; then
    EXPORT_DIR="$(ls -d Basic_LinkedInDataExport_* | sort | tail -1)"
  else
    echo "error: no LinkedIn export folder found in $(pwd)." >&2
    echo "Expected a Basic_LinkedInDataExport_* directory, or pass one as an argument." >&2
    exit 1
  fi
fi

if [ ! -d "$EXPORT_DIR" ]; then
  echo "error: not a directory: $EXPORT_DIR" >&2
  exit 1
fi

FOUND=0
for csv in "$EXPORT_DIR"/*.csv; do
  [ -f "$csv" ] || continue
  FOUND=1
  echo ""
  echo "===== $(basename "$csv" .csv) ($(basename "$EXPORT_DIR")) ====="
  cat "$csv"
done

if [ "$FOUND" -eq 0 ]; then
  echo "error: no .csv files found in $EXPORT_DIR" >&2
  exit 1
fi
