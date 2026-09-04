# P2P QA Lab

Agentic QA for a Purchase-to-Pay API: an **explorer** that autonomously drives
an end-to-end workflow, an **adversarial** layer that tries to break financial
and security invariants, and a **judge** that emits an auditor-style report.

## Quick start

```bash
pip install -r requirements.txt

# Full pipeline against a bundled mock (boots mock, runs explorer + baseline
# + LLM hacker + judge, writes reports/<ts>/report.json, prints narrative):
python -m p2p_qa demo --bug-profile clean

# Better bug-story demo — watch the judge flip to BREACHED:
python -m p2p_qa demo --bug-profile overpayment_leak

# Against a real API (public URL, optional token):
python -m p2p_qa run --api https://<host> --token <token>

# Fast deterministic pass (no LLM hacker / LLM summary):
python -m p2p_qa demo --prepass-only
```

## Commands

| Command | Meaning |
|---|---|
| `python -m p2p_qa run --api <url> [--token] [--skip-explorer] [--prepass-only] [--report path]` | Run all agents against a live API |
| `python -m p2p_qa demo [--bug-profile X] [--require-auth] [--port]` | Boot mock + run + tear down |
| `python -m p2p_qa stress [--seed N] [--n 50] [--bug-profile X]` | 50-PO synthetic stress test — per-rule failure rate |
| `python -m p2p_qa.mock_api --host 0.0.0.0 --port 8000 [--bug-profile X] [--require-auth]` | Mock standalone |

`--bug-profile` values: `clean`, `overpayment_leak`, `duplicate_leak`,
`gl_unbalanced`, `partial_flag_missing`, `phantom_write`, `post_get_mismatch`,
`pii_leak`. `--require-auth` gates with a Bearer token (`dev-token-1234`).

## Architecture

```
cli.py          — run|demo orchestration, atomic reports, narrative
explorer.py     — LLM ReAct loop: plan -> discover -> construct (double-verify) -> verify
adversarial.py  — deterministic baseline (12 probes) + open-ended LLM hacker agent
judge.py        — deterministic pre-pass (recomputes invariants) + LLM summary + report
client.py       — schema-tolerant httpx wrapper, StepRecord log, drift surfacing
llm.py          — OpenRouter via openai SDK, retry+backoff, fail-loud
mock_api.py     — FastAPI mock, integer cents, 8 bug profiles, optional auth
money.py        — integer-cents money helpers (no floats)
```

## Why it's built this way

- **No LangChain/LangGraph** — a raw tool-calling loop you can explain line by
  line, with explicit control over retries, context bounds, and history.
- **Money is integer cents everywhere** — exact equality, off-by-one is the
  game.
- **Judge is two-stage** — deterministic recomputation is the authority; the
  LLM interprets within it, never against it.
- **Double verification** — create responses are never trusted alone; every
  create is GET-proven (catches phantom writes and POST/GET mismatches).
- **Schema drift is surfaced, never hidden** — required-field drift lands in
  `integration_issues` even when the agents adapt and the demo completes.

## Deliverables

- `reports/<ts>/report.json` — the spec report:
  `happy_path{status,steps}` + `adversarial[{rule,status,evidence}]` +
  `integration_issues` + `summary`.
- `runs`/`reports` are gitignored (outputs stay local).
- `prompts/agent-prompts.md` — the agents' system prompts (explorer, hacker,
  judge, loop context), verbatim from code.

## Tests

```bash
python -m pytest tests/ -q             # unit/integration (no LLM)
python -m pytest -m live -q            # live LLM agent tests (needs OPENAI_API_KEY
                                       #   or ~/.pi/agent/auth.json with openrouter.key)
```

