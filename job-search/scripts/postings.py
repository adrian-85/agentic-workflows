"""Normalized posting model: schema, canonical ids, dedup, 24h gate.

Every adapter emits Posting objects in this one shape (spec §3); the
canonical posting_id is the dedup key across runs and across query-param
variants of the same URL.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

DATE_CONFIDENCE_VALUES = ("timestamp", "url-filter", "none")


@dataclass
# R0902 disabled: this IS the spec §3 schema — one attribute per schema
# field (13); the schema's shape is fixed by the design doc, not style.
class Posting:  # pylint: disable=too-many-instance-attributes
    """One normalized job posting (spec §3 schema plus runtime fields)."""

    posting_id: str
    source: str
    url: str
    jd_url: str
    company: str
    title: str
    location: str
    posted_at: datetime | None
    date_confidence: str
    pay_raw: str | None
    fetched_at: datetime
    jd_text: str | None = None
    review_flags: list[str] = field(default_factory=list)


def canonical_id(source: str, url_or_ext_id: str) -> str:
    """Stable '<source>:<id>'; URLs canonicalize to scheme://netloc/path."""
    if url_or_ext_id.startswith("http"):
        parts = urlsplit(url_or_ext_id)
        return f"{source}:{parts.scheme}://{parts.netloc}{parts.path}"
    return f"{source}:{url_or_ext_id}"


def _url_key(url: str) -> str | None:
    """Source-independent URL identity (netloc+path) for cross-source dedup."""
    if not url.startswith("http"):
        return None
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"


def dedup(postings: list[Posting]) -> list[Posting]:
    """Keep the first posting per canonical id and per canonical URL.

    Ext-id collisions across sources are NOT deduped: 'board-a:123' and
    'board-b:123' are usually different jobs. Cross-source duplicates are
    caught by identical detail URLs instead.
    """
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    kept: list[Posting] = []
    for posting in postings:
        url_key = _url_key(posting.url)
        if posting.posting_id in seen_ids:
            continue
        if url_key is not None and url_key in seen_urls:
            continue
        seen_ids.add(posting.posting_id)
        if url_key is not None:
            seen_urls.add(url_key)
        kept.append(posting)
    return kept


def is_within_24h(posted_at: datetime | None, now: datetime) -> bool:
    """Strict literal 24-hour window (spec: non-goal 'since last run')."""
    if posted_at is None:
        return False
    return now - posted_at < timedelta(hours=24)
