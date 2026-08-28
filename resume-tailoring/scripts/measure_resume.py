"""Measure a resume's rendered length and plan compression to a page budget.

The subtractive tailoring flow (copy master, cut down) iterates well when you
know the budget up front. This tool closes that gap: it renders the .docx to
PDF once, attributes rendered lines to each role, and reports how many lines
must be reclaimed to hit a target page count — so cuts can be planned as a
batch instead of discovered through a cut-render-cut-render loop.

Usage::

    python3 scripts/measure_resume.py <resume.docx> [TARGET_PAGES]
    TARGET_PAGES=2 python3 scripts/measure_resume.py <resume.docx>

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

import os
import re
import subprocess
import sys
import tempfile

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
COMPANY_STYLE = "CompanyBlock"
DATE_RE = re.compile(r"\d{1,2}/\d{4}")  # dates on role headers, e.g. 02/2019
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


def _company_key(text):
    """The matchable company-portion of a role-header line (dates stripped).

    The master concatenates the company line and the date range with no
    separator (e.g. 'Company ABC, Phoenix, AZ02/2019 – 04/2020'); the
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
        bullets  – count of numbered bullets (cuttable items)
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
            cur = {"key": _company_key(txt),
                   "bullets": 0, "has_tools": False}
        elif cur is not None:
            # Count numbered bullets (numId not None and not "0", or a
            # paragraph style whose numbering lives on the style, e.g.
            # Word's built-in List Bullet); flag tools lines.
            if (numId is not None and numId != "0") or style in BULLET_STYLES:
                cur["bullets"] += 1
            elif txt.strip().lower().startswith("tool") and "technolog" in txt.lower():
                cur["has_tools"] = True
    if cur:
        roles.append(cur)
    return roles


def _match_roles_to_pages(roles, pages_text):
    """Attribute rendered lines to each role by locating its header in the
    PDF text. Returns list of (role, start_page_1based, rendered_lines).
    """
    # Flatten pages to (page_idx, line) preserving order, for region counting.
    flat = []  # (page_1based, norm_line, raw_line)
    for pi, ptext in enumerate(pages_text, start=1):
        for l in _page_lines(ptext):
            flat.append((pi, _norm(l), l))

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
            results.append((r, None, 0))
            continue
        # End = next matched role start, else Education heading, else EOF.
        e = find_education_line(s)
        for nxt in role_starts[i + 1:]:
            if nxt is not None:
                e = nxt
                break
        rendered = e - s
        results.append((r, flat[s][0], rendered))
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


def main():
    if len(sys.argv) < 2:
        print("usage: measure_resume.py <resume.docx> [TARGET_PAGES]",
              file=sys.stderr)
        print("  Renders the docx, reports per-role rendered line costs and "
              "the reclaim gap to TARGET_PAGES (default 2, or env).",
              file=sys.stderr)
        sys.exit(2)
    docx = sys.argv[1]
    target = int(sys.argv[2]) if len(sys.argv) > 2 else int(
        os.environ.get("TARGET_PAGES", "2"))

    root, body, _, _, _ = de.load(docx)
    roles = _roles(body)

    with tempfile.TemporaryDirectory() as td:
        pdf = _render_pdf(docx, td)
        pages_text = _pdf_pages_text(pdf)
        total_pages = len(pages_text)

    matched = _match_roles_to_pages(roles, pages_text)
    fixed_top = _fixed_top_cost(pages_text, roles)
    edu = _education_cost(pages_text)
    role_lines = sum(m[2] for m in matched)

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

    print()
    print(f"Fixed top block (Summary+Proficiencies+Certifications+chrome): "
          f"{fixed_top} rendered lines (not where compression cuts happen)")
    print()
    print("Per-role rendered cost (oldest roles LAST — cut from the bottom):")
    print(f"  {'Role':<34} {'pg':>3} {'lines':>5} {'bullets':>7} {'tools':>5}")
    for r, pg, lines in matched:
        name = r["key"]
        if len(name) > 33:
            name = name[:30] + "..."
        print(f"  {name:<34} {pg!s:>3} {lines:>5} {r['bullets']:>7} "
              f"{'Y' if r['has_tools'] else '-':>5}")
    print(f"  {'Education (tail)':<34} {'':>3} {edu:>5}")
    print(f"  {'TOTAL':<34} {'':>3} {fixed_top + role_lines + edu:>5}")

    # Reclaim suggestion: size cuts to the overflow gap, from oldest roles.
    if over > 0:
        print()
        print(f"RECLAIM PLAN: drop ~{overflow_lines} rendered line(s) to reach "
              f"{target} page(s).")
        # Each bullet wraps to ~1-3 rendered lines (assume avg 2). Tools line ~1-2.
        print("Cheapest compression targets (oldest roles, then trim Tools):")
        cuttable = [(r["key"], r["bullets"]) for r, _, _ in matched
                   if r["bullets"] > 1]
        for name, bullets in reversed(cuttable):
            print(f"  - {name}: has {bullets} bullets; dropping 1 saves ~2 lines")
        if any(r["has_tools"] for r, _, _ in matched):
            print("  - trim any 2-line Tools list to one line: saves ~1 line each")
        print("  - drop blank inter-role spacer paragraphs (remove_empty): "
              "saves ~1 line each")


if __name__ == "__main__":
    main()
