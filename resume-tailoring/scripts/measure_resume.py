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
        [--ats-report <scan.json>]

It prints ONLY the JD assessment — requirement coverage, the per-role
JD-FIT AUDIT (with copy-pasteable ``find_p`` anchors), WORD-LEVEL TRIM
CANDIDATES, and TOP-BLOCK PRUNE CANDIDATES — and writes the
machine-readable twin to the ``<master>.prune.json`` sidecar (enforced by
``docx_edit.py --lint-prune`` at tailor-run time). It suppresses every
page/word/role-drop metric. The agent does not run this mode;
``auto_prune.py`` owns the machine disposition. Phase 1 cuts irrelevant
content first; Phase 2 owns page, seniority, and word-budget decisions. The
master without ``--jd`` (or with ``--simulate``) is refused with exit 2.

A tailored copy (non-master input) measures the full page math::

    python3 scripts/measure_resume.py <resume.docx> [TARGET_PAGES]
    python3 scripts/measure_resume.py <resume.docx> [TARGET_PAGES] \
        --jd <raw-JD.txt> [--protect "<phrase>"]
    TARGET_PAGES=2 python3 scripts/measure_resume.py <resume.docx>

``--jd`` makes the DROP PLAN use the unified ask engine: evidenced bullets
are excluded from cut suggestions and listed as "JD-evidenced (kept)",
so the plan never fights an explicit JD ask. It also compares
the JD's title against the resume headline and flags a headline that is
MORE SENIOR (SKILL Step 6 title alignment) — advisory only. And it prints
a per-role JD-FIT AUDIT for EVERY role — unevidenced bullets —
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

# Lazy imports here are deliberate (cycle avoidance / heavy deps) — see
# the specific rationale at each site where one is retained.


# pylint: disable=unused-import
# measure_resume/validate_resume is the legacy RE-EXPORT shim: it preserves
# the full mr.*/vr.* surface (imports that appear unused are the re-export
# contract). Keep this header ONLY while the flat-namespace consumers
# resolve these names through the shim.



import contextlib
import io
import json
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
                         extract_flag_all, maybe_help, read_jd_text,
                         word_tokens)


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
    JD_SELF_ASSESSMENT,
    JD_STOP,
    VOCAB_STYLE,
    _NUMBER,
    _all_bullet_texts,
    _bullet_terms,
    _concept_hits,
    _is_protected,
    _jd_capitalized,
    _jd_hits,
    _adjacent_bigrams,
    _line_terms,
    _vocab_terms,
    _weakness_key)

import gap_queue  # noqa: E402
import jd_asks  # noqa: E402


def _jd_terms(jd_text, body=None):
    """The engine's ask phrases as a set (one extraction shared with
    ats_audit and auto_prune).

    ``body`` is accepted for signature compatibility and unused — asks
    are JD-side truth, never resume-intersected (the old
    vocabulary-intersection engine protected exactly the content this
    workflow exists to cut)."""  # pylint: disable=unused-argument
    return {a.phrase for a in jd_asks.parse_asks(jd_text)}

from jd_asks import (  # engine home: JD parsing names live here now
    JD_COMPANY_VOICE_RE,
    JD_SEQ_TERM_RE,
    JD_WORD_TERM_RE,
)

from measure_resume_jd import (
    HEADLINE_STYLE,
    InferenceSources,
    INFERENCE_FAMILIES,
    JD_SHORT_WORDS,
    JD_SOFT_SKILL_RE,
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
    _adjacent_master_body,
    _fail_without_master,
    _print_jd_coverage,
    _print_jd_report,
    title_alignment_notes)
from measure_resume_pruneplan import (  # noqa: E402  (facade re-exports)
    _main_prune_plan,
    _print_disposition_checklist,
    _print_jd_audit,
    _print_top_block_lines,
    _write_prune_sidecar)

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
    _page_removal_note,
    _suggest_drops,
    _top_role_batch,
    prune_candidates)

def _is_master_input(docx):
    """True when <docx> is the master resume — the same convention
    validate_resume.py auto-detects ("X Master Resume.docx"). The master
    is only ever prune-planned: page/word math over content that is about
    to be pruned measures nothing real, and master page math would drive
    cuts that miss non-JD sentences the delivered copy keeps."""
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

    The failure mode: an agreed Step-4 target of 3 for a senior/Staff
    resume is contradicted when measure runs without an explicit target
    and reports "OVER by 2 pages / drop ~117 lines" against the 2-page
    default — an irrelevant reading that invites over-cutting. The tool cannot know
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
          "[--ats-report <scan.json>] [--protect \"<JD-critical phrase>\"] "
          "[--simulate <company-prefix>]",
          file=sys.stderr)
    print("  Renders the docx, reports per-role rendered line costs and "
          "the reclaim gap to TARGET_PAGES (default 2, or env).",
          file=sys.stderr)
    print("  --jd <file>: raw job-description text. Bullets whose text "
          "matches a candidate-tech term the JD asks for, or a named JD "
          "practice (mentorship, shift-left), are excluded from the DROP "
          "PLAN and listed as 'JD-matched (kept)' — the scorer alone " "cannot know the JD.",
          file=sys.stderr)
    print("  --linkedin <file>: a read_profile.sh dump of the LinkedIn "
          "export. Searched by the INFERENCE MAP (a no-host JD term's "
          "variants and skill-family roots) for candidate evidence the " "resume compressed away.",
          file=sys.stderr)
    print("  --ats-report <file>: merge the external scan's missing hard "
          "and soft skills with the internal no-host list, run the same "
          "master/LinkedIn inference map, and write a fingerprinted "
          "<resume>.gap.json queue.", file=sys.stderr)
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
          "on the PRUNED copy (SKILL Step 5), never on the master.",
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
          "the drops for real via drop_role() in the per-target " "tailor script (SKILL Step 5).")
    print()
    return docx, sim_jd_terms


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
                 "is the largest remaining safe source (its " "JD-protected bullets stay)"))
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
              "whole-role drop (seniority decision) over cutting " "JD-matched bullets.")
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
                f"NOTE: even with the top-role batch, " f"~{state.residual - state.batch[2]:.0f} "
                "line(s) remain — the gap cannot close without cutting "
                "JD-matched content or revisiting the approved " "whole-role drops with the user.")
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
    """Word tokens using the shared external-ATS semantics."""
    return word_tokens(text)


def _print_word_budget(body):
    """WORD BUDGET — validator-equivalent whole-resume word count with a
    per-role breakdown and the wordiest bullets. The deliverable gate
    blocks over MAX_WORDS (SKILL Step 9); this section surfaces the
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


def _print_layout_summary(ctx):
    """Page fill, layout hints, page-removal note, spacer opportunities."""
    print()
    print("Page fill (capacity = fullest page from this render):")
    for line in _layout_hints(ctx.matched, ctx.pages_text, ctx.capacity):
        print(line)
    fills = _page_fill(ctx.pages_text)
    page_note = _page_removal_note(ctx.total_pages, ctx.target,
                                   ctx.overflow_lines)
    if page_note:
        print(page_note)
    if ctx.over <= 0 and fills and fills[-1] < ctx.capacity:
        gaps = _boundaries_without_spacer(ctx.body)
        if gaps:
            names = [h[:36] for h, _ in gaps]
            print()
            print(f"SPACER OPPORTUNITIES: {len(gaps)} boundary/boundaries "
                  f"lack a pause ({', '.join(names)}); last page at "
                  f"{fills[-1] * 100 // ctx.capacity}% — add spacers via "
                  f"clone_after(body, find_p(ps, \"<Tools line>\"), \"\")")


def _external_gap_terms(report_path, resume_path, internal_missing):
    """Persist the fingerprinted gap queue; return (terms, soft_terms).

    ``soft_terms`` is the external report's soft-skill subset (source
    ``external-soft``) so the inference map can verdict those SOFT-SKILL
    rather than the lexical AUTO-HOST/RAISE split."""
    if not report_path:
        return list(internal_missing), frozenset()
    artifact_path = resume_path + ".gap.json"
    try:
        artifact = gap_queue.write_artifact(
            report_path, resume_path, internal_missing, artifact_path)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read --ats-report {report_path}: {exc}",
              file=sys.stderr)
        sys.exit(2)
    print(f"ATS GAP QUEUE: {len(artifact['gaps'])} normalized gap(s) "
          f"-> {artifact_path}")
    gaps = artifact["gaps"]
    return ([gap["term"] for gap in gaps],
            frozenset(gap["term"] for gap in gaps
                      if "external-soft" in gap.get("sources", ())))


def _load_and_render(args):
    """Simulate, load the docx, resolve gaps, print the JD report, and render."""
    source_docx = args.docx
    master_body = _adjacent_master_body(source_docx)
    with tempfile.TemporaryDirectory() as td:
        docx, sim_jd_terms = _print_simulate(
            source_docx, args.simulate, args.jd_file, args.jd_text, td)
        _, body, _, _, _ = de.load(docx)
        roles = _roles(body)
        jd_terms = _resolved_jd_terms(
            args.jd_text, body, args.simulate, sim_jd_terms)
        if args.jd_file:
            internal_missing = _jd_missing_terms(
                args.jd_text, body, jd_terms)
            if master_body is None and internal_missing:
                _fail_without_master(
                    "JD terms with NO host in the resume")
            extra_missing, soft_terms = _external_gap_terms(
                args.ats_report, source_docx, internal_missing)
            if master_body is None and extra_missing:
                _fail_without_master("external ATS gap")
            _print_jd_report(
                args.jd_file, args.jd_text, jd_terms, body,
                InferenceSources(linkedin_text=args.evidence_text,
                                 master_body=master_body,
                                 soft_terms=soft_terms),
                extra_missing=tuple(extra_missing))
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
    ats_report: str | None
    protect: list
    simulate: list


def _parse_measure_args():
    """Parse argv and load the JD/LinkedIn text. Exits 2 on usage/error."""
    argv = list(sys.argv[1:])
    maybe_help(argv, __doc__)
    linkedin_file = extract_flag(argv, "--linkedin")
    ats_report = extract_flag(argv, "--ats-report")
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
                 evidence_text, ats_report, protect, simulate)


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
    body, roles, jd_terms, pages_text, _ = _load_and_render(args)
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
