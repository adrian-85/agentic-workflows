"""Ordered, per-target gates for the resume-tailoring workflow.

Theme quality remains an agent judgment. This module makes the existence of
that judgment, the execution order, and the measurable budget rules explicit.
"""

import argparse
import json
import os
import sys
import tempfile

from script_args import MAX_WORDS


PHASES = (
    "pruned", "prune-theme-reviewed", "ats-audited", "ats-theme-reviewed", "seniority-approved",
    "budgets-closed", "spacers-closed",
)

REVIEW_PHASES = {
    "prune": ("pruned", "prune-theme-reviewed"),
    "ats": ("ats-audited", "ats-theme-reviewed"),
}


class GateError(RuntimeError):
    """Raised when a workflow transition is missing or out of order."""


class ReviewError(ValueError):
    """Raised when a review record is incomplete."""


def _write(path, data):
    """Atomically write JSON state or review data."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=parent, prefix=".workflow-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def create_state(path, target, jd, theme):
    """Create the state sidecar at phase ``pruned`` (auto_prune calls this).

    An existing state past ``pruned`` (an auto_prune re-run with, e.g., a
    corrected --equivalence) is RESET: recorded reviews and phase gates
    die with the replaced build. Warn loudly — the reset is otherwise
    invisible until a later gate rejects."""
    try:
        prior = load_state(path)
    except GateError:
        prior = None
    if prior is not None and prior.get("phase") != "pruned":
        print(f"WORKFLOW STATE RESET: {os.path.basename(path)} was "
              f"{prior.get('phase')} — the re-run replaces the build, "
              "so recorded reviews and gates are gone; re-record "
              "Theme Reviews A/B (SKILL Steps 3-4) before advancing",
              file=sys.stderr)
    _write(path, {
        "version": 1,
        "target": target,
        "jd": jd,
        "theme": theme or "",
        "phase": "pruned",
        "history": [{"phase": "pruned"}],
        "reviews": {},
    })


def load_state(path):
    """Load and minimally validate a state sidecar."""
    try:
        with open(path, encoding="utf-8") as stream:
            state = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"cannot read workflow state {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("phase") not in PHASES:
        raise GateError(f"invalid workflow state: {path}")
    return state


def advance(path, phase, details=None, state_updates=None):
    """Advance exactly one phase, rejecting skips and repeats."""
    state = load_state(path)
    current = PHASES.index(state["phase"])
    try:
        wanted = PHASES.index(phase)
    except ValueError as exc:
        raise GateError(f"unknown workflow phase: {phase}") from exc
    if wanted != current + 1:
        raise GateError(
            f"cannot advance {state['phase']} to {phase}; "
            f"next phase is {PHASES[current + 1] if current + 1 < len(PHASES) else 'none'}")
    state["phase"] = phase
    if state_updates:
        state.update(state_updates)
    state.setdefault("history", []).append({"phase": phase, **(details or {})})
    _write(path, state)


def require(path, phase):
    """Require the exact current phase."""
    state = load_state(path)
    if state["phase"] != phase:
        raise GateError(
            f"requires phase {phase}, current phase is {state['phase']} — "
            f"run: workflow_gate.py status {path}")
    return state


def require_at_least(path, phase):
    """Require that a prior phase has completed."""
    state = load_state(path)
    if PHASES.index(state["phase"]) < PHASES.index(phase):
        raise GateError(
            f"requires phase {phase}, current phase is {state['phase']} — "
            f"run: workflow_gate.py status {path}")
    return state


def _nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ReviewError(f"{label} must be non-empty")


def validate_review(review):
    """Validate the structural contract for one agent review record."""
    if not isinstance(review, dict) or review.get("kind") not in REVIEW_PHASES:
        raise ReviewError("review kind must be 'prune' or 'ats'")
    kind = review["kind"]
    if kind == "prune":
        anchors = review.get("theme_anchors")
        if not isinstance(anchors, list) or not anchors:
            raise ReviewError("prune review needs at least one theme anchor")
        for index, anchor in enumerate(anchors, 1):
            _nonempty(anchor, f"theme_anchors[{index}]")
        entries = review.get("dispositions")
    else:
        entries = review.get("findings")
    if not isinstance(entries, list):
        raise ReviewError(f"{kind} review needs a list of dispositions")
    invalid_decisions = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ReviewError(f"{kind} review entry {index} must be an object")
        _nonempty(entry.get("item" if kind == "prune" else "phrase"),
                  f"{kind} review entry {index} subject")
        allowed = ({"restore", "cut", "keep"} if kind == "prune"
                   else {"host", "ignore", "raise"})
        if entry.get("decision") not in allowed:
            choices = ", ".join(sorted(allowed))
            invalid_decisions.append(
                f"{kind} review entry {index} has invalid decision "
                f"{entry.get('decision')!r}; allowed decisions: {choices}")
        _nonempty(entry.get("rationale"), f"{kind} review entry {index}.rationale")
    if invalid_decisions:
        raise ReviewError("; ".join(invalid_decisions))
    return kind


def print_review_template(kind, state_path):
    """Print a ready-to-fill review skeleton for ``review`` (stdout).

    The review JSON schema is easy to get wrong by hand, and an ATS
    review must disposition EXACTLY the recorded baseline set. The
    template pre-fills what the machine knows — every baseline finding
    phrase, in the state's normalized form — so the agent
    fills only decision/rationale and the set match is guaranteed by
    construction. Usage hints go to stderr so stdout stays redirectable:

        workflow_gate.py template ats <state> > theme_review_<target>_ats.json
    """
    if kind not in REVIEW_PHASES:
        raise GateError(
            f"template kind must be one of {sorted(REVIEW_PHASES)}, got {kind!r}")
    state = load_state(state_path)  # also the path/typo check
    if kind == "ats":
        phrases = state.get("finding_phrases") or []
        if not phrases:
            raise GateError(
                f"{state_path} records no baseline findings — run the baseline audit "
                "first (ats_audit.py --baseline; SKILL Step 4); the template pre-fills "
                "its phrases")
        skeleton = {"kind": "ats", "findings": [
            {"phrase": phrase, "decision": "", "rationale": ""} for phrase in phrases]}
        hint = (
            "decisions: host | ignore | raise. Keep EXACTLY one row per phrase — do not "
            "delete or add rows (the gate matches the recorded baseline set exactly). "
            "Soft-skill phrases default to host when kept bullets evidence them "
            "(Hosting reference: action-verb evidence authorizes the literal phrase).")
    else:
        skeleton = {"kind": "prune", "theme_anchors": [""], "dispositions": [
            {"item": "", "decision": "", "rationale": ""}]}
        hint = (
            "decisions: restore | cut | keep. One disposition per prune override; "
            "item = the master paragraph's find_p prefix (copy it from the --prefixes "
            "dump / cut-set diff). Add more entries as needed.")
    print(json.dumps(skeleton, indent=2))
    print(
        f"fill decision + rationale, keep the phrases/items, then record:\n"
        f"  workflow_gate.py review {state_path} <filled.json>\n" f"({hint})", file=sys.stderr)


def record_audit(path, findings, audit_path=None):
    """Record the baseline audit findings before its agent review.

    Re-audits after hosting land (SKILL Step 4) run when the phase has
    already moved past prune-theme-reviewed; accept those and do not rewind
    the phase by re-advancing.
    """
    require_at_least(path, "prune-theme-reviewed")
    if not isinstance(findings, list):
        raise GateError("baseline audit findings must be a list")
    normalized = sorted({str(item).strip().lower() for item in findings
                         if str(item).strip()})
    details = {"finding_phrases": normalized, "findings": len(normalized)}
    if audit_path:
        details["audit"] = os.path.basename(audit_path)
    if load_state(path)["phase"] == "prune-theme-reviewed":
        advance(path, "ats-audited", details, {"finding_phrases": normalized})
        return
    # Re-audit after the phase moved on: no rewind, but the recorded
    # findings must reflect THIS audit — a first baseline run that found
    # nothing (e.g. word-cap-only, no --jd) must not shadow a later run's
    # real no-host phrases, or the Theme Review B template pre-fills empty.
    state = load_state(path)
    state["finding_phrases"] = normalized
    history = state.setdefault("history", [])
    for entry in reversed(history):
        if entry.get("phase") == "ats-audited":
            entry.update(details)
            break
    _write(path, state)


def record_review(state_path, review_path):
    """Validate and record a prune or ATS review, then advance its gate."""
    try:
        with open(review_path, encoding="utf-8") as stream:
            review = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"cannot read review {review_path}: {exc}") from exc
    kind = validate_review(review)
    expected, next_phase = REVIEW_PHASES[kind]
    state = require(state_path, expected)
    if kind == "ats":
        expected_findings = set(state.get("finding_phrases", []))
        actual_findings = {entry["phrase"].strip().lower()
                           for entry in review["findings"]}
        if actual_findings != expected_findings:
            missing = sorted(expected_findings - actual_findings)
            extra = sorted(actual_findings - expected_findings)
            raise ReviewError(
                f"ATS review findings do not match baseline; missing={missing}, "
                f"unexpected={extra}")
    state.setdefault("reviews", {})[kind] = review
    _write(state_path, state)
    advance(state_path, next_phase, {"review": os.path.basename(review_path)})


def _next_hint(phase):
    """The command that moves the workflow forward from ``phase`` —
    printed by status and appended to gate errors."""
    return {
        "pruned": "workflow_gate.py template prune <state> > theme_review_<target>.json, "
                  "fill it, then: workflow_gate.py review <state> <filled.json>",
        "prune-theme-reviewed": "baseline render + ats_audit.py <pdf> --jd <JD.txt> "
                                "--baseline --workflow-state <state>, plus the early "
                                "external scan (SKILL Step 4)",
        "ats-audited": "workflow_gate.py template ats <state> > theme_review_<target>_ats.json, "
                      "fill it, then: workflow_gate.py review <state> <filled.json>",
        "ats-theme-reviewed": "present the measured seniority drop plan; after the USER "
                              "approves: workflow_gate.py advance <state> seniority-approved",
        "seniority-approved": "workflow_gate.py budgets <state> --words <N> --spill-lines <N> "
                              "[--target-pages <N>]",
        "budgets-closed": "workflow_gate.py spacers <state> [--omitted \"<role header>;...\"]",
        "spacers-closed": "final render + audits (SKILL Step 12) — no further gate",
    }[phase]


def print_status(path):
    """Print the state's phase, recorded reviews, and the next command
    (run it instead of reconstructing the phase from gate errors)."""
    state = load_state(path)
    phase = state["phase"]
    print(f"state:  {path}")
    print(f"target: {state.get('target', '')}   jd: {state.get('jd', '')}")
    print(f"phase:  {phase}   ({PHASES.index(phase) + 1} of {len(PHASES)})")
    reviews = state.get("reviews", {})
    if reviews:
        parts = []
        for kind in ("prune", "ats"):
            if kind not in reviews:
                continue
            key = "dispositions" if kind == "prune" else "findings"
            parts.append(f"{kind} ({len(reviews[kind].get(key, []))} entries)")
        print(f"reviews recorded: {', '.join(parts)}")
    if state.get("spacers_omitted"):
        print(f"spacers omitted: {len(state['spacers_omitted'])} boundary/boundaries")
    print(f"next:   {_next_hint(phase)}")


def page_removal_allowed(spill_lines):
    """Return whether the narrow page-removal trim rule permits a pass."""
    return isinstance(spill_lines, int) and 0 < spill_lines <= 5


def close_budgets(path, words, spill_lines, attempted_page_removal,
                  target_pages=None):
    """Close measurable budgets after seniority and positioning edits.

    ``target_pages`` (optional) records the page target agreed at Step 5 —
    render_pdf.sh falls back to it when a render omits --target-pages, so
    overflow measures against the target the user actually approved."""
    require(path, "seniority-approved")
    if words > MAX_WORDS:
        raise GateError(
            f"word budget remains open: {words} words exceeds {MAX_WORDS}")
    if attempted_page_removal and not page_removal_allowed(spill_lines):
        raise GateError(
            "page removal is allowed only for a positive spill of five lines or fewer")
    advance(path, "budgets-closed", {
        "words": words,
        "spill_lines": spill_lines,
        "page_removal_attempted": attempted_page_removal,
        "target_pages": target_pages,
    }, state_updates={"target_pages": target_pages})


def close_spacers(path, creates_new_page, omitted=None):
    """Close the final spacer pass without allowing a new page.

    ``omitted`` records boundaries where page pressure legitimately kept the
    spacer out (SKILL Step 9: omit the spacer, never theme-aligned
    content). The record is what final-phase validation exempts — an
    unrecorded missing spacer still blocks the deliverable.
    """
    require_at_least(path, "budgets-closed")
    if creates_new_page:
        raise GateError("spacers would create a new page")
    omitted = [name.strip() for name in (omitted or []) if name.strip()]
    if load_state(path)["phase"] == "spacers-closed":
        # Re-record omissions (e.g. correcting a header string after render
        # feedback) without rewinding the phase.
        state = load_state(path)
        state["spacers_omitted"] = omitted
        state.setdefault("history", []).append(
            {"phase": "spacers-closed", "spacers_omitted": omitted})
        _write(path, state)
        return
    advance(path, "spacers-closed",
            {"creates_new_page": False, "spacers_omitted": omitted},
            state_updates={"spacers_omitted": omitted})


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review")
    review.add_argument("state")
    review.add_argument("review")
    template_parser = sub.add_parser(
        "template", help="print a ready-to-fill review skeleton (stdout)")
    template_parser.add_argument("kind", choices=sorted(REVIEW_PHASES))
    template_parser.add_argument("state")
    advance_parser = sub.add_parser(
        "advance", usage=(
            "workflow_gate.py advance <state> {"
            + "|".join(PHASES[1:])
            + "}   # e.g. advance 'Name Resume - Target.docx.workflow.json' "
              "seniority-approved"))
    advance_parser.add_argument("state")
    advance_parser.add_argument("phase", choices=PHASES[1:])
    require_parser = sub.add_parser("require")
    require_parser.add_argument("state")
    require_parser.add_argument("phase", choices=PHASES)
    status_parser = sub.add_parser(
        "status", help="print current phase + the next command (stdout)")
    status_parser.add_argument("state")
    at_least_parser = sub.add_parser("require-at-least")
    at_least_parser.add_argument("state")
    at_least_parser.add_argument("phase", choices=PHASES)
    budget_parser = sub.add_parser(
        "budgets", usage=(
            "workflow_gate.py budgets <state> --words N "
            "[--spill-lines N] [--attempted-page-removal] "
            "[--target-pages N]   # e.g. budgets "
            "'Name Resume - Target.docx.workflow.json' --words 998 "
            "--target-pages 3"))
    budget_parser.add_argument("state")
    budget_parser.add_argument("--words", type=int, required=True)
    budget_parser.add_argument("--spill-lines", type=int, default=0)
    budget_parser.add_argument("--attempted-page-removal", action="store_true")
    budget_parser.add_argument(
        "--target-pages", type=int,
        help="the page target agreed at Step 5; render_pdf.sh falls back to "
             "it when a render omits --target-pages")
    spacer_parser = sub.add_parser(
        "spacers", usage=(
            "workflow_gate.py spacers <state> [--creates-new-page] "
            "[--omitted '<role header>[;...]']   # e.g. spacers "
            "'Name Resume - Target.docx.workflow.json'"))
    spacer_parser.add_argument("state")
    spacer_parser.add_argument("--creates-new-page", action="store_true")
    spacer_parser.add_argument(
        "--omitted", default="",
        help="role headers where page pressure kept the spacer out, "
             "separated by ';' (headers themselves contain commas); a "
             "comma-separated list is still accepted for header-free names")
    # parse_known_args + explicit leftover check: argparse reports
    # post-subcommand unknown flags with the TOP-LEVEL usage, which hides
    # the subcommand's own flag list and example (the '--pages' vs
    # '--target-pages' confusion this prevents).
    args, extras = parser.parse_known_args(argv)
    if extras:
        sub = {"advance": advance_parser, "budgets": budget_parser,
               "spacers": spacer_parser}.get(args.command)
        if sub is not None:
            sub.error("unrecognized arguments: " + " ".join(extras))
        parser.error("unrecognized arguments: " + " ".join(extras))
    try:
        _dispatch(args)
    except (GateError, ReviewError) as exc:
        parser.error(str(exc))
    return 0


def _dispatch(args):
    """Run one parsed subcommand (extracted from _main for statement budget)."""
    if args.command == "review":
        record_review(args.state, args.review)
    elif args.command == "template":
        print_review_template(args.kind, args.state)
    elif args.command == "advance":
        advance(args.state, args.phase)
    elif args.command == "budgets":
        close_budgets(args.state, args.words, args.spill_lines,
                      args.attempted_page_removal, args.target_pages)
    elif args.command == "spacers":
        omitted = _split_omitted(args.omitted)
        close_spacers(args.state, args.creates_new_page, omitted)
    elif args.command == "require-at-least":
        require_at_least(args.state, args.phase)
    elif args.command == "status":
        print_status(args.state)
    else:
        require(args.state, args.phase)


def _split_omitted(omitted):
    """Parse the spacers --omitted list into role-header names.

    Role headers contain commas ("GEICO, Chevy Chase, MD"), so the documented
    separator is ';'; fall back to ',' only when no ';' is present
    (header-free names)."""
    if not omitted:
        return None
    sep = ";" if ";" in omitted else ","
    return omitted.split(sep)


if __name__ == "__main__":
    raise SystemExit(_main())
