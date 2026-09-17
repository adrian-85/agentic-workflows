#!/usr/bin/env bash
# Pre-verified tailor-script runner (SKILL Step 8's per-target script loop).
#
# A real session hand-typed two find_p prefixes that missed the master and
# re-typed an AST-parse check before every run — a run-crash-fix cycle per
# miss. This wrapper does all checks FIRST, then executes the script under
# the strict edit gate (exit 2 on any skipped edit):
#
#   1. ast.parse the script            (syntax errors before any edit)
#   2. docx_edit.py <docx> --lint-script <script>
#        every find_p target must resolve against the master (exit 1 on miss)
#   3. docx_edit.py <docx> --lint-prune <script>
#        every <master>.prune.json candidate (emitted by the Step-3 prune
#        plan) must be addressed by an edit or a "# kept:" reason
#        (exit 1 on uncovered — the motivating session skipped the plan's
#        word/sentence-level trims and needed two user prompts)
#   4. DOCX_EDIT_STRICT=1 python3 <script>   (env, incl. RESUME_VALIDATE_ARGS,
#        passes through)
#
# usage:
#   RESUME_WORKFLOW_STATE="Name Resume - Target.docx.workflow.json" \
#   RESUME_VALIDATE_ARGS="--jd jd_x.txt --jd-years 6 --seniority-approved" \
#       scripts/run_tailor.sh "Name Master Resume.docx" scripts/tailor_x.py
#
# auto_prune sets RESUME_TAILOR_PHASE=prune for its own Phase A run. All
# later runs require a state sidecar at least through ats-theme-reviewed.
# Both paths resolve from the skill root (the script's parent's parent);
# the wrapper cd's there so relative --jd paths in RESUME_VALIDATE_ARGS work.
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: run_tailor.sh <master.docx> <tailor_script.py>" >&2
    echo "  env: RESUME_WORKFLOW_STATE and RESUME_VALIDATE_ARGS" >&2
    exit 2
fi

SCRIPT_PATH="$2"
WORKFLOW_STATE="${RESUME_WORKFLOW_STATE:-}"
SKILL_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
DOCX="$1"

cd "$SKILL_ROOT"
[ -f "$DOCX" ] || { echo "error: docx not found: $DOCX" >&2; exit 2; }
[ -f "$SCRIPT_PATH" ] || { echo "error: script not found: $SCRIPT_PATH" >&2; exit 2; }

if [ "${RESUME_TAILOR_PHASE:-}" != "prune" ]; then
    [ -n "$WORKFLOW_STATE" ] || {
        echo "error: Phase 2 tailoring requires RESUME_WORKFLOW_STATE" >&2
        exit 2
    }
    python3 scripts/workflow_gate.py require-at-least "$WORKFLOW_STATE" \
        ats-theme-reviewed
fi

python3 -c "import ast; ast.parse(open('$SCRIPT_PATH').read())" \
    || { echo "run_tailor: syntax error in $SCRIPT_PATH" >&2; exit 1; }

python3 scripts/docx_edit.py "$DOCX" --lint-script "$SCRIPT_PATH"

python3 scripts/docx_edit.py "$DOCX" --lint-prune "$SCRIPT_PATH"

DOCX_EDIT_STRICT=1 exec python3 "$SCRIPT_PATH"
