"""Auth plumbing: saved cURL exports -> authenticated http_get (spec §8).

Mirrors resume-tailoring ats_check.py's proven pattern: the user saves
'Copy as cURL' exports from a logged-in browser session into
auth/<site name>/curl.txt (gitignored, mode 600); those headers replay
on every request to the site. A 401/403 raises AuthExpired naming the
site so the fetch layer isolates it and the report can say exactly which
site needs re-exported credentials.
"""

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class AuthExpired(Exception):
    """The site's saved session no longer authenticates."""

    def __init__(self, site_name: str):
        super().__init__(
            f"auth expired for {site_name}: re-export cURL from a "
            "logged-in session")
        self.site_name = site_name


@dataclass
class RequestSpec:
    """One parsed cURL export: method, url, headers, body."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    data: str | None = None


def parse_curl_exports(path: Path) -> list[RequestSpec]:
    """Parse 'Copy as cURL' blocks (one per line starting with 'curl ')."""
    text = Path(path).read_text(encoding="utf-8")
    blocks = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("curl "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    return [_parse_block(block) for block in blocks]


def build_authed_http_get(site, auth_dir: Path, base_get):
    """http_get wrapper replaying the site's saved headers.

    Exports live at auth/<site name>/curl.txt; the first export for the
    site's host supplies headers for every request. 401/403 raises
    AuthExpired(site.name).
    """
    exports_path = Path(auth_dir) / site.name / "curl.txt"
    specs = parse_curl_exports(exports_path)
    host_headers = {}
    for spec in specs:
        if _same_host(spec.url, site.url):
            host_headers = spec.headers
            break
    if not host_headers and specs:
        host_headers = specs[0].headers

    def authed_get(url, headers=None, data=None):
        merged = dict(host_headers)
        if headers:
            merged.update(headers)
        response = base_get(url, headers=merged, data=data)
        if response.status in (401, 403):
            raise AuthExpired(site.name)
        return response

    return authed_get


def _same_host(first: str, second: str) -> bool:
    """True when both URLs share a host."""
    return urlsplit(first).netloc == urlsplit(second).netloc


def _parse_block(lines: list[str]) -> RequestSpec:
    """One cURL block to a RequestSpec."""
    tokens = shlex.split(" ".join(lines))
    url = ""
    method = None
    data = None
    headers: dict[str, str] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "curl":
            index += 1
            continue
        if token in ("-H", "--header"):
            value = tokens[index + 1]
            name, _, header_value = value.partition(":")
            headers[name.strip().lower()] = header_value.strip()
            index += 2
        elif token in ("--data-raw", "--data", "-d"):
            data = tokens[index + 1]
            method = method or "POST"
            index += 2
        elif token in ("-X", "--request"):
            method = tokens[index + 1]
            index += 2
        elif token.startswith("-"):
            index += 2 if index + 1 < len(tokens) and not tokens[
                    index + 1].startswith("-") else 1
        elif not url:
            url = token
            index += 1
        else:
            index += 1
    return RequestSpec(method=method or "GET", url=url,
                       headers=headers, data=data)
