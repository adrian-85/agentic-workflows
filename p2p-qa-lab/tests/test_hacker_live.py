import pytest

pytestmark = [pytest.mark.live, pytest.mark.usefixtures("p2p_api")]


@pytest.mark.parametrize("p2p_api", ["clean"], indirect=True)
def test_hacker_runs_probes_and_verdicts(request):
    from p2p_qa.adversarial import run_hacker
    from p2p_qa.client import P2PClient
    base = request.getfixturevalue("p2p_api")
    results = run_hacker(P2PClient(base), max_probes=20)
    assert len(results) >= 4, f"expected >=4 verdicts, got {len(results)}"
    for r in results:
        assert r.status in ("HELD", "BREACHED"), r
        assert isinstance(r.evidence, dict) and r.evidence
    # The hacker is open-ended and stochastic: it may probe financial rules,
    # robustness, or novel categories (receipt_gate, etc.). Financial coverage
    # is guaranteed by the deterministic baseline, so we only assert that it
    # actually PROBED things and emitted verifiable verdicts.
    assert any(r.probe_name == "hacker_probe" for r in results), "no hacker probes logged"