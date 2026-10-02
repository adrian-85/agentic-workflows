# Script API Promotion — Implementation Plan (refreshed)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the 18 shared underscore-prefixed helpers that non-test source still reads cross-module to public names, delete the `protected-access` entry from `pyproject.toml`, and leave pylint green with zero non-test W0212 findings.

**Refresh note (2026-10-02):** re-inventoried against the post-split tree (pylint 4.0.8 W0212 + from-import scan) after the DriftBook refactor and follow-on splits (`jd_asks.py`, `measure_resume_jd_terms.py`, `measure_resume_pruneplan.py`, `docx_edit_*.py`). The helper set, homes, consumers, and test counts below supersede the original 2026-09-07 inventory; the design (rename-only promotion, qualified access, atomic config removal) is unchanged from the spec.

**Architecture:** Rename the `def` in its home module, update the facade's from-import + `__all__` re-export lists, update each consumer call site (`mr._render_pdf` → `mr.render_pdf`), and flip the test files' references to the renamed helpers. Aliases have multiplied (`mr`, `mrf`, `jd_asks`, `client`) — verification is pylint-first (W0212 enabled), with a grep sweep as backup.

**Tech Stack:** Python 3.13, stdlib only.

**Spec:** `docs/superpowers/specs/2026-09-07-script-api-promotion-design.md` (inventory refreshed in the same doc-refresh commit as this plan)

## Global Constraints

- **Land after** both `2026-09-07-pylint-clean-refactor` and `2026-09-07-driftbook-refactor` — ✅ both landed; this plan executes now
- Delete the `protected-access` entry from `pyproject.toml` in the same commit as the **final** rename batch (Task 3) — the config must never lie about the code
- Rename-only: no signature/return-type/docstring-semantics changes (docstring *mentions* of renamed names update with the rename)
- Keep qualified access style (`mr.roles`, `jd_asks.norm_text`) — never unqualified imports of the renamed names
- **From-import consumers of a renamed def must update too** (the facade, `measure_resume_pruneplan.py`, `auto_prune.py`, `jd_asks.py`, `measure_resume_drops.py` import some of these names directly)
- Scope = cross-module **attribute reads** (W0212). Underscore names imported via `from x import _y` with no attribute read (e.g. `docx_edit_gate._deliverable_gate` into `docx_edit.py`, the facade's deliberate re-export surface) are **out of scope** — see spec Non-Goals
- Do **not** promote (no non-test cross-module reader): `_jd_requirement_lines`, `_wrapped_tools`, `_norm`, validate's own `_norm_text`, docx_edit's counters (DriftBook owns those), or any helper whose only external reader is a test file
- `script_args.py`'s `parse_flag`/`extract_flag`/`extract_flag_all` are **already public** — nothing to do there; `validate_resume.py`'s underscore aliases of them (`from script_args import parse_flag as _parse_flag`) are module-local bindings, not W0212, and stay
- Test-file headers keep `protected-access` in their disable list only where the tests still white-box genuinely-private internals; shrink per-file at Task 3/4 where no private reads remain

## File Map

- **Modify:** homes `measure_resume_format.py`, `measure_resume_drops.py`, `measure_resume_jd.py`, `measure_resume.py` (facade def + re-exports), `measure_resume_jd_terms.py`, `jd_asks.py`; from-import consumers `measure_resume_pruneplan.py`, `auto_prune.py`; attribute consumers `squeeze_resume.py`, `validate_resume.py`, `validate_resume_checks.py`, `validate_resume_master.py`, `ats_audit.py`; p2p `p2p-qa-lab/p2p_qa/client.py` + `explorer.py`; test files (renamed-helper references); `pyproject.toml` (remove `protected-access`); this plan + the spec (doc-refresh commit)

---

### Task 0: Commit the doc refresh

- [ ] **Step 1:** This plan file + the spec's refreshed inventory/naming/verification sections (already written before execution begins).
- [ ] **Step 2:** Commit

```bash
git add docs/superpowers/plans/2026-09-07-script-api-promotion.md docs/superpowers/specs/2026-09-07-script-api-promotion-design.md
git commit -m "docs: refresh script-api-promotion plan+spec to the post-split tree"
```

---

### Task 1: Rename the measure_resume family (15 helpers)

**Files:**
- Modify: `measure_resume_format.py`, `measure_resume_drops.py`, `measure_resume_jd.py`, `measure_resume.py` (facade), `measure_resume_pruneplan.py`, `auto_prune.py`, `squeeze_resume.py`, `validate_resume.py`, `validate_resume_checks.py`, `validate_resume_master.py`, test files below

**Interfaces:**
- Produces (renamed, all re-exported public through the `measure_resume` facade unless noted):
  - from `measure_resume_format.py`: `render_pdf`, `pdf_pages_text`, `page_lines`, `match_roles_to_pages`, `roles`, `visible_span`, `company_key`, `drop_created_gaps`
  - defined in the `measure_resume.py` facade itself: `jd_terms`
  - from `measure_resume_drops.py`: `drop_suggestions`, `iter_plan_roles`, `jd_fit_audit`, `measured_lines_per_bullet`, `reclaim_batch`
  - from `measure_resume_jd.py`: `boundaries_without_spacer`

- [ ] **Step 1: Rename the defs in the three split home modules**

In `measure_resume_format.py`: `_render_pdf`→`render_pdf`, `_pdf_pages_text`→`pdf_pages_text`, `_page_lines`→`page_lines`, `_match_roles_to_pages`→`match_roles_to_pages`, `_roles`→`roles`, `_visible_span`→`visible_span`, `_company_key`→`company_key`, `_drop_created_gaps`→`drop_created_gaps`. In `measure_resume_drops.py`: `_drop_suggestions`→`drop_suggestions`, `_iter_plan_roles`→`iter_plan_roles`, `_jd_fit_audit`→`jd_fit_audit`, `_measured_lines_per_bullet`→`measured_lines_per_bullet`, `_reclaim_batch`→`reclaim_batch` (this module also from-imports `_page_lines` from format at ~line 29 — update it). In `measure_resume_jd.py`: `_boundaries_without_spacer`→`boundaries_without_spacer`.

Use word-boundary-aware replacement per name; then `grep -nE "\b_old_name\b"` in each home module to catch intra-module call sites and docstring mentions. Watch substring traps: `_iter_plan_roles` contains `_roles`; `sim_jd_terms`/`_resolved_jd_terms` contain `_jd_terms`; `dropped_roles`/`pre_roles` are different names.

- [ ] **Step 2: Rename `_jd_terms` in the facade + update its re-export lists**

In `measure_resume.py`: rename `def _jd_terms` → `def jd_terms` (~line 137) and its intra-facade call sites (~330, ~425). Update the three from-import blocks (format ~86-112, jd ~152-182, drops ~190-210) to the public names for exactly the 15 renamed names, and the `__all__` string list (~217-250) — the other underscore entries stay (still-private re-exports for tests).

- [ ] **Step 3: Update from-import consumers**

- `measure_resume_pruneplan.py`: `from measure_resume_drops import _jd_fit_audit` → `jd_fit_audit` (~19); `from measure_resume_format import _roles` → `roles` (~22); update their uses (~37, ~102)
- `auto_prune.py`: `from measure_resume_format import (..., _roles)` → `roles` (~58) + its uses (~772 area)

- [ ] **Step 4: Update attribute consumers**

- `squeeze_resume.py` (~79, 80, 107, 158, 160, 161, 167, 168, 169, 170, 203): `mr._iter_plan_roles`, `mr._drop_suggestions`, `mr._jd_terms`, `mr._render_pdf` ×2, `mr._pdf_pages_text`, `mr._page_lines`, `mr._match_roles_to_pages`, `mr._measured_lines_per_bullet`, `mr._reclaim_batch`, `mr._roles`
- `validate_resume.py` (~394, 617): `mr._visible_span`, `mr._jd_fit_audit`, `mr._roles`, `mr._jd_terms`
- `validate_resume_checks.py` (~233, 245, 518): `mr._roles`, `mr._boundaries_without_spacer` ×2
- `validate_resume_master.py` (~88, 172, 187 + docstring ~69): `mr._company_key`, `mr._visible_span`, `mrf._drop_created_gaps`

- [ ] **Step 5: Update tests + verify**

In `test_measure_resume.py`, `test_squeeze_resume.py`, `test_validate_resume.py`, `test_auto_prune.py`, `test_ats_check.py`: flip references to the 15 renamed helpers (word-boundary grep per name; leave still-private internals like `_jd_requirement_lines`, `_wrapped_tools`, `_suggest_drops` untouched). Run the full resume suite → green (718 tests). Sweep:

```bash
cd resume-tailoring/scripts && grep -nE "\b(mr|mrf)\._" *.py | grep -v "test_" || echo "no mr./mrf. underscore reads in source"
```

- [ ] **Step 6: Commit**

```bash
git add resume-tailoring/scripts/
git commit -m "refactor: promote measure_resume shared helpers to public names"
```

Note: `pyproject.toml` is NOT touched yet — the jd_asks and p2p renames remain.

---

### Task 2: Rename the jd_asks family (2 helpers)

**Files:**
- Modify: `measure_resume_jd_terms.py` (home of `_norm_text`), `jd_asks.py` (from-import + `_phrase_evidence` home), `ats_audit.py`, `test_jd_asks.py`

**Interfaces:**
- Produces (renamed): `norm_text` (home `measure_resume_jd_terms.py`, re-exported through `jd_asks`), `phrase_evidence` (home `jd_asks.py`) — consumed by `ats_audit.py`

- [ ] **Step 1: Rename the defs**

- `measure_resume_jd_terms.py`: `_norm_text`→`norm_text` (def ~298; intra-module uses ~362, 403, 410). NOTE: `validate_resume_master.py` / `validate_resume.py` define their **own** `_norm_text` — those stay private (intra-module only)
- `jd_asks.py`: `_phrase_evidence`→`phrase_evidence` (def ~567; intra use ~595); update the from-import `from measure_resume_jd_terms import (..., _norm_text)` (~41) and its intra use (~403)

- [ ] **Step 2: Update consumers**

- `ats_audit.py` (~204, 206, 214): `jd_asks._norm_text` ×2 → `jd_asks.norm_text`; `jd_asks._phrase_evidence` → `jd_asks.phrase_evidence`

- [ ] **Step 3: Update tests + verify**

`test_jd_asks.py`: flip `_phrase_evidence` references. Run the full resume suite → green. Sweep:

```bash
cd resume-tailoring/scripts && grep -nE "\bats\b|jd_asks\._" *.py | grep -v "test_" || echo "no jd_asks underscore reads in source"
```

(Cleaner: `grep -nE "jd_asks\._" *.py | grep -v test_` → empty.)

- [ ] **Step 4: Commit**

```bash
git add resume-tailoring/scripts/
git commit -m "refactor: promote jd_asks shared helpers to public names"
```

---

### Task 3: Promote p2p `check_persisted` + delete the global suppression

**Files:**
- Modify: `p2p-qa-lab/p2p_qa/client.py`, `p2p-qa-lab/p2p_qa/explorer.py`, `pyproject.toml`

**Interfaces:**
- Produces: `Client.check_persisted` public method; `explorer.py` calls it; `pyproject.toml` drops `protected-access`

- [ ] **Step 1: Rename in `client.py`**

`def _check_persisted` → `def check_persisted` (~378) and the intra-class `self._check_persisted` call (~367). It is an instance method — the rename alone makes `client.check_persisted(got, expected)` work at the explorer sites.

- [ ] **Step 2: Update `explorer.py`**

`client._check_persisted` → `client.check_persisted` (×3: ~349, 354, 360). No p2p test references `_check_persisted` (verified) — no test changes needed.

- [ ] **Step 3: Delete the `protected-access` global disable**

In `pyproject.toml`, remove `"protected-access", ` from the `disable = [...]` list. The `wrong-import-position` entry and its comment block STAY (live message, repo convention — see the comment's warning).

- [ ] **Step 4: Verify the goal is met**

```bash
.venv/bin/pylint $(git ls-files '*.py') ; echo "exit: $?"   # must be 0 — this is the goal check
```

Cross-module underscore-read sweep (all current aliases):

```bash
grep -rnE "\b(mr|mrf|vr|de|jd_asks|client|sa|aa|ac|sq|ja|wg)\.[a-z_]*_" resume-tailoring/scripts/*.py p2p-qa-lab/p2p_qa/*.py | grep -v "test_" || echo "no cross-module underscore attribute reads"
```

(Confirm any remaining hits are intra-module or the `de._BOOK` docstring mention in `docx_edit.py` — a comment, not a read.)

Test headers: shrink the `protected-access` item in a test header **only** if that file no longer white-boxes any private member (most still do — e.g. `test_validate_resume.py` reads `vr._punctuation_errors`; leave those). Ledger each shrink decision. Run p2p suite → 54 passed (5 deselected).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml p2p-qa-lab/p2p_qa/client.py p2p-qa-lab/p2p_qa/explorer.py
git commit -m "refactor: promote client.check_persisted; delete global protected-access suppression"
```

---

### Task 4: Final verification + spec closeout

**Files:**
- Global (verification only) + spec docs

**Interfaces:** —

- [ ] **Step 1: Acceptance checks (from the spec)**

1. `.venv/bin/pylint $(git ls-files '*.py')` → exit 0 with `protected-access` gone from config (CI command unchanged)
2. Full suites green: 718 unittest + 54 pytest passed (5 deselected)
3. The Task 3 sweep grep stays empty of real reads
4. api.md documented invocations still work (CLI parity smoke: `python3 resume-tailoring/scripts/{docx_edit,measure_resume,validate_resume,squeeze_resume}.py --help` — exit 0 each)

- [ ] **Step 2: Spec status**

Mark `2026-09-07-script-api-promotion-design.md` status → implemented; in `2026-09-07-pylint-clean-refactor-design.md`, note that the `protected-access` global disable is now gone (this spec's deferred follow-up landed).

- [ ] **Step 3: Commit**

```bash
git add -A docs/
git commit -m "docs: close out script API promotion spec"
```
