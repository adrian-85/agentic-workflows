"""EPAM adapter — careers.epam.com __NEXT_DATA__ jobs (public, no auth).

Contract live-verified 2026-10-05: the jobs page embeds
props.pageProps.jobs.jobs with absolute created_at timestamps, inline
JD text (text), and permalink URLs. Remote+USA self-filters from
vacancy_type/country; everything else is a straight mapping.
"""

import json
import re
from datetime import datetime, timezone

from postings import Posting, canonical_id

SOURCE = "epam"
REMOTE_FILTER_PARAMS = ("vacancy_type=remote",)
REMOTE_SELF_FILTERED = True
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.S,
)
JOBS_URL = "https://careers.epam.com/jobs/"


class EpamFetchError(RuntimeError):
    """Raised when the page or its embedded JSON is unusable."""


def list_postings(site, http_get) -> list[Posting]:
    """Parse the embedded jobs list into gated postings."""
    response = http_get(site.url)
    if response.status != 200:
        raise EpamFetchError(f"epam page HTTP {response.status}")
    match = NEXT_DATA_RE.search(response.body)
    if not match:
        raise EpamFetchError("no __NEXT_DATA__ on page")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise EpamFetchError(f"bad __NEXT_DATA__: {exc}") from exc
    jobs = (payload.get("props", {}).get("pageProps", {})
            .get("jobs", {}).get("jobs", []))
    postings = []
    for job in jobs:
        if job.get("is_expired") or job.get("is_hidden"):
            continue
        if job.get("vacancy_type") != "Remote":
            continue
        if not _is_usa(job):
            continue
        created = job.get("created_at")
        try:
            posted_at = (datetime.fromisoformat(created.replace("Z", "+00:00"))
                         if created else None)
        except ValueError:
            posted_at = None
        postings.append(Posting(
            posting_id=canonical_id(SOURCE, str(job["uid"])),
            source=SOURCE,
            url=JOBS_URL + job.get("permalink_key", ""),
            jd_url=JOBS_URL + job.get("permalink_key", ""),
            company="EPAM",
            title=job.get("name", "untitled"),
            location=_location(job),
            posted_at=posted_at,
            date_confidence="timestamp" if posted_at else "none",
            pay_raw=None,
            fetched_at=datetime.now(timezone.utc),
            jd_text=job.get("text") or None,
        ))
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text rides inline from the list payload."""
    if posting.jd_text:
        return posting.jd_text
    for candidate in list_postings(site, http_get):
        if candidate.posting_id == posting.posting_id:
            return candidate.jd_text or ""
    return ""


def _is_usa(job) -> bool:
    """Country list names the USA."""
    for country in job.get("country") or []:
        if (country.get("name") or "").upper() in ("USA", "UNITED STATES"):
            return True
    return False


def _location(job) -> str:
    """'City, Country' joined text from the structured lists."""
    cities = [city.get("name") for city in job.get("city") or []
              if city.get("name")]
    countries = [country.get("name") for country in job.get("country") or []
                 if country.get("name")]
    return ", ".join(cities + countries)
