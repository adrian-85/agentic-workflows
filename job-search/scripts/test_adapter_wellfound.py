"""Wellfound adapter tests: Apollo cache jobs from the location landing.

Fixtures are synthetic but shaped like the live contract: the logged-out
location page SSRs an Apollo cache (JobListingSearchResult + StartupResult
linked via highlightedJobListings refs), sorted by liveStartAt descending.
liveStartAt (epoch seconds) gates the strict 24h window; remote is the
posting's own boolean.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import adapters
from fetch import HttpResponse, Site
from test_helpers import assert_jd_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(name="Wellfound",
            url="https://wellfound.com/location/united-states",
            adapter="wellfound")


def _stub(requests):
    page = (FIXTURES / "wellfound_location_sample.html").read_text(
        encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del headers, data
        requests.append(url)
        return HttpResponse(200, page)
    return http_get


class WellfoundAdapterTest(unittest.TestCase):
    """wellfound: Apollo cache jobs, liveStartAt gate, remote bool."""

    def setUp(self):
        self.requests = []
        self.http_get = _stub(self.requests)
        self.adapter = adapters.get_adapter("wellfound")

    def _list(self):
        return self.adapter.list_postings(SITE, self.http_get, now=NOW)

    def test_wellfound_paginates_with_page_param(self):
        """Successive pages are requested via ?page=N."""
        self.adapter.list_postings(SITE, self.http_get, now=NOW)
        pages = [urlsplit(u).query for u in self.requests]
        self.assertTrue(all("page" in parse_qs(q) for q in pages))

    def test_wellfound_gates_live_start_24h(self):
        """Fresh remote kept; stale and onsite drop."""
        titles = [p.title for p in self._list()]
        self.assertIn("Staff Engineer in Test", titles)
        self.assertNotIn("Old Remote Posting", titles)
        self.assertNotIn("Onsite Support Engineer", titles)

    def test_wellfound_parses_hit_fields(self):
        """Identity, title, company via highlights, pay, JD, date."""
        by_title = {p.title: p for p in self._list()}
        first = by_title["Staff Engineer in Test"]
        self.assertEqual(first.posting_id, "wellfound:4811715")
        self.assertEqual(first.company, "Example Corp")
        self.assertEqual(first.location, "San Francisco")
        self.assertEqual(first.pay_raw, "$120k - $150k")
        self.assertEqual(first.date_confidence, "timestamp")
        self.assertIsNotNone(first.posted_at)
        self.assertEqual(
            first.url,
            "https://wellfound.com/jobs/4811715-staff-engineer-in-test")
        self.assertIn("Key Responsibilities", first.jd_text)
        self.assertIn("quality gates", first.jd_text)

    def test_wellfound_fetch_jd_serves_cached_text(self):
        """JD text rides inline from the Apollo cache during listing."""
        for posting in self._list():
            assert_jd_text(self, self.adapter, SITE, posting, self.http_get)

    def test_wellfound_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts wellfound from the URL guard."""
        self.assertTrue(getattr(
            adapters.get_adapter("wellfound"), "REMOTE_SELF_FILTERED",
            False))


if __name__ == "__main__":
    unittest.main()
