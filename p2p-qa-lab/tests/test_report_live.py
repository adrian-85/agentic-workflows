# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name,import-outside-toplevel,wrong-import-position,unused-import,redefined-outer-name,consider-using-with,multiple-imports,too-many-locals
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.
# import-outside-toplevel/wrong-import-position: live tests guard heavy imports at runtime;
#   flat-namespace tests need the sys.path bootstrap before sibling imports.
# unused-import: migrated shared fixtures leave stdlib imports unused per file.
# redefined-outer-name/consider-using-with/multiple-imports/too-many-locals:
#   test helpers alias fixture names; small one-off scaffolding is idiomatic.

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
