# DriftBook Refactor — Design Spec (deferred)

**Date**: 2026-09-07
**Status**: Deferred — design-complete, not scheduled
**Authors**: Pi Agent (brainstorming session), validated against
`docx_edit.py` v1 (1278-line module)

---

## Overview

Replace the module-level mutable counters in `resume-tailoring/scripts/
docx_edit.py` with a single small `DriftBook` class. This removes the
`global-statement` (W0603) suppressions currently applied to the file and
turns the edited-edit accounting into testable state with a defined
lifecycle.

## Current State (what the refactor replaces)

Module-global state declared at the top of `docx_edit.py`:

```python
_ORIG = {}                      # id(p) -> (p, original text); populated by load()
_APPLIED = 0                    # mutators increment
_SKIPS = []                     # prefix/label of each skipped edit
_ELEMENT_FORM_DROPS = 0         # drop-family calls given an element
```

Mutation sites today:
- `_SKIPS.append(...)` at lines 106, 692, 718, 835
- `_APPLIED += 1` at 579, 593, 658, 725, 786, 801
- `_ELEMENT_FORM_DROPS += 1` at 871 (879 in the drop-family paths)
- `save()` (lines 336-349) reads all three, prints the report, and
  **resets them to zero** (so the counters describe "edits since last
  save")
- `load()` (145-147) clears and repopulates `_ORIG`
- `clone_after` (784) registers into `_ORIG`
- Test file `test_docx_edit.py` **reads and resets the counters
  directly**: `de._APPLIED = 0`, `de._SKIPS.clear()`,
  `de._ELEMENT_FORM_DROPS = 0`, `de._ORIG[...] = ...` at ~30 sites
  (lines 126-131, 198, 212, 511-521, 528, 560-601, 643-649, …)

## Goals

- Zero `global` statements in `docx_edit.py`
- Drift accounting is a single named object with clear lifecycle:
  created fresh per document session (per `load()`), consumed+reset by
  `save()`
- Tests can create the object or reset it without reaching into
  module state
- Behavior of `save()`'s report and the `DOCX_EDIT_STRICT` gate is
  **byte-identical**

## Non-Goals

- Changing the drift sidecar (`*.drift.json`) format — it stays a
  side-effect of `save()`
- Thread-safety machinery (these scripts are single-threaded by design)
- Touching `_ORIG` semantics beyond moving it onto the same object if
  convenient (it is a different concern — original-text cache keyed by
  element id — and may stay module-global; see Decision D1)

## Design

### The class

```python
class DriftBook:
    """Accumulates edit accounting between load() and the next save().

    save() reads these values to print its end-of-run report and reset
    the book for the next session. DO NOT rely on values after save()."""

    def __init__(self) -> None:
        self.applied = 0
        self.skips: list[str] = []
        self.element_form_drops = 0
        self.orig: dict[int, object] = {}   # id(p) -> (p, original text)

    # -- mutators (called by docx_edit.py's mutators) --
    def record_applied(self) -> None:            self.applied += 1
    def record_skip(self, prefix_or_label: str) -> None:
        self.skips.append(prefix_or_label)
    def record_element_form_drop(self) -> None:  self.element_form_drops += 1

    # -- lifecycle --
    def begin(self, p: object, text: str) -> None:
        """load(): record a paragraph's original text for later resolution."""
        self.orig[id(p)] = (p, text)
    def register(self, p: object, text: str) -> None:
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

### Decision D1 — how the book reaches the mutators

Three options, recommendation bolded:

1. **Module-level default instance, functions take optional override** —
   `_BOOK = DriftBook()` at module top; `load(path, book=None)` and
   `save(path, ..., book=None)` default to `_BOOK`; the standalone
   mutator functions (`set_text`, `drop`, …) reference the shared
   instance. No `global` statements (the object is mutated via methods;
   rebinding never happens). **Recommended** — zero signature churn for
   the public editor calls, tests can pass a fresh `DriftBook()` to
   `load`/`save` and delete it instead of resetting counters.
2. **Thread `book` through every mutator signature** — explicit but
   touches ~12 public mutator signatures and every call site; larger
   diff, more churn, no behavioral gain (single-threaded by design).
3. **Additive refactor** — fold counters into the drift sidecar only,
   leaving tests' direct counter resets broken. Rejected.

D1 also gives the resolution for the test file: current
`de._APPLIED = 0; de._SKIPS.clear()` sites become
`de._BOOK = DriftBook()` (or `de._BOOK.reset()` if we add one). Because
`save(path, ..., book=book)` accepts an explicit book, a test can also
hold its own `book = DriftBook()` and assert on `book.applied` /
`book.skips` without touching the module.

### Decision D2 — `_ORIG` stays on the book (folded in)

`_ORIG` moves onto `DriftBook.orig` for a single lifecycle owner
(`load()` → fresh book), with `begin()`/`register()` as the only
mutation entry points. Rationale: it already shares the exact
lifecycle (cleared on load, read by `find_p`, written by clone), so
splitting ownership buys nothing. The price is a handful of
`book.orig[...]` reads in `find_p` paths — mechanical.

## File Impact

| File | Change |
|------|--------|
| `resume-tailoring/scripts/docx_edit.py` | add `DriftBook` (or move to `docx_edit_drift.py` so `docx_edit.py` stays under 1000 lines — *recommended*: keep this spec's changes aligned with the pylint-clean file split); swap all 14 counter mutation sites to method calls; `load`/`save` accept `book=None`; delete all 8 `global` statements |
| `resume-tailoring/scripts/test_docx_edit.py` | replace ~30 direct counter resets with fresh-book/reset calls; assert on book values where readable |
| `resume-tailoring/scripts/docx_edit_cli.py` | no change (CLI only composes editor calls; a CLI-run uses the default module book) |
| docs/README/SKILL | no change (behavior identical) |

If `DriftBook` lives in its own module, it lands *after* the
pylint-clean split so the split sees the module-global version and this
refactor is a clean follow-on.

## Verification

1. `python3 -m unittest test_docx_edit` — full suite green
2. Same-suite coverage of the specific counter behaviors:
   - `test_that_spanning_edit_must_not_count_as_applied`
   - the `DOCX_EDIT_STRICT=1` skip-gate path
   - `element_form_drops` reporting
3. `grep -nE "global " docx_edit.py` → empty
4. Drift sidecar behavior byte-identical against a pre-refactor golden
   run (edit a copy of a sample docx through both, diff the `.docx` and
   `.drift.json`)

## Rollout Notes

- Do **not** start from the lint-suppressed state — this is a
  follow-on to `2026-09-07-pylint-clean-refactor-design.md`; landing it
  will let the `global-statement` file-header suppression on
  `docx_edit.py` be dropped in the same commit that lands this refactor.
- Keep it atomic with the test-file update (the two break together).

## References

- Parent: `2026-09-07-pylint-clean-refactor-design.md` (phase 8+
  suppression pass currently carries `global-statement` for
  `docx_edit.py`)