#!/bin/bash
# setup-worktree.sh - Create git worktree and branch for isolated work
#
# Usage: setup-worktree.sh <workflow-name> [base-path]
#
# Input:
#   $1: Workflow name (e.g., "resume-tailoring")
#   $2: Base path (optional, defaults to config)
#
# Output: Worktree path to stdout
#
# Creates:
#   - Worktree at <base-path>/<prefix>/<workflow-name>-<timestamp>
#   - Branch: improve/<workflow-name>-<timestamp>

set -euo pipefail

# Get script directory for sourcing helpers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source git operations
source "$SCRIPT_DIR/git-operations.sh"

# Source config
source "$SCRIPT_DIR/load-config.sh"

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: setup-worktree.sh <workflow-name> [base-path]" >&2
    exit 1
fi

WORKFLOW_NAME="$1"
BASE_PATH="${2:-$WORKTREE_BASE_PATH}"

# Generate names
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
WORKTREE_NAME="${WORKFLOW_NAME}-${TIMESTAMP}"
BRANCH_NAME="improve/${WORKFLOW_NAME}-${TIMESTAMP}"
WORKTREE_PATH="${BASE_PATH}/${WORKTREE_PREFIX}/${WORKTREE_NAME}"

# Check if worktree path already exists
if [ -d "$WORKTREE_PATH" ]; then
    echo "Error: Worktree path already exists: $WORKTREE_PATH" >&2
    echo "Please choose a different name or remove the existing worktree" >&2
    exit 1
fi

# Ensure base path exists
mkdir -p "$BASE_PATH/${WORKTREE_PREFIX}"

# Create worktree
echo "Creating worktree..."
echo "  Path: $WORKTREE_PATH"
echo "  Branch: $BRANCH_NAME"

git worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME"

# Verify worktree was created
if [ ! -d "$WORKTREE_PATH" ]; then
    echo "Error: Failed to create worktree" >&2
    exit 1
fi

# Output worktree path
echo "$WORKTREE_PATH"
