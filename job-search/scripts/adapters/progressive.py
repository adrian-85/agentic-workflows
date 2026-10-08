"""Progressive adapter — Talemetry SSR search cards + JSON-LD detail pages.

Contract live-verified 2026-10-07: the search page (behind Cloudflare —
this adapter runs under auth="curl-feed") server-renders job anchors each
followed by a machine-readable <time datetime>, and `sortby=cfm16`
orders by date posted descending, so the first out-of-window card ends
the scan. The search URL path IS the site's own remote facet
(remote_work/remote; sibling facets exist for hybrid/on-site), so remote
is self-filtered. Detail pages carry the JobPosting JSON-LD description
(alongside a sibling script block strict JSON parsing must skip).
Employment type is never a gate (spec: no schedule checks).
"""

import re
from datetime import datetime, timezone

from adapters import (AdapterFetchError, detail_jsonld_jd,
                      iso_day, midnight_utc)
from postings import Posting, canonical_id, day_within_window

SOURCE = "progressive"
REMOTE_FILTER_PARAMS = ("remote",)
REMOTE_SELF_FILTERED = True
SORT_BY_DATE = "sortby=cfm16"
MAX_PAGES = 20

_CARD_RE = re.compile(
    r'href="(?P<url>https://careers\.progressive\.com/jobs/'
    r'(?P<id>\d+)-[^"]+/)">(?P<title>[^<]+)</a>(?P<middle>.*?)'
    r'<time datetime="(?P<date>\d{4}-\d{2}-\d{2})">', re.S)




def list_postings(site, http_get, now=None) -> list[Posting]:
    """Date-sorted search cards, gated to the strict 24h window."""
    now = now or datetime.now(timezone.utc)
    postings = []
    for page in range(1, MAX_PAGES + 1):
        response = http_get(f"{site.url}?{SORT_BY_DATE}&page={page}")
        if response.status != 200:
            raise AdapterFetchError(
                f"progressive search HTTP {response.status}")
        cards = _CARD_RE.findall(response.body)
        if not cards:
            break
        stop = False
        for url, job_id, title, middle, card_date in cards:
            card_day = iso_day(card_date)
            if not day_within_window(card_day, now):
                stop = True
                continue
            postings.append(Posting(
                posting_id=canonical_id(SOURCE, job_id),
                source=SOURCE,
                url=url,
                jd_url=url,
                company=site.name,
                title=title,
                location=_location(middle),
                posted_at=midnight_utc(card_day),
                date_confidence="url-filter",
                pay_raw=None,
                fetched_at=now,
            ))
        if stop:
            break
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text from the detail page's JobPosting JSON-LD."""
    return detail_jsonld_jd(site, posting, http_get, "progressive")



def _location(middle: str) -> str:
    """The card's Location column, tag-stripped and collapsed."""
    after = middle.split("Location: </span>", 1)[-1]
    after = after.split("Date Posted:", 1)[0]
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", after))
    return text.replace("&nbsp;", " ").replace("\xa0", " ").strip(" ,")
