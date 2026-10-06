"""Adapter package: registry + lazy import for platform adapters.

An adapter is any object exposing the adapter contract (spec §2):
    list_postings(site, http_get) -> list[Posting]
    fetch_jd(site, posting, http_get) -> str
    REMOTE_FILTER_PARAMS: tuple[str, ...]
Real adapters are modules in this package (adapters/<name>.py); tests may
register instances directly. get_adapter checks the registry first, then
lazily imports adapters/<name>.
"""

import html
import importlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

REGISTRY: dict[str, object] = {}
_CONTRACT_ATTRS = ("list_postings", "fetch_jd", "REMOTE_FILTER_PARAMS")

_SKIP_TAGS = ("script", "style")
_BREAK_TAGS = ("br", "p", "div", "li", "ul", "ol", "tr", "table",
              "h1", "h2", "h3", "h4", "h5", "h6")


class AdapterError(Exception):
    """Unknown or contract-violating adapter."""


def register(name: str, adapter: object) -> None:
    """Register an adapter object (tests) — real ones self-register by file."""
    REGISTRY[name] = adapter


def get_adapter(name: str) -> object:
    """Registry lookup, then lazy import of adapters.<name>."""
    if name in REGISTRY:
        return REGISTRY[name]
    try:
        module = importlib.import_module(f"adapters.{name}")
    except ImportError as exc:
        raise AdapterError(f"unknown adapter: {name}") from exc
    _validate(name, module)
    REGISTRY[name] = module
    return module


def _validate(name: str, adapter: object) -> None:
    missing = [attr for attr in _CONTRACT_ATTRS if not hasattr(adapter, attr)]
    if missing:
        raise AdapterError(
            f"adapter '{name}' missing contract attrs: {', '.join(missing)}"
        )


def available() -> list[str]:
    """Adapter names available as package modules (plus test registrations)."""
    names = {
        path.stem for path in Path(__file__).parent.glob("*.py")
        if path.stem != "__init__"
    }
    return sorted(names | set(REGISTRY))


def parse_iso_time(raw):
    """ISO datetime (with offset) to aware datetime; None on failure."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def decode_json(response, what: str, error_class):
    """Decode a JSON body, raising error_class on non-200 or bad JSON."""
    if response.status != 200:
        raise error_class(f"{what}: HTTP {response.status}")
    try:
        return json.loads(response.body)
    except json.JSONDecodeError as exc:
        raise error_class(f"{what}: bad JSON: {exc}") from exc


class _TextExtractor(HTMLParser):
    """Collects text content, dropping script/style and breaking on blocks."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        """Enter skip regions and emit line breaks for block tags."""
        del attrs
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        """Leave skip regions and break after block tags."""
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in _BREAK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        """Keep text outside skip regions."""
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    """HTML (possibly entity-escaped) to normalized plain text."""
    parser = _TextExtractor()
    parser.feed(html.unescape(raw))
    lines = (re.sub(r"\s+", " ", line).strip()
             for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)
