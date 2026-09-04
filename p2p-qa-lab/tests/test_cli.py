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
        capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    report = json.loads(out.read_text())
    assert set(report.keys()) == {"api_url", "happy_path", "adversarial",
                                  "integration_issues", "summary"}
    assert report["happy_path"]["status"] == "INCOMPLETE"  # explorer skipped
    assert any(a["status"] in ("HELD", "BREACHED") for a in report["adversarial"])