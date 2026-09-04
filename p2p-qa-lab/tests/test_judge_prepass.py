import pytest
from p2p_qa import judge
from p2p_qa.adversarial import ProbeResult
from p2p_qa.client import StepRecord


def _rec(name, status, payload):
    return StepRecord(name=name, method="POST", url="/x", request_payload={},
                      status_code=status, response_payload=payload)


def test_prepass_detects_overpayment_from_log():
    steps = [
        _rec("match_invoice", 200, {"id": 9, "status": "matched",
              "match": {"status": "matched", "partial": True,
                        "received_value_cents": 1000,
                        "invoice_amount_cents": 5000, "variance_cents": -4000}})
    ]
    findings = judge.run_prepass(steps, [])
    assert findings[0].rule == "overpayment_protection"
    assert findings[0].status == "BREACHED"


def test_prepass_detects_unmatched_approve():
    steps = [_rec("approve_invoice", 200, {"id": 3, "status": "approved"})]
    f = next(x for x in judge.run_prepass(steps, []) if x.rule == "match_gate")
    assert f.status == "BREACHED"


def test_prepass_gl_balance():
    steps = [_rec("approve_invoice", 200, {"id": 4, "status": "approved",
        "gl_post": {"entries": [{"account": "expense", "debit_cents": 1000,
                                  "credit_cents": 0},
                                 {"account": "ap", "debit_cents": 0,
                                  "credit_cents": 999}]}})]
    f = next(x for x in judge.run_prepass(steps, []) if x.rule == "gl_balance")
    assert f.status == "BREACHED"


def test_prepass_uses_baseline_for_security_rules():
    baseline = [ProbeResult("pii_exposure", "probe_pii", "BREACHED",
                            {"k": "password"}, "leaked")]
    f = next(x for x in judge.run_prepass([], baseline) if x.rule == "pii_exposure")
    assert f.status == "BREACHED"


def test_prepass_notes_untested_rules():
    findings = judge.run_prepass([], [])
    assert all(f.status == "NOT_TESTED" for f in findings)
    assert [f.rule for f in findings] == list(judge.config.INVARIANT_NAMES)


def test_prepass_data_integrity_from_steps():
    steps = [
        StepRecord(name="create_vendor", method="POST", url="/vendors",
                   request_payload={"name": "GhostCo", "status": "active"},
                   status_code=201, response_payload={"id": 7, "name": "GhostCo", "status": "active"}),
        StepRecord(name="get_vendor", method="GET", url="/vendors/7",
                   request_payload=None, status_code=404, response_payload={"detail": "no"}),
    ]
    f = next(x for x in judge.run_prepass(steps, []) if x.rule == "data_integrity")
    assert f.status == "BREACHED"