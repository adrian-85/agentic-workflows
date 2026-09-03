#!/bin/bash
# find-session.sh - Locate a pi session file for analysis
#
# Usage:
#   find-session.sh              # Most recently modified session file
#   find-session.sh <id>         # Resolve a partial/full session ID to a file path
#   find-session.sh <path>       # Echo path if it is an existing session file
#
# Output: Absolute path to the session file (JSONL)

set -euo pipefail

SESSIONS_DIR="$HOME/.pi/agent/sessions"

if [ $# -ge 1 ]; then
    TARGET="$1"

    # Case 1: an existing file path was given directly
    if [ -f "$TARGET" ]; then
        readlink -f "$TARGET"
        exit 0
    fi

    # Case 2: resolve a partial/full session ID
    MATCHES=$(find "$SESSIONS_DIR" -name "*${TARGET}*.jsonl" -type f 2>/dev/null || true)
    COUNT=$(echo -n "$MATCHES" | grep -c . || true)

    if [ "$COUNT" -eq 0 ]; then
        echo "Error: No session file matching ID: $TARGET" >&2
        exit 1
    fi
    if [ "$COUNT" -gt 1 ]; then
        echo "Error: Ambiguous session ID ($COUNT matches):" >&2
        echo "$MATCHES" >&2
        exit 1
    fi

    readlink -f "$MATCHES"
    exit 0
fi

# Default: most recently modified session file
RECENT=$(find "$SESSIONS_DIR" -name "*.jsonl" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

if [ -z "$RECENT" ]; then
    echo "Error: No session files found in $SESSIONS_DIR" >&2
    exit 1
fi

readlink -f "$RECENT"
