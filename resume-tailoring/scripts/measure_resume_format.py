"""measure_resume format assumptions + layout/pages/roles measurement. Split from measure_resume.py; imported one-way by measure_resume_jd/drops/shim."""  # pylint: disable=line-too-long

# pylint: disable=wrong-import-position,import-outside-toplevel,invalid-name
# invalid-name: numId/rPr/pPr mirror OOXML schema tags verbatim.
# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.


import os
import re
import subprocess
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402

W = de.W

SECTION_CAREER = "Career Experience"


SECTION_EDUCATION = "Education"


SECTION_PROFICIENCIES = "Technical Proficiencies"


COMPANY_STYLE = "CompanyBlock"


DATE_RE = re.compile(r"\d{1,2}/\d{4}")  # dates on role headers, e.g. 03/2022


BULLET_STYLES = ("ListBullet",)  # styles whose bullets carry no paragraph numId


def _render_pdf(docx_path, outdir):
    """Render docx -> pdf via LibreOffice headless; return the pdf path."""
    base = os.path.basename(docx_path[:-5] if docx_path.endswith(".docx") else docx_path)
    pdf = os.path.join(outdir, base + ".pdf")
    subprocess.run(
        ["libreoffice", "--headless", "--convert-to", "pdf", docx_path,
         "--outdir", outdir],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not os.path.exists(pdf):
        sys.exit(f"error: LibreOffice did not produce {pdf}")
    return pdf


def _pdf_pages_text(pdf_path):
    """Return list of page-text strings (one per page), form-feed split.

    pdftotext separates pages with a form feed (\f) and emits a trailing
    one, so the raw split has an empty final element. Drop trailing empty
    parts; page count is then the real rendered page count.
    """
    out = subprocess.run(
        ["pdftotext", "-layout", pdf_path, "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    parts = out.split("\f")
    while parts and not parts[-1].strip():
        parts.pop()
    return parts


def _norm(s):
    """Collapse runs of whitespace to a single space and strip."""
    return re.sub(r"\s+", " ", s).strip()


def _is_footer(line):
    return bool(re.match(r"\s*Page \d+\|\d+\s*$", line))


def _page_lines(page_text):
    """Non-empty, non-footer lines of a single page, in order."""
    return [
        l for l in page_text.split("\n")
        if l.strip() and not _is_footer(l)
    ]


def _flat_from_pages(pages_text):
    """Flatten pages to (page_1based, norm_line, raw_line) preserving order."""
    flat = []
    for pi, ptext in enumerate(pages_text, start=1):
        for l in _page_lines(ptext):
            flat.append((pi, _norm(l), l))
    return flat


def _company_key(text):
    """The matchable company-portion of a role-header line (dates stripped).

    The master concatenates the company line and the date range with no
    separator (e.g. 'Company ABC, Phoenix, AZ07/2014 – 08/2016'); the
    PDF renders them separated by whitespace. Stripping the trailing date
    yields a prefix that matches the PDF header line after whitespace
    normalization.
    """
    m = DATE_RE.search(text)
    head = text[: m.start()] if m else text
    return _norm(head)


def _roles(body):
    """Ordered list of roles between the career and education section
    headings (names from SECTION_CAREER / SECTION_EDUCATION). Each role is a
    dict:

        key      – normalized company-portion (PDF match key)
        raw      – the full company header text, dates included
        bullets  – count of numbered bullets (cuttable items)
        bullet_texts – the bullets' texts, in document order (powers the
                       DROP PLAN's weakest-first ranking and copy-pasteable
                       find_p lines)
        has_tools– whether a Tools & Technologies line is present
    """
    ps = de.paras(body)
    # Find section-heading indices by text.
    def find_section(name):
        for i, p in enumerate(ps):
            if de.text_of(p).strip() == name:
                return i
        return None
    start = find_section(SECTION_CAREER)
    end = find_section(SECTION_EDUCATION)
    if start is None:
        start = 0
    if end is None:
        end = len(ps)
    region = ps[start:end]
    texts_r = [de.text_of(p) for p in region]

    roles = []
    cur = None
    for j, p in enumerate(region):
        style, numId = de.style_and_numid(p)
        txt = texts_r[j]
        if style == COMPANY_STYLE and txt.strip():
            if cur:
                roles.append(cur)
            cur = {"key": _company_key(txt), "raw": txt,
                   "bullets": 0, "bullet_texts": [], "has_tools": False}
        elif cur is not None:
            # Count numbered bullets (numId not None and not "0", or a
            # paragraph style whose numbering lives on the style, e.g.
            # Word's built-in List Bullet); flag tools lines.
            if (numId is not None and numId != "0") or style in BULLET_STYLES:
                cur["bullets"] += 1
                cur["bullet_texts"].append(txt)
            elif txt.strip().lower().startswith("tool") and "technolog" in txt.lower():
                cur["has_tools"] = True
    if cur:
        roles.append(cur)
    return roles


def _role_span_months(raw):
    """(start, end) month indexes from a role-header's date range, else
    (None, None)."""
    dates = []
    for m in DATE_RE.finditer(raw):
        mm, yyyy = m.group(0).split("/")
        dates.append((int(yyyy), int(mm)))
    if len(dates) < 2:
        return None, None
    return dates[0], dates[-1]


def _gap_if_dropped(roles, key):
    """Months of employment gap that dropping the role ``key`` would open
    between its two surviving neighbors, else 0.

    ``roles`` is newest-first (document order). Only interior roles can
    open a gap — dropping the oldest role just shortens the timeline.
    """
    idx = next((i for i, r in enumerate(roles) if r["key"] == key), None)
    if idx is None or idx == 0 or idx + 1 >= len(roles):
        return 0
    _, older_end = _role_span_months(roles[idx + 1]["raw"])
    newer_start, _ = _role_span_months(roles[idx - 1]["raw"])
    if older_end is None or newer_start is None:
        return 0
    gap = ((newer_start[0] - older_end[0]) * 12
           + (newer_start[1] - older_end[1]))
    return max(0, gap)


def _find_role_starts(roles, flat):
    """Find the line index where each role's header appears (in order)."""
    role_starts = []
    search_from = 0
    for r in roles:
        key = r["key"]
        found = None
        for k in range(search_from, len(flat)):
            if flat[k][1].startswith(key):
                found = k
                break
        role_starts.append(found)
        if found is not None:
            search_from = found + 1
    return role_starts


def _match_roles_to_pages(roles, pages_text):  # pylint: disable=too-many-locals
    """Attribute rendered lines to each role by locating its header in the
    PDF text. Returns list of (role, start_page_1based, end_page,
    rendered_lines).
    """
    flat = _flat_from_pages(pages_text)
    role_starts = _find_role_starts(roles, flat)

    def find_education_line(from_idx):
        for k in range(from_idx, len(flat)):
            if flat[k][1] == SECTION_EDUCATION:
                return k
        return len(flat)

    results = []
    for i, r in enumerate(roles):
        s = role_starts[i]
        if s is None:
            results.append((r, None, None, 0))
            continue
        # End = next matched role start, else Education heading, else EOF.
        e = find_education_line(s)
        for nxt in role_starts[i + 1:]:
            if nxt is not None:
                e = nxt
                break
        rendered = e - s
        end_page = flat[e - 1][0] if e > 0 else flat[s][0]
        results.append((r, flat[s][0], end_page, rendered))
    return results


def _tools_boundary(line, others):
    """Return True if ``line`` is a role/section boundary."""
    return (line in (SECTION_EDUCATION, SECTION_CAREER)
            or any(line.startswith(k) for k in others))


def _check_tools_wrap(flat, r, others, flat_len):
    """Check whether role ``r``'s Tools line wraps past one rendered line.

    Returns ``(key, value_chars, capacity, preview)`` if wrapped, else None.
    ``flat_len`` is the total length of ``flat`` (avoiding repeated calls).
    """
    idx = _role_header_flat(flat, r["key"])
    if idx is None:
        return None
    for k in range(idx + 1, flat_len):
        line = flat[k][1]
        if _tools_boundary(line, others):
            return None
        if "tools" in line.lower() and "technolog" in line.lower():
            if k + 1 < flat_len and not _tools_boundary(flat[k + 1][1], others):
                raw_first = flat[k][2]
                label = "Tools & Technologies: "
                stripped = raw_first.lstrip()
                capacity = max(0, len(stripped) - len(label))
                full = stripped[len(label):] if stripped.startswith(label) else stripped
                parts = [full]
                for cont in flat[k + 1:]:
                    if _tools_boundary(cont[1], others):
                        break
                    parts.append(cont[2].strip())
                value_chars = len(" ".join(parts).strip())
                return (r["key"], value_chars, capacity, raw_first.strip()[:80])
            break
    return None


def _wrapped_tools(flat, matched):
    """Roles whose Tools & Technologies line wraps past one rendered line.

    Returns (key, value_chars, wrap_capacity, preview) per wrapped line:
    ``value_chars`` is the full value length after the label, ``wrap_capacity``
    is how many value chars fit on the first rendered line.
    """
    others = {r["key"] for r, *_ in matched}
    flat_len = len(flat)
    results = []
    for r, *_ in matched:
        if not r.get("has_tools"):
            continue
        result = _check_tools_wrap(flat, r, others, flat_len)
        if result is not None:
            results.append(result)
    return results


def _fixed_top_cost(pages_text, roles):
    """Rendered lines before the first role's header (Summary, Proficiencies,
    Certifications, contact/header chrome). This is the mostly-fixed floor the
    agent generally does not compress from.
    """
    if not roles:
        return sum(len(_page_lines(p)) for p in pages_text)
    first_key = roles[0]["key"]
    n = 0
    for ptext in pages_text:
        for l in _page_lines(ptext):
            if _norm(l).startswith(first_key):
                return n
            n += 1
    return n


def _education_cost(pages_text):
    """Rendered lines from the Education heading to end of document."""
    n = 0
    started = False
    for ptext in pages_text:
        for l in _page_lines(ptext):
            if not started and _norm(l) == SECTION_EDUCATION:
                started = True
            if started:
                n += 1
    return n


def _visible_span(company_headers):
    """(start_year_float, end_year_float) across company header date ranges.

    ``company_headers`` are full role-header texts (dates included, e.g.
    "Acme, MA (Remote)05/2021 – 02/2023"). This is the number behind Step
    3's seniority-alignment decision: the resume's visible years, which a
    recruiter compares against the JD's "N+ years" ask — NOT the
    candidate's total career. Returns (None, None) when no headers have
    parseable dates.
    """
    first = last = None
    for text in company_headers:
        dates = DATE_RE.findall(text)
        if not dates:
            continue

        def ymd(s):
            if "/" in s:
                mo, yr = s.split("/")
            else:
                yr, mo = s.split("-")
            return int(yr) + (int(mo) - 1) / 12.0

        vals = [ymd(d) for d in dates]
        if first is None or vals[0] < first:
            first = vals[0]
        if last is None or vals[-1] > last:
            last = vals[-1]
    return first, last


def _page_fill(pages_text):
    """Rendered line count per page; capacity = the fullest page."""
    return [len(_page_lines(p)) for p in pages_text]


def _role_header_flat(flat, key):
    """Flat-index of a role's header line in the rendered text, else None."""
    for k, (_, norm, _) in enumerate(flat):
        if norm.startswith(key):
            return k
    return None


def _preceding_role_key(flat, idx, keys):
    """Key of the role owning the rendered content immediately before
    ``flat[idx]`` (a widow header): the nearest role-header line at or
    before idx - 1. That block is where the reclaim comes from — the fix
    for a stranded header is pulling the break point up from there. None
    when the preceding content is not a role block (e.g. the fixed top
    block), so callers fall back to the generic hint.
    """
    for j in range(idx - 1, -1, -1):
        for k in keys:
            if flat[j][1].startswith(k):
                return k
    return None


def _proficiency_block(body):
    """Text of the Technical Proficiencies section (between its heading and
    the next section heading). This is the resume's own tech vocabulary."""
    ps = de.paras(body)
    start = None
    for i, p in enumerate(ps):
        if de.text_of(p).strip() == SECTION_PROFICIENCIES:
            start = i
            break
    if start is None:
        return []
    out = []
    for p in ps[start + 1:]:
        if de.style_and_numid(p)[0] == "SectionHeading":
            break
        if de.text_of(p).strip():
            out.append(de.text_of(p))
    return out
