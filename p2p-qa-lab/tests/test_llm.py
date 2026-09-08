# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.

import pytest
from p2p_qa import llm


def test_resolve_key_from_env_or_auth_store(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    key = llm.resolve_key()
    assert isinstance(key, str) and len(key) > 10


def test_chat_raises_clear_error_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_AUTH_STORE_PATH", __import__("pathlib").Path("/nonexistent/auth.json"))
    with pytest.raises(llm.AgentError, match="OPENAI_API_KEY"):
        llm.chat("system", [{"role": "user", "content": "hi"}])
