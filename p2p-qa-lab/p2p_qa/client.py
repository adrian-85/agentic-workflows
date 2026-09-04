"""Schema-tolerant API client + step logging + double-verification.

Every call returns a StepRecord (raw request/response + interpretation) and
never raises on unexpected shapes; the caller adapts. Required-field schema
drift is surfaced via client.integration_issues (never silently absorbed).
"""

import json
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

from p2p_qa import config

# ---------------------------------------------------------------------------
# Schema policy: per endpoint, which fields are required vs optional.
# Missing optional -> warning. Missing required -> "break" -> integration issue.
# ---------------------------------------------------------------------------
EXPECTED_SCHEMAS: dict[str, dict] = {
    "GET /vendors": {
        "required": ["id", "name", "status"],
        "optional": ["contact_email", "bank_account_last4", "account_code", "created_at"],
    },
    "GET /vendors/{id}": {
        "required": ["id", "name", "status"],
        "optional": ["contact_email", "bank_account_last4", "account_code", "created_at"],
    },
    "POST /vendors": {
        "required": ["id", "name", "status"],
        "optional": ["contact_email", "bank_account_last4", "account_code", "created_at"],
    },
    "POST /purchase-orders": {
        "required": ["id", "vendor_id", "status", "line_items"],
        "optional": ["created_at", "receipt"],
    },
    "POST /purchase-orders/{id}/submit": {
        "required": ["id", "status"],
        "optional": ["receipt"],
    },
    "POST /purchase-orders/{id}/receive": {
        "required": ["id", "status", "receipt"],
        "optional": ["received_at", "received_value_cents"],
    },
    "GET /purchase-orders/{id}": {
        "required": ["id", "vendor_id", "status", "line_items"],
        "optional": ["receipt", "received_value_cents"],
    },
    "POST /invoices": {
        "required": ["id", "invoice_number", "vendor_id", "po_id", "amount_cents", "status"],
        "optional": ["account_code", "match"],
    },
    "GET /invoices/{id}": {
        "required": ["id", "invoice_number", "vendor_id", "po_id", "amount_cents", "status"],
        "optional": ["account_code", "match", "gl_post"],
    },
    "POST /invoices/{id}/match": {
        "required": ["id", "status", "match"],
        "optional": [],
    },
    "POST /invoices/{id}/approve": {
        "required": ["id", "status"],
        "optional": ["gl_post", "approved_at"],
    },
    "GET /vendors/{id}/exposure": {
        "required": ["vendor_id", "open_ap_cents"],
        "optional": [],
    },
}


@dataclass
class SchemaIssue:
    endpoint: str
    field: str
    severity: str  # "warn" | "break"
    detail: str

    def to_dict(self) -> dict:
        return {"endpoint": self.endpoint, "field": self.field,
                "severity": self.severity, "detail": self.detail}


def validate_response(endpoint: str, payload) -> list[SchemaIssue]:
    """Check a response payload against EXPECTED_SCHEMAS. Never raises."""
    schema = EXPECTED_SCHEMAS.get(endpoint)
    if schema is None:
        return []
    items = payload if isinstance(payload, list) else [payload]
    issues: list[SchemaIssue] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for f in schema["required"]:
            if f not in item:
                issues.append(SchemaIssue(endpoint, f, "break",
                                          f"required field '{f}' missing"))
        for f in schema["optional"]:
            if f not in item:
                issues.append(SchemaIssue(endpoint, f, "warn",
                                          f"optional field '{f}' missing"))
    return issues


@dataclass
class StepRecord:
    name: str
    method: str
    url: str
    request_payload: dict | None
    status_code: int | None
    response_payload: dict | list | None
    error: str | None = None
    duration_ms: float = 0.0
    interpretation: str | None = None
    verified: bool = False
    verify_note: str | None = None
    verifies: str | None = None  # if this GET is the double-verify proof for a create, that create's step name
    schema_issues: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "method": self.method, "url": self.url,
            "request_payload": self.request_payload,
            "status_code": self.status_code,
            "response_payload": self.response_payload,
            "error": self.error, "duration_ms": self.duration_ms,
            "interpretation": self.interpretation, "verified": self.verified,
            "verify_note": self.verify_note, "verifies": self.verifies,
            "schema_issues": [s.to_dict() if hasattr(s, "to_dict") else s
                              for s in self.schema_issues],
        }


class StepLogger:
    """Appends StepRecords as JSONL; iter_steps replays them."""

    def __init__(self, path: str):
        self.path = path
        self._fh = open(path, "a")

    def record(self, step: StepRecord) -> None:
        self._fh.write(json.dumps(step.to_dict()) + "\n")
        self._fh.flush()

    def iter_steps(self) -> list[StepRecord]:
        steps = []
        try:
            with open(self.path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        steps.append(StepRecord(**json.loads(line)))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except FileNotFoundError:
            return []
        return steps

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


class P2PClient:
    """Thin, schema-tolerant wrapper over the P2P API."""

    def __init__(self, base_url: str, token: str | None = None,
                 timeout: float = config.TIMEOUT_S, logger: StepLogger | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.logger = logger
        self.integration_issues: list[dict] = []
        self._client = httpx.Client(timeout=timeout)

    def _request(self, method: str, name: str, path: str,
                 payload: dict | None = None, schema_key: str | None = None,
                 quiet: bool = False) -> StepRecord:
        url = self.base_url + path
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        last_error = None
        attempts = 0
        while True:
            attempts += 1
            start = time.monotonic()
            try:
                resp = self._client.request(method, url, json=payload, headers=headers)
                duration = (time.monotonic() - start) * 1000.0
                try:
                    body = resp.json()
                except Exception:
                    body = {"raw": resp.text[:2000]}
                step = StepRecord(name=name, method=method, url=url,
                                  request_payload=payload, status_code=resp.status_code,
                                  response_payload=body, duration_ms=duration)
                if resp.status_code < 400 and schema_key:
                    issues = validate_response(schema_key, body)
                    step.schema_issues = issues
                    for iss in issues:
                        if iss.severity == "break":
                            entry = {"endpoint": schema_key, "field": iss.field,
                                     "severity": "break", "detail": iss.detail}
                            if entry not in self.integration_issues:
                                self.integration_issues.append(entry)
                if self.logger and not quiet:
                    self.logger.record(step)
                return step
            except httpx.HTTPError as e:
                last_error = e
                duration = (time.monotonic() - start) * 1000.0
                if attempts <= len(config.RETRY_BACKOFF_S[:3]):
                    time.sleep(config.RETRY_BACKOFF_S[attempts - 1])
                    continue
                step = StepRecord(name=name, method=method, url=url,
                                  request_payload=payload, status_code=None,
                                  response_payload=None, error=str(e),
                                  duration_ms=duration)
                if self.logger and not quiet:
                    self.logger.record(step)
                return step

    def verification_get(self, name: str, path: str, schema_key: str | None = None) -> StepRecord:
        """Fetch without logging (used as the double-verify proof GET); the
        caller logs the returned record exactly once with its verifies tag."""
        return self._request("GET", name, path, schema_key=schema_key, quiet=True)

    # ---- vendor ----
    def list_vendors(self) -> StepRecord:
        return self._request("GET", "list_vendors", "/vendors", schema_key="GET /vendors")

    def get_vendor(self, vendor_id: int) -> StepRecord:
        """GET detail; falls back to list+filter if the detail endpoint is absent."""
        rec = self._request("GET", "get_vendor", f"/vendors/{vendor_id}",
                            schema_key="GET /vendors/{id}")
        if rec.status_code == 404:
            lst = self._request("GET", "list_vendors", "/vendors", schema_key="GET /vendors")
            if lst.status_code < 400 and isinstance(lst.response_payload, list):
                found = [v for v in lst.response_payload if v.get("id") == vendor_id]
                if found:
                    rec = StepRecord(name="get_vendor", method="GET",
                                     url=f"{self.base_url}/vendors/{vendor_id}",
                                     request_payload=None, status_code=200,
                                     response_payload=found[0],
                                     duration_ms=rec.duration_ms,
                                     interpretation="detail endpoint absent; resolved via GET /vendors")
        return rec

    def create_vendor(self, name: str, status: str = "active",
                      contact_email: str | None = None,
                      bank_account_last4: str | None = None) -> StepRecord:
        payload = {"name": name, "status": status}
        if contact_email is not None:
            payload["contact_email"] = contact_email
        if bank_account_last4 is not None:
            payload["bank_account_last4"] = bank_account_last4
        return self._request("POST", "create_vendor", "/vendors", payload=payload,
                             schema_key="POST /vendors")

    # ---- purchase orders ----
    def create_po(self, vendor_id: int, line_items: list[dict]) -> StepRecord:
        return self._request("POST", "create_po", "/purchase-orders",
                             payload={"vendor_id": vendor_id, "line_items": line_items},
                             schema_key="POST /purchase-orders")

    def submit_po(self, po_id: int) -> StepRecord:
        return self._request("POST", "submit_po", f"/purchase-orders/{po_id}/submit",
                             schema_key="POST /purchase-orders/{id}/submit")

    def receive_po(self, po_id: int, lines: list[dict]) -> StepRecord:
        return self._request("POST", "receive_po", f"/purchase-orders/{po_id}/receive",
                             payload={"lines": lines},
                             schema_key="POST /purchase-orders/{id}/receive")

    def get_po(self, po_id: int) -> StepRecord:
        return self._request("GET", "get_po", f"/purchase-orders/{po_id}",
                             schema_key="GET /purchase-orders/{id}")

    # ---- invoices ----
    def create_invoice(self, invoice_number: str, vendor_id: int, po_id: int,
                       amount_cents: int, account_code: str | None = None) -> StepRecord:
        payload = {"invoice_number": invoice_number, "vendor_id": vendor_id,
                   "po_id": po_id, "amount_cents": amount_cents}
        if account_code is not None:
            payload["account_code"] = account_code
        return self._request("POST", "create_invoice", "/invoices", payload=payload,
                             schema_key="POST /invoices")

    def match_invoice(self, invoice_id: int) -> StepRecord:
        return self._request("POST", "match_invoice", f"/invoices/{invoice_id}/match",
                             schema_key="POST /invoices/{id}/match")

    def approve_invoice(self, invoice_id: int) -> StepRecord:
        return self._request("POST", "approve_invoice", f"/invoices/{invoice_id}/approve",
                             schema_key="POST /invoices/{id}/approve")

    def get_invoice(self, invoice_id: int) -> StepRecord:
        return self._request("GET", "get_invoice", f"/invoices/{invoice_id}",
                             schema_key="GET /invoices/{id}")

    # ---- exposure / generic ----
    def get_exposure(self, vendor_id: int) -> StepRecord:
        return self._request("GET", "get_exposure", f"/vendors/{vendor_id}/exposure",
                             schema_key="GET /vendors/{id}/exposure")

    def raw(self, method: str, path: str, payload: dict | None = None) -> StepRecord:
        """Generic call for adversarial probes (no schema validation)."""
        return self._request(method, f"raw {method} {path}", path, payload=payload)

    def verify_get(self, create: StepRecord, get_fn: Callable[[], StepRecord],
                   expected_fields: dict):
        """Double-verify a create: run the GET proof, record it, return (ok, note).

        Marks the create with verified/verify_note and tags the proof GET with
        verifies=<create step name>. The GET is the verification itself; it is
        never marked verified its own right.
        """
        got = get_fn()
        ok, note = self._check_persisted(create, got, expected_fields)
        # The create carries verified/verify_note (set by the caller after
        # this). The GET is the verification itself — tag it as the prover
        # (verifies=<create>), never as verified. This method does NOT log;
        # the caller records the proof GET exactly once.
        if got is not None:
            got.verifies = create.name
            got.interpretation = note
        return ok, note, got


    def _check_persisted(self, create: StepRecord, got: StepRecord | None,
                         expected_fields: dict) -> tuple[bool, str]:
        """Return (ok, note) for whether get_fn's response proves the create
        persisted and echoes expected_fields. Does NOT fire or log a GET."""
        if got is None:
            return False, "no GET proof available"
        if got.status_code >= 400:
            return False, f"GET proof failed ({got.status_code}): resource did not persist"
        mismatches = []
        for field, expected in expected_fields.items():
            actual = (got.response_payload or {}).get(field)
            if actual != expected:
                mismatches.append(f"{field}: expected {expected!r}, got {actual!r}")
        if mismatches:
            return False, "POST/GET discrepancy: " + "; ".join(mismatches)
        return True, "GET proof matches POST values"


def double_verify(client: P2PClient, create: StepRecord, get_fn: Callable[[], StepRecord],
                  expected_fields: dict) -> tuple[bool, StepRecord | None, str]:
    """Verify a create actually persisted: run get_fn and compare fields.

    Returns (ok, get_record, note). POST responses are never trusted alone.
    """
    if create.status_code >= 400:
        return (False, None, f"create failed ({create.status_code}); nothing to verify")
    try:
        got = get_fn()
    except Exception as e:  # noqa: BLE001
        return (False, None, f"GET proof failed: {e}")
    if got.status_code >= 400:
        return (False, got, f"GET proof failed ({got.status_code}): resource did not persist")
    mismatches = []
    for field, expected in expected_fields.items():
        actual = (got.response_payload or {}).get(field)
        if actual != expected:
            mismatches.append(f"{field}: expected {expected!r}, got {actual!r}")
    if mismatches:
        return (False, got, "POST/GET discrepancy: " + "; ".join(mismatches))
    return (True, got, "GET proof matches POST values")