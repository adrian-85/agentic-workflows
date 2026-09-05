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

Structural, punctuation, text-integrity, bullet-cap, seniority-gate, and
education-gate errors exit 2 — render_pdf.sh refuses to render.
Near-duplicate and claim warnings exit 0 unless --strict (exit 1).

The master file is auto-detected as the "X Master Resume.docx" next to the
input; override with --master <path>.

Usage:
    python3 scripts/validate_resume.py <resume.docx> [--strict] [--master p]
    python3 scripts/validate_resume.py <resume.docx> --jd-years 5 [--master p]
    python3 scripts/validate_resume.py <resume.docx> --jd <JD.txt> [--jd-years 5] [--education-approved] [--master p]
"""

import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402

# Resume-format constants (same adaptation contract as measure_resume.py).
TITLE_STYLE = "JobTitleBlock"   # job-title paragraph style; adapt per resume
SUMMARY_STYLE = "Summary"       # summary paragraph style
LIST_STYLES = ("ListBullet",)   # paragraph styles whose bullets carry no numId

DUP_K = 20                      # shared substring length that flags near-dups
SENIORITY_GATE_YEARS = 2.0      # visible-span shrink (vs master) that requires approval

# Step 3.4 education predicates, mechanical form (see _education_gate).
# DEGREE_RE requires CREDENTIAL context, not the bare words: a real JD
# matched the old `\bdegree\b` via prose — 'a high degree of autonomy' —
# so a JD with no degree requirement at all entered the education gate
# and warned about a dropped Education section. Credential forms:
# 'Bachelor('s) degree/of/in', 'Master's degree', degree-abbreviations,
# or 'degree' adjacent (same sentence, <=30 chars) to required/preferred.
# The apostrophe group accepts the curly form too — JD text pasted from a
# PDF carries U+2019 ("Master’s degree"), which the ASCII-only group
# missed, silently skipping the education gate on a degree-requiring JD.
DEGREE_RE = re.compile(
    r"\b(?:bachelor|master|associate)(?:['’]s)?\s+(?:degree|of|in)\b"
    r"|\bb\.[sa]\.\b|\bm\.[sa]\.\b|\bph\.?\s?d\b"
    r"|\bdegree\b[^.;]{0,30}\b(?:required|preferred)\b"
    r"|\b(?:required|preferred)[^.;]{0,30}\bdegree\b",
    re.I,
)
# An 'or equivalent' EDUCATION-substitution clause — not a generic
# equivalence: a real JD matched the old bare `or equivalent` branch via
# 'CEFR C2 or equivalent' (language proficiency), fabricating a
# load-bearing education predicate. Require degree/experience/education
# context in the same sentence.
EQUIV_CLAUSE_RE = re.compile(
    r"equivalent (?:professional |work )?(?:experience|education)"
    r"|(?:degree|experience|education)[^.;]{0,40}or (?:an )?equivalent"
    r"|or (?:an )?equivalent[^.;]{0,40}(?:degree|experience|education)",
    re.I,
)
NUM_CLAIM = re.compile(r"\d+(?:\.\d+)?\s*(?:%|hours?|minutes?)", re.I)
YEARS_RE = re.compile(r"(\d{1,2})\s*(?:\+)?\s*(?:years|yrs)", re.I)
DATE_RANGE = re.compile(r"\d{1,2}/\d{4}\s*[–\-]\s*\d{1,2}/\d{4}")

# SKILL Step 8: hard cap on kept bullets per role, regardless of tenure,
# page target, or accomplishment. The master intentionally keeps everything;
# a tailored resume re-selects. Enforced as a blocking render gate below.
MAX_BULLETS_PER_ROLE = 8


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


def _prose_paragraphs(region, summary):
    """Non-empty prose paragraphs in document order: the Summary (if
    present) followed by bullets and role-intro text, excluding company
    headers and job titles. Yields (paragraph, text) pairs."""
    candidates = ([summary] if summary is not None else []) + [
        p for p in region
        if de.style_and_numid(p)[0] not in (mr.COMPANY_STYLE, TITLE_STYLE)
    ]
    for p in candidates:
        text = de.text_of(p)
        if text.strip():
            yield p, text


def _bullet_cap_errors(region):
    """Roles keeping more than MAX_BULLETS_PER_ROLE bullets (SKILL Step 8).

    The cap is enforced by count, not judgment: recency and accomplishment
    never exempt a role — a 1-year Staff role whose master block carries
    20+ bullets selects its strongest JD-aligned ones like everyone else
    (two real sessions let the most-recent role keep 16-19 bullets while
    JD-relevant older-role bullets died under page pressure). Returns one
    error per over-cap role, named by its company header.
    """
    errors = []
    company_text = None
    count = 0

    def _over():
        return (
            f"role {company_text!r} keeps {count} bullets — over the hard "
            f"cap of {MAX_BULLETS_PER_ROLE} (SKILL Step 8): prune to the "
            f"strongest JD-aligned bullets; time-in-role and volume of "
            f"accomplishment never exempt a role"
        )

    for p in region:
        style, _ = de.style_and_numid(p)
        if style == mr.COMPANY_STYLE:
            if company_text is not None and count > MAX_BULLETS_PER_ROLE:
                errors.append(_over())
            company_text = de.text_of(p).strip()
            count = 0
        elif _is_bullet(p):
            count += 1
    if company_text is not None and count > MAX_BULLETS_PER_ROLE:
        errors.append(_over())
    return errors


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


def _punctuation_errors(region, summary):
    """Step 9 punctuation rule: periods and commas only. The Summary and
    the job-history prose (role intros, bullets, tools lines) must contain
    no em dash (—), double hyphen (--), semicolon (;), colon (:), ellipsis
    (... or …), or non-date en dash (–). Exempt: single hyphens inside
    compound words, en dashes inside date ranges, structural lines
    (company headers, job titles), and the structural "Tools &
    Technologies:" label (its colon separates the label from the value
    list, it is not prose punctuation) — plus anything outside the Summary
    and the career region (proficiencies, certifications, education)."""
    errors = []
    for _, text in _prose_paragraphs(region, summary):
        probe = DATE_RANGE.sub(" ", text)  # date ranges are exempt
        # The Tools line's colon is structural (label: values), not prose.
        label_line = bool(_TOOLS_LABEL_RE.match(probe))
        for pat, name in (
            (re.compile(r"—"), "em dash"),
            (re.compile(r"–"), "en dash"),
            (re.compile(r";"), "semicolon"),
            (re.compile(r"-{2,}"), "double hyphen"),
            (re.compile(r"\.{2,}"), "ellipsis / doubled period"),
            (re.compile(r"…"), "ellipsis character"),
        ) + (() if label_line else ((re.compile(r":"), "colon"),)):
            m = pat.search(probe)
            if m is not None:
                s = max(0, m.start() - 30)
                e = min(len(probe), m.end() + 30)
                errors.append(
                    f"{name} in prose — use periods and commas: "
                    f"...{probe[s:e]}..."
                )
    return errors


# Structural "Tools & Technologies:" label inside job-history prose: its
# colon separates the bold label from the value list, so it is exempt from
# the colon ban (prose itself may still use only periods and commas).
_TOOLS_LABEL_RE = re.compile(r"^Tools\s*&\s*Technologies\s*:")

# Non-ASCII characters allowed in prose: typographic marks (curly
# apostrophes/quotes, dashes) and accented Latin letters. The ellipsis
# characters are NOT allowed — _punctuation_errors flags them.
_ASCII_OK_CHARS = "‘’“”–—‐‑"


def _text_integrity_errors(region, summary):
    """Step 9 text-integrity rule: generated prose must be clean. Scans the
    Summary and job-history prose (same scope as _punctuation_errors) for
    mangling artifacts: unexpected non-ASCII characters, doubled
    punctuation, and doubled words."""
    errors = []
    for _, text in _prose_paragraphs(region, summary):
        for i, ch in enumerate(text):
            if ord(ch) < 128 or ch in _ASCII_OK_CHARS:
                continue
            if "LATIN" in unicodedata.name(ch, ""):
                continue  # accented Latin letters are legitimate
            s, e = max(0, i - 30), min(len(text), i + 30)
            errors.append(
                f"non-ASCII {ch!r} (U+{ord(ch):04X} "
                f"{unicodedata.name(ch, '?')}) in prose — likely a mangling "
                f"artifact: ...{text[s:e]}..."
            )
        for m in re.finditer(r"(,|;|:)\1", text):
            s, e = max(0, m.start() - 30), min(len(text), m.end() + 30)
            errors.append(
                f"doubled punctuation {m.group(0)!r} in prose: ...{text[s:e]}..."
            )
        for m in re.finditer(
                r"\b(\w+)\s+\1\b", text, re.IGNORECASE):
            s, e = max(0, m.start() - 30), min(len(text), m.end() + 30)
            errors.append(
                f"doubled word {m.group(0)!r} in prose: ...{text[s:e]}..."
            )
    return errors


def _find_master(docx_path):
    d = os.path.dirname(os.path.abspath(docx_path))
    cands = [f for f in os.listdir(d) if f.endswith(" Master Resume.docx")]
    if len(cands) == 1:
        return os.path.join(d, cands[0])
    return None


def _master_texts(master_path):
    if not master_path or not os.path.exists(master_path):
        return None
    _root, body = _load_master_body(master_path)
    if body is None:
        return None
    return [de.text_of(p) for p in de.paras(body)]


def _company_headers(body):
    """Company-header texts (dates included) in document order."""
    return [
        de.text_of(p).strip()
        for p in de.paras(body)
        if de.style_and_numid(p)[0] == mr.COMPANY_STYLE
    ]


def _role_groups(body):
    """[({key, title, bullets})] per company block, document order.

    ``key`` is the date-stripped company portion (mr._company_key), which
    is stable between the master and a tailored copy. Scoped to the career
    region: education entries reuse the company-block style in this format
    and are not roles.
    """
    groups = []
    cur = None
    in_career = False
    for p in de.paras(body):
        style, _ = de.style_and_numid(p)
        t = de.text_of(p).strip()
        if style == "SectionHeading":
            in_career = (t == mr.SECTION_CAREER)
            continue
        if not in_career:
            continue
        if style == mr.COMPANY_STYLE and t:
            if cur:
                groups.append(cur)
            cur = {"key": mr._company_key(t), "title": None, "bullets": []}
        elif cur is not None:
            if style == TITLE_STYLE and cur["title"] is None:
                cur["title"] = t
            elif _is_bullet(p):
                cur["bullets"].append(t)
    if cur:
        groups.append(cur)
    return groups


def _norm_text(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def _load_master_body(master_path):
    """(root, body) of the master, or (None, None) when missing or unreadable.

    A corrupt/unreadable master degrades to 'no master found' (the claims
    note already covers that case) instead of crashing validation — a
    broken master must not take the whole gate down.
    """
    if not master_path or not os.path.exists(master_path):
        return None, None
    try:
        root, mbody, _n, _d, _ = de.load(master_path)
        return root, mbody
    except Exception:
        return None, None


def _role_integrity_errors(master_path, body):
    """Whole-role removals must be WHOLE. Compared against the master:

    - a kept role must retain its job title AND at least one bullet
      (a company header with no title, or a title with no bullets, is a
      partially-removed role);
    - a removed role must leave NO surviving bullet (its bullets kept
      while its header/title were dropped is the orphaned-content failure:
      they dangle under the previous role or after a Tools line).
    """
    if not master_path or not os.path.exists(master_path):
        return []
    _root, mbody = _load_master_body(master_path)
    if mbody is None:
        return []
    master_groups = _role_groups(mbody)
    out_groups = _role_groups(body)
    out_by_key = {}
    for g in out_groups:
        out_by_key.setdefault(g["key"], []).append(g)
    out_bullet_set = {_norm_text(b) for g in out_groups for b in g["bullets"]}

    errors = []
    for g in master_groups:
        mkey = g["key"]
        mbullets = g["bullets"]
        kept = out_by_key.get(mkey)
        if kept:
            for og in kept:
                if og["title"] is None:
                    errors.append(
                        f"role {mkey!r} kept but its job title was removed "
                        f"(partially-removed role)"
                    )
                if not og["bullets"]:
                    errors.append(
                        f"role {mkey!r} kept but ALL its bullets were "
                        f"removed (empty role)"
                    )
        else:
            for b in mbullets:
                if _norm_text(b) in out_bullet_set:
                    errors.append(
                        f"role {mkey!r} was removed but its bullet survives "
                        f"elsewhere: {b[:60]!r}"
                    )
    return errors


def _master_span(master_path):
    """Visible (start, end) span of the master's role dates, else (None, None)."""
    _root, body = _load_master_body(master_path)
    if body is None:
        return None, None
    return mr._visible_span(_company_headers(body))


def _has_education(body):
    """True when an Education section heading survives in the resume.

    Exact-text match on the heading: a bullet never consists of just the
    word "Education", so no style check is needed and resumes using a
    different heading style still register.
    """
    return any(de.text_of(p).strip().lower() == "education"
               for p in de.paras(body))


def _education_gate(jd_text, body, span, jd_years, approved):
    """Step 3.4's education predicates as (errors, notes).

    Notes are (severity, message) pairs printed under the EDUCATION
    section (severity in warn|ok). The predicates, enforced mechanically
    once the JD text is available via --jd:

    - JD requires a degree (no equivalent clause) and Education was
      dropped -> BLOCKING error unless ``approved`` records the override
      (--education-approved). Restore the section from the master.
    - JD offers an 'or equivalent experience/education' clause: the clause
      is satisfied by experience when the visible span exceeds the ask
      (the drop is safe); at or below the ask the clause is load-bearing —
      Education becomes the substitute evidence and dropping it leaves
      nothing standing in for the degree (warn).
    - JD states no degree requirement -> nothing to check.
    """
    errors, notes = [], []
    if not DEGREE_RE.search(jd_text):
        return errors, notes
    if _has_education(body):
        notes.append(("ok", "section present; the JD's degree requirement "
                           "is satisfied"))
        return errors, notes
    ask = (f"the JD's {jd_years:g}+ years ask" if jd_years is not None
           else None)
    if EQUIV_CLAUSE_RE.search(jd_text):
        if jd_years is not None and span is not None and span > jd_years:
            notes.append((
                "ok",
                f"dropped, but the JD's equivalent-experience clause is "
                f"satisfied by the ~{span:.1f}-year visible span"
                + (f" (vs {ask})" if ask else "") + " — the drop is safe",
            ))
        else:
            span_txt = (f"the ~{span:.1f}-year visible span does not clearly"
                        f" exceed" + (f" {ask}" if ask else "")
                        if span is not None else
                        f"the resume has no dated roles to satisfy"
                        + (f" {ask}" if ask else ""))
            notes.append((
                "warn",
                f"dropped while the JD's 'or equivalent' clause is "
                f"load-bearing: {span_txt} — the clause substitutes "
                f"experience for the degree only, so keep the section "
                f"prominent as the substitute evidence",
            ))
        return errors, notes
    if approved:
        notes.append((
            "ok",
            "dropped although the JD requires a degree — "
            "--education-approved recorded",
        ))
    else:
        errors.append(
            "the JD requires a degree (no 'or equivalent' substitution "
            "clause) but Education was dropped — restore the section from "
            "the master (it is ~3 rendered lines there), or record a "
            "USER-GRANTED override with --education-approved: approval may "
            "come only from the user's chat reply or pre-authorization in "
            "the original request — do NOT pass the flag on your own authority"
        )
    return errors, notes


def _parse_flag(argv, flag):
    """Remove a boolean flag from ``argv`` (in-place) and return True if it was present."""
    if flag in argv:
        argv.remove(flag)
        return True
    return False


def _extract_flag(argv, flag):
    """Extract a flag + value pair from ``argv`` (in-place), returning the value or None."""
    if flag in argv:
        i = argv.index(flag)
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return None


def validate_tree(path, body, *, master_path=None, jd_path=None,
                  jd_years=None, seniority_approved=False,
                  education_approved=False):
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

    # Visible timeline span (shared with measure_resume.py): the number a
    # recruiter compares against the JD's "N+ years" ask. Everything below
    # that checks claims against this span.
    first, last = mr._visible_span(_company_headers(body))
    span = (last - first) if (first is not None and last is not None) else None

    claim_notes = []  # (severity, message); severity in warn|ok|note

    # Education gate (Step 3.4, needs --jd): a degree-requiring JD blocks
    # the render when the section was dropped (--education-approved
    # records the override); under an 'or equivalent' clause the clause is
    # load-bearing only when the visible span does not exceed the ask.
    education_errors, education_notes = [], []
    if jd_path:
        try:
            with open(jd_path, encoding="utf-8", errors="replace") as f:
                jd_text = f.read()
        except OSError as e:
            print(f"error: cannot read --jd file {jd_path}: {e}",
                  file=sys.stderr)
            return 2
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

    # Claims: numbers vs master.
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
    lines.append("== CLAIMS ==")
    for lvl, c in claim_notes:
        tag = {"warn": "WARNING", "ok": "ok", "note": "note"}[lvl]
        lines.append(f"  {tag}: {c}")
    if not claim_notes:
        lines.append("  ok")

    warn_count = (
        len(dups)
        + sum(1 for lvl, _ in claim_notes if lvl == "warn")
    )
    blocking = (len(errors) + len(punct_errors) + len(integrity_errors)
                + len(seniority_errors) + len(education_errors)
                + len(cap_errors))
    if blocking:
        lines.append(
            f"RESULT: {blocking} blocking error(s) — fix before rendering (exit 2)")
    return {"blocking": blocking, "warnings": warn_count, "lines": lines}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = _parse_flag(argv, "--strict")
    master = _extract_flag(argv, "--master")
    jd_years = float(_extract_flag(argv, "--jd-years")) if "--jd-years" in argv else None
    jd_path = _extract_flag(argv, "--jd")
    seniority_approved = _parse_flag(argv, "--seniority-approved")
    education_approved = _parse_flag(argv, "--education-approved")
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]

    root, body, names, data, _ = de.load(path)
    result = validate_tree(
        path, body, master_path=master, jd_path=jd_path, jd_years=jd_years,
        seniority_approved=seniority_approved,
        education_approved=education_approved)
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