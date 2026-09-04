import pytest
from p2p_qa import stress


def test_generate_po_plan_shapes():
    plans = stress.generate_po_plan(seed=1, n=5)
    assert len(plans) == 5
    for p in plans:
        assert p["vendor_name"].startswith("StressVendor")
        assert p["line_items"][0]["quantity"] >= 1
        assert p["line_items"][0]["unit_price_cents"] > 0
        assert 0 <= p["receipt_fraction"] <= 1
        assert isinstance(p["invoice_mismatch"], str)
        # same seed -> same plans (deterministic)
    assert stress.generate_po_plan(seed=1, n=5) == plans


def test_stress_clean_all_held():
    res = stress.run_stress(seed=1, bug_profile="clean")
    assert res["total"] == 50
    for rule, rate in res["failure_rate"].items():
        assert rate == 0.0, f"{rule} breached on clean: {rate}"


def test_stress_overpayment_leak_shows_failures():
    res = stress.run_stress(seed=1, bug_profile="overpayment_leak")
    assert res["failure_rate"]["overpayment_protection"] > 0.0
    # other rules still hold on a clean-ish API
    assert res["failure_rate"]["duplicate_detection"] == 0.0