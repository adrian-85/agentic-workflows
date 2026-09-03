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
4. Compress every role to its most JD-aligned/quantified bullets via `drop`,
   cutting from the oldest roles first (never the most recent).
5. Trim the oldest roles' exhaustive Tools lines to one line each.
6. Drop blank inter-role spacer paragraphs to reclaim vertical space.
7. Save, render the PDF, and iterate until ≤3 pages with a full last page.

Editing order is safe: `find_p` resolves prefixes against each paragraph's
ORIGINAL master text (captured at load), so an earlier edit cannot rewrite
one paragraph's text to start with another target's prefix and collide
mid-run. `find_p` also collapses smart punctuation (curly quotes/dashes)
and supports `after=<paragraph>` / `nth=N` for duplicate job titles (see
docstring). `save()` prints an applied-vs-skipped summary — verify every
edit applied by running with `DOCX_EDIT_STRICT=1` (exit 2 on any skipped
edit) before rendering. It also auto-maintains a <DST>.drift.json baseline
keyed by this script's name: if a re-run's applied-edit count differs from
the last run (an edit was added/removed or stopped matching the master),
it warns (rebaseline so it fires once per change) — the blocking gate
for a stopped-matching edit is the skipped-edit check (exit 2 under strict).

Re-runnable from the untouched master (after replacing the placeholders):

    cd ~/.pi/agent/skills/resume-tailoring && python3 scripts/tailor_<target>.py

Verification is mechanical, not a habit:
- render_pdf.sh runs scripts/validate_resume.py on the output and REFUSES to
  render a structurally broken docx (orphan job titles, company blocks
  without titles, orphaned content after a Tools line).
- The noise-free cut loop is driven by the tools, not extra renders:
  1. `scripts/measure_resume.py <DST> 2 --protect "<JD-critical phrase>"`
     (repeat --protect for every JD ask that must never be cut). Its DROP
     PLAN names the EXACT bullets to drop as copy-pasteable find_p lines
     (weakest-first; quantified/theme-protected bullets excluded).
  2. Paste those prefixes into a `drop(body, [...])` call, re-run script,
     re-measure once to confirm, render once to verify. No cut-render-cut.
- validate_resume.py also cross-checks quantified claims against the master
  and the Summary's "N+ years" claim against the visible role-date span.
- When the JD specifies fewer years than the candidate has, apply Step 3
  seniority alignment (SKILL.md): eliminate entire oldest roles in contiguous
  gapless blocks, reduce "N years" statements, confirm with the user, and
  record approval with RESUME_VALIDATE_ARGS="--jd-years <N> --seniority-approved"
  — the render is blocked without it.

Accuracy: mirror the JD's verbs, but never overclaim. "Designed from scratch"
is for greenfield work; a refactor is "refactored" or "re-architected". Never
fabricate a bullet for a tool the user hasn't used — omit it and flag it to
the user. See SKILL.md → Accuracy section.
"""

import shutil

from docx_edit import (
    load, save, paras, find_p, set_text, set_labeled, replace_text,
    merge_into, drop, drop_role, drop_section, remove_empty,
)

SRC = "<userName> Master Resume.docx"
DST = "<userName> Resume - <Target>.docx"


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
        find_p(ps, "<prefix of the Summary paragraph>"),
        "<Summary that leads with the JD's core ask, mirroring its language. "
        "Keep verbs truthful — see SKILL.md Accuracy section.>",
    )

    # ------------------------------------------------------------------ #
    # 1b. SENIORITY ALIGNMENT — ONLY when the JD years are BELOW the
    #     candidate's (else skip this block entirely). Full rules:
    #     SKILL.md Step 3. Shorthand: drop ENTIRE oldest roles in contiguous
    #     gapless blocks; reduce "N years" statements to the visible span;
    #     keep Education when the JD has an "OR degree" clause; confirm with
    #     the user first. What-if the resulting span with measure's
    #     --simulate BEFORE editing. Enforcement: validate_resume.py blocks
    #     the render on unapproved role elimination — record approval via
    #     RESUME_VALIDATE_ARGS="--seniority-approved" (--jd-years optional).
    # ------------------------------------------------------------------ #
    # drop_role(body, "<oldest-role company header prefix>")   # whole role
    # drop_role(body, "<second-oldest-role company prefix>")
    # drop_section(body, "Education")          # if the degree is not evidence
    # set_text(find_p(ps, "<Summary>"), "...N+ years...")

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
    #    Use merge_into (rewrites the target AND removes the source in one
    #    op) so a merge can never leave the source's old text as
    #    near-duplicate residue:
    #
    #    keep = find_p(ps, "<prefix of the bullet to keep>")
    #    absorb = find_p(ps, "<prefix of the overlapping bullet>")
    #    merge_into(body, keep, absorb, "<merged text>")
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "<prefix of the senior-role intro bullet>"),
        "<Re-anchored intro emphasizing ownership and THIS JD's selling points.>",
    )
    ps = drop(body, [
        "<prefix of an off-theme senior-role bullet to drop>",
        # ...
    ])

    # ------------------------------------------------------------------ #
    # 4. COMPRESS OLDER ROLES — drop the weakest bullets from roles 5+ years
    #    back first; keep the 2-3 with hard numbers or framework-ownership
    #    signal. Never cut the most-recent role to make room — reallocate.
    # ------------------------------------------------------------------ #
    # ps = drop(body, [
    #     "<oldest-role bullet to drop>",
    #     # ...
    # ])

    # ------------------------------------------------------------------ #
    # 5. RECLAIM SPACE — trim the oldest roles' exhaustive Tools lines to
    #    one line each, sized to the MEASURED wrap budget (measure's TOOLS
    #    LINES THAT WRAP prints "value is N chars, wraps after ~M — cut
    #    ~N-M chars"; the proportional font makes a fixed tool count
    #    unreliable). Normalize
    #    the label to "Tools & Technologies:" and fix proper-noun casing
    #    (GitHub, HIPAA).
    # ------------------------------------------------------------------ #
    trims = [
        # Each prefix is the TOOLS LINE's own text start (not the company
        # header — see the --prefixes dump for each line's text). Trim to
        # the measured wrap budget (TOOLS LINES THAT WRAP in measure output).
        ("<Tools-line's own unique text start, e.g. 'Tools & Technologies: MVC,'>",
         "Tools & Technologies: ",
         "<tools trimmed to the measured wrap budget, one line>"),
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

    # save() records an applied-edit baseline in <DST>.drift.json keyed by
    # this script's name — the first run establishes it, later runs warn
    # if the count drifts (an edit was added/removed or stopped matching
    # the master). The blocking gate for a stopped-matching edit is the
    # skipped-edit check (exit 2 under strict). No literal to maintain. render_pdf.sh also runs validate_resume.py on the output
    # and refuses to render a docx with structural errors (orphan job
    # titles, company blocks without titles).
    save(DST, root, names, data, src=SRC)
    print("WROTE", DST)


if __name__ == "__main__":
    main()
