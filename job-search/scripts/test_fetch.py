"""Fetch framework tests: sites loader, guards, gating, isolation, delays.

All postings are synthetic (Example Corp) served by a mock adapter — no
network, no real site data (spec: testing rule).
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import adapters
import config
import fetch
import ledger
from postings import Posting

NOW = datetime.now(timezone.utc)


def _cfg(**overrides) -> config.Config:
    values = {
        "preferred_min": 150000,
        "acceptable_min": 90000,
        "relevance_profile_path": "/tmp/example.docx",
        "relevance_domains": "example domains",
        "ethics_rule": "example rule",
        "request_delay_seconds": 0.01,
    }
    values.update(overrides)
    return config.Config(**values)


def _posting(**overrides) -> Posting:
    base = {
        "posting_id": "mock:1",
        "source": "mock",
        "url": "https://jobs.example.com/1",
        "jd_url": "https://jobs.example.com/1",
        "company": "Example Corp",
        "title": "Staff Engineer in Test",
        "location": "US Remote",
        "posted_at": NOW - timedelta(hours=1),
        "date_confidence": "timestamp",
        "pay_raw": "$100k - $150k",
        "fetched_at": NOW,
    }
    base.update(overrides)
    return Posting(**base)


class MockAdapter:
    """Minimal in-file adapter satisfying the adapter contract."""

    REMOTE_FILTER_PARAMS = ("remote=",)

    def __init__(self, postings=None, jd_text="synthetic jd", error=None):
        self._postings = postings or []
        self._jd_text = jd_text
        self._error = error

    def list_postings(self, _site, _http_get):
        """Serve the fixture postings (or raise the configured error)."""
        if self._error:
            raise self._error
        return list(self._postings)

    def fetch_jd(self, _site, _posting, _http_get):
        """Serve the fixture JD text (or raise the configured error)."""
        if self._error:
            raise self._error
        return self._jd_text


def _site(**overrides) -> fetch.Site:
    """Synthetic site entry with test defaults."""
    base = {
        "name": "Mock Board",
        "url": "https://jobs.example.com/search?remote=us",
        "adapter": "mock",
        "auth": "none",
        "notes": "",
    }
    base.update(overrides)
    return fetch.Site(**base)


class FetchAllTest(unittest.TestCase):
    """fetch_all: applied-exclusion, date gate, remote guard, isolation."""

    def setUp(self):
        self.state_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.state_dir, ignore_errors=True)
        self.sleeps = []

    def _fetch(self, sites, adapter, cfg=None):
        adapters.register("mock", adapter)
        return fetch.fetch_all(
            sites, cfg or _cfg(), self.state_dir,
            http_get=lambda url, **kw: fetch.HttpResponse(200, ""),
            sleep=self.sleeps.append,
        )

    def test_fetch_all_applies_applied_exclusion(self):
        """Postings in the applied ledger never reach candidates."""
        ledger.append_event(self.state_dir, {
            "posting_id": "mock:1", "event": "marked-applied",
        })
        report = self._fetch([_site()], MockAdapter(
            postings=[_posting(), _posting(posting_id="mock:2",
                                            url="https://jobs.example.com/2")]))
        self.assertEqual({p.posting_id for p in report.candidates},
                         {"mock:2"})

    def test_out_of_window_timestamp_dropped(self):
        """Strict literal 24h: a 25h-old timestamp posting is dropped."""
        report = self._fetch([_site()], MockAdapter(
            postings=[_posting(posted_at=NOW - timedelta(hours=25))]))
        self.assertEqual(report.candidates, [])

    def test_url_filter_confidence_passes_without_timestamp(self):
        """url-filter postings pass the date gate on the URL's word."""
        report = self._fetch([_site()], MockAdapter(
            postings=[_posting(posted_at=None, date_confidence="url-filter")]))
        self.assertEqual(len(report.candidates), 1)

    def test_none_date_confidence_flags_review(self):
        """No date signal at all -> kept but flagged for review."""
        report = self._fetch([_site()], MockAdapter(
            postings=[_posting(posted_at=None, date_confidence="none")]))
        self.assertEqual(len(report.candidates), 1)
        self.assertIn("date-unverified", report.candidates[0].review_flags)

    def test_site_without_remote_filter_flags_review(self):
        """A site URL lacking remote filter params flags all its postings."""
        report = self._fetch(
            [_site(url="https://jobs.example.com/search?q=test")],
            MockAdapter(postings=[_posting()]))
        self.assertEqual(len(report.candidates), 1)
        self.assertIn("site-url-lacks-remote-us-filter",
                      report.candidates[0].review_flags)

    def test_site_error_isolates(self):
        """One failing site never aborts the run or its neighbors."""
        adapters.register("mock", MockAdapter(postings=[_posting()]))
        adapters.register("broken", MockAdapter(error=RuntimeError("boom")))
        report = fetch.fetch_all(
            [_site(name="Broken", adapter="broken", url="https://b.example/?remote=1"),
             _site(name="Ok")],
            _cfg(), self.state_dir,
            http_get=lambda url, **kw: fetch.HttpResponse(200, ""),
            sleep=self.sleeps.append)
        self.assertEqual([r.ok for r in report.site_results],
                         [False, True])
        self.assertIn("boom", report.site_results[0].error)
        self.assertEqual(len(report.candidates), 1)

    def test_jd_fetched_for_survivors_only(self):
        """Only gated survivors get a JD fetch (the excluded never do)."""
        adapter = MockAdapter(postings=[
            _posting(),
            _posting(posting_id="mock:old",
                     url="https://jobs.example.com/old",
                     posted_at=NOW - timedelta(hours=25)),
        ])
        report = self._fetch([_site()], adapter)
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(report.candidates[0].jd_text, "synthetic jd")

    def test_jd_fetch_failure_flags_review(self):
        """A JD fetch failure keeps the posting but flags it for review."""
        class JdFails(MockAdapter):
            """Mock whose JD fetch always fails."""

            def fetch_jd(self, _site, _posting, _http_get):
                raise RuntimeError("jd fetch boom")

        report = self._fetch([_site()], JdFails(postings=[_posting()]))
        self.assertEqual(len(report.candidates), 1)
        self.assertIn("jd-fetch-failed", report.candidates[0].review_flags)
        self.assertIsNone(report.candidates[0].jd_text)

    def test_delay_between_requests(self):
        """Same-site requests observe the configured delay."""
        report = self._fetch([_site()], MockAdapter(postings=[
            _posting(),
            _posting(posting_id="mock:2", url="https://jobs.example.com/2"),
        ]), cfg=_cfg(request_delay_seconds=0.05))
        self.assertEqual(len(report.candidates), 2)
        self.assertGreaterEqual(len(self.sleeps), 1)
        self.assertTrue(all(amount > 0 for amount in self.sleeps))


class LoadSitesTest(unittest.TestCase):
    """load_sites parses the committed example file's fictional entries."""

    def test_load_sites_parses_example(self):
        """The committed example parses into Site objects with adapters."""
        example = Path(__file__).resolve().parent.parent / "sites.example.toml"
        sites = fetch.load_sites(str(example))
        self.assertEqual(len(sites), 2)
        self.assertEqual({s.adapter for s in sites},
                         {"greenhouse", "indeed-curlfeed"})
        self.assertTrue(all(s.url.startswith("http") for s in sites))


if __name__ == "__main__":
    unittest.main()
