"""Shopify adapter tests: sitemap gating, turbo-stream detail parsing.

Fixtures are synthetic but shaped like the live contracts (careers
sitemap with lastmod; detail pages whose JD rides a doubly-escaped
streamController.enqueue turbo-stream chunk). No real posting data
(spec: testing rule).
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
from fetch import HttpResponse, Site

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(name="Example Corp Shopify",
            url="https://careers.example.com/careers/disciplines/testing",
            adapter="shopify")


def _serve_detail_map(requests: list):
    """http_get stub: sitemap for the sitemap URL, detail page per job."""
    sitemap = (FIXTURES / "shopify_sitemap_sample.xml").read_text(
        encoding="utf-8")
    details = {
        "staff-engineer-in-test": "shopify_detail_remote.html",
        "office-coordinator": "shopify_detail_hybrid.html",
        "automation-test-architect": "shopify_detail_architect.html",
    }
    def http_get(url, headers=None, data=None):
        del headers, data
        requests.append(url)
        if url.endswith("sitemap.xml"):
            return _resp(200, sitemap)
        for slug, file_name in details.items():
            if slug in url:
                body = (FIXTURES / file_name).read_text(encoding="utf-8")
                return _resp(200, body)
        return _resp(404, "")
    return http_get


def _resp(status, body):
    return HttpResponse(status, body)


class ShopifyAdapterTest(unittest.TestCase):
    """shopify: sitemap 24h gate, remote self-filter, turbo-stream JD."""

    def setUp(self):
        self.requests = []
        self.http_get = _serve_detail_map(self.requests)
        self.adapter = adapters.get_adapter("shopify")

    def _list(self):
        return self.adapter.list_postings(SITE, self.http_get, now=NOW)

    def test_shopify_sitemap_gates_lastmod_24h(self):
        """Stale lastmod never fetches a detail; fresh and missing do."""
        postings = self._list()
        titles = [p.title for p in postings]
        self.assertNotIn("Old Posting", titles)
        self.assertNotIn(
            "old-posting", " ".join(self.requests))
        self.assertTrue(any(r.endswith("sitemap.xml") for r in self.requests))
        self.assertTrue(any("staff-engineer-in-test" in r
                            for r in self.requests))

    def test_shopify_parses_fixture_postings(self):
        """Fresh remote detail parses: id, title, JD with real newlines."""
        postings = self._list()
        by_title = {p.title: p for p in postings}
        first = by_title["Staff Engineer in Test"]
        self.assertEqual(first.posting_id,
                         "shopify:aaaaaaaa-1111-4222-8333-444444444444")
        self.assertEqual(first.company, "Example Corp Shopify")
        self.assertEqual(first.date_confidence, "timestamp")
        self.assertIsNotNone(first.posted_at)
        self.assertIn("Key Responsibilities", first.jd_text)
        self.assertIn("\n", first.jd_text)
        self.assertNotIn("<", first.jd_text)
        self.assertNotIn("\\n", first.jd_text)
        self.assertTrue(first.url.endswith(
            "/staff-engineer-in-test_aaaaaaaa-1111-4222-8333-444444444444"))

    def test_shopify_drops_non_remote_details(self):
        """isRemote=false details never surface."""
        postings = self._list()
        self.assertNotIn("Office Coordinator", [p.title for p in postings])

    def test_shopify_missing_lastmod_flags_none(self):
        """No lastmod -> kept for review (date_confidence none)."""
        postings = self._list()
        by_title = {p.title: p for p in postings}
        self.assertEqual(
            by_title["Automation Test Architect"].date_confidence, "none")
        self.assertIsNone(by_title["Automation Test Architect"].posted_at)

    def test_shopify_fetch_jd_serves_cached_text(self):
        """JD rides inline from the detail fetch during listing."""
        postings = self._list()
        for posting in postings:
            text = self.adapter.fetch_jd(SITE, posting, self.http_get)
            self.assertIn("Example Corp", text)

    def test_shopify_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts shopify from the URL guard."""
        self.assertTrue(getattr(
            adapters.get_adapter("shopify"), "REMOTE_SELF_FILTERED",
            False))


if __name__ == "__main__":
    unittest.main()
