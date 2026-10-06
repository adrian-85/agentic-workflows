"""Pay parsing and tiering (spec §4 pay rules).

Deterministic parsing of raw pay strings into a PayInfo; tiering applies
the configured thresholds. The judgment agent handles formats this parser
does not recognize — parse failures read as seen=False and default to the
acceptable tier per spec.
"""

import re
from dataclasses import dataclass

from config import Config

BASIS_RANGE_TOP = "range_top"
BASIS_POINT = "point"
BASIS_HOURLY = "hourly_x2080"
BASIS_NONE = "none"

# Currency symbols/codes this parser recognizes; anything non-USD is
# reported as such and excluded from tiering by the caller (spec §4).
_SYMBOL_CURRENCIES = {"$": "USD", "€": "EUR", "£": "GBP"}
_CODE_CURRENCIES = ("USD", "EUR", "GBP", "CAD", "AUD", "CHF")

_NUMBER_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?\s?(?P<k>[kK]\b)?"
)
_HOURLY_RE = re.compile(r"\b(?:/hr\b|/hour\b|per hour\b|hourly\b)", re.IGNORECASE)


@dataclass(frozen=True)
class PayInfo:
    """Parsed pay: what the posting said, normalized for tiering."""

    seen: bool
    currency: str = "USD"
    top: int | None = None
    annualized: int | None = None
    basis: str = BASIS_NONE


def parse_pay(raw: str | None, hours_per_year: int = 2080) -> PayInfo:
    """Parse a raw pay string into a PayInfo; unrecognized text is unseen."""
    if not raw or not raw.strip():
        return PayInfo(seen=False)

    currency = _detect_currency(raw)
    amounts = [
        _expand(match) for match in _NUMBER_RE.finditer(raw)
    ]
    amounts = [amount for amount in amounts if amount is not None]
    if not amounts:
        return PayInfo(seen=False)

    top = max(amounts)
    hourly = bool(_HOURLY_RE.search(raw))
    if hourly:
        return PayInfo(seen=True, currency=currency, top=top,
                       annualized=top * hours_per_year, basis=BASIS_HOURLY)
    basis = BASIS_RANGE_TOP if len(set(amounts)) > 1 else BASIS_POINT
    return PayInfo(seen=True, currency=currency, top=top,
                   annualized=top, basis=basis)


def tier(annualized: int | None, cfg: Config) -> str:
    """Apply thresholds: preferred >= preferred_min >= acceptable."""
    if annualized is None:
        # Spec §4: no pay listed classifies as the acceptable tier.
        return "acceptable"
    if annualized >= cfg.preferred_min:
        return "preferred"
    if annualized >= cfg.acceptable_min:
        return "acceptable"
    return "unacceptable"


def _detect_currency(raw: str) -> str:
    for symbol, code in _SYMBOL_CURRENCIES.items():
        if symbol in raw:
            return code
    upper = raw.upper()
    for code in _CODE_CURRENCIES:
        if re.search(rf"\b{code}\b", upper):
            return code
    return "USD"


def _expand(match: re.Match) -> int | None:
    """Number match to integer dollars; k-suffix multiplies by 1,000."""
    value = int(match.group("num").replace(",", ""))
    if match.group("frac"):
        value += int(round(float(f"0.{match.group('frac')}")))
    if match.group("k"):
        value *= 1000
    return value
