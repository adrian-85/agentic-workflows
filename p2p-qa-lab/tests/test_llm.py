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