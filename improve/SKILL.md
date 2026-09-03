---
name: improve
description: "Use when you want to improve an existing workflow based on actual usage. Analyzes the current session for improvement indicators, implements changes in an isolated worktree, runs quality reviews, and merges approved improvements."
---

# Workflow Improvement

## Overview

This workflow improves other workflows by analyzing actual usage patterns. It:

1. **Analyzes the current session** for improvement indicators
2. **Implements improvements** in an isolated git worktree
3. **Runs quality reviews** (code simplicity + writing-skills)
4. **Merges approved changes** back to main

The workflow can improve itself when invoked after using the `improve` workflow.

## Invocation

```
/workflows:improve
```

Or manually: "Improve the workflow I just used"

## Prerequisites

- `jq` installed for JSON parsing
- Git 2.5+ for worktree support
- Pi with `--fork` support

## Workflow Phases

### Phase 1: Analysis

1. **Load configuration:**
   ```bash
   source scripts/load-config.sh
   ```

2. **Read the target session transcript:**
   - The invocation names the session to improve — by default, the
     session the workflow is invoked from, available as `$PI_SESSION_FILE`
   - Read it directly; for large files, read in chunks (offset/limit)
     until the whole transcript is covered.
   - Analyze the transcript for improvement indicators in the workflow
     that was used:
     - Clarification questions the agent asked (unclear workflow)
     - Repetitive or roundabout tool/command patterns (streamlining)
     - Deviations from or workarounds around the skill file
     - Ambiguous or missing guidance in the skill document itself
   - Use the configured analysis model (`$ANALYSIS_MODEL`) for this phase.

4. **Generate prioritized improvement suggestions** from what you observed.
   Quote specific moments from the session as evidence for each suggestion.

5. **Present findings to user:**
   - Format suggestions clearly with rationale
   - Include specific session examples
   - Write suggestions to `.pending-analysis.md`

6. **Get approval:**
   ```bash
   scripts/approval-gate.sh analysis .pending-analysis.md
   ```
   - If declined (exit 1): Stop workflow
   - If modifications requested (exit 2): Iterate until satisfied
   - If approved (exit 0): Proceed to Phase 2

### Phase 2: Implementation Setup

1. **Get workflow name:**
   - From analysis results
   - If unclear, ask user: "Which workflow should I improve?"

2. **Create worktree:**
   ```bash
   scripts/setup-worktree.sh <workflow-name>
   ```

3. **Fork session to worktree:**
   - Get current session ID
   - Execute: `pi --fork <session-id>`
   - Change directory to worktree

4. **Implement approved improvements:**
   - Apply each approved change
   - Follow existing patterns in the workflow
   - Commit after each logical change

### Phase 3: Quality Review

1. **Run code simplicity review:**
   - Invoke code-simplicity-reviewer skill
   - Analyze Phase 2 changes
   - Generate simplification suggestions

2. **Run writing-skills review:**
   - Invoke writing-skills skill
   - Analyze Phase 2 changes
   - Generate improvement suggestions

3. **Combine findings:**
   - Merge suggestions from both reviews
   - Prioritize by impact
   - Write to `.pending-quality.md`

4. **Get approval:**
   ```bash
   scripts/approval-gate.sh quality-review .pending-quality.md
   ```
   - If declined (exit 1): Proceed to Phase 4 with current changes
   - If modifications requested (exit 2): Iterate until satisfied
   - If approved (exit 0): Implement quality improvements

5. **Implement quality improvements:**
   - Apply approved changes
   - Commit with descriptive messages

### Phase 4: Final Review & Merge

1. **Generate final diff:**
   ```bash
   scripts/git-operations.sh get_diff main
   ```

2. **Summarize changes:**
   - What was improved
   - Quality improvements applied
   - Files changed

3. **Present to user:**
   - Write summary to `.pending-final.md`

4. **Get approval:**
   ```bash
   scripts/approval-gate.sh final .pending-final.md
   ```
   - If declined (exit 1): Stop, worktree persists for later
   - If modifications requested (exit 2): Iterate until satisfied
   - If approved (exit 0): Proceed to merge

5. **Merge to main:**
   ```bash
   scripts/merge-worktree.sh <worktree-path>
   ```

6. **Inform user:**
   - Changes merged to main
   - Ready to push to remote

## Error Handling

### No workflow identified
- Ask user to specify which workflow to improve
- If user cannot identify, suggest reviewing session manually

### Worktree name collision
- Prompt user for alternative name
- Or abort and let user clean up manually

### Merge conflicts
- Present conflicts to user
- User resolves in main working directory
- Continue merge after resolution

### Phase declined
- Phase 1 declined: Stop workflow, clean up
- Phase 2 declined: Stop workflow, worktree persists
- Phase 3 declined: Keep Phase 2 changes, merge what exists
- Phase 4 declined: Stop workflow, worktree persists

### Session interrupted
- Worktree persists on disk
- User can resume later with `pi --session <worktree-session>`
- Or manually merge and clean up

## Edge Cases

### Self-improvement
When invoked after using the `improve` workflow:
- Same analysis logic applies
- No special case needed
- Workflow can evolve based on its own usage

### Multiple workflows in session
- Identify primary workflow by frequency of use
- If unclear, ask user to choose

### No improvement opportunities found
- Inform user workflow appears well-optimized
- Suggest running again after more usage

## Configuration

Configuration is stored in `.improvement-workflow.json` in the repo root.

Default values are in `improve/config.json`.

```json
{
  "analysisModel": "z-ai/glm-5.3-flash",
  "reviewModel": "xiaomi/mimo-v2.5",
  "worktreeBasePath": "~/workspace",
  "worktreePrefix": "agentic-workflows-improve"
}
```

## File Structure

```
~/workspace/agentic-workflows/
├── improve/
│   ├── SKILL.md                  # This file
│   ├── config.json               # Default configuration
│   └── scripts/
│       ├── load-config.sh        # Config loading
│       ├── setup-worktree.sh     # Worktree creation
│       ├── approval-gate.sh      # Approval handling
│       ├── merge-worktree.sh     # Merge and cleanup
│       └── git-operations.sh     # Git helpers
└── .improvement-workflow.json    # User configuration (created on first run)
```

## Scripts Reference

### load-config.sh
Loads configuration from `.improvement-workflow.json` or defaults.

```bash
source scripts/load-config.sh
# Exports: ANALYSIS_MODEL, REVIEW_MODEL, WORKTREE_BASE_PATH, WORKTREE_PREFIX
```

### Session targeting

There is no session-lookup machinery. The invocation prompt names the
session to improve ("improve the workflow used in this session"), and the
agent is already inside it — the current session file is available as
`$PI_SESSION_FILE`. If the user names a different session, use that path
instead. Analysis is model-driven: judgment is left to the model, not
to scripts.

### Scripts summary
- `load-config.sh` — load `.improvement-workflow.json` (or defaults)
- `approval-gate.sh` — coded approval gate (exit 0/1/2)
- `setup-worktree.sh` — create isolated worktree + branch
- `merge-worktree.sh` — merge branch to main, remove worktree
- `git-operations.sh` — shared git helpers (source to use)

### setup-worktree.sh
Creates git worktree and branch for isolated work.

```bash
scripts/setup-worktree.sh <workflow-name> [base-path]
# Outputs: Worktree path
```

### approval-gate.sh
Handles approval prompts with user input.

```bash
scripts/approval-gate.sh <gate-name> <proposal-file>
# Exit codes: 0=approved, 1=declined, 2=modifications
```

### merge-worktree.sh
Merges worktree branch to main and cleans up.

```bash
scripts/merge-worktree.sh <worktree-path>
```

### git-operations.sh
Shared git helper functions. Source to use.

```bash
source scripts/git-operations.sh
```

## Tips

- Run this workflow after completing a task to capture fresh insights
- The more you use a workflow, the more improvement signals it generates
- Quality reviews help ensure changes follow best practices
- All changes are isolated until final approval, so safe to experiment
