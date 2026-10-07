"""Phenom adapter tests: /widgets refineSearch contract + JSON-LD JD.

Fixtures are synthetic but shaped like the live contract (phApp config on
the search page; refineSearch payload; detail page JobPosting JSON-LD).
The adapter deliberately applies NO schedule/employment-type filter.
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
from fetch import HttpResponse, Site
from test_helpers import assert_jd_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(name="Example Corp",
            url="https://careers.example.com/us/en/search-results",
            adapter="phenom")
FILTERED_SITE = Site(
    name="Example Corp",
    url=("https://careers.example.com/us/en/search-results"
         "?remote=Remote&country=United%20States"),
    adapter="phenom")


def _stub(requests):
    search = (FIXTURES / "phenom_search_sample.html").read_text(encoding="utf-8")
    widgets = (FIXTURES / "phenom_widgets_sample.json").read_text(encoding="utf-8")
    detail = (FIXTURES / "phenom_detail_sample.html").read_text(encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del headers
        requests.append((url, data))
        if url.endswith("/widgets"):
            return HttpResponse(200, widgets)
        if "/job/" in url:
            return HttpResponse(200, detail)
        return HttpResponse(200, search)
    return http_get


class PhenomAdapterTest(unittest.TestCase):
    """phenom: phApp config, window gate, no schedule filter, JSON-LD JD."""

    def setUp(self):
        self.requests = []
        self.http_get = _stub(self.requests)
        self.adapter = adapters.get_adapter("phenom")

    def _list(self, site=None):
        return self.adapter.list_postings(site or SITE, self.http_get, now=NOW)

    def test_phenom_posts_to_phapp_widget_endpoint(self):
        """The widget endpoint comes from the page's phApp config."""
        self._list()
        urls = [u for u, _ in self.requests]
        self.assertIn("https://careers.example.com/widgets", urls)
        body = json.loads([d for u, d in self.requests
                           if u.endswith("/widgets")][0])
        self.assertEqual(body["ddoKey"], "refineSearch")
        self.assertEqual(body["pageId"], "page10")
        self.assertEqual(body["siteType"], "external")
        self.assertEqual(body["sort"], {"order": "desc", "field": "postedDate"})

    def test_phenom_lists_within_window_only(self):
        """Fresh postings kept; an older postedDate is dropped."""
        titles = [p.title for p in self._list()]
        self.assertIn("Staff Engineer in Test", titles)
        self.assertNotIn("Old Posting", titles)

    def test_phenom_keeps_part_time_no_schedule_filter(self):
        """Employment type is never a gate (spec: no schedule checks)."""
        titles = [p.title for p in self._list()]
        self.assertIn("Automation Test Architect", titles)

    def test_phenom_posting_fields(self):
        """Identity, company, location, date confidence, detail URL."""
        by_title = {p.title: p for p in self._list()}
        first = by_title["Staff Engineer in Test"]
        self.assertEqual(first.posting_id, "phenom:R0000001")
        self.assertEqual(first.company, "Example Corp")
        self.assertEqual(first.date_confidence, "url-filter")
        self.assertIn("Texas", first.location)
        self.assertEqual(
            first.url,
            "https://careers.example.com/us/en/job/R0000001"
            "/Staff-Engineer-in-Test")

    def test_phenom_url_query_params_become_selected_fields(self):
        """Site URL filters are forwarded as the widget's selected_fields."""
        self._list(FILTERED_SITE)
        body = json.loads([d for u, d in self.requests
                           if u.endswith("/widgets")][0])
        self.assertEqual(body["selected_fields"],
                         {"remote": ["Remote"], "country": ["United States"]})

    def test_phenom_fetch_jd_from_embedded_ddo(self):
        """JD text comes from the detail page's embedded jobDetail DDO."""
        postings = self._list()
        assert_jd_text(self, self.adapter, SITE, postings[0], self.http_get)

    def test_phenom_fetch_jd_jsonld_fallback(self):
        """When no embedded DDO exists, the JobPosting ld+json is used."""
        postings = self._list()
        fallback = (FIXTURES / "phenom_detail_jsonld_sample.html").read_text(
            encoding="utf-8")
        def http_get(*_args, **_kwargs):
            return HttpResponse(200, fallback)
        text = self.adapter.fetch_jd(SITE, postings[0], http_get)
        self.assertIn("Key Responsibilities", text)
        self.assertNotIn("<", text)

    def test_phenom_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts phenom from the URL guard."""
        self.assertTrue(getattr(self.adapter, "REMOTE_SELF_FILTERED", False))


if __name__ == "__main__":
    unittest.main()
