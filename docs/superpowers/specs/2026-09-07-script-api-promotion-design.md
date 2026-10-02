# Script API Promotion (defer W0212) — Design Spec

**Date**: 2026-09-07 (inventory refreshed 2026-10-02)
**Status**: In implementation — inventory refreshed against the post-split tree
**Author**: Pi Agent (brainstorming session), inventory from pylint 4.0.8
run

---

## Overview

Promote the deliberately-shared underscore-prefixed helpers of the
flat-namespace scripts to **public names**, so cross-module
`protected-access` (W0212) becomes a real (empty) finding instead of a
suppressed convention. The sole relevant `pyproject.toml` suppression —
the global `protected-access` disable — is **deleted** when this lands.

Deferred by explicit user ruling at design time: the underscore
convention was kept then (suppression carried the rationale); this spec
made the eventual promotion a mechanical, pre-designed change.

## Current State (exact inventory — refreshed 2026-10-02)

Pylint counts **27 non-test W0212 sites** (post-split tree; the
2026-09-07 count of 26 predates the DriftBook refactor and the
`jd_asks`/`measure_resume_jd_terms`/`measure_resume_pruneplan` splits).
Grouped by consumer:

| Consumer | Helper(s) it reads | Written as |
|----------|--------------------|------------|
| `squeeze_resume.py` | `_iter_plan_roles`, `_drop_suggestions`, `_jd_terms`, `_render_pdf` (×2), `_pdf_pages_text`, `_page_lines`, `_match_roles_to_pages`, `_measured_lines_per_bullet`, `_reclaim_batch`, `_roles` | `mr.<name>` (11 sites) |
| `validate_resume.py` | `_visible_span`, `_jd_fit_audit`, `_roles`, `_jd_terms` | `mr.<name>` (4 sites) |
| `validate_resume_checks.py` | `_roles`, `_boundaries_without_spacer` (×2) | `mr.<name>` (3 sites) |
| `validate_resume_master.py` | `_visible_span`, `_company_key` | `mr.<name>`; `_drop_created_gaps` via `mrf.` (3 sites) |
| `ats_audit.py` | `_norm_text` (×2), `_phrase_evidence` | `jd_asks.<name>` (3 sites) |
| `explorer.py` (p2p) | `_check_persisted` (×3) | `client.<name>` (instance method) |

Additionally, non-test source **from-imports** some renamed names
directly (not W0212, but must update with the rename): the
`measure_resume.py` facade re-export lists, `measure_resume_pruneplan.py`
(`_jd_fit_audit`, `_roles`), `auto_prune.py` (`_roles`),
`measure_resume_drops.py` (`_page_lines`), `jd_asks.py` (`_norm_text`).

Test files add many more W0212 sites reading the same helpers plus
deeper internals — tests keep their file-header suppression as the
**white-box** exception. Promotion targets the source-to-source reads
above.

## Goals

- Zero cross-module `_`-member **attribute reads** in non-test source
- Delete the `protected-access` entry from `pyproject.toml`
  `[tool.pylint."messages control"]` (`wrong-import-position` stays —
  live message, deliberate repo convention)
- No behavior change; consumers keep the exact same call shapes
  (only the attribute name changes)
- Config removal lands in the same commit as the final rename batch,
  so the config never lies about the code

## Non-Goals

- Promoting helpers with **no non-test cross-module attribute reader**
  — in the refreshed tree that explicitly excludes `_jd_requirement_lines`
  (only intra-module + test readers remain; `ats_audit` no longer reads
  it), `_wrapped_tools` (facade-internal + tests), `_norm`
  (`measure_resume_format`, intra-module + tests), and validate's own
  `_norm_text` (intra-module only)
- The `script_args.py` flag parsers: `parse_flag`/`extract_flag`/
  `extract_flag_all` are **already public**; `validate_resume.py`'s
  underscore aliases of them are module-local bindings, not W0212
- Changing function signatures, return types, or docstring semantics
- Touching unqualified-import style (the codebase uses qualified
  `import measure_resume as mr` / `mr.roles` — flat-qualified access
  never collides)
- The broader from-import undergrowth (e.g. `docx_edit.py` importing
  `_deliverable_gate` from `docx_edit_gate`, `docx_edit_cli.py`
  importing `_block`): pylint does not flag `from x import _y`, the
  facade's underscore re-export surface is deliberate test white-box
  design, and sweeping it is a separate decision. Scope here = W0212

## Design

### Naming

Drop the underscore, keep the name otherwise identical (18 helpers):

| Now | After promotion | Home module |
|-----|-----------------|-------------|
| `_render_pdf` | `render_pdf` | `measure_resume_format.py` |
| `_pdf_pages_text` | `pdf_pages_text` | `measure_resume_format.py` |
| `_page_lines` | `page_lines` | `measure_resume_format.py` |
| `_match_roles_to_pages` | `match_roles_to_pages` | `measure_resume_format.py` |
| `_roles` | `roles` | `measure_resume_format.py` |
| `_visible_span` | `visible_span` | `measure_resume_format.py` |
| `_company_key` | `company_key` | `measure_resume_format.py` |
| `_drop_created_gaps` | `drop_created_gaps` | `measure_resume_format.py` |
| `_jd_terms` | `jd_terms` | `measure_resume.py` (facade def, delegates to `jd_asks.parse_asks`) |
| `_drop_suggestions` | `drop_suggestions` | `measure_resume_drops.py` |
| `_iter_plan_roles` | `iter_plan_roles` | `measure_resume_drops.py` |
| `_jd_fit_audit` | `jd_fit_audit` | `measure_resume_drops.py` |
| `_measured_lines_per_bullet` | `measured_lines_per_bullet` | `measure_resume_drops.py` |
| `_reclaim_batch` | `reclaim_batch` | `measure_resume_drops.py` |
| `_boundaries_without_spacer` | `boundaries_without_spacer` | `measure_resume_jd.py` |
| `_norm_text` | `norm_text` | `measure_resume_jd_terms.py` (re-exported through `jd_asks`) |
| `_phrase_evidence` | `phrase_evidence` | `jd_asks.py` |
| `_check_persisted` | `check_persisted` | `p2p-qa-lab/p2p_qa/client.py` (instance method) |

### Post-split home (order matters)

Both prerequisites (`2026-09-07-pylint-clean-refactor`,
`2026-09-07-driftbook-refactor`) have landed; each helper's home above
is its split module (or the facade itself, for `_jd_terms`). Per
helper:

- Rename inside the home module (word-boundary-safe: `_iter_plan_roles`
  contains `_roles`; `sim_jd_terms` contains `_jd_terms`)
- Update the `measure_resume.py` facade's from-import blocks and
  `__all__` string list — only the renamed entries flip; still-private
  re-exports (e.g. `_jd_requirement_lines`) keep their underscore
- Update every consumer attribute site and every from-import consumer
  (`measure_resume_pruneplan.py`, `auto_prune.py`, `jd_asks.py`,
  `measure_resume_drops.py`)
- Update tests where they exercise these specific helpers (deep
  internals keep the underscore)

### Options considered

1. **Direct rename in place** (chosen): `def _roles` → `def roles`,
   atomic sweeps. Cleanest end state; delete the `protected-access`
   global disable in the same commit as the final rename batch.
2. **Public alias before rename**: `roles = _roles` keeps one release
   of compatibility — unnecessary inside a single repo whose tests are
   the compatibility net; adds a permanent dead-alias once all call
   sites flip. Rejected (YAGNI).
3. **Keep underscore + `__all__` exposure**: `__all__` doesn't silence
   W0212 (pylint keys off the underscore) — so this fails the goal.
   Rejected.

## Edge Cases

1. **Shim re-export drift** — if the facade forgets the renamed name,
   consumers fail at import; caught by the unittest suites + the pylint
   run (W0212 on the stale attribute read once the disable is gone).
2. **Flat-namespace collision** — a public `roles` in
   `measure_resume_format.py` is always accessed qualified
   (`mr.roles`), so no module-global collision. Multiple `_norm_text`
   definitions (jd_terms home, validate modules) coexist for the same
   reason; only the jd-terms one is promoted.
3. **Substring traps** — `_iter_plan_roles` ⊃ `_roles`,
   `sim_jd_terms`/`_resolved_jd_terms` ⊃ `_jd_terms`, `dropped_roles`
   ≢ `_roles`: renames must be word-boundary-aware.
4. **From-import consumers** — a renamed def breaks `from x import
   _old` at import time; the from-import list above is the checklist.

## Verification

1. `.venv/bin/pylint $(git ls-files '*.py')` → **exit 0** with
   `protected-access` deleted from the disable list (the authoritative
   check — aliases multiplied past any fixed grep list: `mr`, `mrf`,
   `jd_asks`, `client`)
2. Backup sweep: `grep -rnE "\b(mr|mrf|vr|de|jd_asks|client|sa|aa|ac|sq|ja|wg)\.[a-z_]*_" resume-tailoring/scripts/*.py p2p-qa-lab/p2p_qa/*.py | grep -v test_` → no real reads
3. Full test suites green: **718 unittest** (resume) + **54 pytest
   passed, 5 deselected** (p2p)
4. api.md documented invocations still work (CLI parity)

## Rollout Notes

- Four code commits: measure family → jd_asks family → p2p + config
  removal → docs closeout. The config removal rides the p2p commit (the
  last rename batch) so the config never lies.
- Not required for the pylint-clean effort (which kept the convention +
  suppression); this is the debt-clearing follow-up.

## References

- Parent: `2026-09-07-pylint-clean-refactor-design.md`
- Related: `2026-09-07-driftbook-refactor-design.md`
- Plan: `../plans/2026-09-07-script-api-promotion.md`
