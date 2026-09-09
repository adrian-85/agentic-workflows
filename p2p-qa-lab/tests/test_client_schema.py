# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel,wrong-import-position
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.

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
