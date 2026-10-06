"""Judgment layer: prompt build, headless session, validation, lint.

One `pi --no-session --mode json -p <prompt>` session per run judges
every candidate posting against the configured criteria (spec §4).
Output is validated against the JSON contract, coverage-checked against
the requested postings, consistency-linted (pay vs decision), and only
then recorded. Malformed output retries exactly once, then fails the
run loudly — nothing partial reaches the ledger.
"""

import json
import subprocess
from dataclasses import dataclass

from config import Config, criteria_hash
import ledger
from postings import Posting

DECISIONS = ("preferred", "acceptable", "unacceptable", "excluded", "review")
REASONS = ("none", "pay_below_threshold", "not_relevant", "ethics")
PAY_BASES = ("range_top", "point", "hourly_x2080", "none")
PI_TIMEOUT_SECONDS = 1800


class JudgeFormatError(Exception):
    """Session output violates the output contract."""


class JudgeError(Exception):
    """The judgment session failed after its one retry."""


@dataclass
# One attribute per contract field (pay flattened) — the spec §4 schema.
# Upstream pylint#9058 tracks a method-less-dataclass exemption for
# R0902; drop this pragma when the repo's pinned pylint ships it.
class Judgment:  # pylint: disable=too-many-instance-attributes
    """One validated session judgment (spec §4 schema, pay flattened)."""

    posting_id: str
    decision: str
    reason: str
    pay_seen: bool
    pay_top: int | None
    pay_annualized: int | None
    pay_basis: str
    rationale_short: str
    lint_note: str | None = None


def build_judge_prompt(cfg: Config, postings: list[Posting],
                       resume_text: str) -> str:
    """Render criteria, contract, resume, and postings for the session."""
    postings_payload = [
        {
            "posting_id": p.posting_id,
            "company": p.company,
            "title": p.title,
            "location": p.location,
            "pay_raw": p.pay_raw,
            "url": p.url,
            "review_flags": p.review_flags,
            "jd_text": p.jd_text,
        }
        for p in postings
    ]
    return f"""You are judging job postings for a job seeker. Judge EVERY
posting independently against the criteria, and respond with ONLY a JSON
array (no prose, no code fences).

CRITERIA (criteria_version {criteria_hash(cfg)}):
- Pay tiers (USD/year): preferred at or above {cfg.preferred_min};
  acceptable from {cfg.acceptable_min} to {cfg.preferred_min - 1};
  unacceptable below {cfg.acceptable_min}.
- Pay parsing: a range tiers by its TOP figure; a single figure is
  itself; hourly pay annualizes as rate x {cfg.hours_per_year};
  "up to $X" means max = $X. A posting with NO pay listed is the
  ACCEPTABLE tier (pay seen=false, annualized=null).
- Relevance (hard gate outranking pay — an irrelevant posting is
  "excluded" with reason "not_relevant" no matter the salary):
{cfg.relevance_domains}
- Ethics (role-based — judge what the WORK directly contributes to,
  employer type is evidence not verdict; violation -> "excluded" with
  reason "ethics"):
{cfg.ethics_rule}
- Remote/US-workability and posting age were already handled
  deterministically upstream: do NOT re-judge them. review_flags on a
  posting are upstream warnings, not decisions.
- If a posting is not easy to call, decide "review" with reason "none".

RESUME (the job seeker's profile):
{resume_text}

POSTINGS:
{json.dumps(postings_payload, indent=1)}

OUTPUT CONTRACT — a JSON array with EXACTLY one object per posting,
each object with EXACTLY these fields:
{{"posting_id": "<posting_id>", "decision":
"preferred|acceptable|unacceptable|excluded|review", "reason":
"none|pay_below_threshold|not_relevant|ethics", "pay":
{{"seen": <bool>, "top": <int|null>, "annualized": <int|null>, "basis":
"range_top|point|hourly_x2080|none"}}, "rationale_short": "<one line>"}}"""


def validate(raw: str) -> list[Judgment]:
    """Parse and shape-check session output; raise JudgeFormatError."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeFormatError(f"not JSON: {exc}") from exc
    if isinstance(payload, dict) and "judgments" in payload:
        payload = payload["judgments"]
    if not isinstance(payload, list) or not payload:
        raise JudgeFormatError("expected a non-empty JSON array")
    judgments = []
    for item in payload:
        judgments.append(_validate_one(item))
    return judgments


def lint(judgments: list[Judgment], cfg: Config) -> list[Judgment]:
    """Flag genuine pay/decision contradictions as review (spec §4).

    An excluded posting with high pay is NOT a contradiction —
    relevance and ethics legitimately outrank pay.
    """
    for judgment in judgments:
        annualized = judgment.pay_annualized
        if annualized is None:
            continue
        if (annualized >= cfg.preferred_min
                and judgment.decision == "acceptable"):
            judgment.decision = "review"
            judgment.lint_note = (
                f"annualized {annualized} >= preferred "
                f"{cfg.preferred_min} but decision was acceptable")
        elif (annualized < cfg.acceptable_min
                and judgment.decision in ("preferred", "acceptable")):
            judgment.decision = "review"
            judgment.lint_note = (
                f"annualized {annualized} < acceptable "
                f"{cfg.acceptable_min} but decision was {judgment.decision}")
    return judgments


def run_judgment(cfg: Config, postings: list[Posting], resume_text: str,
                 runner=None) -> list[Judgment]:
    """Run the session (retry once), validate, coverage-check, lint."""
    if runner is None:
        runner = _default_runner
    prompt = build_judge_prompt(cfg, postings, resume_text)
    last_error = None
    for _attempt in range(2):
        stdout = runner(prompt)
        try:
            judgments = validate(extract_final_message(stdout))
            _check_coverage(judgments, postings)
            return lint(judgments, cfg)
        except JudgeFormatError as exc:
            last_error = exc
            prompt = (f"{prompt}\n\nYour previous reply was invalid: "
                      f"{exc}. Respond again with ONLY the JSON array, "
                      f"exactly one object per posting.")
    raise JudgeError(f"judgment session invalid after retry: {last_error}")


def record_judgments(judgments: list[Judgment], postings: list[Posting],
                     state_dir, cfg: Config, run_id: str) -> None:
    """Append one judged event per judgment to the ledger."""
    by_id = {p.posting_id: p for p in postings}
    for judgment in judgments:
        posting = by_id.get(judgment.posting_id)
        ledger.append_event(state_dir, {
            "run_id": run_id,
            "posting_id": judgment.posting_id,
            "url": posting.url if posting else "",
            "company": posting.company if posting else "",
            "title": posting.title if posting else "",
            "event": "judged",
            "decision": judgment.decision,
            "reason": judgment.reason,
            "rationale_short": judgment.rationale_short,
            "criteria_version": criteria_hash(cfg),
        })


def extract_final_message(stdout: str) -> str:
    """Final assistant text from pi --mode json JSONL events."""
    final = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (event.get("type") == "message_end"
                and (event.get("message") or {}).get("role") == "assistant"):
            final = event["message"].get("content") or []
    if final is None:
        return ""
    return "".join(part.get("text", "")
                   for part in final if part.get("type") == "text")


def _default_runner(prompt: str) -> str:
    """Spawn the headless pi session and return its stdout."""
    result = subprocess.run(
        ["pi", "--no-session", "--mode", "json", "-p", prompt],
        capture_output=True, text=True, timeout=PI_TIMEOUT_SECONDS,
        check=False)
    return result.stdout


def _check_coverage(judgments: list[Judgment], postings: list[Posting]):
    """Exactly one judgment per requested posting."""
    expected = {p.posting_id for p in postings}
    actual = [j.posting_id for j in judgments]
    missing = expected - set(actual)
    duplicated = {pid for pid in actual if actual.count(pid) > 1}
    if missing or duplicated:
        raise JudgeFormatError(
            f"coverage mismatch (missing: {sorted(missing)}, "
            f"duplicated: {sorted(duplicated)})")


def _validate_one(item) -> Judgment:
    """Shape-check one judgment object."""
    if not isinstance(item, dict):
        raise JudgeFormatError("judgment is not an object")
    for field in ("posting_id", "decision", "reason", "pay",
                  "rationale_short"):
        if field not in item:
            raise JudgeFormatError(f"judgment missing field: {field}")
    if item["decision"] not in DECISIONS:
        raise JudgeFormatError(f"unknown decision: {item['decision']!r}")
    if item["reason"] not in REASONS:
        raise JudgeFormatError(f"unknown reason: {item['reason']!r}")
    pay = item["pay"]
    if not isinstance(pay, dict) or "seen" not in pay:
        raise JudgeFormatError("pay block missing or malformed")
    basis = pay.get("basis") or "none"
    if basis not in PAY_BASES:
        raise JudgeFormatError(f"unknown pay basis: {basis!r}")
    return Judgment(
        posting_id=item["posting_id"],
        decision=item["decision"],
        reason=item["reason"],
        pay_seen=bool(pay["seen"]),
        pay_top=_int_or_none(pay.get("top")),
        pay_annualized=_int_or_none(pay.get("annualized")),
        pay_basis=basis,
        rationale_short=str(item["rationale_short"]),
    )


def _int_or_none(value) -> int | None:
    """Numeric to int; None stays None."""
    return None if value is None else int(value)
