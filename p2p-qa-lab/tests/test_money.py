# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel,wrong-import-position
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.

import pytest
from p2p_qa import money


def test_parse_cents_int_passthrough():
    assert money.parse_cents(1234) == 1234


def test_parse_cents_string():
    assert money.parse_cents("12.34") == 1234
    assert money.parse_cents("$12.34") == 1234
    assert money.parse_cents("0") == 0


def test_parse_cents_rejects_garbage():
    with pytest.raises(ValueError):
        money.parse_cents("abc")
    with pytest.raises(ValueError):
        money.parse_cents(None)


def test_as_cents_str_roundtrip():
    assert money.as_cents_str(1234) == "12.34"
    assert money.as_cents_str(-5) == "-0.05"


def test_received_value_cents_sums_exactly():
    lines = [
        {"unit_price_cents": 1000, "quantity_received": 3},
        {"unit_price_cents": 250, "quantity_received": 1},
    ]
    assert money.received_value_cents(lines) == 3250


def test_line_value_cents_exact():
    assert money.line_value_cents(333, 3) == 999


def test_fmt_cents_negative_and_zero():
    assert money.fmt_cents(0) == "$0.00"
    assert money.fmt_cents(1234) == "$12.34"
    assert money.fmt_cents(-50) == "-$0.50"
