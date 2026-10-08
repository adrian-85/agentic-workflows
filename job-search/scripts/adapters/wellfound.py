"""Wellfound adapter — location landing page's Apollo cache.

Contract live-verified 2026-10-08: the logged-out location landing page
(https://wellfound.com/location/united-states) SSRs an Apollo cache
holding JobListingSearchResult records (title, compensation, remote
bool, locationNames, liveStartAt epoch seconds, full markdown
description) plus StartupResult records whose highlightedJobListings
refs resolve each job's company. The landing's ordering is curated, not
by date, so the adapter scans pages (?page=N) up to MAX_PAGES or the
served pageCount — a bounded slice of the directory, not the whole
14759-job listing. Gates: liveStartAt (precise, strict 24h window) and
the posting's own remote bool; the landing path is the site's US scope.
"""

import json
import re
from datetime import datetime, timezone

from adapters import epoch_time, html_to_text
from postings import Posting, canonical_id, is_within_24h

SOURCE = "wellfound"
REMOTE_FILTER_PARAMS = ("remote", "united-states")
REMOTE_SELF_FILTERED = True
MAX_PAGES = 20

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class WellfoundFetchError(RuntimeError):
    """Raised when the landing page or its cache is unusable."""


def list_postings(site, http_get, now=None) -> list[Posting]:
    """Location landing pages, gated to the strict 24h window."""
    now = now or datetime.now(timezone.utc)
    postings = []
    page = 1
    page_count = None
    while page <= MAX_PAGES:
        response = http_get(f"{site.url}?page={page}")
        if response.status != 200:
            raise WellfoundFetchError(
                f"wellfound landing HTTP {response.status} "
                f"(page {page}, {site.name})")
        jobs, companies, served_count = _apollo_page(response.body)
        if page_count is None:
            page_count = served_count
        if not jobs:
            break
        postings.extend(_page_postings(jobs, companies, site, now))
        if page_count is not None and page >= page_count:
            break
        page += 1
    return sorted(postings, key=lambda p: p.posted_at or now, reverse=True)


def fetch_jd(site, posting, http_get) -> str:
    """JD text rides inline from the Apollo cache during listing."""
    del site, http_get  # the landing cache carries the full description
    if posting.jd_text:
        return posting.jd_text
    raise WellfoundFetchError(
        f"no inline JD text for {posting.posting_id}")


def _page_postings(jobs, companies, site, now):
    """In-window remote postings for one landing page."""
    postings = []
    for job_id, job in jobs.items():
        posted_at = epoch_time(job.get("liveStartAt"))
        if posted_at is None or not is_within_24h(posted_at, now):
            continue
        if not job.get("remote"):
            continue
        locations = job.get("locationNames") or []
        location = ", ".join(locations) if locations else "Remote"
        slug = job.get("slug") or "listing"
        job_url = f"https://wellfound.com/jobs/{job_id}-{slug}"
        postings.append(Posting(
            posting_id=canonical_id(SOURCE, job_id),
            source=SOURCE,
            url=job_url,
            jd_url=job_url,
            company=companies.get(job_id) or site.name,
            title=job.get("title", "untitled"),
            location=location,
            posted_at=posted_at,
            date_confidence="timestamp",
            pay_raw=job.get("compensation"),
            fetched_at=now,
            jd_text=html_to_text(job.get("description") or "") or None,
        ))
    return postings


def _apollo_page(body: str):
    """(jobs, companies, page_count) from the landing's Apollo cache.

    jobs: ordered job records keyed by numeric id. companies: startup-
    name resolution per job id. page_count: the served directory length.
    """
    match = _NEXT_DATA_RE.search(body)
    if not match:
        raise WellfoundFetchError("no __NEXT_DATA__ island on landing page")
    try:
        data = json.loads(match.group(1))["props"]["pageProps"][
            "apolloState"]["data"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise WellfoundFetchError(f"bad Apollo cache: {exc}") from exc
    jobs, companies, page_count = {}, {}, None
    for key, record in data.items():
        if not isinstance(record, dict):
            continue
        typename = record.get("__typename")
        if typename == "JobListingSearchResult":
            jobs[key.split(":")[-1]] = record
        elif typename == "StartupResult":
            for ref in record.get("highlightedJobListings") or []:
                job_key = (ref.get("__ref") or "").split(":")[-1]
                if job_key:
                    companies[job_key] = record.get("name") or ""
        elif typename == "Results":
            page_count = record.get("pageCount")
    return jobs, companies, page_count
