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

import math
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
    "GEICO, MD (Remote)06/2025 – 07/2026"). This is the number behind Step
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


# Process-y phrasing that signals a generic bullet (weakest to cut). A
# bullet with any such phrase and NO hard number ranks weakest; hard
# numbers/percentages (quantified evidence) always rank strongest.
GENERIC_PHRASES = (
    "established", "coordinated", "enhanced", "presented", "mentored",
    "assisted", "advocated", "organized", "scheduled", "attended",
    "facilitated", "streamlined", "ensured", "participated",
)
_NUMBER = re.compile(r"\d|%")


def _weakness_key(text, protect=()):
    """Deterministic weakness sort key for a bullet: weakest first.

    Order: (1) no hard number + generic phrasing (clearest drop), (2) no
    hard number, (3) hard number present (strongest — keep). Ties break
    toward LONGER text (cutting it saves more rendered lines). ``protect``
    phrases are JD-critical content the scorer cannot know about: any
    bullet containing one ranks strongest (never suggested), e.g.
    ``--protect "partner integrations"``.
    """
    low = text.lower()
    has_number = bool(_NUMBER.search(text))
    generic = any(phrase in low for phrase in GENERIC_PHRASES)
    protected = any(phrase.lower() in low for phrase in protect)
    return (1 if has_number or protected else 0,
            0 if generic else 1,
            -len(text) if not protected else 0)


def _suggest_drops(bullet_texts, budget, protect=()):
    """The `budget` weakest bullets (weakest first), deterministically.

    Returns [] when budget <= 0 or a bullet list is empty; never suggests
    more bullets than exist. Bullets containing a ``protect`` phrase are
    never suggested.
    """
    if budget <= 0 or not bullet_texts:
        return []
    ranked = sorted(bullet_texts, key=lambda t: _weakness_key(t, protect))
    return ranked[:budget]


def _drop_plan_lines(bullet_texts, budget, all_texts=None, protect=()):
    """Copy-pasteable find_p lines for the `budget` weakest bullets.

    Each line is ``find_p(ps, "<unique prefix>")  # <full bullet>`` so the
    agent can paste the exact cut into the tailor script with zero
    render-measure iterations. Uniqueness is checked against ``all_texts``
    (pass the FULL document's paragraph texts so the emitted prefix stays
    unique document-wide), falling back to the role's own bullets.
    ``protect`` phrases keep JD-critical bullets out of the suggestions.
    """
    out = []
    unique_against = all_texts if all_texts else bullet_texts
    for text in _suggest_drops(bullet_texts, budget, protect=protect):
        try:
            idx = unique_against.index(text)
        except ValueError:
            continue
        prefix = de.shortest_unique_prefix(unique_against, idx, min_len=6)
        if prefix is None:
            continue
        out.append(f'find_p(ps, "{prefix}")  # {text}')
    return out


_DROP_ACTION = re.compile(r"^drop (\d+) bullet\(s\)")


def _drop_sections(plan, roles, all_texts=None, protect=()):
    """Turn a BATCH RECLAIM PLAN into per-role DROP PLAN sections.

    Each "drop N bullet(s)" plan entry (keyed by role key) becomes a
    section listing the N weakest bullets as copy-pasteable ``find_p(ps, ...)``
    lines. "consider dropping the whole role" entries produce no section —
    the header/tools lines save more than any single bullet, and the
    seniority decision is the user's, not the ranker's.
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
        lines = _drop_plan_lines(bullets, n, all_texts=all_texts, protect=protect)
        if not lines:
            continue
        section = [f"DROP PLAN ({key}): drop {n} of {len(bullets)} bullets"]
        section.append("  weakest-first (generic/no-number first — review each")
        section.append("  against the JD before cutting):")
        for line in lines:
            section.append(f"    {line}")
        sections.append("\n".join(section))
    return sections


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
    for r, sp, ep, rendered in matched:
        idx = _role_header_flat(flat, r["key"])
        if idx is not None and idx + 1 < len(flat):
            if flat[idx][0] != flat[idx + 1][0] and (idx == 0 or flat[idx][0] == flat[idx - 1][0]):
                out.append(
                    f"  WIDOW: {r['key'][:44]} header is the last line of page "
                    f"{flat[idx][0]}; its body starts page {flat[idx + 1][0]} — "
                    f"trim earlier content or merge bullets"
                )
    return out


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


def main():
    argv = [a for a in sys.argv[1:]]
    protect = []
    kept = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--protect":
            protect.append(argv[i + 1])
            i += 2
        else:
            kept.append(a)
            i += 1
    if len(kept) < 1:
        print("usage: measure_resume.py <resume.docx> [TARGET_PAGES] "
              "[--protect \"<JD-critical phrase>\"]",
              file=sys.stderr)
        print("  Renders the docx, reports per-role rendered line costs and "
              "the reclaim gap to TARGET_PAGES (default 2, or env).",
              file=sys.stderr)
        print("  --protect: pass repeatedly; bullets containing the phrase "
              "are never suggested for cutting (JD-critical content the "
              "weakness scorer cannot know about).",
              file=sys.stderr)
        sys.exit(2)
    docx = kept[0]
    target = int(kept[1]) if len(kept) > 1 else int(
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

    # Visible timeline span — the number behind Step 3's seniority-alignment
    # decision (compare against the JD's "N+ years" ask, NOT the candidate's
    # total career).
    first, last = _visible_span([r["raw"] for r in roles])
    if first is not None:
        print(f"TIMELINE: roles span {first:.0f} – {last:.0f} "
              f"(~{last - first:.1f} years shown)")

    print()
    print(f"Fixed top block (Summary+Proficiencies+Certifications+chrome): "
          f"{fixed_top} rendered lines (not where compression cuts happen)")
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

    # Reclaim suggestion: size cuts to the overflow gap, from oldest roles.
    if over > 0:
        print()
        print(f"RECLAIM PLAN: drop ~{overflow_lines} rendered line(s) to reach "
              f"{target} page(s).")

        # Measured math + concrete batch (replaces an earlier hardcoded
        # "~2 lines per bullet" estimate that undercounted dense bullets).
        per = _measured_lines_per_bullet(matched)
        plan, remaining = _reclaim_batch(matched, per, overflow_lines + per)
        print()
        print(f"MEASURED: ~{per:.1f} rendered lines per bullet (this render)")
        print("BATCH RECLAIM PLAN (oldest roles first; +1-bullet buffer):")
        for key, action, saved in plan:
            print(f"  - {key}: {action}")
        if remaining > 0:
            print(f"  (still ~{remaining:.0f} line(s) over plan — cut past the "
                  f"listed bullet(s) or trim Tools lines)")
        print("  Generic savings: trim any 2-line Tools list to one line "
              "(~1 line each); drop blank inter-role spacers via remove_empty "
              "(~1 line each)")

        # The DROP PLAN: name the exact bullets each "drop N bullet(s)"
        # entry refers to, weakest-first, as copy-pasteable find_p lines
        # (uniqueness checked against the full document). No more deciding
        # WHICH of a role's bullets to cut.
        all_texts = [de.text_of(p) for p in de.paras(body)]
        sections = _drop_sections(plan, roles, all_texts=all_texts,
                                  protect=protect)
        if sections:
            print()
            for section in sections:
                print(section)
                print()

    print()
    print("Page fill (capacity = fullest page from this render):")
    for line in _layout_hints(matched, pages_text, capacity):
        print(line)


if __name__ == "__main__":
    main()
