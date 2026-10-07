"""Phenom adapter — CareerConnect /widgets search + JSON-LD detail pages.

Contract live-verified 2026-10-07 (CVS Health): the search page embeds a
`phApp` config naming the widget API endpoint; a POST to that endpoint
with ddoKey "refineSearch" returns pageable job JSON. Query params on the
site URL are forwarded as the widget's selected_fields (the site's own
remote+US filter), so remote is self-filtered. Dates are day-granular
(postedDate) — the strict window is enforced on that field and recorded
as date_confidence "url-filter" (Phenom exposes no precise timestamp;
dateCreated is a mass-refresh stamp, not a posting time). Employment type
is never a gate (spec: no schedule checks). JD text comes from the detail
page's embedded jobDetail DDO (data.job.description), falling back to the
schema.org JobPosting ld+json description.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

from adapters import (decode_json, fetch_detail_body, html_to_text,
                      jsonld_description, origin_of)
from postings import Posting, canonical_id

SOURCE = "phenom"
REMOTE_FILTER_PARAMS = ("remote", "location", "country")
REMOTE_SELF_FILTERED = True
PAGE_SIZE = 100

_PHAPP_RE = re.compile(r"phApp\s*=\s*phApp\s*\|\|\s*(\{.*?\});", re.S)
_JOB_DETAIL_RE = re.compile(r'"jobDetail"\s*:\s*\{')


class PhenomFetchError(RuntimeError):
    """Raised when the search page, widget API, or detail is unusable."""


def list_postings(site, http_get, now=None) -> list[Posting]:
    """phApp config -> /widgets refineSearch -> postings within window."""
    now = now or datetime.now(timezone.utc)
    page = http_get(site.url)
    if page.status != 200:
        raise PhenomFetchError(f"search page HTTP {page.status}")
    config = _phapp_config(page.body)
    endpoint = config.get("widgetApiEndpoint")
    if not endpoint:
        raise PhenomFetchError("no widgetApiEndpoint in phApp config")
    selected = _selected_fields(site.url)
    postings, offset = [], 0
    while True:
        body = _refine_body(config, selected, offset)
        response = http_get(endpoint, headers={"Content-Type":
                                               "application/json"},
                            data=json.dumps(body))
        payload = decode_json(response, "phenom refineSearch",
                              PhenomFetchError)
        jobs = (payload.get("refineSearch", {}).get("data") or {}).get("jobs")
        if not jobs:
            break
        for job in jobs:
            if _within_window(job.get("postedDate"), now):
                postings.append(_to_posting(site, job, now))
        if not _within_window(jobs[-1].get("postedDate"), now) \
                or len(jobs) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """JD text from the detail page's JobPosting ld+json description."""
    if posting.jd_text:
        return posting.jd_text
    body = fetch_detail_body(posting, http_get, PhenomFetchError,
                             f"phenom ({site.name})")
    return _detail_description(body)


def _phapp_config(html: str) -> dict:
    """Parsed phApp config object from the search page."""
    match = _PHAPP_RE.search(html)
    if not match:
        raise PhenomFetchError("no phApp config found on search page")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise PhenomFetchError(f"bad phApp JSON: {exc}") from exc


def _selected_fields(site_url: str) -> dict:
    """Query params on the site URL become widget selected_fields."""
    fields: dict[str, list[str]] = {}
    for key, value in parse_qsl(urlsplit(site_url).query):
        fields.setdefault(key, []).append(value)
    return fields


def _refine_body(config: dict, selected: dict, offset: int) -> dict:
    """The refineSearch request body built from phApp + URL filters."""
    return {
        "lang": config.get("locale", "en_us"),
        "deviceType": config.get("deviceType", "desktop"),
        "country": config.get("country", "us"),
        "pageName": config.get("pageName", "search-results"),
        "ddoKey": "refineSearch",
        "subsearch": "", "from": offset, "jobs": True, "counts": True,
        "size": PAGE_SIZE, "clicks": 0, "isSliderEnable": False,
        "pageId": config.get("pageId"), "siteType": config.get("siteType"),
        "keywords": "", "global": True, "sortBy": "",
        "selected_fields": selected,
        "sort": {"order": "desc", "field": "postedDate"},
    }


def _to_posting(site, job, now) -> Posting:
    """A refineSearch job to a normalized Posting."""
    req_id = str(job.get("reqId") or job.get("jobId") or "")
    origin = origin_of(site.url)
    prefix = _locale_prefix(site.url)
    title = job.get("title", "untitled")
    detail_url = f"{origin}{prefix}/job/{req_id}/{_slug(title)}"
    return Posting(
        posting_id=canonical_id(SOURCE, req_id),
        source=SOURCE,
        url=detail_url,
        jd_url=detail_url,
        company=site.name,
        title=title,
        location=job.get("location") or _location(job),
        posted_at=None,
        date_confidence="url-filter",
        pay_raw=None,
        fetched_at=now,
    )


def _within_window(posted_date, now: datetime) -> bool:
    """Day-granular postedDate inside the 24h window (date comparison)."""
    day = _posted_day(posted_date)
    if day is None:
        return False
    return day >= (now - timedelta(hours=24)).date()


def _posted_day(raw):
    """The date part of a Phenom postedDate, or None."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("+0000", "+00:00")).date()
    except ValueError:
        return None


def _detail_description(html: str) -> str:
    """JD text from the detail page (embedded jobDetail, else ld+json)."""
    embedded = _embedded_job_description(html)
    if embedded:
        return html_to_text(embedded)
    description = jsonld_description(html)
    if description:
        return html_to_text(description)
    raise PhenomFetchError("no job description on detail page")


def _embedded_job_description(html: str) -> str | None:
    """description HTML from the page's embedded jobDetail DDO."""
    match = _JOB_DETAIL_RE.search(html)
    if not match:
        return None
    detail = _json_object_at(html, match.end() - 1)
    if not isinstance(detail, dict):
        return None
    job = (detail.get("data") or {}).get("job") or {}
    return job.get("description")


def _json_object_at(text: str, brace: int):
    """Parse the balanced JSON object that starts at `brace`, or None."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(brace, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[brace:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _location(job) -> str:
    """Fallback location string from city/state/country."""
    parts = [job.get("city"), job.get("state"), job.get("country")]
    return ", ".join(part for part in parts if part)


def _locale_prefix(site_url: str) -> str:
    """The /us/en style prefix that precedes /job/ in a Phenom site URL."""
    path = urlsplit(site_url).path
    return path[: path.rfind("/search-results")] if "/search-results" in path \
        else ""


def _slug(title: str) -> str:
    """Title to URL slug: non-alphanumerics collapse to single dashes."""
    return re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9]+", "-", title)).strip("-")
