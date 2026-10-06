"""Judge layer tests: prompt build, session output validation, lint.

The session runner is always mocked; the JSONL event shape mirrors pi's
live --mode json output (calibrated 2026-10-05). All postings synthetic.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import judge
import ledger
from test_helpers import make_config, make_posting

CFG = make_config(preferred_min=200000, acceptable_min=90000,
                  ethics_rule="example ethics rule",
                  relevance_domains="example relevance domains")
POSTING = make_posting(jd_text="Example Corp SDET role owning CI/CD quality.")
SECOND = make_posting(posting_id="mock:2", url="https://jobs.example.com/2",
                      jd_url="https://jobs.example.com/2",
                      jd_text="Example Corp QA automation role.",
                      review_flags=["date-unverified"])


# Defaults per parameter — the spec §4 sample values.
def _valid_judgment(posting_id: str, decision: str = "acceptable",  # pylint: disable=too-many-arguments,too-many-positional-arguments
                    reason: str = "none", top=120000, annualized=120000,
                    basis: str = "range_top") -> dict:
    return {
        "posting_id": posting_id,
        "decision": decision,
        "reason": reason,
        "pay": {"seen": True, "top": top, "annualized": annualized,
                "basis": basis},
        "rationale_short": "synthetic rationale",
    }


def _jsonl_stdout(payload) -> str:
    """pi --mode json style stdout carrying payload as assistant text."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return json.dumps({"type": "agent_start"}) + "\n" + json.dumps({
        "type": "message_end",
        "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "internal"},
            {"type": "text", "text": text},
        ]},
    }) + "\n" + json.dumps({"type": "turn_end"}) + "\n"


class BuildPromptTest(unittest.TestCase):
    """build_judge_prompt renders criteria, contract, resume, postings."""

    def test_prompt_contains_criteria_and_contract(self):
        """Thresholds, ethics text, decision/reason enums all present."""
        prompt = judge.build_judge_prompt(
            CFG, [POSTING], "resume text")
        self.assertIn("200000", prompt)
        self.assertIn("90000", prompt)
        self.assertIn("2080", prompt)
        self.assertIn("example ethics rule", prompt)
        self.assertIn("example relevance domains", prompt)
        for decision in ("preferred", "acceptable", "unacceptable",
                         "excluded", "review"):
            self.assertIn(decision, prompt)
        self.assertIn("pay_below_threshold", prompt)
        self.assertIn("posting_id", prompt)
        self.assertIn("criteria_version", prompt)

    def test_prompt_contains_resume_text_and_postings(self):
        """Resume text and each posting's fields/jd_text ride along."""
        prompt = judge.build_judge_prompt(
            CFG, [POSTING, SECOND], "RESUME MARKER TEXT")
        self.assertIn("RESUME MARKER TEXT", prompt)
        self.assertIn(POSTING.posting_id, prompt)
        self.assertIn(SECOND.posting_id, prompt)
        self.assertIn("owning CI/CD quality", prompt)
        self.assertIn("date-unverified", prompt)


class ValidateTest(unittest.TestCase):
    """validate enforces the spec §4 output contract."""

    def test_validate_parses_valid_block(self):
        """A bare JSON array parses into Judgment objects."""
        judgments = judge.validate(json.dumps(
            [_valid_judgment("mock:1"), _valid_judgment("mock:2")]))
        self.assertEqual(len(judgments), 2)
        self.assertEqual(judgments[0].posting_id, "mock:1")
        self.assertTrue(judgments[0].pay_seen)

    def test_validate_parses_judgments_wrapper(self):
        """A {"judgments": [...]} wrapper parses identically."""
        judgments = judge.validate(json.dumps(
            {"judgments": [_valid_judgment("mock:1")]}))
        self.assertEqual(len(judgments), 1)

    def test_validate_rejects_unknown_decision(self):
        """A decision outside the enum fails loudly."""
        with self.assertRaises(judge.JudgeFormatError):
            judge.validate(json.dumps(
                [_valid_judgment("mock:1", decision="maybe")]))

    def test_validate_rejects_missing_pay_field(self):
        """A judgment without the pay block fails loudly."""
        broken = _valid_judgment("mock:1")
        del broken["pay"]
        with self.assertRaises(judge.JudgeFormatError):
            judge.validate(json.dumps([broken]))


class LintTest(unittest.TestCase):
    """Consistency lint: pay/decision contradictions become review."""

    def test_lint_high_pay_marked_acceptable_becomes_review(self):
        """annualized >= preferred but acceptable -> review + note."""
        judgments = judge.validate(json.dumps(
            [_valid_judgment("mock:1", decision="acceptable",
                             top=200000, annualized=200000)]))
        linted = judge.lint(judgments, CFG)
        self.assertEqual(linted[0].decision, "review")
        self.assertIsNotNone(linted[0].lint_note)

    def test_lint_low_pay_marked_acceptable_becomes_review(self):
        """annualized below acceptable but acceptable -> review + note."""
        judgments = judge.validate(json.dumps(
            [_valid_judgment("mock:1", decision="acceptable",
                             top=80000, annualized=80000)]))
        linted = judge.lint(judgments, CFG)
        self.assertEqual(linted[0].decision, "review")
        self.assertIsNotNone(linted[0].lint_note)

    def test_lint_excluded_high_pay_not_flagged(self):
        """Relevance/ethics outrank pay: excluded high pay stands."""
        judgments = judge.validate(json.dumps(
            [_valid_judgment("mock:1", decision="excluded",
                             reason="not_relevant",
                             top=300000, annualized=300000)]))
        linted = judge.lint(judgments, CFG)
        self.assertEqual(linted[0].decision, "excluded")
        self.assertIsNone(linted[0].lint_note)


class RunJudgmentTest(unittest.TestCase):
    """run_judgment: retry-once, loud failure, coverage, lint applied."""

    def test_run_judgment_success_returns_linted(self):
        """A valid session returns linted judgments for every posting."""
        runner_calls = []
        def runner(prompt):
            runner_calls.append(prompt)
            return _jsonl_stdout([_valid_judgment("mock:1"),
                                  _valid_judgment("mock:2")])
        judgments = judge.run_judgment(CFG, [POSTING, SECOND],
                                       "resume", runner=runner)
        self.assertEqual(len(judgments), 2)
        self.assertEqual(runner_calls and len(runner_calls), 1)

    def test_run_judgment_retries_once_then_fails_loudly(self):
        """Garbage twice -> JudgeError; runner invoked exactly twice."""
        calls = []
        def runner(prompt):
            calls.append(prompt)
            return "not json at all"
        with self.assertRaises(judge.JudgeError):
            judge.run_judgment(CFG, [POSTING], "resume", runner=runner)
        self.assertEqual(len(calls), 2)
        self.assertIn("invalid", calls[1].lower())

    def test_run_judgment_rejects_missing_posting(self):
        """Valid JSON missing a requested posting retries, then fails."""
        def runner(_prompt):
            return _jsonl_stdout([_valid_judgment("mock:1")])
        with self.assertRaises(judge.JudgeError):
            judge.run_judgment(CFG, [POSTING, SECOND], "resume",
                               runner=runner)


class ExtractFinalMessageTest(unittest.TestCase):
    """extract_final_message reads pi's --mode json event stream."""

    def test_extract_final_message_from_json_mode_stdout(self):
        """Last assistant message_end's text items concatenate."""
        stdout = _jsonl_stdout([_valid_judgment("mock:1")])
        text = judge.extract_final_message(stdout)
        self.assertIn('"posting_id": "mock:1"', text)

    def test_extract_final_message_empty_on_garbage(self):
        """Non-JSON stdout yields empty text (validation then fails)."""
        self.assertEqual(judge.extract_final_message("garbage"), "")


class RecordJudgmentsTest(unittest.TestCase):
    """record_judgments appends judged events with criteria_version."""

    def test_record_judgments_appends_events(self):
        """Each judgment becomes one ledger event."""
        state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state_dir, ignore_errors=True)
        judgments = judge.validate(json.dumps(
            [_valid_judgment("mock:1")]))
        judge.record_judgments(judgments, [POSTING], state_dir, CFG,
                               run_id="run42")
        state = ledger.current_state(state_dir)
        self.assertEqual(state["mock:1"]["event"], "judged")
        self.assertEqual(state["mock:1"]["run_id"], "run42")
        self.assertEqual(state["mock:1"]["criteria_version"],
                         judge.criteria_hash(CFG))
        self.assertEqual(state["mock:1"]["decision"], "acceptable")


if __name__ == "__main__":
    unittest.main()
