"""Ashby adapter — api.ashbyhq.com posting API (public, no auth).

includeCompensation=true yields structured pay (summaryComponents) which
becomes pay_raw; descriptionPlain is the JD text, carried inline from
the list request.
"""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from adapters import AdapterFetchError, fetch_json, parse_iso_time
from postings import Posting, canonical_id

SOURCE = "ashby"
REMOTE_FILTER_PARAMS = ("location=", "remote")
REMOTE_SELF_FILTERED = True
API_BASE = "https://api.ashbyhq.com/posting-api/job-board"




def org_from_url(url: str) -> str:
    """Extract the org slug from a jobs.ashbyhq.com or API URL."""
    segments = [seg for seg in urlsplit(url).path.split("/") if seg]
    if "job-board" in segments:
        return segments[segments.index("job-board") + 1]
    if not segments:
        raise AdapterFetchError(f"no org slug in url: {url}")
    return segments[0]


def list_postings(site, http_get) -> list[Posting]:
    """List the org's jobs as postings with pay_raw and inline JD text."""
    org = org_from_url(site.url)
    payload = fetch_json(f"{API_BASE}/{org}?includeCompensation=true",
                         http_get, f"ashby board {org}")
    now = datetime.now(timezone.utc)
    company = org.replace("-", " ").replace("_", " ").title()
    postings = []
    for job in payload.get("jobs", []):
        if not _is_remote(job):
            continue
        posted_at = parse_iso_time(job.get("publishedAt"))
        postings.append(Posting(
            posting_id=canonical_id(SOURCE, str(job["id"])),
            source=SOURCE,
            url=job.get("jobUrl", site.url),
            jd_url=job.get("jobUrl", site.url),
            company=company,
            title=job.get("title", "untitled"),
            location=job.get("location", ""),
            posted_at=posted_at,
            date_confidence="timestamp" if posted_at else "none",
            pay_raw=_pay_raw(job.get("compensation")),
            fetched_at=now,
            jd_text=job.get("descriptionPlain") or None,
        ))
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """Serve cached list JD text, else re-fetch the board payload."""
    if posting.jd_text:
        return posting.jd_text
    postings = list_postings(site, http_get)
    for candidate in postings:
        if candidate.posting_id == posting.posting_id:
            return candidate.jd_text or ""
    return ""


def _is_remote(job) -> bool:
    """The site's own remote classification: isRemote, location fallback."""
    if job.get("isRemote") is not None:
        return bool(job.get("isRemote"))
    return "remote" in (job.get("location") or "").lower()


def _pay_raw(compensation):
    """First USD summary component to a '$min - $max/period' string."""
    if not compensation:
        return None
    for component in compensation.get("summaryComponents", []):
        if component.get("currencyCode") != "USD":
            continue
        low, high = component.get("minValue"), component.get("maxValue")
        if low is None or high is None:
            continue
        unit = "/hr" if component.get("interval") == "1 HOUR" else "/yr"
        if low == high:
            return f"${low:,}{unit}"
        return f"${low:,} - ${high:,}{unit}"
    return None
