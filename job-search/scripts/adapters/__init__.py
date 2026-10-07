"""Adapter package: registry + lazy import for platform adapters.

An adapter is any object exposing the adapter contract (spec §2):
    list_postings(site, http_get) -> list[Posting]
    fetch_jd(site, posting, http_get) -> str
    REMOTE_FILTER_PARAMS: tuple[str, ...]
Real adapters are modules in this package (adapters/<name>.py); tests may
register instances directly. get_adapter checks the registry first, then
lazily imports adapters/<name>.
"""

import html
import importlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

from postings import Posting, canonical_id, is_within_24h

REGISTRY: dict[str, object] = {}
_CONTRACT_ATTRS = ("list_postings", "fetch_jd", "REMOTE_FILTER_PARAMS")

_SKIP_TAGS = ("script", "style")
_BREAK_TAGS = ("br", "p", "div", "li", "ul", "ol", "tr", "table",
              "h1", "h2", "h3", "h4", "h5", "h6")


class AdapterError(Exception):
    """Unknown or contract-violating adapter."""


def register(name: str, adapter: object) -> None:
    """Register an adapter object (tests) — real ones self-register by file."""
    REGISTRY[name] = adapter


def get_adapter(name: str) -> object:
    """Registry lookup, then lazy import of adapters/<name>.

    Adapter ids may use dashes in config ("linkedin-guest"); module names
    use underscores (adapters/linkedin_guest.py).
    """
    if name in REGISTRY:
        return REGISTRY[name]
    module_name = f"adapters.{name.replace('-', '_')}"
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise AdapterError(f"unknown adapter: {name}") from exc
    _validate(name, module)
    REGISTRY[name] = module
    return module


def _validate(name: str, adapter: object) -> None:
    missing = [attr for attr in _CONTRACT_ATTRS if not hasattr(adapter, attr)]
    if missing:
        raise AdapterError(
            f"adapter '{name}' missing contract attrs: {', '.join(missing)}"
        )


def parse_iso_time(raw):
    """ISO datetime (with offset) to aware datetime; None on failure."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


_WITHIN_WINDOW_EXACT = ("just now", "today", "just posted",
                        "less than a minute ago")
_RELATIVE_RE = re.compile(r"^(\d+)\+?\s*(minute|hour|day)s?\s+ago$")


def card_posting(source: str, ext_id: str, **fields) -> Posting:
    """Posting from a parsed card: no timestamp, no pay (agent reads JD).

    fields carries the card's per-posting values (url, jd_url, company,
    title, location, date_confidence); everything else is card-shaped.
    A missing required field raises TypeError from Posting itself.
    """
    return Posting(
        posting_id=canonical_id(source, ext_id),
        source=source,
        posted_at=None,
        pay_raw=None,
        fetched_at=datetime.now(timezone.utc),
        **fields,
    )


def relative_within_window(label: str) -> bool:
    """Relative date label inside the strict 24h window.

    Accepts "3 hours ago" / "Just now" style labels and "Posted"
    prefixes ("PostedToday", "Posted 3 days ago"); callers may
    pre-strip a leading "posted".
    """
    text = label.strip().lower().replace("posted", " ").strip()
    if text in _WITHIN_WINDOW_EXACT:
        return True
    match = _RELATIVE_RE.match(text)
    if match:
        count, unit = int(match.group(1)), match.group(2)
        return unit == "minute" or (unit == "hour" and count < 24)
    return False


def decode_json(response, what: str, error_class):
    """Decode a JSON body, raising error_class on non-200 or bad JSON."""
    if response.status != 200:
        raise error_class(f"{what}: HTTP {response.status}")
    try:
        return json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise error_class(f"{what}: bad JSON: {exc}") from exc


class _TextExtractor(HTMLParser):
    """Collects text content, dropping script/style and breaking on blocks."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        """Enter skip regions and emit line breaks for block tags."""
        del attrs
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        """Leave skip regions and break after block tags."""
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        """Keep text outside skip regions."""
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    """HTML (possibly entity-escaped) to normalized plain text."""
    parser = _TextExtractor()
    parser.feed(html.unescape(raw))
    lines = (re.sub(r"\s+", " ", line).strip()
             for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


_JSONLD_RE = re.compile(
    r'<script\b[^>]*application/ld[^>]*>(.*?)</script>',
    re.S)


def jsonld_job_posting(raw: str) -> dict | None:
    """The JobPosting dict from ld+json blocks, or None.

    The type attribute is matched loosely: some sites HTML-encode the
    plus sign (application/ld&#x2B;json).
    """
    for match in _JSONLD_RE.finditer(raw):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def jsonld_description(raw: str) -> str | None:
    """schema.org JobPosting description HTML from ld+json blocks."""
    description = jsonld_job_posting(raw).get("description")
    return description if description else None


def sitemap_entries(body: str) -> list[tuple[str, str | None]]:
    """(loc, lastmod) pairs from a sitemap; lastmod None when absent."""
    entries = re.findall(
        r'<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?', body)
    return [(loc, lastmod or None) for loc, lastmod in entries]


def lastmod_time(raw: str | None):
    """Sitemap lastmod (ISO, maybe date-only) to aware datetime."""
    parsed = parse_iso_time(raw)
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def sitemap_url(site_url: str, path: str = "/sitemap.xml") -> str:
    """Sitemap URL on the site's own host."""
    return f"https://{urlsplit(site_url).netloc}{path}"


def fresh_sitemap_details(body: str, pattern, now: datetime, http_get):
    """Yield (match, loc, lastmod, body) for job URLs fresh in the window.

    Sitemap-driven adapters share this shape: the sitemap's lastmod is a
    cheap freshness pre-filter, then each fresh URL gets one detail
    fetch. Entries without lastmod are kept; non-200 details are skipped.
    """
    for loc, lastmod in sitemap_entries(body):
        match = pattern.search(loc)
        if not match:
            continue
        modified = lastmod_time(lastmod)
        if modified is not None and not is_within_24h(modified, now):
            continue
        # Sitemap <loc> values may carry literal non-ASCII (IRI); requests
        # need the percent-encoded form.
        loc = quote(loc, safe=":/?&=%#")
        detail = http_get(loc)
        if detail.status != 200:
            continue
        yield match, loc, modified, detail.body


def origin_of(url: str) -> str:
    """Scheme and host of a site URL."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def fetch_detail_body(posting, http_get, error_class, label: str) -> str:
    """GET a posting's detail page, raising error_class on non-200."""
    response = http_get(posting.jd_url)
    if response.status != 200:
        raise error_class(
            f"{label} detail HTTP {response.status} for "
            f"{posting.posting_id}")
    return response.body
