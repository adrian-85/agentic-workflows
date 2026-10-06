"""Config loading for the job-search workflow.

Parses the TOML config (real values live in gitignored config.toml; the
committed config.example.toml carries placeholders only) and computes the
criteria_version hash stamped on every ledger event so decision diffs
across criteria tweaks stay attributable (spec §1, §5).
"""

import hashlib
import json
import tomllib
from dataclasses import dataclass

REQUIRED_KEYS = ("preferred_min", "acceptable_min")
REQUIRED_CRITERIA = ("relevance_domains", "ethics_rule")
REQUIRED_PROFILE = ("relevance_profile_path",)
CRITERIA_BLOCK_FIELDS = (
    "preferred_min",
    "acceptable_min",
    "hours_per_year",
    "relevance_domains",
    "ethics_rule",
)


class ConfigError(Exception):
    """Raised when a config file is missing required keys or malformed."""


@dataclass(frozen=True)
# R0902 disabled: a config value object legitimately holds one attribute per
# config knob (10); splitting it would add indirection the spec's §1 config
# block does not have.
# Upstream pylint#9058 tracks a method-less-dataclass exemption for
# R0902; drop this pragma when the repo's pinned pylint ships it.
class Config:  # pylint: disable=too-many-instance-attributes
    """Workflow configuration; personal values only ever live in config.toml."""

    preferred_min: int
    acceptable_min: int
    relevance_profile_path: str
    relevance_domains: str
    ethics_rule: str
    hours_per_year: int = 2080
    currency: str = "USD"
    linkedin_export_path: str | None = None
    max_parallel_tailoring: int = 3
    request_delay_seconds: float = 1.5


def load_config(path: str) -> Config:
    """Load and validate a config file into a Config."""
    try:
        with open(path, "rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc

    pay = _section(raw, "pay")
    for key in REQUIRED_KEYS:
        _require(pay, key, "pay")
    if pay["preferred_min"] < pay["acceptable_min"]:
        raise ConfigError("pay.preferred_min must be >= pay.acceptable_min")

    profile = _section(raw, "profile")
    for key in REQUIRED_PROFILE:
        _require(profile, key, "profile")

    criteria = _section(raw, "criteria")
    for key in REQUIRED_CRITERIA:
        _require(criteria, key, "criteria")

    linkedin_export = profile.get("linkedin_export_path") or None
    return Config(
        preferred_min=pay["preferred_min"],
        acceptable_min=pay["acceptable_min"],
        relevance_profile_path=profile["relevance_profile_path"],
        linkedin_export_path=linkedin_export,
        relevance_domains=criteria["relevance_domains"],
        ethics_rule=criteria["ethics_rule"],
        hours_per_year=pay.get("hours_per_year", 2080),
        currency=pay.get("currency", "USD"),
        max_parallel_tailoring=_section(raw, "dispatch").get(
            "max_parallel_tailoring", 3
        ),
        request_delay_seconds=_section(raw, "dispatch").get(
            "request_delay_seconds", 1.5
        ),
    )


def criteria_hash(cfg: Config) -> str:
    """Stable short hash of the criteria block (the decision-shaping values)."""
    block = {field: getattr(cfg, field) for field in CRITERIA_BLOCK_FIELDS}
    canonical = json.dumps(block, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _section(raw: dict, name: str) -> dict:
    section = raw.get(name)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    return section


def _require(section: dict, key: str, section_name: str) -> None:
    if key not in section:
        raise ConfigError(f"missing required config key: [{section_name}].{key}")
