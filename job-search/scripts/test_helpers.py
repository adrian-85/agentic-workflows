"""Shared synthetic factories for job-search tests.

All content is fictional (Example Corp, example.com URLs) — no personal
data in committed test code (spec: testing rule).
"""

from datetime import datetime, timedelta, timezone

import config
from postings import Posting

NOW = datetime.now(timezone.utc)


def make_posting(**overrides) -> Posting:
    """Synthetic posting with test defaults; overrides applied on top."""
    base = {
        "posting_id": "mock:1",
        "source": "mock",
        "url": "https://jobs.example.com/postings/1",
        "jd_url": "https://jobs.example.com/postings/1",
        "company": "Example Corp",
        "title": "Staff Engineer in Test",
        "location": "US Remote",
        "posted_at": NOW - timedelta(hours=1),
        "date_confidence": "timestamp",
        "pay_raw": "$100k - $150k",
        "fetched_at": NOW,
    }
    base.update(overrides)
    return Posting(**base)


def make_config(**overrides) -> config.Config:
    """Synthetic config with test defaults; overrides applied on top."""
    values = {
        "preferred_min": 185000,
        "acceptable_min": 100000,
        "relevance_profile_path": "/tmp/example-resume.docx",
        "relevance_domains": "example domains",
        "ethics_rule": "example rule",
    }
    values.update(overrides)
    return config.Config(**values)
