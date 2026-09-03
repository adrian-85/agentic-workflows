#!/bin/bash
# checkpoint.sh — Gate checkpoint enforcement for the improve workflow.
#
# Usage:
#   checkpoint.sh gate <N>        # Mark gate N as passed
#   checkpoint.sh require <N>     # Fail (exit 1) unless gate N was passed
#   checkpoint.sh status          # Print state of all four gates
#   checkpoint.sh reset           # Clear all state (new run)
#
# State file: /tmp/improve-workflow-checkpoint.json
# Gates follow the hard stops in SKILL.md:
#   1 = analysis approved          2 = model switched
#   3 = quality review approved    4 = final review approved

set -euo pipefail

STATE_FILE="/tmp/improve-workflow-checkpoint.json"

usage() {
    echo "Usage: checkpoint.sh {gate <N>|require <N>|status|reset}" >&2
    exit 1
}

ensure_state() {
    [ -f "$STATE_FILE" ] || echo '{"gates":{}}' > "$STATE_FILE"
}

gate() {
    local n="${1:-}"
    [ -n "$n" ] || usage
    ensure_state
    local tmp
    tmp=$(mktemp)
    jq --arg n "$n" '.gates[$n].passed = true' "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
    echo "Gate $n recorded."
}

require() {
    local n="${1:-}"
    [ -n "$n" ] || usage
    ensure_state
    if jq -e --arg n "$n" '.gates[$n].passed == true' "$STATE_FILE" > /dev/null; then
        exit 0
    fi
    echo "BLOCKED: Gate $n has not been passed." >&2
    echo "The previous phase must be completed and approved before continuing." >&2
    exit 1
}

status() {
    ensure_state
    jq -r '("1","2","3","4") as $n |
        "\($n): \(if .gates[$n].passed == true then "✓" else "✗" end)"' "$STATE_FILE"
}

reset() {
    echo '{"gates":{}}' > "$STATE_FILE"
    echo "State cleared."
}

case "${1:-}" in
    gate)    gate "${2:-}" ;;
    require) require "${2:-}" ;;
    status)  status ;;
    reset)   reset ;;
    *)       usage ;;
esac
