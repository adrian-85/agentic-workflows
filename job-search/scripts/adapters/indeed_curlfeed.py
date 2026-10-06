"""Indeed adapter — curl-fed search page parsing.

Contract basis: Indeed's stable card markers (data-jk job id,
jobTitle/companyName/companyLocation spans, Posted date metadata). The
search page requires a logged-in session, supplied through the auth
layer (auth/curl-feed). Strict 24h gate in-adapter from Posted labels;
remote self-filters from the card location. JD text comes from the
viewjob page's jobDescriptionText div.
"""

import html
import re

from adapters import (card_posting, html_to_text,
                      relative_within_window)
from postings import Posting

SOURCE = "indeed-curlfeed"
REMOTE_FILTER_PARAMS = ("l=Remote", "remote")
REMOTE_SELF_FILTERED = True
VIEW_URL = "https://www.indeed.com/viewjob?jk="

_CARD_SPLIT = 'data-jk="'
_ID_RE = re.compile(r'^([0-9a-fA-F]+)"')
_TITLE_RE = re.compile(r'class="jobTitle[^"]*"[^>]*>.*?<span[^>]*>(.*?)'
                       r'</span>', re.S)
_COMPANY_RE = re.compile(r'class="companyName"[^>]*>(.*?)<', re.S)
_LOCATION_RE = re.compile(r'class="companyLocation"[^>]*>(.*?)<', re.S)
_DATE_RE = re.compile(r'class="date"[^>]*>(.*?)<', re.S)


class IndeedFetchError(RuntimeError):
    """Raised when the search page or view page is unusable."""


def list_postings(site, http_get) -> list[Posting]:
    """Parse the fed search page's cards into gated postings."""
    response = http_get(site.url)
    if response.status != 200:
        raise IndeedFetchError(f"indeed search HTTP {response.status}")
    postings = []
    for chunk in response.body.split(_CARD_SPLIT)[1:]:
        id_match = _ID_RE.match(chunk)
        if not id_match:
            continue
        location = _strip(_LOCATION_RE.search(chunk))
        if "remote" not in location.lower():
            continue
        date_label = _strip(_DATE_RE.search(chunk))
        if date_label:
            if not relative_within_window(date_label):
                continue
            date_confidence = "url-filter"
        else:
            date_confidence = "none"
        postings.append(card_posting(
            source=SOURCE,
            ext_id=id_match.group(1),
            url=VIEW_URL + id_match.group(1),
            jd_url=VIEW_URL + id_match.group(1),
            company=_strip(_COMPANY_RE.search(chunk)) or site.name,
            title=_strip(_TITLE_RE.search(chunk)) or "untitled",
            location=location,
            date_confidence=date_confidence,
        ))
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """Fetch the viewjob page and extract jobDescriptionText."""
    del site
    response = http_get(posting.jd_url)
    if response.status != 200:
        raise IndeedFetchError(f"indeed view HTTP {response.status}")
    match = re.search(r'id="jobDescriptionText"[^>]*>(.*?)</div>',
                      response.body, re.S)
    if not match:
        raise IndeedFetchError(
            f"no jobDescriptionText for {posting.posting_id}")
    return html_to_text(match.group(1))



def _strip(match) -> str:
    """Regex match to unescaped, tag-stripped text."""
    if not match:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
