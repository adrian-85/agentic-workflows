# Pylint-Clean Refactor — Design Spec

**Date**: 2026-09-07
**Status**: Draft
**Author**: Pi Agent (brainstorming session)

---

## Overview

Make `pylint $(git ls-files '*.py')` exit **0** on the `agentic-workflows`
repo and turn pylint into a **deterministic hard gate** in CI.

Current state (pylint 4.0.8, Python 3.13, repo deps installed — matches
CI exactly: rating 8.57/10, exit 28):

- **1193 messages, 0 errors** — all convention/warning/refactor
- ~907 in test files (~76%), 286 in source code (non-test)
- Headline buckets: `missing-function-docstring` 517, `protected-access`
  376, `line-too-long` 56, `invalid-name` 35, `import-outside-toplevel`
  29, `too-many-*` clusters ~68, `missing-class/module-docstring` 40,
  plus a small set of genuine issues (`cell-var-from-loop` ×2,
  `cyclic-import` ×2, `unspecified-encoding` ×1, `broad-exception-caught`
  ×12, `duplicate-code` ×6)
- CI workflow runs bare `pylint $(git ls-files '*.py')` with an unpinned
  pylint and no config — results float with pylint versions; the job is
  currently red by default (exit 28)

Approach: **Option A** — fix everything that is genuinely fixable, and
apply *documented* suppressions only where the code is deliberately
conventional (OOXML vocabulary, flat-namespace sharing, module drift
state, data records, test white-boxing). **No `too-many-*` threshold
changes**: large functions are extracted, large files are split (source
only).

## Goals

- `pylint $(git ls-files '*.py')` exits 0, deterministically, local == CI
- Hard gate via the **improve workflow**: `verify-worktree.sh` blocks
  any merge to `main` whose **change set** fails the pinned lint or the
  test suites
- Large **source** files split below 1000 lines (clears `C0302`)
- **Test** files stay one-file-per-source (may exceed 1000 lines) per
  maintainability ruling — mapping test → source must stay obvious
- Pylint becomes a hard CI gate on push and pull_request
- Every suppression carries a written rationale at its point of effect
- Zero behavior change; entry points and public surfaces preserved;
  docs/README/SKILL.md untouched

## Non-Goals

- No `max-*-args`/`max-*-locals`/etc. threshold changes in config
- No changes to the flat-script namespace or `python3 scripts/<x>.py`
  invocation surface
- No public API renames (deferred — see separate spec
  `2026-09-07-script-api-promotion-design.md`)
- No `DriftBook` refactor of the `docx_edit.py` module counters
  (deferred — see `2026-09-07-driftbook-refactor-design.md`)
- No packaging/`pyproject`-as-installable (the repo stays self-contained
  scripts; `pyproject.toml` is used only for pylint tool config)
- No auto-formatting pass (black/isort) — reflow by hand, in-place

## Configuration & Hard-Gate Mechanism

### Pylint version pin

pylint 4.0.8 (verified to reproduce CI output exactly). Pin:

- `.github/workflows/pylint.yml`: change `pip install pylint` →
  `pip install pylint==4.0.8`; keep `pip install -r
  p2p-qa-lab/requirements.txt` first (kills false `import-error`s)
- Document the local recipe in the repo README (or a `PYLINT.md`
  note): `pip install -r p2p-qa-lab/requirements.txt pylint==4.0.8`,
  then `pylint $(git ls-files '*.py')`

### Config file: `pyproject.toml` (new, repo root)

Pylint auto-discovers `[tool.pylint]` — single source of truth for both
local and CI.

```toml
[tool.pylint]
reports = "no"          # cleaner output; score line off
fail-under = 0.0        # any message → non-zero exit (hard gate)

[tool.pylint."messages control"]
# Repo-wide convention, one written rationale:
# The resume-tailoring scripts live in a flat namespace and deliberately
# share underscore-prefixed helpers across sibling modules (the "internal
# API" of each script). Tests further white-box the same helpers. This is
# the repo's documented convention; a future pass may promote a public
# API (see script-api-promotion spec) — until then protected access is
# expected, not accidental.
disable = [
    "protected-access",
]
```

Everything else stays at pylint defaults (line length 100,
`too-many-*` defaults, etc.). `fail-under = 0.0` makes exit code
deterministic: convention messages alone exit 16 (verified), so **any
residual message fails the gate**.

### Per-file suppression mechanism (important)

Pylint 4.0 has **no per-file-ignores option** (verified). Per-file
suppressions are therefore **file-header `# pylint: disable=…`
comments**, each accompanied by a rationale comment, placed at the top of
the affected file. Global-only items go in `pyproject.toml` (only
`protected-access` above). Everything else is fixed in code or disabled
at the specific class/line scope.

### Workflow change: hard gate via the improve workflow

The **enforcement point is the `improve` workflow, not GitHub branch
protection**: nothing lands on `main` except through its four approval
`>STOP.` gates + `merge-worktree.sh` step. The pylint gate therefore
lives **in that flow** — main only ever receives a worktree merge whose
**change set** (its diff vs `main`) passed the pinned lint scoped to
that diff, plus both test suites, locally, at the same pinned version
CI uses.

#### New: `improve/scripts/verify-worktree.sh`

Run **inside the worktree, before any merge**, scoped to the **change
set** — exactly like every other check in the improve workflow
(analysis, reviews, gates all target the improvement's diff, never the
whole repo):

1. Installs/uses the pinned toolchain (deps via
   `p2p-qa-lab/requirements.txt`, `pylint==4.0.8`)
2. **Lints only the changed Python files**: resolves the change set as
   `git diff --name-only main...HEAD -- '*.py'` and runs pylint on
   exactly those files (no `.py` changed → lint skipped). Fails
   (non-zero) on any message in a changed file. Lint debt is per-file
   and additive, so a SKILL.md-only or otherwise unrelated improvement
   must never trip on repo lint debt outside its diff. Once this
   effort lands (whole repo exits 0), this is equivalent to "fail on
   new lint debt" — every touched file is clean on `main`.
3. Runs both suites (398 unittest resume + 54 pytest p2p-qa, same
   `*_live` exclusions) — tests are a *correctness* gate and run
   repo-wide: the merged change set must keep every consumer green.
4. Prints `✓ lint + tests pass` or a blocking failure summary

The pylint-clean effort **itself** exercises the whole-repo form
`pylint $(git ls-files '*.py')` as *its own* acceptance criterion — its
change set *is* the entire repo. That acceptance lives in the plan's
tasks, not in `verify-worktree.sh`.

#### Wiring (two points)

- **`improve/SKILL.md` Phase 3 (Final Review & Merge):** run
  `verify-worktree.sh` *before* generating the final diff for hard
  stop #4. If it fails, the workflow **stops and reports what failed**
  — no diff presentation, no merge.
- **`improve/scripts/merge-worktree.sh`:** call the same verify as a
  belt-and-suspenders guard *inside* the merge step (`set -euo pipefail`
  aborts the merge on a failed verify), so a skipped SKILL.md step
  cannot merge a failing tree.

This applies **to `improve` itself** as well: when the workflow
improves its own files (including `verify-worktree.sh` and
`merge-worktree.sh`), the change-set gate runs on the self-improved
diff before merge (user-confirmed).

#### CI workflow stays as the remote signal/backstop

`.github/workflows/pylint.yml` remains but is not the enforcement gate:

- Pin `pylint==4.0.8`, keep deps install step
- It keeps catching `push` events from any path that bypasses the
  improve flow (e.g. a direct push) — a fast, cheap, remote signal that
  still fails red on any message
- Branch-protection *required-checks* are **not** needed for the gate
  (the improve merge is the gate); they may be added later as defense
  in depth if desired

### Message disposition — non-test (286 messages)

| Code | Count | Disposition | Mechanism |
|------|-------|-------------|-----------|
| C0116 missing-function-docstring | 65 | **Fix** | add source docstrings |
| C0115 missing-class-docstring | 5 | **Fix** | add source docstrings |
| C0114 missing-module-docstring | 2 | **Fix** | add module docstrings |
| C0301 line-too-long | 42 | **Fix** | reflow; long string literals get inline `# noqa: E501` |
| C0302 too-many-lines | 3 | **Fix** | source file splits (below) |
| R0914/0912/0915/0913/0917/0911/R1702 | 68 | **Fix** | function extraction (p2p-qa hotspots, big entry fns) |
| C0415 import-outside-toplevel | 15 | **Fix** | hoist to top-level (deps always installed; the `validate_resume`-in-`docx_edit` sites become top-level once the cycle is broken) |
| R0801 duplicate-code | 6 | **Fix** | dedupe via `script_args.py` + `test_helpers.py` |
| R0401 cyclic-import | 2 | **Fix** | break cycle via extraction (below) |
| W0621 redefined-outer-name | 4 | **Fix** | rename shadowing locals (client `field`, mock_api `app`, docx_edit `prefixes`) |
| W0640 cell-var-from-loop | 2 | **Fix** | default-arg binding (latent closure bug) |
| R1732 consider-using-with | 2 | **Fix** | use `with` |
| W1514 unspecified-encoding | 1 | **Fix** | `encoding="utf-8"` |
| C0103 invalid-name (VERDICT_PROMPT) | 1 | **Fix** | rename to `verdict_prompt` |
| W0603 global-statement (ai-judge `_OPENAI_CLIENT`) | 1 | **Fix** | `@functools.cache` on a `_build_client()` factory |
| W0718 broad-exception-caught | 6 | **Fix** | narrow (llm key-load → `OSError/KeyError`; httpx transport → `httpx.HTTPError`; LLM call sites → openai/AgentError types) |
| C0103 invalid-name (OOXML) | 13 | **Suppress** | file-header disable on `docx_edit.py` (names mirror `w:rPr/pPr/numId` schema tags verbatim for grepping) — applies tree-wide to same-domain code |
| C0103 invalid-name (numId ×3) | 3 | **Suppress** | inline `# pylint: disable=invalid-name` at the 3 sites in `measure_resume.py`/`validate_resume.py` (OOXML vocabulary) |
| W0603 global-statement (docx_edit) | 7 | **Suppress** | file-header disable with rationale (deliberate module drift counters read by tests; DriftBook refactor deferred) |
| C0413 wrong-import-position | 6 | **Suppress** | file-header disable on the 5 flat-namespace scripts (the `sys.path.insert(0, …)` bootstrap precedes sibling imports by necessity); `ai-judge/judge.py` hoists the insert to top + inline disable on its import line |
| W0212 protected-access | 26 | **Suppress** | global disable in `pyproject.toml` (convention rationale above; API promotion deferred) |
| R0902 too-many-instance-attributes | 1 | **Suppress** | class-line disable on `StepRecord` (data record mirroring wire schema) |
| R0903 too-few-public-methods | 1 | **Suppress** | class-line disable on mock-api `Store` |
| W0718 broad-exception-caught | 5 | **Suppress** | inline `# pylint: disable=broad-exception-caught` at true process boundaries with comment (user-approved): cli server-wait retry, adversarial payload truncation, adversarial probe isolation, validate master-parse boundary |

### Message disposition — test files (907 messages)

Each `test_*.py` (and `tests/conftest.py`) gets a **file-header
`# pylint: disable=` block with a rationale comment** covering:

- `missing-module-docstring, missing-class-docstring,
  missing-function-docstring` — unittest/pytest method names are
  self-documenting
- `protected-access` — test files white-box the `_` helpers they test
  (the tested behavior *is* the underscore contract)
- `too-many-lines` — test files may exceed 1000 lines when they map
  1:1 to a source file (maintainability ruling)
- `invalid-name` — OOXML fixture names (`pPr`, `numId`, …) mirror the
  schema

Beyond suppression, the test consolidation below removes the actual
repetition where it exists (data-driven refactor, shared fixtures).

## Source Splits (kills C0302 — every source file lands < 1000 lines)

### `docx_edit.py` (1278 lines) → + `docx_edit_cli.py`

Move the CLI surface out: `cli()`, `paragraph_map`, `prefixes`,
`shortest_unique_prefix`, `style_and_numid`, `_headline_index`,
`_prefix_arg`, `_block`. `docx_edit.py` keeps the editor core
(`load`/`save`/mutators/`find_p`/`_deliverable_gate`/counters).
`docx_edit_cli.py` imports from `docx_edit.py` and owns
`if __name__ == "__main__"`; module docstring cross-references the
CLI home. Tests for CLI behavior move with the CLI (grouped split per
test-file section below).

### `measure_resume.py` (2388 lines) → thin entry + re-export shim

`measure_resume.py` becomes: constants re-export + `main()` + the
CLI-only helpers (`_target_from_args`, `_default_target_note`,
`_resolved_jd_terms`). Logic splits by seam:

| New module | Contents |
|------------|----------|
| `measure_resume_format.py` | format constants, pages/roles/layout/budget (`_render_pdf`, `_pdf_pages_text`, `_roles`, `_match_roles_to_pages`, `_wrapped_tools`, `_visible_span`, `_layout_hints`, `_reclaim_batch`, `_measured_lines_per_bullet`, `_page_fill`, …) |
| `measure_resume_jd.py` | JD vocabulary/requirements/inference/title (`_jd_terms`, `_jd_requirement_coverage`, `_jd_report`, `_inference_map`, `_title_rank`, `_jd_title`, `title_alignment_notes`, …) |
| `measure_resume_drops.py` | drop planning (`_suggest_drops`, `_drop_suggestions`, `_top_role_batch`, `_jd_fit_audit`, `_drop_sections`, `_apply_simulate`, `_drop_plan_lines`, …) |

**Contract:** `measure_resume.py` re-exports the **full `mr.*` surface**
explicitly (`from measure_resume_format import *, _roles, …` style —
public + the underscore helpers consumers use: `_roles`, `_jd_terms`,
`_render_pdf`, `_pdf_pages_text`, `_page_lines`, `_match_roles_to_pages`,
`_measured_lines_per_bullet`, `_reclaim_batch`, `_drop_suggestions`,
`_top_role_batch`, `_jd_fit_audit`, `_visible_span`, `_inference_map`,
`_jd_title`, constants, `main`). Consumers (`validate_resume.py`,
`squeeze_resume.py`, `ats_audit.py`, all `test_*`) keep working
unmodified. Same flat directory; `sys.path` bootstrap unchanged.

### `validate_resume.py` (1094 lines) → thin entry + re-export shim

| New module | Contents |
|------------|----------|
| `validate_resume_checks.py` | region/punctuation/structural/text-integrity/readability/`_word_count`/constants |
| `validate_resume_master.py` | master loading, role-integrity, education gate, `_extract_flag*`/`_parse_flag` |

`validate_resume.py` keeps `validate_tree()`, `main()`, constants, and
re-exports the whole `vr.*` surface (including `_visible_span`,
`_jd_fit_audit`, `_roles`, `_jd_terms`, `_company_key`, `_norm`,
`_wrapped_tools`, `_extract_flag`, `_extract_flag_all`, `_parse_flag`,
…). Consumers unchanged.

### `script_args.py` (new)

The duplicated `--protect`/`--jd` argv loops (R0801 duplicate-code
cluster across `measure_resume.py`, `squeeze_resume.py`,
`validate_resume.py`) become one shared helper used by all three.
Placing the argv/flag parsing *outside* `validate_resume.py` is also
what lets `docx_edit.py`'s `validate_resume` import be hoisted to
top-level without the `docx_edit → validate_resume → measure_resume →
docx_edit` import cycle.

### p2p-qa (all files < 1000 — function-level extraction)

- `adversarial.py:484` `run_hacker` (25 locals / 15 branches / 52 stmts)
  — extract probe-driver / reporter sub-functions
- `explorer.py:194` `run_explorer` (26 locals / 61 stmts) — extraction
- `mock_api.py:79` `create_app` (160 stmts) — extract per-route
  builders (`_build_vendor_routes(app, store, …)`, etc.)
- `client.py:182` (6 args / 19 locals) — extract; `StepRecord` /
  `StepLogger` keep class-line suppressions (data records)
- `mock_api.py` module-level `app = create_app()` is a deliberate
  singleton — keep; the W0621 `app` shadow inside `create_app` is fixed
  by renaming the local

## Test Consolidation

### `test_helpers.py` (new, in `scripts/`)

Owns the `sys.path.insert(0, scriptdir)` bootstrap (single place), plus
shared fixtures: `_para`, `_body`, `_sample_date`, and the
`tempfile`+`zipfile` docx scaffold (currently duplicated ~40× across the
giant test files, e.g. `_docx`/`_write_docx` helpers). Imported by the
test files — still a flat-namespace sibling, so the sys.path bootstrap
must run before its import in every test file (kept as a one-line idiom).

### One-file-per-source stays

`test_measure_resume.py` / `test_docx_edit.py` / `test_validate_resume.py`
keep their names and 1:1 mapping (may stay > 1000 lines). Each:

1. switches to `test_helpers` and drops its private `_para`/`_body`/
   `_docx` copies
2. follows their source split for *grouping only where it helps* —
   e.g. `docx_edit_cli` tests move into the same file under a
   `DocxEditCLI*` class; no new test files required (keeps 1:1 mapping)
3. `test_ats_audit.py` / `test_ats_check.py` / `test_squeeze_resume.py`
   also adopt `test_helpers` where the scaffold applies (not required
   where they don't use docx fixtures)

### Data-driven where the evidence actually shows repetition

- `test_validate_resume.py` **WordCapTests**: the 5 `_docx(path,
  bullet_words=…)` siblings (`test_within_cap_ok`,
  `test_over_cap_blocks`, `test_master_input_exempt`,
  `test_max_words_zero_disables`, `test_max_words_flag_lowers_cap`)
  fold into one `for case in CASES:` block asserting per-case report
  substrings
- `test_validate_resume.py` **PunctuationTests**: the ~17 cases driven
  by `_docx(summary_text=, bullet_text=, …)` fold into a
  `for banned, exempt in CASES:` block
- `test_measure_resume.py` single-assert helper clusters (e.g.
  `_jd_title` extraction variants) fold where inputs clearly vary
- `test_docx_edit.py` stays test-per-behavior (its variety is real —
  no forced data-driving)

## Genuine Bug Fixes (included because they're real)

| Finding | Location | Fix |
|---------|----------|-----|
| W0640 cell-var-from-loop ×2 | `measure_resume.py:1121-1122` — closure over loop vars `variants`/`roots` | default-arg binding / factory |
| R0401 cyclic-import ×2 | `docx_edit ↔ validate_resume ↔ measure_resume` static cycle | `script_args.py` extraction + hoisted top-level imports |
| W1514 | `test_ats_check.py:184` `open()` without encoding | add `encoding="utf-8"` |
| W0718 (narrowable ×6) | llm key-load, httpx transports, LLM call sites | narrow exception types |

## Verification

- **Per-phase:** full test suites stay green —
  resume-tailoring: `cd resume-tailoring/scripts && python3 -m unittest
  test_docx_edit test_measure_resume test_validate_resume test_ats_check
  test_ats_audit test_squeeze_resume` (398 tests) and
  p2p-qa: `cd p2p-qa-lab && pytest tests -q` (54 tests, exclusions for
  the four `*_live` network tests)
- **Per-phase:** `pylint $(git ls-files '*.py')` message count only
  decreases; final phase must exit 0
- **Final:** clean checkout run of the pinned command reproduces CI
  (rating 10.00/10, exit 0); CI workflow green on push + PR

## Implementation Phases

1. **Toolchain & config** — `pyproject.toml`, pin workflow, add PR
   trigger, local recipe doc
2. **Triage fixes** — the genuine bugs + small fixes table (W0640,
   W1514, W0621 renames, R1732, C0415 hoist list, ai-judge
   `functools.cache`, `VERDICT_PROMPT` rename, narrowable W0718)
3. **`script_args.py`** — dedupe argv loops; break the import cycle
4. **`docx_edit_cli.py`** — extract CLI surface; move CLI tests
5. **`measure_resume.py` split** — format/jd/drops modules + re-export
   shim; run the resume-tailoring suite after each module moves
6. **`validate_resume.py` split** — checks/master modules + shim
7. **p2p-qa extractions** — adversarial/explorer/mock_api/client
8. **Test consolidation** — `test_helpers.py`, migrate the giants, drop
   private scaffolds, apply data-driven refactors
9. **Suppression pass** — file-header disable blocks (with rationale),
   remaining inline class/line disables, docstring + reflow sweep
10. **Hard-gate closeout** — full lint exit 0, full suites, CI green;
    add `verify-worktree.sh`, wire it into `improve/SKILL.md` Phase 3
    and `merge-worktree.sh`; document that the improve merge is now
    the enforcement point

## Edge Cases

1. **Re-export drift** — a consumer references an `mr.*`/`vr.*`/`de.*`
   name the shim forgets to re-export → caught by the unittest suites
   (every consumer is exercised) + a grep sweep of `\.(mr|vr|de)\.`
   vs the shim's `__all__`.
2. **CLI parity** — `python3 scripts/*.py --help` and the api.md
   documented invocations must behave identically after splits.
3. **Test-file 1:1 mapping** — grouping CLI tests inside
   `test_docx_edit.py` must not create a second test file for the same
   source (mapping rule).
4. **Suppression scope creep** — any new `# pylint: disable` must not
   cover a file/subtree beyond its documented rationale (reviewed in
   the suppression pass).
5. **pylint future upgrades** — pinned `==4.0.8`; config + suppressions
   documented so a deliberate upgrade bump is a conscious change.

## Testing Strategy

1. Existing suites (unittest 398 + pytest 54) are the regression net —
   must stay green at every phase boundary.
2. Pylint message-count diff per phase: monotonic decrease to 0.
3. CLI smoke: the documented api.md invocations run after each split.
4. Final CI parity check on a clean checkout.

## References

- Deferred: `2026-09-07-script-api-promotion-design.md`
- Deferred: `2026-09-07-driftbook-refactor-design.md`