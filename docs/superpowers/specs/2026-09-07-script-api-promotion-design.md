# Script API Promotion (defer W0212) — Design Spec (deferred)

**Date**: 2026-09-07
**Status**: Deferred — design-complete, not scheduled
**Author**: Pi Agent (brainstorming session), inventory from pylint 4.0.8
run

---

## Overview

Promote the deliberately-shared underscore-prefixed helpers of the
flat-namespace scripts to **public names**, so cross-module
`protected-access` (W0212) becomes a real (empty) finding instead of a
suppressed convention. The sole `pyproject.toml` suppression — the
global `protected-access` disable — is **deleted** when this lands.

Deferred by explicit user ruling: the underscore convention is kept for
now (suppression carries the rationale); this spec makes the eventual
promotion a mechanical, pre-designed change.

## Current State (exact inventory)

Pylint counts 26 non-test W0212 sites today. Grouped by **consumer**
(the reading module), the shared helpers are:

| Consumer | Helper(s) it reads | Written as |
|----------|--------------------|------------|
| `squeeze_resume.py` | `mr._render_pdf` (×2), `mr._pdf_pages_text`, `mr._page_lines`, `mr._match_roles_to_pages`, `mr._measured_lines_per_bullet`, `mr._reclaim_batch`, `mr._drop_suggestions`, `mr._jd_terms` | `mr.<name>` |
| `validate_resume.py` | `mr._visible_span` (×2), `mr._company_key` | `mr.<name>` |
| `ats_audit.py` | `mr._jd_requirement_lines` | `mr.<name>` |
| `docx_edit.py` | `vr._extract_flag`, `vr._extract_flag_all`, `vr._parse_flag` | `vr.<name>` |
| `explorer.py` (p2p) | `client._check_persisted` (×3) | `client.<name>` |

Test files add ~400 more W0212 sites reading the same helpers plus
deeper internals — but tests are already covered by their file-header
suppression and remain the **white-box** exception (testing the
underscore contract of private internals is the point). Promotion
specifically targets the **source-to-source** reads above.

## Goals

- Zero cross-module `_`-member reads in non-test source
- Delete the `protected-access` entry from `pyproject.toml`
  `[tool.pylint."messages control"]`
- No behavior change; consumers keep the exact same call shapes
  (only the attribute name changes)
- Landing this is atomic: source renames + consumer renames + test
  renames (tests keep using the now-public names; their header
  suppression shrinks to just `missing-*-docstring`, `too-many-lines`,
  `invalid-name`, and the genuinely-private helpers they still white-box)

## Non-Goals

- Promoting purely **intra-module** helpers (e.g. `measure_resume`'s
  `_suggest_drops` used only inside its own module) — those stay
  private; only cross-module reads are promoted
- Changing function signatures, return types, or docstring semantics
- Touching unqualified-import style (the codebase uses qualified
  `import measure_resume as mr` / `mr.roles` — which is exactly what
  makes promotion low-risk: flat-qualified access never collides)

## Design

### Naming

Drop the underscore, keep the name otherwise identical:

| Now | After promotion |
|-----|-----------------|
| `_render_pdf` | `render_pdf` |
| `_pdf_pages_text` | `pdf_pages_text` |
| `_page_lines` | `page_lines` |
| `_match_roles_to_pages` | `match_roles_to_pages` |
| `_measured_lines_per_bullet` | `measured_lines_per_bullet` |
| `_reclaim_batch` | `reclaim_batch` |
| `_drop_suggestions` | `drop_suggestions` |
| `_jd_terms` | `jd_terms` |
| `_jd_requirement_lines` | `jd_requirement_lines` |
| `_visible_span` | `visible_span` |
| `_company_key` | `company_key` |
| `_extract_flag` | `extract_flag` |
| `_extract_flag_all` | `extract_flag_all` |
| `_parse_flag` | `parse_flag` |
| `_check_persisted` | `check_persisted` |

### Post-split home (order matters)

Run **after** `2026-09-07-pylint-clean-refactor-design.md`, so each
helper's home is its split module (`measure_resume_format.py`,
`measure_resume_jd.py`, `measure_resume_drops.py`,
`validate_resume_checks.py`/`master.py`, `docx_edit.py`) and the shim's
re-export list is touched exactly once:

- Rename inside the home module
- Rename the shim `measure_resume.py`/`validate_resume.py` re-export
  (`from measure_resume_format import render_pdf, …`)
- Update every consumer call site (`mr._render_pdf` → `mr.render_pdf`)
- Update tests where they exercise these specific helpers
  (optional for deep internals, which keep the underscore)

### Options considered

1. **Direct rename in place** (recommended): `def _roles` → `def roles`,
   atomic sweeps. Cleanest end state; delete the `protected-access`
   global disable in the same commit.
2. **Public alias before rename**: `roles = _roles` keeps one release
   of compatibility — unnecessary inside a single repo whose tests are
   the compatibility net; adds a permanent dead-alias once all call
   sites flip. Rejected (YAGNI).
3. **Keep underscore + `__all__` exposure**: `__all__` doesn't silence
   W0212 (pylint keys off the underscore) — so this fails the goal.
   Rejected.

### Do NOT promote (remain private)

- Purely internal helpers of each module (used only within their own
  module after the split)
- The docx_edit module counters (covered by the DriftBook spec)
- Any helper whose only external reader is a test file (tests are the
  white-box exception)

## Edge Cases

1. **Shim re-export drift** — if the shim forgets the renamed name,
  consumers fail at import; caught by the unittest suites + a
  `grep -nE "\._[a-z]+"` sweep over non-test source.
2. **Flat-namespace collision** — a public `roles` in
  `measure_resume_format.py` is always accessed qualified
  (`mr.roles`), so no module-global collision; the split's per-module
  `__all__` documents the surface.
3. **Split-first sequencing** — doing this before the split would
  rename in the giant 2388-line module and immediately re-move; the
  spec pins the order.

## Verification

1. `grep -nE "mr\._|vr\._|de\._|client\._|aa\._|ac\._|sq\._" \
   resume-tailoring/scripts/*.py p2p-qa-lab/p2p_qa/*.py` →
   **empty** (no non-test cross-module underscore reads)
2. Full test suites green (unittest 398 + pytest 54)
3. `pylint $(git ls-files '*.py')` exit 0 **without** the
   `protected-access` disable — and test-file headers no longer need
   `protected-access`
4. api.md documented invocations still work (CLI parity)

## Rollout Notes

- Land in one commit with the `pyproject.toml` removal of
  `protected-access`, so the config never lies about the code.
- Not required for the pylint-clean effort (which keeps the
  convention + suppression); purely the debt-clearing follow-on.

## References

- Parent: `2026-09-07-pylint-clean-refactor-design.md`
- Related: `2026-09-07-driftbook-refactor-design.md`