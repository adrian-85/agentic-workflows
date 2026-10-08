"""Shopify adapter — careers sitemap + turbo-stream detail pages.

Contract live-verified 2026-10-07: the careers sitemap lists every job
URL (<loc>) with an ISO lastmod; detail pages server-render the title
and embed the JD inside a doubly-escaped
window.__reactRouterContext.streamController.enqueue("...") turbo-stream
chunk (JSON-in-JS-string). The strict 24h window gates on sitemap
lastmod; only fresh URLs get a detail fetch (bounded by the window, so
listing makes 1 + N-fresh requests; the fetch layer's pacing applies to
fetch_jd, which serves the inline JD). Remote self-filters from the
island's isRemote element pair.
"""

import html
import json
import re
from datetime import datetime, timezone

from adapters import (AdapterFetchError, fetch_detail_body, fresh_sitemap_details,
                      html_to_text, sitemap_url)
from postings import Posting, canonical_id

SOURCE = "shopify"
REMOTE_FILTER_PARAMS = ("remote", "location=")
REMOTE_SELF_FILTERED = True

_JOB_URL_RE = re.compile(
    r'/careers/(?P<slug>[a-z0-9-]+)_(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-'
    r'[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$')
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_ENQUEUE_RE = re.compile(
    r'streamController\.enqueue\("((?:[^"\\]|\\.)*)"\)')
_MIN_JD_CHARS = 80




def list_postings(site, http_get, now=None) -> list[Posting]:
    """Sitemap (lastmod 24h gate) -> detail fetch -> postings."""
    now = now or datetime.now(timezone.utc)
    response = http_get(sitemap_url(site.url, "/careers/sitemap.xml"))
    if response.status != 200:
        raise AdapterFetchError(f"careers sitemap HTTP {response.status}")
    postings = []
    for match, loc, posted_at, body in fresh_sitemap_details(
            response.body, _JOB_URL_RE, now, http_get):
        posting = _posting_from_detail(site, match, loc, body, posted_at)
        if posting is not None:
            postings.append(posting)
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text rides inline from the detail fetch during listing."""
    if posting.jd_text:
        return posting.jd_text
    body = fetch_detail_body(posting, http_get,
                             f"shopify ({site.name})")
    return _chunks_to_text(_enqueue_payloads(body)) or ""


def _posting_from_detail(site, match, loc, body, posted_at):
    """Detail page to a posting; None when not remote or unparsable."""
    chunks = _enqueue_payloads(body)
    if not _is_remote(chunks):
        return None
    title_match = _TITLE_RE.search(body)
    title = html.unescape(title_match.group(1)).split(" - ")[0].strip()
    return Posting(
        posting_id=canonical_id(SOURCE, match.group("uuid")),
        source=SOURCE,
        url=loc,
        jd_url=loc,
        company=site.name,
        title=title or match.group("slug"),
        location="Remote",
        posted_at=posted_at,
        date_confidence="timestamp" if posted_at else "none",
        pay_raw=None,
        fetched_at=datetime.now(timezone.utc),
        jd_text=_chunks_to_text(chunks),
    )


def _enqueue_payloads(body: str) -> list[list]:
    """Parsed turbo-stream arrays from every enqueue() chunk."""
    payloads = []
    for match in _ENQUEUE_RE.finditer(body):
        try:
            inner = json.loads(f'"{match.group(1)}"')
            payload = json.loads(inner)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            payloads.append(payload)
    return payloads


def _is_remote(payloads: list[list]) -> bool:
    """True when an isRemote string element is followed by True."""
    return any(a == "isRemote" and b is True
               for chunk in payloads for a, b in zip(chunk, chunk[1:]))


def _chunks_to_text(chunks) -> str | None:
    """The JD (plain text): longest turbo-stream string, HTML-stripped."""
    longest = max((element for chunk in chunks for element in chunk
                   if isinstance(element, str)
                   and len(element) >= _MIN_JD_CHARS),
                  key=len, default=None)
    return html_to_text(longest) if longest else None
