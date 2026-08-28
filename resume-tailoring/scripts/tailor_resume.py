"""Reference template for a per-target resume-tailoring script.

This is a TEMPLATE, not a tailoring of any specific job. It demonstrates the
subtractive pattern — every primitive you need, in order, with placeholder
content. Copy it to `scripts/tailor_<target>.py` and replace every
`<placeholder>` with choices driven by the job description or recruiter
message from THIS session. Do not carry over tool lists, accuracy notes, or
bullet choices from other targets — each resume customization uses only the
input provided in its own session.

The pattern (see SKILL.md for the full workflow):

1. Rewrite the Summary to lead with the target's core ask.
2. Reorder/retrim Technical Proficiencies so JD-relevant tools lead.
3. Re-anchor the most-recent/senior role intro around ownership and the
   JD's selling points; weave JD-named tools into the role bullet where they
   were actually used (merge, don't append).
4. Compress every role to its most JD-aligned/quantified bullets via `remove`,
   cutting from the oldest roles first (never the most recent).
5. Trim the oldest roles' exhaustive Tools lines to one line each.
6. Drop blank inter-role spacer paragraphs to reclaim vertical space.
7. Save, render the PDF, and iterate until ≤3 pages with a full last page.

Editing order is safe: `find_p` resolves prefixes against each paragraph's
ORIGINAL master text (captured at load), so an earlier edit cannot rewrite
one paragraph's text to start with another target's prefix and collide
mid-run. `save()` prints an applied-vs-skipped summary — verify every edit
applied by running with `DOCX_EDIT_STRICT=1` (exit 2 on any skipped edit)
before rendering.

Re-runnable from the untouched master (after replacing the placeholders):

    cd ~/.pi/agent/skills/resume-tailoring && python3 scripts/tailor_<target>.py

Accuracy: mirror the JD's verbs, but never overclaim. "Designed from scratch"
is for greenfield work; a refactor is "refactored" or "re-architected". Never
fabricate a bullet for a tool the user hasn't used — omit it and flag it to
the user. See SKILL.md → Accuracy section.
"""

import shutil

from docx_edit import (
    load, save, paras, find_p, set_text, set_labeled, replace_text,
    remove, remove_empty,
)

SRC = "<userName> Master Resume.docx"
DST = "<userName> Resume - <Target>.docx"


def _drop(body, ps, prefixes):
    """Remove paragraphs whose text starts with any prefix; refresh `ps`."""
    for prefix in prefixes:
        remove(body, find_p(ps, prefix))
        ps = paras(body)


def main():
    shutil.copy(SRC, DST)
    root, body, names, data, _ = load(DST)
    ps = paras(body)

    # ------------------------------------------------------------------ #
    # 1. SUMMARY — lead with the JD's core ask. Mirror the employer's
    #    language and the user's selling points for THIS role. ~4-5
    #    sentences. Use set_text (preserves the first run's formatting).
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "Results-driven Staff engineer specializing"),
        "<Summary that leads with the JD's core ask, mirroring its language. "
        "Keep verbs truthful — see SKILL.md Accuracy section.>",
    )

    # ------------------------------------------------------------------ #
    # 2. TECHNICAL PROFICIENCIES — lead with the JD's deep-proficiency
    #    languages; retrim each line so JD-relevant tools lead. Use
    #    set_labeled (NOT set_text) on these "Label: values" lines, or the
    #    whole line collapses to bold.
    # ------------------------------------------------------------------ #
    set_labeled(
        find_p(ps, "Programming Languages:"),
        "Programming Languages: ",
        "<languages, most JD-relevant first>",
    )

    # ------------------------------------------------------------------ #
    # 3. MOST-RECENT / SENIOR ROLE — carries the most weight. Re-anchor its
    #    intro around ownership and the JD's selling points. Where new
    #    content overlaps an existing bullet, MERGE rather than append.
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "<prefix of the senior-role intro bullet>"),
        "<Re-anchored intro emphasizing ownership and THIS JD's selling points.>",
    )
    _drop(body, ps, [
        "<prefix of an off-theme senior-role bullet to drop>",
        # ...
    ])

    # ------------------------------------------------------------------ #
    # 4. COMPRESS OLDER ROLES — drop the weakest bullets from roles 5+ years
    #    back first; keep the 2-3 with hard numbers or framework-ownership
    #    signal. Never cut the most-recent role to make room — reallocate.
    # ------------------------------------------------------------------ #
    # _drop(body, ps, [
    #     "<oldest-role bullet to drop>",
    #     # ...
    # ])

    # ------------------------------------------------------------------ #
    # 5. RECLAIM SPACE — trim the oldest roles' exhaustive Tools lines to
    #    one line each (each wraps to two rendered lines), keeping the 6-8
    #    most JD-relevant tools plus the stack's signature one. Normalize
    #    the label to "Tools & Technologies:" and fix proper-noun casing
    #    (GitHub, HIPAA).
    # ------------------------------------------------------------------ #
    trims = [
        ("<oldest-role Tools-line prefix>",
         "Tools & Technologies: ",
         "<6-8 most JD-relevant tools, one line>"),
        # ...
    ]
    for prefix, label, value in trims:
        set_labeled(find_p(ps, prefix), label, value)

    # ------------------------------------------------------------------ #
    # 6. SURGICAL FIXES — grammar, casing, or a word swap on a kept bullet
    #    without rewriting the whole paragraph. Preserves each run's
    #    formatting (does not collapse a multi-run proficiency line).
    # ------------------------------------------------------------------ #
    # replace_text(find_p(ps, "<prefix of a kept bullet>"), "Github", "GitHub")
    # replace_text(find_p(ps, "<prefix of a kept bullet>"), "API's", "APIs")

    # Drop blank inter-role spacer paragraphs to reclaim vertical space.
    remove_empty(body)

    save(DST, root, names, data)
    print("WROTE", DST)


if __name__ == "__main__":
    main()
