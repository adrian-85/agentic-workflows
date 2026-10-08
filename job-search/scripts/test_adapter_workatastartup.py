"""Work at a Startup adapter tests: Algolia search + inline JD.

Fixtures are synthetic but shaped like the live contract: an Algolia
multi-query response whose hits carry precise created_at timestamps,
remote flags, locations_for_search, and the full markdown description.
The site URL carries the app id + secured search key (rotates ~daily).
"""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import adapters
from fetch import HttpResponse, Site
from test_helpers import assert_jd_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
SITE = Site(name="Work at a Startup",
            url=("https://testapp-dsn.algolia.net/1/indexes/*/queries"
                 "?x-algolia-application-id=TESTAPP"
                 "&x-algolia-api-key=TESTKEY"),
            adapter="workatastartup")


def _stub(requests):
    page = (FIXTURES / "workatastartup_search_sample.json").read_text(
        encoding="utf-8")
    def http_get(url, headers=None, data=None):
        del url, headers
        requests.append(json.loads(data))
        return HttpResponse(200, page)
    return http_get


class WorkAtAStartupAdapterTest(unittest.TestCase):
    """workatastartup: Algolia filters, created_at gate, inline JD."""

    def setUp(self):
        self.requests = []
        self.http_get = _stub(self.requests)
        self.adapter = adapters.get_adapter("workatastartup")

    def _list(self):
        return self.adapter.list_postings(SITE, self.http_get, now=NOW)

    def test_workatastartup_queries_index_with_remote_us_filters(self):
        """The Algolia query pins the index and remote+US filters only —
        role and job_type are the judge's, not schedule/type gates."""
        self._list()
        body = self.requests[0]
        request = body["requests"][0]
        self.assertEqual(request["indexName"],
                         "WaaSPublicCompanyJob_created_at_desc_production")
        params = parse_qs(request["params"])
        self.assertEqual(params["filters"],
                         ['(remote:yes) AND (locations_for_search:"US")'])
        self.assertNotIn("role", params.get("filters", [""])[0])
        self.assertNotIn("job_type", params.get("filters", [""])[0])

    def test_workatastartup_gates_created_at_24h(self):
        """Precise created_at gates the window; stale/no-date drop."""
        titles = [p.title for p in self._list()]
        self.assertIn("Staff Engineer in Test", titles)
        self.assertNotIn("Old Posting", titles)
        self.assertNotIn("No Date Posting", titles)

    def test_workatastartup_parses_hit_fields(self):
        """Identity, title, company, most-specific location, pay, JD."""
        by_title = {p.title: p for p in self._list()}
        first = by_title["Staff Engineer in Test"]
        self.assertEqual(first.posting_id, "workatastartup:111")
        self.assertEqual(first.company, "Example Corp")
        self.assertEqual(first.location, "San Francisco, CA, US")
        self.assertEqual(first.date_confidence, "timestamp")
        self.assertIsNotNone(first.posted_at)
        self.assertTrue(first.url.endswith(
            "/companies/example/jobs/111"))
        self.assertIsNone(first.pay_raw)
        self.assertIn("Key Responsibilities", first.jd_text)
        self.assertIn("release quality gates", first.jd_text)

    def test_workatastartup_fetch_jd_serves_cached_text(self):
        """JD text rides inline from the Algolia hit during listing."""
        for posting in self._list():
            assert_jd_text(self, self.adapter, SITE, posting, self.http_get)

    def test_workatastartup_self_filters_remote(self):
        """REMOTE_SELF_FILTERED exempts workatastartup from the URL guard."""
        self.assertTrue(getattr(
            adapters.get_adapter("workatastartup"),
            "REMOTE_SELF_FILTERED", False))


if __name__ == "__main__":
    unittest.main()
