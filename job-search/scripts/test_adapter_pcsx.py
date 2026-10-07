"""pcsx adapter tests: /api/pcsx/search contract + JSON-LD JD.

Fixtures are synthetic but shaped like the live contract (jobs.<host>
/api/pcsx/search positions; detail page JobPosting JSON-LD). The adapter
applies NO schedule/employment-type filter.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
from fetch import HttpResponse, Site
from test_helpers import assert_jd_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(
    name="Example Corp",
    url=("https://careers.example.com/api/pcsx/search?domain=example.com"
         "&query=&location=united%20states"
         "&filter_work_location_option=remote"),
    adapter="pcsx")


def _stub(requests):
    search = (FIXTURES / "pcsx_search_sample.json").read_text(encoding="utf-8")
    detail = (FIXTURES / "pcsx_detail_sample.html").read_text(encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del headers, data
        requests.append(url)
        if "/api/pcsx/search" in url:
            return HttpResponse(200, search)
        return HttpResponse(200, detail)
    return http_get


class PcsxAdapterTest(unittest.TestCase):
    """pcsx: pagination, window gate, no schedule filter, JSON-LD JD."""

    def setUp(self):
        self.requests = []
        self.http_get = _stub(self.requests)
        self.adapter = adapters.get_adapter("pcsx")

    def _list(self):
        return self.adapter.list_postings(SITE, self.http_get, now=NOW)

    def test_pcsx_adds_start_and_timestamp_sort(self):
        """The adapter pages by start and sorts newest-first."""
        self._list()
        search_urls = [u for u in self.requests if "/api/pcsx/search" in u]
        self.assertTrue(search_urls)
        self.assertIn("start=0", search_urls[0])
        self.assertIn("sort_by=timestamp", search_urls[0])

    def test_pcsx_lists_within_window_only(self):
        """Fresh postedTs kept; an older one is dropped."""
        titles = [p.title for p in self._list()]
        self.assertIn("Staff Engineer in Test", titles)
        self.assertNotIn("Old Posting", titles)

    def test_pcsx_keeps_part_time_no_schedule_filter(self):
        """Employment type is never a gate (spec: no schedule checks)."""
        self.assertIn("Automation Test Architect",
                      [p.title for p in self._list()])

    def test_pcsx_posting_fields(self):
        """Identity, company, location, date confidence, detail URL."""
        by_title = {p.title: p for p in self._list()}
        first = by_title["Staff Engineer in Test"]
        self.assertEqual(first.posting_id, "pcsx:893397923700")
        self.assertEqual(first.company, "Example Corp")
        self.assertEqual(first.date_confidence, "url-filter")
        self.assertIn("Remote", first.location)
        self.assertEqual(first.url,
                         "https://careers.example.com/careers/job/893397923700")

    def test_pcsx_drops_non_remote_positions(self):
        """The site filter is an umbrella on some tenants (Dexcom
        remote_local): only positions whose own locations carry the
        Remote marker survive."""
        postings = self._list()
        self.assertNotIn("Old Posting", [p.title for p in postings])
        titles = [p.title for p in postings]
        self.assertIn("Staff Engineer in Test", titles)
        self.assertIn("Automation Test Architect", titles)
        self.assertNotIn("Field Service Technician", titles)

    def test_pcsx_fetch_jd_from_jsonld(self):
        """JD text comes from the detail page's JobPosting description."""
        postings = self._list()
        assert_jd_text(self, self.adapter, SITE, postings[0], self.http_get)

    def test_pcsx_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts pcsx from the URL guard."""
        self.assertTrue(getattr(self.adapter, "REMOTE_SELF_FILTERED", False))


if __name__ == "__main__":
    unittest.main()
