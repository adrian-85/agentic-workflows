import pytest

pytestmark = pytest.mark.live


def test_classify_violation_and_clean():
    from p2p_qa import dspy_judge
    # a real overpayment match response must be flagged
    assert dspy_judge.classify(
        '{"match": {"received_value_cents": 5000, "invoice_amount_cents": 5001, "partial": true}, "status": 200}'
    ) == "VIOLATION"
    # a clean rejection must be CLEAN
    assert dspy_judge.classify("400 {'detail': 'invoice exceeds received value (5001>5000)'}") == "CLEAN"


def test_classify_never_raises():
    from p2p_qa import dspy_judge
    r = dspy_judge.classify(None)
    assert r in ("VIOLATION", "CLEAN")