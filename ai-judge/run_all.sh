#!/usr/bin/env bash
#
# Run the judge across all transcripts in a directory.
# Loads OpenRouter credentials from Pi's auth store, then invokes judge.py.
#
# Each execution creates a new timestamped subfolder under OUTDIR so runs
# never overwrite each other (needed when running repeatedly to verify judge
# accuracy). The run folder contains one JSON per transcript plus a
# run_meta.json manifest.
#
set -euo pipefail
cd "$(dirname "$0")"

TRANSCRIPTS="${1:-./transcripts}"
OUTDIR="${2:-./judgments}"

AUTH="$HOME/.pi/agent/auth.json"
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f "$AUTH" ]; then
  export OPENAI_API_KEY=$(python3 -c 'import json;print(json.load(open("'"$AUTH"'"))["openrouter"]["key"])')
fi
if [ -z "${OPENAI_BASE_URL:-}" ]; then
  export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
fi

# Any extra args after the two positional args are forwarded to judge.py.
# --prepass-only runs just the deterministic checks with no API cost.
# Drop that flag to also run the LLM judge.
python3 judge.py --input "$TRANSCRIPTS" --rubric default_rubric.json \
  --output "$OUTDIR" "${@:3}"

echo
# Resolve the most recent run folder for the message.
LAST=$(ls -dt "$OUTDIR"/run-* 2>/dev/null | head -1)
echo "Done. Judgments in ${LAST:-$OUTDIR}"