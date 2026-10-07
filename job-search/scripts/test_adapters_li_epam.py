"""LinkedIn-guest + EPAM adapter tests against synthetic fixtures.

Both contracts live-verified 2026-10-05 (guest cards + view-page markup;
EPAM __NEXT_DATA__ pageProps.jobs.jobs). Fixtures are fictional (spec:
testing rule).
"""

import unittest

import adapters
from fetch import Site
from test_helpers import serve_fixture
LINKEDIN_SITE = Site(
    name="LinkedIn Guest",
    url=("https://www.linkedin.com/jobs/search-results/?currentJobId=4475"
         "&keywords=Software%20Engineer%20in%20Test&origin=PREFERENCES"
         "_LANDING&geoId=103644278&f_TPR=r86400"),
    adapter="linkedin-guest")
EPAM_SITE = Site(name="EPAM Example",
                 url=("https://careers.example.com/en/jobs/"
                      "united_states_of_america?search=test"),
                 adapter="epam")


class LinkedInGuestAdapterTest(unittest.TestCase):
    """linkedin-guest: URL conversion, card parsing, 24h gate, JD fetch."""

    def setUp(self):
        self.requests = []
        self.http_get = serve_fixture("linkedin_cards_sample.html", self.requests)
        self.adapter = adapters.get_adapter("linkedin-guest")

    def test_linkedin_guest_url_conversion(self):
        """UI search URL becomes the guest API URL, filters preserved."""
        postings = self.adapter.list_postings(LINKEDIN_SITE, self.http_get)
        self.assertTrue(postings or self.requests)
        requested = self.requests[0]
        self.assertIn("jobs-guest/jobs/api/seeMoreJobPostings/search",
                      requested)
        self.assertIn("keywords=Software+Engineer+in+Test", requested)
        self.assertIn("f_TPR=r86400", requested)
        self.assertIn("geoId=103644278", requested)
        self.assertNotIn("currentJobId", requested)
        self.assertNotIn("origin=", requested)

    def test_linkedin_guest_parses_job_cards(self):
        """Cards parse to postings; remote self-filter; ids stable."""
        postings = self.adapter.list_postings(LINKEDIN_SITE, self.http_get)
        by_title = {p.title: p for p in postings}
        first = by_title["Staff Software Development Engineer in Test"]
        self.assertEqual(first.posting_id, "linkedin-guest:9900000001")
        self.assertEqual(first.company, "Example Corp")
        self.assertEqual(first.location, "Remote (US)")
        self.assertEqual(first.source, "linkedin-guest")

    def test_linkedin_guest_relative_dates_gate_window(self):
        """"3 hours ago"/"Just now" pass; "1 day ago" drops; no-time flags."""
        postings = self.adapter.list_postings(LINKEDIN_SITE, self.http_get)
        by_title = {p.title: p for p in postings}
        self.assertIn("Staff Software Development Engineer in Test", by_title)
        self.assertIn("Release Test Engineer", by_title)
        self.assertNotIn("Quality Assurance Engineer", by_title)
        self.assertEqual(
            by_title["Staff Software Development Engineer in Test"]
            .date_confidence, "url-filter")
        no_time = by_title["Automation Test Architect"]
        self.assertEqual(no_time.date_confidence, "none")

    def test_linkedin_drops_non_remote_locations(self):
        """Locations without Remote never surface."""
        postings = self.adapter.list_postings(LINKEDIN_SITE, self.http_get)
        locations = [p.location for p in postings]
        self.assertTrue(all("Remote" in loc for loc in locations))
        self.assertNotIn("Hybrid Support Engineer",
                         [p.title for p in postings])

    def test_linkedin_keywords_carrying_remote_trust_the_search(self):
        """A saved search whose keywords carry the remote scope IS the
        site's own remote filter: per-card location checks are skipped."""
        site = Site(name="LinkedIn Guest",
                    url=("https://www.linkedin.com/jobs/search-results/"
                         "?keywords=quality%20engineer%2C%20remote"
                         "&f_TPR=r86400"),
                    adapter="linkedin-guest")
        postings = self.adapter.list_postings(site, self.http_get)
        self.assertIn("Hybrid Support Engineer", [p.title for p in postings])

    def test_linkedin_fetch_jd_returns_description(self):
        """The guest view page's markup div becomes plain JD text."""
        postings = self.adapter.list_postings(LINKEDIN_SITE, self.http_get)
        view = serve_fixture("linkedin_view_sample.html", self.requests)
        text = self.adapter.fetch_jd(LINKEDIN_SITE, postings[0], view)
        self.assertIn("Staff SDET", text)
        self.assertIn("release quality gates", text)
        self.assertNotIn("<p>", text)
        self.assertIn("/jobs/view/9900000001", self.requests[-1])


class EpamAdapterTest(unittest.TestCase):
    """epam: NEXT_DATA parsing, remote self-filter, inline JD text."""

    def setUp(self):
        self.requests = []
        self.http_get = serve_fixture("epam_sample.json", self.requests)
        self.adapter = adapters.get_adapter("epam")

    def test_epam_parses_fixture_postings(self):
        """Remote USA postings parse with absolute timestamps + JD inline."""
        postings = self.adapter.list_postings(EPAM_SITE, self.http_get)
        self.assertEqual(len(postings), 1)
        first = postings[0]
        self.assertEqual(first.title, "Senior Test Automation Engineer")
        self.assertEqual(first.posting_id, "epam:blt0example0000000001")
        self.assertEqual(first.location, "Remote, USA")
        self.assertEqual(first.date_confidence, "timestamp")
        self.assertIsNotNone(first.posted_at)
        self.assertIn("test automation", first.jd_text)
        self.assertTrue(first.url.endswith(
            "/jobs/senior-test-automation-engineer_example01"))

    def test_epam_drops_hybrid(self):
        """Only Remote vacancy_type postings surface (self-filtered)."""
        postings = self.adapter.list_postings(EPAM_SITE, self.http_get)
        self.assertEqual([p.title for p in postings],
                         ["Senior Test Automation Engineer"])

    def test_epam_fetch_jd_serves_cached_text(self):
        """JD text rides inline from the list payload."""
        postings = self.adapter.list_postings(EPAM_SITE, self.http_get)
        text = self.adapter.fetch_jd(EPAM_SITE, postings[0], self.http_get)
        self.assertIn("release quality", text)


class AdapterContractTest(unittest.TestCase):
    """Both adapters declare remote handling for the guard."""

    def test_adapters_declare_remote_handling(self):
        """Self-filtered adapters exempt from the URL-param guard."""
        for name in ("linkedin-guest", "epam"):
            adapter = adapters.get_adapter(name)
            self.assertTrue(
                getattr(adapter, "REMOTE_SELF_FILTERED", False), msg=name)


if __name__ == "__main__":
    unittest.main()
