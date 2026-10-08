"""HiringCafe adapter — classic view __NEXT_DATA__ island.

Contract live-verified 2026-10-07: the classic view passes Cloudflare's
edge challenge with browser sec-fetch/accept headers alone (no cookies),
and SSRs the filtered hits into __NEXT_DATA__ pageProps.ssrHits. Each hit
carries estimated_publish_date_millis (precise — gates the strict 24h
window), workplace/location from the searchState (US + Remote — the
site's own filter), structured yearly_min/max_compensation (composed
into pay_raw), company_name, and a requirements_summary + technical_tools
digest as the JD text (HiringCafe aggregates external boards; full JDs
live at the source apply_url). Employment type is never a gate.
"""

import html
import json
import re
from datetime import datetime, timezone

from adapters import (AdapterFetchError, epoch_time, html_to_text,
                      inline_jd)
from postings import Posting, canonical_id, is_within_24h

SOURCE = "hiringcafe"
REMOTE_FILTER_PARAMS = ("searchState",)
REMOTE_SELF_FILTERED = True

# Cloudflare's edge challenge on this site keys on missing browser
# fetch-metadata headers; these are the set verified to pass bare.
_BROWSER_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "accept-language": "en-US,en;q=0.5",
    "sec-ch-ua": ('"Chromium";v="154", "Brave";v="154", '
                  '"Not A(Brand";v="99"'),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)




def list_postings(site, http_get, now=None) -> list[Posting]:
    """Classic view -> ssrHits -> postings inside the strict 24h window."""
    now = now or datetime.now(timezone.utc)
    response = http_get(site.url, headers=dict(_BROWSER_HEADERS))
    if response.status != 200:
        raise AdapterFetchError(
            f"hiringcafe classic HTTP {response.status} for {site.name} "
            "(Cloudflare edge challenge — browser headers required)")
    hits = _ssr_hits(response.body)
    postings = []
    for hit in hits:
        v5 = hit.get("v5_processed_job_data") or {}
        posted_at = epoch_time(
            (v5.get("estimated_publish_date_millis") or 0) / 1000)
        if posted_at is None or not is_within_24h(posted_at, now):
            continue
        postings.append(_to_posting(site, hit, v5, posted_at, now))
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text rides inline from the SSR hit during listing."""
    del site, http_get
    return inline_jd(posting)


def _ssr_hits(body: str) -> list[dict]:
    """The classic page's SSR hit list from its __NEXT_DATA__ island."""
    match = _NEXT_DATA_RE.search(body)
    if not match:
        raise AdapterFetchError("no __NEXT_DATA__ island on classic page")
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise AdapterFetchError(f"bad __NEXT_DATA__ JSON: {exc}") from exc
    try:
        return data["props"]["pageProps"]["ssrHits"]
    except (KeyError, TypeError) as exc:
        raise AdapterFetchError(
            f"no ssrHits in __NEXT_DATA__: {exc}") from exc



def _to_posting(site, hit, v5, posted_at, now) -> Posting:
    """An SSR hit to a normalized Posting."""
    job = hit.get("job_information") or {}
    title = job.get("title") or v5.get("core_job_title") or "untitled"
    digest = _jd_text(v5)
    return Posting(
        posting_id=canonical_id(SOURCE, hit.get("objectID")
                                or hit.get("id") or ""),
        source=SOURCE,
        url=hit.get("apply_url") or "",
        jd_url=hit.get("apply_url") or "",
        company=v5.get("company_name") or site.name,
        title=html.unescape(title),
        location=v5.get("formatted_workplace_location", ""),
        posted_at=posted_at,
        date_confidence="timestamp",
        pay_raw=_pay_raw(v5),
        fetched_at=now,
        jd_text=digest,
    )


def _pay_raw(v5) -> str | None:
    """Yearly compensation range (USD) to the standard pay_raw shape."""
    minimum = v5.get("yearly_min_compensation")
    maximum = v5.get("yearly_max_compensation")
    if minimum is None and maximum is None:
        return None
    currency = (v5.get("listed_compensation_currency") or "USD").upper()
    if currency != "USD":
        return None
    if minimum is not None and maximum is not None and minimum != maximum:
        return f"${minimum:,.0f} - ${maximum:,.0f}"
    value = maximum if maximum is not None else minimum
    return f"${value:,.0f}"


def _jd_text(v5) -> str | None:
    """Requirements digest plus tool list, or None."""
    parts = [v5.get("requirements_summary") or ""]
    tools = v5.get("technical_tools") or []
    if tools:
        parts.append("Tools: " + ", ".join(tools))
    text = html_to_text("\n".join(part for part in parts if part))
    return text or None
