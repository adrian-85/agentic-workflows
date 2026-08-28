#!/bin/sh
# Extract readable text from the bundled LinkedIn Profile.pdf (binary — a
# plain file read returns garbage). Resume tailoring cross-references this
# for content the master resume may have compressed away (sub-roles, extra
# bullets).
#
# Usage:
#   ./scripts/read_profile.sh                  # print to stdout
#   ./scripts/read_profile.sh > /tmp/profile.txt
#
# Requires `pdftotext` (poppler-utils). Prints a hint if it's missing.

set -e
cd "$(dirname "$0")/.."   # skill root, where Profile.pdf lives

if ! command -v pdftotext >/dev/null 2>&1; then
  echo "error: pdftotext not found. Install poppler-utils (Debian/Ubuntu:" \
       "sudo apt install poppler-utils)." >&2
  exit 1
fi

if [ ! -f "Profile.pdf" ]; then
  echo "error: Profile.pdf not found in $(pwd)." >&2
  exit 1
fi

exec pdftotext -layout "Profile.pdf" -
