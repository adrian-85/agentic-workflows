import json
import pytest
from p2p_qa import judge


def test_report_schema_exact():
    report = judge.build_report(
        "http://x", [], [], [],
        "happy path completed; all six guardrails HELD.")
    assert set(report.keys()) == {"api_url", "happy_path", "adversarial",
                                  "integration_issues", "summary"}
    assert report["happy_path"]["status"] == "PASS"
    assert report["adversarial"] == []
    json.dumps(report)  # serializable


def test_report_happy_path_incomplete_when_no_approve():
    report = judge.build_report("http://x", [], [], [], "no approve reached",
                                happy_status="INCOMPLETE")
    assert report["happy_path"]["status"] == "INCOMPLETE"


def test_report_carries_steps_findings_and_issues():
    from p2p_qa.client import StepRecord
    from p2p_qa.judge import Finding
    steps = [StepRecord(name="approve_invoice", method="POST", url="/invoices/1/approve",
                        request_payload=None, status_code=200,
                        response_payload={"id": 1, "status": "approved"},
                        interpretation="GL balanced")]
    report = judge.build_report(
        "http://x", steps, [Finding("gl_balance", "HELD")],
        [{"endpoint": "POST /invoices", "field": "gl_post", "severity": "warn"}],
        "summary")
    assert report["happy_path"]["steps"][0]["name"] == "approve_invoice"
    assert report["adversarial"][0]["rule"] == "gl_balance"
    assert len(report["integration_issues"]) == 1