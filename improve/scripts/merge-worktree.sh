#!/bin/bash
# merge-worktree.sh - Merge worktree branch to main and cleanup
#
# Usage: merge-worktree.sh <worktree-path>
#
# Input:
#   $1: Worktree path
#
# Output: Success/failure status
#
# Actions:
#   - Switch to main branch
#   - Merge worktree branch
#   - Handle merge conflicts
#   - Remove worktree
#   - Remove branch

set -euo pipefail

# Get script directory for sourcing helpers
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source git operations
source "$SCRIPT_DIR/git-operations.sh"

# Check arguments
if [ $# -lt 1 ]; then
    echo "Usage: merge-worktree.sh <worktree-path>" >&2
    exit 1
fi

WORKTREE_PATH="$1"

# Check if worktree exists
if [ ! -d "$WORKTREE_PATH" ]; then
    echo "Error: Worktree not found: $WORKTREE_PATH" >&2
    exit 1
fi

# Get branch name from worktree
BRANCH_NAME=$(git -C "$WORKTREE_PATH" branch --show-current)

if [ -z "$BRANCH_NAME" ]; then
    echo "Error: Could not determine branch name from worktree" >&2
    exit 1
fi

echo "Merging worktree branch to main..."
echo "  Worktree: $WORKTREE_PATH"
echo "  Branch: $BRANCH_NAME"

# Get repo root
REPO_ROOT=$(get_repo_root)

# Switch to main branch in main working directory
cd "$REPO_ROOT"
echo "Switching to main branch..."
git checkout main

# Merge branch
echo "Merging branch: $BRANCH_NAME"
if git merge "$BRANCH_NAME" --no-edit; then
    echo "✓ Merge successful"
else
    echo ""
    echo "⚠ Merge conflicts detected"
    echo "Please resolve conflicts in: $REPO_ROOT"
    echo "Then run: git merge --continue"
    echo ""
    echo "After resolving, clean up manually:"
    echo "  git worktree remove $WORKTREE_PATH"
    echo "  git branch -d $BRANCH_NAME"
    exit 1
fi

# Remove worktree
echo "Removing worktree..."
git worktree remove "$WORKTREE_PATH"

# Remove branch
echo "Removing branch..."
git branch -d "$BRANCH_NAME"

echo ""
echo "✓ Merge complete"
echo "✓ Worktree removed"
echo "✓ Branch removed"
echo ""
echo "Changes are ready to push to remote"
