"""LLM access via OpenRouter (openai SDK). Fail loud, never silently degrade."""

import json
import os
import time
from pathlib import Path

import openai

from p2p_qa import config


class AgentError(Exception):
    """Raised when the LLM cannot be reached after retries."""


_AUTH_STORE_PATH = Path.home() / ".pi" / "agent" / "auth.json"


def resolve_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    if _AUTH_STORE_PATH.exists():
        try:
            store = json.loads(_AUTH_STORE_PATH.read_text())
            key = store.get("openrouter", {}).get("key")
            if key:
                return key
        except Exception:
            pass
    raise AgentError(
        "No LLM key: set OPENAI_API_KEY (OpenRouter or OpenAI) or run inside "
        "Pi so ~/.pi/agent/auth.json is available.")


def _client() -> openai.OpenAI:
    return openai.OpenAI(api_key=resolve_key(), base_url=config.OPENROUTER_BASE)


def chat(system: str, messages: list[dict], tools: list[dict] | None = None,
         temperature: float = 0.2, model: str | None = None) -> dict:
    """One chat turn. Returns {"role","content","tool_calls"}. Retries with backoff."""
    client = _client()
    kwargs = dict(model=model or config.MODEL, temperature=temperature,
                  messages=[{"role": "system", "content": system}] + messages)
    if tools:
        kwargs["tools"] = tools
    last_err: Exception | None = None
    for delay in config.RETRY_BACKOFF_S:
        try:
            resp = client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            return {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": tc.id, "name": tc.function.name,
                     "arguments": tc.function.arguments}
                    for tc in (msg.tool_calls or [])
                ],
            }
        except openai.RateLimitError as e:
            last_err = e
        except openai.APIConnectionError as e:
            last_err = e
        except openai.APIStatusError as e:
            if e.status_code >= 500 or e.status_code == 429:
                last_err = e
            else:
                raise AgentError(f"LLM API error {e.status_code}: {e}") from e
        time.sleep(delay)
    raise AgentError(f"LLM unreachable after retries: {last_err}")