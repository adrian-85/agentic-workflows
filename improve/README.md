# Improve

A self-improvement workflow that makes *other* workflows better by mining how a
session actually used them. Instead of guessing what's wrong, it reads the
session transcript, finds concrete signs of friction — clarification questions,
roundabout tool patterns, deviations from or gaps in the skill file itself —
turns them into prioritized, evidence-backed suggestions, and implements the
approved ones in an isolated branch before merging back.

All changes happen in a git **worktree**: nothing touches the main working tree
until a four-stage approval gate says otherwise, so the whole process is safe to
run on production workflows.

The full process — the four hard stops, the two-model split, every checkpoint —
is in [`SKILL.md`](SKILL.md). This README is the quick orientation.

## What it does

1. **Analyzes** the target session for improvement indicators
   (clarifications, repetition, workarounds, missing guidance).
2. **Implements** approved improvements in an isolated git worktree.
3. **Reviews** the changes (code-simplicity + writing-skills) and applies
   the approved quality pass.
4. **Merges** the approved, reviewed result back to `main`.

Because the workflow is invoked from the very sessions it learns from, it can
improve *itself* — running it after using the `improve` workflow applies the
same analysis to `improve` itself.

## The four hard stops

The chat is the approval mechanism. At each boundary the workflow stops and
waits for the user; nothing proceeds without an explicit go-ahead. `checkpoint.sh`
makes these stops *enforceable*.

| # | After | Waiting for |
|---|-------|-------------|
| 1 | Analysis findings | Approval / decline / modifications |
| 2 | Phase 1 implementation | Model switch to `reviewModel` + confirmation |
| 3 | Quality review findings | Approval / decline / modifications |
| 4 | Final review (diff + summary) | Approval to merge |

## Two models

The workflow splits across **two models**, switched manually by the user between
phases (the workflow refuses to switch models itself):

- **`analysisModel`** — Phase 1: session analysis + improvement implementation.
- **`reviewModel`** — Phase 2: quality review + quality-change implementation.

At invocation `$PI_MODEL` should match `analysisModel`; hard stop #2 is the
hand-off to `reviewModel`.

## Physical model

All real work happens in a git worktree; `main` is untouched until final merge.

- `setup-worktree.sh <workflow-name>` creates
  `<base>/<prefix>/<workflow-name>-<timestamp>` on branch
  `improve/<workflow-name>-<timestamp>`.
- `merge-worktree.sh <worktree-path>` merges that branch to `main` and cleans up
  the worktree and branch.
- A session interrupted at any point leaves the worktree on disk; re-invoke the
  workflow pointing at it (or merge and clean up manually).

## Directory layout

| Path | Purpose |
|---|---|
| `SKILL.md` | The complete workflow manual — phases, all four hard stops, error handling, edge cases. |
| `config.json` | Default configuration, copied to the repo-root `.improvement-workflow.json` on first run. |
| `scripts/checkpoint.sh` | Gate enforcement. The only way past a hard stop: `gate <N>` records it, `require <N>` refuses unless passed. State in `/tmp/improve-workflow-checkpoint.json`. |
| `scripts/load-config.sh` | Sourced by the other scripts. Loads `.improvement-workflow.json` (or copies the default), validates JSON, exports `ANALYSIS_MODEL`, `REVIEW_MODEL`, `WORKTREE_BASE_PATH`, `WORKTREE_PREFIX` (expanding `~`). |
| `scripts/setup-worktree.sh` | Creates the isolated worktree + branch. Prints the worktree path. |
| `scripts/merge-worktree.sh` | Merges the worktree branch to `main` and cleans up. Runs from anywhere — resolves the main repo root from the worktree's `--git-common-dir`. |
| `scripts/git-operations.sh` | Shared git helpers — a library to **source**, not a CLI: `get_diff`, `get_diff_stat`, `commit_changes`, worktree/branch/stash utilities. |

The repo-root `.improvement-workflow.json` (created on first run) holds your
mutable config; `improve/config.json` is the checked-in default.

## Requirements

- **`jq`** — required for JSON/checkpoint parsing (checkpoint.sh has no
  fallback). `load-config.sh` falls back to `python3` if `jq` is absent.
- **Git 2.5+** — for `git worktree` support.

## Quick start

1. **Switch to the analysis model** and confirm `$PI_MODEL` matches
   `analysisModel`:
   ```bash
   echo "$PI_MODEL"
   ```
2. **Invoke** the workflow, naming the session to improve (defaults to the
   current session):
   ```
   /improve
   ```
3. **Work the gates** — approve findings, switch to `reviewModel` at hard stop
   #2, approve the quality review, then the final review. Approvals are given in
   chat; the script records them:
   ```bash
   scripts/checkpoint.sh gate 1     # record: gate passed
   scripts/checkpoint.sh require 1  # enforce: block unless passed
   scripts/checkpoint.sh status     # show all four gates
   scripts/checkpoint.sh reset      # clear state for a fresh run
   ```

If at any point a gate blocks, the previous phase simply wasn't approved yet —
pass its gate and continue.

## Tips

- Run it right after completing a task, while the friction is fresh in the
  transcript.
- The more a workflow is used, the more improvement signals its sessions
  generate.
- Every change stays isolated until the final approval, so it's safe to
  experiment — a declined run touches nothing.
- To evolve `improve` itself, invoke it after a session that used `improve`.