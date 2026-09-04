"""Violation classifier — DSPy-style prompt optimization seam.

classify(response_text) -> "VIOLATION" | "CLEAN"  determines whether an API
response represents a financial-integrity violation. This is the prompt-opt
seam named in the stretch goal: today it uses a curated few-shot prompt via
our existing LLM access (no extra deps). To swap in real DSPy:

    python -m venv .venv && . .venv/bin/activate
    pip install dspy
    # then replace few-shot prompt with a dspy.Signature + Optimizer over the
    # labeled examples in _EXAMPLES below. The classify() contract stays the
    # same, so the judge/CLI need no changes.

Rules: a response is a VIOLATION if it accepts money above received value,
approves an unmatched invoice, hides a partial receipt, posts unbalanced GL,
accepts duplicates, leaks secrets, or 500s on ill-typed input. Anything that
correctly rejects (4xx with detail, guardrail held) is CLEAN.
"""

from p2p_qa import llm

_EXAMPLES = [
    # (response_text, label)
    ("{match: {received_value_cents: 5000, invoice_amount_cents: 5001, partial: true}, status: 200}", "VIOLATION"),
    ("400 {'detail': 'invoice exceeds received value (5001>5000)'}", "CLEAN"),
    ("{id: 9, status: approved, gl_post: {balanced: true}}", "VIOLATION"),
    ("{id: 9, status: approved, gl_post: {entries: [...], balanced: false}}", "VIOLATION"),
    ("400 {'detail': 'invoice must be matched before approval'}", "CLEAN"),
    ("{id: 1, status: open, invoice_number: 'INV-1', vendor_id: 1}", "CLEAN"),
    ("{id: 42, status: matched, match: {partial: false, received_value_cents: 3000}}", "VIOLATION"),
    ("500 Internal Server Error on /receive with string quantity", "VIOLATION"),
    ("{id: 7, name: 'Acme', password: 'hunter2'}", "VIOLATION"),
    ("400 {'detail': 'duplicate invoice_number'}", "CLEAN"),
]

_CLASSIFIER_SYSTEM = (
    "You classify API responses as VIOLATION or CLEAN for financial-integrity "
    "rules (overpayment, match gate, partial-receipt hiding, unbalanced GL, "
    "duplicates, secret leakage, 500-on-bad-input). Respond with exactly one "
    "word: VIOLATION or CLEAN.")


def classify(response_text: str, llm_chat=None) -> str:
    """-> "VIOLATION" | "CLEAN". Never raises; 'CLEAN' on uncertainty is NOT
    the default — ambiguity is returned as 'VIOLATION' (fail-safe) with the
    caller free to treat it as needing human review."""
    if llm_chat is None:
        llm_chat = llm.chat
    shot_block = "\n".join(f"{text} -> {label}" for text, label in _EXAMPLES)
    user = f"Labeled examples:\n{shot_block}\n\nClassify this response:\n{response_text}"
    try:
        resp = llm_chat(_CLASSIFIER_SYSTEM, [{"role": "user", "content": user}],
                        temperature=0.0)
        text = (resp.get("content") or "").strip().upper()
        if "VIOLATION" in text:
            return "VIOLATION"
        if "CLEAN" in text and "VIOLATION" not in text:
            return "CLEAN"
        return "VIOLATION"  # fail-safe on garbage output
    except Exception:
        return "VIOLATION"  # fail-safe: better to over-flag than under-flag money