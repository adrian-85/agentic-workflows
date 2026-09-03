# Workflow Improvement Workflow - Design Spec

**Date**: 2025-09-02
**Status**: Draft
**Author**: Pi Agent (brainstorming session)

---

## Overview

A meta-workflow that improves existing agentic workflows through session analysis, isolated implementation via git worktrees, and quality review gates. Designed for on-demand invocation with user approval at each critical step.

## Goals

- Improve existing workflows based on actual usage patterns
- Isolate changes in git worktrees to avoid disrupting active sessions
- Ensure quality through code simplicity and writing-skills reviews
- Provide clear approval gates for user control

## Self-Improvement

The workflow can improve itself. When invoked after using the `improve` workflow, it analyzes its own session for improvements. No special case needed — the same analysis logic applies.

---

## Non-Goals

- Automatic/background improvement (on-demand only)
- Cross-workflow analysis (one workflow at a time)
- Real-time monitoring of active sessions

---

## Models

Two models, configured in `.improvement-workflow.json`:

- **`analysisModel`** — Phase 1: session analysis and improvement implementation
- **`reviewModel`** — Phase 2: quality review and quality-change implementation

The **user switches models manually** — the agent cannot switch its own
model. The skill verifies the active model via `$PI_MODEL` at invocation
and at the Phase 1 → Phase 2 boundary, stopping until the user confirms
the correct model is active. (The original headless-subprocess design was
considered but rejected in favor of manual switching.)

## User Interface

### Invocation

The user switches to the analysis model, then invokes:
```
/improve
```

The invocation names the session to improve — by default the session the
workflow is invoked from (`$PI_SESSION_FILE`). No session-lookup machinery
exists.

---

## Configuration

### `.improvement-workflow.json`

Location: Repository root (`~/workspace/agentic-workflows/`)

```json
{
  "analysisModel": "z-ai/glm-5.3-flash",
  "reviewModel": "xiaomi/mimo-v2.5",
  "worktreeBasePath": "~/workspace",
  "worktreePrefix": "agentic-workflows-improve"
}
```

**Fields**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `analysisModel` | string | `z-ai/glm-5.3-flash` | Model for Phase 1 analysis and implementation |
| `reviewModel` | string | `xiaomi/mimo-v2.5` | Model for Phase 2 quality review and implementation |
| `worktreeBasePath` | string | `~/workspace` | Base directory for worktree creation |
| `worktreePrefix` | string | `agentic-workflows-improve` | Prefix for worktree directory names |

---

## Isolation Model

### File System Isolation

- **Original directory**: `~/workspace/agentic-workflows/` — untouched until merge
- **Worktree directory**: `~/workspace/agentic-workflows-improve/<name>/` — all modifications happen here
- **Symlink**: `~/.pi/agent/skills/` → `~/workspace/agentic-workflows/` — reads from original

### Session Isolation

- **Single session**: the workflow runs in the session it improves; no
  forking (the original auto-fork design was removed — `pi --fork` spawns
  a new interactive process, which an in-session agent cannot hand off to
  mid-turn, and the live run proved same-session + worktree isolation
  works)
- **Other sessions**: user can run unrelated Pi sessions in parallel
  without interference

### Git Isolation

- Worktree uses separate working directory on same repo
- Branch created for improvements
- Changes only affect main branch after explicit merge

---

## Workflow Phases

### Phase 1: Analysis & Implementation  (model: `analysisModel`)

1. **Verify model** (`$PI_MODEL` vs `analysisModel`): stop until correct
2. **Session transcript analysis** — model-driven; raw transcript read
   directly (`$PI_SESSION_FILE`); identify clarification questions,
   tool/command patterns, skill deviations; generate prioritized
   suggestions with session evidence
3. **Hard stop #1** — present findings; stop until user approves,
   declines, or requests modifications
4. **Implement** — create worktree, apply approved changes, commit
   logically, run the workflow's own verification
5. **Hard stop #2** — report completion; user switches to `reviewModel`;
   stop until they confirm

### Phase 2: Quality Review & Implementation  (model: `reviewModel`)

1. **Verify model** (`$PI_MODEL` vs `reviewModel`): stop until correct
2. **Code simplicity review** + **writing-skills review** of Phase 1
   changes — suggestions only, nothing applied
3. **Hard stop #3** — present combined findings; stop until user approves
   or declines (decline keeps Phase 1 changes, proceeds to final review)
4. **Implement approved quality improvements** — apply, commit

### Phase 3: Final Review & Merge

1. **Hard stop #4** — present full diff + summary; stop until approved
2. **Merge to main**, clean up worktree, inform user changes are ready
   to push

---

## Approval Gates

Four **chat-level hard stops** — the conversation is the approval
mechanism; there is no approval script (an interactive `read`-based script
cannot work: pi's bash tool is non-interactive, so stdin hits EOF).

At each stop the agent presents findings and **ends its turn**; workflow
action resumes only after the user replies.

| # | After | Waiting for |
|---|-------|-------------|
| 1 | Analysis findings | Approve / decline / modify |
| 2 | Phase 1 implementation complete | Model switch to `reviewModel` + confirm |
| 3 | Quality review findings | Approve / decline / modify |
| 4 | Final review | Approve merge / decline |

Findings are presented **directly in chat** — no proposal files; the
session transcript is the record.

**Checkpoint enforcement:** `checkpoint.sh` records when each gate is
passed and blocks the next phase until its prerequisite gate is recorded.
This makes the hard stops verifiable, not just advisory. State file:
`/tmp/improve-workflow-checkpoint.json`.

---

## File Structure

```
~/.pi/agent/skills/                          # Symlink to agentic-workflows
~/workspace/agentic-workflows/
├── .improvement-workflow.json               # Configuration
├── docs/superpowers/specs/
│   └── 2025-09-02-workflow-improvement-design.md  # This spec
├── improve/
│   ├── SKILL.md                             # The improvement workflow
│   ├── config.json                          # Default configuration
│   └── scripts/                             # load-config, setup-worktree,
│       ...                                  # merge-worktree, git-operations
└── [other workflows...]

~/workspace/agentic-workflows-improve/       # Worktrees (created at runtime)
├── <workflow-name>-<timestamp>/
│   └── [modified workflow files...]
└── ...
```

---

## Edge Cases

1. **No workflow identified in session**: Prompt user to specify which workflow to improve
2. **Worktree already exists for workflow**: Prompt user to name this improvement or abort previous
3. **Merge conflicts**: Present conflicts to user, ask how to resolve
4. **Hard stop #1 declined**: Clean up any partial changes, return to original session
5. **Hard stop #3 declined**: Keep Phase 1 improvements, proceed to final review
6. **Session interrupted**: Worktree persists; re-invoke the workflow and point at the existing worktree, or manually merge and clean up

---

## Testing Strategy

1. **Unit tests**: Analysis logic, config parsing
2. **Integration tests**: Worktree creation/cleanup, git operations
3. **End-to-end tests**: Full workflow with mock session transcript
4. **Manual verification**: Run against real session, verify improvements are sensible

---

## Implementation Plan

1. Create workflow directory structure
2. Implement `.improvement-workflow.json` config loading
3. Session analysis: model-driven (raw transcript, no scripted extraction)
4. Implement worktree creation/management
5. Model handling: user switches manually; skill verifies `$PI_MODEL` and stops at phase boundary (no fork — removed after live run)
6. Implement Phase 1 (analysis + implementation)
7. Implement Phase 2 (quality review integration)
8. Implement Phase 3 (final review + merge)
9. Add error handling and edge cases
10. Test with real workflows
