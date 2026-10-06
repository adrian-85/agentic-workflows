"""Report tests: console sections, applied exclusion, decisions.md superset."""

import tempfile
import unittest
from pathlib import Path

from report import render_console, write_decisions_md
from test_helpers import make_config

CFG = make_config()


def _event(posting_id, **overrides) -> dict:
    """A ledger-event-shaped dict; overrides replace whole values."""
    event = {
        "posting_id": posting_id,
        "url": f"https://jobs.example.com/{posting_id}",
        "company": "Example Corp",
        "title": "Staff Engineer in Test",
        "event": "judged",
        "decision": "acceptable",
        "reason": "none",
        "rationale_short": "synthetic rationale",
        "criteria_version": "abc123def456",
    }
    event.update(overrides)
    return event


STATE = {
    "mock:1": _event("mock:1", decision="preferred",
                     rationale_short="preferred-tier rationale"),
    "mock:2": _event("mock:2", decision="acceptable"),
    "mock:3": _event("mock:3", decision="review",
                     rationale_short="unclear relevance"),
    "mock:4": _event("mock:4", decision="excluded", reason="not_relevant"),
    "mock:5": _event("mock:5", decision="excluded", reason="ethics"),
    "mock:6": _event("mock:6", decision="unacceptable",
                     reason="pay_below_threshold"),
    "mock:7": _event("mock:7", event="marked-applied",
                     decision="preferred"),
}

RUN_INFO = {
    "run_id": "run42",
    "criteria_version": "abc123def456",
    "site_results": [
        {"name": "Ok Board", "ok": True},
        {"name": "Dead Board", "ok": False,
         "error": "AuthExpired: auth expired for Dead Board: re-export "
                  "cURL from a logged-in session"},
    ],
    "queue": {"running": 1, "queued": 2,
              "outcomes": ["mock:9 tailoring-succeeded"]},
}


class ConsoleTest(unittest.TestCase):
    """render_console prints every spec §7 section."""

    def test_console_has_all_sections(self):
        """Header, tiers, review, excluded, failed sites, queue."""
        text = render_console(STATE, RUN_INFO, CFG)
        for marker in ("run42", "abc123def456", "PREFERRED",
                       "apply manually", "mark-applied", "ACCEPTABLE",
                       "REVIEW", "EXCLUDED", "not_relevant", "ethics",
                       "UNACCEPTABLE", "pay_below_threshold",
                       "FAILED SITES", "Dead Board",
                       "TAILORING", "queued 2"):
            self.assertIn(marker, text, msg=marker)
        self.assertIn("Example Corp", text)

    def test_applied_never_appears(self):
        """A marked-applied posting never surfaces in the report."""
        text = render_console(STATE, RUN_INFO, CFG)
        self.assertNotIn("mock:7", text)

    def test_failed_site_names_site_and_reexport_hint(self):
        """Auth-expired failures carry the cURL re-export instruction."""
        text = render_console(STATE, RUN_INFO, CFG)
        self.assertIn("Dead Board", text)
        self.assertIn("re-export", text)
        self.assertIn("curl.txt", text)


class DecisionsMdTest(unittest.TestCase):
    """decisions.md mirrors the console and adds full detail."""

    def test_decisions_md_is_superset_of_console(self):
        """Every console line appears in the md, plus rationale detail."""
        console = render_console(STATE, RUN_INFO, CFG)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "decisions.md"
            content = write_decisions_md(STATE, RUN_INFO, CFG, path)
            self.assertTrue(path.exists())
        for line in console.splitlines():
            line = line.strip()
            if line:
                self.assertIn(line, content, msg=f"missing: {line!r}")
        self.assertIn("preferred-tier rationale", content)
        self.assertIn("https://jobs.example.com/mock:1".replace(":", ""),
                      content.replace(":", ""))
        self.assertIn("criteria_version", content)


if __name__ == "__main__":
    unittest.main()
