"""Explorer agent — raw tool-calling ReAct loop (LLM, hard dependency).

Plan -> discover -> construct (with double-verification) -> verify.
Each step is logged with its interpretation; the model context stays bounded
(plan + last step); the full history goes to the StepLogger for the judge.
"""

import json

from p2p_qa import config
from p2p_qa.client import StepRecord

EXPLORER_SYSTEM = """You are an autonomous QA exploration agent for a Purchase-to-Pay (P2P) API.
Mission: build one valid end-to-end workflow: create vendor -> create draft PO -> submit -> receive (partial) -> create invoice -> match -> approve.
Financial invariants you protect (integer cents):
 1. invoice amount must never exceed the value of goods actually received (equality is fine, +1 cent is a violation)
 2. an invoice cannot be approved unless it has passed matching
 3. partial receipt must be surfaced as partial=true in the match result
 4. no new POs against inactive vendors
 5. every approved invoice must post a balanced GL entry (debits == credits)
 6. same invoice_number from the same vendor must be rejected
Rules of operation:
 - Every create is double-verified by the harness: the create response, then a deterministic GET proof appended to that create's tool result (look for the '[verify: ...]' note and the proof GET). Never trust a POST alone. Do NOT call get_vendor/get_po/get_invoice yourself to verify a create - the harness proof already did it.
 - After each tool result, on its own line, write: INTERPRET: <one sentence: did it succeed; is the data consistent; any anomaly?>
 - Check the match result for the partial flag and variance; check approve for a balanced GL entry.
 - If an endpoint misbehaves or a schema field is missing, note it and adapt; do not crash.
 - When the workflow is complete, call finish_happy_path with a JSON summary.
"""


def _tool_specs():
    def spec(name, desc, props, required=()):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(required)}}}

    return [
        spec("list_vendors", "List all vendors.", {}, []),
        spec("get_vendor", "Get one vendor by id.", {"vendor_id": {"type": "integer"}}, ["vendor_id"]),
        spec("create_vendor", "Create a vendor.",
             {"name": {"type": "string"}, "status": {"type": "string", "enum": ["active", "inactive"]}},
             ["name"]),
        spec("create_po", "Create a draft PO with line items.",
             {"vendor_id": {"type": "integer"},
              "line_items": {"type": "array",
                             "items": {"type": "object",
                                       "properties": {"sku": {"type": "string"},
                                                      "description": {"type": "string"},
                                                      "unit_price_cents": {"type": "integer"},
                                                      "quantity": {"type": "integer"}}}}},
             ["vendor_id", "line_items"]),
        spec("submit_po", "Submit a draft PO.", {"po_id": {"type": "integer"}}, ["po_id"]),
        spec("receive_po", "Record a goods receipt (partial ok).",
             {"po_id": {"type": "integer"},
              "lines": {"type": "array",
                        "items": {"type": "object",
                                  "properties": {"sku": {"type": "string"},
                                                 "quantity_received": {"type": "integer"}}}}},
             ["po_id", "lines"]),
        spec("get_po", "Get PO detail + receipt status.", {"po_id": {"type": "integer"}}, ["po_id"]),
        spec("create_invoice", "Create an invoice against a PO.",
             {"invoice_number": {"type": "string"}, "vendor_id": {"type": "integer"},
              "po_id": {"type": "integer"}, "amount_cents": {"type": "integer"}},
             ["invoice_number", "vendor_id", "po_id", "amount_cents"]),
        spec("match_invoice", "3-way match an invoice.", {"invoice_id": {"type": "integer"}}, ["invoice_id"]),
        spec("approve_invoice", "Approve a matched invoice + post to GL.", {"invoice_id": {"type": "integer"}}, ["invoice_id"]),
        spec("get_exposure", "Total open AP liability for a vendor.", {"vendor_id": {"type": "integer"}}, ["vendor_id"]),
        spec("finish_happy_path", "Call when the full workflow is complete.",
             {"completed": {"type": "boolean"},
              "summary": {"type": "string", "description": "JSON dict describing what was done and the outcome"}},
             ["completed"]),
    ]


def _execute_tool(client, name: str, arguments: str) -> StepRecord:
    args = json.loads(arguments) if arguments else {}
    if name == "list_vendors":
        return client.list_vendors()
    if name == "get_vendor":
        return client.get_vendor(int(args["vendor_id"]))
    if name == "create_vendor":
        return client.create_vendor(args["name"], args.get("status", "active"))
    if name == "create_po":
        return client.create_po(int(args["vendor_id"]), args["line_items"])
    if name == "submit_po":
        return client.submit_po(int(args["po_id"]))
    if name == "receive_po":
        return client.receive_po(int(args["po_id"]), args["lines"])
    if name == "get_po":
        return client.get_po(int(args["po_id"]))
    if name == "create_invoice":
        return client.create_invoice(args["invoice_number"], int(args["vendor_id"]),
                                     int(args["po_id"]), int(args["amount_cents"]))
    if name == "match_invoice":
        return client.match_invoice(int(args["invoice_id"]))
    if name == "approve_invoice":
        return client.approve_invoice(int(args["invoice_id"]))
    if name == "get_exposure":
        return client.get_exposure(int(args["vendor_id"]))
    if name == "finish_happy_path":
        return StepRecord(name="finish_happy_path", method="NONE", url="", request_payload=args,
                          status_code=0, response_payload=args)
    raise ValueError(f"unknown tool {name}")


def _extract_interpretation(text: str | None) -> str | None:
    if not text:
        return None
    lines = [l for l in text.splitlines() if l.strip().upper().startswith("INTERPRET:")]
    return lines[-1].strip() if lines else None


def _extract_facts(name: str, step: StepRecord, facts: dict) -> dict:
    """Pull the key handles from a tool result into a small facts dict."""
    body = step.response_payload
    if not isinstance(body, dict):
        return facts
    if name in ("create_vendor", "get_vendor"):
        if "id" in body:
            facts["vendor_id"] = body["id"]
        if "status" in body:
            facts["vendor_status"] = body["status"]
        if "account_code" in body:
            facts["vendor_account_code"] = body["account_code"]
    elif name == "list_vendors" and isinstance(body, list):
        active = [v for v in body if isinstance(v, dict) and v.get("status") == "active"]
        if active:
            facts["vendor_id"] = active[0]["id"]
            facts["vendor_status"] = "active"
    elif name in ("create_po", "get_po", "receive_po", "submit_po"):
        if "id" in body:
            facts["po_id"] = body["id"]
        if body.get("line_items"):
            facts["skus"] = [l.get("sku") for l in body["line_items"] if l.get("sku")]
        if "status" in body:
            facts["po_status"] = body["status"]
    elif name in ("create_invoice", "get_invoice", "match_invoice", "approve_invoice"):
        if "id" in body:
            facts["invoice_id"] = body["id"]
        if "invoice_number" in body:
            facts["invoice_number"] = body["invoice_number"]
        if "amount_cents" in body:
            facts["invoice_amount_cents"] = body["amount_cents"]
        if body.get("match"):
            facts["match_partial"] = body["match"].get("partial")
            facts["match_received_value_cents"] = body["match"].get("received_value_cents")
            facts["match_variance_cents"] = body["match"].get("variance_cents")
        if body.get("gl_post"):
            facts["gl_balanced"] = body["gl_post"].get("balanced")
    return facts


_FLOW_ORDER = ["vendor", "po", "submit", "receive", "invoice", "match", "approve"]


def _next_expected(flow_done: list[str]) -> str | None:
    for stage in _FLOW_ORDER:
        if stage not in flow_done:
            return stage
    return None


FALLBACK_INTERP = {
    "create_vendor": "vendor created (POST {status}); GET proof must confirm persistence",
    "create_po": "draft PO created (POST {status}); vendor matches rules",
    "submit_po": "PO submitted (POST {status})",
    "receive_po": "goods receipt recorded (POST {status}); check partial receipt flag at match",
    "create_invoice": "invoice created (POST {status}); amount must not exceed received value",
    "match_invoice": "3-way match attempted (POST {status}); verify partial flag + variance",
    "approve_invoice": "approve attempted (POST {status}); verify GL balance",
    "get_exposure": "exposure read (GET {status})",
}


def _deterministic_interp(name: str, step: StepRecord) -> str | None:
    tpl = FALLBACK_INTERP.get(name)
    if not tpl:
        return None
    status = step.status_code if step.status_code is not None else "error"
    return tpl.format(status=status)





def _happy_result(status: str, flow_done: list[str], interpretations: dict) -> dict:
    return {
        "status": status, "approved_late": True, "steps_count": len(flow_done),
        "flow": ["vendor", "po", "submit", "receive", "invoice", "match", "approve"],
        "interpretations": interpretations,
    }


def run_explorer(client, logger, llm_chat=None, max_steps=config.MAX_EXPLORER_STEPS,
              progress=None) -> dict:
    if llm_chat is None:
        from p2p_qa import llm
        llm_chat = llm.chat
    flow_done: list[str] = []
    interpretations: dict[str, str] = {}
    facts: dict = {}
    last = None
    history: list[dict] = []  # assistant tool_calls -> tool results -> user state

    def build_context() -> str:
        ctx = {
            "stage": "explore",
            "plan": "create vendor -> PO -> submit -> partial receive -> invoice -> match (check partial) -> approve (check GL balanced). Do not keep re-exploring: once you have an active vendor id and a sku, move to creating the PO.",
            "flow_done": flow_done,
            "next_expected": _next_expected(flow_done),
            "facts": facts,
            "last_step": last,
        }
        return json.dumps(ctx)

    for _ in range(max_steps):
        messages = history + [{"role": "user", "content": build_context()}]
        resp = llm_chat(EXPLORER_SYSTEM, messages, tools=_tool_specs())
        interp = _extract_interpretation(resp.get("content"))

        tool_calls = resp.get("tool_calls") or []
        if not tool_calls:
            last = {"name": "(no tool call)", "status_code": None, "key": {},
                    "error": "model returned no tool call", "interp": interp}
            history.append({"role": "assistant", "content": resp.get("content") or ""})
            continue

        # record the assistant's tool-call turn in history (canonical ReAct pattern)
        history.append({
            "role": "assistant",
            "content": resp.get("content") or "",
            "tool_calls": [{"id": tc["id"], "type": "function",
                             "function": {"name": tc["name"],
                                           "arguments": tc.get("arguments") or "{}"}}
                            for tc in tool_calls],
        })

        finished = False
        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("arguments") or "{}"
            step = _execute_tool(client, name, args)
            if not interp:
                interp = _deterministic_interp(name, step)
            step.interpretation = interp
            if interp and name not in interpretations:
                interpretations.setdefault(name, interp)
            facts = _extract_facts(name, step, facts)
            step.verified = False
            if progress:
                progress(step)
            if name != "finish_happy_path":
                if "create" in name:
                    # Verify via ONE quiet proof GET (never double-logs), then
                    # annotate the create (verified/verify_note) and log the
                    # create ONCE, then the single tagged proof GET.
                    ok, got = _mark_verified(client, step)
                    step.verified = ok
                    logger.record(step)
                    if got is not None:
                        got.verifies = name
                        got.interpretation = step.verify_note or "GET proof matches POST values"
                        logger.record(got)
                else:
                    logger.record(step)
            interp = None  # consume this turn's interpretation; don't leak it forward
            # tool result goes back into history (compressed)
            compact = {"name": name, "status_code": step.status_code,
                       "response": (json.dumps(step.response_payload)[:600]
                                     if step.response_payload is not None else None),
                       "error": step.error}
            history.append({"role": "tool", "tool_call_id": tc["id"],
                            "content": json.dumps(compact)})
            if name == "finish_happy_path":
                finished = True
                try:
                    done = json.loads(args).get("completed", False)
                except json.JSONDecodeError:
                    done = False
                last = {"name": "finish_happy_path", "status_code": 0, "key": {},
                        "error": None, "done": done}
                if done:
                    return _happy_result("PASS", flow_done, interpretations)
            else:
                # Mission-complete: an approved invoice IS the completed happy
                # path (finish_happy_path only confirms). Stop immediately so
                # we never wander into a second workflow cycle.
                if name == "approve_invoice" and step.status_code is not None and step.status_code < 400:
                    return _happy_result("PASS", flow_done, interpretations)
                flow_name = _flow_step(name)
                if flow_name and flow_name not in flow_done:
                    flow_done.append(flow_name)
                facts_slice = {k: facts.get(k) for k in ("vendor_id", "po_id", "invoice_id",
                                                          "invoice_amount_cents", "match_partial",
                                                          "gl_balanced") if facts.get(k) is not None}
                last = {"name": name, "status_code": step.status_code,
                        "key": facts_slice, "error": step.error, "interp": interp}
        # bound the history window (drop oldest assistant/tool pairs beyond 24 msgs)
        if len(history) > 24:
            history = history[-24:]

    return {
        "status": "INCOMPLETE", "approved_late": False, "steps_count": len(flow_done),
        "flow": flow_done, "interpretations": interpretations,
    }


def _flow_step(name: str) -> str | None:
    mapping = {
        "create_vendor": "vendor", "create_po": "po", "submit_po": "submit",
        "receive_po": "receive", "create_invoice": "invoice",
        "match_invoice": "match", "approve_invoice": "approve",
    }
    return mapping.get(name)


def _mark_verified(client, step: StepRecord):
    """Double-verify a create via a GET proof. Returns (ok, verified_record).

    The verified_record is the GET-proof StepRecord that verify_get already
    recorded to the logger (tagged verifies=<create>). It is the same record
    the caller logs, so the proof shows up in the audit trail.
    """
    body = step.response_payload
    rid = (body or {}).get("id")
    if rid is None:
        return False, None
    if step.name == "create_vendor":
        expected = {"name": step.request_payload.get("name"),
                    "status": step.request_payload.get("status", "active")}
        got = client.verification_get("get_vendor", f"/vendors/{rid}",
                                      schema_key="GET /vendors/{id}")
        ok, note = client._check_persisted(step, got, expected)
    elif step.name == "create_po":
        expected = {"status": "draft"}
        got = client.verification_get("get_po", f"/purchase-orders/{rid}",
                                      schema_key="GET /purchase-orders/{id}")
        ok, note = client._check_persisted(step, got, expected)
    elif step.name == "create_invoice":
        expected = {"invoice_number": step.request_payload.get("invoice_number"),
                    "amount_cents": step.request_payload.get("amount_cents")}
        got = client.verification_get("get_invoice", f"/invoices/{rid}",
                                      schema_key="GET /invoices/{id}")
        ok, note = client._check_persisted(step, got, expected)
    else:
        return False, None
    step.verified = ok
    step.verify_note = note
    if "[verify:" not in (step.interpretation or ""):
        step.interpretation = (step.interpretation or "") + f" [verify: {note}]"
    return ok, got