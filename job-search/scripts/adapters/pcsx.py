"""pcsx adapter — jobs.<host>/api/pcsx/search JSON + JSON-LD detail pages.

Contract live-verified 2026-10-07 (NVIDIA): GET /api/pcsx/search returns
data.positions (page size 10) with a sortable epoch postedTs, plus a
count for pagination. The site URL carries the site's own remote+US
filter (location / filter_work_location_option), so remote is
self-filtered; the adapter adds start and sort_by=timestamp. postedTs is
day-granular (midnight UTC), so the strict window is enforced on that
date and recorded as date_confidence "url-filter" (the API exposes no
precise posting time). Employment type is never a gate (spec: no schedule
checks). JD text comes from the detail page's schema.org JobPosting
ld+json description.
"""

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from adapters import (detail_jsonld_jd, epoch_time, fetch_json,
                      origin_of)
from postings import Posting, canonical_id, day_within_window

SOURCE = "pcsx"
REMOTE_FILTER_PARAMS = ("filter_work_location_option", "location")
REMOTE_SELF_FILTERED = True




def list_postings(site, http_get, now=None) -> list[Posting]:
    """Paged /api/pcsx/search, gated to the 24h window in-adapter."""
    now = now or datetime.now(timezone.utc)
    postings, start = [], 0
    while True:
        payload = fetch_json(_page_url(site.url, start), http_get,
                             "pcsx search")
        data = payload.get("data") or {}
        positions = data.get("positions") or []
        if not positions:
            break
        for position in positions:
            if not _is_remote(position):
                continue
            if _within_window(position.get("postedTs"), now):
                postings.append(_to_posting(site, position, now))
        start += len(positions)
        total = data.get("count")
        if not _within_window(positions[-1].get("postedTs"), now):
            break
        if total is not None and start >= total:
            break
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text from the detail page's JobPosting JSON-LD."""
    return detail_jsonld_jd(site, posting, http_get, "pcsx")


def _page_url(site_url: str, start: int) -> str:
    """Site URL with an explicit start and newest-first sort."""
    parts = urlsplit(site_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["start"] = [str(start)]
    query["sort_by"] = ["timestamp"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query, doseq=True), parts.fragment))


def _is_remote(position) -> bool:
    """Position's own locations carry the Remote marker.

    The URL filter is an umbrella on some tenants (Dexcom's
    remote_local covers city-anchored flexible roles), so the marker in
    the position's locations list is the per-posting deterministic
    signal ("Remote - US", "US, TX, Remote", ...).
    """
    return "remote" in ", ".join(position.get("locations") or []).lower()


def _to_posting(site, position, now) -> Posting:
    """A pcsx position to a normalized Posting."""
    position_url = position.get("positionUrl") or ""
    origin = origin_of(site.url)
    return Posting(
        posting_id=canonical_id(SOURCE, str(position.get("id"))),
        source=SOURCE,
        url=origin + position_url,
        jd_url=origin + position_url,
        company=site.name,
        title=position.get("name", "untitled"),
        location=", ".join(position.get("locations") or []),
        posted_at=epoch_time(position.get("postedTs")),
        date_confidence="url-filter",
        pay_raw=None,
        fetched_at=now,
    )


def _within_window(posted_ts, now: datetime) -> bool:
    """Day-granular postedTs inside the 24h window (date comparison)."""
    posted_at = epoch_time(posted_ts)
    return day_within_window(posted_at.date() if posted_at else None, now)
