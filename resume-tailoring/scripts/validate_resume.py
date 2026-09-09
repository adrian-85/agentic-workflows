"""Lint a (tailored) resume for structural and claim-consistency errors.

Catches the error classes tailoring sessions actually hit:

1. STRUCTURE — orphan paragraphs left by subtractive cuts:
   - a job-title paragraph with no preceding company block (a company
     header was removed but its title stayed, e.g. Acme / Globex
     dangles), or a company block followed by no job title
   - content after a role's Tools line with no new company block (a
     company+title were removed but later bullets survived)
   - ROLE INTEGRITY (needs the master): whole-role removals must be whole.
     A kept role must retain its job title and at least one bullet; a
     removed role must leave no surviving bullet (header dropped but
     bullets kept = orphaned content that dangles under another role)
   - near-duplicate bullets: a merge that left the source's old text beside
     the rewritten target (long shared substring => likely residue)

2. CLAIMS — truthfulness drift between the document and the master:
   - quantified claims (%, hours, minutes) on kept bullets that do not
     appear anywhere in the master (possible fabrication)
   - the Summary's "N+ years" claim vs the span of the visible role dates
     (e.g. claiming "15 years" while only 2019-2026 is shown)
   - ANY other "N years" statement (not just the Summary) that outruns the
     visible timeline
   - `--jd-years N`: compare the visible span against the JD's "N+ years"
     ask — warns if the resume shows fewer years than the JD requires
     (underqualified), and notes a large overage so the agent can offer the
     Step 3 seniority-alignment option (eliminate oldest roles in
     contiguous blocks + reduce years statements) when it is relevant
   - JD-TITLE ALIGNMENT (`--jd <JD.txt>`): when the resume headline (the
     title line under the name) is MORE SENIOR than the JD's named title,
     warns to apply SKILL Step 4 (set the top title to the JD's exact
     title and level the Summary's echo). Advisory, never blocking: the
     JD-title extraction and the seniority ladder are heuristics, and a
     posting may use a generic title for a senior role
   - SENIORITY GATE: when whole roles were eliminated (visible span >= 2
     years shorter than the master), the run is a blocking error unless
     `--seniority-approved` records the user's approval — and the token's
     authority must come from OUTSIDE the agent: the user's chat reply or
     pre-authorization in the original request. An agent passing the token
     itself is not an approval, it is a bypass. This makes the Step 3 "ask
     the user first" rule a gate: render_pdf.sh will not produce a PDF
     from a shortened timeline without the approval token.
   - EDUCATION GATE (`--jd <JD.txt>`): Step 3.4's predicates, mechanical.
     A JD that requires a degree blocks the render when Education was
     dropped (`--education-approved` records a USER-GRANTED override, same
     origin rule as the seniority token). Under an
     'or equivalent' clause the clause is satisfied by experience only
     when the visible span exceeds the ask; at/below the ask, dropping
     Education warns (the clause is load-bearing — keep the section).

3. PUNCTUATION — periods and commas only. Enforced on the Summary and the
   job-history prose (role intros, bullets, tools lines): no em dashes,
   double hyphens (--), semicolons, colons, ellipses (...), or non-date
   en dashes. Single hyphens
   in compound words and date-range en dashes are exempt; structural lines
   (company headers, job titles) and out-of-region sections
   (proficiencies, certifications, education) are not scanned.

4. BULLET CAP — every role keeps at most MAX_BULLETS_PER_ROLE (8) bullets,
   regardless of tenure, page target, or accomplishment (SKILL Step 8).
   The cap applies to tailored resumes; when the input IS the master it is
   advisory only (the master intentionally keeps everything).

5. TEXT INTEGRITY — generated-prose mangling artifacts. Enforced on the
   same paragraphs as PUNCTUATION: non-ASCII characters that are not
   Latin letters or standard typographic marks (a real session had a
   mangled CJK char replace " and " inside a bullet), doubled punctuation
   (,, / ;;), and doubled words ("the the"). These are the artifact
   classes that reach the Summary and bullets through generated text;
   catching them mechanically replaces a user's manual proofread.

6. GUIDANCE — readability signals the agent should act on (advisory).
   Word-count cap — no prose paragraph or individual bullet over 40 words
   (<=40 acceptable; SKILL Step 4) — and sections inserted between the
   Summary and Technical Proficiencies (SKILL Step 5 forbids this). These
   are warnings, not blocking errors — the agent may have a reason to
   deviate, but the validator flags the deviation so it cannot go unnoticed.

Structural, punctuation, text-integrity, bullet-cap, seniority-gate, and
education-gate errors exit 2 — render_pdf.sh refuses to render.
Near-duplicate, guidance, and claim warnings exit 0 unless --strict (exit 1).

The master file is auto-detected as the "X Master Resume.docx" next to the
input; override with --master <path>.

Usage:
    python3 scripts/validate_resume.py <resume.docx> [--strict] [--master p]
    python3 scripts/validate_resume.py <resume.docx> --jd-years 5 [--master p]
    python3 scripts/validate_resume.py <resume.docx> --jd <JD.txt> [--jd-years 5] [--education-approved] [--master p]  # pylint: disable=line-too-long
"""

# pylint: disable=wrong-import-position,import-outside-toplevel
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.

# pylint: disable=unused-import
# measure_resume/validate_resume is the legacy RE-EXPORT shim: it preserves
# the full mr.*/vr.* surface (imports that appear unused are the re-export
# contract). Keep this header ONLY while the flat-namespace consumers
# resolve these names through the shim.



import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402
from script_args import parse_flag as _parse_flag  # noqa: E402
from script_args import extract_flag as _extract_flag  # noqa: E402
from script_args import extract_flag_all as _extract_flag_all  # noqa: E402
from script_args import MAX_WORDS  # noqa: E402  (single source of truth)


SENIORITY_GATE_YEARS = 2.0      # visible-span shrink (vs master) that requires approval


NUM_CLAIM = re.compile(r"\d+(?:\.\d+)?\s*(?:%|hours?|minutes?)", re.I)


from validate_resume_checks import (
    DATE_RANGE,
    DUP_K,
    LIST_STYLES,
    MAX_BULLETS_PER_ROLE,
    PARA_WORD_CAP,
    SUMMARY_STYLE,
    TITLE_STYLE,
    YEARS_RE,
    _ASCII_OK_CHARS,
    _TOOLS_LABEL_RE,
    _bullet_cap_errors,
    _claim_years,
    _is_bullet,
    _is_tools,
    _near_duplicates,
    _prose_paragraphs,
    _punctuation_errors,
    _readability_guidance,
    _region,
    _structural_errors,
    _summary_paragraph,
    _text_integrity_errors,
    _word_count)

from validate_resume_master import (
    DEGREE_RE,
    EQUIV_CLAUSE_RE,
    _company_headers,
    _education_gate,
    _find_master,
    _has_education,
    _load_master_body,
    _master_span,
    _master_texts,
    _norm_text,
    _role_groups,
    _role_integrity_errors)

@dataclass
class TreeOptions:
    """The validate-tree keyword options, bundled so validate_tree's
    signature stays small (master_path/jd_path/jd_years/*_approved/protect/
    max_words). All default to the same values the old keyword signature
    used."""

    master_path: str | None = None
    jd_path: str | None = None
    jd_years: float | None = None
    seniority_approved: bool = False
    education_approved: bool = False
    protect: tuple = ()
    max_words: int = MAX_WORDS


@dataclass
class _Notes:
    """Threads the advisory/guidance note lists through the check helpers
    (claim_notes, guidance_notes) without multi-arg signatures."""

    claim: list = field(default_factory=list)      # (severity, message)
    guidance: list = field(default_factory=list)   # (severity, message)


def validate_tree(path, body, opts=None):
    """Run every check against an ALREADY-LOADED document tree.

    Returns ``{"blocking": int, "warnings": int, "lines": [str]}`` — the
    blocking-error count, the advisory-warning count, and the full report
    lines. The CLI (main) prints the lines and maps the counts to exit
    codes; ``docx_edit.save``'s deliverable gate calls this in memory
    BEFORE writing the .docx, so a gated state never becomes a file on
    disk (the render gate alone is bypassable — the user can convert the
    .docx themselves).

    ``path`` locates the master for the claims/role-integrity/seniority
    checks when ``master_path`` is None (pass ``src`` from save()). The
    education gate runs only when ``jd_path`` is given; ``*_approved``
    record user-granted overrides (never self-granted).
    """
    opts = opts if opts is not None else TreeOptions()
    master_path = opts.master_path
    jd_path = opts.jd_path
    jd_years = opts.jd_years
    seniority_approved = opts.seniority_approved
    max_words = opts.max_words
    region = _region(body)
    summary = _summary_paragraph(body)

    errors = _structural_errors(region)
    punct_errors = _punctuation_errors(region, summary)
    integrity_errors = _text_integrity_errors(region, summary)
    dups = list(_near_duplicates(region))

    # Bullet cap (SKILL Step 8): every role within MAX_BULLETS_PER_ROLE.
    # The cap applies to TAILORED resumes; when the input IS the master it
    # is advisory only — the master intentionally keeps everything.
    is_master_input = path.endswith("Master Resume.docx")
    cap_errors = [] if is_master_input else _bullet_cap_errors(region)

    # Whole-resume word cap (SKILL Steps 3/8): blocking for tailored
    # resumes, exempt for the master, same as the bullet cap above.
    word_count = _word_count(body)
    word_errors = []
    if max_words and not is_master_input and word_count > max_words:
        word_errors.append(
            f"{word_count} words exceeds the {max_words}-word cap by "
            f"{word_count - max_words} — cut content (JD-driven, Step 8), "
            "do not shrink fonts")

    # Visible timeline span (shared with measure_resume.py): the number a
    # recruiter compares against the JD's "N+ years" ask. Everything below
    # that checks claims against this span.
    first, last = mr._visible_span(_company_headers(body))
    span = (last - first) if (first is not None and last is not None) else None

    claim_notes = []  # (severity, message); severity in warn|ok|note
    guidance_notes = _readability_guidance(body, summary, region=region,
                                           master_input=is_master_input)

    # Education gate (Step 3.4, needs --jd): a degree-requiring JD blocks
    # the render when the section was dropped (--education-approved
    # records the override); under an 'or equivalent' clause the clause is
    # load-bearing only when the visible span does not exceed the ask.
    notes = _Notes()
    notes.claim = claim_notes
    notes.guidance = guidance_notes
    try:
        education_errors, education_notes = _jd_checks(
            jd_path, body, span, opts, notes)
    except _JdBlocking as exc:
        return exc.args[0]
    # Claims: numbers vs master.
    master_path = master_path or _find_master(path)
    master_texts = _master_texts(master_path)
    master_blob = " ".join(master_texts) if master_texts is not None else None

    # Whole-role integrity (needs the master): kept roles keep title+bullets,
    # removed roles leave no surviving bullets (the orphaned-content failure).
    errors.extend(_role_integrity_errors(master_path, body))

    # Seniority gate (Step 3 enforcement): if whole roles were eliminated
    # (visible span shrank >= SENIORITY_GATE_YEARS vs the master), the run
    # is a blocking error unless --seniority-approved records the user's
    # approval. This turns "ask the user first" into a gate — the PDF cannot
    # be produced from a shortened timeline without the approval token.
    seniority_errors = []
    master_first, master_last = _master_span(master_path)
    master_span = (
        (master_last - master_first)
        if (master_first is not None and master_last is not None)
        else None
    )
    if master_span is not None and span is not None:
        shrink = master_span - span
        if shrink >= SENIORITY_GATE_YEARS:
            if not seniority_approved:
                seniority_errors.append(
                    f"whole-role elimination detected: visible span "
                    f"~{span:.1f}y is ~{shrink:.1f}y shorter than the master "
                    f"(~{master_span:.1f}y). The seniority-alignment decision "
                    f"belongs to the USER (SKILL Step 3): approval may come "
                    f"only from their chat reply or from pre-authorization in "
                    f"the original request — do NOT pass --seniority-approved "
                    f"on your own authority. Finish the .docx, present the "
                    f"proposed span with the numbers, and hand the user the "
                    f"render command; the PDF stays blocked until they "
                    f"approve."
                )
            else:
                claim_notes.append((
                    "ok",
                    f"seniority alignment approved: ~{shrink:.1f}y of oldest "
                    f"roles removed (visible ~{span:.1f}y vs master "
                    f"~{master_span:.1f}y)",
                ))

    if master_blob is not None:
        for p in region:
            if not _is_bullet(p):
                continue
            for m in NUM_CLAIM.finditer(de.text_of(p)):
                tok = m.group(0).strip()
                if tok not in master_blob:
                    claim_notes.append((
                        "warn",
                        f"quantified claim {tok!r} on a kept bullet is absent "
                        f"from the master — possible fabrication: "
                        f"{de.text_of(p)[:70]!r}",
                    ))
    else:
        claim_notes.append((
            "note",
            "no master found next to the input (looking for '* Master "
            "Resume.docx'); skipping the quantified-claims check and the "
            "seniority gate — pass "
            "--master <path> to enable it",
        ))

    # Claims: every "N years" statement must not outrun the visible
    # timeline. Step 3's seniority alignment reduces years claims when work
    # is eliminated; this makes that mechanical for the Summary AND any
    # other paragraph.
    if summary is not None:
        claim = _claim_years(de.text_of(summary))
        if claim is not None and span is not None:
            if claim > span + 1.0:
                claim_notes.append((
                    "warn",
                    f"summary claims ~{claim} years but the visible timeline "
                    f"spans ~{span:.1f} years ({first:.0f}-{last:.0f}) "
                    f"— shorten the claim or restore roles",
                ))
            else:
                claim_notes.append((
                    "ok",
                    f"summary claims ~{claim} years; visible timeline spans "
                    f"~{span:.1f} years (start {first:.0f}) — OK",
                ))
    if span is not None:
        for p in de.paras(body):
            if p is summary:
                continue  # handled above with a specific message
            t = de.text_of(p)
            for m in YEARS_RE.finditer(t):
                if int(m.group(1)) > span + 1.0:
                    claim_notes.append((
                        "warn",
                        f"years claim {m.group(0)!r} ({int(m.group(1))} "
                        f"years) exceeds the visible timeline (~{span:.1f} "
                        f"years): {t[:70]!r}",
                    ))

    # Claims: optional JD feedback. --jd-years N compares the visible span
    # against the JD's years ask. Under -> warn (underqualified); far over
    # -> advisory note (for a mid-level title, consider trimming the oldest
    # roles; a degree-substitution clause can complement the shorter span).
    if jd_years is not None and span is not None:
        if span < jd_years - 1.0:
            claim_notes.append((
                "warn",
                f"resume shows ~{span:.1f} years, below the JD's "
                f"{jd_years:g}+ years — underqualified; restore roles or "
                f"reconsider the resume's framing",
            ))
        elif span > jd_years + 3.0:
            claim_notes.append((
                "note",
                f"resume shows ~{span:.1f} years vs the JD's {jd_years:g}+ — "
                f"well above the ask; for a mid-level title consider "
                f"trimming the oldest roles to align (see SKILL Step 3; a "
                f"degree/education-substitution clause in the JD can "
                f"complement the shorter span)",
            ))
        else:
            claim_notes.append((
                "ok",
                f"resume shows ~{span:.1f} years vs the JD's {jd_years:g}+ "
                f"— aligned",
            ))

    # Build the report lines (returned; the CLI prints them, the save-time
    # deliverable gate surfaces only the blocking ones).
    ctx = {
        "errors": errors, "punct_errors": punct_errors,
        "integrity_errors": integrity_errors, "dups": dups,
        "cap_errors": cap_errors, "word_errors": word_errors,
        "word_count": word_count, "max_words": max_words,
        "is_master_input": is_master_input,
        "seniority_errors": seniority_errors, "jd_path": jd_path,
        "education_errors": education_errors,
        "education_notes": education_notes,
        "guidance_notes": guidance_notes, "claim_notes": claim_notes,
    }
    return _assemble_report(ctx)


def _assemble_report(ctx):
    """Assemble the validator's sectioned report from the computed checks.

    ``ctx`` mirrors validate_tree's computation locals (errors, punct_errors,
    integrity_errors, dups, cap_errors, word_errors, word_count, max_words,
    is_master_input, seniority_errors, jd_path, education_errors,
    education_notes, guidance_notes, claim_notes). Returns the full
    result dict (blocking/warnings/lines)."""
    errors = ctx["errors"]
    punct_errors = ctx["punct_errors"]
    integrity_errors = ctx["integrity_errors"]
    dups = ctx["dups"]
    cap_errors = ctx["cap_errors"]
    word_errors = ctx["word_errors"]
    word_count = ctx["word_count"]
    max_words = ctx["max_words"]
    is_master_input = ctx["is_master_input"]
    seniority_errors = ctx["seniority_errors"]
    jd_path = ctx["jd_path"]
    education_errors = ctx["education_errors"]
    education_notes = ctx["education_notes"]
    guidance_notes = ctx["guidance_notes"]
    claim_notes = ctx["claim_notes"]
    # Build the report lines (returned; the CLI prints them, the save-time
    # deliverable gate surfaces only the blocking ones).
    lines = []
    lines.append("== STRUCTURE ==")
    for e in errors:
        lines.append(f"  ERROR: {e}")
    if not errors:
        lines.append("  ok (all roles have a company + job title; no orphan content)")
    lines.append("== PUNCTUATION ==")
    for e in punct_errors:
        lines.append(f"  ERROR: {e}")
    if not punct_errors:
        lines.append("  ok (periods and commas only — no em dashes, double hyphens, "
              "semicolons, colons, or ellipses in Summary/job-history prose)")
    lines.append("== TEXT INTEGRITY ==")
    for e in integrity_errors:
        lines.append(f"  ERROR: {e}")
    if not integrity_errors:
        lines.append("  ok (no mangling artifacts — clean ASCII/Latin prose, no "
              "doubled punctuation or words)")
    lines.append("== SENIORITY ==")
    for e in seniority_errors:
        lines.append(f"  ERROR: {e}")
    if not seniority_errors:
        lines.append("  ok")
    lines.append("== BULLET CAP ==")
    if is_master_input:
        lines.append("  note: input is a master — the per-role cap applies to "
              "tailored resumes only (the master keeps everything)")
    else:
        for e in cap_errors:
            lines.append(f"  ERROR: {e}")
        if not cap_errors:
            lines.append(f"  ok (every role within the hard cap of "
                  f"{MAX_BULLETS_PER_ROLE} kept bullets)")
    lines.append("== WORD COUNT ==")
    if is_master_input:
        lines.append(f"  note: input is a master ({word_count} words) — the "
              f"{max_words}-word deliverable cap applies to tailored "
              "resumes only")
    elif not max_words:
        lines.append("  note: word cap disabled (--max-words 0)")
    else:
        for e in word_errors:
            lines.append(f"  ERROR: {e}")
        if not word_errors:
            lines.append(f"  ok ({word_count} words, within the "
                         f"{max_words}-word cap)")
    if jd_path:
        lines.append("== EDUCATION ==")
        for e in education_errors:
            lines.append(f"  ERROR: {e}")
        for lvl, c in education_notes:
            tag = {"warn": "WARNING", "ok": "ok", "note": "note"}[lvl]
            lines.append(f"  {tag}: {c}")
    lines.append("== NEAR-DUPLICATES ==")
    for a, b, snip in dups:
        lines.append(f"  WARNING: bullets share {DUP_K}+ chars ({snip!r}):")
        lines.append(f"      A: {a!r}")
        lines.append(f"      B: {b!r}")
    if not dups:
        lines.append("  ok")
    lines.append("== GUIDANCE ==")
    for lvl, c in guidance_notes:
        tag = {"warn": "WARNING", "ok": "ok", "note": "note"}[lvl]
        lines.append(f"  {tag}: {c}")
    if not guidance_notes:
        lines.append("  ok")
    lines.append("== CLAIMS ==")
    for lvl, c in claim_notes:
        tag = {"warn": "WARNING", "ok": "ok", "note": "note"}[lvl]
        lines.append(f"  {tag}: {c}")
    if not claim_notes:
        lines.append("  ok")

    warn_count = (
        len(dups)
        + sum(1 for lvl, _ in claim_notes if lvl == "warn")
        + sum(1 for lvl, _ in guidance_notes if lvl == "warn")
    )
    blocking = (len(errors) + len(punct_errors) + len(integrity_errors)
                + len(seniority_errors) + len(education_errors)
                + len(cap_errors) + len(word_errors))
    if blocking:
        lines.append(
            f"RESULT: {blocking} blocking error(s) — fix before rendering (exit 2)")
    return {"blocking": blocking, "warnings": warn_count, "lines": lines}



def _parse_validate_args(argv):
    """Parse the validate-resume CLI arguments. Returns (path, strict, TreeOptions).

    Mutates ``argv`` in place (removing consumed flags)."""
    strict = _parse_flag(argv, "--strict")
    master = _extract_flag(argv, "--master")
    jd_years = float(_extract_flag(argv, "--jd-years")) if "--jd-years" in argv else None
    jd_path = _extract_flag(argv, "--jd")
    protect = _extract_flag_all(argv, "--protect")
    max_words = (int(_extract_flag(argv, "--max-words"))
                 if "--max-words" in argv else MAX_WORDS) or None
    seniority_approved = _parse_flag(argv, "--seniority-approved")
    education_approved = _parse_flag(argv, "--education-approved")
    opts = TreeOptions(master_path=master, jd_path=jd_path, jd_years=jd_years,
                       seniority_approved=seniority_approved,
                       education_approved=education_approved, protect=protect,
                       max_words=max_words)
    return argv[0], strict, opts


def main(argv=None):
    """Validate-resume CLI entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    path, strict, opts = _parse_validate_args(argv)

    _root, body, _names, _data, _ = de.load(path)
    result = validate_tree(path, body, opts)
    for line in result["lines"]:
        print(line)
    if result["blocking"]:
        return 2
    if strict and result["warnings"]:
        print(f"RESULT: {result['warnings']} warning(s) — --strict fails (exit 1)")
        return 1
    print(f"RESULT: clean ({result['warnings']} advisory warning(s) to review)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

class _JdBlocking(Exception):
    """Early-return carrier: _jd_checks raises this with the blocking
    result dict when the JD file is unreadable. validate_tree catches it
    and returns the dict (the documented dict contract)."""


def _jd_checks(jd_path, body, span, opts, notes):
    """Run the JD-dependent gates (education, title alignment, JD-FIT).

    Appends to ``notes.claim``/``notes.guidance`` in place; returns
    (education_errors, education_notes). Raises _JdBlocking with the
    blocking result dict when the JD file cannot be read."""
    jd_years = opts.jd_years
    education_approved = opts.education_approved
    protect = opts.protect
    claim_notes = notes.claim
    guidance_notes = notes.guidance
    education_errors, education_notes = [], []
    if jd_path:
        try:
            with open(jd_path, encoding="utf-8", errors="replace") as f:
                jd_text = f.read()
        except OSError as e:
            # KEEP the documented dict contract. Both consumers index the
            # result: validate_resume.main prints result["lines"] and
            # docx_edit's deliverable gate reads result["blocking"] BEFORE
            # writing a tailored .docx. An int return here made the gate
            # crash with "TypeError: 'int' object is not subscriptable"
            # instead of blocking with a readable message (found when a
            # session's --jd file was unreadable at save time). Blocking: 1
            # -> the CLI still exits 2 and the gate refuses the write.
            raise _JdBlocking({"blocking": 1, "warnings": 0, "lines": [
                f"error: cannot read --jd file {jd_path}: {e} "
                f"— JD-dependent gates cannot run"]}) from e
        education_errors, education_notes = _education_gate(
            jd_text, body, span, jd_years, education_approved)
        # A fabricated ask poisons every span comparison downstream (the
        # underqualified warning, the education load-bearing check): a
        # real session passed --jd-years 10 against a JD with no years
        # line and got false 'underqualified' output. Warn so the number
        # is only ever the JD's own.
        if jd_years is not None and not YEARS_RE.search(jd_text):
            claim_notes.append(("warn",
                f"--jd-years {jd_years:g} passed, but the JD text states "
                f"no 'N+ years' ask — the number looks invented; drop the "
                f"flag unless the posting states one"))
        # SKILL Step 4 title alignment (advisory, shared with measure): a
        # headline MORE SENIOR than the JD's title warns — never blocks.
        claim_notes.append(mr.title_alignment_notes(body, jd_text))

        # SKILL Step 8 render-path check: the JD-FIT AUDIT lives in measure
        # (planning); the deliverable gate runs HERE, so bullets with weak
        # or no JD evidence surface at render time too — a clean render is
        # not a JD-tight resume. Advisory: the human rule may keep one,
        # with a one-line reason tied to the JD.
        jd_fit = mr._jd_fit_audit(mr._roles(body), mr._jd_terms(jd_text, body),
                                  protect=protect)
        if jd_fit:
            flagged = sum(1 for s in jd_fit for l in s.splitlines()
                          if l.lstrip().startswith(("OFF-JD", "weak-match")))
            guidance_notes.append(("warn",
                f"JD-FIT: {flagged} bullet(s) across {len(jd_fit)} role(s) "
                f"carry weak or no JD evidence (measure's JD-FIT AUDIT "
                f"names them) — cut or shorten even when on target, or "
                f"keep with a one-line reason tied to the JD"))
        else:
            guidance_notes.append(("ok",
                "JD-FIT: every bullet carries JD evidence"))
    return education_errors, education_notes
