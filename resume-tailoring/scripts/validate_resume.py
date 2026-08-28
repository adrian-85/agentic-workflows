"""Lint a (tailored) resume for structural and claim-consistency errors.

Catches the error classes tailoring sessions actually hit:

1. STRUCTURE — orphan paragraphs left by subtractive cuts:
   - a job-title paragraph with no preceding company block (a company
     header was removed but its title stayed, e.g. Epic Sciences / Rakuten
     dangles), or a company block followed by no job title
   - content after a role's Tools line with no new company block (a
     company+title were removed but later bullets survived)
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
   - SENIORITY GATE: when whole roles were eliminated (visible span >= 2
     years shorter than the master), the run is a blocking error unless
     `--seniority-approved` records the user's approval. This makes the
     Step 3 "ask the user first" rule a gate: render_pdf.sh will not
     produce a PDF from a shortened timeline without the approval token.

Structural errors and the seniority gate exit 2 — render_pdf.sh refuses to
render. Near-duplicate and claim warnings exit 0 unless --strict (exit 1).

The master file is auto-detected as the "X Master Resume.docx" next to the
input; override with --master <path>.

Usage:
    python3 scripts/validate_resume.py <resume.docx> [--strict] [--master p]
    python3 scripts/validate_resume.py <resume.docx> --jd-years 5 [--master p]
    python3 scripts/validate_resume.py <resume.docx> --seniority-approved [--master p]  # (--jd-years is a separate optional advisory)
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402

# Resume-format constants (same adaptation contract as measure_resume.py).
TITLE_STYLE = "JobTitleBlock"   # job-title paragraph style; adapt per resume
SUMMARY_STYLE = "Summary"       # summary paragraph style
LIST_STYLES = ("ListBullet",)   # paragraph styles whose bullets carry no numId

DUP_K = 20                      # shared substring length that flags near-dups
SENIORITY_GATE_YEARS = 2.0      # visible-span shrink (vs master) that requires approval
NUM_CLAIM = re.compile(r"\d+(?:\.\d+)?\s*(?:%|hours?|minutes?)", re.I)
YEARS_RE = re.compile(r"(\d{1,2})\s*(?:\+)?\s*(?:years|yrs)", re.I)


def _is_bullet(p):
    style, numId = de.style_and_numid(p)
    return (numId is not None and numId != "0") or style in LIST_STYLES


def _is_tools(p):
    t = de.text_of(p).strip().lower()
    return t.startswith("tool") and "technolog" in t


def _region(body):
    """Paragraphs between the Career Experience heading and the NEXT section
    heading (Education, or an Open Source / Projects section). Confines the
    role-structure rules to the role block so legitimate non-role sections
    (projects, open source) can't false-positive."""
    ps = de.paras(body)
    start = None
    for i, p in enumerate(ps):
        if de.text_of(p).strip() == mr.SECTION_CAREER:
            start = i
            break
    if start is None:
        return []
    region = []
    for p in ps[start + 1:]:
        style, _ = de.style_and_numid(p)
        if (style == "SectionHeading"
                or de.text_of(p).strip() == mr.SECTION_EDUCATION):
            break
        region.append(p)
    return region


def _summary_paragraph(body):
    for p in de.paras(body):
        style, _ = de.style_and_numid(p)
        if style == SUMMARY_STYLE:
            return p
    return None


def _structural_errors(region):
    """Structural failures (exit 2) in the career region: orphan job titles,
    companies without a title, and content orphaned after a Tools line."""
    errors = []
    waiting_title = False
    company_text = None
    last_kind = None  # 'company' | 'title' | 'other' (bullet/tools/etc)
    for p in region:
        if not de.text_of(p).strip():
            continue
        style, numId = de.style_and_numid(p)
        if style == mr.COMPANY_STYLE:
            if waiting_title:
                errors.append(
                    f"company block has no job title before next company: "
                    f"{company_text!r}"
                )
            waiting_title = True
            company_text = de.text_of(p).strip()
            last_kind = 'company'
        elif style == TITLE_STYLE:
            if not waiting_title and last_kind != 'title':
                errors.append(
                    f"job title without a preceding company block: "
                    f"{de.text_of(p).strip()!r}"
                )
            waiting_title = False
            last_kind = 'title'
        else:
            if waiting_title:
                errors.append(
                    f"company block has no job title (next content is a "
                    f"bullet/tools line): {company_text!r}"
                )
                waiting_title = False
            if last_kind == 'tools':
                # Content after a role's Tools line with no new company:
                # a company+title block was removed but later bullets survived.
                errors.append(
                    f"content after a Tools line with no new company block "
                    f"(orphaned role content?): {de.text_of(p).strip()[:60]!r}"
                )
            if _is_tools(p):
                last_kind = 'tools'
            elif _is_bullet(p):
                last_kind = 'bullet'
            else:
                last_kind = last_kind  # intro paragraphs etc. keep state
    if waiting_title:
        errors.append(
            f"company block has no job title (end of section): "
            f"{company_text!r}"
        )
    return errors


def _near_duplicates(region):
    """Yield (bullet_a[:60], bullet_b[:60], shared snippet) for bullets that
    share a DUP_K-char substring — the signature of a merge that left the
    source's old text beside the rewritten target (or a literal duplicate)."""
    bullets = [de.text_of(p) for p in region if _is_bullet(p)]
    subs = {}
    warned = set()
    for i, t in enumerate(bullets):
        norm = re.sub(r"\s+", " ", t).strip()
        if len(norm) < DUP_K:
            continue
        for j in range(len(norm) - DUP_K + 1):
            s = norm[j:j + DUP_K]
            if not s.strip():
                continue
            if s in subs:
                k = subs[s]
                pair = tuple(sorted((i, k)))
                if pair not in warned:
                    warned.add(pair)
                    yield bullets[k][:60], bullets[i][:60], s[:40]
            else:
                subs.setdefault(s, i)


def _claim_years(text):
    m = YEARS_RE.search(text)
    return int(m.group(1)) if m else None


def _find_master(docx_path):
    d = os.path.dirname(os.path.abspath(docx_path))
    cands = [f for f in os.listdir(d) if f.endswith(" Master Resume.docx")]
    if len(cands) == 1:
        return os.path.join(d, cands[0])
    return None


def _master_texts(master_path):
    if not master_path or not os.path.exists(master_path):
        return None
    root, body, names, data, _ = de.load(master_path)
    return [de.text_of(p) for p in de.paras(body)]


def _company_headers(body):
    """Company-header texts (dates included) in document order."""
    return [
        de.text_of(p).strip()
        for p in de.paras(body)
        if de.style_and_numid(p)[0] == mr.COMPANY_STYLE
    ]


def _master_span(master_path):
    """Visible (start, end) span of the master's role dates, else (None, None)."""
    if not master_path or not os.path.exists(master_path):
        return None, None
    root, body, names, data, _ = de.load(master_path)
    return mr._visible_span(_company_headers(body))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    argv = [a for a in argv if a not in ("--strict",)]
    master = None
    if "--master" in argv:
        i = argv.index("--master")
        master = argv[i + 1]
        del argv[i:i + 2]
    jd_years = None
    if "--jd-years" in argv:
        i = argv.index("--jd-years")
        jd_years = float(argv[i + 1])
        del argv[i:i + 2]
    seniority_approved = "--seniority-approved" in argv
    argv = [a for a in argv if a != "--seniority-approved"]
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]

    root, body, names, data, _ = de.load(path)
    region = _region(body)

    errors = _structural_errors(region)
    dups = list(_near_duplicates(region))

    # Visible timeline span (shared with measure_resume.py): the number a
    # recruiter compares against the JD's "N+ years" ask. Everything below
    # that checks claims against this span.
    first, last = mr._visible_span(_company_headers(body))
    span = (last - first) if (first is not None and last is not None) else None

    claim_notes = []  # (severity, message); severity in warn|ok|note

    # Claims: numbers vs master.
    master_path = master or _find_master(path)
    master_texts = _master_texts(master_path)
    master_blob = " ".join(master_texts) if master_texts is not None else None

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
                    f"(~{master_span:.1f}y). Confirm the seniority-alignment "
                    f"option (SKILL Step 3) with the user and record approval "
                    f"by re-running with --seniority-approved — the PDF render "
                    f"is blocked without it."
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
    summary = _summary_paragraph(body)
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

    # Print.
    print("== STRUCTURE ==")
    for e in errors:
        print(f"  ERROR: {e}")
    if not errors:
        print("  ok (all roles have a company + job title; no orphan content)")
    print("== SENIORITY ==")
    for e in seniority_errors:
        print(f"  ERROR: {e}")
    if not seniority_errors:
        print("  ok")
    print("== NEAR-DUPLICATES ==")
    for a, b, snip in dups:
        print(f"  WARNING: bullets share {DUP_K}+ chars ({snip!r}):")
        print(f"      A: {a!r}")
        print(f"      B: {b!r}")
    if not dups:
        print("  ok")
    print("== CLAIMS ==")
    for lvl, c in claim_notes:
        tag = {"warn": "WARNING", "ok": "ok", "note": "note"}[lvl]
        print(f"  {tag}: {c}")
    if not claim_notes:
        print("  ok")

    warn_count = (
        len(dups)
        + sum(1 for lvl, _ in claim_notes if lvl == "warn")
    )
    blocking = len(errors) + len(seniority_errors)
    if blocking:
        print(f"RESULT: {blocking} blocking error(s) — fix before rendering (exit 2)")
        return 2
    if strict and warn_count:
        print(f"RESULT: {warn_count} warning(s) — --strict fails (exit 1)")
        return 1
    print(f"RESULT: clean ({warn_count} advisory warning(s) to review)")
    return 0


if __name__ == "__main__":
    sys.exit(main())