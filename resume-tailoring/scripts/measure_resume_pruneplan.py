"""measure_resume_pruneplan — PRUNE-PLAN mode (the master's ONLY sanctioned
measure run, SKILL Step 3).

Split from measure_resume.py: the master mode is a distinct pipeline with
its own entry (`_main_prune_plan`), its own printers, and its own sidecar
artifact — it shares the JD report printers with the tailored-copy report
but no page math (the unpruned master is never measured). measure_resume.py
re-imports the public entry so the `measure_resume` facade and its tests
stay stable.
"""

import json
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import docx_edit as de  # noqa: E402
from measure_resume_drops import (  # noqa: E402
    _jd_fit_audit,
    _keep_trim_section,
    prune_candidates)
from measure_resume_format import _roles  # noqa: E402
from measure_resume_jd import (  # noqa: E402
    InferenceSources,
    _print_jd_coverage,
    _print_jd_report,
    _top_block_candidates)
import jd_asks  # noqa: E402


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
    jd_terms = {a.phrase for a in jd_asks.parse_asks(args.jd_text)}
    print("PRUNE PLAN — master input: cut everything irrelevant FIRST "
          "(SKILL Step 3) — every OFF-JD/weak bullet, dead sentence, "
          "non-JD clause, and non-JD list chunk below goes in the first "
          "pass, before any page target, role drop, seniority, or word "
          "count is decided. Page/word math on the unpruned master is "
          "never measured; prune, then measure the tailored copy "
          "(SKILL Step 4).")
    print()
    _print_jd_report(args.jd_file, args.jd_text, jd_terms, body,
                     InferenceSources(linkedin_text=args.evidence_text))
    _print_jd_coverage(roles, body, args.jd_text, jd_terms)
    _print_jd_audit(roles, body, jd_terms, args.protect)
    _print_top_block_prune(body, jd_terms)
    candidates = prune_candidates(roles, jd_terms, body, protect=args.protect)
    sidecar = _write_prune_sidecar(args.docx, args.jd_file, candidates)
    _print_disposition_checklist(sidecar, candidates)


def _write_prune_sidecar(docx_path, jd_file, candidates):
    """Write the machine-readable prune plan next to the master.

    ``<master>.prune.json`` — the same sidecar pattern as the drift
    file: docx_edit.py --lint-prune (run_tailor.sh) reads it and blocks
    the tailor run while any candidate lacks an edit or a recorded
    ``# kept:`` reason. Written fresh on EVERY --jd run, so re-running
    the prune plan also refreshes it after a master fold or a user edit.
    Returns the sidecar path.
    """
    path = de.prune_sidecar_path(docx_path, jd_file)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"jd": os.path.basename(jd_file) if jd_file else None,
                   "candidates": candidates}, f, indent=1)
    return path


def _print_disposition_checklist(sidecar_path, candidates):
    """The fill-in disposition table for the ONE-message plan (SKILL
    Steps 2-4) — the fix for the motivating session's 'Prune plan
    highlights' summary, which listed only the bullet cuts and left the
    word/sentence-level trims out of the user's approval entirely."""
    print()
    print(f"PRUNE COVERAGE SIDECAR: {sidecar_path}")
    print("PRUNE DISPOSITION CHECKLIST — EVERY candidate needs exactly one "
          "disposition: CUT (drop whole), TRIM (word-level per the plan: "
          "cut the flagged sentence, strip the flagged clause/chunk), or "
          "KEEP (# kept: <one-line JD reason>). Copy this table into the "
          "ONE-message plan filled in — 'highlights' are not a plan — and "
          "mirror every row in the tailor script: run_tailor.sh exits 2 "
          "while any line is uncovered (--lint-prune).")
    for i, c in enumerate(candidates, 1):
        anchor = (f'find_p(ps, "{c["prefix"]}")' if c["prefix"]
                  else "(no unique prefix)")
        print(f"  {i:2d}. {c['kind']:<10s} {anchor}")
        print(f"      # {c['text'][:76]}")
        if c["detail"]:
            print(f"      ({c['detail'][:76]})")
    print()
