# Script API Promotion — Implementation Plan (deferred)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the ~15 shared underscore-prefixed helpers to public names, delete the `protected-access` entry from `pyproject.toml`, and leave zero non-test cross-module underscore reads.

**Architecture:** Rename the helper in its home module, update the shim's re-export list, update each consumer call site (`mr._render_pdf` → `mr.render_pdf`), and flip the test files' affected call sites. Atomic single-commit landing: source renames + consumer renames + `pyproject.toml` removal together.

**Tech Stack:** Python 3.13, stdlib only.

**Spec:** `docs/superpowers/specs/2026-09-07-script-api-promotion-design.md`

## Global Constraints

- **Land after** both `2026-09-07-pylint-clean-refactor` and `2026-09-07-driftbook-refactor` (so each helper's home is its split module, and the shim's re-export list is touched exactly once)
- **Delete** the `protected-access` entry from `pyproject.toml` in the same commit as the renames — the config must never lie about the code
- Rename-only: no signature/return-type/docstring-semantics changes
- Keep qualified access style (`mr.roles`, `vr.extract_flag`) — never unqualified imports
- Do **not** promote: purely intra-module helpers, docx_edit's counters (DriftBook owns those), or helpers whose only external reader is a test file (tests remain the white-box exception)
- Test-file headers may keep `protected-access` in their disable list only where the tests still white-box genuinely-private internals; once specific helpers become public, update/keep the header as appropriate per the spec's "shrink" note

## File Map

- **Modify:** home modules `resume-tailoring/scripts/measure_resume_format.py`, `measure_resume_jd.py`, `measure_resume_drops.py`, `validate_resume_checks.py`, `validate_resume_master.py`, `docx_edit.py` (rename-only), shims `measure_resume.py`/`validate_resume.py` (re-export list), consumers `squeeze_resume.py`, `validate_resume.py`, `ats_audit.py`, `docx_edit.py`, `p2p-qa-lab/p2p_qa/explorer.py` + `client.py`, test files (affected call sites), `pyproject.toml` (remove `protected-access`)

---

### Task 1: Rename the measure_resume helpers (format / jd / drops)

**Files:**
- Modify: `resume-tailoring/scripts/measure_resume_format.py`, `measure_resume_jd.py`, `measure_resume_drops.py`, `measure_resume.py` (shim), `squeeze_resume.py`, `validate_resume.py`, `ats_audit.py`

**Interfaces:**
- Produces (renamed): `render_pdf`, `pdf_pages_text`, `page_lines`, `match_roles_to_pages`, `measured_lines_per_bullet`, `reclaim_batch`, `drop_suggestions`, `jd_terms`, `jd_requirement_lines`, `visible_span`, `company_key` — all public on `measure_resume` (`mr.*`) after the shim update

- [ ] **Step 1: Rename in each home module**

In `measure_resume_format.py`, rename `def _render_pdf → render_pdf`, `_pdf_pages_text → pdf_pages_text`, `_page_lines → page_lines`, `_match_roles_to_pages → match_roles_to_pages`, `_measured_lines_per_bullet → measured_lines_per_bullet`, `_reclaim_batch → reclaim_batch`, `_visible_span → visible_span`, `_company_key → company_key`. In `measure_resume_jd.py`: `_jd_terms → jd_terms`, `_jd_requirement_lines → jd_requirement_lines`. In `measure_resume_drops.py`: `_drop_suggestions → drop_suggestions`.

(Internal cross-references *within* each module update automatically via the rename — verify by running the module's tests, then fix any remaining `_` references the editor missed.)

- [ ] **Step 2: Update the `measure_resume.py` shim**

Replace the explicit `_name` re-export list with the public names (list them explicitly, not star-import — star-import would now pick up public names too, but explicit keeps the surface auditable):

```python
from measure_resume_format import (render_pdf, pdf_pages_text, page_lines,
    match_roles_to_pages, measured_lines_per_bullet, reclaim_batch,
    visible_span, company_key, …constants…)
from measure_resume_jd import (jd_terms, jd_requirement_lines, …)
from measure_resume_drops import (drop_suggestions, …)
```

- [ ] **Step 3: Update consumer call sites**

- `squeeze_resume.py`: `mr._render_pdf`→`mr.render_pdf` (×2), `mr._pdf_pages_text`→`mr.pdf_pages_text`, `mr._page_lines`→`mr.page_lines`, `mr._match_roles_to_pages`→`mr.match_roles_to_pages`, `mr._measured_lines_per_bullet`→`mr.measured_lines_per_bullet`, `mr._reclaim_batch`→`mr.reclaim_batch`, `mr._drop_suggestions`→`mr.drop_suggestions`, `mr._jd_terms`→`mr.jd_terms`
- `validate_resume.py`: `mr._visible_span`→`mr.visible_span` (×2), `mr._company_key`→`mr.company_key`
- `ats_audit.py`: `mr._jd_requirement_lines`→`mr.jd_requirement_lines`

- [ ] **Step 4: Update test call sites + verify**

In `test_squeeze_resume.py`, `test_measure_resume.py`, `test_validate_resume.py`, `test_ats_audit.py`: update the exercised public-helper references (keep white-box tests of still-private internals untouched). Run the full resume suite → green (398).

Verify the sweep is complete:

```bash
cd resume-tailoring/scripts && grep -nE "mr\._" *.py | grep -v "test_" || echo "no mr._ reads in source"
```

- [ ] **Step 5: Commit this task**

```bash
git add resume-tailoring/scripts/
git commit -m "refactor: promote measure_resume shared helpers to public names"
```

Note: `pyproject.toml` is NOT touched yet — more renames remain (validate/docx/p2p).

---

### Task 2: Rename the validate_resume helpers + flag parsers

**Files:**
- Modify: `resume-tailoring/scripts/validate_resume_checks.py`, `validate_resume_master.py`, `validate_resume.py` (shim), `docx_edit.py`, `resume-tailoring/scripts/test_validate_resume.py`

**Interfaces:**
- Produces (renamed): `visible_span` (from `_visible_span` in checks), `jd_fit_audit`, `roles`, `jd_terms`, `company_key`, `norm`, `wrapped_tools`, `extract_flag`, `extract_flag_all`, `parse_flag` — all public on `validate_resume` (`vr.*`)

- [ ] **Step 1: Rename in the split modules**

- `validate_resume_checks.py`: `_visible_span → visible_span`, `_norm → norm`
- `validate_resume_master.py`: `_extract_flag → extract_flag`, `_extract_flag_all → extract_flag_all`, `_parse_flag → parse_flag`
- `validate_resume.py` (the remaining orchestrator): `_jd_fit_audit → jd_fit_audit`, `_roles → roles`, `_jd_terms → jd_terms`, `_company_key → company_key`, `_wrapped_tools → wrapped_tools`
- `script_args.py`: already-public `parse_flag`/`extract_flag`/`extract_flag_all` — the shim re-imports them under public names, so `docx_edit.py`'s `vr.` calls update accordingly

- [ ] **Step 2: Update the `validate_resume.py` shim**

Explicit re-export list with the public names (mirror Task 1 Step 2).

- [ ] **Step 3: Update consumers**

- `docx_edit.py`: `vr._extract_flag`→`vr.extract_flag`, `vr._extract_flag_all`→`vr.extract_flag_all`, `vr._parse_flag`→`vr.parse_flag`

- [ ] **Step 4: Update tests + verify**

`test_validate_resume.py` + `test_docx_edit.py`: update exercised public references. Run the full resume suite → green. Sweep:

```bash
cd resume-tailoring/scripts && grep -nE "vr\._" *.py | grep -v "test_" || echo "no vr._ reads in source"
```

- [ ] **Step 5: Commit**

```bash
git add resume-tailoring/scripts/
git commit -m "refactor: promote validate_resume + script_args helpers to public names"
```

---

### Task 3: Promote p2p-qa `_check_persisted` + delete the global suppression

**Files:**
- Modify: `p2p-qa-lab/p2p_qa/client.py`, `explorer.py`, `p2p-qa-lab/tests/test_explorer_live.py` (call sites), `pyproject.toml`

**Interfaces:**
- Produces: `client.check_persisted` public; `explorer.py` calls it; `pyproject.toml` drops `protected-access`

- [ ] **Step 1: Rename in `client.py`**

`def _check_persisted` → `def check_persisted` (assign to the client instance so `client.check_persisted(got, expected)` works at the 3 explorer sites).

- [ ] **Step 2: Update `explorer.py` + data-path tests**

`client._check_persisted` → `client.check_persisted` (×3), and any test asserting on it.

- [ ] **Step 3: Delete the `protected-access` global disable**

In `pyproject.toml`, remove the `protected-access` entry and the whole `[tool.pylint."messages control"]` block if now empty.

- [ ] **Step 4: Verify the goal is met**

```bash
grep -rnE "\._[a-z_]+" resume-tailoring/scripts/*.py p2p-qa-lab/p2p_qa/*.py | grep -vE "test_|def _|self\.|#.*_{2}" || echo "no cross-module underscore reads"
```

(This regex may match intra-module `_` calls — confirm the remaining hits are all intra-module private use, which is allowed.)

Test headers: shrink the `protected-access` item in each test header **only** if the tests no longer white-box any private members; otherwise keep it (the spec allows the white-box exception). Run p2p-qa suite → 54 green; full pylint exit 0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml p2p-qa-lab/p2p_qa/client.py p2p-qa-lab/p2p_qa/explorer.py p2p-qa-lab/tests/test_explorer_live.py
git commit -m "refactor: promote client.check_persisted; delete global protected-access suppression"
```

---

### Task 4: Final verification + spec closeout

**Files:**
- Global (verification only)

**Interfaces:** —

- [ ] **Step 1: Acceptance checks (from the spec)**

1. `grep -nE "mr\._|vr\._|de\._|client\._|aa\._|ac\._|sq\._" resume-tailoring/scripts/*.py p2p-qa-lab/p2p_qa/*.py` → **empty** (no non-test cross-module underscore reads)
2. Full suites green: 398 unittest + 54 pytest
3. `pylint $(git ls-files '*.py')` exit 0 **without** `protected-access` in config; test headers no longer list `protected-access` where the white-box exception no longer applies
4. api.md documented invocations still work (CLI parity smoke: `python3 scripts/{docx_edit,measure_resume,validate_resume,squeeze_resume}.py --help`)

- [ ] **Step 2: Spec status**

Mark `2026-09-07-script-api-promotion-design.md` status → implemented; note in the pylint-clean spec that the `protected-access` global disable is gone.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "docs: close out script API promotion spec"
```