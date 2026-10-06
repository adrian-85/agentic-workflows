"""Workday adapter — wday/cxs tenant search API (public, no auth).

List contract live-verified 2026-10-05: POST .../wday/cxs/{tenant}/
{site}/jobs returns jobPostings with relative postedOn dates. The strict
24h window is enforced IN-ADAPTER from those relative dates ("Posted
Today" passes; anything older is dropped), and remote is self-filtered
from locationsText — both stronger than a URL param, so
REMOTE_SELF_FILTERED exempts this adapter from the URL guard. JD text
comes from the CXS detail endpoint; tenants that bot-gate it yield an
empty jobPostingInfo, which raises loudly (the fetch layer then flags
the posting jd-fetch-failed -> review).
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from adapters import decode_json, html_to_text
from postings import Posting, canonical_id

SOURCE = "workday"
REMOTE_FILTER_PARAMS = ("locations=", "location=", "remote")
REMOTE_SELF_FILTERED = True
WITHIN_WINDOW_MARKERS = ("posted today", "just posted")


class WorkdayFetchError(RuntimeError):
    """Raised when the cxs API answers non-200, bad JSON, or empty detail."""


def _tenant_parts(url: str) -> tuple[str, str, str]:
    """(host, tenant, site-name) from a myworkdayjobs.com careers URL."""
    parts = urlsplit(url)
    host = parts.netloc
    tenant = host.split(".")[0]
    segments = [seg for seg in parts.path.split("/") if seg]
    if not segments:
        raise WorkdayFetchError(f"no site segment in url: {url}")
    return host, tenant, segments[0]


def list_postings(site, http_get) -> list[Posting]:
    """Search the tenant as postings; relative dates gate the 24h window."""
    host, tenant, site_name = _tenant_parts(site.url)
    url = f"https://{host}/wday/cxs/{tenant}/{site_name}/jobs"
    body = json.dumps({"appliedFacets": {}, "limit": 20, "offset": 0,
                       "searchText": ""})
    response = http_get(url, headers={"Content-Type": "application/json"},
                        data=body)
    payload = decode_json(response, "workday search", WorkdayFetchError)
    now = datetime.now(timezone.utc)
    postings = []
    for job in payload.get("jobPostings", []):
        if not _within_window(job.get("postedOn", "")):
            continue
        if "remote" not in (job.get("locationsText") or "").lower():
            continue
        external_path = job.get("externalPath", "")
        postings.append(Posting(
            posting_id=canonical_id(SOURCE, external_path),
            source=SOURCE,
            url=site.url.rstrip("/") + external_path,
            jd_url=site.url.rstrip("/") + external_path,
            company=site.name,
            title=job.get("title", "untitled"),
            location=job.get("locationsText", ""),
            posted_at=None,
            date_confidence="url-filter",
            pay_raw=None,
            fetched_at=now,
        ))
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """Fetch the CXS job detail and convert jobDescription HTML to text."""
    host, tenant, site_name = _tenant_parts(site.url)
    external_path = posting.posting_id.split(":", 1)[1]
    url = f"https://{host}/wday/cxs/{tenant}/{site_name}{external_path}"
    response = http_get(url, headers={"Content-Type": "application/json"},
                        data="{}")
    payload = decode_json(response, f"workday job {external_path}",
                          WorkdayFetchError)
    info = payload.get("jobPostingInfo") or {}
    description = info.get("jobDescription")
    if not description:
        raise WorkdayFetchError(
            f"empty jobPostingInfo for {external_path} "
            "(tenant may bot-gate detail requests)")
    return html_to_text(description)


def _within_window(posted_on: str) -> bool:
    """Relative postedOn label inside the strict 24h window."""
    return posted_on.strip().lower() in WITHIN_WINDOW_MARKERS
