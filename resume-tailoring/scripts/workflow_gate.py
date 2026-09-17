"""Ordered, per-target gates for the resume-tailoring workflow.

Theme quality remains an agent judgment. This module makes the existence of
that judgment, the execution order, and the measurable budget rules explicit.
"""

import argparse
import json
import os
import tempfile

from script_args import MAX_WORDS


PHASES = (
    "pruned",
    "prune-theme-reviewed",
    "ats-audited",
    "ats-theme-reviewed",
    "seniority-approved",
    "budgets-closed",
    "spacers-closed",
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
    """Create the state sidecar at phase ``pruned`` (auto_prune calls this)."""
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
        raise GateError(f"requires phase {phase}, current phase is {state['phase']}")
    return state


def require_at_least(path, phase):
    """Require that a prior phase has completed."""
    state = load_state(path)
    if PHASES.index(state["phase"]) < PHASES.index(phase):
        raise GateError(f"requires phase {phase}, current phase is {state['phase']}")
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
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ReviewError(f"{kind} review entry {index} must be an object")
        _nonempty(entry.get("item" if kind == "prune" else "phrase"),
                  f"{kind} review entry {index} subject")
        allowed = ({"restore", "cut", "keep"} if kind == "prune"
                   else {"host", "ignore", "raise"})
        if entry.get("decision") not in allowed:
            raise ReviewError(f"{kind} review entry {index} has invalid decision")
        _nonempty(entry.get("rationale"), f"{kind} review entry {index}.rationale")
    return kind


def record_audit(path, findings, audit_path=None):
    """Record the baseline audit findings before its agent review."""
    require(path, "prune-theme-reviewed")
    if not isinstance(findings, list):
        raise GateError("baseline audit findings must be a list")
    normalized = sorted({str(item).strip().lower() for item in findings
                         if str(item).strip()})
    details = {"finding_phrases": normalized, "findings": len(normalized)}
    if audit_path:
        details["audit"] = os.path.basename(audit_path)
    advance(path, "ats-audited", details, {"finding_phrases": normalized})


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


def page_removal_allowed(spill_lines):
    """Return whether the narrow page-removal trim rule permits a pass."""
    return isinstance(spill_lines, int) and 0 < spill_lines <= 5


def close_budgets(path, words, spill_lines, attempted_page_removal):
    """Close measurable budgets after seniority and positioning edits."""
    require(path, "seniority-approved")
    if words > MAX_WORDS:
        raise GateError(
            f"word budget remains open: {words} words exceeds {MAX_WORDS}")
    if attempted_page_removal and not page_removal_allowed(spill_lines):
        raise GateError(
            "page removal is allowed only for a positive spill of five lines "
            "or fewer")
    advance(path, "budgets-closed", {
        "words": words,
        "spill_lines": spill_lines,
        "page_removal_attempted": attempted_page_removal,
    })


def close_spacers(path, creates_new_page):
    """Close the final spacer pass without allowing a new page."""
    require(path, "budgets-closed")
    if creates_new_page:
        raise GateError("spacers would create a new page")
    advance(path, "spacers-closed", {"creates_new_page": False})


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review")
    review.add_argument("state")
    review.add_argument("review")
    advance_parser = sub.add_parser("advance")
    advance_parser.add_argument("state")
    advance_parser.add_argument("phase", choices=PHASES[1:])
    require_parser = sub.add_parser("require")
    require_parser.add_argument("state")
    require_parser.add_argument("phase", choices=PHASES)
    at_least_parser = sub.add_parser("require-at-least")
    at_least_parser.add_argument("state")
    at_least_parser.add_argument("phase", choices=PHASES)
    budget_parser = sub.add_parser("budgets")
    budget_parser.add_argument("state")
    budget_parser.add_argument("--words", type=int, required=True)
    budget_parser.add_argument("--spill-lines", type=int, default=0)
    budget_parser.add_argument("--attempted-page-removal", action="store_true")
    spacer_parser = sub.add_parser("spacers")
    spacer_parser.add_argument("state")
    spacer_parser.add_argument("--creates-new-page", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "review":
            record_review(args.state, args.review)
        elif args.command == "advance":
            advance(args.state, args.phase)
        elif args.command == "budgets":
            close_budgets(args.state, args.words, args.spill_lines,
                          args.attempted_page_removal)
        elif args.command == "spacers":
            close_spacers(args.state, args.creates_new_page)
        elif args.command == "require-at-least":
            require_at_least(args.state, args.phase)
        else:
            require(args.state, args.phase)
    except (GateError, ReviewError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
