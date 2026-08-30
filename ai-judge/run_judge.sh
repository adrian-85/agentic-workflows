#!/usr/bin/env bash
#
# Thin wrapper: load OpenRouter credentials from Pi's auth store, then run judge.py.
# If OPENAI_API_KEY / OPENAI_BASE_URL are already set, they take precedence.
#
set -euo pipefail
cd "$(dirname "$0")"

AUTH="$HOME/.pi/agent/auth.json"
if [ -z "${OPENAI_API_KEY:-}" ] && [ -f "$AUTH" ]; then
  export OPENAI_API_KEY=$(python3 -c 'import json;print(json.load(open("'$AUTH'"))["openrouter"]["key"])')
fi
if [ -z "${OPENAI_BASE_URL:-}" ]; then
  export OPENAI_BASE_URL="https://openrouter.ai/api/v1"
fi

python3 judge.py "$@"