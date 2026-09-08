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
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "== verify-worktree: dependencies =="
# Prefer an existing pinned venv (local dev); otherwise install into the
# active python. pylint must be on PATH for the lint step below.
if [ -x /tmp/lintvenv/bin/pylint ]; then
    PY_BIN=/tmp/lintvenv/bin/python
    export PATH="/tmp/lintvenv/bin:$PATH"
elif command -v pylint >/dev/null 2>&1 && pylint --version >/dev/null 2>&1; then
    PY_BIN=python3
    echo "using system pylint: $(pylint --version | head -1)"
else
    python3 -m pip install --quiet --break-system-packages \
        -r p2p-qa-lab/requirements.txt pylint==4.0.8 2>/dev/null \
      || python3 -m pip install --quiet -r p2p-qa-lab/requirements.txt pylint==4.0.8
    PY_BIN=python3
fi

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
    (cd resume-tailoring/scripts && python3 -m unittest test_docx_edit \
        test_measure_resume test_validate_resume test_ats_check \
        test_ats_audit test_squeeze_resume)
    echo "✓ resume-tailoring suite green"
else
    echo "resume-tailoring not touched — skipping its suite"
fi

if printf '%s\n' "$CHANGED" | grep -q '^p2p-qa-lab/'; then
    echo "-- p2p-qa suite --"
    (cd p2p-qa-lab && python3 -m pytest tests -x -q \
        --ignore=tests/test_dspy_live.py --ignore=tests/test_hacker_live.py \
        --ignore=tests/test_explorer_live.py --ignore=tests/test_report_live.py)
    echo "✓ p2p-qa suite green"
else
    echo "p2p-qa-lab not touched — skipping its suite"
fi
echo "== verify-worktree: PASS =="