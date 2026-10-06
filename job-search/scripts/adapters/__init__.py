"""Adapter package: registry + lazy import for platform adapters.

An adapter is any object exposing the adapter contract (spec §2):
    list_postings(site, http_get) -> list[Posting]
    fetch_jd(site, posting, http_get) -> str
    REMOTE_FILTER_PARAMS: tuple[str, ...]
Real adapters are modules in this package (adapters/<name>.py); tests may
register instances directly. get_adapter checks the registry first, then
lazily imports adapters/<name>.
"""

import importlib
from pathlib import Path

REGISTRY: dict[str, object] = {}
_CONTRACT_ATTRS = ("list_postings", "fetch_jd", "REMOTE_FILTER_PARAMS")


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
