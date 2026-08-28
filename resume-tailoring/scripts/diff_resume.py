"""Reconcile manual edits a user made to a tailored .docx against a fresh
regenerate from the per-target script.

The skill keeps a re-runnable `tailor_<target>.py` so edits are diff-able and
reproducible. But the user often does a final manual pass directly in the .docx
(grammar tweaks, dropping a term they don't want to claim, adding a JD-required
term only they know they have). Those edits live in the binary .docx and are
invisible until you diff them back against what the script produces.

Usage::

    # Regenerate the script's output to a temp file, then diff the user's
    # (manually-edited) docx against it to see exactly what the user changed:
    python3 scripts/diff_resume.py \\
        "<userName> Resume - <Target>.docx" \\
        /tmp/regen.docx

    # To produce /tmp/regen.docx, point the tailor script's DST at a temp path:
    #   import tailor_<target>; tailor_<target>.DST='/tmp/regen.docx'
    #   tailor_<target>.main()

Prints a unified diff of paragraph text (regenerated on the left, user-edited
on the right). Paragraphs whose only change is whitespace/run-splitting are
shown as identical — only real text differences surface.

This is a reading tool, not a writing tool: it never modifies either .docx.
After reviewing the diff, fold confirmed user changes back into the
tailor_<target>.py script so the next regenerate stays reproducible.
"""

import difflib
import sys

from docx_edit import load, paras, text_of


def texts(path):
    root, body, _names, _data, _ = load(path)
    return [text_of(p) for p in paras(body)]


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    user_path, regen_path = sys.argv[1], sys.argv[2]
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


if __name__ == "__main__":
    main()
