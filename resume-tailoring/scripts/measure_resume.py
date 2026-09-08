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
as "JD-matched (kept)", so the plan never fights the JD. It also compares
the JD's title against the resume headline and flags a headline that is
MORE SENIOR (SKILL Step 4 title alignment) — advisory only. And it prints
a per-role JD-FIT AUDIT for EVERY role — OFF-JD and weak-match bullets —
because the DROP PLAN only fires under page pressure and JD alignment is
the first priority: weak bullets get cut even when the resume is already
on target.

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
# pylint: disable=unused-import
# measure_resume/validate_resume is the legacy RE-EXPORT shim: it preserves
# the full mr.*/vr.* surface (imports that appear unused are the re-export
# contract). Keep this header ONLY while the flat-namespace consumers
# resolve these names through the shim.



import contextlib
import io
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
import script_args  # noqa: E402
from script_args import extract_common, extract_flag, extract_flag_all, read_jd_text  # noqa: E402


W = de.W

MAX_BULLETS_PER_ROLE = 8


from measure_resume_format import (
    BULLET_STYLES,
    COMPANY_STYLE,
    DATE_RE,
    SECTION_CAREER,
    SECTION_EDUCATION,
    SECTION_PROFICIENCIES,
    _company_key,
    _education_cost,
    _fixed_top_cost,
    _flat_from_pages,
    _gap_if_dropped,
    _is_footer,
    _match_roles_to_pages,
    _norm,
    _page_fill,
    _page_lines,
    _pdf_pages_text,
    _preceding_role_key,
    _proficiency_block,
    _render_pdf,
    _role_header_flat,
    _role_span_months,
    _roles,
    _visible_span,
    _wrapped_tools)

from measure_resume_jd import (
    CORE_TECH_NOUNS,
    GENERIC_PHRASES,
    HEADLINE_STYLE,
    INFERENCE_FAMILIES,
    JD_COMPANY_VOICE_RE,
    JD_CONCEPTS,
    JD_QUAL_HEADING_RE,
    JD_SELF_ASSESSMENT,
    JD_SEQ_TERM_RE,
    JD_SHORT_WORDS,
    JD_SOFT_SKILL_RE,
    JD_STOP,
    JD_WORD_TERM_RE,
    SECTION_STYLE,
    TITLE_LABEL_RE,
    TITLE_MAX_WORDS,
    TITLE_RANK_PATTERNS,
    VOCAB_STYLE,
    _INFERENCE_MATCH_CAP,
    _NUMBER,
    _all_bullet_texts,
    _boundaries_without_spacer,
    _bullet_terms,
    _concept_hits,
    _family_roots,
    _headline_text,
    _inference_map,
    _inference_variants,
    _is_protected,
    _jd_capitalized,
    _jd_hits,
    _jd_hits_classified,
    _jd_kept,
    _jd_line_terms,
    _jd_missing_terms,
    _jd_report,
    _jd_requirement_coverage,
    _jd_requirement_lines,
    _jd_terms,
    _jd_title,
    _line_terms,
    _title_rank,
    _top_block_candidates,
    _vocab_terms,
    _weak_jd_terms,
    _weakness_key,
    title_alignment_notes)

from measure_resume_drops import (
    _DROP_ACTION,
    _apply_simulate,
    _batch_section,
    _dead_end_roles,
    _drop_plan_lines,
    _drop_sections,
    _drop_suggestions,
    _jd_fit_audit,
    _jd_listing_lines,
    _layout_hints,
    _measured_lines_per_bullet,
    _protected_count,
    _protected_top_role_section,
    _reclaim_batch,
    _role_jd_evidence_lines,
    _sparse_last_page_note,
    _suggest_drops,
    _top_role_batch)

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


def _resolved_jd_terms(jd_text, body, simulate, sim_jd_terms):
    """JD terms the --jd report and DROP PLAN rank with.

    With ``--simulate`` the terms come from the PRE-DROP body (computed
    in main's simulate block). Without ``--simulate`` they are derived
    from the real body here — computing them only in the simulate block
    made ``--jd`` silently JD-blind when ``--simulate`` was absent."""
    if simulate:
        return set(sim_jd_terms) if sim_jd_terms is not None else set()
    return _jd_terms(jd_text, body) if jd_text else set()


def main():
    argv = list(sys.argv[1:])
    linkedin_file = extract_flag(argv, "--linkedin")
    simulate = extract_flag_all(argv, "--simulate")
    protect, jd_file, kept = extract_common(argv)
    if len(kept) < 1:
        print("usage: measure_resume.py <resume.docx> [TARGET_PAGES] "
              "[--jd <raw-JD.txt>] [--linkedin <profile-dump.txt>] "
              "[--protect \"<JD-critical phrase>\"] "
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
        print("  --linkedin <file>: a read_profile.sh dump of the LinkedIn "
              "export. Searched by the INFERENCE MAP (a no-host JD term's "
              "variants and skill-family roots) for candidate evidence the "
              "resume compressed away.",
              file=sys.stderr)
        print("  --protect: pass repeatedly; bullets containing the phrase "
              "are never suggested for cutting (candidate-specific facts "
              "the JD text cannot name, e.g. a confirmed Snyk duty).",
              file=sys.stderr)
        print("  --simulate: pass repeatedly; drops each named WHOLE role "
              "(company-header prefix) in a temp copy and measures THAT — "
              "the seniority-alignment what-if. The file on disk is never "
              "modified; compare the printed TIMELINE against the JD's ask. "
              "With --jd it also reports JD-matched bullets each drop would "
              "lose — trim those roles to their JD bullets instead of "
              "dropping whole.",
              file=sys.stderr)
        sys.exit(2)
    docx = kept[0]
    target, default_target = _target_from_args(kept)

    jd_text = read_jd_text(jd_file) if jd_file else None

    evidence_text = None
    if linkedin_file:
        try:
            with open(linkedin_file, encoding="utf-8",
                      errors="replace") as f:
                evidence_text = f.read()
        except OSError as e:
            print(f"error: cannot read --linkedin file {linkedin_file}: "
                  f"{e}", file=sys.stderr)
            sys.exit(2)

    with tempfile.TemporaryDirectory() as td:
        sim_jd_terms = None  # sentinel: no --jd passed
        if simulate:
            _, pre_body, _, _, _ = de.load(docx)
            pre_roles = _roles(pre_body)
            if jd_file:
                sim_jd_terms = _jd_terms(jd_text, pre_body)
            sim_path = os.path.join(td, "simulated.docx")
            docx, dropped = _apply_simulate(docx, simulate, sim_path)
            print("SIMULATED seniority alignment — the file on disk was "
                  "NOT modified:")
            for header in dropped:
                print(f"  dropped whole role: {header}")
                for line in _role_jd_evidence_lines(
                        pre_roles, header, sim_jd_terms or set()):
                    print(f"    {line}")
            missing = len(simulate) - len(dropped)
            if missing:
                print(f"  ({missing} prefix(es) matched nothing — see "
                      f"warnings above)")
            if not jd_file:
                print("  (no --jd passed — JD evidence in the dropped roles "
                      "cannot be assessed; pass --jd <JD.txt> to see it)")
            print("  Compare the TIMELINE below against the JD's ask; apply "
                  "the drops for real via drop_role() in the per-target "
                  "tailor script (SKILL Step 3).")
            print()

        _, body, _, _, _ = de.load(docx)
        roles = _roles(body)

        jd_terms = _resolved_jd_terms(jd_text, body, simulate, sim_jd_terms)
        if jd_file:
            for line in _jd_report(jd_file, jd_text, jd_terms, body,
                                   evidence_text):
                print(line)
            print("JD TITLE vs HEADLINE:")
            lvl, msg = title_alignment_notes(body, jd_text)
            tag = {"warn": "WARNING", "ok": "ok", "note": "note"}[lvl]
            print(f"  {tag}: {msg}")

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
    print(f"  {'Role':<34} {'pg':>4} {'lines':>5} {'b/cap':>7} {'tools':>5}")
    for r, sp, ep, lines in matched:
        name = r["key"]
        if len(name) > 33:
            name = name[:30] + "..."
        pg_s = f"{sp}-{ep}" if (sp and ep and ep != sp) else (str(sp) if sp is not None else "?")
        b_s = f"{r['bullets']}/{MAX_BULLETS_PER_ROLE}"
        print(f"  {name:<34} {pg_s:>4} {lines:>5} {b_s:>7} "
              f"{'Y' if r['has_tools'] else '-':>5}")
    print(f"  {'Education (tail)':<34} {'':>4} {edu:>5}")
    print(f"  {'TOTAL':<34} {'':>4} {fixed_top + role_lines + edu:>5}")
    print("  b/cap = NUMBERED bullets vs the Step-8 cap. Intros are not "
          "bullets and not cap fillers: intended keep + drops must equal")
    print("  the master's count per role (23 bullets, keep 8, drop 16 = "
          "7 kept — one bullet more cut than intended).")

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
        for key, action, _saved in plan:
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
            if residual > 0:
                protected = _protected_top_role_section(matched, jd_terms)
                if protected:
                    print()
                    print(protected)
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

    # JD REQUIREMENT COVERAGE — per qualification line, its kept hosts.
    # Cutting off-JD content keeps the resume honest; this keeps it
    # QUALIFIED: the resume must demonstrate each JD ask. [UNCOVERED]
    # lines are the never-fabricate flags' positive counterpart.
    if jd_terms:
        coverage = _jd_requirement_coverage(roles, body, jd_text)
        if coverage:
            uncov = sum(1 for _, s, _ in coverage if s == "uncovered")
            weak = sum(1 for _, s, _ in coverage if s == "weak")
            print()
            tag = {"covered": "covered", "weak": "weak",
                   "uncovered": "UNCOVERED", "by_hand": "by hand"}
            print("JD REQUIREMENT COVERAGE (each qualification line → "
                  f"status; {len(coverage)} line(s)):")
            for label, status, detail in coverage:
                print(f"  [{tag[status]}] {label}")
                if detail:
                    print(f"      {detail}")
            if uncov:
                print(f"  {uncov} requirement(s) UNCOVERED — a resume that "
                      "does not demonstrate a required qual reads as "
                      "unqualified for it.")
            if weak:
                print(f"  {weak} requirement(s) [weak] — hosted only on "
                      "proficiencies/Tools lines; weave into a bullet "
                      "where used (SKILL Step 5).")
            print()

    # JD-FIT AUDIT — every role, independent of the page math. These are
    # FIRST-PASS cuts (SKILL Step 8): every OFF-JD/weak bullet listed here
    # goes in the first authoring pass — no page-math condition. The DROP
    # PLAN above is only the page-budget question after these land. Read
    # it AFTER the build as well — a clean render is not a JD-tight resume.
    if jd_terms:
        audit = _jd_fit_audit(roles, jd_terms, protect=protect)
        if audit:
            print("JD-FIT AUDIT (every role — cut every OFF-JD/weak bullet "
                  "listed here in the FIRST pass, no page-math condition; "
                  "the DROP PLAN above is only the page-budget subset):")
            for section in audit:
                print(section)
                print()

    print()
    print("Page fill (capacity = fullest page from this render):")
    for line in _layout_hints(matched, pages_text, capacity):
        print(line)
    fills = _page_fill(pages_text)
    sparse = _sparse_last_page_note(total_pages, target, fills, capacity,
                                    overflow_lines)
    if sparse:
        print(sparse)

    # SPACER OPPORTUNITIES — Step 8's readability pause, reported instead
    # of remembered: which role boundaries lack a blank spacer while the
    # render has slack for one. Lowest priority — when content or pages
    # need room, spacers go first.
    if over <= 0 and fills and fills[-1] < capacity:
        gaps = _boundaries_without_spacer(body)
        if gaps:
            names = [h[:36] for h, _ in gaps]
            print()
            print(f"SPACER OPPORTUNITIES: {len(gaps)} boundary/boundaries "
                  f"lack a pause ({', '.join(names)}); last page at "
                  f"{fills[-1] * 100 // capacity}% — add spacers via "
                  f"clone_after(body, find_p(ps, \"<Tools line>\"), \"\")")


if __name__ == "__main__":
    main()

