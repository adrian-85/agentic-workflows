"""ServiceNow adapter tests: sitemap lastmod gate + JSON-LD detail.

Fixtures are synthetic but shaped like the live contract (sitemap with
lastmod; detail pages whose JobPosting JSON-LD rides in a script tag
whose type HTML-encodes the plus sign). No real posting data.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
from fetch import HttpResponse, Site

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(name="Example Corp ServiceNow",
            url="https://careers.example.com/jobs/", adapter="servicenow")

DETAILS = {
    "744000154174169": "servicenow_detail_remote.html",
    "744000154174170": "servicenow_detail_office.html",
    "744000154174171": "servicenow_detail_nonus.html",
}


def _stub(requests):
    sitemap = (FIXTURES / "servicenow_sitemap_sample.xml").read_text(
        encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del headers, data
        requests.append(url)
        if url.endswith("/sitemap.xml"):
            return HttpResponse(200, sitemap)
        for job_id, file_name in DETAILS.items():
            if job_id in url:
                body = (FIXTURES / file_name).read_text(encoding="utf-8")
                return HttpResponse(200, body)
        return HttpResponse(404, "")
    return http_get


class ServiceNowAdapterTest(unittest.TestCase):
    """servicenow: lastmod gate, JSON-LD gates, remote+US self-filter."""

    def setUp(self):
        self.requests = []
        self.http_get = _stub(self.requests)
        self.adapter = adapters.get_adapter("servicenow")

    def _list(self):
        return self.adapter.list_postings(SITE, self.http_get, now=NOW)

    def test_servicenow_sitemap_gates_lastmod_24h(self):
        """Stale lastmod entries are never detail-fetched."""
        postings = self._list()
        self.assertNotIn("Old Posting", [p.title for p in postings])
        self.assertNotIn("old-posting", " ".join(self.requests))
        self.assertTrue(any(r.endswith("/sitemap.xml") for r in self.requests))

    def test_servicenow_parses_remote_us_posting(self):
        """Fresh TELECOMMUTE US posting: id, title, JD, location, date."""
        postings = self._list()
        by_title = {p.title: p for p in postings}
        first = by_title["Senior Manager, Platform Engineering"]
        self.assertEqual(first.posting_id, "servicenow:744000154174169")
        self.assertEqual(first.company, "Example Corp ServiceNow")
        self.assertEqual(first.location, "Santa Clara")
        self.assertEqual(first.date_confidence, "url-filter")
        self.assertIn("Key Responsibilities", first.jd_text)
        self.assertNotIn("<", first.jd_text)
        self.assertTrue(first.url.endswith(
            "/jobs/744000154174169/senior-manager-platform-engineering/"))

    def test_servicenow_drops_office_postings(self):
        """No TELECOMMUTE marker -> not remote, dropped."""
        self.assertNotIn("Office Coordinator",
                         [p.title for p in self._list()])

    def test_servicenow_drops_non_us_postings(self):
        """applicantLocationRequirements outside the US -> dropped."""
        self.assertNotIn("Engineer, India", [p.title for p in self._list()])

    def test_servicenow_fetch_jd_serves_cached_text(self):
        """JD text rides inline from the detail fetch during listing."""
        for posting in self._list():
            self.assertIn("Example Corp",
                          self.adapter.fetch_jd(SITE, posting, self.http_get))

    def test_servicenow_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts servicenow from the URL guard."""
        self.assertTrue(getattr(
            adapters.get_adapter("servicenow"), "REMOTE_SELF_FILTERED",
            False))


if __name__ == "__main__":
    unittest.main()
