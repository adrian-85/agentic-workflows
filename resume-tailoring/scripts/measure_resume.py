"""Measure a resume's rendered length and plan compression to a page budget.

The subtractive tailoring flow (copy master, cut down) iterates well when you
know the budget up front. This tool closes that gap: it renders the .docx to
PDF once, attributes rendered lines to each role, and reports how many lines
must be reclaimed to hit a target page count — so cuts can be planned as a
batch instead of discovered through a cut-render-cut-render loop.

Usage::

    python3 scripts/measure_resume.py <resume.docx> [TARGET_PAGES]
    python3 scripts/measure_resume.py <resume.docx> [TARGET_PAGES] \
        --jd <raw-JD.txt> [--protect "<phrase>"]
    TARGET_PAGES=2 python3 scripts/measure_resume.py <resume.docx>

``--jd`` makes the DROP PLAN JD-aware (see JD_CONCEPTS / JD_STOP below):
candidate-tech terms that the raw JD also asks for — and JD practice
phrases like mentorship — are excluded from the cut suggestions and listed
as "JD-matched (kept)", so the plan never fights the JD.

Reads role/bullet structure from the .docx (via docx_edit) and rendered line
counts from the PDF (via pdftotext). Requires libreoffice + pdftotext.

Output:
  - Total pages vs target, and the rendered-line gap to reclaim.
  - A "fixed" top block (Summary + Proficiencies + Certifications + headers)
    cost — mostly not where compression happens, but shows the floor.
  - Per-role rendered cost (lines, bullet count, start page), oldest roles
    last so the cheapest compression targets are at the bottom of the table.
  - A concrete reclaim suggestion (which oldest roles to trim and by how
    much) sized to the gap.

This is a MEASUREMENT tool: it does not edit the .docx. Run it after the
content edits (Summary rewrite, proficiency retrim, role re-anchoring) and
BEFORE the compression cuts, to plan them. Re-run render_pdf.sh after cutting
to verify.
"""

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402

W = de.W

# ---------------------------------------------------------------------- #
# Resume-format assumptions — EDIT THESE to match your own master resume. #
#                                                                         #
# Measurement keys off your resume's structure. If yours uses different   #
# section headings, a different role-header style name, a different date  #
# format, or bullet paragraphs whose numbering lives on the paragraph     #
# STYLE rather than on the paragraph, change the values here — the        #
# logic below stays the same.                                             #
# ---------------------------------------------------------------------- #
SECTION_CAREER = "Career Experience"
SECTION_EDUCATION = "Education"
SECTION_PROFICIENCIES = "Technical Proficiencies"
COMPANY_STYLE = "CompanyBlock"
VOCAB_STYLE = "JobTitleBlock"  # job-title paragraphs feed the --jd vocabulary
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


def _top_block_candidates(body, jd_terms=()):
    """Cut candidates from the FIXED TOP BLOCK: Technical Proficiencies
    lines and certification lines carrying no JD evidence.

    The whole resume tailors to the JD — compression is NOT limited to
    role bullets. Each candidate is ``(find_p_prefix, text)``; a line that
    matches a JD term or practice phrase is NOT a candidate (it is doing
    JD work). The Certifications section heading itself is skipped (it is
    only cuttable together with its last line). Empty without --jd? No —
    without ``jd_terms`` every top-block line is a candidate (the caller
    labels them "review against the JD").
    """
    ps = de.paras(body)
    texts = [de.text_of(p) for p in ps]
    start = None
    for i, p in enumerate(ps):
        if texts[i].strip() == SECTION_PROFICIENCIES:
            start = i + 1
            break
    if start is None:
        return []
    out = []
    for i in range(start, len(ps)):
        p = ps[i]
        style, _ = de.style_and_numid(p)
        t = texts[i]
        if style == COMPANY_STYLE and t.strip():
            break  # career region begins
        if style == "SectionHeading" or not t.strip():
            continue
        if _jd_hits(t, jd_terms) or _concept_hits(t):
            continue
        prefix = de.shortest_unique_prefix(texts, i, min_len=6)
        if prefix is not None:
            out.append((prefix, t.strip()))
    return out


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


def _match_roles_to_pages(roles, pages_text):
    """Attribute rendered lines to each role by locating its header in the
    PDF text. Returns list of (role, start_page_1based, end_page,
    rendered_lines).
    """
    flat = _flat_from_pages(pages_text)

    # Find the line index where each role's header appears (in order).
    role_starts = []  # flat-index of each role header
    search_from = 0
    for r in roles:
        key = r["key"]
        found = None
        for k in range(search_from, len(flat)):
            if flat[k][1].startswith(key):
                found = k
                break
        if found is None:
            # Could not match; treat as zero-cost (shouldn't normally happen).
            role_starts.append(None)
            continue
        role_starts.append(found)
        search_from = found + 1

    # Bound each role at the next role's header, or the education heading, or end.
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


def _wrapped_tools(flat, matched):
    """Roles whose Tools & Technologies line wraps past one rendered line.

    The validator guarantees a Tools line is the last content of its role
    (nothing legit follows it), so a wrap is exactly: the line AFTER the
    tools line is not the next role/section boundary.

    Returns (key, value_chars, wrap_capacity, preview) per wrapped line:
    ``value_chars`` is the full value length after the "Tools &
    Technologies: " label (continuation lines joined), ``wrap_capacity`` is
    how many value chars fit on the FIRST rendered line. The gap between
    the two is the honest trim budget — the render's proportional font
    makes a fixed "~N tools" heuristic wrong, so the measured wrap point
    (not a guess) is what the trim note reports.
    """
    others = {r["key"] for r, *_ in matched}

    def is_boundary(line):
        return (line in (SECTION_EDUCATION, SECTION_CAREER)
                or any(line.startswith(k) for k in others))

    results = []
    for r, *_ in matched:
        if not r.get("has_tools"):
            continue
        idx = _role_header_flat(flat, r["key"])
        if idx is None:
            continue
        for k in range(idx + 1, len(flat)):
            line = flat[k][1]
            if is_boundary(line):
                break  # no tools line in this role's region
            if "tools" in line.lower() and "technolog" in line.lower():
                if k + 1 < len(flat) and not is_boundary(flat[k + 1][1]):
                    raw_first = flat[k][2]
                    label = "Tools & Technologies: "
                    stripped = raw_first.lstrip()
                    # Capacity = value chars that fit on the first rendered
                    # line (label excluded, indent excluded).
                    capacity = max(0, len(stripped) - len(label))
                    full = stripped[len(label):] if stripped.startswith(label) else stripped
                    parts = [full]
                    for cont in flat[k + 1:]:
                        if is_boundary(cont[1]):
                            break
                        parts.append(cont[2].strip())
                    value_chars = len(" ".join(parts).strip())
                    results.append((r["key"], value_chars, capacity,
                                    raw_first.strip()[:80]))
                break
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


# Process-y phrasing that signals a generic bullet (weakest to cut). A
# bullet with any such phrase and NO hard number ranks weakest; hard
# numbers/percentages (quantified evidence) always rank strongest.
GENERIC_PHRASES = (
    "established", "coordinated", "enhanced", "presented", "mentored",
    "assisted", "advocated", "organized", "scheduled", "attended",
    "facilitated", "streamlined", "ensured", "participated",
)
_NUMBER = re.compile(r"\d|%")


# ---------------------------------------------------------------------- #
# JD-aware ranking (--jd <file>). The weakness scorer is JD-blind: it ranks
# by numbers and generic phrasing, so a bullet like "Championed the
# adoption of Cypress" — a directly named JD Required qual — can land on
# the cut list, and a "Mentored junior team member" bullet can be silently
# cut under page pressure even though the JD requires mentorship. --jd
# fixes that with zero NLP: a term is JD-relevant when it appears in BOTH
# the candidate's own tech vocabulary (proficiency lines, Tools lines, job
# titles — the universe of what the candidate claims) AND the raw JD text.
# The intersection is exactly "tools the JD asks for that this candidate
# actually has", and it is robust to JD phrasing (Selenium vs Selenium
# WebDriver).
# ---------------------------------------------------------------------- #

# Candidate-tech terms that are too generic across bullets to signal JD
# relevance (protecting them over-protects: Java/Python appear everywhere).
# Add to this list only when a vocabulary term keeps over-matching.
JD_STOP = frozenset({
    # Vague résumé/JD nouns and generic ENGLISH PROSE. Tech words (rest,
    # api, java, sql, testing, ...) are deliberately NOT here: matching is
    # whole-word + capitalized-for-bullet-only-terms + a generic-hit-rate
    # guard, so a JD that names REST or Java now protects the bullets that
    # use them instead of being silenced by the stop list. The stop list is
    # only for words that are NEVER tech evidence.
    "experience", "senior", "staff", "team", "teams", "project",
    "projects", "process", "processes", "product", "products",
    "quality", "engineer", "engineers", "role", "roles", "end",
    "end-to-end", "e2e", "standard", "standards", "deliver",
    "delivered", "delivering", "deliveries",
    "and", "the", "for", "a", "an", "or", "of", "in", "to", "on",
    "with", "from", "into", "them", "they", "their", "each",
    "when", "while", "where", "which", "through", "throughout",
    "than", "then", "also", "both", "over", "more", "most",
    "other", "others", "some", "such", "only", "well", "work",
    "worked", "working", "works", "need", "needs", "using",
    "used", "uses", "across", "against", "within", "without",
    "via", "per", "plus", "near", "among", "along", "since",
    "until", "upon", "about", "after", "before", "during",
    "between", "internal", "external", "global", "globally",
    "international", "meeting", "meetings", "contact", "corporate",
    "clients", "client", "customers", "customer", "hour", "hours",
    "time", "lead", "leads", "leading", "flow", "flows", "gain",
    "gains", "approach", "approaches", "clearly", "clear",
    "required", "require", "requires", "requirement", "requirements",
    "commit", "commits", "committed", "resolution", "resolve",
    "resolved", "support", "supports", "supported", "supporting",
    "issue", "issues", "based", "multiple", "various", "several",
    "include", "includes", "included", "including", "deeply", "deep",
    "key", "core", "strong", "strongly", "solid", "proven",
    "ability", "abilities", "skill", "skills", "skilled",
    "knowledge", "understanding", "complex", "concepts", "concept",
    "bachelor", "degree", "education", "university", "college",
    "business", "businesses", "progress", "flexible", "flexibility",
    "learning", "collaborative", "environment", "environments",
    "practice", "practices", "types", "type", "internally",
})

# JD-Named PRACTICES the vocabulary intersection cannot see (they are not
# tools): "Mentor junior QA engineers" names a responsibility, not a
# technology. A bullet naming one of these is JD-evidence and must not be
# cut while non-matching bullets remain. Extend with JD-specific practice
# phrases when the JD names one (shift-left, contract testing, ...).
JD_CONCEPTS = (
    "mentor", "mentoring", "mentorship", "shift-left", "shift left",
    "contract testing", "root-cause", "root cause", "risk-based",
    "exploratory", "chaos", "model-based", "code review", "design review",
    "traceability", "documentation gaps", "go-live", "go live",
    "instructor-led", "incomplete documentation",
)

# Unambiguous technology nouns that JDs routinely use lowercase
# mid-sentence ("Perform API, service, integration, and backend
# validation"). The bullet-only capitalization gate exists to block PROSE
# flood; these can never be prose, so they are exempt. The generic-hit-rate
# guard (term hits >50% of bullets) still applies to them. A past session:
# 'integration' was gated as bullet-only, so the partner-integrations
# bullet (strong integration-testing evidence) was ranked for cutting.
CORE_TECH_NOUNS = frozenset({
    "api", "apis", "sql", "sdk", "graphql", "grpc", "rest", "soap",
    "json", "xml", "yaml", "integration", "integrations", "backend",
    "database", "databases", "sandbox",
    "regression", "end-to-end", "playwright", "cypress", "selenium",
    "karate", "postman", "jenkins", "docker", "kubernetes", "terraform",
})


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


def _line_terms(line):
    """Tech terms from one labeled line ("Label: values"): each comma/;
    chunk verbatim (so multi-word "GitHub Actions" stays a phrase) plus
    len>=3 words inside multi-word chunks. Label text (the "Label" side)
    also contributes len>=3 words — so an "API & Web Services" line yields
    "api"/"web"/"services" as claimed vocabulary."""
    terms = set()
    if ":" in line:
        label, value = line.split(":", 1)
    else:
        label, value = None, line
    if label:
        for word in re.findall(r"[a-z0-9][a-z0-9#.+]*", label.lower()):
            if len(word) >= 3 and not re.fullmatch(r"[0-9.]+\w*", word):
                terms.add(word)
    for chunk in re.split(r"[,;]", value):
        chunk = chunk.strip().lower()
        if not chunk:
            continue
        terms.add(chunk)
        if " " in chunk:
            for word in re.findall(r"[a-z0-9][a-z0-9#.+]*", chunk):
                if len(word) >= 3 and not re.fullmatch(r"[0-9.]+\w*", word):
                    terms.add(word)
    return terms


def _vocab_terms(body):
    """The candidate's claimed tech vocabulary: proficiency lines, every
    role's Tools & Technologies line, and job-title paragraphs."""
    terms = set()
    for line in _proficiency_block(body):
        terms |= _line_terms(line)
    for p in de.paras(body):
        t = de.text_of(p)
        if t.lower().startswith("tools") and "technolog" in t.lower():
            terms |= _line_terms(t)
        elif de.style_and_numid(p)[0] == VOCAB_STYLE:
            terms |= _line_terms(t)
    return terms


def _bullet_terms(body):
    """Single-word alnum tokens (len>=4, not stops/numeric) from every
    numbered bullet. This catches candidate tools that appear ONLY in a
    bullet (e.g. Snyk folded into the master, absent from the proficiency
    and Tools lists) — a gap the vocabulary intersection alone misses.
    Prose words are largely filtered by JD_STOP; the token must also appear
    in the JD to become a term, so misses only over-protect when the JD
    itself names a prose word."""
    terms = set()
    for text in _all_bullet_texts(body):
        for w in re.findall(r"[a-z0-9][a-z0-9#.+-]*", text.lower()):
            w = w.rstrip(".,;:!?'")
            if w in JD_STOP or len(w) < 4 or re.fullmatch(r"[0-9.]+\w*", w):
                continue
            terms.add(w)
    return terms


def _all_bullet_texts(body):
    """Texts of every numbered bullet in the document (document order)."""
    out = []
    for p in de.paras(body):
        style, numId = de.style_and_numid(p)
        if (numId in (None, "0") and style not in BULLET_STYLES):
            continue
        out.append(de.text_of(p))
    return out


def _jd_capitalized(jd_text, term):
    """True if ``term`` occurs in the JD as a mid-sentence Capitalized or
    ALL-CAPS token.

    Bullet-only terms (tools named nowhere in the proficiencies/Tools
    vocabulary, e.g. Snyk) must pass this test: tool names are proper
    nouns and stay capitalized mid-sentence in well-formed JDs, while the
    generic prose that floods JD matching (closely, critical, deliver)
    does not. Sentence-start capitals are rejected — every English
    sentence starts capitalized, which would re-admit the prose flood.
    """
    for m in re.finditer(
            r"(?<![A-Za-z0-9#.+-])" + re.escape(term) + r"(?![A-Za-z0-9#.+-])",
            jd_text, re.I):
        if not m.group(0)[0].isupper():
            continue
        pre = jd_text[:m.start()].rstrip()
        if pre and pre[-1] not in ".!?\n":
            return True
    return False


def _jd_terms(jd_text, body):
    """Candidate-technical terms the JD actually asks for: vocabulary and
    bullet-tool terms the JD also names, minus generic stopwords. Empty
    when jd_text is empty/garbage — callers fall back to the JD-blind
    ranking.

    Vocab-derived terms (proficiencies, Tools lines, job titles — the
    candidate's CLAIMED tech) match anywhere in the JD. Bullet-only terms
    must additionally pass _jd_capitalized: they are the prose-flood
    source, and a tool name is a proper noun.

    A GENERIC-HIT-RATE GUARD discards any surviving term that matches more
    than half of the document's bullets: such a term is prose the stop list
    missed, not technology — keeping it would "protect" half the resume and
    stall the DROP PLAN (the consulting-JD flood this guard exists for).
    """
    jd_low = jd_text.lower()
    terms = set()
    for t in _vocab_terms(body):
        # "c#"/"c++"/"f#" are length-2 but unambiguous tech terms.
        if (len(t) < 3 and not re.search(r"[#+]", t)) or t in JD_STOP \
                or re.fullmatch(r"[0-9.]+\w*", t):
            continue
        if t in jd_low:
            terms.add(t)
    for t in _bullet_terms(body):
        if t in jd_low and (_jd_capitalized(jd_text, t)
                            or t in CORE_TECH_NOUNS):
            terms.add(t)
    if terms:
        bullets = _all_bullet_texts(body)
        if len(bullets) >= 6:
            texts_low = [b.lower() for b in bullets]
            generic = set()
            for t in terms:
                hits = sum(1 for b in texts_low if _jd_hits(b, {t}))
                if hits > 0.5 * len(texts_low):
                    generic.add(t)
            terms -= generic
    return terms


JD_SHORT_WORDS = 100  # below this, a --jd file is likely a summary, not the posting


def _jd_report(jd_file, jd_text, jd_terms):
    """Lines describing the --jd ranking (printed before the page math).

    Prints the full extracted term list (not just the first 8) plus the JD's
    word count, so a term missing from a paraphrased or summarized JD file
    is visible at a glance. A file under JD_SHORT_WORDS words gets a
    fidelity note (advisory — a recruiter's message is legitimately short).
    """
    words = len(jd_text.split())
    if not jd_terms:
        return [
            f"JD-aware ranking: no candidate-tech terms in {jd_file} "
            f"intersect the resume's vocabulary — falling back to the "
            f"JD-blind ranking; check the file is the raw JD text.",
        ]
    lines = [
        f"JD-aware ranking: {len(jd_terms)} term(s) matched from "
        f"{jd_file} ({words} words)",
        textwrap.fill(
            ", ".join(sorted(jd_terms)),
            width=76,
            initial_indent="  ",
            subsequent_indent="  ",
        ),
    ]
    if words < JD_SHORT_WORDS:
        lines.append(
            f"NOTE: {jd_file} is only {words} words — if it is the full "
            f"posting, verify it was pasted verbatim (paraphrasing can "
            f"drop match terms); a recruiter's message is fine."
        )
    return lines


def _jd_hits(text, jd_terms):
    """Sorted list of JD terms present in ``text`` (WHOLE-WORD match,
    lowercase).

    Word-boundary matching, not substring: the substring form made the
    generic token "lead" match "leader/leadership/leading" and "flow"
    match "workflow", protecting bullets that merely share a prose word
    with the JD. Multi-word terms keep their space-separated phrase form;
    single tokens must not be flanked by token characters
    (``[a-z0-9#.+-]``, the same class _bullet_terms tokenizes with).

    Plural tolerance is BIDIRECTIONAL — a singular/plural pair is the SAME
    evidence: a term ending in ``s`` also matches its singular stem as a
    whole word (the JD asks for "API integrations", the bullet says
    "integration test"), and a singular term also matches its ``s``-plural
    (JD: "integration"; bullet: "partner integrations"; JD: "API";
    resume line: "REST APIs"). Keeps genuinely-technical lines (an API
    proficiencies line vs the JD's "APIs") from being misread as off-JD
    cut candidates.
    """
    low = text.lower()
    out = []
    for t in jd_terms:
        if " " in t:
            if t in low:
                out.append(t)
            continue
        cands = {t}
        if len(t) >= 4 and t.endswith("s"):
            cands.add(t[:-1])
        if len(t) >= 3:
            cands.add(t + "s")
        for c in cands:
            if re.search(
                    r"(?<![a-z0-9#.+-])" + re.escape(c) + r"(?![a-z0-9#.+-])",
                    low):
                out.append(t)
                break
    return sorted(out)


def _concept_hits(text):
    """JD practice phrases present in ``text`` (JD_CONCEPTS)."""
    low = text.lower()
    return [c for c in JD_CONCEPTS if c in low]


def _weakness_key(text):
    """Deterministic weakness sort key for a bullet: weakest first.

    Order: (1) no hard number + generic phrasing (clearest drop), (2) no
    hard number, (3) hard number present (strongest — keep). Ties break
    toward LONGER text (cutting it saves more rendered lines).
    """
    low = text.lower()
    has_number = bool(_NUMBER.search(text))
    generic = any(phrase in low for phrase in GENERIC_PHRASES)
    return (1 if has_number else 0,
            0 if generic else 1,
            -len(text))


def _is_protected(text, protect):
    """True if ``text`` contains any ``protect`` phrase (case-insensitive)."""
    low = text.lower()
    return any(p.lower() in low for p in protect)


def _jd_kept(text, jd_terms):
    """True if JD evidence (a matched JD term or a JD practice phrase)."""
    return bool(_jd_hits(text, jd_terms)) or bool(_concept_hits(text))


def _suggest_drops(bullet_texts, budget, protect=(), jd_terms=()):
    """The `budget` weakest bullets (weakest first), deterministically.

    Bullets containing a ``protect`` phrase are **never** suggested — the
    budget is filled exclusively from unprotected bullets.  With ``jd_terms``
    (from --jd), bullets carrying JD evidence (a matched term or a JD
    practice phrase) are excluded the same way, while any non-JD bullet
    remains — so a Cypress bullet stops being cuttable the moment the JD
    asks for Cypress.  When the budget exceeds the unprotected supply,
    returns only what is available (a short list); callers should surface
    the shortfall to the user.
    """
    if budget <= 0 or not bullet_texts:
        return []
    cuttable = [t for t in bullet_texts
                if not _is_protected(t, protect) and not _jd_kept(t, jd_terms)]
    ranked = sorted(cuttable, key=_weakness_key)
    return ranked[:budget]


def _drop_suggestions(bullet_texts, budget, all_texts=None, protect=(),
                      jd_terms=()):
    """[(find_p_prefix, full_bullet_text)] for the `budget` weakest cuttable
    bullets — the structured form behind the DROP PLAN's copy-pasteable
    lines, consumed by squeeze_resume.py's auto loop so it applies exactly
    what the plan names.
    """
    out = []
    unique_against = all_texts if all_texts else bullet_texts
    for text in _suggest_drops(bullet_texts, budget, protect=protect,
                               jd_terms=jd_terms):
        try:
            idx = unique_against.index(text)
        except ValueError:
            continue
        prefix = de.shortest_unique_prefix(unique_against, idx, min_len=6)
        if prefix is None:
            continue
        out.append((prefix, text))
    return out

def _drop_plan_lines(bullet_texts, budget, all_texts=None, protect=(),
                     jd_terms=()):
    """Copy-pasteable find_p lines for the `budget` weakest bullets.

    Each line is ``find_p(ps, "<unique prefix>")  # <full bullet>`` so the
    agent can paste the exact cut into the tailor script with zero
    render-measure iterations. Uniqueness is checked against ``all_texts``
    (pass the FULL document's paragraph texts so the emitted prefix stays
    unique document-wide), falling back to the role's own bullets.
    ``protect`` phrases and ``jd_terms`` keep JD-critical bullets out of the
    suggestions.
    """
    return [
        f'find_p(ps, "{prefix}")  # {text}'
        for prefix, text in _drop_suggestions(
            bullet_texts, budget, all_texts=all_texts, protect=protect,
            jd_terms=jd_terms)
    ]


_DROP_ACTION = re.compile(r"^drop (\d+) bullet\(s\)")


def _protected_count(bullets, protect=(), jd_terms=()):
    """How many of ``bullets`` carry JD/protect evidence (never suggested
    for cutting while weaker bullets remain)."""
    return sum(1 for b in bullets
               if _is_protected(b, protect) or _jd_kept(b, jd_terms))


def _dead_end_roles(plan, roles, protect=(), jd_terms=()):
    """Role keys whose "drop N bullet(s)" budget exceeds their unprotected
    bullets: meeting the budget means cutting JD-matched/protected content.
    The honest fixes are TOP-BLOCK RECLAIM CANDIDATES, a Tools-line trim,
    or a whole-role drop — not slicing kept bullets."""
    dead = []
    for key, action, _saved in plan:
        m = _DROP_ACTION.match(action)
        if not m:
            continue
        role = next((r for r in roles if r["key"] == key), None)
        if not role:
            continue
        bullets = role.get("bullet_texts") or []
        n = int(m.group(1))
        protected = _protected_count(bullets, protect=protect,
                                     jd_terms=jd_terms)
        if n > len(bullets) - protected and protected > 0:
            dead.append(key)
    return dead


def _top_role_batch(matched, plan, per, required, tools_savings=0,
                    top_block_count=0, protect=(), jd_terms=()):
    """Size the most-recent role's trim batch — the residual-gap closer.

    The BATCH RECLAIM PLAN is oldest-first and stops as soon as its listed
    savings reach the gap. But dead-end budgets (JD-protected bullets)
    overstate what the oldest roles can actually give, and TOP-BLOCK lines
    and Tools de-wraps are the only other removal sources. When even those
    fall short of ``required``, the honest remaining source is the
    most-recent role's weakest UNPROTECTED bullets — the failure this
    replaces is the author inventing levers to close the gap (hand-
    shortening kept bullets from two rendered lines to one), because the
    tool's plan visibly cannot reach the target.

    Returns ``(batch_entry, adjusted_plan, feasible)`` where ``batch_entry``
    is ``(top_key, action, saved_lines)`` or ``None`` when the feasible
    cuts already close the gap (or the top role has no unprotected
    bullet to give); ``adjusted_plan`` drops any superseded dead-end entry
    for the top role (the batch is the authoritative sizing for it); and
    ``feasible`` is the total line savings the removals above can actually
    deliver (dead-end budgets shrunk to unprotected counts, + Tools
    de-wraps, + TOP-BLOCK lines) — so main() can state honestly when the
    gap cannot close without cutting JD-matched content.
    """
    if not matched:
        return None, list(plan), 0.0
    by_key = {r["key"]: r for r, _sp, _ep, _l in matched}
    top_key = matched[0][0]["key"]  # matched is document order: most-recent first
    feasible = 0.0
    adjusted = []
    for key, action, saved in plan:
        m = _DROP_ACTION.match(action)
        if not m:
            feasible += saved  # whole-role drop: feasible by definition
            adjusted.append((key, action, saved))
            continue
        role = by_key.get(key) or {}
        bullets = role.get("bullet_texts") or []
        prot = _protected_count(bullets, protect=protect, jd_terms=jd_terms)
        take = min(int(m.group(1)), max(0, len(bullets) - prot))
        if take > 0:
            feasible += take * per
        if key == top_key:
            continue  # superseded: the batch below is the authoritative sizing
        adjusted.append((key, action, saved))
    feasible += tools_savings + top_block_count
    shortfall = required - feasible
    top_bullets = matched[0][0].get("bullet_texts") or []
    top_protected = _protected_count(top_bullets, protect=protect,
                                     jd_terms=jd_terms)
    unprotected = max(0, len(top_bullets) - top_protected)
    if shortfall <= 0 or unprotected <= 0:
        return None, adjusted, feasible
    n = min(unprotected, math.ceil(shortfall / per))
    saved = n * per
    return ((top_key, f"drop {n} bullet(s) (saves ~{saved:.0f} lines)", saved),
            adjusted, feasible)


def _apply_simulate(docx_path, drop_prefixes, out_path):
    """Copy ``docx_path`` to ``out_path`` and drop the WHOLE roles named by
    each prefix (docx_edit.drop_role) in the copy — the seniority-alignment
    what-if behind ``--simulate``. Returns ``(out_path, dropped)`` where
    ``dropped`` lists the company-header texts actually removed (prefixes
    that matched nothing are absent, with drop_role's stderr warning).
    The original file is never modified."""
    shutil.copyfile(docx_path, out_path)
    root, body, names, data, _ = de.load(out_path)
    dropped = []
    for prefix in drop_prefixes:
        ps = de.paras(body)
        anchor = de.find_p(ps, prefix)
        if anchor is None:
            continue  # drop_role already warned; nothing removed
        header = de.text_of(anchor)
        before = len(ps)
        de.drop_role(body, prefix)
        if len(de.paras(body)) < before:
            dropped.append(header)
    de.save(out_path, root, names, data, drift_key="simulate-temp")
    return out_path, dropped


def _drop_sections(plan, roles, all_texts=None, protect=(), jd_terms=()):
    """Turn a BATCH RECLAIM PLAN into per-role DROP PLAN sections.

    Each "drop N bullet(s)" plan entry (keyed by role key) becomes a
    section listing the N weakest bullets as copy-pasteable ``find_p(ps, ...)``
    lines. "consider dropping the whole role" entries produce no section —
    the header/tools lines save more than any single bullet, and the
    seniority decision is the user's, not the ranker's.

    With ``jd_terms`` (--jd), JD-evidence bullets are excluded from the
    suggestions and listed under "JD-matched (kept)" with the terms that
    matched — so the plan shows WHY a bullet was kept instead of making the
    agent re-derive it by reading each suggestion against the JD.
    """
    sections = []
    for key, action, _saved in plan:
        m = _DROP_ACTION.match(action)
        if not m:
            continue
        role = next((r for r in roles if r["key"] == key), None)
        if not role:
            continue
        n = int(m.group(1))
        bullets = role.get("bullet_texts") or []
        jd_kept = [(b, _jd_hits(b, jd_terms)) for b in bullets
                   if _jd_hits(b, jd_terms)]
        concept_kept = [(b, _concept_hits(b)) for b in bullets
                        if _concept_hits(b) and not _jd_hits(b, jd_terms)]
        protected_count = _protected_count(bullets, protect=protect,
                                           jd_terms=jd_terms)
        unprotected_count = len(bullets) - protected_count
        lines = _drop_plan_lines(bullets, n, all_texts=all_texts,
                                 protect=protect, jd_terms=jd_terms)
        section = [f"DROP PLAN ({key}): drop {n} of {len(bullets)} bullets"]
        if jd_kept or concept_kept:
            section.append(
                "  JD-matched (kept) — never suggested while weaker "
                "bullets remain:"
            )
            for b, hits in jd_kept:
                section.append(f"    - {b[:68]}  [{' , '.join(hits)}]")
            for b, hits in concept_kept:
                section.append(
                    f"    - {b[:68]}  [practice: {', '.join(hits)}]"
                )
        if n > unprotected_count and protected_count > 0:
            if not lines:
                section.append(
                    f"  ALL {len(bullets)} bullet(s) protected — budget={n} "
                    "cannot be met without cutting JD/protected content. "
                    "Cuts can still come from ANY section: the TOP-BLOCK "
                    "RECLAIM CANDIDATES (proficiencies/certs), a Tools-line "
                    "trim, or a whole-role drop (seniority decision; check "
                    "the gap warning in the BATCH RECLAIM PLAN)."
                )
            else:
                section.append(
                    f"  NOTE: budget={n} but only {unprotected_count} "
                    f"unprotected bullet(s) — {protected_count} excluded "
                    f"(JD-matched/protected)."
                )
        if lines:
            section.append("  weakest-first (generic/no-number first — review each")
            section.append("  against the JD before cutting):")
            for line in lines:
                section.append(f"    {line}")
        sections.append("\n".join(section))
    return sections


def _batch_section(batch, role, header, all_texts=None, protect=(),
                   jd_terms=()):
    """Render the TOP-ROLE TRIM BATCH section — the residual-gap closer.

    ``batch`` is ``(key, action, saved_lines)`` from
    :func:`_top_role_batch`. ``header`` is the caller-provided first line
    (e.g. 'TOP-ROLE TRIM BATCH (Acme; closes ...)'). Returns the section
    as a multi-line string, or ``None`` when the batch/role is empty.
    """
    _key, action, _saved = batch
    m = _DROP_ACTION.match(action)
    if not m or role is None:
        return None
    n = int(m.group(1))
    bullets = role.get("bullet_texts") or []
    jd_kept = [(b, _jd_hits(b, jd_terms)) for b in bullets
               if _jd_hits(b, jd_terms)]
    concept_kept = [(b, _concept_hits(b)) for b in bullets
                    if _concept_hits(b) and not _jd_hits(b, jd_terms)]
    lines = _drop_plan_lines(bullets, n, all_texts=all_texts,
                             protect=protect, jd_terms=jd_terms)
    section = [header]
    if jd_kept or concept_kept:
        section.append("  JD-matched (kept) — never suggested while weaker "
                       "bullets remain:")
        for b, hits in jd_kept:
            section.append(f"    - {b[:68]}  [{' , '.join(hits)}]")
        for b, hits in concept_kept:
            section.append(
                f"    - {b[:68]}  [practice: {', '.join(hits)}]"
            )
    if lines:
        section.append("  weakest-first (generic/no-number first — review each")
        section.append("  against the JD before cutting):")
        for line in lines:
            section.append(f"    {line}")
    return "\n".join(section)


def _layout_hints(matched, pages_text, capacity):
    """Page-fill table plus widow/underfill notes.

    A widow in the render is a role header that is the LAST line of a page
    while its body starts the next page — the exact failure mode of a
    "role header stranded at the bottom" that a line-count budget cannot
    see. An underfilled page whose next page starts with a role header is
    usually the same keep-with/heading-pagination effect; report it with a
    concrete line-cut suggestion so the fix is a batch action, not a
    cut-render-cut loop.
    """
    fills = _page_fill(pages_text)
    out = []
    for i, f in enumerate(fills, start=1):
        pct = (100 * f // capacity) if capacity else 0
        out.append(f"  page {i}: {f:3} lines ({pct}% of max {capacity})")
    if capacity and len(fills) > 1:
        for i, f in enumerate(fills[:-1], start=1):
            if f < 0.85 * capacity:
                nxt = _page_lines(pages_text[i])  # first line of page i+1
                nxt_first = nxt[0][:60] if nxt else "(blank)"
                out.append(
                    f"  NOTE: page {i} underfilled — holds {f} of ~{int(capacity)} lines "
                    f"({(100 * f // capacity)}% of max); page {i + 1} starts "
                    f"with: {nxt_first} — likely a keep-with/widow break; "
                    f"trimming ~{max(1, int(0.85 * capacity - f))} earlier "
                    f"line(s) may pull it up"
                )
    flat = [(pi, _norm(l), l) for pi, ptext in
            enumerate(pages_text, start=1)
            for l in _page_lines(ptext)]
    keys = [r["key"] for r, *_ in matched]
    for r, sp, ep, rendered in matched:
        idx = _role_header_flat(flat, r["key"])
        if idx is not None and idx + 1 < len(flat):
            on_page_break = flat[idx][0] != flat[idx + 1][0]
            at_page_end = idx == 0 or flat[idx][0] == flat[idx - 1][0]
            if on_page_break and at_page_end:
                prev = _preceding_role_key(flat, idx, keys)
                if prev:
                    out.append(
                        f"  WIDOW: {r['key'][:44]} header is the last line of page "
                        f"{flat[idx][0]}; its body starts page {flat[idx + 1][0]} — "
                        f"reclaim ~2 line(s) from the {prev[:44]} block (the "
                        f"content preceding the widow) to pull the header up, "
                        f"or merge bullets"
                    )
                else:
                    out.append(
                        f"  WIDOW: {r['key'][:44]} header is the last line of page "
                        f"{flat[idx][0]}; its body starts page {flat[idx + 1][0]} — "
                        f"trim earlier content or merge bullets"
                    )
    return out


def _sparse_last_page_note(total_pages, target, fills, capacity,
                           overflow_lines=0):
    """Signal to reconsider the page target when the last page is sparse.

    The failure mode (a real session): a senior/Staff resume was built to
    the agreed 3-page target — "ON target" — and the page-fill table showed
    the last page at 43%, then 20%, then 13% as compression passes landed.
    SKILL Step 3's "target 2; accept 3 for senior/Staff" gave no rule for
    WHEN to accept 3, so the agent waffled through ~8 extra measure/render
    cycles re-deciding the target mid-flight. The tool CAN see the one
    signal that settles it: a sparse final page. SKILL Step 3's rule (added
    alongside this note): re-target one page lower and re-measure BEFORE
    cutting any JD-matched bullet — cutting JD-matched content to fill a
    sparse page is the trap.

    Fires whenever the last page fills <50% of capacity on a multi-page
    document; at/under target the message points one page lower, over
    target it points out that the reclaim gap is roughly the sparse tail
    itself and a dead-ending DROP PLAN means the target — not the bullets —
    is what to revisit.
    """
    if not capacity or len(fills) < 2:
        return None
    last = fills[-1]
    pct = 100 * last // capacity
    if pct >= 50:
        return None
    if total_pages > target:
        return (f"TARGET NOTE: last page is only {pct}% full ({last} of "
                f"~{capacity} lines). The ~{overflow_lines}-line gap to "
                f"{target} page(s) is roughly this sparse tail itself; if "
                f"the DROP PLAN dead-ends on JD-matched content, revisit "
                f"the page target (one page lower) and re-measure BEFORE "
                f"cutting JD-matched bullets (SKILL Step 3).")
    lower = f" Re-target one page lower ({target - 1}) and re-measure" \
            if target > 1 else " Re-measure against a lower target"
    return (f"TARGET NOTE: last page is only {pct}% full ({last} of "
            f"~{capacity} lines) — a sparse final page reads as "
            f"unpolished.{lower} BEFORE cutting any JD-matched bullet to "
            f"fill it (SKILL Step 3).")


def _measured_lines_per_bullet(matched):
    """Average rendered lines per bullet, measured from THIS render.

    Attributes each role's rendered lines to bullets by subtracting a
    2-line header block (company + job title) and ~1 line for the Tools
    line (tailored tools lines are trimmed to one line; wrapping adds on
    average well under a line). Honest reclaim math: the old hardcoded
    "~2 lines per bullet" budget undercounted dense bullets, which is why
    compression turned into cut-render-cut cycles.
    """
    total_bullet_lines = 0.0
    bullet_count = 0
    for r, sp, ep, rendered in matched:
        n = r["bullets"]
        if not n:
            continue
        tools_len = 1.0 if r["has_tools"] else 0.0
        bullet_lines = max(1, rendered - 2.0 - tools_len)
        total_bullet_lines += bullet_lines
        bullet_count += n
    return total_bullet_lines / bullet_count if bullet_count else 2.0


def _reclaim_batch(matched, per_bullet, gap):
    """Oldest-first concrete cut list sized to `gap` (lines).

    The skill rule is: cut the OLDEST roles first. For each oldest role with
    2+ bullets, take as many bullet cuts as the budget needs (keeping at
    least one bullet per role); a 1-bullet role is cheaper to drop whole
    (header + tools + bullets) once it is the oldest — that is the cleanest
    page math and also compresses the timeline. Returns (plan, remaining)
    where plan is [(role_key, action, saved_lines)].
    """
    plan = []
    remaining = gap
    for r, sp, ep, rendered in reversed(matched):
        if remaining <= 0:
            break
        n = r["bullets"]
        key = r["key"]
        if n >= 2:
            take = min(n - 1, max(1, math.ceil(remaining / per_bullet)))
            saved = take * per_bullet
            plan.append((key, f"drop {take} bullet(s) (saves ~{saved:.0f} lines)", saved))
            remaining -= saved
        else:
            plan.append((key, f"consider dropping the whole role (saves ~{rendered:.0f} lines)", rendered))
            remaining -= rendered
    return plan, remaining


def _target_from_args(kept):
    """(target, is_default) from the positional args or TARGET_PAGES env."""
    if len(kept) > 1:
        return int(kept[1]), False
    if "TARGET_PAGES" in os.environ:
        return int(os.environ["TARGET_PAGES"]), False
    return 2, True


def _default_target_note(total_pages, target, is_default):
    """Reminder when the reclaim gap is measured against the default target.

    The failure mode (a real session): the agreed Step-3 target was 3 for a
    senior/Staff resume, but measure ran without an explicit target and
    reported "OVER by 2 pages / drop ~117 lines" against the 2-page default
    — an irrelevant reading that invites over-cutting. The tool cannot know
    the agreed target, so it flags the one thing it CAN detect: the default
    is in play while the document is over it. Nothing prints when the target
    was passed explicitly (positionally or via TARGET_PAGES) or the document
    fits the default.
    """
    if not is_default or total_pages <= target:
        return None
    return ("NOTE: no page target given — the gap above is measured against "
            "the 2-page default. Pass the agreed Step-3 target (senior/Staff "
            "= 3) so the reclaim plan measures the goal actually agreed on.")


def main():
    argv = [a for a in sys.argv[1:]]
    protect = []
    jd_file = None
    simulate = []
    kept = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--protect":
            protect.append(argv[i + 1])
            i += 2
        elif a == "--jd":
            jd_file = argv[i + 1]
            i += 2
        elif a == "--simulate":
            simulate.append(argv[i + 1])
            i += 2
        else:
            kept.append(a)
            i += 1
    if len(kept) < 1:
        print("usage: measure_resume.py <resume.docx> [TARGET_PAGES] "
              "[--jd <raw-JD.txt>] [--protect \"<JD-critical phrase>\"] "
              "[--simulate <company-prefix>]",
              file=sys.stderr)
        print("  Renders the docx, reports per-role rendered line costs and "
              "the reclaim gap to TARGET_PAGES (default 2, or env).",
              file=sys.stderr)
        print("  --jd <file>: raw job-description text. Bullets whose text "
              "matches a candidate-tech term the JD asks for, or a named JD "
              "practice (mentorship, shift-left), are excluded from the DROP "
              "PLAN and listed as 'JD-matched (kept)' — the scorer alone "
              "cannot know the JD.",
              file=sys.stderr)
        print("  --protect: pass repeatedly; bullets containing the phrase "
              "are never suggested for cutting (candidate-specific facts "
              "the JD text cannot name, e.g. a confirmed Snyk duty).",
              file=sys.stderr)
        print("  --simulate: pass repeatedly; drops each named WHOLE role "
              "(company-header prefix) in a temp copy and measures THAT — "
              "the seniority-alignment what-if. The file on disk is never "
              "modified; compare the printed TIMELINE against the JD's ask.",
              file=sys.stderr)
        sys.exit(2)
    docx = kept[0]
    target, default_target = _target_from_args(kept)

    with tempfile.TemporaryDirectory() as td:
        if simulate:
            sim_path = os.path.join(td, "simulated.docx")
            docx, dropped = _apply_simulate(docx, simulate, sim_path)
            print("SIMULATED seniority alignment — the file on disk was "
                  "NOT modified:")
            for header in dropped:
                print(f"  dropped whole role: {header}")
            missing = len(simulate) - len(dropped)
            if missing:
                print(f"  ({missing} prefix(es) matched nothing — see "
                      f"warnings above)")
            print("  Compare the TIMELINE below against the JD's ask; run "
                  "without --simulate to apply the drops for real.")
            print()

        root, body, _, _, _ = de.load(docx)
        roles = _roles(body)

        jd_terms = set()
        if jd_file:
            try:
                with open(jd_file, encoding="utf-8", errors="replace") as f:
                    jd_text = f.read()
            except OSError as e:
                print(f"error: cannot read --jd file {jd_file}: {e}",
                      file=sys.stderr)
                sys.exit(2)
            jd_terms = _jd_terms(jd_text, body)
            for line in _jd_report(jd_file, jd_text, jd_terms):
                print(line)

        pdf = _render_pdf(docx, td)
        pages_text = _pdf_pages_text(pdf)
        total_pages = len(pages_text)

    matched = _match_roles_to_pages(roles, pages_text)
    fixed_top = _fixed_top_cost(pages_text, roles)
    edu = _education_cost(pages_text)
    capacity = max(_page_fill(pages_text)) if pages_text else 0
    role_lines = sum(m[3] for m in matched)

    print(f"PAGES: {total_pages}  (target: {target})")
    over = total_pages - target
    overflow_lines = sum(len(_page_lines(p)) for p in pages_text[target:]) if over > 0 else 0
    if over > 0:
        print(f"OVER by {over} page(s) — ~{overflow_lines} rendered line(s) "
              f"spilled past page {target}.")
    elif over < 0:
        print(f"UNDER target by {-over} page(s) — room to expand.")
    else:
        print("ON target.")
    note = _default_target_note(total_pages, target, default_target)
    if note:
        print(note)

    # Visible timeline span — the number behind Step 3's seniority-alignment
    # decision (compare against the JD's "N+ years" ask, NOT the candidate's
    # total career).
    first, last = _visible_span([r["raw"] for r in roles])
    if first is not None:
        print(f"TIMELINE: roles span {first:.0f} – {last:.0f} "
              f"(~{last - first:.1f} years shown)")

    print()
    print(f"Fixed top block (Summary+Proficiencies+Certifications+chrome): "
          f"{fixed_top} rendered lines")
    print("  (the WHOLE resume tailors to the JD — cuts can come from ANY")
    print("   section; see TOP-BLOCK RECLAIM CANDIDATES below when over "
          "target)")
    print()
    print("Per-role rendered cost (oldest roles LAST — cut from the bottom):")
    print(f"  {'Role':<34} {'pg':>4} {'lines':>5} {'bullets':>7} {'tools':>5}")
    for r, sp, ep, lines in matched:
        name = r["key"]
        if len(name) > 33:
            name = name[:30] + "..."
        pg_s = f"{sp}-{ep}" if (sp and ep and ep != sp) else (str(sp) if sp is not None else "?")
        print(f"  {name:<34} {pg_s:>4} {lines:>5} {r['bullets']:>7} "
              f"{'Y' if r['has_tools'] else '-':>5}")
    print(f"  {'Education (tail)':<34} {'':>4} {edu:>5}")
    print(f"  {'TOTAL':<34} {'':>4} {fixed_top + role_lines + edu:>5}")

    # Tools lines that wrap — each costs ~1 extra rendered line; name the
    # roles so the agent can trim them without re-measuring.
    flat = _flat_from_pages(pages_text)
    wrapped = _wrapped_tools(flat, matched)
    if wrapped:
        print()
        print("TOOLS LINES THAT WRAP (each costs ~1 rendered line; trim to "
              "the measured budget):")
        for key, value_chars, fit_chars, preview in wrapped:
            over = value_chars - fit_chars
            print(f"  {key} — value is {value_chars} chars, wraps after "
                  f"~{fit_chars} — cut ~{over} chars (≈2-4 tools)")
            print(f"    \"{preview}\"")

    # Reclaim suggestion: size cuts to the overflow gap, from oldest roles.
    if over > 0:
        print()
        print(f"RECLAIM PLAN: drop ~{overflow_lines} rendered line(s) to reach "
              f"{target} page(s).")

        # Measured math + concrete batch (replaces an earlier hardcoded
        # "~2 lines per bullet" estimate that undercounted dense bullets).
        per = _measured_lines_per_bullet(matched)
        required = overflow_lines + per
        plan, remaining = _reclaim_batch(matched, per, required)
        # TOP-BLOCK candidates are a planned removal source, so compute
        # them BEFORE sizing the top-role batch; printed below in the same
        # place as before.
        top = _top_block_candidates(body, jd_terms)
        # The oldest-first plan overstates what dead-end roles can give;
        # when TOP-BLOCK + Tools de-wraps + feasible oldest cuts still fall
        # short, size a TOP-ROLE TRIM BATCH here (see _top_role_batch) —
        # the author then pastes emitted find_p lines instead of inventing
        # levers (hand-shortening kept bullets) to close the gap.
        batch, plan, feasible = _top_role_batch(
            matched, plan, per, required, tools_savings=len(wrapped),
            top_block_count=len(top), protect=protect, jd_terms=jd_terms)
        matched_roles = [m[0] for m in matched]
        print()
        print(f"MEASURED: ~{per:.1f} rendered lines per bullet (this render)")
        print("BATCH RECLAIM PLAN (oldest roles first; +1-bullet buffer):")
        for key, action, saved in plan:
            print(f"  - {key}: {action}")
            if action.startswith("consider dropping"):
                gap = _gap_if_dropped(matched_roles, key)
                if gap:
                    print(f"      WARNING: dropping this (interior) role "
                          f"opens a ~{gap}-month employment gap between its "
                          f"surviving neighbors — prefer cutting from the "
                          f"oldest role, or drop the whole gapless tail.")
        residual = required - feasible
        closes = batch is not None and math.isclose(batch[2], residual,
                                                 abs_tol=0.001)
        if batch is not None:
            print(f"  - residual ~{residual:.0f} line(s) after the feasible "
                  f"cuts above — TOP-ROLE TRIM BATCH below "
                  + ("closes it" if closes else
                     "is the largest remaining safe source (its "
                     "JD-protected bullets stay)"))
        elif remaining > 0:
            print(f"  (still ~{remaining:.0f} line(s) over plan — cut past the "
                  f"listed bullet(s) or trim Tools lines)")
        print("  Generic savings: drop blank inter-role spacers via "
              "remove_empty (~1 line each)")

        # Dead-end plans: roles whose budget cannot be met from unprotected
        # bullets — say so at the top so the fix is TOP-BLOCK/Tools/whole-
        # role, not slicing JD-matched bullets.
        dead = _dead_end_roles(plan, roles, protect=protect,
                               jd_terms=jd_terms)
        if dead:
            print()
            print("DEAD-END PLANS: " + ", ".join(dead) + " cannot meet "
                  "their cut budget from unprotected bullets — prefer the "
                  "TOP-BLOCK RECLAIM CANDIDATES, a Tools-line trim, or a "
                  "whole-role drop (seniority decision) over cutting "
                  "JD-matched bullets.")

        # TOP-BLOCK CANDIDATES: off-JD proficiency/certification lines are
        # first-class cuts too (line-costed, copy-pasteable), not just role
        # bullets — the whole resume tailors to the JD. (Computed above so
        # the top-role batch can size against them.)
        if top:
            print()
            print("TOP-BLOCK RECLAIM CANDIDATES (Technical Proficiencies / "
                  "Certifications lines with no JD evidence; ~1 line each):")
            if not jd_terms:
                print("  (no --jd given — review each against the JD before "
                      "cutting)")
            for prefix, text in top:
                print(f'    find_p(ps, "{prefix}")  # {text[:70]}')

        # The DROP PLAN: name the exact bullets each "drop N bullet(s)"
        # entry refers to, weakest-first, as copy-pasteable find_p lines
        # (uniqueness checked against the full document). No more deciding
        # WHICH of a role's bullets to cut.
        all_texts = [de.text_of(p) for p in de.paras(body)]
        sections = _drop_sections(plan, roles, all_texts=all_texts,
                                  protect=protect, jd_terms=jd_terms)
        if batch is not None:
            top_role = next((r for r in roles if r["key"] == batch[0]), None)
            batch_hdr = ("closes the residual gap after the cuts above"
                         if closes else "the largest remaining safe source")
            header = f"TOP-ROLE TRIM BATCH ({batch[0]}; {batch_hdr}): "
            section = _batch_section(batch, top_role, header,
                                     all_texts=all_texts, protect=protect,
                                     jd_terms=jd_terms)
            if section is not None:
                sections.append(section)
            if not closes:
                sections.append(
                    f"NOTE: even with the top-role batch, ~{residual - batch[2]:.0f} "
                    "line(s) remain — the gap cannot close without cutting "
                    "JD-matched content or revisiting the approved "
                    "whole-role drops with the user.")
        if batch is None and residual > 0:
            sections.append(
                f"NO SAFE PLAN: feasible removals cover ~{feasible:.0f} of "
                f"~{required:.0f} line(s) and the most-recent role has no "
                "unprotected bullet to give — the gap cannot close without "
                "cutting JD-matched content or revisiting the approved "
                "whole-role drops with the user.")
        if sections:
            print()
            for section in sections:
                print(section)
                print()

    print()
    print("Page fill (capacity = fullest page from this render):")
    for line in _layout_hints(matched, pages_text, capacity):
        print(line)
    sparse = _sparse_last_page_note(total_pages, target,
                                    _page_fill(pages_text), capacity,
                                    overflow_lines)
    if sparse:
        print(sparse)


if __name__ == "__main__":
    main()
