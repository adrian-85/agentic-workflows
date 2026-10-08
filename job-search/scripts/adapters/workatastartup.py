"""Work at a Startup adapter — Algolia search index (Y Combinator).

Contract live-verified 2026-10-07: the jobs search is Algolia
(WaaSPublicCompanyJob_created_at_desc_production), queried with a
SECURED search key the site mints per session (~24h validity). The key
rides in the site URL (gitignored); rotate by re-copying the URL from a
fresh logged-in capture — an expired key surfaces as a loud non-200.

The adapter enforces remote:yes + locations_for_search:"US"
(deterministic remote/US gates); role and job_type stay with the judge
(spec: no schedule/type checks — e.g. no full-time-only gate). Hit
created_at is precise, so timestamp confidence gates the strict 24h
window, and the full markdown description rides inline as JD text
(apply URLs still point at YC's login flow — the data is for surfacing
and judging).
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

from adapters import decode_json, html_to_text, parse_iso_time
from postings import Posting, canonical_id, is_within_24h

SOURCE = "workatastartup"
REMOTE_FILTER_PARAMS = ("remote", "locations_for_search")
REMOTE_SELF_FILTERED = True
INDEX_NAME = "WaaSPublicCompanyJob_created_at_desc_production"
FILTERS = '(remote:yes) AND (locations_for_search:"US")'
HITS_PER_PAGE = 100
MAX_PAGES = 10


class WorkAtAStartupFetchError(RuntimeError):
    """Raised when the Algolia search is unusable."""


def list_postings(site, http_get, now=None) -> list[Posting]:
    """Page the date-desc index, stopping when hits leave the window."""
    now = now or datetime.now(timezone.utc)
    postings = []
    for page in range(MAX_PAGES):
        params = urlencode({"query": "", "page": page, "hitsPerPage": 100,
                            "filters": FILTERS})
        body = json.dumps({"requests": [{"indexName": INDEX_NAME,
                                         "params": params}]})
        response = http_get(
            site.url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body)
        payload = decode_json(response, "workatastartup search",
                              WorkAtAStartupFetchError)
        result = payload["results"][0]
        hits = result.get("hits") or []
        if not hits:
            break
        stop = False
        for hit in hits:
            posted_at = parse_iso_time(hit.get("created_at"))
            if posted_at is None or not is_within_24h(posted_at, now):
                stop = True
                continue
            postings.append(_to_posting(site, hit, posted_at, now))
        if stop or len(hits) < 100:
            break
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text rides inline from the Algolia hit during listing."""
    del site, http_get  # the search hit carries the full description
    if posting.jd_text:
        return posting.jd_text
    raise WorkAtAStartupFetchError(
        f"no inline JD text for {posting.posting_id}")



def _to_posting(site, hit, posted_at, now) -> Posting:
    """An Algolia hit to a normalized Posting."""
    locations = hit.get("locations_for_search") or []
    description = hit.get("description") or ""
    location = locations[-1] if locations else ""
    if not re.search(r"\bUS\b", location, re.I):
        # Worldwide-remote roles carry multi-country location lists; the
        # searchState's US eligibility is what admitted them.
        location = f"US / {location}" if location else "US"
    return Posting(
        posting_id=canonical_id(SOURCE, str(hit.get("objectID")
                                             or hit.get("id") or "")),
        source=SOURCE,
        url=hit.get("search_path") or "",
        jd_url=hit.get("search_path") or "",
        company=hit.get("company_name") or site.name,
        title=hit.get("title", "untitled"),
        location=location,
        posted_at=posted_at,
        date_confidence="timestamp",
        pay_raw=None,
        fetched_at=now,
        jd_text=html_to_text(description) or None,
    )
