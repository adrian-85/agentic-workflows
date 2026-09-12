# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.
# import-outside-toplevel: live tests guard heavy imports at runtime.

import json
from p2p_qa import judge


def test_report_schema_exact():
    report = judge.build_report(judge.ReportInputs(
        "http://x", [], [], [], "happy path completed; all six guardrails HELD."))
    assert set(report.keys()) == {"api_url", "happy_path", "adversarial",
                                  "integration_issues", "summary"}
    assert report["happy_path"]["status"] == "PASS"
    assert report["adversarial"] == []
    json.dumps(report)  # serializable


def test_report_happy_path_incomplete_when_no_approve():
    report = judge.build_report(judge.ReportInputs(
        "http://x", [], [], [], "no approve reached", happy_status="INCOMPLETE"))
    assert report["happy_path"]["status"] == "INCOMPLETE"


def test_report_carries_steps_findings_and_issues():
    from p2p_qa.client import StepRecord
    from p2p_qa.judge import Finding
    steps = [StepRecord(name="approve_invoice", method="POST", url="/invoices/1/approve",
                        request_payload=None, status_code=200,
                        response_payload={"id": 1, "status": "approved"},
                        interpretation="GL balanced")]
    report = judge.build_report(judge.ReportInputs(
        "http://x", steps, [Finding("gl_balance", "HELD")],
        [{"endpoint": "POST /invoices", "field": "gl_post", "severity": "warn"}],
        "summary"))
    assert report["happy_path"]["steps"][0]["name"] == "approve_invoice"
    assert report["adversarial"][0]["rule"] == "gl_balance"
    assert len(report["integration_issues"]) == 1
