# Workflow Improvement Workflow - Implementation Plan

**Date**: 2025-09-02
**Spec**: `docs/superpowers/specs/2025-09-02-workflow-improvement-design.md`
**Status**: Ready to implement

---

## Overview

This plan breaks the workflow improvement feature into implementation steps. Each step is a logical unit that can be implemented and verified independently.

---

## Prerequisites

- Git repository at `~/workspace/agentic-workflows/`
- Pi installed with `--fork` support
- Git worktree support enabled

---

## Implementation Steps

### Step 1: Create Workflow Directory Structure

**Files to create:**
```
workflows/improve/
├── SKILL.md                    # Main workflow skill
└── scripts/
    └── parse-config.sh         # Config file parser
```

**Actions:**
1. Create `workflows/improve/` directory
2. Create `workflows/improve/scripts/` directory
3. Create empty `SKILL.md` with frontmatter skeleton
4. Create `scripts/parse-config.sh` skeleton

**Verification:** Directory structure exists, files are valid

---

### Step 2: Create Configuration File

**Files to create:**
```
.improvement-workflow.json      # Configuration
```

**Actions:**
1. Create `.improvement-workflow.json` with default values:
   ```json
   {
     "analysisModel": "deepseek/deepseek-v4-flash-0731",
     "reviewModel": "deepseek/deepseek-v4-flash-0731",
     "worktreeBasePath": "~/workspace",
     "worktreePrefix": "agentic-workflows-improve"
   }
   ```
2. Update `.gitignore` to exclude worktree directories (not config)

**Verification:** Config loads correctly, defaults are sensible

---

### Step 3: Implement Config Loading in SKILL.md

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for config loading:
   - Read `.improvement-workflow.json` from repo root
   - Parse JSON using bash `jq` or similar
   - Set variables: `analysisModel`, `reviewModel`, `worktreeBasePath`, `worktreePrefix`
   - Fallback to defaults if config missing

**Verification:** Config loading documented, fallback behavior clear

---

### Step 4: Implement Session Analysis Logic

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for session transcript analysis:
   - Read current session (use `pi --session <id>` to export or read session file)
   - Identify which workflow was primarily used:
     - Look for workflow invocation patterns (`/workflows:...` or skill references)
     - Count frequency of skill file reads
     - Determine primary workflow name
   - Analyze for improvement indicators:
     - Clarification questions asked by agent
     - Tool/command usage patterns
     - Skill file deviations or workarounds
   - Generate prioritized improvement suggestions

**Verification:** Analysis logic documented, output format defined

---

### Step 5: Implement Approval Gate #1 (Analysis)

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for presenting analysis results:
   - Format suggestions clearly with rationale
   - Include specific session examples
   - Present approval prompt to user
   - Handle approve/decline/modification responses
   - If declined: stop workflow, clean up
   - If modifications requested: iterate until satisfied

**Verification:** Approval gate flow documented, edge cases handled

---

### Step 6: Implement Fork and Worktree Setup

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for session forking:
   - Get current session ID
   - Execute `pi --fork <session-id>` to create forked session
   - Note: This creates a new session file, workflow continues there
2. Add section for worktree creation:
   - Generate worktree name: `<workflow-name>-<timestamp>`
   - Generate branch name: `improve/<workflow-name>-<timestamp>`
   - Execute `git worktree add <path> -b <branch>`
   - Change directory to worktree
3. Add section for handling existing worktrees:
   - Check if worktree already exists for workflow
   - Prompt user for new name or abort

**Verification:** Fork and worktree commands documented, error handling included

---

### Step 7: Implement Phase 1 Improvements Implementation

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for implementing approved improvements:
   - Apply each approved change to workflow files
   - Follow existing patterns in the workflow
   - Write meaningful commit messages
   - Commit after each logical change
2. Add section for implementation tracking:
   - Track what changes were made
   - Track which suggestions were implemented
   - Prepare summary for Phase 2

**Verification:** Implementation steps documented, commit strategy defined

---

### Step 8: Implement Phase 2 Quality Review Integration

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for invoking code-simplicity-reviewer:
   - Read the code-simplicity-reviewer skill
   - Apply review to Phase 1 changes
   - Generate simplification suggestions
2. Add section for invoking writing-skills:
   - Read the writing-skills skill
   - Apply review to Phase 1 changes
   - Generate improvement suggestions
3. Add section for presenting Phase 2 findings:
   - Combine suggestions from both reviews
   - Format clearly for user
   - Present approval prompt

**Verification:** Quality review integration documented, approval gate included

---

### Step 9: Implement Phase 2 Quality Improvements Implementation

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for implementing approved quality improvements:
   - Apply each approved quality change
   - Commit with descriptive messages
   - Track changes for final summary

**Verification:** Quality implementation steps documented

---

### Step 10: Implement Final Review and Merge

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for final review:
   - Generate full diff: `git diff main...HEAD`
   - Summarize all changes made
   - Present to user for final approval
2. Add section for merge to main:
   - Switch to main branch
   - Merge worktree branch: `git merge <branch>`
   - Handle merge conflicts if any
   - Clean up worktree: `git worktree remove <path>`
   - Inform user changes are ready to push

**Verification:** Final review and merge steps documented, conflict handling included

---

### Step 11: Add Edge Case Handling

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for edge cases:
   - No workflow identified: prompt user to specify
   - Worktree name collision: prompt for alternative name
   - Merge conflicts: present to user for resolution
   - Phase 1 declined: clean up partial changes
   - Phase 2 declined: merge Phase 1 only
   - Session interrupted: document worktree persistence and resume

**Verification:** All edge cases from spec addressed

---

### Step 12: Add Error Handling

**Files to modify:**
```
workflows/improve/SKILL.md
```

**Actions:**
1. Add section for error handling:
   - Git command failures
   - Fork command failures
   - Config file parse errors
   - Permission errors
   - Network errors (if applicable)

**Verification:** Error scenarios documented, recovery steps included

---

## Implementation Order

Implement in this order for incremental progress:

1. **Steps 1-2**: Directory structure and config file
2. **Steps 3-5**: Analysis and first approval gate
3. **Steps 6-7**: Fork, worktree, and Phase 1 implementation
4. **Steps 8-9**: Phase 2 quality review
5. **Steps 10-12**: Final review, merge, edge cases, errors

---

## Verification Strategy

After each step:
- Review SKILL.md for clarity
- Check that instructions are actionable
- Verify edge cases are handled
- Ensure approval gates are present

After all steps:
- Test with a real workflow session
- Verify worktree isolation works
- Verify merge back to main works
- Run code-simplicity-reviewer on final SKILL.md
- Run writing-skills review on final SKILL.md

---

## Dependencies

- `jq` for JSON parsing (install if not present)
- Git worktree support (built into git 2.5+)
- Pi with `--fork` support

---

## Success Criteria

1. User can invoke `/workflows:improve` to start improvement workflow
2. Analysis identifies actionable improvements from session
3. Approval gates work at each phase
4. Worktree isolation prevents interference with active sessions
5. Quality reviews (simplicity + writing-skills) are integrated
6. Final merge back to main is clean and reversible
7. User is informed when changes are ready to push
