import pytest

pytestmark = pytest.mark.live


def test_llm_summary_nonempty():
    from p2p_qa import judge
    findings = [judge.Finding("overpayment_protection", "HELD",
                              {}, "invoice <= received"),
                judge.Finding("gl_balance", "HELD", {}, "balanced"),
                judge.Finding("authorization", "BREACHED",
                              {}, "no auth layer present")]
    summ = judge.llm_summary(findings, happy_status="PASS")
    assert isinstance(summ, str) and len(summ) > 20
    # the summary must not contradict a BREACHED finding
    assert "breach" in summ.lower() or "exposure" in summ.lower() or "auth" in summ.lower()