"""Workday adapter tests against a synthetic fixture.

The wday/cxs list contract is live-verified (2026-10-05); the fixture
mirrors its shape with fictional content (spec: testing rule). Relative
postedOn dates gate the strict 24h window inside the adapter.
"""

import json
import unittest
from pathlib import Path

import adapters
from adapters import AdapterFetchError
from fetch import HttpResponse, Site

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WORKDAY_SITE = Site(name="Example Corp Workday",
                    url="https://example.wd1.myworkdayjobs.com/examplecareers",
                    adapter="workday")


def _serve(file_name: str, requests: list):
    """http_get stub serving a fixture; records requested URLs/bodies."""
    body = (FIXTURES / file_name).read_text(encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del headers
        requests.append((url, data))
        return HttpResponse(200, body)
    return http_get


class WorkdayAdapterTest(unittest.TestCase):
    """workday adapter: relative-date 24h gate, remote self-filter, JD."""

    def setUp(self):
        self.requests = []
        self.http_get = _serve("workday_sample.json", self.requests)
        self.adapter = adapters.get_adapter("workday")

    def test_workday_parses_fixture_postings(self):
        """"Posted Today" remote postings survive with url-filter confidence."""
        postings = self.adapter.list_postings(WORKDAY_SITE, self.http_get)
        self.assertEqual(len(postings), 1)
        first = postings[0]
        self.assertEqual(first.title, "Senior Software Engineer in Test")
        self.assertEqual(first.company, "Example Corp Workday")
        self.assertEqual(first.location, "US - Remote")
        self.assertIsNone(first.posted_at)
        self.assertEqual(first.date_confidence, "url-filter")
        self.assertTrue(first.url.endswith(
            "/job/US---Remote/Senior-Software-Engineer-in-Test_43130-JOB-1"))
        self.assertIn("/wday/cxs/example/examplecareers/jobs",
                      self.requests[0][0])

    def test_workday_forwards_url_query_params_as_facets(self):
        """Site URL query params ride into the CXS body as appliedFacets.

        Facet-gated tenants (e.g. Illumina's locations=US - Remote) trust
        the site-side filter, so the per-posting locationsText remote
        check is skipped when facets are applied.
        """
        site = Site(name="Faceted Corp",
                    url=("https://example.wd1.myworkdayjobs.com/examplecareers"
                         "?locations=45f38a85"),
                    adapter="workday")
        postings = self.adapter.list_postings(site, self.http_get)
        body = json.loads(self.requests[0][1])
        self.assertEqual(body["appliedFacets"], {"locations": ["45f38a85"]})
        # Facet-guaranteed remote: the "N Locations" card survives.
        self.assertIn("Multi Location Remote Role",
                      [p.title for p in postings])

    def test_workday_posted_on_relative_dates(self):
        """"Posted Yesterday" and older never pass the strict 24h window."""
        postings = self.adapter.list_postings(WORKDAY_SITE, self.http_get)
        titles = [p.title for p in postings]
        self.assertNotIn("Quality Engineer, Release Validation", titles)

    def test_workday_drops_non_remote_locations(self):
        """The adapter self-filters remote (locationsText must say Remote)."""
        postings = self.adapter.list_postings(WORKDAY_SITE, self.http_get)
        titles = [p.title for p in postings]
        self.assertNotIn("Staff Test Architect", titles)

    def test_workday_fetch_jd_returns_description_text(self):
        """A detail response's jobDescription HTML becomes plain text."""
        postings = self.adapter.list_postings(WORKDAY_SITE, self.http_get)
        detail = json.dumps({"jobPostingInfo": {
            "jobDescription": "<p>Example Corp JD text for SDET.</p>"
        }})
        def detail_get(url, headers=None, data=None):
            del url, headers, data
            return HttpResponse(200, detail)
        text = self.adapter.fetch_jd(WORKDAY_SITE, postings[0], detail_get)
        self.assertIn("Example Corp JD text for SDET.", text)
        self.assertNotIn("<p>", text)

    def test_workday_fetch_jd_raises_on_empty_detail(self):
        """Bot-gated tenants yield empty details -> loud error -> review."""
        postings = self.adapter.list_postings(WORKDAY_SITE, self.http_get)
        empty = json.dumps({"jobPostingInfo": {}})
        def empty_get(url, headers=None, data=None):
            del url, headers, data
            return HttpResponse(200, empty)
        with self.assertRaises(AdapterFetchError):
            self.adapter.fetch_jd(WORKDAY_SITE, postings[0], empty_get)

    def test_workday_remote_self_filtered_satisfies_guard(self):
        """REMOTE_SELF_FILTERED exempts workday from the URL-param guard."""
        self.assertTrue(getattr(self.adapter, "REMOTE_SELF_FILTERED", False))


if __name__ == "__main__":
    unittest.main()
