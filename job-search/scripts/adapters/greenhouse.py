"""Greenhouse adapter — boards-api.greenhouse.io/v1 (public, no auth).

The list request uses ?content=true so each posting carries its JD
inline (entity-escaped HTML, converted to text). Date confidence is
timestamp: first_published/updated_at are absolute ISO datetimes.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from adapters import AdapterFetchError, fetch_json, html_to_text, parse_iso_time
from postings import Posting, canonical_id

SOURCE = "greenhouse"
REMOTE_FILTER_PARAMS = ("location=", "remote")
REMOTE_SELF_FILTERED = True
API_BASE = "https://boards-api.greenhouse.io/v1/boards"




def board_token(url: str) -> str:
    """Extract the board token from a boards/jobs UI or API URL."""
    segments = [seg for seg in urlsplit(url).path.split("/") if seg]
    if "boards" in segments:
        return segments[segments.index("boards") + 1]
    if not segments:
        raise AdapterFetchError(f"no board token in url: {url}")
    return segments[0]


def list_postings(site, http_get) -> list[Posting]:
    """List the board's jobs as normalized postings with inline JD text."""
    token = board_token(site.url)
    payload = fetch_json(f"{API_BASE}/{token}/jobs?content=true",
                         http_get, f"greenhouse board {token}")
    now = datetime.now(timezone.utc)
    postings = []
    for job in payload.get("jobs", []):
        location_name = (job.get("location") or {}).get("name", "")
        if "remote" not in location_name.lower():
            continue
        if not _in_us(location_name):
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
    job = fetch_json(f"{API_BASE}/{token}/jobs/{ext_id}", http_get,
                     f"greenhouse job {ext_id}")
    return _content_text(job.get("content"))


_US_TOKENS = frozenset({
    "us", "usa", "united states", "dc", "d.c.",
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
})


def _in_us(location_name: str) -> bool:
    """US-remote per the posting's own location segments.

    Boards segment multi-location names with ';' or '|' (e.g. GitLab's
    "Remote, Canada; Remote, United States"). A segment ending in a US
    token (state abbreviation, DC, US/USA/United States) makes the job
    US-eligible; every segment pinned to a non-US country drops it. A
    segment with no country signal (bare "Remote") is neutral.
    """
    non_us = False
    for segment in re.split(r"[;|]", location_name):
        segment = segment.strip()
        if not segment:
            continue
        if "," in segment:
            if segment.rsplit(",", 1)[-1].strip().lower() in _US_TOKENS:
                return True
            non_us = True
        else:
            return True
    return not non_us


_US_WORD_RE = re.compile(r"\b(?:us|usa)\b", re.I)
_US_ABBR_RE = re.compile(
    r"\b(?:dc|d\.c\.|al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|ia|"
    r"ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|"
    r"or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)\.?\s*$", re.I)


def _in_us(location_name: str) -> bool:
    """US-remote per the posting's own location segments.

    Boards segment multi-location names with ';' or '|' (e.g. GitLab's
    "Remote, Canada; Remote, United States"). A segment naming the US
    ("Remote, United States", "...CA", "US - Remote", "North America")
    makes the job US-eligible; a segment whose remaining words (after
    "remote") carry no US token drops it; a bare "Remote" has no country
    signal and is neutral.
    """
    non_us = False
    for segment in re.split(r"[;|]", location_name):
        low = segment.strip().lower()
        if not low:
            continue
        if "united states" in low or "north america" in low:
            return True
        if _US_WORD_RE.search(low) or _US_ABBR_RE.search(low):
            return True
        if any(word != "remote" for word in re.findall(r"[a-z]+", low)):
            non_us = True
    return not non_us


def _content_text(content):
    """Convert entity-escaped board HTML to plain text."""
    if not content:
        return None
    return html_to_text(content) or None
