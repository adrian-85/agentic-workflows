#!/bin/bash
# git-operations.sh - Shared git helper functions
#
# Usage: source git-operations.sh
#
# Functions:
#   get_repo_root() - Get repository root path
#   get_current_branch() - Get current git branch
#   check_worktree_exists() - Check if worktree exists
#   list_worktrees() - List all worktrees
#   commit_changes() - Commit with message
#   get_diff() - Get diff between branches

set -euo pipefail

# Get repository root path
get_repo_root() {
    git rev-parse --show-toplevel
}

# Get current git branch
get_current_branch() {
    git branch --show-current
}

# Check if worktree exists for a given path
# Usage: check_worktree_exists <path>
check_worktree_exists() {
    local path="$1"
    git worktree list | grep -q "$path"
}

# List all worktrees
list_worktrees() {
    git worktree list
}

# Get worktree path for a branch
# Usage: get_worktree_path <branch>
get_worktree_path() {
    local branch="$1"
    git worktree list | grep "$branch" | awk '{print $1}'
}

# Commit changes with message
# Usage: commit_changes <message>
commit_changes() {
    local message="$1"
    git add -A
    if git diff --cached --quiet; then
        echo "No changes to commit"
        return 0
    fi
    git commit -m "$message"
}

# Get diff between current branch and main
# Usage: get_diff [base_branch]
get_diff() {
    local base_branch="${1:-main}"
    git diff "$base_branch"...HEAD
}

# Get diff stat between current branch and main
# Usage: get_diff_stat [base_branch]
get_diff_stat() {
    local base_branch="${1:-main}"
    git diff "$base_branch"...HEAD --stat
}

# Check if working directory is clean
is_working_clean() {
    git diff --quiet && git diff --cached --quiet
}

# Stash changes
stash_changes() {
    if ! is_working_clean; then
        git stash push -m "Auto-stash for workflow improvement"
        return 0
    fi
    return 1
}

# Pop stashed changes
pop_stash() {
    git stash pop
}
