import pytest
from p2p_qa.client import validate_response


def test_optional_missing_warns():
    issues = validate_response("GET /vendors", [{"id": 1, "name": "A", "status": "active"}])
    assert issues and all(i.severity == "warn" for i in issues)
    assert any("contact_email" in i.field for i in issues)


def test_required_missing_breaks():
    issues = validate_response("POST /vendors", {"id": 1, "name": "A"})  # missing status
    assert any(i.severity == "break" and i.field == "status" for i in issues)


def test_error_payload_no_crash():
    issues = validate_response("GET /vendors", {"detail": "boom"})  # not a list
    assert isinstance(issues, list)