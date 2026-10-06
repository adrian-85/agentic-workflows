"""run.py stage-runner tests: search pipeline and approve resolution."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# protected-access: tests white-box the _save/_resolve/_load candidates
# helpers they exercise — that IS the contract here (repo convention).
# pylint: disable=protected-access
import fetch as fetch_mod
import judge as judge_mod
import ledger
import run
from postings import Posting
from test_helpers import make_posting

CANDIDATE = make_posting(jd_text="synthetic jd text")


def _fetch_result(postings):
    """FetchReport stand-in with the given candidates."""
    return fetch_mod.FetchReport(
        site_results=[fetch_mod.SiteResult(
            fetch_mod.Site(name="Mock Board",
                           url="https://jobs.example.com/?remote=1",
                           adapter="mock"), True, postings)],
        candidates=postings)


def _judgment(posting_id, decision="acceptable"):
    """Judgment stand-in matching the dataclass."""
    return judge_mod.Judgment(
        posting_id=posting_id, decision=decision, reason="none",
        pay_seen=True, pay_top=120000, pay_annualized=120000,
        pay_basis="range_top", rationale_short="synthetic")


class SearchTest(unittest.TestCase):
    """cmd_search: fetch -> judge -> record -> report -> candidates file."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.state_dir = self.dir / "state"
        self.config = self.dir / "config.toml"
        self.config.write_text(
            "[pay]\npreferred_min = 150000\nacceptable_min = 90000\n"
            "[profile]\nrelevance_profile_path = \"/tmp/example.docx\"\n"
            "[criteria]\nrelevance_domains = \"example\"\n"
            "ethics_rule = \"example\"\n", encoding="utf-8")
        self.sites = self.dir / "sites.toml"
        self.sites.write_text("[[site]]\nname = \"Mock Board\"\n"
                              "url = \"https://jobs.example.com/?remote=1\"\n"
                              "adapter = \"mock\"\n", encoding="utf-8")
        self.judge_calls = []

    def _search(self, postings, resume="RESUME TEXT"):
        def fake_fetch(sites, cfg, state_dir, **kwargs):
            del sites, cfg, state_dir, kwargs
            return _fetch_result(postings)
        def fake_judge(cfg, candidates, resume_text, runner=None):
            del cfg, runner
            self.judge_calls.append(resume_text)
            return [_judgment(p.posting_id) for p in candidates]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            run.cmd_search(str(self.config), str(self.sites),
                           self.state_dir,
                           _fetch=fake_fetch, _judge=fake_judge,
                           _resume=lambda _path: resume)
        return stdout.getvalue()

    def test_search_prints_report_and_saves_candidates(self):
        """Console report prints; candidates persist for the approve step."""
        out = self._search([CANDIDATE])
        self.assertIn("ACCEPTABLE", out)
        self.assertIn("Mock Board", out)
        self.assertIn(CANDIDATE.posting_id, out)
        self.assertIn("RESUME TEXT", self.judge_calls[0])
        state = ledger.current_state(self.state_dir)
        self.assertEqual(state[CANDIDATE.posting_id]["event"], "judged")
        candidates_file = self.state_dir / "candidates.json"
        self.assertTrue(candidates_file.exists())
        saved = json.loads(candidates_file.read_text(encoding="utf-8"))
        self.assertIn(CANDIDATE.posting_id, saved["candidates"])
        decisions = self.state_dir / "decisions.md"
        self.assertTrue(decisions.exists())

    def test_search_zero_candidates_skips_judgment(self):
        """No candidates -> no judgment session, empty report still written."""
        out = self._search([])
        self.assertIn("no candidates", out)
        self.assertEqual(self.judge_calls, [])
        self.assertTrue((self.state_dir / "decisions.md").exists())


class ApproveTest(unittest.TestCase):
    """Reference resolution and dispatch wiring for cmd_approve."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.state_dir = self.dir / "state"
        self.state_dir.mkdir()
        run._save_candidates(self.state_dir, "run42", {
            "mock:1": (make_posting(posting_id="mock:1"), "jd 1"),
            "mock:2": (make_posting(posting_id="mock:2",
                                    url="https://jobs.example.com/2"),
                       "jd 2"),
            "mock:3": (make_posting(posting_id="mock:3",
                                    url="https://jobs.example.com/3"),
                       "jd 3"),
        })

    def _config(self):
        path = self.dir / "config.toml"
        path.write_text(
            "[pay]\npreferred_min = 150000\nacceptable_min = 90000\n"
            "[profile]\nrelevance_profile_path = \"/tmp/example.docx\"\n"
            "[criteria]\nrelevance_domains = \"example\"\n"
            "ethics_rule = \"example\"\n", encoding="utf-8")
        return str(path)

    def test_resolve_refs_all_with_except(self):
        """"all" minus --except ids, preserving candidates-file order."""
        resolved = run._resolve_refs(
            self.state_dir, ["all"], except_refs=["mock:2"])
        self.assertEqual(resolved, ["mock:1", "mock:3"])

    def test_resolve_refs_explicit_ids(self):
        """Explicit ids pass through in given order."""
        resolved = run._resolve_refs(self.state_dir, ["mock:3", "mock:1"],
                                     except_refs=[])
        self.assertEqual(resolved, ["mock:3", "mock:1"])

    def test_resolve_refs_unknown_id_raises(self):
        """An unknown id fails loudly instead of silently skipping."""
        with self.assertRaises(run.RunError):
            run._resolve_refs(self.state_dir, ["mock:9"], except_refs=[])

    def test_approve_dispatches_approved_only(self):
        """cmd_approve sends only resolved refs to the dispatch queue."""
        dispatched = []
        def fake_queue(approved, cfg, state_dir, target_dir=None, spawn=None):
            del cfg, state_dir, target_dir, spawn
            dispatched.extend(posting.posting_id for posting, _ in approved)
            return [{"posting_id": pid, "status": "tailoring-succeeded",
                     "returncode": 0} for pid in dispatched]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            run.cmd_approve(self._config(), self.state_dir, ["mock:1"],
                            except_refs=[], _queue=fake_queue)
        self.assertEqual(dispatched, ["mock:1"])
        self.assertIn("tailoring-succeeded", stdout.getvalue())

    def test_candidates_roundtrip_preserves_posting(self):
        """Saved candidates rebuild into Posting objects with jd_text."""
        candidates = run._load_candidates(self.state_dir)
        posting, jd_text = candidates["mock:1"]
        self.assertIsInstance(posting, Posting)
        self.assertEqual(jd_text, "jd 1")
        self.assertEqual(posting.company, "Example Corp")
        self.assertIsInstance(posting.fetched_at, datetime)
        self.assertEqual(posting.fetched_at.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
