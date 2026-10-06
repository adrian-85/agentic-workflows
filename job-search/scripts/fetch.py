"""Fetch framework: sites loader, adapter dispatch, gates, isolation.

Data flow (spec §2): adapters normalize postings; fetch_all applies the
deterministic gates — applied-exclusion, strict 24h, date-confidence and
remote-filter guards — dedups across sites, then fetches JD text for the
survivors. Per-site failures isolate; requests to the same site observe
cfg.request_delay_seconds.
"""

import time
import tomllib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import adapters as adapter_registry
import auth
import ledger
from postings import Posting, dedup, is_within_24h

HTTP_TIMEOUT_SECONDS = 30
REVIEW_FLAG_DATE = "date-unverified"
REVIEW_FLAG_REMOTE = "site-url-lacks-remote-us-filter"
REVIEW_FLAG_JD = "jd-fetch-failed"
AUTH_DIR_NAME = "auth"


class SitesError(Exception):
    """Raised when a sites file is malformed."""


@dataclass(frozen=True)
class FetchSeams:
    """Test injection points for fetch_all (defaults hit the network).

    http_get: request callable; sleep: pacing callable; auth_dir: where
    curl-feed sites find their saved cURL exports.
    """

    http_get: object = None
    sleep: object = None
    auth_dir: Path | None = None

    def resolved(self):
        """Seams with defaults filled in."""
        return FetchSeams(
            http_get=self.http_get or default_http_get,
            sleep=self.sleep or time.sleep,
            auth_dir=self.auth_dir,
        )


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


def fetch_all(sites: list[Site], cfg, state_dir,
              seams: FetchSeams | None = None) -> FetchReport:
    """Fetch every site, gate, dedup, and fetch JD text for survivors.

    curl-feed sites get an auth-wrapped http_get built from their saved
    cURL exports (auth_dir defaults to the workflow root's auth/).
    """
    seams = (seams or FetchSeams()).resolved()
    if seams.auth_dir is None:
        seams = replace(seams, auth_dir=Path(__file__).resolve().parent.parent
                        / AUTH_DIR_NAME)
    report = FetchReport()
    now = datetime.now(timezone.utc)
    _fetch_sites(sites, seams, report)
    applied = ledger.applied_ids(state_dir)
    pairs = _gate_postings(report, applied, now)
    report.candidates = dedup([posting for _, posting in pairs])
    site_of = {posting.posting_id: site for site, posting in pairs}
    _fetch_jds(report.candidates, site_of, seams,
               cfg.request_delay_seconds)
    return report


def _site_http_get(site: Site, seams: FetchSeams):
    """Wrap the seam's http_get with the site's saved session."""
    if site.auth != "curl-feed":
        return seams.http_get
    return auth.build_authed_http_get(site, seams.auth_dir, seams.http_get)


def _fetch_sites(sites: list[Site], seams: FetchSeams,
                 report: FetchReport) -> None:
    """List postings per site; any failure isolates to that site's result."""
    for site in sites:
        try:
            adapter = adapter_registry.get_adapter(site.adapter)
            postings = adapter.list_postings(site, _site_http_get(site,
                                                                  seams))
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


def _fetch_jds(candidates: list[Posting], site_of, seams: FetchSeams,
               delay_seconds: float) -> None:
    """Fetch JD text per candidate, spacing same-site requests by delay."""
    last_call: dict[str, float] = {}
    for posting in candidates:
        site = site_of[posting.posting_id]
        _pace(last_call, site.name, seams.sleep, delay_seconds)
        try:
            posting.jd_text = adapter_registry.get_adapter(
                site.adapter).fetch_jd(site, posting,
                                       _site_http_get(site, seams))
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
