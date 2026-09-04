"""Shared constants across the P2P QA lab. No secrets live here."""

# Mock API
BUG_PROFILES: tuple[str, ...] = (
    "clean",
    "overpayment_leak",
    "duplicate_leak",
    "gl_unbalanced",
    "partial_flag_missing",
    "phantom_write",
    "post_get_mismatch",
    "pii_leak",
)
SEED_TOKEN = "dev-token-1234"

# LLM
MODEL = "openrouter/auto"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
TIMEOUT_S = 10
RETRY_BACKOFF_S: list[float] = [1, 2, 4, 8, 16]

# Agent limits
MAX_EXPLORER_STEPS = 40
MAX_HACKER_PROBES = 20

# Rule slugs, in report order (financial first, then security).
INVARIANT_NAMES: tuple[str, ...] = (
    "overpayment_protection",
    "match_gate",
    "partial_receipt_flag",
    "inactive_vendor_gate",
    "gl_balance",
    "duplicate_detection",
    "authorization",
    "pii_exposure",
    "mis_credit",
    "injection",
    "destructive_ops",
    "data_integrity",
)