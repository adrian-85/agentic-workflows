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

## User Interface

### Invocation

User invokes explicitly via:
```
/workflows:improve
```

The workflow reads the current session transcript to identify which workflow was primarily used and targets that for improvement.

---

## Workflow Phases

### Phase 1: Analysis & Initial Implementation

**Model**: Configurable via `.improvement-workflow.json` (`analysisModel`)

**Steps**:

1. **Session Transcript Analysis**
   - Analysis is **model-driven**: the configured analysis model reads the
     raw session JSONL transcript directly (no regex/heuristic pre-filtering,
     which discards context and nuance)
   - A thin `find-session.sh` helper only locates the session file
   - Identify:
     - Clarification questions agent asked (indicates unclear workflow)
     - Tool/command patterns (repetitive actions, streamlining opportunities)
     - Skill file deviations or workarounds (skill needs improvement)
   - Generate prioritized improvement suggestions with session evidence

2. **Present Findings to User**
   - Format suggestions clearly with rationale
   - Include specific examples from session
   - Present at approval gate → **STOP** if declined

3. **Implementation Setup** (if approved)
   - Auto-fork session: `pi --fork <current-session-id>`
   - Create worktree: `git worktree add ~/workspace/agentic-workflows-improve/<workflow-name>-<timestamp> -b improve/<workflow-name>-<timestamp>`
   - Change directory to worktree

4. **Implement Improvements**
   - Apply approved changes to workflow files
   - Follow existing patterns in the workflow
   - Commit changes with descriptive messages

---

### Phase 2: Quality Review & Implementation

**Model**: Configurable via `.improvement-workflow.json` (`reviewModel`)

**Steps**:

1. **Code Simplicity Review**
   - Invoke code-simplicity-reviewer skill
   - Analyze Phase 1 changes for:
     - Unnecessary complexity
     - YAGNI violations
     - Opportunities for simplification
   - Generate prioritized simplification suggestions

2. **Writing Skills Review**
   - Invoke writing-skills skill
   - Analyze Phase 1 changes for:
     - Skill structure (frontmatter, sections, clarity)
     - Testability (can this skill be pressure-tested?)
     - Completeness (missing edge cases?)
   - Generate improvement suggestions

3. **Present Findings to User**
   - Combine simplicity and writing-skills suggestions
   - Present at approval gate → **STOP** if declined

4. **Implement Quality Improvements** (if approved)
   - Apply approved quality improvements
   - Commit changes with descriptive messages

---

### Phase 3: Final Review & Merge

**Steps**:

1. **Present Final Changes**
   - Show diff of all changes made
   - Summarize what was improved
   - Present at approval gate → **STOP** if declined

2. **Merge to Main** (if approved)
   - Merge worktree branch to main
   - Clean up worktree: `git worktree remove <path>`
   - Inform user changes are ready to push

---

## Configuration

### `.improvement-workflow.json`

Location: Repository root (`~/workspace/agentic-workflows/`)

```json
{
  "analysisModel": "openrouter/anthropic/claude-sonnet-4",
  "reviewModel": "openrouter/anthropic/claude-opus-4",
  "worktreeBasePath": "~/workspace",
  "worktreePrefix": "agentic-workflows-improve"
}
```

**Fields**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `analysisModel` | string | `deepseek/deepseek-v4-flash-0731` | Model for Phase 1 analysis and implementation |
| `reviewModel` | string | `deepseek/deepseek-v4-flash-0731` | Model for Phase 2 quality review and implementation |
| `worktreeBasePath` | string | `~/workspace` | Base directory for worktree creation |
| `worktreePrefix` | string | `agentic-workflows-improve` | Prefix for worktree directory names |

---

## Isolation Model

### File System Isolation

- **Original directory**: `~/workspace/agentic-workflows/` — untouched until merge
- **Worktree directory**: `~/workspace/agentic-workflows-improve/<name>/` — all modifications happen here
- **Symlink**: `~/.pi/agent/skills/` → `~/workspace/agentic-workflows/` — reads from original

### Session Isolation

- **Original session**: Continues unaffected after forking
- **Forked session**: Runs in worktree, has full context from original
- **New sessions**: User can start unrelated Pi sessions in other tabs without interference

### Git Isolation

- Worktree uses separate working directory on same repo
- Branch created for improvements
- Changes only affect main branch after explicit merge

---

## Approval Gates

| Gate | Location | Decline Action |
|------|----------|----------------|
| After Phase 1 analysis | End of analysis step | Stop workflow |
| After Phase 2 review | End of quality review step | Stop workflow |
| After final review | Before merge | Stop workflow |

Each gate:
- Presents findings clearly
- Allows user to request modifications
- Resumes after user approval

---

## File Structure

```
~/.pi/agent/skills/                          # Symlink to agentic-workflows
~/workspace/agentic-workflows/
├── .improvement-workflow.json               # Configuration
├── docs/superpowers/specs/
│   └── 2025-09-02-workflow-improvement-design.md  # This spec
├── workflows/
│   └── improve/
│       └── SKILL.md                         # The improvement workflow
└── [other workflows...]

~/workspace/agentic-workflows-improve/       # Worktrees (created at runtime)
├── <workflow-name>-<timestamp>/
│   ├── workflows/improve/SKILL.md
│   └── [modified workflow files...]
└── ...
```

---

## Edge Cases

1. **No workflow identified in session**: Prompt user to specify which workflow to improve
2. **Worktree already exists for workflow**: Prompt user to name this improvement or abort previous
3. **Merge conflicts**: Present conflicts to user, ask how to resolve
4. **Phase 1 declined**: Clean up any partial changes, return to original session
5. **Phase 2 declined**: Keep Phase 1 improvements, merge what exists
6. **Session interrupted**: Worktree persists, user can resume later with `pi --session <worktree-session>`

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
3. Implement session transcript analysis logic
4. Implement worktree creation/management
5. Implement fork integration
6. Implement Phase 1 (analysis + implementation)
7. Implement Phase 2 (quality review integration)
8. Implement Phase 3 (final review + merge)
9. Add error handling and edge cases
10. Test with real workflows
