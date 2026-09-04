import pytest
from p2p_qa.adversarial import run_baseline
from p2p_qa.client import P2PClient

pytestmark = pytest.mark.usefixtures("p2p_api")

FINANCIAL_RULES = ("overpayment_protection", "match_gate", "partial_receipt_flag",
                   "inactive_vendor_gate", "gl_balance", "duplicate_detection")
SECURITY_RULES = ("authorization", "pii_exposure", "mis_credit", "injection",
                  "destructive_ops")


def _run(request):
    base = request.getfixturevalue("p2p_api")
    return run_baseline(P2PClient(base))


def test_all_rules_held_on_clean(request):
    results = _run(request)
    by_rule = {r.rule: r.status for r in results}
    # clean profile is a realistic messy legacy API: authless -> authorization
    # + PII exposure findings; no input sanitization -> injection finding. All
    # other rules (incl. all financial + mis_credit/destructive/data) hold.
    breached = {"authorization", "pii_exposure", "injection"}
    for rule in FINANCIAL_RULES + SECURITY_RULES + ("data_integrity",):
        expected = "BREACHED" if rule in breached else "HELD"
        assert by_rule.get(rule) == expected, f"{rule}: expected {expected}, got {by_rule}"


@pytest.mark.require_auth
@pytest.mark.parametrize("p2p_api", ["clean"], indirect=True)
def test_authorization_held_when_auth_required(request):
    results = _run(request)
    by_rule = {r.rule: r.status for r in results}
    assert by_rule.get("authorization") == "HELD"


@pytest.mark.parametrize("p2p_api", ["overpayment_leak"], indirect=True)
def test_overpayment_breached_on_leak_profile(request):
    results = _run(request)
    assert any(r.rule == "overpayment_protection" and r.status == "BREACHED"
               for r in results)


@pytest.mark.parametrize("p2p_api", ["pii_leak"], indirect=True)
def test_pii_breached_on_leak_profile(request):
    results = _run(request)
    assert any(r.rule == "pii_exposure" and r.status == "BREACHED" for r in results)


@pytest.mark.parametrize("p2p_api", ["gl_unbalanced"], indirect=True)
def test_gl_breached_on_leak_profile(request):
    results = _run(request)
    assert any(r.rule == "gl_balance" and r.status == "BREACHED" for r in results)


@pytest.mark.parametrize("p2p_api", ["duplicate_leak"], indirect=True)
def test_duplicate_breached_on_leak_profile(request):
    results = _run(request)
    assert any(r.rule == "duplicate_detection" and r.status == "BREACHED"
               for r in results)


@pytest.mark.parametrize("p2p_api", ["partial_flag_missing"], indirect=True)
def test_partial_flag_breached_on_leak_profile(request):
    results = _run(request)
    assert any(r.rule == "partial_receipt_flag" and r.status == "BREACHED"
               for r in results)