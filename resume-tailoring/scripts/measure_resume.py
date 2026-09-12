"""Measure a resume's rendered length and plan compression to a page budget.

The subtractive tailoring flow (copy master, cut down) iterates well when you
know the budget up front. This tool closes that gap: it renders the .docx to
PDF once, attributes rendered lines to each role, and reports how many lines
must be reclaimed to hit a target page count — so cuts can be planned as a
batch instead of discovered through a cut-render-cut-render loop.

Two modes, split by input:

**Master input** (`X Master Resume.docx`) runs PRUNE-PLAN mode — the ONLY
sanctioned measure run on the master::

    python3 scripts/measure_resume.py "X Master Resume.docx" \
        --jd <raw-JD.txt> [--protect "<phrase>"] [--linkedin <dump>]

It prints ONLY the JD assessment — requirement coverage, the per-role
JD-FIT AUDIT (with copy-pasteable ``find_p`` anchors), WORD-LEVEL TRIM
CANDIDATES, and TOP-BLOCK PRUNE CANDIDATES — and suppresses every
page/word/role-drop metric. Relevance assessment and page math are
different decisions: all the irrelevant content is cut FIRST (SKILL
Step 3), before pages, seniority, or word counts are decided, and a
master's page math describes content that is about to be deleted. The
master without ``--jd`` (or with ``--simulate``) is refused with exit 2.

A tailored copy (non-master input) measures the full page math::

    python3 scripts/measure_resume.py <resume.docx> [TARGET_PAGES]
    python3 scripts/measure_resume.py <resume.docx> [TARGET_PAGES] \
        --jd <raw-JD.txt> [--protect "<phrase>"]
    TARGET_PAGES=2 python3 scripts/measure_resume.py <resume.docx>

``--jd`` makes the DROP PLAN JD-aware (see JD_CONCEPTS / JD_STOP below):
candidate-tech terms that the raw JD also asks for — and JD practice
phrases like mentorship — are excluded from the cut suggestions and listed
as "JD-matched (kept)", so the plan never fights the JD. It also compares
the JD's title against the resume headline and flags a headline that is
MORE SENIOR (SKILL Step 5 title alignment) — advisory only. And it prints
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

This is a MEASUREMENT tool: it does not edit the .docx. On a tailored copy,
run it after the prune pass (SKILL Step 3) and the content edits (title,
Summary, re-anchoring) and BEFORE the residual compression cuts, to plan
them. Re-run render_pdf.sh after cutting to verify.
"""

# flat-namespace sibling imports require the sys.path bootstrap; the
# sibling import must precede use, which pylint flags as wrong position.
# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.


# pylint: disable=unused-import
# measure_resume/validate_resume is the legacy RE-EXPORT shim: it preserves
# the full mr.*/vr.* surface (imports that appear unused are the re-export
# contract). Keep this header ONLY while the flat-namespace consumers
# resolve these names through the shim.



import contextlib
import io
import math
from typing import NamedTuple
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
from script_args import (MAX_WORDS, extract_common, extract_flag,  # noqa: E402
                         extract_flag_all, maybe_help, read_jd_text)


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

from measure_resume_jd_terms import (
    CORE_TECH_NOUNS,
    GENERIC_PHRASES,
    JD_CONCEPTS,
    JD_STOP,
    VOCAB_STYLE,
    _NUMBER,
    _all_bullet_texts,
    _bullet_terms,
    _concept_hits,
    _is_protected,
    _jd_capitalized,
    _jd_hits,
    _jd_hits_classified,
    _jd_kept,
    _jd_terms,
    _line_terms,
    _vocab_terms,
    _weak_jd_terms,
    _weakness_key)

from measure_resume_jd import (
    HEADLINE_STYLE,
    INFERENCE_FAMILIES,
    JD_COMPANY_VOICE_RE,
    JD_QUAL_HEADING_RE,
    JD_SELF_ASSESSMENT,
    JD_SEQ_TERM_RE,
    JD_SHORT_WORDS,
    JD_SOFT_SKILL_RE,
    JD_WORD_TERM_RE,
    SECTION_STYLE,
    TITLE_LABEL_RE,
    TITLE_MAX_WORDS,
    TITLE_RANK_PATTERNS,
    _INFERENCE_MATCH_CAP,
    _boundaries_without_spacer,
    _family_roots,
    _headline_text,
    _inference_map,
    _inference_variants,
    _jd_line_terms,
    _jd_line_terms_map,
    _jd_missing_terms,
    _jd_report,
    _jd_requirement_coverage,
    _jd_requirement_lines,
    _jd_title,
    _title_rank,
    _top_block_candidates,
    title_alignment_notes)

from measure_resume_drops import (
    Budget,
    _DROP_ACTION,
    _apply_simulate,
    _batch_section,
    _dead_end_roles,
    _drop_plan_lines,
    _drop_sections,
    _drop_suggestions,
    _iter_plan_roles,
    _jd_fit_audit,
    _jd_listing_lines,
    _keep_trim_section,
    _layout_hints,
    _measured_lines_per_bullet,
    _protected_count,
    _protected_top_role_section,
    _reclaim_batch,
    _role_jd_evidence_lines,
    _sparse_last_page_note,
    _suggest_drops,
    _top_role_batch)

def _is_master_input(docx):
    """True when <docx> is the master resume — the same convention
    validate_resume.py auto-detects ("X Master Resume.docx"). The master
    is only ever prune-planned: page/word math over content that is about
    to be pruned measures nothing real (the Gravie session planned its
    cuts from master page math, and the user then hand-cut four more
    non-JD sentences the delivered copy kept)."""
    return os.path.basename(docx).endswith(" Master Resume.docx")


def _target_from_args(kept):
    """(target, is_default) from the positional args or TARGET_PAGES env."""
    if len(kept) > 1:
        return int(kept[1]), False
    if "TARGET_PAGES" in os.environ:
        return int(os.environ["TARGET_PAGES"]), False
    return 2, True


def _default_target_note(total_pages, target, is_default):
    """Reminder when the reclaim gap is measured against the default target.

    The failure mode (a real session): the agreed Step-4 target was 3 for a
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
            "the 2-page default. Pass the agreed Step-4 target (senior/Staff "
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


def _print_usage():
    """Print the measure_resume CLI usage message to stderr."""
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
          "dropping whole. Refused on the master: seniority what-ifs run "
          "on the PRUNED copy (SKILL Step 4), never on the master.",
          file=sys.stderr)
    print("  Master input (X Master Resume.docx) runs in PRUNE-PLAN mode: "
          "--jd required, page/word math suppressed — the JD assessment "
          "(audit + trim + top-block candidates) is the only output.",
          file=sys.stderr)


class _ReportCtx(NamedTuple):
    """Shared state for measure_resume's report section printers."""
    target: int
    default_target: bool
    jd_text: str | None
    jd_terms: set
    protect: list
    body: object
    roles: list
    matched: list
    pages_text: list
    total_pages: int
    over: int
    overflow_lines: int
    capacity: int
    fixed_top: int
    role_lines: int
    edu: int
    wrapped: list


def _print_simulate(docx, simulate, jd_file, jd_text, td):
    """Run the --simulate what-if: drop named whole roles in a temp copy
    and print the seniority-alignment preview. Returns (docx, sim_jd_terms)
    — docx is the (possibly simulated) path to measure."""
    sim_jd_terms = None
    if not simulate:
        return docx, sim_jd_terms
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
          "tailor script (SKILL Step 4).")
    print()
    return docx, sim_jd_terms


def _print_jd_report(jd_file, jd_text, jd_terms, body, evidence_text):
    """Print the JD report + title-alignment check."""
    for line in _jd_report(jd_file, jd_text, jd_terms, body, evidence_text):
        print(line)
    print("JD TITLE vs HEADLINE:")
    lvl, msg = title_alignment_notes(body, jd_text)
    tag = {"warn": "WARNING", "ok": "ok", "note": "note"}[lvl]
    print(f"  {tag}: {msg}")


def _print_page_summary(ctx):
    """PAGES / OVER / UNDER / TIMELINE / fixed-top block header."""
    print(f"PAGES: {ctx.total_pages}  (target: {ctx.target})")
    if ctx.over > 0:
        print(f"OVER by {ctx.over} page(s) — ~{ctx.overflow_lines} rendered "
              f"line(s) spilled past page {ctx.target}.")
    elif ctx.over < 0:
        print(f"UNDER target by {-ctx.over} page(s) — room to expand.")
    else:
        print("ON target.")
    note = _default_target_note(ctx.total_pages, ctx.target,
                                ctx.default_target)
    if note:
        print(note)
    first, last = _visible_span([r["raw"] for r in ctx.roles])
    if first is not None:
        print(f"TIMELINE: roles span {first:.0f} – {last:.0f} "
              f"(~{last - first:.1f} years shown)")
    print()
    print(f"Fixed top block (Summary+Proficiencies+Certifications+chrome): "
          f"{ctx.fixed_top} rendered lines")
    print("  (the WHOLE resume tailors to the JD — cuts can come from ANY")
    print("   section; see TOP-BLOCK RECLAIM CANDIDATES below when over "
          "target)")
    print()


def _print_cost_table(ctx):
    """Per-role rendered cost table (oldest roles LAST)."""
    print("Per-role rendered cost (oldest roles LAST — cut from the bottom):")
    print(f"  {'Role':<34} {'pg':>4} {'lines':>5} {'b/cap':>7} {'tools':>5}")
    for r, sp, ep, lines in ctx.matched:
        name = r["key"]
        if len(name) > 33:
            name = name[:30] + "..."
        pg_s = f"{sp}-{ep}" if (sp and ep and ep != sp) else (str(sp) if sp is not None else "?")
        b_s = f"{r['bullets']}/{MAX_BULLETS_PER_ROLE}"
        print(f"  {name:<34} {pg_s:>4} {lines:>5} {b_s:>7} "
              f"{'Y' if r['has_tools'] else '-':>5}")
    print(f"  {'Education (tail)':<34} {'':>4} {ctx.edu:>5}")
    print(f"  {'TOTAL':<34} {'':>4} {ctx.fixed_top + ctx.role_lines + ctx.edu:>5}")
    print("  b/cap = NUMBERED bullets vs the Step-8 cap. Intros are not "
          "bullets and not cap fillers: intended keep + drops must equal")
    print("  the master's count per role (23 bullets, keep 8, drop 16 = "
          "7 kept — one bullet more cut than intended).")


def _print_tools_wrap(ctx):
    """Tools lines that wrap — each costs ~1 extra rendered line."""
    if not ctx.wrapped:
        return
    print()
    print("TOOLS LINES THAT WRAP (each costs ~1 rendered line; trim to "
          "the measured budget):")
    for key, value_chars, fit_chars, preview in ctx.wrapped:
        over = value_chars - fit_chars
        print(f"  {key} — value is {value_chars} chars, wraps after "
              f"~{fit_chars} — cut ~{over} chars (≈2-4 tools)")
        print(f"    \"{preview}\"")


class _ReclaimState(NamedTuple):
    """Computed reclaim-plan state shared between the batch-listing and
    the drop-sections printers."""
    per: float
    required: int
    plan: list
    remaining: int
    top: list
    batch: tuple | None
    feasible: float
    matched_roles: list
    residual: float
    closes: bool


def _print_reclaim_plan(ctx):
    """Reclaim suggestion: size cuts to the overflow gap, from oldest roles."""
    if ctx.over <= 0:
        return
    state = _print_reclaim_batch(ctx)
    _print_reclaim_sections(ctx, state)


def _print_reclaim_batch(ctx):
    """Print the RECLAIM header + measured math + batch listing + residual.
    Returns the computed _ReclaimState for the drop-sections printer."""
    print()
    print(f"RECLAIM PLAN: drop ~{ctx.overflow_lines} rendered line(s) to "
          f"reach {ctx.target} page(s).")
    per = _measured_lines_per_bullet(ctx.matched)
    required = ctx.overflow_lines + per
    plan, remaining = _reclaim_batch(ctx.matched, per, required)
    top = _top_block_candidates(ctx.body, ctx.jd_terms)
    batch, plan, feasible = _top_role_batch(
        ctx.matched, plan,
        Budget(per=per, required=required, tools_savings=len(ctx.wrapped),
               top_block_count=len(top)),
        protect=ctx.protect, jd_terms=ctx.jd_terms)
    matched_roles = [m[0] for m in ctx.matched]
    print()
    print(f"MEASURED: ~{per:.1f} rendered lines per bullet (this render)")
    print("BATCH RECLAIM PLAN (oldest roles first; +1-bullet buffer):")
    for key, action, _ in plan:
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
            protected = _protected_top_role_section(ctx.matched, ctx.jd_terms)
            if protected:
                print()
                print(protected)
    print("  Generic savings: drop blank inter-role spacers via "
          "remove_empty (~1 line each)")
    return _ReclaimState(per=per, required=required, plan=plan,
                         remaining=remaining, top=top, batch=batch,
                         feasible=feasible, matched_roles=matched_roles,
                         residual=residual, closes=closes)


def _print_reclaim_sections(ctx, state):
    """Print dead-end plans, top-block candidates, and the DROP PLAN
    sections (including the top-role trim batch if sized)."""
    dead = _dead_end_roles(state.plan, ctx.roles, protect=ctx.protect,
                           jd_terms=ctx.jd_terms)
    if dead:
        print()
        print("DEAD-END PLANS: " + ", ".join(dead) + " cannot meet "
              "their cut budget from unprotected bullets — prefer the "
              "TOP-BLOCK RECLAIM CANDIDATES, a Tools-line trim, or a "
              "whole-role drop (seniority decision) over cutting "
              "JD-matched bullets.")
    if state.top:
        print()
        print("TOP-BLOCK RECLAIM CANDIDATES (Technical Proficiencies / "
              "Certifications lines with no JD evidence; ~1 line each):")
        if not ctx.jd_terms:
            print("  (no --jd given — review each against the JD before "
                  "cutting)")
        _print_top_block_lines(state.top)
    all_texts = [de.text_of(p) for p in de.paras(ctx.body)]
    sections = _drop_sections(state.plan, ctx.roles, all_texts=all_texts,
                              protect=ctx.protect, jd_terms=ctx.jd_terms)
    if state.batch is not None:
        top_role = next((r for r in ctx.roles
                         if r["key"] == state.batch[0]), None)
        batch_hdr = ("closes the residual gap after the cuts above"
                     if state.closes else "the largest remaining safe source")
        header = f"TOP-ROLE TRIM BATCH ({state.batch[0]}; {batch_hdr}): "
        batch_bullets = top_role.get("bullet_texts") or []
        batch_n = int(_DROP_ACTION.match(state.batch[1]).group(1))
        batch_lines = _drop_plan_lines(
            batch_bullets, batch_n, all_texts=all_texts,
            protect=ctx.protect, jd_terms=ctx.jd_terms)
        batch_jd = _jd_listing_lines(batch_bullets, ctx.jd_terms)
        section = _batch_section(state.batch, top_role, header,
                                 batch_lines, batch_jd)
        if section is not None:
            sections.append(section)
        if not state.closes:
            sections.append(
                f"NOTE: even with the top-role batch, "
                f"~{state.residual - state.batch[2]:.0f} "
                "line(s) remain — the gap cannot close without cutting "
                "JD-matched content or revisiting the approved "
                "whole-role drops with the user.")
    if state.batch is None and state.residual > 0:
        sections.append(
            f"NO SAFE PLAN: feasible removals cover ~{state.feasible:.0f} of "
            f"~{state.required:.0f} line(s) and the most-recent role has no "
            "unprotected bullet to give — the gap cannot close without "
            "cutting JD-matched content or revisiting the approved "
            "whole-role drops with the user.")
    if sections:
        print()
        for section in sections:
            print(section)
            print()


def _word_tokens(text):
    """Whitespace tokens containing at least one alphanumeric character —
    the validator's word-count semantics (a dingbat is not a word)."""
    return [t for t in text.split() if re.search(r"[A-Za-z0-9]", t)]


def _print_word_budget(body):
    """WORD BUDGET — validator-equivalent whole-resume word count with a
    per-role breakdown and the wordiest bullets. The deliverable gate
    blocks over MAX_WORDS (SKILL Step 8); this section surfaces the
    arithmetic BEFORE the gate does, so cuts are planned in one pass
    instead of hand-estimated across blocked re-run cycles. Prints only
    near the cap (85%+) — under it the section is noise."""
    ps = de.paras(body)
    total = sum(len(_word_tokens(de.text_of(p))) for p in ps)
    if total <= MAX_WORDS * 0.85:
        return
    delta = total - MAX_WORDS
    if delta > 0:
        print(f"WORD BUDGET (cap {MAX_WORDS}): {total} words — "
              f"{delta} over")
    else:
        print(f"WORD BUDGET (cap {MAX_WORDS}): {total} words — "
              f"{-delta} of headroom left")

    # Bucket paragraphs: fixed top block (before the first company
    # header), one bucket per role, Education tail last.
    buckets = []  # (label, words)
    label, words = "Fixed top block (Summary/Proficiencies/Certs)", 0
    for p in ps:
        style, _ = de.style_and_numid(p)
        text = de.text_of(p)
        if style == COMPANY_STYLE and text.strip():
            buckets.append((label, words))
            label, words = text.strip()[:40], 0
        words += len(_word_tokens(text))
    buckets.append((label, words))
    for label, words in buckets:
        if words:
            print(f"  {words:>5}  {label}")

    bullets = [(len(_word_tokens(t)), t) for t in _all_bullet_texts(body)]
    if bullets:
        print("  Wordiest bullets (shorten or cut first):")
        for n, t in sorted(bullets, reverse=True)[:5]:
            print(f"    {n:>3}w  {t[:72]}")
    print()


def _coverage_status_counts(coverage):
    """Status histogram + the hard-skill subset of the UNCOVERED lines
    (the three-state call-to-action count for REQUIREMENTS SUMMARY)."""
    counts = {s: sum(1 for _, st, _ in coverage if st == s)
              for s in ("covered", "weak", "uncovered", "by_hand")}
    hard_uncovered = sum(
        1 for label, s, _ in coverage
        if s == "uncovered" and not JD_SOFT_SKILL_RE.search(label))
    return counts, hard_uncovered


def _print_coverage_lines(coverage, term_map):
    """The per-qualification status lines (with matcher-term noise on
    weak/uncovered rows)."""
    tag = {"covered": "covered", "weak": "weak",
           "uncovered": "UNCOVERED", "by_hand": "by hand"}
    for (label, status, detail), (_, terms) in zip(coverage, term_map):
        # Show the matcher's extracted terms on weak/uncovered lines: the
        # fix for a demonstrated-but-UNCOVERED qual is hosting the JD's
        # literal phrase, and that requires seeing WHICH phrase the
        # matcher wants (an artifact like 'solid sql' mined from "Solid
        # SQL skills" is visible instead of a debugging session).
        shown = f" (extracted terms: {', '.join(sorted(terms))})" \
            if terms and status in ("uncovered", "weak") else ""
        print(f"  [{tag[status]}] {label}{shown}")
        if detail:
            print(f"      {detail}")


def _requirements_summary_line(coverage, counts, hard_uncovered):
    """The compact one-line REQUIREMENTS SUMMARY signal for the agent —
    when unconfirmed_hard > 0, the three-state checklist (SKILL Step 2)
    MUST be presented to the user before claiming done."""
    summary = (f"REQUIREMENTS SUMMARY: {counts['covered']}/{len(coverage)} "
               f"quals covered, {counts['weak']} weak, "
               f"{counts['uncovered']} uncovered, "
               f"{counts['by_hand']} by-hand")
    if hard_uncovered:
        summary += (f" ({hard_uncovered} unconfirmed hard skill(s) — "
                    "present three-state checklist to user, SKILL Step 2)")
    if counts["by_hand"]:
        # Soft-skill asks extract no terms ([by hand]) — without a
        # directive they sat unhosted until the Step-11 scan flagged the
        # absence and the score paid for it. Host them in the authoring
        # pass, where the action-verb evidence and the literal-phrase
        # bullet are both in hand (SKILL Step 2's default-inference rule).
        summary += (f" ({counts['by_hand']} soft-skill line(s) [by hand] — "
                    "host the literal phrases in THIS pass; soft skills are "
                    "safe to infer from action-verb evidence, SKILL Step 2)")
    return summary


def _print_jd_coverage(roles, body, jd_text, jd_terms):
    """JD REQUIREMENT COVERAGE — per qualification line, its kept hosts."""
    if not jd_terms:
        return
    coverage = _jd_requirement_coverage(roles, body, jd_text)
    if not coverage:
        return
    counts, hard_uncovered = _coverage_status_counts(coverage)
    print()
    print("JD REQUIREMENT COVERAGE (each qualification line → "
          f"status; {len(coverage)} line(s)):")
    _print_coverage_lines(coverage, _jd_line_terms_map(jd_text))
    if counts["uncovered"]:
        print(f"  {counts['uncovered']} requirement(s) UNCOVERED — a resume "
              "that does not demonstrate a required qual reads as "
              "unqualified for it.")
    if counts["weak"]:
        print(f"  {counts['weak']} requirement(s) [weak] — hosted only on "
              "proficiencies/Tools lines; weave into a bullet "
              "where used (SKILL Step 6).")
    print(_requirements_summary_line(coverage, counts, hard_uncovered))
    print()


def _print_jd_audit(roles, body, jd_terms, protect):
    """JD-FIT AUDIT — every role, independent of the page math."""
    if not jd_terms:
        return
    all_texts = [de.text_of(p) for p in de.paras(body)]
    audit = _jd_fit_audit(roles, jd_terms, protect=protect,
                          all_texts=all_texts)
    if audit:
        print("JD-FIT AUDIT (every role — cut every OFF-JD/weak bullet "
              "listed here in the FIRST pass, no page-math condition; "
              "on the master this IS the whole plan):")
        for section in audit:
            print(section)
            print()
    trim = _keep_trim_section(roles, jd_terms, body, protect=protect)
    if trim:
        print(trim)
        print()


def _print_top_block_lines(top):
    """The copy-pasteable cut lines for TOP-BLOCK candidates (shared by
    the prune-plan and reclaim-plan printers)."""
    for prefix, text in top:
        print(f'    find_p(ps, "{prefix}")  # {text[:70]}')


def _print_top_block_prune(body, jd_terms):
    """TOP-BLOCK PRUNE CANDIDATES — off-JD proficiencies/cert lines.

    The prune-plan (master) form of the reclaim-plan's TOP-BLOCK section:
    here it is unconditional — an off-JD top-block line is irrelevant
    content regardless of any page math."""
    top = _top_block_candidates(body, jd_terms)
    if not top:
        return
    print()
    print("TOP-BLOCK PRUNE CANDIDATES (Technical Proficiencies / "
          "Certifications lines with no JD evidence; cut whole):")
    _print_top_block_lines(top)
    print()


def _main_prune_plan(args):
    """PRUNE-PLAN mode — the only sanctioned measure run on the master.

    Assess every paragraph of the master against the JD and cut everything
    irrelevant FIRST (SKILL Step 3); no page, word, or role-drop math is
    printed, because it would describe content that is about to be pruned
    (and measuring the full master invites keeping it). The PDF is not
    even rendered — relevance needs no layout. After the prune pass,
    measure the tailored copy for the length/seniority decision
    (SKILL Step 4)."""
    if args.simulate:
        print("error: --simulate answers a seniority question (which whole "
              "roles to drop) — decided on the PRUNED copy in SKILL Step 4, "
              "after the prune pass. The master only answers 'what is "
              "irrelevant'.", file=sys.stderr)
        sys.exit(2)
    if not args.jd_text:
        print("error: the master is measured ONLY with --jd (prune-plan "
              "mode). Without a JD there is no relevance signal — and "
              "page/word math on the unpruned master is never measured "
              "(SKILL Step 3). Pass --jd <JD.txt>.", file=sys.stderr)
        sys.exit(2)
    if not args.default_target:
        print(f"(page target {args.target} ignored — the master is only "
              "prune-planned; measure the tailored copy for page math)")
        print()
    _, body, _, _, _ = de.load(args.docx)
    roles = _roles(body)
    jd_terms = _jd_terms(args.jd_text, body)
    print("PRUNE PLAN — master input: cut everything irrelevant FIRST "
          "(SKILL Step 3) — every OFF-JD/weak bullet, dead sentence, "
          "non-JD clause, and non-JD list chunk below goes in the first "
          "pass, before any page target, role drop, seniority, or word "
          "count is decided. Page/word math on the unpruned master is "
          "never measured; prune, then measure the tailored copy "
          "(SKILL Step 4).")
    print()
    _print_jd_report(args.jd_file, args.jd_text, jd_terms, body,
                     args.evidence_text)
    _print_jd_coverage(roles, body, args.jd_text, jd_terms)
    _print_jd_audit(roles, body, jd_terms, args.protect)
    _print_top_block_prune(body, jd_terms)


def _print_layout_summary(ctx):
    """Page fill, layout hints, sparse-last-page note, spacer opportunities."""
    print()
    print("Page fill (capacity = fullest page from this render):")
    for line in _layout_hints(ctx.matched, ctx.pages_text, ctx.capacity):
        print(line)
    fills = _page_fill(ctx.pages_text)
    sparse = _sparse_last_page_note(ctx.total_pages, ctx.target, fills,
                                    ctx.capacity, ctx.overflow_lines)
    if sparse:
        print(sparse)
    if ctx.over <= 0 and fills and fills[-1] < ctx.capacity:
        gaps = _boundaries_without_spacer(ctx.body)
        if gaps:
            names = [h[:36] for h, _ in gaps]
            print()
            print(f"SPACER OPPORTUNITIES: {len(gaps)} boundary/boundaries "
                  f"lack a pause ({', '.join(names)}); last page at "
                  f"{fills[-1] * 100 // ctx.capacity}% — add spacers via "
                  f"clone_after(body, find_p(ps, \"<Tools line>\"), \"\")")


def _load_and_render(docx, simulate, jd_file, jd_text, evidence_text):
    """Simulate (if requested), load the docx, resolve JD terms, print the
    JD report, and render the PDF. Returns (body, roles, jd_terms,
    pages_text, total_pages)."""
    with tempfile.TemporaryDirectory() as td:
        docx, sim_jd_terms = _print_simulate(docx, simulate, jd_file,
                                             jd_text, td)
        _, body, _, _, _ = de.load(docx)
        roles = _roles(body)
        jd_terms = _resolved_jd_terms(jd_text, body, simulate, sim_jd_terms)
        if jd_file:
            _print_jd_report(jd_file, jd_text, jd_terms, body, evidence_text)
        pdf = _render_pdf(docx, td)
        pages_text = _pdf_pages_text(pdf)
        total_pages = len(pages_text)
    return body, roles, jd_terms, pages_text, total_pages


class _Args(NamedTuple):
    """Parsed measure_resume CLI args."""
    docx: str
    target: int
    default_target: bool
    jd_text: str | None
    jd_file: str | None
    evidence_text: str | None
    protect: list
    simulate: list


def _parse_measure_args():
    """Parse argv and load the JD/LinkedIn text. Exits 2 on usage/error."""
    argv = list(sys.argv[1:])
    maybe_help(argv, __doc__)
    linkedin_file = extract_flag(argv, "--linkedin")
    simulate = extract_flag_all(argv, "--simulate")
    protect, jd_file, kept = extract_common(argv)
    if len(kept) < 1:
        _print_usage()
        sys.exit(2)
    docx = kept[0]
    target, default_target = _target_from_args(kept)
    jd_text = read_jd_text(jd_file) if jd_file else None
    evidence_text = None
    if linkedin_file:
        try:
            with open(linkedin_file, encoding="utf-8",
                      errors="replace") as fh:
                evidence_text = fh.read()
        except OSError as e:
            print(f"error: cannot read --linkedin file {linkedin_file}: "
                  f"{e}", file=sys.stderr)
            sys.exit(2)
    return _Args(docx, target, default_target, jd_text, jd_file,
                 evidence_text, protect, simulate)


def _build_ctx(args, body, roles, jd_terms, pages_text):
    """Compute page-math metrics and build the _ReportCtx."""
    total_pages = len(pages_text)
    matched = _match_roles_to_pages(roles, pages_text)
    fixed_top = _fixed_top_cost(pages_text, roles)
    edu = _education_cost(pages_text)
    capacity = max(_page_fill(pages_text)) if pages_text else 0
    role_lines = sum(m[3] for m in matched)
    over = total_pages - args.target
    overflow_lines = (sum(len(_page_lines(p)) for p in pages_text[args.target:])
                      if over > 0 else 0)
    wrapped = _wrapped_tools(_flat_from_pages(pages_text), matched)
    return _ReportCtx(
        target=args.target, default_target=args.default_target,
        jd_text=args.jd_text, jd_terms=jd_terms,
        protect=args.protect,
        body=body, roles=roles, matched=matched, pages_text=pages_text,
        total_pages=total_pages, over=over, overflow_lines=overflow_lines,
        capacity=capacity, fixed_top=fixed_top, role_lines=role_lines,
        edu=edu, wrapped=wrapped)


def main():  # CLI entry: prune-plan on the master, full page math otherwise

    """Measure-resume CLI entry point."""
    args = _parse_measure_args()
    if _is_master_input(args.docx):
        _main_prune_plan(args)
        return
    body, roles, jd_terms, pages_text, _ = _load_and_render(
        args.docx, args.simulate, args.jd_file, args.jd_text,
        args.evidence_text)
    ctx = _build_ctx(args, body, roles, jd_terms, pages_text)
    _print_page_summary(ctx)
    _print_cost_table(ctx)
    _print_tools_wrap(ctx)
    _print_reclaim_plan(ctx)
    _print_word_budget(body)
    _print_jd_coverage(ctx.roles, ctx.body, ctx.jd_text, ctx.jd_terms)
    _print_jd_audit(ctx.roles, ctx.body, ctx.jd_terms, ctx.protect)
    _print_layout_summary(ctx)


if __name__ == "__main__":
    main()
