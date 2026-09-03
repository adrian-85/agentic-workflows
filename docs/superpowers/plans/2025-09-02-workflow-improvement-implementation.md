# Workflow Improvement Workflow - Implementation Plan

**Date**: 2025-09-02
**Spec**: `docs/superpowers/specs/2025-09-02-workflow-improvement-design.md`
**Status**: Ready to implement

---

## Overview

This plan implements the workflow improvement feature using a hybrid approach:
- **Programmatic scripts** for deterministic operations (config, git, approval gates)
- **SKILL.md** for non-deterministic guidance (analysis, interpretation, implementation decisions)

---

## Directory Structure

```
~/workspace/agentic-workflows/
├── improve/
│   ├── SKILL.md                  # Workflow guidance and orchestration
│   ├── config.json               # Default configuration (copied to repo root on first run)
│   └── scripts/
│       ├── load-config.sh        # Load and parse configuration
│       ├── analyze-session.sh    # Extract improvement indicators from session
│       ├── setup-worktree.sh     # Create worktree and branch
│       ├── approval-gate.sh      # Handle approval prompts with user input
│       ├── merge-worktree.sh     # Merge branch and cleanup
│       └── git-operations.sh     # Shared git helper functions
└── .improvement-workflow.json    # User configuration (created on first run)
```

---

## Implementation Steps

### Step 1: Create Directory Structure

**Actions:**
1. Create `improve/` directory
2. Create `improve/scripts/` directory
3. Create placeholder files

**Verification:** Directory structure exists

---

### Step 2: Create Configuration Files

**Files to create:**
```
improve/config.json              # Default config template
.improvement-workflow.json       # User config (created on first run)
```

**Actions:**
1. Create `improve/config.json` with default values:
   ```json
   {
     "analysisModel": "deepseek/deepseek-v4-flash-0731",
     "reviewModel": "deepseek/deepseek-v4-flash-0731",
     "worktreeBasePath": "~/workspace",
     "worktreePrefix": "agentic-workflows-improve"
   }
   ```
2. Document that `.improvement-workflow.json` is created in repo root on first run

**Verification:** Config template valid JSON, defaults sensible

---

### Step 3: Implement `load-config.sh`

**File:** `improve/scripts/load-config.sh`

**Purpose:** Load configuration from `.improvement-workflow.json` or defaults

**Actions:**
1. Check for `.improvement-workflow.json` in repo root
2. If exists, parse with `jq` and export variables
3. If not exists, copy `improve/config.json` to repo root as `.improvement-workflow.json`
4. Export: `ANALYSIS_MODEL`, `REVIEW_MODEL`, `WORKTREE_BASE_PATH`, `WORKTREE_PREFIX`
5. Validate required fields exist

**Verification:** Script loads config correctly, handles missing file

---

### Step 4: Implement `analyze-session.sh`

**File:** `improve/scripts/analyze-session.sh`

**Purpose:** Extract improvement indicators from session transcript

**Input:** Session ID or session file path

**Output:** Structured JSON with analysis results

**Actions:**
1. Accept session identifier as argument
2. Read session file (JSONL format)
3. Extract and analyze:
   - Workflow invocations (which workflow was used)
   - Clarification questions (agent asked for more info)
   - Tool/command patterns (repetitive actions)
   - Skill file reads and deviations
4. Generate structured output:
   ```json
   {
     "workflow": "resume-tailoring",
     "indicators": [
       {"type": "clarification", "count": 3, "examples": [...]},
       {"type": "repetitive_commands", "commands": [...], "count": 5},
       {"type": "skill_deviation", "description": "..."}
     ],
     "suggestions": [...]
   }
   ```
5. Handle errors (invalid session, no workflow found)

**Verification:** Script extracts meaningful indicators from test session

---

### Step 5: Implement `approval-gate.sh`

**File:** `improve/scripts/approval-gate.sh`

**Purpose:** Handle approval prompts with user input

**Input:** 
- `$1`: Gate name (e.g., "analysis", "quality-review", "final")
- `$2`: Path to proposal file (markdown or JSON)

**Output:** Exit code 0 (approved), 1 (declined), 2 (modifications requested)

**Actions:**
1. Display gate header
2. Read and display proposal content
3. Prompt user for decision:
   - `[a]pprove` - proceed with implementation
   - `[d]ecline` - stop workflow
   - `[m]odify` - request changes
4. Handle response:
   - `approve`: exit 0
   - `decline`: exit 1
   - `modify`: prompt for modification text, write to file, exit 2
5. Include timeout option (default: no timeout)

**Verification:** Script correctly handles all response types

---

### Step 6: Implement `setup-worktree.sh`

**File:** `improve/scripts/setup-worktree.sh`

**Purpose:** Create git worktree and branch for isolated work

**Input:**
- `$1`: Workflow name
- `$2`: Base path (optional, from config)

**Output:** Worktree path

**Actions:**
1. Load config to get `WORKTREE_BASE_PATH` and `WORKTREE_PREFIX`
2. Generate worktree name: `<workflow-name>-<timestamp>`
3. Generate branch name: `improve/<workflow-name>-<timestamp>`
4. Check if worktree already exists:
   - If exists, prompt user for alternative name or abort
5. Create worktree:
   ```bash
   git worktree add "$BASE_PATH/$WORKTREE_PREFIX/$NAME" -b "$BRANCH"
   ```
6. Return worktree path

**Verification:** Worktree created, branch exists, path returned

---

### Step 7: Implement `merge-worktree.sh`

**File:** `improve/scripts/merge-worktree.sh`

**Purpose:** Merge worktree branch to main and cleanup

**Input:**
- `$1`: Worktree path

**Output:** Success/failure status

**Actions:**
1. Get current branch from worktree
2. Switch to main branch: `git checkout main`
3. Merge branch: `git merge <branch>`
4. Handle merge conflicts:
   - If conflicts, present to user
   - User resolves conflicts
   - Continue merge
5. Remove worktree: `git worktree remove <path>`
6. Remove branch: `git branch -d <branch>`
7. Inform user changes ready to push

**Verification:** Merge successful, worktree cleaned up

---

### Step 8: Implement `git-operations.sh`

**File:** `improve/scripts/git-operations.sh`

**Purpose:** Shared git helper functions

**Functions:**
- `get_current_branch()` - Get current git branch
- `get_repo_root()` - Get repository root path
- `check_worktree_exists()` - Check if worktree exists
- `list_worktrees()` - List all worktrees
- `commit_changes()` - Commit with message
- `get_diff()` - Get diff between branches

**Verification:** Functions work correctly

---

### Step 9: Create SKILL.md

**File:** `improve/SKILL.md`

**Purpose:** Workflow guidance for non-deterministic parts

**Content:**
- Frontmatter with name and description
- Overview of the workflow
- Phase 1: Analysis guidance
  - Invoke `analyze-session.sh`
  - Interpret results
  - Generate improvement suggestions
  - Present to user via `approval-gate.sh`
- Phase 2: Implementation guidance
  - Invoke `setup-worktree.sh`
  - Implement approved changes
  - Commit changes
- Phase 3: Quality review guidance
  - Invoke code-simplicity-reviewer
  - Invoke writing-skills
  - Present findings via `approval-gate.sh`
  - Implement quality improvements
- Phase 4: Final merge guidance
  - Present final diff
  - Get approval via `approval-gate.sh`
  - Invoke `merge-worktree.sh`
- Error handling guidance
- Edge case handling guidance

**Verification:** SKILL.md is clear, references scripts correctly

---

### Step 10: Implement Approval Gate Flow

**Files to modify:**
```
improve/SKILL.md
```

**Purpose:** Wire up approval gates at each phase

**Actions:**
1. Phase 1 approval gate:
   - After analysis, write suggestions to `.pending-analysis.md`
   - Invoke `approval-gate.sh analysis .pending-analysis.md`
   - Handle response (approve/decline/modify)
2. Phase 2 approval gate:
   - After quality review, write suggestions to `.pending-quality.md`
   - Invoke `approval-gate.sh quality-review .pending-quality.md`
   - Handle response
3. Phase 3 approval gate:
   - After all implementation, write diff summary to `.pending-final.md`
   - Invoke `approval-gate.sh final .pending-final.md`
   - Handle response

**Verification:** All approval gates wired correctly

---

### Step 11: Add Error Handling

**Files to modify:**
```
improve/scripts/*.sh
improve/SKILL.md
```

**Purpose:** Handle error conditions gracefully

**Actions:**
1. Add error handling to all scripts:
   - Check exit codes
   - Provide meaningful error messages
   - Clean up partial changes on failure
2. Document error scenarios in SKILL.md
3. Add recovery guidance

**Verification:** Errors handled gracefully, no partial states left

---

### Step 12: Add Edge Case Handling

**Files to modify:**
```
improve/SKILL.md
```

**Purpose:** Handle edge cases from spec

**Actions:**
1. No workflow identified: prompt user to specify
2. Worktree name collision: prompt for alternative
3. Merge conflicts: present to user for resolution
4. Phase declined: clean up appropriately
5. Session interrupted: document worktree persistence

**Verification:** All edge cases addressed

---

## Implementation Order

1. **Steps 1-2**: Directory structure and config
2. **Steps 3-4**: Config loading and session analysis
3. **Step 5**: Approval gate script
4. **Steps 6-8**: Git operations (worktree, merge, helpers)
5. **Step 9**: SKILL.md creation
6. **Steps 10-12**: Wiring up gates and edge cases

---

## Dependencies

- `jq` for JSON parsing
- Git 2.5+ for worktree support
- Pi with `--fork` support
- Bash 4.0+ for modern features

---

## Verification Strategy

1. Unit test each script independently
2. Integration test full flow with mock session
3. Test approval gates with user interaction
4. Test worktree creation and merge
5. Test error handling scenarios
6. Manual verification with real workflow

---

## Success Criteria

1. Scripts handle all deterministic operations
2. SKILL.md guides non-deterministic decisions
3. Approval gates work with user input
4. Worktree isolation prevents interference
5. Merge back to main is clean
6. Error handling is graceful
7. User informed when changes ready to push
