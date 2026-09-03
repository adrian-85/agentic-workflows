---
name: improve
description: "Use when you want to improve an existing workflow based on actual usage. Analyzes the current session for improvement indicators, implements changes in an isolated worktree, runs quality reviews, and merges approved improvements."
---

# Workflow Improvement

## Overview

This workflow improves other workflows by analyzing actual usage patterns. It:

1. **Analyzes the target session** for improvement indicators
2. **Implements improvements** in an isolated git worktree
3. **Runs quality reviews** (code simplicity + writing-skills)
4. **Merges approved changes** back to main

The workflow can improve itself when invoked after using the `improve` workflow.

## Models

This workflow uses two models, configured in `.improvement-workflow.json`:

- **`analysisModel`** — Phase 1: session analysis and improvement implementation
- **`reviewModel`** — Phase 2: quality review and quality-change implementation

The **user switches models manually**. Do not attempt to switch models
yourself — you cannot. Instead, verify the active model with `$PI_MODEL`
(which holds the full model ID, matching the config format) and stop at
the phase boundary so the user can switch:

- At invocation, `$PI_MODEL` should match `analysisModel`. If it does not,
  tell the user which model to switch to and **stop until they confirm**.
- After Phase 1 implementation, **stop** and ask the user to switch to
  `reviewModel` before starting Phase 2.

## Invocation

The user switches to the analysis model first, then invokes:

```
/improve  (or: "improve the workflow used in this session")
```

The invocation names the session to improve — by default the session the
workflow is invoked from (`$PI_SESSION_FILE`).

## Hard Stops

There are four hard stops. At each one:

> **STOP. End your turn after presenting the required information. Do not
> implement anything, create worktrees, run reviews, or take any further
> workflow action until the user replies.**

| # | After | Waiting for |
|---|-------|-------------|
| 1 | Analysis findings | Approval / decline / modifications |
| 2 | Phase 1 implementation complete | Model switch to `reviewModel` + confirmation |
| 3 | Quality review findings | Approval / decline / modifications |
| 4 | Final review (diff + summary) | Approval to merge |

The chat is the approval mechanism — there is no approval script.

## Prerequisites

- `jq` installed for JSON parsing (python3 fallback exists in load-config.sh)
- Git 2.5+ for worktree support

## Workflow Phases

### Phase 1: Analysis & Implementation  (model: `analysisModel`)

1. **Load configuration:**
   ```bash
   source scripts/load-config.sh
   ```

2. **Verify the model:** Check `$PI_MODEL` against `analysisModel`.
   If it does not match, tell the user which model is active and which
   is configured, and **stop until they confirm** how to proceed.

3. **Read the target session transcript:**
   - Read `$PI_SESSION_FILE` (or the session path named in the invocation)
     directly; for large files, read in chunks (offset/limit) until the
     whole transcript is covered.
   - Analyze the transcript for improvement indicators in the workflow
     that was used:
     - Clarification questions the agent asked (unclear workflow)
     - Repetitive or roundabout tool/command patterns (streamlining)
     - Deviations from or workarounds around the skill file
     - Ambiguous or missing guidance in the skill document itself

4. **Generate prioritized improvement suggestions** from what you observed.
   Quote specific moments from the session as evidence for each suggestion.

5. **Present findings and stop (hard stop #1):**
   - Format suggestions clearly with rationale and session evidence
   - Save the proposal to a temp directory for reference:
     ```bash
     mktemp -d   # write .pending-analysis.md there — never into the live repo
     ```
   - **STOP.** If the user declines, the workflow ends. If they request
     modifications, revise and present again. If they approve, continue.

6. **Implement approved improvements:**
   - Create the worktree:
     ```bash
     scripts/setup-worktree.sh <workflow-name>
     ```
   - Work entirely inside the worktree (use the returned path; do not
     modify files in the main working tree)
   - Apply each approved change; follow existing patterns in the workflow
   - Commit after each logical change with descriptive messages
   - Run the workflow's own tests/verification if it has any

7. **Report completion and stop (hard stop #2 — model switch):**
   - Summarize what was implemented (commits, files changed, test results)
   - Tell the user: "Phase 2 requires the review model — please switch
     to `$REVIEW_MODEL`"
   - **STOP.** Do not begin Phase 2 until the user confirms they have
     switched.

### Phase 2: Quality Review & Implementation  (model: `reviewModel`)

1. **Verify the model:** Check `$PI_MODEL` against `reviewModel`.
   If it does not match, remind the user and **stop until they confirm**.

2. **Run code simplicity review:**
   - Invoke the code-simplicity-reviewer skill on the Phase 1 changes
   - Generate simplification suggestions — **do not apply them yet**

3. **Run writing-skills review:**
   - Invoke the writing-skills skill on the Phase 1 changes
   - Generate skill-structure improvements — **do not apply them yet**

4. **Combine findings and stop (hard stop #3):**
   - Merge suggestions from both reviews, prioritized by impact
   - Save to the same temp directory as `.pending-quality.md`
   - **STOP.** If the user declines, keep Phase 1 changes and proceed to
     Phase 3 (final review). If they request modifications, revise and
     present again. If they approve, continue.

5. **Implement approved quality improvements:**
   - Apply each approved change in the worktree
   - Commit with descriptive messages

### Phase 3: Final Review & Merge

1. **Generate the final diff:**
   ```bash
   scripts/git-operations.sh get_diff main
   ```

2. **Present everything and stop (hard stop #4):**
   - Full diff summary: what was improved, quality changes applied,
     files changed, commits
   - **STOP.** If the user declines, stop — the worktree persists for later.
     If they approve, continue to merge.

3. **Merge to main:**
   ```bash
   scripts/merge-worktree.sh <worktree-path>
   ```

4. **Inform the user:**
   - Changes merged to main
   - Ready to push to remote

## Error Handling

### No workflow identified
- Ask the user to specify which workflow to improve
- If user cannot identify, suggest reviewing the session manually

### Worktree name collision
- Prompt the user for an alternative name
- Or abort and let the user clean up manually

### Merge conflicts
- Present conflicts to the user
- User resolves them in the main working directory
- Continue merge after resolution

### Gate declined
- Hard stop #1 declined: workflow ends, nothing was modified
- Hard stop #2: user may pause indefinitely (model switch) — resume when
  they confirm
- Hard stop #3 declined: keep Phase 1 changes, proceed to final review
- Hard stop #4 declined: stop, worktree persists

### Session interrupted
- Worktree persists on disk
- User can resume later by re-invoking the workflow and pointing at the
  existing worktree, or manually merge and clean up

## Edge Cases

### Self-improvement
When invoked after using the `improve` workflow:
- Same analysis logic applies
- No special case needed
- Workflow can evolve based on its own usage

### Multiple workflows in session
- Identify primary workflow by frequency of use
- If unclear, ask the user to choose

### No improvement opportunities found
- Inform the user the workflow appears well-optimized
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

### setup-worktree.sh
Creates git worktree and branch for isolated work.

```bash
scripts/setup-worktree.sh <workflow-name> [base-path]
# Output: worktree path
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

### Approval mechanism
There is no approval script. The chat is the gate: present findings,
end your turn, and wait for the user's reply. Proposal files are written
to a temp directory (`mktemp -d`), never into the live repo.

## Tips

- Run this workflow after completing a task to capture fresh insights
- The more you use a workflow, the more improvement signals it generates
- Quality reviews help ensure changes follow best practices
- All changes are isolated until final approval, so safe to experiment
