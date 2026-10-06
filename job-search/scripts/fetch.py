"""Fetch framework: sites loader, adapter dispatch, gates, isolation.

Data flow (spec §2): adapters normalize postings; fetch_all applies the
deterministic gates — applied-exclusion, strict 24h, date-confidence and
remote-filter guards — dedups across sites, then fetches JD text for the
survivors. Per-site failures isolate; requests to the same site observe
cfg.request_delay_seconds.
"""

import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import adapters as adapter_registry
import ledger
from postings import Posting, dedup, is_within_24h

HTTP_TIMEOUT_SECONDS = 30
REVIEW_FLAG_DATE = "date-unverified"
REVIEW_FLAG_REMOTE = "site-url-lacks-remote-us-filter"
REVIEW_FLAG_JD = "jd-fetch-failed"


class SitesError(Exception):
    """Raised when a sites file is malformed."""


@dataclass(frozen=True)
class Site:
    """One configured site (sites.toml entry)."""

    name: str
    url: str
    adapter: str
    auth: str = "none"
    notes: str = ""


@dataclass(frozen=True)
class HttpResponse:
    """Minimal response object adapters consume."""

    status: int
    body: str


@dataclass
class SiteResult:
    """One site's fetch outcome; failures isolate to their own entry."""

    site: Site
    ok: bool
    postings: list[Posting] = field(default_factory=list)
    error: str | None = None


@dataclass
class FetchReport:
    """All sites' results plus the gated, deduped candidate list."""

    site_results: list[SiteResult] = field(default_factory=list)
    candidates: list[Posting] = field(default_factory=list)


def load_sites(path: str) -> list[Site]:
    """Parse a sites.toml ([[site]] entries) into Site objects."""
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SitesError(f"cannot read sites file {path}: {exc}") from exc
    sites = []
    for entry in raw.get("site", []):
        missing = [k for k in ("name", "url", "adapter") if k not in entry]
        if missing:
            raise SitesError(
                f"site entry missing keys: {', '.join(missing)} ({entry})"
            )
        sites.append(Site(
            name=entry["name"],
            url=entry["url"],
            adapter=entry["adapter"],
            auth=entry.get("auth", "none"),
            notes=entry.get("notes", ""),
        ))
    return sites


def site_has_remote_filter(site: Site) -> bool:
    """True when the URL carries filter params OR the adapter self-filters.

    REMOTE_SELF_FILTERED adapters enforce remote per-posting inside
    list_postings (a stronger deterministic signal than any URL param),
    so the URL-param guard does not apply to them.
    """
    adapter = adapter_registry.get_adapter(site.adapter)
    if getattr(adapter, "REMOTE_SELF_FILTERED", False):
        return True
    params = getattr(adapter, "REMOTE_FILTER_PARAMS", ())
    return any(param in site.url for param in params)


def default_http_get(url, headers=None, data=None) -> HttpResponse:
    """urllib-based fetch; HTTPError bodies surface as their status."""
    request = Request(
        url,
        headers=headers or {},
        data=data,
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return HttpResponse(response.status,
                                response.read().decode("utf-8", "replace"))
    except Exception as exc:  # pylint: disable=broad-exception-caught  # boundary: adapters see errors as status/body, never raise
        status = getattr(exc, "code", 0)
        return HttpResponse(status, str(exc))


def fetch_all(sites: list[Site], cfg, state_dir, http_get=default_http_get,
              sleep=time.sleep) -> FetchReport:
    """Fetch every site, gate, dedup, and fetch JD text for survivors."""
    report = FetchReport()
    now = datetime.now(timezone.utc)
    _fetch_sites(sites, http_get, report)
    applied = ledger.applied_ids(state_dir)
    pairs = _gate_postings(report, applied, now)
    report.candidates = dedup([posting for _, posting in pairs])
    site_of = {posting.posting_id: site for site, posting in pairs}
    _fetch_jds(report.candidates, site_of, http_get, sleep,
               cfg.request_delay_seconds)
    return report


def _fetch_sites(sites: list[Site], http_get, report: FetchReport) -> None:
    """List postings per site; any failure isolates to that site's result."""
    for site in sites:
        try:
            adapter = adapter_registry.get_adapter(site.adapter)
            postings = adapter.list_postings(site, http_get)
            report.site_results.append(SiteResult(site, True, postings))
        except Exception as exc:  # pylint: disable=broad-exception-caught  # boundary: per-site isolation (spec §7)
            report.site_results.append(
                SiteResult(site, False, [], f"{type(exc).__name__}: {exc}"))


def _gate_postings(report: FetchReport, applied: set[str],
                   now: datetime) -> list[tuple[Site, Posting]]:
    """Applied-exclusion, strict 24h, date/remote guards (spec §2)."""
    pairs: list[tuple[Site, Posting]] = []
    for result in report.site_results:
        if not result.ok:
            continue
        remote_guard = site_has_remote_filter(result.site)
        for posting in result.postings:
            if posting.posting_id in applied:
                continue
            if posting.date_confidence == "timestamp":
                if not is_within_24h(posting.posted_at, now):
                    continue
            elif posting.date_confidence == "none":
                posting.review_flags.append(REVIEW_FLAG_DATE)
            if not remote_guard:
                posting.review_flags.append(REVIEW_FLAG_REMOTE)
            pairs.append((result.site, posting))
    return pairs


def _fetch_jds(candidates: list[Posting], site_of: dict, http_get, sleep,
               delay_seconds: float) -> None:
    """Fetch JD text per candidate, spacing same-site requests by delay."""
    last_call: dict[str, float] = {}
    for posting in candidates:
        site = site_of[posting.posting_id]
        _pace(last_call, site.name, sleep, delay_seconds)
        try:
            posting.jd_text = adapter_registry.get_adapter(
                site.adapter).fetch_jd(site, posting, http_get)
        except Exception:  # pylint: disable=broad-exception-caught  # boundary: JD loss -> review flag, never a run abort
            posting.jd_text = None
            posting.review_flags.append(REVIEW_FLAG_JD)


def _pace(last_call: dict[str, float], site_name: str, sleep,
          delay_seconds: float) -> None:
    """Sleep just enough to keep delay_seconds between same-site requests."""
    now = time.monotonic()
    previous = last_call.get(site_name)
    if previous is not None and delay_seconds > 0:
        wait = delay_seconds - (now - previous)
        if wait > 0:
            sleep(wait)
    last_call[site_name] = time.monotonic()
