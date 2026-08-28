"""Reconcile manual edits a user made to a tailored .docx against a fresh
regenerate from the per-target script.

The skill keeps a re-runnable `tailor_<target>.py` so edits are diff-able and
reproducible. But the user often does a final manual pass directly in the .docx
(grammar tweaks, dropping a term they don't want to claim, adding a JD-required
term only they know they have). Those edits live in the binary .docx and are
invisible until you diff them back against what the script produces.

Usage::

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

import contextlib
import difflib
import importlib.util
import io
import os
import sys
import tempfile

from docx_edit import load, paras, text_of


def texts(path):
    root, body, _names, _data, _ = load(path)
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