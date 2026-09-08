# DriftBook Refactor — Implementation Plan (deferred)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `docx_edit.py`'s module-level mutable counters (`_APPLIED`, `_SKIPS`, `_ELEMENT_FORM_DROPS`, `_ORIG`) with a `DriftBook` class, removing all `global` statements while keeping `save()`'s drift report byte-identical.

**Architecture:** A single `DriftBook` object owns the four pieces of drift state. `load(path, book=None)`/`save(path, …, book=None)` default to a shared module instance (so CLI behavior is unchanged); tests pass a fresh book to read/reset instead of touching module globals. `_ORIG` folds onto the same object's `orig` dict (same lifecycle).

**Tech Stack:** Python 3.13, stdlib only (`unittest`, `zipfile`, `xml.etree`).

**Spec:** `docs/superpowers/specs/2026-09-07-driftbook-refactor-design.md`

## Global Constraints

- **Land after** `2026-09-07-pylint-clean-refactor` (so `docx_edit.py` is already split with `docx_edit_cli.py`) — the same commit that lands this refactor drops the `global-statement` file-header suppression from `docx_edit.py`
- `save()`'s printed report (`applied N edits`, skip NOTICE, element-form note) and the `*.drift.json` sidecar stay byte-identical
- Test file `test_docx_edit.py` keeps its assertions valid — the ~30 direct `de._APPLIED = 0` / `de._SKIPS.clear()` sites must stop hitting module attributes
- Zero behavioral change; api.md/README unaffected (public `load`/`save` signatures gain an optional `book=` kwarg, backward-compatible)
- `find_p`'s original-text resolution (`_ORIG` reads at lines 91, 145-147, 784) must keep working with the same semantics

## File Map

- **Create:** `resume-tailoring/scripts/docx_edit_drift.py` (holds `DriftBook`; keeps `docx_edit.py` small)
- **Modify:** `resume-tailoring/scripts/docx_edit.py` (14 counter sites → method calls; delete 8 `global` statements; `load`/`save` get `book=None`; `_deliverable_gate` calls move through `save`'s book)
- **Modify:** `resume-tailoring/scripts/test_docx_edit.py` (~30 reset sites → fresh-book/reset; assert on book values where readable)

---

### Task 1: Create `DriftBook`

**Files:**
- Create: `resume-tailoring/scripts/docx_edit_drift.py`

**Interfaces:**
- Produces: `DriftBook` with fields `applied:int`, `skips:list[str]`, `element_form_drops:int`, `orig:dict[int,tuple]`; methods `record_applied()`, `record_skip(prefix_or_label:str)`, `record_element_form_drop()`, `begin(p, text)`, `register(p, text)`, `snapshot() -> tuple[int, list[str], int]`

- [ ] **Step 1: Write the class**

```python
"""DriftBook — edit accounting for docx_edit.py between load() and save().

Replaces the module-level _APPLIED/_SKIPS/_ELEMENT_FORM_DROPS/_ORIG
globals. save() reads a snapshot and resets the book for the next
document session; tests pass a fresh book instead of resetting globals.
"""


class DriftBook:
    """Accumulates drift between load() and the next save()."""

    def __init__(self) -> None:
        self.applied = 0
        self.skips: list[str] = []
        self.element_form_drops = 0
        self.orig: dict[int, tuple] = {}

    # -- mutator entry points (called by docx_edit's mutators) --
    def record_applied(self) -> None:
        self.applied += 1

    def record_skip(self, prefix_or_label: str) -> None:
        self.skips.append(prefix_or_label)

    def record_element_form_drop(self) -> None:
        self.element_form_drops += 1

    # -- original-text registration (replaces _ORIG) --
    def begin(self, p, text: str) -> None:
        """load(): record a paragraph's ORIGINAL text for later resolution."""
        self.orig[id(p)] = (p, text)

    def register(self, p, text: str) -> None:
        """clone_after(): register a NEW paragraph so find_p can resolve it."""
        self.orig[id(p)] = (p, text)

    def snapshot(self) -> tuple[int, list[str], int]:
        """save(): read + reset atomically (for the exported report)."""
        applied, skips, element = self.applied, list(self.skips), self.element_form_drops
        self.applied = 0
        self.skips.clear()
        self.element_form_drops = 0
        return applied, skips, element
```

- [ ] **Step 2: Commit**

```bash
git add resume-tailoring/scripts/docx_edit_drift.py
git commit -m "feat: DriftBook class for docx_edit drift accounting"
```

---

### Task 2: Wire DriftBook into `docx_edit.py`

**Files:**
- Modify: `resume-tailoring/scripts/docx_edit.py`

**Interfaces:**
- Consumes: `DriftBook` from Task 1
- Produces: `load(path, book=None)`, `save(path, root, names, data, drift_key=None, src=None, book=None)`; module-level `_BOOK = DriftBook()` default; **zero** `global` statements

- [ ] **Step 1: Add the module-level default + imports**

At top of `docx_edit.py`:

```python
from docx_edit_drift import DriftBook

_BOOK = DriftBook()   # default book for CLI runs; tests pass their own
```

Delete the four module-level declarations (`_ORIG = {}`, `_APPLIED = 0`, `_SKIPS = []`, `_ELEMENT_FORM_DROPS = 0`).

- [ ] **Step 2: Convert `load()`**

Replace `_ORIG.clear()` + `_ORIG[id(p)] = (p, text_of(p))` at lines 145-147:

```python
def load(path, book=None):
    book = book or _BOOK
    ...
    book.orig.clear()
    for p in paras(root):
        book.orig[id(p)] = (p, text_of(p))
```

(Adjust: the original cleared `_ORIG` after building the map; keep the same ordering — clear first, then populate.)

- [ ] **Step 3: Convert the mutators (14 sites) + `_orig_text`**

- `_orig_text(p)` — replace `_ORIG.get(id(p))` with `_BOOK.orig.get(id(p))`
- `_warn_missing`'s `_SKIPS.append` → `_BOOK.record_skip(...)`
- every `_APPLIED += 1` (6 sites) → `_BOOK.record_applied()`
- the two `_SKIPS.append(old)` in `replace_text` → `_BOOK.record_skip(old)`
- `drop`'s `_SKIPS.append(prefix)` → `_BOOK.record_skip(prefix)`
- `element_form_drops += 1` → `_BOOK.record_element_form_drop()`
- `clone_after`'s `_ORIG[id(new)] = (new, text)` → `_BOOK.register(new, text)`
- delete all 8 `global _APPLIED, _SKIPS, _ELEMENT_FORM_DROPS` statements

- [ ] **Step 4: Convert `save()`**

```python
def save(path, root, names, data, drift_key=None, src=None, book=None):
    book = book or _BOOK
    _deliverable_gate(path, root, src)   # unchanged
    # ... write zip as before ...
    applied, skipped, element_form = book.snapshot()
    if element_form:
        print(f"note: {element_form} drop-family call(s) used the element form …",
              file=sys.stderr)
    ...
```

The rest of `save()` (drift sidecar, NOTICE print, `DOCX_EDIT_STRICT`) reads `applied`/`skipped` locals — identical output.

- [ ] **Step 5: Verify**

Run `cd resume-tailoring/scripts && python3 -m unittest test_docx_edit` — expect failures in the ~30 sites that still reset `/assert` module globals (Task 3 fixes them; if the suite passes because tests use `de._APPLIED` → AttributeError will surface). Also run the full resume suite; `pylint docx_edit.py` → `global-statement` count drops to 0 once the header suppression is removed (do that after Task 3).

---

### Task 3: Migrate the tests off module globals

**Files:**
- Modify: `resume-tailoring/scripts/test_docx_edit.py`

**Interfaces:**
- Consumes: `DriftBook`, `load(path, book=…)`, `save(…, book=…)`
- Produces: tests using per-test `book` instances; assertions read `book.applied` / `book.skips`

- [ ] **Step 1: Add a per-test helper**

In the test file: `from docx_edit_drift import DriftBook`. The `_save`/`_docx_with` helpers gain an optional `book` parameter passed through to `de.save(..., book=book)`.

- [ ] **Step 2: Convert reset sites**

Every `de._APPLIED = 0; de._SKIPS.clear(); de._ELEMENT_FORM_DROPS = 0; de._ORIG.clear()` block becomes a fresh book created in the test and threaded into the `load`/`save` calls:

```python
book = DriftBook()
root, body, names, data, _ = de.load(path, book=book)
...mutations...
de.save(path, root, names, data, book=book)
self.assertEqual(book.applied, 2)
self.assertIn("No Such Prefix", book.skips)
```

For tests that *seed* `_ORIG` directly (`de._ORIG[id(p)] = (p, de.text_of(p))` at 511/643): use `book.register(p, de.text_of(p))` instead.

- [ ] **Step 3: Convert assertion sites**

`assertEqual(de._APPLIED, 0)` → `assertEqual(book.applied, 0)`, `assertIn("x", de._SKIPS)` → `assertIn("x", book.skips)`, `assertEqual(de._ELEMENT_FORM_DROPS, 1)` → `assertEqual(book.element_form_drops, 1)`.

- [ ] **Step 4: Verify + drop the suppression**

Run `python3 -m unittest test_docx_edit` → green; full resume suite → green. Remove `,global-statement` from the `docx_edit.py` header disable (and the rationale line for it). Confirm `pylint docx_edit.py` shows no `W0603` (and no new `W0212` — `book.applied` is public).

- [ ] **Step 5: Commit**

```bash
git add resume-tailoring/scripts/docx_edit.py resume-tailoring/scripts/test_docx_edit.py
git commit -m "refactor: DriftBook replaces module drift globals; drop global-statement suppression"
```

---

### Task 4: Byte-identical drift + final verify

**Files:**
- Global (verification only)

**Interfaces:** —

- [ ] **Step 1: Golden-run comparison**

Before the refactor (git stash of the previous commit), run the documented api.md edit flow on a sample docx through the Tailor script and capture: the `*.docx` bytes + `*.drift.json` + the printed `applied N edits`/NOTICE lines. After: re-run the identical flow and `diff` all three. They must be byte-identical.

- [ ] **Step 2: Full regression + self-review**

- `python3 -m unittest test_docx_edit test_measure_resume test_validate_resume test_squeeze_resume` (and the full 398) → green
- `grep -nE "global " resume-tailoring/scripts/docx_edit.py` → empty
- `pylint $(git ls-files '*.py')` exit 0 (all suites + lint, matching the parent spec's gate)
- Cross-check the DriftBook spec's verification list (4 items) → all done

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: verify DriftBook byte-identical drift and full gate"
```

> **Post-commit:** mark `2026-09-07-driftbook-refactor-design.md` status → implemented, and note in the pylint-clean spec that the `global-statement` suppression for `docx_edit.py` was removed.