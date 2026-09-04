"""Adversarial baseline — deterministic probes for the six financial
invariants plus security attack classes and data-integrity double-verification.

Each probe returns HELD (API rejected correctly) or BREACHED (leak observed)
with byte-level evidence. One probe's failure never aborts the suite.
"""

from dataclasses import dataclass, field
from typing import Callable

from p2p_qa import config
from p2p_qa.client import P2PClient, double_verify

SECRET_KEYS = ("password", "bank_account_full", "ssn", "api_key",
               "bank_account_number", "card_number",
               "bank_account_last4", "contact_email")


@dataclass
class ProbeResult:
    rule: str
    probe_name: str
    status: str  # HELD | BREACHED | ERROR
    evidence: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return {"rule": self.rule, "probe_name": self.probe_name,
                "status": self.status, "evidence": self.evidence, "note": self.note}


def _truncate(payload, limit: int = 400) -> str:
    import json
    try:
        s = json.dumps(payload, default=str)
    except Exception:
        s = str(payload)
    return s[:limit] + ("..." if len(s) > limit else "")


def _ev(method, url, status, payload, request_payload=None) -> dict:
    ev = {"request": f"{method} {url}", "status": status,
          "response": _truncate(payload)}
    # Surface the exact payload sent on create requests so a human can see
    # what was attempted (e.g. the +1 cent invoice in the overpayment probe).
    if request_payload is not None:
        ev["request_payload"] = request_payload
    return ev


def _inv_evidence(inv_payload: dict) -> dict:
    """Extract the invoice-relevant fields from an invoice response for evidence."""
    if not isinstance(inv_payload, dict):
        return {}
    return {"invoice_number": inv_payload.get("invoice_number"),
            "vendor_id": inv_payload.get("vendor_id"),
            "po_id": inv_payload.get("po_id"),
            "amount_cents": inv_payload.get("amount_cents")}


def _setup_received_po(client: P2PClient, vendor_name: str, sku: str = "SKU-ADV",
                       price: int = 1000, qty: int = 5, received: int | None = None):
    v = client.create_vendor(vendor_name, "active").response_payload
    po = client.create_po(v["id"], [{"sku": sku, "description": "adv",
                                     "unit_price_cents": price, "quantity": qty}]).response_payload
    client.submit_po(po["id"])
    client.receive_po(po["id"], [{"sku": sku, "quantity_received": qty if received is None else received}])
    return v, po


# ---------- financial invariant probes ----------

def probe_overpayment(client: P2PClient) -> ProbeResult:
    v, po = _setup_received_po(client, "OverProbe")
    inv = client.create_invoice("INV-ADV-OVR", v["id"], po["id"], 5001)  # received 5000, +1 cent
    m = client.match_invoice(inv.response_payload["id"])
    if m.status_code == 400:
        return ProbeResult("overpayment_protection", "overpayment_plus_1_cent", "HELD",
                           _ev("POST", f"/invoices/{inv.response_payload['id']}/match",
                               m.status_code, m.response_payload,
                               request_payload={"invoice_number": inv.response_payload.get("invoice_number"),
                                                "vendor_id": inv.response_payload.get("vendor_id"),
                                                "po_id": inv.response_payload.get("po_id"),
                                                "amount_cents": inv.response_payload.get("amount_cents")}),
                           "invoice (5001) > received value (5000) rejected at match")
    return ProbeResult("overpayment_protection", "overpayment_plus_1_cent", "BREACHED",
                       _ev("POST", f"/invoices/{inv.response_payload['id']}/match",
                           m.status_code, m.response_payload),
                       "invoice above received value accepted (off-by-one bypass)")


def probe_approve_unmatched(client: P2PClient) -> ProbeResult:
    v, po = _setup_received_po(client, "GateProbe")
    inv = client.create_invoice("INV-ADV-NM", v["id"], po["id"], 5000)
    a = client.approve_invoice(inv.response_payload["id"])  # never matched
    if a.status_code == 400:
        return ProbeResult("match_gate", "approve_unmatched", "HELD",
                           _ev("POST", f"/invoices/{inv.response_payload['id']}/approve",
                               a.status_code, a.response_payload,
                               request_payload=_inv_evidence(inv.response_payload)),
                           "unmatched invoice rejected at approve")
    return ProbeResult("match_gate", "approve_unmatched", "BREACHED",
                       _ev("POST", f"/invoices/{inv.response_payload['id']}/approve",
                           a.status_code, a.response_payload,
                           request_payload=_inv_evidence(inv.response_payload)),
                       "unmatched invoice approved")


def probe_partial_flag(client: P2PClient) -> ProbeResult:
    v, po = _setup_received_po(client, "FlagProbe", qty=5, received=2)
    inv = client.create_invoice("INV-ADV-PART", v["id"], po["id"], 2000)
    m = client.match_invoice(inv.response_payload["id"])
    if m.status_code != 200:
        return ProbeResult("partial_receipt_flag", "partial_flag_present", "ERROR",
                           _ev("POST", f"/invoices/{inv.response_payload['id']}/match",
                               m.status_code, m.response_payload), "match failed unexpectedly")
    match = (m.response_payload or {}).get("match", {})
    if match.get("partial") is True:
        return ProbeResult("partial_receipt_flag", "partial_flag_present", "HELD",
                           _ev("POST", f"/invoices/{inv.response_payload['id']}/match",
                               m.status_code, m.response_payload,
                               request_payload=_inv_evidence(inv.response_payload)),
                           "partial receipt surfaced with partial=true")
    return ProbeResult("partial_receipt_flag", "partial_flag_present", "BREACHED",
                       _ev("POST", f"/invoices/{inv.response_payload['id']}/match",
                           m.status_code, m.response_payload,
                           request_payload=_inv_evidence(inv.response_payload)),
                       "partial receipt matched but partial flag missing/false")


def probe_inactive_vendor(client: P2PClient) -> ProbeResult:
    r = client.create_po(2, [{"sku": "SKU-ADV", "description": "adv",
                              "unit_price_cents": 1000, "quantity": 1}])  # vendor 2 seeded inactive
    if r.status_code == 400:
        return ProbeResult("inactive_vendor_gate", "po_against_inactive_vendor", "HELD",
                           _ev("POST", "/purchase-orders", r.status_code, r.response_payload,
                               request_payload=r.request_payload),
                           "PO against inactive vendor rejected")
    return ProbeResult("inactive_vendor_gate", "po_against_inactive_vendor", "BREACHED",
                       _ev("POST", "/purchase-orders", r.status_code, r.response_payload),
                       "PO created against inactive vendor")


def probe_gl_balance(client: P2PClient) -> ProbeResult:
    v, po = _setup_received_po(client, "GlProbe", price=700, qty=2)
    inv = client.create_invoice("INV-ADV-GL", v["id"], po["id"], 1400)
    client.match_invoice(inv.response_payload["id"])
    a = client.approve_invoice(inv.response_payload["id"])
    gl = (a.response_payload or {}).get("gl_post")
    if gl is None:
        return ProbeResult("gl_balance", "balanced_gl", "ERROR",
                           _ev("POST", f"/invoices/{inv.response_payload['id']}/approve",
                               a.status_code, a.response_payload), "no gl_post in approve response")
    debts = sum(e.get("debit_cents", 0) for e in gl.get("entries", []))
    creds = sum(e.get("credit_cents", 0) for e in gl.get("entries", []))
    if debts == creds:
        return ProbeResult("gl_balance", "balanced_gl", "HELD",
                           _ev("POST", f"/invoices/{inv.response_payload['id']}/approve",
                               a.status_code, a.response_payload,
                               request_payload=_inv_evidence(inv.response_payload)),
                           f"GL balanced (debits {debts} == credits {creds})")
    return ProbeResult("gl_balance", "balanced_gl", "BREACHED",
                       _ev("POST", f"/invoices/{inv.response_payload['id']}/approve",
                           a.status_code, a.response_payload,
                           request_payload=_inv_evidence(inv.response_payload)),
                       f"GL unbalanced (debits {debts} != credits {creds})")


def probe_duplicate(client: P2PClient) -> ProbeResult:
    v, po = _setup_received_po(client, "DupProbe")
    first = client.create_invoice("INV-ADV-DUP", v["id"], po["id"], 5000)
    second = client.create_invoice("INV-ADV-DUP", v["id"], po["id"], 5000)
    if second.status_code == 400:
        return ProbeResult("duplicate_detection", "duplicate_invoice_number", "HELD",
                           _ev("POST", "/invoices", second.status_code, second.response_payload,
                               request_payload=second.request_payload),
                           "duplicate invoice_number rejected")
    return ProbeResult("duplicate_detection", "duplicate_invoice_number", "BREACHED",
                       _ev("POST", "/invoices", second.status_code, second.response_payload),
                       "duplicate invoice_number accepted (first 201 too)")


# ---------- security probes ----------

def probe_authorization(client: P2PClient) -> ProbeResult:
    r = client.raw("GET", "/vendors")
    if r.status_code == 401:
        authed = P2PClient(client.base_url, token=config.SEED_TOKEN)
        ok = authed.raw("GET", "/vendors")
        if ok.status_code == 200:
            return ProbeResult("authorization", "no_auth_access", "HELD",
                               _ev("GET", "/vendors", r.status_code, r.response_payload),
                               "endpoints require auth; valid token accepted")
        return ProbeResult("authorization", "no_auth_access", "HELD",
                           _ev("GET", "/vendors", r.status_code, r.response_payload),
                           "auth required; token rejected — unable to probe further")
    return ProbeResult("authorization", "no_auth_access", "BREACHED",
                       _ev("GET", "/vendors", r.status_code, r.response_payload),
                       "endpoints expose data without authentication")


def probe_pii(client: P2PClient) -> ProbeResult:
    leaked = []
    trace: list[dict] = []
    for rec in (client.list_vendors(), client.get_vendor(1)):
        trace.append({"request": f"{rec.method} {rec.url}", "status": rec.status_code,
                      "response": _truncate(rec.response_payload),
                      "request_payload": rec.request_payload})
        body = rec.response_payload
        items = body if isinstance(body, list) else [body]
        for item in items:
            if isinstance(item, dict):
                for k in SECRET_KEYS:
                    if k in item:
                        leaked.append(f"vendor id {item.get('id')}: '{k}' present")
    if leaked:
        return ProbeResult("pii_exposure", "secret_field_leak", "BREACHED",
                           {"leaked_fields": leaked[:6], "trace": trace},
                           "confidential vendor data exposed: " + "; ".join(leaked[:3]))
    return ProbeResult("pii_exposure", "secret_field_leak", "HELD",
                       {"checked": list(SECRET_KEYS), "trace": trace},
                       "no secret or confidential fields exposed")


def probe_mis_credit(client: P2PClient) -> ProbeResult:
    v, po = _setup_received_po(client, "MiscreditProbe")
    r = client.create_invoice("INV-ADV-MC", v["id"], po["id"], 5000,
                              account_code="ACC-999")  # another entity's account
    if r.status_code == 400:
        return ProbeResult("mis_credit", "wrong_account_credit", "HELD",
                           _ev("POST", "/invoices", r.status_code, r.response_payload,
                               request_payload=r.request_payload),
                           "invoice crediting another entity's account rejected")
    return ProbeResult("mis_credit", "wrong_account_credit", "BREACHED",
                       _ev("POST", "/invoices", r.status_code, r.response_payload),
                       "invoice accepted with account_code belonging to another entity")


_SQL_MARKERS = ("syntax error", "near \"", "sqlite", "psycopg", "postgres",
                "mysql", "unterminated", "query error", "sql")


def probe_injection(client: P2PClient) -> ProbeResult:
    evil_name = "x' OR '1'='1"
    evil_inv = "<script>alert(1)</script>"
    trace: list[dict] = []
    issues: list[str] = []
    v = client.create_vendor(evil_name, "active")
    trace.append(_ev("POST", "/vendors", v.status_code, v.response_payload,
                     request_payload=v.request_payload))
    suspect = ""
    if v.status_code >= 500:
        suspect = f"vendor create 5xx: {_truncate(v.response_payload)}"
    body = v.response_payload
    if isinstance(body, dict):
        text = _truncate(body).lower()
        if any(m in text for m in _SQL_MARKERS):
            suspect = f"SQL error text in vendor response: {_truncate(body)}"
    if not suspect:
        vid = (v.response_payload or {}).get("id")
        if vid is not None:
            got = client.get_vendor(vid)
            trace.append(_ev("GET", f"/vendors/{vid}", got.status_code, got.response_payload))
            if got.status_code >= 500:
                suspect = f"vendor get 5xx: {_truncate(got.response_payload)}"
    if not suspect:
        po = client.create_po(1, [{"sku": "SKU-ADV", "description": evil_inv,
                                   "unit_price_cents": 100, "quantity": 1}])
        trace.append(_ev("POST", "/purchase-orders", po.status_code, po.response_payload,
                         request_payload=po.request_payload))
        if po.status_code >= 500:
            suspect = f"po create 5xx with script value: {_truncate(po.response_payload)}"
    # Accepted + stored malicious input is itself a breach (no sanitization):
    # a real DB would persist the SQLi name / script description verbatim.
    if v.status_code < 400:
        issues.append("SQLi payload accepted & stored as vendor name (no sanitization)")
    if po.status_code < 400:
        issues.append("script payload accepted & stored as PO description (stored-XSS vector)")
    all_issues = []
    if suspect:
        all_issues.append(suspect)
    all_issues.extend(issues)
    if all_issues:
        return ProbeResult("injection", "sqli_script_injection", "BREACHED",
                           {"detail": "; ".join(all_issues), "trace": trace,
                            "accepted_unsanitized": issues},
                           "injection payloads accepted/stored or caused 5xx/leak")
    return ProbeResult("injection", "sqli_script_injection", "HELD",
                       {"payloads_tried": [evil_name, evil_inv], "trace": trace},
                       "injection payloads rejected/sanitized")


def probe_destructive_ops(client: P2PClient) -> ProbeResult:
    del_r = client.raw("DELETE", "/vendors/1")
    if del_r.status_code < 400:
        gone = client.get_vendor(1)
        if gone.status_code == 404:
            return ProbeResult("destructive_ops", "delete_vendor", "BREACHED",
                               _ev("DELETE", "/vendors/1", del_r.status_code, del_r.response_payload),
                               "DELETE /vendors/1 succeeded and removed the resource")
        return ProbeResult("destructive_ops", "delete_vendor", "BREACHED",
                           _ev("DELETE", "/vendors/1", del_r.status_code, del_r.response_payload),
                           "DELETE /vendors/1 returned 2xx")
    return ProbeResult("destructive_ops", "delete_vendor", "HELD",
                       _ev("DELETE", "/vendors/1", del_r.status_code, del_r.response_payload),
                       "destructive DELETE rejected")


def probe_data_integrity(client: P2PClient) -> ProbeResult:
    create = client.create_vendor("IntegrityProbe", "active")
    vid = (create.response_payload or {}).get("id")
    if vid is None:
        return ProbeResult("data_integrity", "post_get_verify", "ERROR",
                           _ev("POST", "/vendors", create.status_code, create.response_payload),
                           "create returned no id")
    ok, got, note = double_verify(client, create, lambda: client.get_vendor(vid),
                                  {"name": "IntegrityProbe", "status": "active"})
    if ok:
        return ProbeResult("data_integrity", "post_get_verify", "HELD",
                           _ev("GET", f"/vendors/{vid}", got.status_code, got.response_payload),
                           "POST persisted; GET proof matches")
    return ProbeResult("data_integrity", "post_get_verify", "BREACHED",
                       _ev("GET", f"/vendors/{vid}", got.status_code if got else None,
                           got.response_payload if got else None), note)


_PROBES: list[Callable[[P2PClient], ProbeResult]] = [
    probe_overpayment, probe_approve_unmatched, probe_partial_flag,
    probe_inactive_vendor, probe_gl_balance, probe_duplicate,
    probe_authorization, probe_pii, probe_mis_credit, probe_injection,
    probe_destructive_ops, probe_data_integrity,
]


def run_baseline(client: P2PClient) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for probe in _PROBES:
        try:
            results.append(probe(client))
        except Exception as e:  # noqa: BLE001
            results.append(ProbeResult(getattr(probe, "__name__", "probe"),
                                       "exception", "ERROR", {"error": str(e)[:300]}))
    return results

# ---------------------------------------------------------------------------
# Open-ended LLM hacker agent (red-team, not limited to the six invariants)
# ---------------------------------------------------------------------------

HACKER_SYSTEM = """You are an adversarial QA hacker for a Purchase-to-Pay (P2P) API. Your job: try to break it, then verify the guardrail held or leaked.

Endpoints: GET /vendors | POST /vendors | POST /purchase-orders | POST /purchase-orders/{id}/submit | POST /purchase-orders/{id}/receive | GET /purchase-orders/{id} | POST /invoices | POST /invoices/{id}/match | POST /invoices/{id}/approve | GET /vendors/{id}/exposure

Financial invariants to attack:
 1. overpayment_protection - invoice amount must not exceed value of goods actually received (equality is legal; +1 cent is a violation)
 2. match_gate - an invoice cannot be approved unless it has passed matching
 3. partial_receipt_flag - partial receipt must surface as partial=true in the match
 4. inactive_vendor_gate - no new POs against inactive vendors
 5. gl_balance - every approved invoice must post a balanced GL entry (debits == credits)
 6. duplicate_detection - same invoice_number from the same vendor must be rejected

Attack classes to probe (be creative; do not stop at the six invariants):
 - input validation: zero amounts, negative quantities, huge values, floats/strings where ints expected, NaN-like strings, missing/extra fields
 - state machine: approve before match, receive before submit, re-submit, re-receive, re-approve, invoice against a draft PO
 - business logic: overpayment with partial receipts, duplicate invoice_number with case/whitespace tricks, vendor swap between PO and invoice, zero qty / zero price lines
 - authorization: perform a transaction with no auth, a forged caller, or on behalf of another vendor; attempt a payment/refund you have no entitlement to
 - PII & sensitive data: hunt for passwords, full payment instruments, and other tenants' data leaking through list/detail/error responses
 - fraud by mis-credit: credit an invoice to an account owned by another entity, then approve - a refund for a payment never made
 - injection: SQL injection and script injection in names/invoice_number/query params - expect no error, no leak, no raw reflection
 - destructive ops: DELETE/PUT on vendors/POs/invoices/receipts - expect 4xx/5xx, never silent mutation
 - information exposure: verbose error bodies, exposure endpoint leaks

Rules of operation:
 - Use raw_probe to fire HTTP probes. Seeded data: vendor 1 active "Acme Building Supply", vendor 2 INACTIVE "Blocked Materials Co", PO 101 submitted (BRICK-001 x100 @ 1200c). Reuse existing records where possible; create new ones only as needed.
 - After a probe result comes back, on its own line write: VERDICT: HELD|BREACHED <rule> <one sentence of reasoning with evidence>
 - HELD means the API correctly rejected/guarded it. BREACHED means the API accepted something it must reject, leaked sensitive data, or mutated without authority.
 - Verify any mutation with a follow-up GET; never trust a POST response alone.
 - A 5xx on malformed/ill-typed input is itself a robustness breach: mark it BREACHED (rule robustness) even if no money leaked.
 - Stay polite: modest concurrency, no floods. Probe the API under test.
 - After ~15-20 probes, call finish with a JSON summary of distinct rules probed."""


# Minimal rule-name normalization: accept either the canonical slug or a loose token.
_RULE_ALIASES = {
    "overpayment": "overpayment_protection", "overpayment_protection": "overpayment_protection",
    "match": "match_gate", "match_gate": "match_gate", "matchgate": "match_gate",
    "partial": "partial_receipt_flag", "partial_receipt_flag": "partial_receipt_flag",
    "partialreceipt": "partial_receipt_flag",
    "inactive": "inactive_vendor_gate", "inactive_vendor_gate": "inactive_vendor_gate",
    "gl": "gl_balance", "gl_balance": "gl_balance", "glbalance": "gl_balance",
    "duplicate": "duplicate_detection", "duplicate_detection": "duplicate_detection",
    "dupdetect": "duplicate_detection",
    "auth": "authorization", "authorization": "authorization", "authentication": "authorization",
    "pii": "pii_exposure", "pii_exposure": "pii_exposure", "pii_leak": "pii_exposure",
    "miscredit": "mis_credit", "mis_credit": "mis_credit", "mis-credit": "mis_credit",
    "injection": "injection", "sqli": "injection", "sql": "injection", "xss": "injection",
    "destructive": "destructive_ops", "destructive_ops": "destructive_ops", "delete": "destructive_ops",
    "data_integrity": "data_integrity", "dataintegrity": "data_integrity",
}


def _normalize_rule(token: str) -> str:
    t = token.strip().lower().lstrip("'").rstrip("'").rstrip(":,.;")
    return _RULE_ALIASES.get(t, t)


def _hacker_tool_specs():
    def spec(name, desc, props, required=()):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(required)}}}

    return [
        spec("raw_probe", "Fire a raw HTTP probe at the API (any method/path you can construct).",
             {"method": {"type": "string",
                          "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]},
              "path": {"type": "string"},
              "payload": {"type": ["object", "null"], "description": "JSON body (for POST/PUT)"}},
             ["method", "path"]),
        spec("get_vendor", "GET one vendor by id.", {"vendor_id": {"type": "integer"}}, ["vendor_id"]),
        spec("get_po", "GET a PO by id.", {"po_id": {"type": "integer"}}, ["po_id"]),
        spec("get_exposure", "GET a vendor's open AP exposure.", {"vendor_id": {"type": "integer"}}, ["vendor_id"]),
        spec("finish", "Call when done probing.",
             {"summary": {"type": "string", "description": "JSON dict: {rules_probed: [..], overall_risk: str}"}},
             ["summary"]),
    ]


def _execute_hacker_tool(client, name: str, args: dict):
    from p2p_qa.client import StepRecord
    if name == "raw_probe":
        return client.raw(args["method"].upper(), args["path"], payload=args.get("payload"))
    if name == "get_vendor":
        return client.get_vendor(int(args["vendor_id"]))
    if name == "get_po":
        return client.get_po(int(args["po_id"]))
    if name == "get_exposure":
        return client.get_exposure(int(args["vendor_id"]))
    if name == "finish":
        return None
    raise ValueError(f"unknown hacker tool {name}")


def _extract_verdicts(text: str | None) -> list[tuple[str, str, str]]:
    """Parse VERDICT: HELD|BREACHED <rule> <reasoning> lines -> (status, rule, reasoning)."""
    if not text:
        return []
    out = []
    for line in text.splitlines():
        if "VERDICT" not in line.upper():
            continue
        up = line.upper()
        status = None
        if "INFO" in up:
            status = "INFO"
        elif "BREACHED" in up:
            status = "BREACHED"
        elif "HELD" in up:
            status = "HELD"
        if status is None:
            continue
        rest = line.split("VERDICT", 1)[1]
        after = rest
        idx = after.upper().find(status)
        if idx >= 0:
            after = after[idx + len(status):]
        tokens = after.split()
        rule = tokens[0] if tokens else "hacker_probe"
        reasoning = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        if not rule:
            continue
        out.append((status, _normalize_rule(rule), reasoning[:300]))
    return out


def _step_evidence(step) -> dict:
    if step is None:
        return {"request": None, "status": None, "response": "(no probe yet)"}
    ev = {"request": f"{step.method} {step.url}", "status": step.status_code,
          "response": _truncate(step.response_payload)}
    if getattr(step, "request_payload", None) is not None:
        ev["request_payload"] = step.request_payload
    return ev


def run_hacker(client: P2PClient, llm_chat=None, max_probes: int = config.MAX_HACKER_PROBES,
               logger=None, progress=None) -> list[ProbeResult]:
    """Open-ended red-team agent: proposes and executes probes, then emits
    HELD/BREACHED verdicts in a dedicated reflection turn (deterministic format).
    Same ReAct pattern as the explorer, plus an explicit verdict step."""
    if llm_chat is None:
        from p2p_qa import llm
        llm_chat = llm.chat
    import json
    results: list[ProbeResult] = []
    history: list[dict] = []
    last_step = None
    probes_executed = 0
    finished = False
    VERDICT_PROMPT = ("For each probe whose result you just received, write exactly one line:\n"
                      "VERDICT: HELD|BREACHED <rule> <one sentence of reasoning with evidence>\n"
                      "If a probe was pure reconnaissance with no rule under test, write: VERDICT: INFO <reason>.\n"
                      "Do not fire new tools in this reply; verdicts only.")

    for _ in range(max_probes + 6):
        ctx = {"stage": "red_team",
               "probes_executed": probes_executed,
               "verdicts_so_far": [r.to_dict() for r in results[-6:]],
               "last_result": _step_evidence(last_step)}
        messages = history + [{"role": "user", "content": json.dumps(ctx)}]
        resp = llm_chat(HACKER_SYSTEM, messages, tools=_hacker_tool_specs())
        tool_calls = resp.get("tool_calls") or []
        history.append({"role": "assistant", "content": resp.get("content") or "",
                        "tool_calls": [{"id": tc["id"], "type": "function",
                                         "function": {"name": tc["name"],
                                                       "arguments": tc.get("arguments") or "{}"}}
                                        for tc in tool_calls]})
        if not tool_calls:
            continue

        executed: list = []
        for tc in tool_calls:
            if finished:
                break
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            step = _execute_hacker_tool(client, tc["name"], args)
            if tc["name"] == "finish":
                finished = True
                history.append({"role": "tool", "tool_call_id": tc["id"],
                                "content": "finish acknowledged"})
                break
            if progress:
                progress(step)
            last_step = step
            probes_executed += 1
            history.append({"role": "tool", "tool_call_id": tc["id"],
                            "content": json.dumps({"status_code": step.status_code,
                                                    "response": _truncate(step.response_payload, 500),
                                                    "error": step.error})})
            executed.append(step)
        if len(history) > 30:
            history = history[-30:]
        if finished:
            break
        if not executed:
            continue

        # Reflection turn: force the verdict lines for the probes just executed.
        vresp = llm_chat(HACKER_SYSTEM, history + [{"role": "user", "content": VERDICT_PROMPT}])
        vtext = vresp.get("content") or ""
        history.append({"role": "assistant", "content": vtext})
        for status, rule, reasoning in _extract_verdicts(vtext):
            if status == "INFO":
                continue
            results.append(ProbeResult(rule, "hacker_probe", status,
                                       _step_evidence(last_step), reasoning))
        if probes_executed >= max_probes:
            break
        if len(history) > 30:
            history = history[-30:]
    return results
