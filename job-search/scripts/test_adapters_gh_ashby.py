"""Greenhouse + Ashby adapter tests against synthetic fixtures.

Fixture samples are hand-authored to each platform's public JSON shape
(no captured live pages, no real companies — spec: testing rule).
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
from fetch import HttpResponse, Site

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GREENHOUSE_SITE = Site(name="Example Corp Greenhouse",
                       url="https://boards.greenhouse.io/examplecorp",
                       adapter="greenhouse")
ASHBY_SITE = Site(name="Example Corp Ashby",
                  url="https://jobs.ashbyhq.com/examplecorp",
                  adapter="ashby")


def _serve(file_name: str, requests: list):
    """http_get stub serving a fixture; records requested URLs."""
    body = (FIXTURES / file_name).read_text(encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del headers, data
        requests.append(url)
        return HttpResponse(200, body)
    return http_get


class GreenhouseAdapterTest(unittest.TestCase):
    """greenhouse adapter parses the v1 boards API shape."""

    def setUp(self):
        self.requests = []
        self.http_get = _serve("greenhouse_sample.json", self.requests)
        self.adapter = adapters.get_adapter("greenhouse")

    def test_greenhouse_parses_fixture_postings(self):
        """List response becomes normalized postings with timestamps."""
        postings = self.adapter.list_postings(GREENHOUSE_SITE, self.http_get)
        self.assertEqual(len(postings), 2)
        first = postings[0]
        self.assertEqual(first.posting_id, "greenhouse:1001")
        self.assertEqual(first.company, "Example Corp")
        self.assertEqual(first.title, "Staff Software Engineer in Test")
        self.assertEqual(first.location, "Remote - US")
        self.assertEqual(first.date_confidence, "timestamp")
        self.assertIsInstance(first.posted_at, datetime)
        self.assertEqual(first.url,
                         "https://boards.greenhouse.io/examplecorp/jobs/1001")
        self.assertIsNone(first.pay_raw)
        # content=true on the list request carries the JD inline
        self.assertIn("engineer in test", first.jd_text)
        self.assertIn("examplecorp", self.requests[0])
        self.assertIn("/v1/boards/", self.requests[0])

    def test_greenhouse_fetch_jd_returns_description_text(self):
        """A posting lacking jd_text gets a detail fetch, tags stripped."""
        postings = self.adapter.list_postings(GREENHOUSE_SITE, self.http_get)
        bare = postings[0]
        bare.jd_text = None
        detail = json.dumps({"content": "&lt;p&gt;Detail JD text&lt;/p&gt;"})
        def detail_get(url, headers=None, data=None):
            del url, headers, data
            return HttpResponse(200, detail)
        text = self.adapter.fetch_jd(GREENHOUSE_SITE, bare, detail_get)
        self.assertIn("Detail JD text", text)
        self.assertNotIn("<p>", text)


class AshbyAdapterTest(unittest.TestCase):
    """ashby adapter parses the posting API shape."""

    def setUp(self):
        self.requests = []
        self.http_get = _serve("ashby_sample.json", self.requests)
        self.adapter = adapters.get_adapter("ashby")

    def test_ashby_parses_fixture_postings(self):
        """List response becomes postings with pay and JD text inline."""
        postings = self.adapter.list_postings(ASHBY_SITE, self.http_get)
        self.assertEqual(len(postings), 3)
        first = postings[0]
        self.assertTrue(first.posting_id.startswith("ashby:"))
        self.assertEqual(first.company, "Examplecorp")
        self.assertEqual(first.date_confidence, "timestamp")
        self.assertIsInstance(first.posted_at, datetime)
        self.assertEqual(
            first.posted_at.tzinfo, timezone.utc)
        self.assertIn("senior SDET", first.jd_text)
        self.assertIn("examplecorp", self.requests[0])
        self.assertIn("includeCompensation=true", self.requests[0])

    def test_ashby_salary_pay_raw(self):
        """Yearly compensation components become range pay_raw strings."""
        postings = self.adapter.list_postings(ASHBY_SITE, self.http_get)
        by_title = {p.title: p for p in postings}
        self.assertEqual(by_title[
            "Senior Software Development Engineer in Test"].pay_raw,
            "$140,000 - $180,000/yr")

    def test_ashby_hourly_pay_raw(self):
        """Hourly compensation components become /hr pay_raw strings."""
        postings = self.adapter.list_postings(ASHBY_SITE, self.http_get)
        by_title = {p.title: p for p in postings}
        self.assertEqual(by_title["Test Automation Contractor"].pay_raw,
                         "$70 - $90/hr")

    def test_ashby_fetch_jd_returns_description_text(self):
        """A posting lacking jd_text re-fetches the board payload."""
        postings = self.adapter.list_postings(ASHBY_SITE, self.http_get)
        bare = postings[0]
        bare.jd_text = None
        text = self.adapter.fetch_jd(ASHBY_SITE, bare, self.http_get)
        self.assertIn("senior SDET", text)


class AdapterContractTest(unittest.TestCase):
    """Both adapters declare remote filter params for the URL guard."""

    def test_both_adapters_declare_remote_filter_params(self):
        """REMOTE_FILTER_PARAMS is a non-empty tuple on each adapter."""
        for name in ("greenhouse", "ashby"):
            params = adapters.get_adapter(name).REMOTE_FILTER_PARAMS
            self.assertIsInstance(params, tuple)
            self.assertGreater(len(params), 0, msg=name)


class HtmlToTextTest(unittest.TestCase):
    """adapters.html_to_text unescapes entities and strips tags."""

    def test_html_to_text_unescapes_and_strips(self):
        """Escaped HTML becomes plain text; script content is dropped."""
        raw = "&lt;p&gt;Line one&lt;/p&gt;&lt;script&gt;evil()&lt;/script&gt;" \
              "&lt;li&gt;Bullet&lt;/li&gt;"
        text = adapters.html_to_text(raw)
        self.assertIn("Line one", text)
        self.assertIn("Bullet", text)
        self.assertNotIn("evil", text)
        self.assertNotIn("<", text)


if __name__ == "__main__":
    unittest.main()
