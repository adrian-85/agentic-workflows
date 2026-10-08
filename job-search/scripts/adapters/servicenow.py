"""ServiceNow adapter — careers sitemap + JobPosting JSON-LD detail pages.

Contract live-verified 2026-10-07: the careers sitemap lists every job
URL with an ISO lastmod (cheap freshness pre-filter); detail pages embed
the full JobPosting JSON-LD in a script tag whose type HTML-encodes the
plus sign (application/ld&#x2B;json). The JSON-LD carries datePosted
(day-granular — gated in-adapter with day_within_window and recorded as
date_confidence "url-filter"), jobLocationType TELECOMMUTE (the
per-posting remote marker; ServiceNow's remote=true covers city-anchored
remote-eligible roles), applicantLocationRequirements (the US gate), and
description (the JD, HTML). The search page's cards carry no dates, which
is why the sitemap drives the window. Employment type is never a gate.
"""

import re
from datetime import datetime, timezone

from adapters import (fetch_detail_body, fresh_sitemap_details,
                      html_to_text, iso_day, jsonld_job_posting,
                      midnight_utc, sitemap_url)
from postings import Posting, canonical_id, day_within_window

SOURCE = "servicenow"
REMOTE_FILTER_PARAMS = ("remote", "country=")
REMOTE_SELF_FILTERED = True

_JOB_URL_RE = re.compile(r"/jobs/(?P<id>\d+)/")


class ServiceNowFetchError(RuntimeError):
    """Raised when the sitemap or a detail page is unusable."""


def list_postings(site, http_get, now=None) -> list[Posting]:
    """Sitemap (lastmod pre-filter) -> detail JSON-LD -> postings."""
    now = now or datetime.now(timezone.utc)
    response = http_get(sitemap_url(site.url))
    if response.status != 200:
        raise ServiceNowFetchError(f"careers sitemap HTTP {response.status}")
    postings = []
    for match, loc, _modified, body in fresh_sitemap_details(
            response.body, _JOB_URL_RE, now, http_get):
        job = jsonld_job_posting(body)
        if job is None or not _keep(job, now):
            continue
        postings.append(_to_posting(site, match, loc, job, now))
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text rides inline from the detail fetch during listing."""
    if posting.jd_text:
        return posting.jd_text
    body = fetch_detail_body(posting, http_get, ServiceNowFetchError,
                             f"servicenow ({site.name})")
    job = jsonld_job_posting(body)
    if job is None:
        raise ServiceNowFetchError(
            f"no JobPosting JSON-LD on detail page for "
            f"{posting.posting_id} ({site.name})")
    return html_to_text(job.get("description") or "")


def _keep(job, now) -> bool:
    """TELECOMMUTE + US + datePosted inside the strict 24h window."""
    if job.get("jobLocationType") != "TELECOMMUTE":
        return False
    if not _in_us(job):
        return False
    return day_within_window(iso_day(job.get("datePosted")), now)


def _in_us(job) -> bool:
    """US remote-eligible per the posting's own location data."""
    requirements = job.get("applicantLocationRequirements") or {}
    if str(requirements.get("name", "")).lower() == "united states":
        return True
    locations = job.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    for location in locations or []:
        address = location.get("address") or {}
        if str(address.get("addressCountry", "")).lower() == "united states":
            return True
    return False



def _to_posting(site, match, loc, job, now) -> Posting:
    """A JobPosting JSON-LD to a normalized Posting."""
    posted_day = iso_day(job.get("datePosted"))
    location = job.get("jobLocation") or {}
    if isinstance(location, list):
        location = location[0] if location else {}
    location_name = location.get("name") or (
        location.get("address") or {}).get("addressLocality", "")
    return Posting(
        posting_id=canonical_id(SOURCE, match.group("id")),
        source=SOURCE,
        url=loc,
        jd_url=loc,
        company=site.name,
        title=job.get("title", "untitled"),
        location=location_name,
        posted_at=midnight_utc(posted_day),
        date_confidence="url-filter",
        pay_raw=None,
        fetched_at=now,
        jd_text=html_to_text(job.get("description") or "") or None,
    )
