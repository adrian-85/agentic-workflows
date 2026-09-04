"""Integer-cents money helpers. No floats anywhere for amounts."""

import re

_AMOUNT_RE = re.compile(r"^[^0-9+-]*(-)?(?:(\d+)(?:\.(\d{1,2}))?|\.(\d{1,2}))$")


def parse_cents(value: int | str) -> int:
    """Parse an int (already cents) or a string like '12.34' / '$12.34' / '-0.05'."""
    if isinstance(value, bool):
        raise ValueError(f"not a money value: {value!r}")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError(f"not a money value: {value!r}")
    m = _AMOUNT_RE.match(value.strip())
    if not m:
        raise ValueError(f"not a money value: {value!r}")
    neg = m.group(1) == "-"
    dollars = int(m.group(2) or 0)
    frac = m.group(3) or m.group(4) or "0"
    frac = frac.ljust(2, "0")[:2]
    cents = dollars * 100 + int(frac)
    return -cents if neg else cents


def as_cents_str(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    a = abs(cents)
    return f"{sign}{a // 100}.{a % 100:02d}"


def line_value_cents(unit_price_cents: int, quantity: int) -> int:
    return unit_price_cents * quantity


def received_value_cents(lines: list[dict]) -> int:
    return sum(line_value_cents(l["unit_price_cents"], l["quantity_received"]) for l in lines)


def fmt_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    a = abs(cents)
    return f"{sign}${a // 100}.{a % 100:02d}"