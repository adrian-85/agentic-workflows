"""Ledger tests: append-only events, current state, applied exclusion, CLI.

All postings are synthetic (Example Corp) — no personal data (spec:
testing rule).
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import ledger


class LedgerTest(unittest.TestCase):
    """append_event/current_state/applied_ids semantics."""

    def setUp(self):
        self.state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state_dir, ignore_errors=True)

    def _event(self, posting_id: str, event: str, **extra) -> dict:
        base = {
            "posting_id": posting_id,
            "url": f"https://jobs.example.com/{posting_id}",
            "company": "Example Corp",
            "title": "Staff Engineer in Test",
            "event": event,
            "decision": "acceptable",
            "reason": "none",
            "rationale_short": "synthetic test event",
            "criteria_version": "abc123",
        }
        base.update(extra)
        return base

    def test_append_and_current_state_latest_wins(self):
        """The newest event per posting_id is its current state."""
        ledger.append_event(self.state_dir, self._event("a:1", "judged"))
        ledger.append_event(
            self.state_dir, self._event("a:1", "corrected", decision="review")
        )
        ledger.append_event(self.state_dir, self._event("a:2", "judged"))
        state = ledger.current_state(self.state_dir)
        self.assertEqual(set(state), {"a:1", "a:2"})
        self.assertEqual(state["a:1"]["decision"], "review")

    def test_append_auto_fills_ts_and_run_id(self):
        """Events missing ts/run_id get them filled on append."""
        ledger.append_event(self.state_dir, self._event("a:1", "judged"))
        event = ledger.current_state(self.state_dir)["a:1"]
        self.assertIn("ts", event)
        self.assertIn("run_id", event)

    def test_current_state_skips_trailing_partial_line(self):
        """A crashed mid-append partial line never breaks current_state."""
        ledger.append_event(self.state_dir, self._event("a:1", "judged"))
        ledger_file = self.state_dir / ledger.LEDGER_FILENAME
        with open(ledger_file, "a", encoding="utf-8") as fh:
            fh.write('{"posting_id": "a:2", "event": "jud')
        state = ledger.current_state(self.state_dir)
        self.assertEqual(set(state), {"a:1"})

    def test_applied_ids_excludes_from_results(self):
        """Applied postings never resurface — sticky across later events."""
        ledger.append_event(self.state_dir, self._event("a:1", "judged"))
        ledger.append_event(
            self.state_dir, self._event("a:1", "marked-applied")
        )
        ledger.append_event(self.state_dir, self._event("a:2", "judged"))
        # A later judged event must not un-apply a:1 (early-mode re-judging).
        ledger.append_event(self.state_dir, self._event("a:1", "judged"))
        self.assertEqual(ledger.applied_ids(self.state_dir), {"a:1"})

    def test_retry_tailor_cli_appends_queue_event(self):
        """retry-tailor re-queues a posting as tailoring-queued."""
        ledger.append_event(self.state_dir, self._event("a:1", "judged"))
        ledger.main(["retry-tailor", "a:1"], state_dir=self.state_dir)
        state = ledger.current_state(self.state_dir)
        self.assertEqual(state["a:1"]["event"], "tailoring-queued")


class LedgerCliTest(unittest.TestCase):
    """mark-applied and show CLI behavior."""

    def setUp(self):
        self.state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state_dir, ignore_errors=True)
        ledger.append_event(
            self.state_dir,
            {
                "posting_id": "board:77",
                "url": "https://jobs.example.com/postings/77?utm=track",
                "company": "Example Corp",
                "title": "QA Engineer",
                "event": "judged",
                "decision": "preferred",
                "reason": "none",
                "rationale_short": "synthetic",
                "criteria_version": "abc123",
            },
        )

    def test_mark_applied_cli_appends_event(self):
        """A posting URL resolves to its ledger posting_id (query-insensitive)."""
        ledger.main(
            ["mark-applied", "https://jobs.example.com/postings/77"],
            state_dir=self.state_dir,
        )
        state = ledger.current_state(self.state_dir)
        self.assertEqual(state["board:77"]["event"], "marked-applied")

    def test_mark_applied_by_id_appends_event(self):
        """A direct posting_id marks applied without URL resolution."""
        ledger.main(["mark-applied", "board:77"], state_dir=self.state_dir)
        state = ledger.current_state(self.state_dir)
        self.assertEqual(state["board:77"]["event"], "marked-applied")

    def test_mark_applied_unknown_url_errors(self):
        """An unknown URL fails loudly instead of writing a bogus id."""
        with self.assertRaises(ledger.LedgerError):
            ledger.main(
                ["mark-applied", "https://unknown.example.com/job/1"],
                state_dir=self.state_dir,
            )

    def test_show_prints_latest_event(self):
        """show prints the posting's latest event as JSON."""
        ledger.main(["show", "board:77"], state_dir=self.state_dir)


if __name__ == "__main__":
    unittest.main()
