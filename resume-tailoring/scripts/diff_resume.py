"""Reconcile manual edits a user made to a tailored .docx against a fresh
regenerate from the per-target script, or diff the master against a build.

Usage (Theme Review A's cut set — SKILL Step 3)::

    # One command: the master-vs-build paragraph diff, grouped by role/
    # section header, whitespace-normalized so shifted indices don't noise
    # it up. The CUT list is the theme-review work order.
    python3 scripts/diff_resume.py --cutset "<Name> Master Resume.docx" \
        "<Name> Resume - <Target>.docx"

Usage (reconcile manual user edits against a regenerate)::

    # Auto: regenerate via the tailor script to a temp file, then diff the
    # user's (manually-edited) docx against it. One command — the regen is
    # ephemeral and cleaned up:
    python3 scripts/diff_resume.py --tailor scripts/tailor_<target>.py \\
        "<userName> Resume - <Target>.docx"

    # Manual: if you already have a regenerated copy:
    python3 scripts/diff_resume.py \\
        "<userName> Resume - <Target>.docx" \\
        /tmp/regen.docx

Prints a unified diff of paragraph text (regenerated on the left, user-edited
on the right). Paragraphs whose only change is whitespace/run-splitting are
shown as identical — only real text differences surface.

This is a reading tool, not a writing tool: it never modifies either .docx.
After reviewing the diff, fold confirmed user changes back into the
tailor_<target>.py script so the next regenerate stays reproducible.
"""
# pylint: disable=import-outside-toplevel
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.



import contextlib
import difflib
import importlib.util
import io
import os
import sys
import tempfile

from docx_edit import load, paras, style_and_numid, text_of
from script_args import maybe_help  # noqa: E402  (flat-namespace sibling)

# Block-boundary styles for cut-set grouping (mirrors docx_edit's block
# grammar): a role or section heading starts a new group label.
_CUTSET_BOUNDARY_STYLES = ("CompanyBlock", "SectionHeading", "Heading1", "Heading2")


def _grouped_texts(path):
    """[(group_label, normalized_text)] for every non-empty paragraph.

    The group label is the last role/section heading seen above the
    paragraph, so cut items read in context (which role lost the bullet).
    """
    _root, body, _names, _data, _ = load(path)
    out = []
    label = "(top)"
    for p in paras(body):
        text = " ".join(text_of(p).split())
        style, _numid = style_and_numid(p)
        if text and style in _CUTSET_BOUNDARY_STYLES:
            label = text
        if text:
            out.append((label, text))
    return out


def cutset(master_path, build_path):
    """Print the master-vs-build paragraph cut set (Theme Review A's diff).

    Sessions hand-rolled this diff differently every run (comm -23 on
    prefix dumps, grep -vxF, python set arithmetic) after discovering that
    raw index-based diffs are noise — the prune renumbers everything. This
    normalizes whitespace, compares by text, and groups each side by the
    role or section header above it. A rewritten paragraph appears on BOTH
    sides (old text cut, new text added) — that is the trim/host signal.
    """
    master = _grouped_texts(master_path)
    build = _grouped_texts(build_path)
    build_texts = {text for _label, text in build}
    master_texts = {text for _label, text in master}
    cut = [(label, text) for label, text in master if text not in build_texts]
    added = [(label, text) for label, text in build if text not in master_texts]
    print(f"master {len(master)} paras, build {len(build)} paras — "
          f"{len(cut)} cut, {len(added)} added (whitespace-normalized)")
    print(f"CUT — in the master, not in the build ({len(cut)}): "
          "# theme-review each against the Step-1 brief (SKILL Step 3)")
    for label, text in cut:
        print(f"  [{label[:44]}] {text[:90]}")
    print(f"ADDED — in the build, not in the master ({len(added)}): "
          "# fresh hosts and rewrites")
    for label, text in added:
        print(f"  [{label[:44]}] {text[:90]}")
    if not cut and not added:
        print("(identical: the build carries the master's full paragraph set)")


def texts(path):

    """Extract the visible paragraph texts from a docx."""
    _root, body, _names, _data, _ = load(path)
    return [text_of(p) for p in paras(body)]


def _diff(user_path, regen_path):
    """Print the paragraph-text diff between user-edited and regenerated."""
    user = texts(user_path)
    regen = texts(regen_path)
    print(f"user-edited: {len(user)} paras   regenerated: {len(regen)} paras")
    diff = difflib.unified_diff(
        regen, user,
        fromfile="regen(script)", tofile="user(edited)",
        lineterm="",
    )
    for line in diff:
        print(line)


def _regen_with_tailor(script_path):
    """Run the tailor script (its DST overridden to a temp file) and return
    the path of the freshly regenerated .docx. The temp file is unlinked by
    the caller when done."""
    if not os.path.exists(script_path):
        print(f"Error: tailor script not found: {script_path}", file=sys.stderr)
        sys.exit(2)
    mod_name = os.path.splitext(os.path.basename(script_path))[0]
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fd, tmp = tempfile.mkstemp(suffix=".docx", prefix="regen_")
    os.close(fd)
    os.unlink(tmp)  # the script's shutil.copy(SRC, DST) creates it fresh
    mod.DST = tmp
    with contextlib.redirect_stdout(io.StringIO()):
        mod.main()
    return tmp


def main():

    """Diff-resume CLI entry point."""
    maybe_help(sys.argv[1:], __doc__)
    if len(sys.argv) == 4 and sys.argv[1] == "--cutset":
        cutset(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--tailor":
        script_path, user_path = sys.argv[2], sys.argv[3]
        regen = _regen_with_tailor(script_path)
        try:
            _diff(user_path, regen)
        finally:
            os.unlink(regen)
        return
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    user_path, regen_path = sys.argv[1], sys.argv[2]
    _diff(user_path, regen_path)


if __name__ == "__main__":
    main()
