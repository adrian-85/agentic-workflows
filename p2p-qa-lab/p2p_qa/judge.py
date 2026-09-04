"""Judge — deterministic pre-pass (evidence anchors) + report assembly.

The deterministic layer replays the step log and recomputes each invariant
exactly (integer-cents math), folding in adversarial baseline results. The
LLM interpretation layer (later) must not contradict these anchors.
"""

import re
from dataclasses import dataclass, field

from p2p_qa import config
from p2p_qa.adversarial import ProbeResult
from p2p_qa.client import StepRecord


@dataclass
class Finding:
    rule: str
    status: str  # HELD | BREACHED | NOT_TESTED
    evidence: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return {"rule": self.rule, "status": self.status,
                "evidence": self.evidence, "note": self.note}


def _merge(log_status: str, base_status: str) -> str:
    """Recomputation is authoritative for detecting breaches; baseline enriches."""
    if "BREACHED" in (log_status, base_status):
        return "BREACHED"
    if "HELD" in (log_status, base_status):
        return "HELD"
    return "NOT_TESTED"


def _status_of(status_code: int | None) -> str | None:
    return "OK" if status_code is not None and status_code < 400 else "ERR"


def _vendor_status_map(steps: list[StepRecord]) -> dict[int, str]:
    out: dict[int, str] = {}
    for s in steps:
        body = s.response_payload
        if not isinstance(body, dict):
            continue
        if s.name in ("create_vendor", "get_vendor", "list_vendors"):
            if "id" in body and "status" in body:
                out[body["id"]] = body["status"]
        if s.name == "list_vendors" and isinstance(body, list):
            for v in body:
                if isinstance(v, dict) and "id" in v and "status" in v:
                    out[v["id"]] = v["status"]
    return out


def _po_context_map(steps: list[StepRecord]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for s in steps:
        body = s.response_payload
        if not isinstance(body, dict):
            continue
        if s.name in ("create_po", "get_po", "receive_po", "submit_po") and _status_of(s.status_code) == "OK":
            if "id" in body:
                out[body["id"]] = body
    return out


def _norm(s: str) -> str:
    return (s or "").casefold().replace(" ", "")


# ---------- financial rules ----------

def _rule_overpayment(steps):
    for s in steps:
        body = s.response_payload
        if s.name == "match_invoice" and isinstance(body, dict) and body.get("match"):
            m = body["match"]
            if isinstance(m, dict) and m.get("invoice_amount_cents", 0) > m.get("received_value_cents", 0):
                return "BREACHED", {"step": s.name, "invoice_amount_cents": m.get("invoice_amount_cents"),
                                    "received_value_cents": m.get("received_value_cents")}, \
                       "invoice amount exceeded received value on a successful match"
    for s in steps:
        body = s.response_payload
        if s.name == "match_invoice" and isinstance(body, dict) and body.get("match"):
            return "HELD", {}, "all matches respected the received-value bound"
    return "NOT_TESTED", {}, "no match steps in log"


def _rule_match_gate(steps):
    matched_ids: set[int] = set()
    for s in steps:
        body = s.response_payload
        if s.name == "match_invoice" and isinstance(body, dict) and _status_of(s.status_code) == "OK" and "id" in body:
            matched_ids.add(body["id"])
    for s in steps:
        body = s.response_payload
        if s.name == "approve_invoice" and isinstance(body, dict) and _status_of(s.status_code) == "OK":
            iid = body.get("id")
            if iid is not None and iid not in matched_ids:
                return "BREACHED", {"step": s.name, "invoice_id": iid}, \
                       "invoice approved without a successful prior match"
    if any(s.name == "approve_invoice" and _status_of(s.status_code) == "OK" for s in steps):
        return "HELD", {}, "every approved invoice had a prior successful match"
    return "NOT_TESTED", {}, "no approved invoices in log"


def _rule_partial_flag(steps):
    po_ctx = _po_context_map(steps)
    checked = 0
    for s in steps:
        body = s.response_payload
        if s.name != "match_invoice" or not isinstance(body, dict):
            continue
        m = body.get("match") or {}
        po = po_ctx.get(body.get("po_id"))
        if not isinstance(po, dict):
            continue
        checked += 1
        by_sku = {l["sku"]: l for l in po.get("line_items", [])}
        receipt = po.get("receipt") or {}
        partial_ctx = any(
            rl.get("quantity_received", 0) < by_sku[rl["sku"]]["quantity"]
            for rl in receipt.get("lines", []) if rl["sku"] in by_sku)
        if partial_ctx and m.get("partial") is not True:
            return "BREACHED", {"step": s.name, "po_id": body.get("po_id")}, \
                   "partial receipt silently passed (partial flag missing/false)"
    if checked:
        return "HELD", {}, f"partial-receipt flag verified on {checked} match(es)"
    return "NOT_TESTED", {}, "no PO context to verify partial flag"


def _rule_inactive_vendor(steps):
    v_status = _vendor_status_map(steps)
    for s in steps:
        body = s.response_payload
        req = s.request_payload or {}
        if s.name == "create_po" and isinstance(body, dict) and _status_of(s.status_code) == "OK":
            vid = req.get("vendor_id")
            if vid is not None and v_status.get(vid) == "inactive":
                return "BREACHED", {"step": s.name, "vendor_id": vid}, \
                       "PO created against inactive vendor"
    if any(s.name == "create_po" and _status_of(s.status_code) == "OK" for s in steps):
        return "HELD", {}, "all POs created against active vendors"
    return "NOT_TESTED", {}, "no PO creations in log"


def _rule_gl_balance(steps):
    for s in steps:
        body = s.response_payload
        if s.name == "approve_invoice" and isinstance(body, dict):
            gl = body.get("gl_post") or {}
            entries = gl.get("entries") or []
            debts = sum(e.get("debit_cents", 0) for e in entries)
            creds = sum(e.get("credit_cents", 0) for e in entries)
            if debts != creds:
                return "BREACHED", {"step": s.name, "debit_cents": debts, "credit_cents": creds}, \
                       "GL posting unbalanced (debits != credits)"
            if entries:
                return "HELD", {"step": s.name}, "GL posting balanced"
    return "NOT_TESTED", {}, "no GL postings in log"


def _rule_duplicate(steps):
    """Count only *unverified* accepted creates (the write path double-logs a
    create once for the POST and once for the GET proof via `verified`)."""
    seen: dict[tuple, int] = {}
    for s in steps:
        body = s.response_payload
        if s.name != "create_invoice" or not isinstance(body, dict):
            continue
        key = (_norm(body.get("invoice_number")), body.get("vendor_id"))
        if _status_of(s.status_code) == "OK":
            if s.verified:
                continue  # this is the GET-proof re-record of an already-counted create
            if key in seen:
                return "BREACHED", {"invoice_number": body.get("invoice_number"),
                                    "vendor_id": body.get("vendor_id")}, \
                       "duplicate invoice_number accepted from same vendor"
            seen[key] = 1
        elif s.status_code == 400 and key in seen:
            return "HELD", {"invoice_number": body.get("invoice_number"),
                            "vendor_id": body.get("vendor_id")}, \
                   "duplicate invoice_number rejected"
    return "NOT_TESTED", {}, "no invoice creations in log"


def _rule_data_integrity(steps):
    for i, s in enumerate(steps):
        body = s.response_payload
        if s.name.startswith("create_") and isinstance(body, dict) and _status_of(s.status_code) == "OK":
            rid = body.get("id")
            for later in steps[i + 1:]:
                if later.name.startswith("get_") and str(rid) in later.url and later.status_code == 404:
                    return "BREACHED", {"step": s.name, "resource_id": rid,
                                        "get_step": later.name}, \
                           "create returned 2xx but resource did not persist (phantom write)"
        if s.interpretation and "POST/GET discrepancy" in s.interpretation:
            return "BREACHED", {"step": s.name}, s.interpretation
    if any(s.name.startswith("create_") and _status_of(s.status_code) == "OK" for s in steps):
        return "HELD", {}, "creates verified by GET proof"
    return "NOT_TESTED", {}, "no creates in log"


_FINANCIAL_RULES = {
    "overpayment_protection": _rule_overpayment,
    "match_gate": _rule_match_gate,
    "partial_receipt_flag": _rule_partial_flag,
    "inactive_vendor_gate": _rule_inactive_vendor,
    "gl_balance": _rule_gl_balance,
    "duplicate_detection": _rule_duplicate,
    "data_integrity": _rule_data_integrity,
}


def run_prepass(steps: list[StepRecord], baseline: list[ProbeResult]) -> list[Finding]:
    # Carry the baseline probe's status, concrete evidence, and note. A probe's
    # evidence (raw request/status/response) is the most specific we have.
    baseline_by_rule: dict[str, tuple[str, dict, str]] = {}
    for p in baseline:
        if p.rule not in baseline_by_rule or p.status == "BREACHED":
            status = ("HELD" if p.status == "HELD" else
                      ("BREACHED" if p.status == "BREACHED" else "NOT_TESTED"))
            baseline_by_rule[p.rule] = (status, p.evidence, p.note)

    findings: list[Finding] = []
    for rule in config.INVARIANT_NAMES:
        base_status, base_ev, base_note = baseline_by_rule.get(
            rule, ("NOT_TESTED", {}, "no evidence in this run"))
        if rule in _FINANCIAL_RULES:
            log_status, log_ev, log_note = _FINANCIAL_RULES[rule](steps)
            status = _merge(log_status, base_status)
            # Prefer the probe's concrete evidence; fall back to the recompute.
            evidence = base_ev or log_ev
            note = " | ".join(x for x in (log_note, f"baseline: {base_note}") if x)
            note = note.strip(" |") or "no evidence in this run"
        else:
            status = base_status
            evidence = base_ev
            note = base_note or "no evidence in this run"
        if not evidence:
            evidence = {"status": status, "note": note}  # never an empty {}
        findings.append(Finding(rule, status, evidence, note))
    return findings

# ---------------------------------------------------------------------------
# Report assembly (exact spec JSON) + LLM narrative summary
# ---------------------------------------------------------------------------

def build_report(api_url: str, steps: list[StepRecord], findings: list[Finding],
                 integration_issues: list[dict], summary: str,
                 happy_status: str = "PASS") -> dict:
    """Assemble the exact report JSON from the spec."""
    happy_steps = []
    for s in steps:
        # verified/verify_note apply ONLY to create steps (the object being
        # verified). On every other step those keys are absent entirely, not
        # 'null' — they are not applicable. The proof GET instead carries
        # verifies=<create> (it is the verification, not the subject).
        step = {
            "name": s.name, "method": s.method, "url": s.url,
            "status_code": s.status_code,
            "interpretation": s.interpretation,
        }
        if s.request_payload is not None:
            step["request_payload"] = s.request_payload
        if isinstance(s.response_payload, dict):
            step["response_summary"] = (s.response_payload or {})
        else:
            step["response_summary"] = s.response_payload
        if s.name.startswith("create"):
            step["verified"] = s.verified
            step["verify_note"] = s.verify_note
        elif s.verifies:
            step["verifies"] = s.verifies
        happy_steps.append(step)
    adversarial = [f.to_dict() for f in findings]
    return {
        "api_url": api_url,
        "happy_path": {"status": happy_status, "steps": happy_steps},
        "adversarial": adversarial,
        "integration_issues": integration_issues,
        "summary": summary,
    }


_JUDGE_SYSTEM = ("You are a financial-integrity judge for a Purchase-to-Pay API. "
                 "Given the deterministic findings (recomputed invariants) and the "
                 "happy-path status, write a 2-4 sentence narrative summary for "
                 "engineering leadership: which guardrails held, which were BREACHED, "
                 "and the financial/operational risk. Do NOT contradict the findings. "
                 "Be specific with evidence; avoid generic filler.")


def llm_summary(findings: list[Finding], happy_status: str = "PASS",
                llm_chat=None) -> str:
    """LLM narrative summary, constrained by the deterministic findings."""
    if llm_chat is None:
        from p2p_qa import llm
        llm_chat = llm.chat
    payload = {"happy_path_status": happy_status,
               "findings": [f.to_dict() for f in findings]}
    try:
        resp = llm_chat(_JUDGE_SYSTEM,
                        [{"role": "user", "content": __import__("json").dumps(payload)}])
        text = (resp.get("content") or "").strip()
        if text:
            return text
    except Exception:
        pass
    # dev-only deterministic fallback if the LLM is unavailable
    breached = [f.rule for f in findings if f.status == "BREACHED"]
    held = [f.rule for f in findings if f.status == "HELD"]
    parts = []
    if held:
        parts.append(f"guardrails held: {', '.join(held)}")
    if breached:
        parts.append(f"BREACHED: {', '.join(breached)}")
    else:
        parts.append("no breaches detected")
    return (f"Happy path {'PASS' if happy_status == 'PASS' else happy_status}. "
            + "; ".join(parts) + ".")
