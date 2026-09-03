#!/bin/bash
# load-config.sh - Load and parse configuration from .improvement-workflow.json
#
# Usage: source load-config.sh
#
# Exports:
#   ANALYSIS_MODEL - Model for analysis phase
#   REVIEW_MODEL - Model for review phase
#   WORKTREE_BASE_PATH - Base path for worktree creation
#   WORKTREE_PREFIX - Prefix for worktree directory names
#
# If .improvement-workflow.json doesn't exist, copies default config.

set -euo pipefail

# Find repo root (where .git is)
find_repo_root() {
    local dir="$PWD"
    while [ "$dir" != "/" ]; do
        if [ -d "$dir/.git" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    echo "Error: Not in a git repository" >&2
    return 1
}

# Parse JSON using available parser
parse_json() {
    local file="$1"
    local field="$2"
    local default="$3"
    
    if command -v jq &> /dev/null; then
        jq -r ".$field // \"$default\"" "$file"
    elif command -v python3 &> /dev/null; then
        python3 -c "
import json, sys
try:
    with open('$file') as f:
        data = json.load(f)
    keys = '$field'.split('.')
    result = data
    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            result = None
            break
    print(result if result is not None else '$default')
except:
    print('$default')
"
    else
        echo "Error: jq or python3 is required for config parsing" >&2
        return 1
    fi
}

# Load config from JSON file
load_config() {
    local repo_root="$1"
    local config_file="$repo_root/.improvement-workflow.json"
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local default_config="$script_dir/../config.json"
    
    # Check if parser is available
    if ! command -v jq &> /dev/null && ! command -v python3 &> /dev/null; then
        echo "Error: jq or python3 is required for config parsing" >&2
        echo "Install jq with: sudo apt-get install jq" >&2
        return 1
    fi
    
    # Create config if it doesn't exist
    if [ ! -f "$config_file" ]; then
        echo "Creating .improvement-workflow.json from defaults..."
        cp "$default_config" "$config_file"
    fi
    
    # Validate config file is valid JSON
    if command -v jq &> /dev/null; then
        if ! jq empty "$config_file" 2>/dev/null; then
            echo "Error: .improvement-workflow.json is not valid JSON" >&2
            return 1
        fi
    elif command -v python3 &> /dev/null; then
        if ! python3 -c "import json; json.load(open('$config_file'))" 2>/dev/null; then
            echo "Error: .improvement-workflow.json is not valid JSON" >&2
            return 1
        fi
    fi
    
    # Export config values with defaults
    export ANALYSIS_MODEL=$(parse_json "$config_file" "analysisModel" "z-ai/glm-5.3-flash")
    export REVIEW_MODEL=$(parse_json "$config_file" "reviewModel" "xiaomi/mimo-v2.5")
    export WORKTREE_BASE_PATH=$(parse_json "$config_file" "worktreeBasePath" "~/workspace")
    export WORKTREE_PREFIX=$(parse_json "$config_file" "worktreePrefix" "agentic-workflows-improve")
    
    # Expand ~ in worktree base path
    WORKTREE_BASE_PATH="${WORKTREE_BASE_PATH/#\~/$HOME}"
    export WORKTREE_BASE_PATH
    
    return 0
}

# Main execution
REPO_ROOT=$(find_repo_root) || exit 1
load_config "$REPO_ROOT" || exit 1

# Print loaded config if verbose
if [ "${VERBOSE:-false}" = "true" ]; then
    echo "Configuration loaded:"
    echo "  ANALYSIS_MODEL: $ANALYSIS_MODEL"
    echo "  REVIEW_MODEL: $REVIEW_MODEL"
    echo "  WORKTREE_BASE_PATH: $WORKTREE_BASE_PATH"
    echo "  WORKTREE_PREFIX: $WORKTREE_PREFIX"
fi
