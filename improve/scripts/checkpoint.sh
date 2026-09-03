#!/bin/bash
# checkpoint.sh — Gate checkpoint enforcement for the improve workflow.
#
# Maintains a small state file so each hard stop is recorded, and the
# next phase refuses to run until its prerequisite gate has been passed.
#
# Usage:
#   checkpoint.sh gate <N>        # Mark gate N as passed
#   checkpoint.sh require <N>     # Fail (exit 1) unless gate N was passed
#   checkpoint.sh status          # Print current state
#   checkpoint.sh reset           # Clear all state (new run)
#
# State file: /tmp/improve-workflow-checkpoint.json
# Gate numbering follows the hard stops in SKILL.md:
#   1 = analysis findings approved  (before implementation)
#   2 = model switched              (before Phase 2)
#   3 = quality review approved     (before implementing quality fixes)
#   4 = final review approved       (before merge)

set -euo pipefail

STATE_FILE="/tmp/improve-workflow-checkpoint.json"

usage() {
    echo "Usage: checkpoint.sh {gate <N>|require <N>|status|reset}" >&2
    exit 1
}

# Ensure state file exists
ensure_state() {
    if [ ! -f "$STATE_FILE" ]; then
        echo '{"gates":{}}' > "$STATE_FILE"
    fi
}

# Record gate N as passed
gate() {
    [ $# -ge 1 ] || usage
    local n="$1"
    ensure_state

    local tmp
    tmp=$(mktemp)
    python3 -c "
import json, sys, datetime
with open('$STATE_FILE') as f:
    state = json.load(f)
state['gates']['$n'] = {
    'passed': True,
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat()
}
with open('$tmp', 'w') as f:
    json.dump(state, f, indent=2)
" && mv "$tmp" "$STATE_FILE"

    echo "Gate $n recorded."
}

# Require gate N to have been passed; exit 1 otherwise
require() {
    [ $# -ge 1 ] || usage
    local n="$1"
    ensure_state

    python3 -c "
import json, sys
with open('$STATE_FILE') as f:
    state = json.load(f)
gate = state.get('gates', {}).get('$n', {})
if gate.get('passed'):
    sys.exit(0)
else:
    print('BLOCKED: Gate $n has not been passed.', file=sys.stderr)
    print('The previous phase must be completed and approved before continuing.', file=sys.stderr)
    sys.exit(1)
"
}

# Print current state
status() {
    ensure_state
    python3 -c "
import json
with open('$STATE_FILE') as f:
    state = json.load(f)
gates = state.get('gates', {})
for n in ['1','2','3','4']:
    g = gates.get(n, {})
    mark = '✓' if g.get('passed') else '✗'
    ts = g.get('at', '—')
    print(f'  Gate {n}: {mark}  {ts}')
"
}

# Clear state
reset() {
    echo '{"gates":{}}' > "$STATE_FILE"
    echo "State cleared."
}

case "${1:-}" in
    gate)   gate "${2:-}" ;;
    require) require "${2:-}" ;;
    status) status ;;
    reset)  reset ;;
    *)      usage ;;
esac
