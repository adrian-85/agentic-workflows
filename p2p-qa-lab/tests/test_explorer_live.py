# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel,wrong-import-position
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.
# import-outside-toplevel/wrong-import-position: live tests guard heavy imports at runtime;
#   flat-namespace tests need the sys.path bootstrap before sibling imports.

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
