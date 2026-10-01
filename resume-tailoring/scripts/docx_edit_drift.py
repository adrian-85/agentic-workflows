"""Drift bookkeeping for docx_edit.save().

Split from docx_edit.py (same reason as docx_edit_gate.py) so the editor
core stays focused and under the module-size lint cap with headroom for
future work. This module is a LEAF: it imports only the stdlib and never
docx_edit, so docx_edit can import it at module load with no cycle.

Two concerns live here, both serving save()'s drift reporting:

* ``DriftBook`` — the IN-MEMORY edit accounting between load() and the
  next save(): applied/skipped/element-form counters plus the
  original-text map (id(p) -> (p, text at load/clone time)) that find_p
  resolves prefixes against. It replaces docx_edit's former module-level
  mutable counters; docx_edit keeps a module-default ``_BOOK`` and
  tests rebind a fresh book instead of resetting globals.
* ``drift_sidecar`` — the ``<path>.drift.json`` sidecar: the per-script
  applied-edit baseline, the master sha256 (MASTER CHANGED detection),
  and the folds-must-be-additive paragraph count check. See
  docx_edit.save()'s docstring for the behavioral contract; only the
  bookkeeping lives here.
"""

import hashlib
import json
import os
import pathlib
import sys
from dataclasses import dataclass

# OOXML main namespace — duplicated from docx_edit (a one-line constant)
# so this module stays a leaf: importing docx_edit for one string would
# create the import cycle the split exists to avoid.
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class DriftMeta:
    """Drift-tracking metadata for save(): the calling script's drift_key
    and the optional master ``src`` path (arms the deliverable gate +
    master-changed detection)."""
    drift_key: str | None = None
    src: str | None = None


def drift_sidecar(path, drift, applied, root):
    """Load/update the ``<path>.drift.json`` sidecar: record the applied
    edit count + master sha + paragraph count, warn on drift or a changed
    master, and enforce the fold-additive rule. Returns ``master_changed``
    (bool) so the caller can run the auto-strict gate."""
    drift_key = drift.drift_key if drift else None
    if drift_key is None:
        drift_key = os.path.basename(sys.argv[0]).rsplit(".", 1)[0]
    src = drift.src if drift else None
    drift_path = path + ".drift.json"
    baseline = {}
    if os.path.exists(drift_path):
        try:
            baseline = json.loads(
                pathlib.Path(drift_path).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            baseline = {}
    master_sha = None
    if src:
        master_sha = hashlib.sha256(
            pathlib.Path(src).read_bytes()).hexdigest()
    prev = baseline.get(drift_key)
    prev_edits = prev.get("edits") if isinstance(prev, dict) else prev
    prev_sha = prev.get("master_sha") if isinstance(prev, dict) else None
    prev_paras = prev.get("paragraphs") if isinstance(prev, dict) else None
    if prev is not None and prev_edits != applied:
        if prev_sha and master_sha and prev_sha != master_sha:
            print(
                f"DRIFT: {drift_key} expected {prev_edits} edits (last "
                f"recorded run) but applied {applied}. Two possible causes:\n"
                f"  (a) this script's edit set changed intentionally mid-"
                f"authoring — no action needed: the baseline updates "
                f"automatically (warn-once);\n"
                f"  (b) the master changed under a finished script — see "
                f"the master-change notice below and run 'diff_resume.py "
                f"--tailor' before reusing it.\n"
                f"The blocking gate for a stopped-matching edit remains "
                f"the skipped-edit check.",
                file=sys.stderr,
            )
        else:
            # The master is unchanged, so cause (b) is impossible: the
            # edit set itself changed — one line, not the two-cause block.
            print(
                f"DRIFT: {drift_key} edit set changed ({prev_edits} -> "
                f"{applied} applied); baseline rebaselined (warn-once)",
                file=sys.stderr,
            )
    master_changed = bool(prev_sha and master_sha and prev_sha != master_sha)
    if master_changed:
        print(
            f"MASTER CHANGED: {src} differs from the master of the last "
            f"run of {drift_key} — prefixes may have drifted or edits may "
            f"now land on rewritten text. Re-dump `docx_edit.py {src!r} "
            f"--prefixes` and run diff_resume.py --tailor before "
            f"rendering. Expected if you folded content into the master "
            f"this session; this run is auto-strict — any skipped edit " f"now exits 2.",
            file=sys.stderr,
        )
    para_count = len(list(root.iter(f"{W}p")))
    if src is None and prev_paras is not None and para_count < prev_paras:
        print(
            f"FOLD CHECK: {drift_key} saved {prev_paras} paragraphs "
            f"last time but now has {para_count} — content was removed. "
            "Folds must be ADDITIVE only: new bullets (clone_after), "
            "proficiency additions, and in-place appends — never " "removals (SKILL Step 13).",
            file=sys.stderr,
        )
    baseline[drift_key] = {"edits": applied, "master_sha": master_sha,
                           "paragraphs": para_count}
    try:
        pathlib.Path(drift_path).write_text(
            json.dumps(baseline, indent=1), encoding="utf-8")
    except OSError:
        pass  # sidecar is best-effort; never fails the save
    return master_changed


class DriftBook:
    """Accumulates edit accounting between load() and the next save().

    save() reads a snapshot of these values to print its end-of-run
    report, then the book resets for the next session. DO NOT rely on
    the counter values after save() has snapshotted the book.
    """

    def __init__(self) -> None:
        self.applied = 0
        self.skips: list[str] = []
        self.element_form_drops = 0
        # id(p) -> (paragraph, text as of load()/clone time). Cleared by
        # load() (never save()) — paragraphs stay alive via `body` for the
        # run, so stale entries cannot clash.
        self.orig: dict[int, tuple] = {}

    # -- mutator entry points (called by docx_edit's mutators) --
    def record_applied(self) -> None:
        """Count one landed edit."""
        self.applied += 1

    def record_skip(self, prefix_or_label: str) -> None:
        """Record one skipped edit (reported by save(); strict fails)."""
        self.skips.append(prefix_or_label)

    def record_element_form_drop(self) -> None:
        """Count one drop-family call given an element, not a prefix."""
        self.element_form_drops += 1

    # -- original-text registration (replaces the _ORIG map) --
    def begin(self, p, text: str) -> None:
        """load(): record a paragraph's ORIGINAL text for later resolution."""
        self.orig[id(p)] = (p, text)

    def register(self, p, text: str) -> None:
        """clone_after(): register a NEW paragraph so find_p can resolve it."""
        self.orig[id(p)] = (p, text)

    def snapshot(self) -> tuple[int, list[str], int]:
        """save(): read + reset the counters atomically (for the report).

        Returns (applied, skips copy, element_form_drops) and leaves the
        book zeroed; ``orig`` is NOT spent — the load()→save() window may
        still resolve prefixes after a snapshot.
        """
        applied = self.applied
        skips = list(self.skips)
        element_form = self.element_form_drops
        self.applied = 0
        self.skips.clear()
        self.element_form_drops = 0
        return applied, skips, element_form
