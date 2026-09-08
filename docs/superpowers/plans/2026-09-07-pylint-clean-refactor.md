# Pylint-Clean Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pylint $(git ls-files '*.py')` exit 0 on the repo, split the oversized source files, consolidate duplicated test scaffolding, and wire pylint + both test suites into the improve workflow's merge gate.

**Architecture:** Option A — fix everything fixable; suppress only documented conventions (OOXML names, flat-namespace sharing, drift counters, test white-boxing). Large source files split into sibling modules with thin re-export shims (entry points and public surfaces unchanged); test files stay 1:1 with source and may remain >1000 lines. The improve workflow's `verify-worktree.sh` becomes the hard gate on every merge to main.

**Tech Stack:** Python 3.13, pylint 4.0.8 (pinned), stdlib-only resume-tailoring, fastapi/uvicorn/httpx/openai/pytest for p2p-qa, bash (improve scripts), TOML (pylint config).

**Spec:** `docs/superpowers/specs/2026-09-07-pylint-clean-refactor-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

(From the spec — every task implicitly includes these.)

- Pylint pinned `==4.0.8` everywhere (CI, local, `verify-worktree.sh`); deps come from `p2p-qa-lab/requirements.txt` before any pylint run (kills false `import-error`s)
- **No `too-many-*` threshold changes.** Large functions get extracted; large source files get split. Test files may stay >1000 lines (1:1 test→source mapping).
- Entry points and public surfaces preserved exactly: `python3 scripts/<x>.py …` unchanged; `mr.*`, `vr.*`, `de.*` re-exports unchanged; api.md / README / SKILL.md untouched
- Flat-namespace `sys.path.insert(0, scriptdir)` bootstrap preserved; the `import docx_edit as de` style unchanged
- Every `# pylint: disable` gets a written rationale at its point of effect
- Zero behavior change — the 398 unittest (resume) + 54 pytest (p2p-qa) suites must stay green at every phase boundary
- Pylint command to verify at any point: `pylint $(git ls-files '*.py')` (from repo root, toolchain installed)

---

## File Map

**Created:**
- `pyproject.toml` — pylint tool config
- `resume-tailoring/scripts/docx_edit_cli.py` — CLI half of docx_edit
- `resume-tailoring/scripts/measure_resume_format.py` — pages/roles/layout/budget
- `resume-tailoring/scripts/measure_resume_jd.py` — JD vocab/requirements/inference/title
- `resume-tailoring/scripts/measure_resume_drops.py` — drop planning
- `resume-tailoring/scripts/validate_resume_checks.py` — region/checks/readability
- `resume-tailoring/scripts/validate_resume_master.py` — master/integrity/gate/flags
- `resume-tailoring/scripts/script_args.py` — shared argv/flag parsing
- `resume-tailoring/scripts/test_helpers.py` — sys.path bootstrap + shared fixtures
- `improve/scripts/verify-worktree.sh` — the hard-gate verify

**Modified:**
- `.github/workflows/pylint.yml` — pin, PR trigger (backstop only)
- `resume-tailoring/scripts/{docx_edit,measure_resume,validate_resume,squeeze_resume,ats_audit,ats_check,tailor_resume,diff_resume}.py` — splits, re-export shims, docstrings, reflows
- `resume-tailoring/scripts/test_{docx_edit,measure_resume,validate_resume,squeeze_resume,ats_audit,ats_check}.py` — test_helpers migration, headers
- `p2p-qa-lab/p2p_qa/{adversarial,explorer,mock_api,client,cli,llm,judge,money,stress,dspy_judge}.py` — extractions, fixes, docstrings
- `p2p-qa-lab/tests/*.py` — module docstrings, reflows, hoisted imports
- `improve/SKILL.md`, `improve/scripts/merge-worktree.sh` — verify wiring
- `ai-judge/{judge,parse_transcript}.py` — hoisted import, functools.cache, reflows

---

### Task 1: Toolchain & config

**Files:**
- Create: `pyproject.toml`
- Modify: `.github/workflows/pylint.yml`

**Interfaces:**
- Produces: `[tool.pylint]` config consumed by local runs, CI, and `verify-worktree.sh` (Task 10)

- [ ] **Step 1: Create `pyproject.toml` at repo root**

```toml
[tool.pylint]
reports = "no"
fail-under = 0.0

[tool.pylint."messages control"]
# Repo-wide convention with written rationale: the resume-tailoring
# scripts live in a flat namespace and deliberately share underscore-
# prefixed helpers across sibling modules (their "internal API"). Tests
# white-box the same helpers. Expected until the API-promotion spec
# lands; see docs/superpowers/specs/2026-09-07-script-api-promotion-design.md
disable = [
    "protected-access",
]
```

- [ ] **Step 2: Pin pylint + PR trigger in the workflow**

In `.github/workflows/pylint.yml`:

```yaml
on: [push, pull_request]
# ...
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r p2p-qa-lab/requirements.txt
        pip install pylint==4.0.8
    - name: Analysing the code with pylint
      run: |
        pylint $(git ls-files '*.py')
```

- [ ] **Step 3: Verify local reproduces config**

Run: `/tmp/lintvenv/bin/pylint --rcfile=pyproject.toml $(git ls-files '*.py') 2>&1 | tail -1`
Expected: still 1193 messages (count unchanged — no suppression yet beyond `protected-access`), rating unaffected; note the `protected-access` messages disappear from output (verify: `grep -c "W0212" <(...)` → 0).

> If `pip install -r p2p-qa-lab/requirements.txt && pip install pylint==4.0.8` is not yet done in the local env (venv exists at `/tmp/lintvenv` with deps), create/reuse it: `python3 -m venv /tmp/lintvenv && /tmp/lintvenv/bin/pip install -r p2p-qa-lab/requirements.txt pylint==4.0.8`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .github/workflows/pylint.yml
git commit -m "chore: pin pylint 4.0.8, add [tool.pylint] config, gate PRs"
```

---

### Task 2: Triage fixes — genuine issues

**Files:**
- Modify: `resume-tailoring/scripts/measure_resume.py`, `ai-judge/judge.py`, `resume-tailoring/scripts/test_ats_check.py`, `p2p-qa-lab/p2p_qa/*.py`

**Interfaces:**
- Consumes: nothing new
- Produces: a clean baseline for the splits (Tasks 4-6) — fewer moving parts to move

- [ ] **Step 1: Fix `cell-var-from-loop` in `measure_resume.py` (~1121)**

The `_hits` closure inside the `for term in missing_terms:` loop captures the
loop variables `variants` and `roots`:

```python
    for term in missing_terms:
        variants = _inference_variants(term)
        roots = _family_roots(term)

        def _hits(texts):                                # BEFORE: closes over loop vars
            matched = []
            for t in texts:
                low = t.lower()
                if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])",
                                 low) for v in variants) or \
                        any(r in low for r in roots):
                    matched.append(t)
                    if len(matched) >= _INFERENCE_MATCH_CAP:
                        break
            return matched
```

Fix by binding the loop values as default arguments (runs once per
iteration, so each closure keeps its own copy):

```python
    for term in missing_terms:
        _variants = _inference_variants(term)
        _roots = _family_roots(term)

        def _hits(texts, variants=_variants, roots=_roots):   # AFTER: default-arg binding
            matched = []
            for t in texts:
                low = t.lower()
                if any(re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])",
                                 low) for v in variants) or \
                        any(r in low for r in roots):
                    matched.append(t)
                    if len(matched) >= _INFERENCE_MATCH_CAP:
                        break
            return matched
```

Run: `cd resume-tailoring/scripts && python3 -m unittest test_measure_resume -k inference` → pass. Confirm: `pylint measure_resume.py 2>&1 | grep -c W0640` → 0.

- [ ] **Step 2: Fix `unspecified-encoding` at `test_ats_check.py:184`**

Add `encoding="utf-8"` to the `open(...)` call.

- [ ] **Step 3: Fix `redefined-outer-name` (W0621) ×4**

- `p2p-qa-lab/p2p_qa/client.py:344,368` — loop var `field` shadows module-level import `field` (dataclasses). Rename the loop var to `fname` (both sites).
- `p2p-qa-lab/p2p_qa/mock_api.py:81` — local `app` inside `create_app` shadows module-level `app = create_app()`; rename the local to `fastapi_app` (and the `return app`).
- `resume-tailoring/scripts/docx_edit.py:804` — local `prefixes` shadows imported module; rename to `pfxes` (or import as `prefixes_fn`).

For each: run the nearest suite, confirm W0621 count drops by 1.

- [ ] **Step 4: Fix `consider-using-with` (R1732) ×2**

- `p2p-qa-lab/p2p_qa/cli.py:138` — replace bare `x = open(...)` / resource handle with `with open(...) as ...:`
- `p2p-qa-lab/p2p_qa/client.py:141` — same treatment.

- [ ] **Step 5: Fix ai-judge `global _OPENAI_CLIENT` + hoist import**

In `ai-judge/judge.py`:

```python
import functools

@functools.cache
def _build_client():
    api_key = os.environ.get("OPENAI_API_KEY") or load_openrouter_credentials()
    base_url = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    from openai import OpenAI   # ← move to top-level (deps installed)
    return OpenAI(api_key=api_key, base_url=base_url,
                  default_headers={"HTTP-Referer": "https://localhost",
                                   "X-Title": "ai-judge"})

def get_client():
    return _build_client()
```

Also hoist `from parse_transcript import …` to the top after the module docstring (delete the lazy `sys.path.insert` only if the import works without it — it does not; see Task 9 header which keeps the bootstrap and adds the inline disable). Run `python3 -c "import judge"` (from `ai-judge/`) — imports cleanly.

- [ ] **Step 6: Fix `invalid-name` for `VERDICT_PROMPT`**

`p2p-qa-lab/p2p_qa/adversarial.py:498` — rename `VERDICT_PROMPT` → `verdict_prompt` (single local; update its 1-2 uses).

- [ ] **Step 7: Narrow the 6 fixable `broad-exception-caught`**

- `p2p-qa-lab/p2p_qa/llm.py:30` — key load: `except (OSError, KeyError, TypeError)` instead of bare `Exception`
- `p2p-qa-lab/p2p_qa/client.py:166,198,363` — transport: `except httpx.HTTPError` (import `httpx` at top; it's installed)
- `p2p-qa-lab/p2p_qa/dspy_judge.py:60`, `stress.py:136` — LLM call sites: catch the concrete openai/dspy error types they already import, or wrap in the module's `AgentError` and catch that.

Run `pytest p2p-qa-lab/tests -x -q` (exclude `test_dspy_live/test_hacker_live/test_explorer_live/test_report_live`) → 54 passed. Confirm W0718 narrowable count in `/tmp` lint output drops to the 5 boundary sites.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "fix: lint triage — closure binding, encodings, shadows, resource handles, client cache, verdict rename, narrow broad excepts"
```

---

### Task 3: `script_args.py` — dedupe argv loops, break the import cycle

**Files:**
- Create: `resume-tailoring/scripts/script_args.py`
- Modify: `resume-tailoring/scripts/validate_resume.py` (flag fns move out / re-export), `measure_resume.py`, `squeeze_resume.py` (use shared parser)

**Interfaces:**
- Produces: `parse_flag(argv, flag) -> bool`, `extract_flag(argv, flag) -> str|None`, `extract_flag_all(argv, flag) -> list[str]`, `extract_common(argv) -> tuple[protect, jd_file, kept]` — signatures identical to the current `validate_resume._parse_flag/_extract_flag/_extract_flag_all` plus one common-argv helper.

- [ ] **Step 1: Create `script_args.py`**

Move the bodies of `validate_resume.py:634-660` (`_parse_flag`, `_extract_flag`, `_extract_flag_all`) verbatim as public `parse_flag`, `extract_flag`, `extract_flag_all` (module docstring: "Flat-namespace argv helpers shared by the resume scripts; lives outside validate_resume so docx_edit can import it without the import cycle.").

- [ ] **Step 2: Add `extract_common` (the shared protect/jd loop)**

```python
def extract_common(argv, extra_flags=()):
    """Split argv into (protect, jd_file, kept) using the standard --protect/
    --jd loop; extra_flags are single-value flags consumed but not returned.
    Mirrors measure_resume/squeeze_resume main() parsing exactly."""
    protect, jd_file = [], None
    kept = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--protect" and i + 1 < len(argv):
            protect.append(argv[i + 1]); i += 2
        elif a == "--jd" and i + 1 < len(argv):
            jd_file = argv[i + 1]; i += 2
        elif a in extra_flags:
            i += 1
        else:
            kept.append(a); i += 1
    return protect, jd_file, kept
```

- [ ] **Step 3: Swap `docx_edit.py`'s lazy imports to top-level `script_args`**

`docx_edit.py:195-209`: replace `import shlex; import validate_resume as vr` + `vr._extract_flag` calls with top-level `from script_args import extract_flag, extract_flag_all, parse_flag` and direct calls (drop the `shlex` lazy import; `_deliverable_gate` uses `script_args` directly). This removes the `docx_edit → validate_resume` edge — the cycle is broken.

- [ ] **Step 4: Update `validate_resume.py` to use `script_args` and re-export**

In `validate_resume.py`: delete the three flag defs, `from script_args import parse_flag as _parse_flag, extract_flag as _extract_flag, extract_flag_all as _extract_flag_all` at top (keeps `vr._parse_flag` etc. working for consumers), and update `main()` to call them.

- [ ] **Step 5: Convert `measure_resume.py` + `squeeze_resume.py` main() loops**

Replace each hand-rolled `while i < len(argv): …` with `protect, jd_file, kept = script_args.extract_common(argv, extra_flags=(...))`, preserving per-script extras (`--linkedin`, `--simulate` for measure; `--plan-only` for squeeze).

- [ ] **Step 6: Verify**

Run: `cd resume-tailoring/scripts && python3 -m unittest test_docx_edit test_measure_resume test_validate_resume test_squeeze_resume` → all pass (398 total across the suite). Confirm duplicate-code count in that run's pylint output drops by ≥2 (the argv-loop R0801 clusters).

- [ ] **Step 7: Commit**

```bash
git add resume-tailoring/scripts/script_args.py resume-tailoring/scripts/docx_edit.py resume-tailoring/scripts/validate_resume.py resume-tailoring/scripts/measure_resume.py resume-tailoring/scripts/squeeze_resume.py
git commit -m "refactor: script_args.py — shared flat-namespace argv parsing, break docx_edit import cycle"
```

---

### Task 4: Split `docx_edit.py` — extract `docx_edit_cli.py`

**Files:**
- Create: `resume-tailoring/scripts/docx_edit_cli.py`
- Modify: `resume-tailoring/scripts/docx_edit.py`, `resume-tailoring/scripts/test_docx_edit.py` (CLI test grouping)

**Interfaces:**
- Consumes: `docx_edit` core (`load`, `save`, `find_p`, `paras`, `text_of`, `W`) — public names unchanged
- Produces: `docx_edit_cli.cli(argv) -> int`, `docx_edit_cli` owns `__main__`; `docx_edit.cli` becomes `from docx_edit_cli import cli` (re-export) so `python3 scripts/docx_edit.py` keeps working

- [ ] **Step 1: Create `docx_edit_cli.py`**

Move from `docx_edit.py` (verbatim, re-tying the import): `cli()`, `paragraph_map`, `prefixes`, `shortest_unique_prefix`, `style_and_numid`, `_headline_index`, `_prefix_arg`, `_block` (they only call the core's public API + `W`/`TEXT` namespace). Module docstring: "docx_edit.py command-line surface — inspect/find_p prefixes/append-after/set-text. Split from docx_edit.py so the editor core stays focused." Keep `if __name__ == "__main__": sys.exit(cli(sys.argv))` here.

- [ ] **Step 2: Slim `docx_edit.py`**

Delete the moved helpers; add `from docx_edit_cli import cli  # re-export for `python3 scripts/docx_edit.py``; keep `if __name__ == "__main__": sys.exit(cli(sys.argv))` (works via the re-export).

- [ ] **Step 3: Keep the file-header solves the C0103/W0603 suppressions**

Now is the moment to add to `docx_edit.py`'s top (see Task 9 for exact header set — for this task, at least add):

```python
# pylint: disable=invalid-name,global-statement
# invalid-name: rPr/pPr/numId/… mirror OOXML w:rPr/pPr/numId schema tags
#   verbatim so template/spec greps stay obvious.
# global-statement: _APPLIED/_SKIPS/_ELEMENT_FORM_DROPS are module drift
#   counters read by tests; DriftBook refactor deferred (spec 2026-09-07).
```

- [ ] **Step 4: Group the CLI tests**

In `test_docx_edit.py`, the `AppendCLI`/`SetTextCLI`/`StyleFilterCLI`/`PrefixesHeadline`/`CommaListRange` classes stay (they exercise public CLI behavior through the re-export) — no file move needed; add a comment noting they cover `docx_edit_cli` through the re-export.

- [ ] **Step 5: Verify**

Run the full resume suite (398). Smoke: `python3 scripts/docx_edit.py --help` → usage prints (CLI parity). `pylint docx_edit.py` → C0302 gone (module <1000 after re-count), W0603/C0103 suppressed with rationale.

- [ ] **Step 6: Commit**

```bash
git add resume-tailoring/scripts/docx_edit_cli.py resume-tailoring/scripts/docx_edit.py resume-tailoring/scripts/test_docx_edit.py
git commit -m "refactor: split docx_edit CLI surface into docx_edit_cli.py (core <1000 lines)"
```

---

### Task 5: Split `measure_resume.py` — format / jd / drops + re-export shim

**Files:**
- Create: `resume-tailoring/scripts/measure_resume_format.py`, `measure_resume_jd.py`, `measure_resume_drops.py`
- Modify: `resume-tailoring/scripts/measure_resume.py` (slim + re-export)

**Interfaces:**
- Consumes: `docx_edit` public API (unchanged)
- Produces: the three modules each export their functions + constants; `measure_resume.py` re-exports the **full** surface so `import measure_resume as mr; mr.<any existing name>` works without consumer edits

- [ ] **Step 1: Create `measure_resume_format.py`**

Move from `measure_resume.py`, verbatim: `SECTION_*`/`COMPANY_STYLE`/… constants (lines 70-85), `_render_pdf`, `_pdf_pages_text`, `_norm`, `_is_footer`, `_page_lines`, `_flat_from_pages`, `_company_key`, `_roles`, `_top_block_candidates`, `_role_span_months`, `_gap_if_dropped`, `_match_roles_to_pages`, `_wrapped_tools`, `_fixed_top_cost`, `_education_cost`, `_visible_span`, `_page_fill`, `_role_header_flat`, `_preceding_role_key`, `_layout_hints`, `_sparse_last_page_note`, `_measured_lines_per_bullet`, `_reclaim_batch`, `_proficiency_block`. These self-contained helpers need `import docx_edit as de` + `import re` + the constants they reference.

- [ ] **Step 2: Create `measure_resume_jd.py`**

Move: `GENERIC_PHRASES`, `_NUMBER`, `JD_STOP`, `JD_CONCEPTS`, `CORE_TECH_NOUNS`, `_line_terms`, `_vocab_terms`, `_bullet_terms`, `_all_bullet_texts`, `_jd_capitalized`, `_jd_terms`, `JD_SHORT_WORDS`, `JD_SEQ_TERM_RE`, `JD_WORD_TERM_RE`, `JD_COMPANY_VOICE_RE`, `JD_QUAL_HEADING_RE`, `JD_SELF_ASSESSMENT`, `JD_SOFT_SKILL_RE`, `_jd_requirement_lines`, `_jd_line_terms`, `_jd_missing_terms`, `_jd_requirement_coverage`, `_boundaries_without_spacer`, `_jd_report`, `INFERENCE_FAMILIES`, `_INFERENCE_MATCH_CAP`, `_inference_variants`, `_family_roots`, `_inference_map`, `TITLE_MAX_WORDS`, `TITLE_LABEL_RE`, `TITLE_RANK_PATTERNS`, `_title_rank`, `_jd_title`, `_headline_text`, `title_alignment_notes`, `_jd_hits`, `_concept_hits`, `_weakness_key`, `_is_protected`, `_weak_jd_terms`, `_jd_hits_classified`, `_jd_kept`. Depends on `measure_resume_format` for `_roles`/`_visible_span`/`_company_key` and `docx_edit` for the XML.

- [ ] **Step 3: Create `measure_resume_drops.py`**

Move: `_suggest_drops`, `_drop_suggestions`, `_drop_plan_lines`, `_DROP_ACTION`, `_protected_count`, `_dead_end_roles`, `_top_role_batch`, `_apply_simulate`, `_role_jd_evidence_lines`, `_jd_fit_audit`, `_jd_listing_lines`, `_drop_sections`, `_protected_top_role_section`, `_batch_section`. Depends on `measure_resume_format` and `measure_resume_jd`.

- [ ] **Step 4: Slim `measure_resume.py` to a re-export shim**

Keep: `main()`, `_target_from_args`, `_default_target_note`, `_resolved_jd_terms`. Then:

```python
from measure_resume_format import *      # noqa: F401,F403  (public + underscore surface re-exported)
from measure_resume_format import (_company_key, _roles, _render_pdf, _pdf_pages_text,
    _page_lines, _match_roles_to_pages, _measured_lines_per_bullet, _reclaim_batch,
    _visible_span, _layout_hints, _sparse_last_page_note, COMPANY_STYLE, SECTION_CAREER, …)
from measure_resume_jd import *
from measure_resume_drops import *
```

(Spell the underscore names explicitly rather than star-importing them — star-import skips `_` names, so the **explicit list is what preserves `mr._roles`**. The `# noqa` marks keep unused-name nagging quiet; each is justified by re-export intent.)

Note: `_top_role_batch`'s 8-positional-arg signature (R0917 in the original) — leave the signature unchanged now; extraction of its internals can happen in Task 7's spirit if the suite allows, but signature stability for `squeeze_resume`/tests is the priority here.

- [ ] **Step 5: Verify the surface is complete**

```bash
cd resume-tailoring/scripts && python3 -c "
import measure_resume as mr
for name in ['_roles','_jd_terms','_render_pdf','_pdf_pages_text','_page_lines',
             '_match_roles_to_pages','_measured_lines_per_bullet','_reclaim_batch',
             '_drop_suggestions','_top_role_batch','_jd_fit_audit','_visible_span',
             '_inference_map','_jd_title','_company_key','_norm','_wrapped_tools',
             'COMPANY_STYLE','SECTION_CAREER','MAX_BULLETS_PER_ROLE','main']:
    assert hasattr(mr, name), name
print('surface OK')"
```

Run the full resume suite (398) → green. Also `python3 -m unittest test_measure_resume` specifically.

- [ ] **Step 6: Commit**

```bash
git add resume-tailoring/scripts/measure_resume_format.py resume-tailoring/scripts/measure_resume_jd.py resume-tailoring/scripts/measure_resume_drops.py resume-tailoring/scripts/measure_resume.py
git commit -m "refactor: split measure_resume into format/jd/drops modules; thin re-export shim"
```

---

### Task 6: Split `validate_resume.py` — checks / master + shim

**Files:**
- Create: `resume-tailoring/scripts/validate_resume_checks.py`, `validate_resume_master.py`
- Modify: `resume-tailoring/scripts/validate_resume.py`

**Interfaces:**
- Consumes: `script_args`, `measure_resume` (re-exported `mr.*`), `docx_edit`
- Produces: checks/master modules; `validate_resume.py` keeps `validate_tree()`, `main()`, constants, and re-exports the whole `vr.*` surface

- [ ] **Step 1: Create `validate_resume_checks.py`**

Move: constants `TITLE_STYLE`, `SUMMARY_STYLE`, `LIST_STYLES`, `DUP_K`, `SENIORITY_GATE_YEARS`, `DEGREE_RE`, `EQUIV_CLAUSE_RE`, `NUM_CLAIM`, `YEARS_RE`, `DATE_RANGE`, `MAX_BULLETS_PER_ROLE`, `PARA_WORD_CAP`, `MAX_WORDS`; functions `_is_bullet`, `_is_tools`, `_region`, `_summary_paragraph`, `_prose_paragraphs`, `_bullet_cap_errors`, `_structural_errors`, `_near_duplicates`, `_claim_years`, `_TOOLS_LABEL_RE`, `_punctuation_errors`, `_ASCII_OK_CHARS`, `_text_integrity_errors`, `_readability_guidance`, `_word_count`.

- [ ] **Step 2: Create `validate_resume_master.py`**

Move: `_find_master`, `_master_texts`, `_company_headers`, `_role_groups`, `_norm_text`, `_load_master_body`, `_role_integrity_errors`, `_master_span`, `_has_education`, `_education_gate`.

- [ ] **Step 3: Slim `validate_resume.py`**

Keep: `TITLE_STYLE`/`SUMMARY_STYLE` re-exported, `validate_tree()` (the 52-local/56-branch orchestrator — extract its report-building into 2-3 private helpers to clear R0914/R0912/R0915), `main()`, module docstring. Add re-export block mirroring Task 5's (explicit underscore names: `_visible_span`, `_jd_fit_audit`, `_roles`, `_jd_terms`, `_company_key`, `_norm`, `_wrapped_tools`, `_extract_flag`, `_extract_flag_all`, `_parse_flag`, constants, `validate_tree`, `main`).

- [ ] **Step 4: Verify**

`python3 -c "import validate_resume as vr; [assert hasattr(vr, n) for n in ['validate_tree','main','_visible_span','_jd_fit_audit','_roles','_jd_terms','_company_key','_norm','_wrapped_tools','_extract_flag','_extract_flag_all','_parse_flag','TITLE_STYLE','SUMMARY_STYLE','MAX_WORDS']]"` → OK. Full resume suite → green.

- [ ] **Step 5: Commit**

```bash
git add resume-tailoring/scripts/validate_resume_checks.py resume-tailoring/scripts/validate_resume_master.py resume-tailoring/scripts/validate_resume.py
git commit -m "refactor: split validate_resume into checks/master modules; shim keeps vr.* surface"
```

---

### Task 7: p2p-qa — extract the four function hotspots

**Files:**
- Modify: `p2p-qa-lab/p2p_qa/adversarial.py:61,484`, `explorer.py:75,113,194`, `mock_api.py:79`, `client.py:182`

**Interfaces:**
- Consumes: existing module internals; produces sub-functions, public behavior unchanged (the pytest suite + live-test paths)

- [ ] **Step 1: `adversarial.py` — extract in `run_hacker` (line 484)**

`run_hacker` (25 locals/15 branches/52 stmts): extract two private helpers — `_hacker_probe(client, candidate, i, results)` (the per-candidate try/except + append, moving the `ProbeResult(...)` construction) and `_hacker_summary(results)` (the tail that aggregates/prints). Also hoist the lazy `from p2p_qa import llm` at line 490 to top-level and `import json` at 492 (deps installed).

- [ ] **Step 2: `explorer.py` — extract from `run_explorer` (line 194)**

26 locals/61 stmts: extract `_explore_step(client, step, ctx) -> StepRecord` (the per-step POST/GET/verify/record block including the `_check_persisted` calls) and `_summarize(run)` (the report tail). Also hoist `from p2p_qa import llm` (197) and `R0911` on line 75: convert the 12-return control flow to early-return via a small lookup dict if trivial, else per-file `# pylint: disable=too-many-return-statements` is **not** allowed — so do the dict/early-return extraction.

- [ ] **Step 3: `mock_api.py` — extract per-route builders from `create_app` (line 79)**

160 stmts: extract `_vendor_routes(app, store, lock, require_auth)`, `_po_routes(...)`, `_invoice_routes(...)`, `_match_routes(...)`, `_approve_routes(...)`, `_report_routes(...)` (each takes the shared `store`/`lock`/`require_auth` and registers into `app`). `create_app` becomes the composition of these. Hoist `import uvicorn` (379) to top (deps installed). R0903 on the `Store` dataclass: add class-line disable with data-record rationale (validated: it's a data holder).

- [ ] **Step 4: `client.py:182` — extract**

6 args/19 locals: extract the response-handling inner block into `_post_with_proof(...)`; keep the public method signature. Confirm the `StepRecord` class-line disable for R0902 (13 attrs, data-record) is in place (if not already from Task 1's scope, add inline with comment).

- [ ] **Step 5: Verify**

Run p2p-qa suite (54 expected passing with the four `*_live` excluded) and `python -m p2p_qa --help` smoke. Confirm the four hotspot `R0914/0915/0913/0917` disappear from pylint output.

- [ ] **Step 6: Commit**

```bash
git add p2p-qa-lab/p2p_qa/
git commit -m "refactor: extract p2p-qa hotspots (adversarial/explorer/mock_api/client), hoist lazy imports"
```

---

### Task 8: Test consolidation — `test_helpers.py` + data-driven folds

**Files:**
- Create: `resume-tailoring/scripts/test_helpers.py`
- Modify: `resume-tailoring/scripts/test_measure_resume.py`, `test_docx_edit.py`, `test_validate_resume.py`, `test_squeeze_resume.py`

**Interfaces:**
- Produces: `test_helpers._para(text, style=None, numId=None)`, `_body(ps)`, `_sample_date()`, `_write_docx(path, paragraphs)` (the tempfile+zipfile scaffold); the three giants switch to it and delete private copies

- [ ] **Step 1: Create `test_helpers.py`**

```python
"""Shared fixtures for the resume-tailoring script tests.

Owns the sys.path bootstrap so sibling-import tests and docx scaffolding
live in one place (was copy-pasted ~40x across the giant test files)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, __file__.rsplit("/", 1)[0])

import docx_edit as de  # noqa: E402

W = de.W

def _para(text, style=None, numId=None):
    """Build a <w:p> with optional pStyle/numId (mirrors the master)."""
    p = ET.Element(W + "p")
    if style is not None or numId is not None:
        pPr = ET.SubElement(p, W + "pPr")
        if style is not None:
            st = ET.SubElement(pPr, W + "pStyle")
            st.set(W + "val", style)
        if numId is not None:
            np = ET.SubElement(pPr, W + "numPr")
            ni = ET.SubElement(np, W + "numId")
            ni.set(W + "val", str(numId))
    r = ET.SubElement(p, W + "r")
    t = ET.SubElement(r, W + "t")
    t.text = text
    return p

def _body(ps):
    body = ET.Element(W + "body")
    for p in ps:
        body.append(p)
    return body

def _sample_date():
    """A date token the CURRENT DATE_RE matches (MM/YYYY or ISO)."""
    return "06/2021"

def _write_docx(path, paragraphs):
    """Zip a minimal .docx (document.xml + [Content_Types]) to path
    and return (root, body, names, data) via de.load() for edits."""
    fd, real = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    os.replace(real, path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="' + de.XMLNS
                   + '"><w:body/></w:document>')
        z.writestr("[Content_Types].xml", "<Types/>")
    root, body_el, names, data, _ = de.load(path)
    for p in paragraphs:
        body_el.append(p)
    with contextlib.redirect_stdout(io.StringIO()):
        de.save(path, root, names, data)
    return root, body_el, names, data
```

- [ ] **Step 2: Migrate `test_measure_resume.py`**

Replace its `_para`/`_body`/`_sample_date` defs with `from test_helpers import W, _para, _body, _sample_date` (keep its own `sys.path.insert` line — the bootstrap must run before the `test_helpers` import too; the `# noqa: E402` notes that). Delete the duplicated block. Run `python3 -m unittest test_measure_resume` → green.

- [ ] **Step 3: Migrate `test_docx_edit.py` + `test_validate_resume.py` + `test_squeeze_resume.py`**

Same swap (validate uses `mk`/`body` names — keep a one-line alias `mk = _para; body = _body` or rename call sites; prefer aliases for minimal diff). Delete private `_docx`/`_write_docx`/`_write` copies where the shared `_write_docx` covers them (validate's `_docx(path, bullet_words=…)` variants adapt: build the paragraph list with `_para(..., numId=4)` and `_write_docx`). Run each suite → green.

- [ ] **Step 4: Data-driven folds (only where the evidence supports it)**

In `test_validate_resume.py` WordCapTests, replace the five `_docx(path, bullet_words=…)` sibling tests with one table:

```python
CASES = [
    # (bullet_words, expected_needle, absent_needle)
    (99,  "within the 1000-word cap", None),
    (140, "exceeds the 1000-word cap", None),
    (140, "input is a master", "exceeds the 1000-word cap"),   # master exempt
    (140, "word cap disabled", "exceeds the 1000-word cap"),   # max_words=None
    (140, None, None),                                          # lowered-cap case
]
def test_word_cap_matrix(self):
    for bullet_words, needle, absent in CASES:
        path = os.path.join(tempfile.mkdtemp(), "Resume - T.docx")
        try:
            self._docx(path, bullet_words=bullet_words)
            result = vr.validate_tree(path, self._body(path))
            report = "\n".join(result["lines"])
            if needle: self.assertIn(needle, report)
            if absent: self.assertNotIn(absent, report)
        finally:
            os.unlink(path)
```

(Keep the per-case assertions for blocking counts where the original asserted `result["blocking"]` — fold those into the table as an extra `expected_blocking` column.)

In PunctuationTests, fold the ~17 cases into `for banned, exempt in CASES:` using the existing `_docx(summary_text=, bullet_text=, …)` params. In `test_measure_resume.py`, fold the `_jd_title` extraction variants (TitleAlignment) into a small input/expected table. **Do not** data-drive `test_docx_edit.py` — its variety is real.

- [ ] **Step 5: Verify + commit**

Full resume suite → green, message count for the three giants' duplicate-code drops to 0. Commit:

```bash
git add resume-tailoring/scripts/test_helpers.py resume-tailoring/scripts/test_measure_resume.py resume-tailoring/scripts/test_docx_edit.py resume-tailoring/scripts/test_validate_resume.py resume-tailoring/scripts/test_squeeze_resume.py
git commit -m "test: shared test_helpers fixtures + data-driven folds for repeated case clusters"
```

---

### Task 9: Suppression headers + docstring/reflow sweep

**Files:** all remaining files with messages

**Interfaces:** — (convergence task)

- [ ] **Step 1: Add test-file headers (each with rationale)**

For every `test_*.py` + `p2p-qa-lab/tests/conftest.py`, insert after the module docstring (create one if missing so the header has a home):

```python
# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.
```

(Add `import-outside-toplevel,wrong-import-position` to the header of any test still using the flat `sys.path` bootstrap ordering.)

- [ ] **Step 2: Add source-file headers (each with rationale)**

- `resume-tailoring/scripts/{docx_edit,measure_resume,squeeze_resume,validate_resume,ats_audit,ats_check,tailor_resume,diff_resume}.py`: `# pylint: disable=wrong-import-position,import-outside-toplevel` — "flat-namespace sibling imports require the sys.path bootstrap; sibling import precedes use." (Where a lazy import was already hoisted in Tasks 2/7, don't re-add its disable.)
- `ai-judge/judge.py`: keep the bootstrap, inline `# pylint: disable=wrong-import-position` on the one `from parse_transcript import …` line (add rationale comment on the line above).

- [ ] **Step 3: Add class-line disables (data records)**

- `p2p-qa-lab/p2p_qa/client.py` `class StepRecord` → `# pylint: disable=too-many-instance-attributes  # data record mirroring the wire schema`
- `p2p-qa-lab/p2p_qa/mock_api.py` `class Store` → `# pylint: disable=too-few-public-methods  # data holder (bug profile + seed)`

- [ ] **Step 4: Add the 5 boundary `broad-exception-caught` inline disables**

At `p2p-qa-lab/p2p_qa/cli.py:127` (server-wait retry), `adversarial.py:36` (payload truncation), `adversarial.py:340` (probe isolation — already `# noqa: BLE001`, add the pylint disable alongside), `resume-tailoring/scripts/validate_resume.py:496` (master parse boundary), each with a one-line comment: `# pylint: disable=broad-exception-caught  # process boundary: ...`.

- [ ] **Step 5: Docstring + reflow sweep on remaining source**

- Add source `missing-function/class/module-docstring` (the 72 non-test sites) — one-line docstrings describing intent; where the function is a moved helper, reuse its original docstring.
- Reflow the 42 `line-too-long` non-test sites (and the `parse_transcript.py:89` etc.); long string literals get `# noqa: E501`.
- `p2p-qa-lab/tests/*.py` module docstrings (18 missing) — one line each; reflow their C0301s.

- [ ] **Step 6: Converge to exit 0**

Run the clean-slate check to find any residue:

```bash
/tmp/lintvenv/bin/pylint $(git ls-files '*.py') 2>&1 | grep -E "^[a-z/._-]+\.py:" | wc -l
```

Iterate: each remaining message is either (a) fixed (docstring/reflow/rename/extraction) or (b) a documented suppression that belongs in the header/class-line. **No new category disables.** Stop when the count is 0 and the run exits 0.

- [ ] **Step 7: Full verify + commit**

```bash
cd resume-tailoring/scripts && python3 -m unittest test_docx_edit test_measure_resume test_validate_resume test_ats_check test_ats_audit test_squeeze_resume
cd p2p-qa-lab && pytest tests -x -q
cd .. && pylint $(git ls-files '*.py') && echo "exit 0"
git add -A
git commit -m "lint: suppression headers with rationale, source docstrings, reflows — pylint exit 0"
```

---

### Task 10: Hard-gate closeout — `verify-worktree.sh` + improve wiring

**Files:**
- Create: `improve/scripts/verify-worktree.sh`
- Modify: `improve/SKILL.md`, `improve/scripts/merge-worktree.sh`

**Interfaces:**
- Consumes: the pinned toolchain + the exact lint/suite commands from Tasks 1-9
- Produces: `verify-worktree.sh` (exit 0 = mergeable) wired into hard stop #4 and the merge script

- [ ] **Step 1: Create `improve/scripts/verify-worktree.sh`**

```bash
#!/bin/bash
# verify-worktree.sh - Block a worktree merge unless lint + tests pass.
# Hard gate for the improve workflow: main only ever receives a merge
# that passed the pinned pylint + both test suites, in the worktree.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "== verify-worktree: dependencies =="
python3 -m pip install --quiet --break-system-packages \
    -r p2p-qa-lab/requirements.txt pylint==4.0.8 2>/dev/null \
  || python3 -m pip install --quiet -r p2p-qa-lab/requirements.txt pylint==4.0.8

echo "== verify-worktree: pylint =="
pylint $(git ls-files '*.py')
echo "✓ pylint clean"

echo "== verify-worktree: resume-tailoring suite =="
(cd resume-tailoring/scripts && python3 -m unittest test_docx_edit test_measure_resume \
    test_validate_resume test_ats_check test_ats_audit test_squeeze_resume)
echo "✓ resume-tailoring suite green"

echo "== verify-worktree: p2p-qa suite =="
(cd p2p-qa-lab && python3 -m pytest tests -x -q \
    --ignore=tests/test_dspy_live.py --ignore=tests/test_hacker_live.py \
    --ignore=tests/test_explorer_live.py --ignore=tests/test_report_live.py)
echo "✓ p2p-qa suite green"
echo "== verify-worktree: PASS =="
```

(`--break-system-packages` covers Debian-managed Python where pip refuses; the `||` fallback covers venvs. If the repo uses a venv at runtime, the caller should ensure the toolchain is active — verify-worktree uses whatever python3/pylint is on PATH after a best-effort install.)

- [ ] **Step 2: Wire into `improve/SKILL.md` Phase 3**

In the Phase 3 section, before "Generate the final diff":

```markdown
1. **Verify (hard gate):** run `scripts/verify-worktree.sh` inside the
   worktree. If it exits non-zero, **STOP** — report the failing check
   and do not present the final diff until the worktree is fixed and
   verify passes.
```

- [ ] **Step 3: Wire into `improve/scripts/merge-worktree.sh`**

Insert immediately after the argument/branch checks (before any `git checkout main`):

```bash
# Hard gate: refuse to merge a worktree that fails lint or tests.
echo "Running verify-worktree hard gate..."
"$SCRIPT_DIR/verify-worktree.sh"
echo "✓ hard gate passed; merging."
```

(`set -e` aborts the merge on failure — belt-and-suspenders behind the SKILL.md step.)

- [ ] **Step 4: Verify the gate end-to-end**

From a clean worktree of the repo: run `improve/scripts/verify-worktree.sh` → PASS. Prove it blocks: `echo "x = 1" >> resume-tailoring/scripts/diff_resume.py` in a scratch worktree, run verify → non-zero with `pylint` message; revert. Confirm `merge-worktree.sh` runs verify (stub a failing verify, watch the merge abort before checkout).

- [ ] **Step 5: Confirm the self-improvement gate**

When the `improve` workflow improves itself (including `verify-worktree.sh`/`merge-worktree.sh`), the gate runs on the self-improved worktree before merge — verify by reading SKILL.md's own-improvement path still routes through Phase 3 (it does: self-improvement reuses the same phases).

- [ ] **Step 6: Commit**

```bash
chmod +x improve/scripts/verify-worktree.sh
git add improve/scripts/verify-worktree.sh improve/scripts/merge-worktree.sh improve/SKILL.md
git commit -m "feat: verify-worktree.sh hard gate wired into improve Phase 3 and merge"
```

- [ ] **Step 7: Final acceptance**

Fresh checkout → `verify-worktree.sh` PASS; `pylint $(git ls-files '*.py')` exit 0; both suites green; CI workflow green on a push; the improve merge path runs the gate. Update the plan's spec status to implemented.