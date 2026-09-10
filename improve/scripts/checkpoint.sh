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
#
# Gate 4 additionally requires a verify-worktree.sh PASS recorded for the
# current HEAD (verify-worktree.sh writes it into the state file on success).
# Record gate 4 from inside the worktree, after the last commit.

set -euo pipefail

STATE_FILE="${IMPROVE_CHECKPOINT_FILE:-/tmp/improve-workflow-checkpoint.json}"

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

    # Gate 4 is authorized by a verify-worktree.sh pass on the current HEAD.
    if [ "$n" = "4" ]; then
        local head sha
        head=$(git rev-parse HEAD 2>/dev/null) || {
            echo "BLOCKED: gate 4 must be recorded from inside the worktree (cwd is not a git repository)." >&2
            exit 1
        }
        sha=$(jq -r '.verify.sha // ""' "$STATE_FILE")
        if [ "$sha" != "$head" ]; then
            echo "BLOCKED: gate 4 requires a verify-worktree.sh PASS on the current HEAD ($head)." >&2
            echo "Run verify-worktree.sh inside the worktree after the last commit, then record gate 4." >&2
            exit 1
        fi
    fi

    # Warn on out-of-order recording (e.g. gate 4 before gate 3).
    local m
    for m in 1 2 3; do
        [ "$n" -gt "$m" ] || continue
        if ! jq -e --arg m "$m" '.gates[$m].passed == true' "$STATE_FILE" > /dev/null 2>&1; then
            echo "WARNING: gate $m was never recorded — recording gate $n out of order." >&2
        fi
    done

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
