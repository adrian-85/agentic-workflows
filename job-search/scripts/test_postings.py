"""Posting model tests: canonical ids, dedup, and the strict 24h gate.

All data is synthetic (Example Corp etc.) — no real postings (spec:
testing rule).
"""

import unittest
from datetime import datetime, timedelta

from postings import Posting, canonical_id, dedup, is_within_24h

NOW = datetime(2026, 10, 5, 12, 0, 0)


def _posting(**overrides):
    """Synthetic posting with test defaults; overrides applied on top."""
    base = {
        "posting_id": "example:1",
        "source": "example",
        "url": "https://jobs.example.com/postings/1",
        "jd_url": "https://jobs.example.com/postings/1",
        "company": "Example Corp",
        "title": "Staff Engineer in Test",
        "location": "US Remote",
        "posted_at": NOW - timedelta(hours=1),
        "date_confidence": "timestamp",
        "pay_raw": "$120,000 - $150,000/yr",
        "fetched_at": NOW,
    }
    base.update(overrides)
    return Posting(**base)


class CanonicalIdTest(unittest.TestCase):
    """canonical_id yields source-prefixed, query-stripped stable ids."""

    def test_posting_id_format(self):
        """An external id becomes '<source>:<id>'."""
        self.assertEqual(canonical_id("example-source", "12345"),
                         "example-source:12345")

    def test_canonical_id_strips_query_params(self):
        """Tracking query params never change the canonical id."""
        first = canonical_id(
            "s", "https://x.example/jobs/1?utm_source=li&ref=feed"
        )
        second = canonical_id("s", "https://x.example/jobs/1")
        self.assertEqual(first, second)
        self.assertEqual(first, "s:https://x.example/jobs/1")


class DedupTest(unittest.TestCase):
    """dedup keeps the first posting per canonical id or canonical URL."""

    def test_dedup_same_source_query_variant(self):
        """Query-param variants of one URL collapse to the first seen."""
        first = _posting(posting_id="s:https://x.example/j/1",
                         url="https://x.example/j/1")
        variant = _posting(posting_id="s:https://x.example/j/1?utm=1",
                           url="https://x.example/j/1?utm=1")
        self.assertEqual(len(dedup([first, variant])), 1)
        self.assertIs(dedup([first, variant])[0], first)

    def test_dedup_across_sources(self):
        """The same detail URL on two sources collapses to the first seen."""
        first = _posting(source="aggregator",
                         posting_id="aggregator:https://c.example/j/9",
                         url="https://c.example/j/9")
        second = _posting(source="company",
                          posting_id="company:https://c.example/j/9",
                          url="https://c.example/j/9")
        result = dedup([first, second])
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], first)

    def test_dedup_keeps_distinct_postings(self):
        """Different canonical URLs and ids never collapse."""
        first = _posting(posting_id="a:1", url="https://x.example/j/1")
        second = _posting(posting_id="a:2", url="https://x.example/j/2")
        self.assertEqual(len(dedup([first, second])), 2)

    def test_dedup_ext_id_collision_across_sources_kept(self):
        """The same numeric id on two sources is usually two different
        jobs — ext-id collisions do NOT dedup across sources."""
        first = _posting(source="board-a", posting_id="board-a:123",
                         url="https://a.example/j/123")
        second = _posting(source="board-b", posting_id="board-b:123",
                          url="https://b.example/j/123")
        self.assertEqual(len(dedup([first, second])), 2)


class Within24hTest(unittest.TestCase):
    """is_within_24h implements the strict literal 24-hour window."""

    def test_is_within_24h_boundaries(self):
        """23h59m inside; 24h01m outside; missing timestamp outside."""
        self.assertTrue(is_within_24h(NOW - timedelta(hours=23, minutes=59),
                                      NOW))
        self.assertFalse(is_within_24h(NOW - timedelta(hours=24, minutes=1),
                                       NOW))
        self.assertFalse(is_within_24h(None, NOW))


if __name__ == "__main__":
    unittest.main()
