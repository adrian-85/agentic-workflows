"""Curl-feed auth plumbing tests (all synthetic).

The curl-export fixture mirrors browser 'Copy as cURL' blocks for a
fictional board; no real credentials or captured pages (spec: testing
rule). The auth layer serves any session-gated site (e.g. a platform's
curl-feed fallback), independent of the platform adapter.
"""

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import adapters
import auth
import fetch
from fetch import Site
from postings import Posting, canonical_id
from test_helpers import make_config, serve_fixture

CURL_EXPORTS = """
curl 'https://jobs.example-board.example/jobs?q=test&l=Remote&fromage=1' \\
  -H 'authority: jobs.example-board.example' \\
  -H 'cookie: SESSION=abc123; csrftoken=tok456' \\
  -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) ExampleAgent/1.0' \\
  --compressed

curl 'https://jobs.example-board.example/jobs/view?id=9' \\
  -H 'cookie: SESSION=abc123' \\
  --data-raw 'csrfmiddlewaretoken=tok456'
""".strip()


class ParseCurlExportsTest(unittest.TestCase):
    """parse_curl_exports reads 'Copy as cURL' blocks."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.exports = self.dir / "curl.txt"
        self.exports.write_text(CURL_EXPORTS, encoding="utf-8")

    def test_parse_curl_exports_synthetic(self):
        """Blocks parse to method/url/headers/data specs."""
        specs = auth.parse_curl_exports(self.exports)
        self.assertEqual(len(specs), 2)
        first = specs[0]
        self.assertEqual(first.method, "GET")
        self.assertEqual(first.url,
                         "https://jobs.example-board.example/jobs"
                         "?q=test&l=Remote&fromage=1")
        self.assertIn("SESSION=abc123", first.headers.get("cookie", ""))
        self.assertIn("csrftoken", first.headers.get("cookie", ""))
        self.assertIsNone(first.data)
        second = specs[1]
        self.assertEqual(second.method, "POST")
        self.assertEqual(second.data, "csrfmiddlewaretoken=tok456")


class AuthedHttpGetTest(unittest.TestCase):
    """build_authed_http_get replays headers and detects expiry."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        site_dir = self.dir / "Example Jobs Board"
        site_dir.mkdir()
        (site_dir / "curl.txt").write_text(CURL_EXPORTS, encoding="utf-8")
        self.site = Site(name="Example Jobs Board",
                         url="https://jobs.example-board.example/jobs?q=test",
                         adapter="mock", auth="curl-feed")

    def test_authed_get_replays_headers(self):
        """Saved headers ride along on requests."""
        seen = {}
        def base_get(_url, headers=None, data=None):
            del data
            seen["headers"] = headers or {}
            return fetch.HttpResponse(200, "<html>ok</html>")
        authed = auth.build_authed_http_get(self.site, self.dir, base_get)
        authed("https://jobs.example-board.example/jobs?q=test")
        self.assertIn("SESSION=abc123", seen["headers"].get("cookie", ""))

    def test_authed_get_raises_auth_expired_on_401(self):
        """401/403 surface as AuthExpired naming the site."""
        def base_get(_url, headers=None, data=None):
            del headers, data
            return fetch.HttpResponse(401, "denied")
        authed = auth.build_authed_http_get(self.site, self.dir, base_get)
        with self.assertRaises(auth.AuthExpired) as ctx:
            authed("https://jobs.example-board.example/jobs?q=test")
        self.assertEqual(ctx.exception.site_name, "Example Jobs Board")


class AuthIsolationTest(unittest.TestCase):
    """An expired session isolates to its site and names it."""

    def test_auth_expired_isolates_to_site_result(self):
        """401 -> failed SiteResult naming the site; neighbors proceed."""
        requests = []
        ok_site = Site(name="Ok Board",
                       url="https://ok.example.com/search?remote=1",
                       adapter="mock")
        dead_site = Site(name="Dead Board",
                         url="https://dead.example.com/search",
                         adapter="mock", auth="curl-feed")
        adapters.register("mock", _MockAdapter())
        self.addCleanup(adapters.REGISTRY.pop, "mock", None)
        def base_get(url, headers=None, data=None):
            del headers, data
            if "dead.example.com" in url:
                return fetch.HttpResponse(401, "denied")
            return serve_fixture("greenhouse_sample.json", requests)(url)
        report = fetch.fetch_all(
            [dead_site, ok_site], make_config(), Path(tempfile.mkdtemp()),
            seams=fetch.FetchSeams(http_get=base_get,
                                   sleep=lambda _s: None,
                                   auth_dir=_auth_dir_with_dead_exports()))
        self.assertFalse(report.site_results[0].ok)
        self.assertIn("Dead Board", report.site_results[0].error)
        self.assertTrue(report.site_results[1].ok)


class _MockAdapter:
    """Minimal adapter that touches http_get to surface auth expiry."""

    REMOTE_FILTER_PARAMS = ("remote=",)

    def list_postings(self, site, http_get):
        """Touch the session, then serve a stand-in posting list."""
        http_get(site.url)
        return [Posting(posting_id=canonical_id("mock", "1"), source="mock",
                        url="https://ok.example.com/j/1",
                        jd_url="https://ok.example.com/j/1",
                        company="Example Corp",
                        title="Staff Engineer in Test", location="US Remote",
                        posted_at=None, date_confidence="url-filter",
                        pay_raw=None,
                        fetched_at=datetime.now(timezone.utc),
                        jd_text="synthetic jd")]

    def fetch_jd(self, site, posting, http_get):
        """Serve the cached JD."""
        del site, http_get
        return posting.jd_text or "synthetic jd"


def _auth_dir_with_dead_exports() -> Path:
    """Auth dir whose Dead Board exports answer 401 via base_get."""
    auth_dir = Path(tempfile.mkdtemp())
    site_dir = auth_dir / "Dead Board"
    site_dir.mkdir()
    (site_dir / "curl.txt").write_text(
        "curl 'https://dead.example.com/search' \\\n"
        "  -H 'cookie: SESSION=expired'\n", encoding="utf-8")
    return auth_dir


if __name__ == "__main__":
    unittest.main()
