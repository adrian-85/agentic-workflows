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
from urllib.parse import urlsplit

from adapters import html_to_text, parse_iso_time
from postings import Posting, canonical_id, is_within_24h

SOURCE = "shopify"
REMOTE_FILTER_PARAMS = ("remote", "location=")
REMOTE_SELF_FILTERED = True
SITEMAP_PATH = "/careers/sitemap.xml"

_JOB_URL_RE = re.compile(
    r'/careers/(?P<slug>[a-z0-9-]+)_(?P<uuid>[0-9a-f]{8}-[0-9a-f]{4}-'
    r'[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$')
_SITEMAP_ENTRY_RE = re.compile(
    r'<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?')
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_ENQUEUE_RE = re.compile(
    r'streamController\.enqueue\("((?:[^"\\]|\\.)*)"\)')
_MIN_JD_CHARS = 80


class ShopifyFetchError(RuntimeError):
    """Raised when the sitemap or a detail page is unusable."""


def sitemap_url(site_url: str) -> str:
    """Careers sitemap URL derived from the site's own host."""
    return f"https://{urlsplit(site_url).netloc}{SITEMAP_PATH}"


def list_postings(site, http_get, now=None) -> list[Posting]:
    """Sitemap (lastmod 24h gate) -> detail fetch -> postings."""
    now = now or datetime.now(timezone.utc)
    response = http_get(sitemap_url(site.url))
    if response.status != 200:
        raise ShopifyFetchError(f"careers sitemap HTTP {response.status}")
    postings = []
    for loc, lastmod in _SITEMAP_ENTRY_RE.findall(response.body):
        match = _JOB_URL_RE.search(loc)
        if not match:
            continue
        posted_at = _lastmod_time(lastmod)
        if posted_at is not None and not is_within_24h(posted_at, now):
            continue
        detail = http_get(loc)
        if detail.status != 200:
            continue
        posting = _posting_from_detail(site, match, loc, detail.body,
                                       posted_at)
        if posting is not None:
            postings.append(posting)
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text rides inline from the detail fetch during listing."""
    if posting.jd_text:
        return posting.jd_text
    detail = http_get(posting.jd_url)
    if detail.status != 200:
        raise ShopifyFetchError(
            f"shopify detail HTTP {detail.status} for "
            f"{posting.posting_id} ({site.name})")
    return _jd_text(detail.body) or ""


def _posting_from_detail(site, match, loc, body, posted_at):
    """Detail page to a posting; None when not remote or unparsable."""
    chunks = _enqueue_payloads(body)
    if not _is_remote(chunks):
        return None
    title_match = _TITLE_RE.search(body)
    title = html.unescape(title_match.group(1)).split(" - ")[0].strip()
    jd_text = _jd_text(body)
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
        jd_text=jd_text,
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
    for payload in payloads:
        for index, element in enumerate(payload[:-1]):
            if element == "isRemote" and payload[index + 1] is True:
                return True
    return False


def _longest_string(body: str) -> str | None:
    """The JD: the longest string across all turbo-stream chunks."""
    best = None
    for payload in _enqueue_payloads(body):
        for element in payload:
            if isinstance(element, str) and len(element) >= _MIN_JD_CHARS:
                if best is None or len(element) > len(best):
                    best = element
    return best


def _jd_text(body: str) -> str | None:
    """The JD (plain text): longest turbo-stream string, HTML-stripped."""
    jd_html = _longest_string(body)
    return html_to_text(jd_html) if jd_html else None


def _lastmod_time(raw):
    """Sitemap lastmod (ISO, maybe date-only) to aware datetime."""
    parsed = parse_iso_time(raw)
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
