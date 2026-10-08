"""LinkedIn adapter — guest search endpoint (no auth, verified 2026-10-05).

Converts a logged-out UI search URL to the guest API endpoint, preserving
the search's own filter params (keywords, geoId, f_TPR, f_WT, ...). The
strict 24h window is enforced in-adapter from the cards' relative dates
(minutes/hours/just-now pass; "1 day ago"+ drops; no time -> review
flag via date_confidence none). Remote self-filters from the card
location text. JD text comes from the guest view page's
show-more-less-html__markup div.
"""

import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit

from adapters import (AdapterFetchError, card_posting, html_to_text,
                      relative_within_window)
from postings import Posting

SOURCE = "linkedin-guest"
REMOTE_FILTER_PARAMS = ("f_WT=2", "remote")
REMOTE_SELF_FILTERED = True
GUEST_ENDPOINT = ("https://www.linkedin.com/jobs-guest/jobs/api/"
                  "seeMoreJobPostings/search")
# Query params that carry meaning for the guest search; UI-only params
# (currentJobId, origin, referralSearchId, vjk, ...) are dropped.
KEEP_PARAMS = ("keywords", "geoId", "location", "f_TPR", "f_WT", "f_E",
               "f_JT", "f_C", "start")
MAX_PAGES = 3

_CARD_SPLIT = 'data-entity-urn="urn:li:jobPosting:'
_URN_RE = re.compile(r'urn:li:jobPosting:(\d+)')
_TITLE_RE = re.compile(r'class="base-search-card__title">\s*(.*?)\s*</h3>',
                       re.S)
_COMPANY_RE = re.compile(
    r'base-search-card__subtitle.*?<a[^>]*>\s*(.*?)\s*</a>', re.S)
_LOCATION_RE = re.compile(
    r'class="job-search-card__location">\s*(.*?)\s*<', re.S)
_TIME_RE = re.compile(r'<time[^>]*>(.*?)</time>', re.S)
_VIEW_LINK_RE = re.compile(r'href="(https://www\.linkedin\.com/jobs/view/'
                           r'[^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")




def guest_search_url(site_url: str) -> str:
    """UI search URL -> guest API URL, meaningful params preserved."""
    if "jobs-guest" in site_url:
        return site_url
    kept = [(key, value) for key, value in parse_qsl(urlsplit(site_url).query)
            if key in KEEP_PARAMS]
    return f"{GUEST_ENDPOINT}?{urlencode(kept)}"


def list_postings(site, http_get) -> list[Posting]:
    """Page the guest search (up to MAX_PAGES) into gated postings."""
    base_url = guest_search_url(site.url)
    now = datetime.now(timezone.utc)
    postings: list[Posting] = []
    for page in range(MAX_PAGES):
        url = _with_start(base_url, page * 10)
        response = http_get(url)
        if response.status != 200:
            raise AdapterFetchError(f"guest search HTTP {response.status}")
        batch = _parse_cards(response.body, site, now)
        if not batch:
            break
        postings.extend(batch)
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """Fetch the guest view page and extract the description markup."""
    del site
    ext_id = posting.posting_id.split(":", 1)[1]
    response = http_get(f"https://www.linkedin.com/jobs/view/{ext_id}")
    if response.status != 200:
        raise AdapterFetchError(f"guest view HTTP {response.status}")
    match = re.search(
        r'show-more-less-html__markup[^>]*>(.*?)</div>', response.body, re.S)
    if not match:
        raise AdapterFetchError(
            f"no description markup in view page for {ext_id}")
    return html_to_text(match.group(1))


def _with_start(base_url: str, start: int) -> str:
    """Set (or replace) the start param on the guest URL."""
    parts = urlsplit(base_url)
    query = [(key, value) for key, value in parse_qsl(parts.query)
             if key != "start"]
    if start:
        query.append(("start", str(start)))
    return parts._replace(query=urlencode(query)).geturl()


def _parse_cards(body: str, site, now) -> list[Posting]:
    """Cards to postings; relative dates and location gate here."""
    del now
    # A site URL carrying the remote scope (facet or keywords) IS the
    # site's own remote filter; per-card location checking is for URLs
    # without one.
    trust_remote = any(marker in site.url
                       for marker in REMOTE_FILTER_PARAMS)
    postings = []
    for chunk in body.split(_CARD_SPLIT)[1:]:
        urn = _URN_RE.search(_CARD_SPLIT + chunk)
        if not urn:
            continue
        title = _text(_TITLE_RE.search(chunk))
        location = _text(_LOCATION_RE.search(chunk))
        if not trust_remote and "remote" not in location.lower():
            continue
        time_match = _TIME_RE.search(chunk)
        if time_match is not None:
            if not relative_within_window(html.unescape(time_match.group(1))):
                continue
            date_confidence = "url-filter"
        else:
            date_confidence = "none"
        link_match = _VIEW_LINK_RE.search(chunk)
        postings.append(card_posting(
            source=SOURCE,
            ext_id=urn.group(1),
            url=link_match.group(1) if link_match else site.url,
            jd_url=f"https://www.linkedin.com/jobs/view/{urn.group(1)}",
            company=_text(_COMPANY_RE.search(chunk)) or site.name,
            title=title or "untitled",
            location=location,
            date_confidence=date_confidence,
        ))
    return postings



def _text(match) -> str:
    """Regex match to unescaped, tag-stripped text."""
    if not match:
        return ""
    return html.unescape(_TAG_RE.sub("", match.group(1))).strip()
