"""Dispatch tests: JD files, FIFO bounded queue, ledger outcomes.

The spawn callable is always faked (no real pi sessions in tests); all
postings synthetic (spec: testing rule).
"""

import shutil
import tempfile
import time
import unittest
from pathlib import Path

import dispatch
import ledger
from test_helpers import make_config, make_posting


def _approved(count):
    """(posting, jd_text) tuples for the queue."""
    return [(make_posting(posting_id=f"mock:{i}",
                          url=f"https://jobs.example.com/{i}",
                          jd_url=f"https://jobs.example.com/{i}",
                          company="Example Corp"),
             f"synthetic jd {i}") for i in range(1, count + 1)]


class JdFileTest(unittest.TestCase):
    """write_jd_file honors resume-tailoring's jd_<target>.txt contract."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_jd_file_first_line_is_posting_url(self):
        """Line one is exactly 'Posting URL: <url>' (SKILL Step 1)."""
        posting = make_posting(url="https://jobs.example.com/1",
                               company="Example Corp")
        path = dispatch.write_jd_file(posting, "jd body text", self.dir)
        self.assertEqual(path.name, "jd_ExampleCorp.txt")
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0],
                         "Posting URL: https://jobs.example.com/1")
        self.assertEqual(lines[1], "jd body text")

    def test_sanitize_target_filesystem_safe(self):
        """Unsafe characters vanish; result is non-empty."""
        cleaned = dispatch.sanitize_target("Example Corp: QA/L2? *Remote*")
        self.assertNotRegex(cleaned, r"[^A-Za-z0-9_-]")
        self.assertTrue(cleaned)


class QueueTest(unittest.TestCase):
    """run_queue: bounded parallelism, FIFO, outcomes, no auto-retry."""

    def setUp(self):
        self.state_dir = Path(tempfile.mkdtemp())
        self.target_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.target_dir, ignore_errors=True)
        self.cfg = make_config(max_parallel_tailoring=3)

    def test_queue_respects_max_parallel(self):
        """Five jobs, cap three: observed concurrency peaks at exactly 3."""
        active = {"now": 0, "max": 0}
        lock = __import__("threading").Lock()
        def spawn(_posting, _jd_path):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.08)
            with lock:
                active["now"] -= 1
            return 0
        outcomes = dispatch.run_queue(_approved(5), self.cfg, self.state_dir,
                                      target_dir=self.target_dir,
                                      spawn=spawn)
        self.assertEqual(len(outcomes), 5)
        self.assertEqual(active["max"], 3)

    def test_fifo_order_started(self):
        """Jobs start in approval order."""
        started = []
        def spawn(posting, _jd_path):
            started.append(posting.posting_id)
            return 0
        dispatch.run_queue(_approved(4), self.cfg, self.state_dir,
                           target_dir=self.target_dir, spawn=spawn)
        self.assertEqual(started, [f"mock:{i}" for i in range(1, 5)])

    def test_outcomes_appended_to_ledger(self):
        """Exit 0 -> tailoring-succeeded; nonzero -> tailoring-failed."""
        def spawn(posting, _jd_path):
            return 0 if posting.posting_id == "mock:1" else 1
        dispatch.run_queue(_approved(2), self.cfg, self.state_dir,
                           target_dir=self.target_dir, spawn=spawn)
        state = ledger.current_state(self.state_dir)
        self.assertEqual(state["mock:1"]["event"], "tailoring-succeeded")
        self.assertEqual(state["mock:2"]["event"], "tailoring-failed")

    def test_queued_events_recorded(self):
        """Every job logs tailoring-queued before its outcome."""
        def spawn(_posting, _jd_path):
            return 0
        dispatch.run_queue(_approved(2), self.cfg, self.state_dir,
                           target_dir=self.target_dir, spawn=spawn)
        raw = (self.state_dir / ledger.LEDGER_FILENAME).read_text(
            encoding="utf-8").splitlines()
        events = [__import__("json").loads(line)["event"] for line in raw]
        self.assertEqual(events.count("tailoring-queued"), 2)
        self.assertEqual(events.count("tailoring-succeeded"), 2)
        self.assertEqual(events[0], "tailoring-queued")

    def test_no_autoretry(self):
        """A failing job spawns exactly once."""
        calls = []
        def spawn(posting, _jd_path):
            calls.append(posting.posting_id)
            return 1
        dispatch.run_queue(_approved(3), self.cfg, self.state_dir,
                           target_dir=self.target_dir, spawn=spawn)
        self.assertEqual(calls.count("mock:1"), 1)
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
