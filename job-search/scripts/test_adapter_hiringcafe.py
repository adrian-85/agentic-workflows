"""HiringCafe adapter tests: classic view __NEXT_DATA__ island.

Fixtures are synthetic but shaped like the live contract: the classic
page passes Cloudflare with browser sec-fetch/accept headers (no
cookies), and SSRs the filtered hits into __NEXT_DATA__ pageProps.ssrHits
with precise estimated_publish_date_millis and structured yearly pay.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
from fetch import HttpResponse, Site

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(name="HiringCafe",
            url=("https://hiringcafe.com/classic?searchState=%7B%22locations"
                 "%22%3A%5B%7B%22id%22%3A%22FxY1yZQBoEtHp_8UEq7V%22%7D%5D%7D"),
            adapter="hiringcafe")


def _stub(requests):
    page = (FIXTURES / "hiringcafe_classic_sample.html").read_text(
        encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del data
        requests.append((url, headers))
        return HttpResponse(200, page)
    return http_get


class HiringCafeAdapterTest(unittest.TestCase):
    """hiringcafe: browser headers, publish-date gate, structured pay."""

    def setUp(self):
        self.requests = []
        self.http_get = _stub(self.requests)
        self.adapter = adapters.get_adapter("hiringcafe")

    def _list(self):
        return self.adapter.list_postings(SITE, self.http_get, now=NOW)

    def test_hiringcafe_sends_browser_headers(self):
        """Cloudflare's edge challenge needs browser-like headers."""
        self._list()
        headers = self.requests[0][1] or {}
        self.assertEqual(headers.get("sec-fetch-dest"), "document")
        self.assertIn("sec-fetch-mode", headers)
        self.assertIn("accept", headers)

    def test_hiringcafe_gates_publish_date_24h(self):
        """Precise publish timestamps gate the strict window."""
        titles = [p.title for p in self._list()]
        self.assertIn("Staff Engineer in Test", titles)
        self.assertIn("Platform Engineer", titles)
        self.assertNotIn("Old Posting", titles)
        self.assertNotIn("Automation Test Architect", titles)

    def test_hiringcafe_parses_hit_fields(self):
        """Identity, title, company, location, pay, JD digest, date."""
        by_title = {p.title: p for p in self._list()}
        first = by_title["Staff Engineer in Test"]
        self.assertEqual(first.posting_id,
                         "hiringcafe:hc-staff-engineer-in-test")
        self.assertEqual(first.company, "Example Corp")
        self.assertEqual(first.location, "United States")
        self.assertEqual(first.pay_raw, "$120,000 - $150,000")
        self.assertEqual(first.date_confidence, "timestamp")
        self.assertIsNotNone(first.posted_at)
        self.assertIn("requirements summary for Example Corp", first.jd_text)
        self.assertIn("Python", first.jd_text)
        self.assertTrue(first.url.startswith("https://jobs.example.com/"))

    def test_hiringcafe_missing_pay_keeps_posting(self):
        """No compensation data -> pay_raw None, posting still surfaces."""
        by_title = {p.title: p for p in self._list()}
        self.assertIsNone(by_title["Platform Engineer"].pay_raw)

    def test_hiringcafe_fetch_jd_serves_cached_text(self):
        """JD text rides inline from the SSR hit during listing."""
        for posting in self._list():
            self.assertIn("Example Corp",
                          self.adapter.fetch_jd(SITE, posting, self.http_get))

    def test_hiringcafe_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts hiringcafe from the URL guard."""
        self.assertTrue(getattr(
            adapters.get_adapter("hiringcafe"), "REMOTE_SELF_FILTERED",
            False))


if __name__ == "__main__":
    unittest.main()
