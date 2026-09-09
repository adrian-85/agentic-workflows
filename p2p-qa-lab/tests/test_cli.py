# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel,wrong-import-position
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.

import json
import subprocess
import sys
import pytest

pytestmark = pytest.mark.usefixtures("p2p_api")


def test_cli_run_writes_spec_report(request, tmp_path):
    base = request.getfixturevalue("p2p_api")
    out = tmp_path / "report.json"
    r = subprocess.run(
        [sys.executable, "-m", "p2p_qa", "run", "--api", base,
         "--skip-explorer", "--prepass-only", "--report", str(out)],
        capture_output=True, text=True, timeout=180, check=False)
    assert r.returncode == 0, r.stderr
    report = json.loads(out.read_text())
    assert set(report.keys()) == {"api_url", "happy_path", "adversarial",
                                  "integration_issues", "summary"}
    assert report["happy_path"]["status"] == "INCOMPLETE"  # explorer skipped
    assert any(a["status"] in ("HELD", "BREACHED") for a in report["adversarial"])
