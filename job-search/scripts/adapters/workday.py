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
from urllib.parse import parse_qsl, urlsplit

from adapters import AdapterFetchError, fetch_json, html_to_text
from postings import Posting, canonical_id

SOURCE = "workday"
REMOTE_FILTER_PARAMS = ("locations=", "location=", "remote")
REMOTE_SELF_FILTERED = True
WITHIN_WINDOW_MARKERS = ("posted today", "just posted")




def _tenant_parts(url: str) -> tuple[str, str, str]:
    """(host, tenant, site-name) from a myworkdayjobs.com careers URL."""
    parts = urlsplit(url)
    host = parts.netloc
    tenant = host.split(".")[0]
    segments = [seg for seg in parts.path.split("/") if seg]
    if not segments:
        raise AdapterFetchError(f"no site segment in url: {url}")
    return host, tenant, segments[0]


def list_postings(site, http_get) -> list[Posting]:
    """Search the tenant as postings; relative dates gate the 24h window."""
    host, tenant, site_name = _tenant_parts(site.url)
    url = f"https://{host}/wday/cxs/{tenant}/{site_name}/jobs"
    facets = _applied_facets(site.url)
    body = json.dumps({"appliedFacets": facets, "limit": 20, "offset": 0,
                       "searchText": ""})
    payload = fetch_json(url, http_get, "workday search",
                         headers={"Content-Type": "application/json"},
                         data=body)
    now = datetime.now(timezone.utc)
    postings = []
    for job in payload.get("jobPostings", []):
        if not _within_window(job.get("postedOn", "")):
            continue
        if not facets and not _is_remote(job):
            continue
        external_path = job.get("externalPath", "")
        postings.append(Posting(
            posting_id=canonical_id(SOURCE, external_path),
            source=SOURCE,
            url=site.url.rstrip("/").split("?")[0] + external_path,
            jd_url=site.url.rstrip("/").split("?")[0] + external_path,
            company=site.name,
            title=job.get("title", "untitled"),
            location=job.get("locationsText", ""),
            posted_at=None,
            date_confidence="url-filter",
            pay_raw=None,
            fetched_at=now,
        ))
    return postings


def _is_remote(job) -> bool:
    """Remote marker in the posting's locationsText.

    Skipped when the site URL applies facets: a facet-gated listing is
    already the site's own remote filter (e.g. Illumina's
    locations=US - Remote, whose results read "N Locations").
    """
    return "remote" in (job.get("locationsText") or "").lower()


def fetch_jd(site, posting, http_get) -> str:
    """Fetch the CXS job detail and convert jobDescription HTML to text."""
    host, tenant, site_name = _tenant_parts(site.url)
    external_path = posting.posting_id.split(":", 1)[1]
    url = f"https://{host}/wday/cxs/{tenant}/{site_name}{external_path}"
    payload = fetch_json(url, http_get, f"workday job {external_path}",
                         headers={"Content-Type": "application/json"},
                         data="{}")
    info = payload.get("jobPostingInfo") or {}
    description = info.get("jobDescription")
    if not description:
        raise AdapterFetchError(
            f"empty jobPostingInfo for {external_path} "
            "(tenant may bot-gate detail requests)")
    return html_to_text(description)


def _applied_facets(site_url: str) -> dict:
    """Site URL query params become CXS appliedFacets (e.g. locations)."""
    return {key: [value] for key, value in parse_qsl(urlsplit(site_url).query)}


def _within_window(posted_on: str) -> bool:
    """Relative postedOn label inside the strict 24h window."""
    return posted_on.strip().lower() in WITHIN_WINDOW_MARKERS
