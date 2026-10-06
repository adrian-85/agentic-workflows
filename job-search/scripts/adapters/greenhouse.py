"""Greenhouse adapter — boards-api.greenhouse.io/v1 (public, no auth).

The list request uses ?content=true so each posting carries its JD
inline (entity-escaped HTML, converted to text). Date confidence is
timestamp: first_published/updated_at are absolute ISO datetimes.
"""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from adapters import decode_json, html_to_text, parse_iso_time
from postings import Posting, canonical_id

SOURCE = "greenhouse"
REMOTE_FILTER_PARAMS = ("location=", "remote")
REMOTE_SELF_FILTERED = True
API_BASE = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseFetchError(RuntimeError):
    """Raised when the boards API answers non-200 or bad JSON."""


def board_token(url: str) -> str:
    """Extract the board token from a boards/jobs UI or API URL."""
    segments = [seg for seg in urlsplit(url).path.split("/") if seg]
    if "boards" in segments:
        return segments[segments.index("boards") + 1]
    if not segments:
        raise GreenhouseFetchError(f"no board token in url: {url}")
    return segments[0]


def list_postings(site, http_get) -> list[Posting]:
    """List the board's jobs as normalized postings with inline JD text."""
    token = board_token(site.url)
    response = http_get(f"{API_BASE}/{token}/jobs?content=true")
    payload = decode_json(response, f"greenhouse board {token}",
                          GreenhouseFetchError)
    now = datetime.now(timezone.utc)
    postings = []
    for job in payload.get("jobs", []):
        location_name = (job.get("location") or {}).get("name", "")
        if "remote" not in location_name.lower():
            continue
        posted_at = parse_iso_time(job.get("first_published")
                                   or job.get("updated_at"))
        postings.append(Posting(
            posting_id=canonical_id(SOURCE, str(job["id"])),
            source=SOURCE,
            url=job.get("absolute_url", site.url),
            jd_url=job.get("absolute_url", site.url),
            company=job.get("company_name") or token,
            title=job.get("title", "untitled"),
            location=location_name,
            posted_at=posted_at,
            date_confidence="timestamp" if posted_at else "none",
            pay_raw=None,
            fetched_at=now,
            jd_text=_content_text(job.get("content")),
        ))
    return postings


def fetch_jd(site, posting, http_get) -> str:
    """Serve cached list JD text, else fetch the job detail content."""
    if posting.jd_text:
        return posting.jd_text
    token = board_token(site.url)
    ext_id = posting.posting_id.split(":", 1)[1]
    response = http_get(f"{API_BASE}/{token}/jobs/{ext_id}")
    job = decode_json(response, f"greenhouse job {ext_id}",
                      GreenhouseFetchError)
    return _content_text(job.get("content"))


def _content_text(content):
    """Convert entity-escaped board HTML to plain text."""
    if not content:
        return None
    return html_to_text(content) or None
