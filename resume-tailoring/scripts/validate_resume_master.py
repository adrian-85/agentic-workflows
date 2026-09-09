"""validate_resume's master-loading / role-integrity / education-gate helpers. Split from validate_resume.py; imported one-way by the shim."""  # pylint: disable=line-too-long  # (long string/help literal)
# pylint: disable=wrong-import-position,import-outside-toplevel
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.



import os
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
import measure_resume as mr  # noqa: E402
from validate_resume_checks import _is_bullet, TITLE_STYLE  # noqa: E402

# (constant) DEGREE_RE
DEGREE_RE = re.compile(
    r"\b(?:bachelor|master|associate)(?:['’]s)?\s+(?:degree|of|in)\b"
    r"|\bb\.[sa]\.\b|\bm\.[sa]\.\b|\bph\.?\s?d\b"
    r"|\bdegree\b[^.;]{0,30}\b(?:required|preferred)\b"
    r"|\b(?:required|preferred)[^.;]{0,30}\bdegree\b",
    re.I,
)


# (constant) EQUIV_CLAUSE_RE
EQUIV_CLAUSE_RE = re.compile(
    r"equivalent (?:professional |work )?(?:experience|education)"
    r"|(?:degree|experience|education)[^.;]{0,40}or (?:an )?equivalent"
    r"|or (?:an )?equivalent[^.;]{0,40}(?:degree|experience|education)",
    re.I,
)


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
            in_career = t == mr.SECTION_CAREER
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
    except Exception:  # pylint: disable=broad-exception-caught  # boundary: master parse failure → None, None (caller falls back)
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
                        "the resume has no dated roles to satisfy"
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
