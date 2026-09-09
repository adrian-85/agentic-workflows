# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel,wrong-import-position
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.
# line-too-long: fixture/expected strings exceed 100 chars.
# import-outside-toplevel/wrong-import-position: live tests guard heavy imports at runtime;
#   flat-namespace tests need the sys.path bootstrap before sibling imports.

import pytest

pytestmark = pytest.mark.live


def test_classify_violation_and_clean():
    from p2p_qa import dspy_judge
    # a real overpayment match response must be flagged
    assert dspy_judge.classify(
        '{"match": {"received_value_cents": 5000, "invoice_amount_cents": 5001, "'
         '"partial": true}, "status": 200}'
    ) == "VIOLATION"
    # a clean rejection must be CLEAN
    assert dspy_judge.classify(
        "400 {'detail': 'invoice exceeds received value (5001>5000)'}") == "CLEAN"


def test_classify_never_raises():
    from p2p_qa import dspy_judge
    r = dspy_judge.classify(None)
    assert r in ("VIOLATION", "CLEAN")
