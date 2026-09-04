import pytest

pytestmark = pytest.mark.live


@pytest.mark.usefixtures("p2p_api")
def test_explorer_completes_happy_path(request):
    from p2p_qa.client import P2PClient, StepLogger
    from p2p_qa.explorer import run_explorer
    base = request.getfixturevalue("p2p_api")
    client = P2PClient(base)
    logger = StepLogger("/tmp/p2p_explorer_live.jsonl")
    try:
        summary = run_explorer(client, logger)
    finally:
        logger.close()
    assert summary["status"] == "PASS", summary
    assert summary["flow"] == ["vendor", "po", "submit", "receive", "invoice", "match", "approve"]
    # every step should carry an interpretation the LLM wrote
    assert summary["interpretations"], "expected at least one interpretation"