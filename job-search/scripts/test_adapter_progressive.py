"""Progressive (Talemetry) adapter tests: SSR cards + JSON-LD detail.

Fixtures are synthetic but shaped like the live contract: the search
page server-renders job anchors each followed by a machine-readable
<time datetime> (the 24h gate), behind curl-feed auth (Cloudflare);
detail pages carry the JobPosting JSON-LD description. Live-grounded
2026-10-07. Employment type is never a gate.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
from fetch import HttpResponse, Site
from test_helpers import assert_jd_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(name="Progressive",
            url="https://careers.progressive.com/search/remote_work/remote/jobs",
            adapter="progressive", auth="curl-feed")


def _stub(requests):
    search = (FIXTURES / "progressive_search_sample.html").read_text(
        encoding="utf-8")
    detail = (FIXTURES / "progressive_detail_sample.html").read_text(
        encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del headers, data
        requests.append(url)
        if "/jobs/" in url and "search" not in url:
            return HttpResponse(200, detail)
        return HttpResponse(200, search)
    return http_get


class ProgressiveAdapterTest(unittest.TestCase):
    """progressive: card dates gate the window; JSON-LD carries the JD."""

    def setUp(self):
        self.requests = []
        self.http_get = _stub(self.requests)
        self.adapter = adapters.get_adapter("progressive")

    def _list(self):
        return self.adapter.list_postings(SITE, self.http_get, now=NOW)

    def test_progressive_sorts_by_date_and_gates_window(self):
        """Requests sort by date posted; in-window cards parse."""
        self._list()
        search_urls = [u for u in self.requests if "/search/" in u]
        self.assertEqual(len(search_urls), 1)
        self.assertIn("sortby=cfm16", search_urls[0])
        titles = [p.title for p in self._list()]
        self.assertIn("Reinsurance Accountant - Senior or Lead", titles)
        self.assertIn("Data Scientist Senior", titles)
        self.assertNotIn("Old Posting", titles)

    def test_progressive_parses_card_fields(self):
        """Identity, title, location, date confidence, detail URL."""
        by_title = {p.title: p for p in self._list()}
        first = by_title["Reinsurance Accountant - Senior or Lead"]
        self.assertEqual(first.posting_id, "progressive:18303704")
        self.assertEqual(first.company, "Progressive")
        self.assertEqual(first.location, "Mayfield Village, OH")
        self.assertEqual(first.date_confidence, "url-filter")
        self.assertEqual(
            first.url,
            "https://careers.progressive.com/jobs/"
            "18303704-reinsurance-accountant-senior-or-lead/")

    def test_progressive_fetch_jd_from_jsonld(self):
        """JD text from the detail page's JobPosting description; the
        unparsable sibling script block is skipped."""
        postings = self._list()
        assert_jd_text(self, self.adapter, SITE, postings[0], self.http_get)

    def test_progressive_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts progressive from the URL guard."""
        self.assertTrue(getattr(
            adapters.get_adapter("progressive"), "REMOTE_SELF_FILTERED",
            False))


if __name__ == "__main__":
    unittest.main()
