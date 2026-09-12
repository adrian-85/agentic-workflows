#!/bin/bash
# verify-worktree.sh - Block a worktree merge unless the CHANGE SET passes.
# Hard gate for the improve workflow (spec 2026-09-07-pylint-clean-refactor).
# Scoped by WORKFLOW — the repo is a collection of independent,
# self-contained workflows:
#   - lint: only the Python files this branch touches
#   - tests: the FULL suite of each workflow the change set touches
# A workflow's changes NEVER run another workflow's tests. A change set
# touching several workflows runs each one's full suite. Docs-only or
# config-only changes touch no workflow and run no tests.
#
# Usage:
#   verify-worktree.sh                  full gate: pylint changed py + full
#                                       suites of touched workflows; records
#                                       the pass for checkpoint gate 4
#   verify-worktree.sh preflight <wf>   setup-time checks: pylint invokable +
#                                       source files under the line cap —
#                                       run BEFORE implementing
#   verify-worktree.sh baseline <wf>    run one workflow's full suite on the
#                                       current tree — surfaces pre-existing
#                                       failures in carried-in WIP
#   verify-worktree.sh lint FILE...     ad-hoc lint with the CI-pinned pylint
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# pylint default too-many-lines (C0302) threshold; repo convention: SOURCE
# files must stay under it, test files are exempt (1:1 test→source mapping).
LINE_CAP=1000

# pylint version pin — read from the CI workflow (single source of truth)
# so this gate can never drift from CI. The gate MUST run the pylint CI
# runs: message sets differ between versions, so a gate on the wrong
# version silences live messages (or flags dead ones) that CI then fails
# on. The 1e10a2f/fb53fa6 "strip stale disables" commits ran an unpinned
# pylint, judged live C0413 pragmas stale, and CI went red. Any pylint
# not matching the pin is ignored; a matching one is used in place;
# otherwise /tmp/lintvenv is built with the pinned version.
PYLINT_PIN="$(sed -n 's/.*pip install pylint==\([0-9][0-9.]*\).*/\1/p' \
    .github/workflows/pylint.yml | head -1)"
[ -n "$PYLINT_PIN" ] || {
    echo "cannot read pylint pin from .github/workflows/pylint.yml" >&2
    exit 1
}

pylint_is_pinned() {  # $1: pylint binary (path or PATH name)
    "$1" --version 2>/dev/null | head -1 | grep -qx "pylint $PYLINT_PIN"
}

ensure_pylint() {
    # Resolve a pylint that exactly matches the CI pin ($PYLINT_PIN).
    # Order: existing matching /tmp/lintvenv (fast path, local dev) ->
    # system pylint matching the pin -> build the pinned /tmp/lintvenv.
    if [ -x /tmp/lintvenv/bin/pylint ] \
            && pylint_is_pinned /tmp/lintvenv/bin/pylint; then
        PY_BIN=/tmp/lintvenv/bin/python
        export PATH="/tmp/lintvenv/bin:$PATH"
    elif command -v pylint >/dev/null 2>&1 && pylint_is_pinned pylint; then
        echo "using system pylint $(pylint --version | head -1 | awk '{print $2}') (CI pin $PYLINT_PIN)"
    else
        echo "pylint $PYLINT_PIN not available — building /tmp/lintvenv (CI pin)"
        python3 -m venv /tmp/lintvenv
        /tmp/lintvenv/bin/pip install --quiet \
            -r p2p-qa-lab/requirements.txt "pylint==$PYLINT_PIN"
        PY_BIN=/tmp/lintvenv/bin/python
        export PATH="/tmp/lintvenv/bin:$PATH"
    fi
    # Belt and braces: whatever PATH resolves now MUST be the pinned one.
    pylint_is_pinned pylint || {
        echo "pylint version mismatch: gate requires $PYLINT_PIN (CI pin), got: $(pylint --version 2>/dev/null | head -1)" >&2
        exit 1
    }
}

# Single source of truth for each workflow's test suite — used by the full
# gate and by `baseline`.
run_suite() {
    case "$1" in
    resume-tailoring)
        (cd resume-tailoring/scripts && python3 -m unittest test_docx_edit \
            test_measure_resume test_validate_resume test_ats_check \
            test_ats_audit test_squeeze_resume)
        ;;
    p2p-qa-lab)
        (cd p2p-qa-lab && python3 -m pytest tests -x -q \
            --ignore=tests/test_dspy_live.py --ignore=tests/test_hacker_live.py \
            --ignore=tests/test_explorer_live.py --ignore=tests/test_report_live.py)
        ;;
    *)
        echo "no test suite registered for workflow '$1'" >&2
        return 2
        ;;
    esac
}

record_pass() {
    # Record the passing run for the checkpoint gate: gate 4 requires a
    # verify pass on the current HEAD (see checkpoint.sh).
    if ! command -v jq >/dev/null 2>&1; then
        echo "warning: jq not installed — verify pass not recorded (gate 4 will not authorize)" >&2
        return 1
    fi
    STATE_FILE="${IMPROVE_CHECKPOINT_FILE:-/tmp/improve-workflow-checkpoint.json}"
    [ -f "$STATE_FILE" ] || echo '{"gates":{}}' > "$STATE_FILE"
    tmp=$(mktemp)
    jq --arg sha "$(git rev-parse HEAD)" --arg ts "$(date -Iseconds)" \
        '.verify = {sha: $sha, passed: $ts}' "$STATE_FILE" > "$tmp"
    mv "$tmp" "$STATE_FILE"
    echo "✓ verify pass recorded for $(git rev-parse --short HEAD)"
}

case "${1:-verify}" in

lint)
    # Ad-hoc lint for sessions: the same pylint the gate and CI run, so a
    # local clean can never be a version-skew false negative.
    ensure_pylint
    shift
    pylint "$@"
    ;;

preflight)
    WF="${2:?usage: verify-worktree.sh preflight <workflow>}"
    [ -d "$WF" ] || { echo "workflow dir not found: $WF" >&2; exit 2; }
    ensure_pylint

    echo "== preflight [$WF]: pylint invokable =="
    pylint --version >/dev/null 2>&1 || { echo "pylint still not invokable" >&2; exit 1; }
    echo "✓ pylint invokable: $(pylint --version 2>/dev/null | head -1)"

    echo "== preflight [$WF]: source files vs ${LINE_CAP}-line cap (C0302) =="
    over=0
    while IFS= read -r f; do
        lines=$(wc -l < "$f")
        if [ "$lines" -gt "$LINE_CAP" ]; then
            echo "OVER CAP: $f ($lines lines)"
            over=1
        else
            echo "  ok ($lines lines): $f"
        fi
    done < <(find "$WF" -name '*.py' ! -name 'test_*.py' ! -path '*/tests/*' | sort)
    if [ "$over" -ne 0 ]; then
        echo "✗ preflight: source file(s) exceed the ${LINE_CAP}-line cap — split before implementing" >&2
        exit 1
    fi
    echo "✓ preflight [$WF]: PASS"
    ;;

baseline)
    WF="${2:?usage: verify-worktree.sh baseline <workflow>}"
    [ -d "$WF" ] || { echo "workflow dir not found: $WF" >&2; exit 2; }
    echo "== baseline [$WF]: full suite on the CURRENT tree =="
    set +e
    run_suite "$WF"
    rc=$?
    set -e
    if [ "$rc" -eq 2 ]; then
        exit 0
    elif [ "$rc" -ne 0 ]; then
        echo "✗ baseline [$WF]: failures above are PRE-EXISTING on the carried-in tree" >&2
        exit 1
    fi
    echo "✓ baseline [$WF]: suite green"
    ;;

verify)
    ensure_pylint
    CHANGED="$(git diff --name-only main...HEAD)"

    echo "== verify-worktree: pylint (changed Python files only) =="
    CHANGED_PY="$(printf '%s\n' "$CHANGED" | grep '\.py$' || true)"
    if [ -z "$CHANGED_PY" ]; then
        echo "no Python files changed — skipping pylint"
    else
        echo "$CHANGED_PY"
        pylint $CHANGED_PY
    fi
    echo "✓ pylint clean"

    echo "== verify-worktree: full suite of each touched workflow =="
    if printf '%s\n' "$CHANGED" | grep -q '^resume-tailoring/'; then
        echo "-- resume-tailoring suite --"
        run_suite resume-tailoring
        echo "✓ resume-tailoring suite green"
    else
        echo "resume-tailoring not touched — skipping its suite"
    fi

    if printf '%s\n' "$CHANGED" | grep -q '^p2p-qa-lab/'; then
        echo "-- p2p-qa suite --"
        run_suite p2p-qa-lab
        echo "✓ p2p-qa suite green"
    else
        echo "p2p-qa-lab not touched — skipping its suite"
    fi
    echo "== verify-worktree: PASS =="
    record_pass
    ;;

*)
    echo "usage: verify-worktree.sh [verify | preflight <workflow> | baseline <workflow>]" >&2
    exit 2
    ;;
esac