"""Mock P2P API — faithful rehearsal target for the QA agent.

Runs standalone:  python -m p2p_qa.mock_api [--host H] [--port P]
                  [--bug-profile X] [--require-auth] [--seed N]

Environment overrides (used by the test harness / demo):
  P2P_BUG_PROFILE, P2P_REQUIRE_AUTH

Profiles:
  clean               financial invariants enforced, but a REALISTIC messy
                      legacy API: authless (vendor PII incl. bank_account_last4
                      + contact_email exposed to any caller), no input
                      sanitization (injection payloads stored verbatim). The
                      agent should surface authorization / pii_exposure /
                      injection findings. Auditors would flag all three.
  overpayment_leak    rule 1 not enforced (invoice > received accepted at match)
  duplicate_leak      rule 6 not enforced
  gl_unbalanced       rule 5 broken (GL post with unequal debits/credits)
  partial_flag_missing rule 3 broken (match silently passes partial receipts)
  phantom_write       create endpoints return 201 but never persist (GET 404s)
  post_get_mismatch   POST returns one set of values, GET proves different ones
  pii_leak            vendor list/detail expose password + full account number

Money is integer cents everywhere. Amounts may arrive as int or string.
"""

import argparse
import os
import threading
import time
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from p2p_qa import config, money

_now = lambda: datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, bug_profile: str, seed: int):
        self.bug_profile = bug_profile
        self.seed = seed
        self.vendors: dict[int, dict] = {}
        self.pos: dict[int, dict] = {}
        self.invoices: dict[int, dict] = {}
        self._next = {"vendor": 3, "po": 102, "invoice": 1}
        self._init_seed()

    def _init_seed(self):
        self.vendors[1] = {
            "id": 1, "name": "Acme Building Supply", "status": "active",
            "account_code": "ACC-100", "contact_email": "ap@acme.test",
            "bank_account_last4": "1234", "created_at": _now(),
        }
        self.vendors[2] = {
            "id": 2, "name": "Blocked Materials Co", "status": "inactive",
            "account_code": "ACC-200", "contact_email": "ar@blocked.test",
            "bank_account_last4": "5678", "created_at": _now(),
        }
        self.pos[101] = {
            "id": 101, "vendor_id": 1, "status": "submitted",
            "line_items": [{"sku": "BRICK-001", "description": "Standard brick",
                            "unit_price_cents": 1200, "quantity": 100}],
            "receipt": None, "created_at": _now(),
        }

    def new_id(self, kind: str) -> int:
        i = self._next[kind]
        self._next[kind] += 1
        return i


def _allowed(bug_profile: str, *profiles: str) -> bool:
    return bug_profile in profiles


def create_app(bug_profile: str = "clean", require_auth: bool = False, seed: int = 0):
    store = Store(bug_profile, seed)
    app = FastAPI(title=f"P2P Mock API ({bug_profile})")
    lock = threading.Lock()

    async def guard(authorization: str | None = Header(default=None)):
        if not require_auth:
            return
        if authorization != f"Bearer {config.SEED_TOKEN}":
            raise HTTPException(status_code=401, detail="Not authenticated")

    def vendor_out(v: dict) -> dict:
        out = dict(v)
        if bug_profile == "pii_leak":
            out["password"] = "hunter2"
            out["bank_account_full"] = "1111222233334444"
        return out

    def get_vendor_or_404(vid: int) -> dict:
        v = store.vendors.get(vid)
        if v is None:
            raise HTTPException(status_code=404, detail="vendor not found")
        return v

    def get_po_or_404(pid: int) -> dict:
        p = store.pos.get(pid)
        if p is None:
            raise HTTPException(status_code=404, detail="purchase order not found")
        return p

    def get_invoice_or_404(iid: int) -> dict:
        i = store.invoices.get(iid)
        if i is None:
            raise HTTPException(status_code=404, detail="invoice not found")
        return i

    def po_received_value(p: dict) -> int:
        receipt = p.get("receipt") or {}
        if not receipt:
            return 0
        by_sku = {l["sku"]: l for l in p["line_items"]}
        total = 0
        for rl in receipt.get("lines", []):
            item = by_sku[rl["sku"]]
            total += money.line_value_cents(item["unit_price_cents"], rl["quantity_received"])
        return total

    def po_partial(p: dict) -> bool:
        receipt = p.get("receipt") or {}
        if not receipt:
            return False
        by_sku = {l["sku"]: l for l in p["line_items"]}
        return any(rl["quantity_received"] < by_sku[rl["sku"]]["quantity"]
                   for rl in receipt.get("lines", []))

    # ---------------- vendors ----------------
    @app.get("/vendors")
    async def list_vendors(_=Depends(guard)):
        with lock:
            return [vendor_out(v) for v in store.vendors.values()]

    @app.get("/vendors/{vendor_id}")
    async def get_vendor(vendor_id: int, _=Depends(guard)):
        with lock:
            return vendor_out(get_vendor_or_404(vendor_id))

    @app.post("/vendors", status_code=201)
    async def create_vendor(body: dict, _=Depends(guard)):
        with lock:
            name = (body.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="name is required")
            status = body.get("status", "active")
            if status not in ("active", "inactive"):
                raise HTTPException(status_code=422, detail="status must be active|inactive")
            vid = store.new_id("vendor")
            rec = {
                "id": vid, "name": name, "status": status,
                "account_code": body.get("account_code") or f"ACC-{vid}",
                "contact_email": body.get("contact_email"),
                "bank_account_last4": body.get("bank_account_last4"),
                "created_at": _now(),
            }
            if _allowed(bug_profile, "phantom_write"):
                return vendor_out(rec)          # never persisted
            stored = dict(rec)
            if bug_profile == "post_get_mismatch":
                stored["name"] = name + " (persisted)"
            store.vendors[vid] = stored
            return vendor_out(rec)

    # ---------------- purchase orders ----------------
    @app.post("/purchase-orders", status_code=201)
    async def create_po(body: dict, _=Depends(guard)):
        with lock:
            vid = body.get("vendor_id")
            v = store.vendors.get(vid)
            if v is None:
                raise HTTPException(status_code=400, detail="vendor not found")
            if v["status"] != "active":
                raise HTTPException(status_code=400, detail="inactive vendor: no new POs")
            lines = body.get("line_items") or []
            if not lines:
                raise HTTPException(status_code=422, detail="line_items required")
            for ln in lines:
                if ln.get("quantity", 0) < 0 or ln.get("unit_price_cents", 0) < 0:
                    raise HTTPException(status_code=422, detail="negative quantity or price")
            pid = store.new_id("po")
            rec = {
                "id": pid, "vendor_id": vid, "status": "draft",
                "line_items": lines, "receipt": None, "created_at": _now(),
            }
            if _allowed(bug_profile, "phantom_write"):
                return rec
            stored = dict(rec)
            if bug_profile == "post_get_mismatch":
                stored["line_items"] = [
                    {"sku": l["sku"], "description": l["description"],
                     "unit_price_cents": l["unit_price_cents"],
                     "quantity": max(1, l["quantity"] // 2)} for l in lines
                ]
            store.pos[pid] = stored
            return rec

    @app.post("/purchase-orders/{po_id}/submit")
    async def submit_po(po_id: int, _=Depends(guard)):
        with lock:
            p = get_po_or_404(po_id)
            if p["status"] != "draft":
                raise HTTPException(status_code=400, detail="PO must be draft to submit")
            p["status"] = "submitted"
            return p

    @app.post("/purchase-orders/{po_id}/receive")
    async def receive_po(po_id: int, body: dict, _=Depends(guard)):
        with lock:
            p = get_po_or_404(po_id)
            if p["status"] not in ("submitted", "received"):
                raise HTTPException(status_code=400, detail="PO must be submitted to receive")
            lines = body.get("lines") or []
            if not lines:
                raise HTTPException(status_code=422, detail="lines required")
            by_sku = {l["sku"]: l for l in p["line_items"]}
            so_far: dict[str, int] = {}
            for rl in (p.get("receipt") or {}).get("lines", []):
                so_far[rl["sku"]] = so_far.get(rl["sku"], 0) + rl["quantity_received"]
            for rl in lines:
                if rl.get("quantity_received", 0) < 0:
                    raise HTTPException(status_code=422, detail="negative receipt qty")
                item = by_sku.get(rl["sku"])
                if item is None:
                    raise HTTPException(status_code=400, detail="sku not on PO")
                new_total = so_far.get(rl["sku"], 0) + rl["quantity_received"]
                if new_total > item["quantity"]:
                    raise HTTPException(status_code=400,
                                        detail=f"over-receipt: {rl['sku']} {new_total}>{item['quantity']}")
                so_far[rl["sku"]] = new_total
            new_lines = list((p.get("receipt") or {}).get("lines", []))
            for rl in lines:
                new_lines.append(rl)
            p["receipt"] = {"lines": new_lines, "received_at": _now()}
            p["status"] = "received" if all(so_far[s] >= by_sku[s]["quantity"]
                                            for s in by_sku) else "submitted"
            return {**p, "received_value_cents": po_received_value(p)}

    @app.get("/purchase-orders/{po_id}")
    async def get_po(po_id: int, _=Depends(guard)):
        with lock:
            p = get_po_or_404(po_id)
            return {**p, "received_value_cents": po_received_value(p)}

    # ---------------- invoices ----------------
    @app.post("/invoices", status_code=201)
    async def create_invoice(body: dict, _=Depends(guard)):
        with lock:
            inv_no = (body.get("invoice_number") or "").strip()
            if not inv_no:
                raise HTTPException(status_code=400, detail="invoice_number required")
            vid = body.get("vendor_id")
            pid = body.get("po_id")
            v = store.vendors.get(vid)
            p = store.pos.get(pid)
            if v is None:
                raise HTTPException(status_code=400, detail="vendor not found")
            if p is None:
                raise HTTPException(status_code=400, detail="purchase order not found")
            if p["vendor_id"] != vid:
                raise HTTPException(status_code=400, detail="invoice vendor must match PO vendor")
            try:
                amount = money.parse_cents(body.get("amount_cents"))
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            if amount < 0:
                raise HTTPException(status_code=422, detail="negative invoice amount")
            norm = inv_no.casefold().replace(" ", "")
            if not _allowed(bug_profile, "duplicate_leak"):
                for i in store.invoices.values():
                    other = (i["invoice_number"] or "").casefold().replace(" ", "")
                    if i["vendor_id"] == vid and other == norm:
                        raise HTTPException(status_code=400, detail="duplicate invoice_number")
            acct = body.get("account_code") or v["account_code"]
            if acct != v["account_code"]:
                raise HTTPException(status_code=400,
                                    detail="account_code does not belong to vendor")
            iid = store.new_id("invoice")
            rec = {
                "id": iid, "invoice_number": inv_no, "vendor_id": vid, "po_id": pid,
                "amount_cents": amount, "status": "open", "account_code": acct,
                "match": None, "gl_post": None, "created_at": _now(),
            }
            if _allowed(bug_profile, "phantom_write"):
                return rec
            store.invoices[iid] = rec
            return rec

    @app.post("/invoices/{invoice_id}/match")
    async def match_invoice(invoice_id: int, _=Depends(guard)):
        with lock:
            inv = get_invoice_or_404(invoice_id)
            if inv["status"] in ("matched", "approved"):
                raise HTTPException(status_code=400, detail="invoice already matched or approved")
            p = get_po_or_404(inv["po_id"])
            if not p.get("receipt"):
                raise HTTPException(status_code=400, detail="no goods receipt on PO to match against")
            received = po_received_value(p)
            if inv["amount_cents"] > received and not _allowed(bug_profile, "overpayment_leak"):
                raise HTTPException(status_code=400,
                                    detail=f"invoice exceeds received value ({inv['amount_cents']}>{received})")
            partial = po_partial(p)
            if bug_profile == "partial_flag_missing":
                partial = False
            variance = received - inv["amount_cents"]
            inv["status"] = "matched"
            inv["match"] = {
                "status": "partial" if partial else "matched",
                "partial": partial,
                "received_value_cents": received,
                "invoice_amount_cents": inv["amount_cents"],
                "variance_cents": variance,
                "line_notes": ["partial receipt" if partial
                               else "fully received"],
            }
            return inv

    @app.post("/invoices/{invoice_id}/approve")
    async def approve_invoice(invoice_id: int, _=Depends(guard)):
        with lock:
            inv = get_invoice_or_404(invoice_id)
            if inv["status"] != "matched":
                raise HTTPException(status_code=400,
                                    detail="invoice must be matched before approval")
            if inv.get("approved_at"):
                raise HTTPException(status_code=400, detail="invoice already approved")
            amount = inv["amount_cents"]
            credit = amount - 1 if bug_profile == "gl_unbalanced" else amount
            entries = [
                {"account": "expense", "debit_cents": amount, "credit_cents": 0},
                {"account": "accounts_payable", "debit_cents": 0, "credit_cents": credit},
            ]
            inv["status"] = "approved"
            inv["approved_at"] = _now()
            inv["gl_post"] = {
                "entries": entries,
                "balanced": sum(e["debit_cents"] for e in entries)
                            == sum(e["credit_cents"] for e in entries),
            }
            return inv

    @app.get("/invoices/{invoice_id}")
    async def get_invoice(invoice_id: int, _=Depends(guard)):
        with lock:
            return get_invoice_or_404(invoice_id)

    # ---------------- exposure ----------------
    @app.get("/vendors/{vendor_id}/exposure")
    async def exposure(vendor_id: int, _=Depends(guard)):
        with lock:
            v = store.vendors.get(vendor_id)
            if v is None:
                raise HTTPException(status_code=404, detail="vendor not found")
            total = sum(i["amount_cents"] for i in store.invoices.values()
                        if i["vendor_id"] == vendor_id and i["status"] == "approved")
            return {"vendor_id": vendor_id, "open_ap_cents": total}

    return app


app = create_app()


def main(argv=None):
    parser = argparse.ArgumentParser(description="P2P mock API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--bug-profile", default=os.environ.get("P2P_BUG_PROFILE", "clean"),
                        choices=list(config.BUG_PROFILES))
    parser.add_argument("--require-auth", action="store_true",
                        default=os.environ.get("P2P_REQUIRE_AUTH") == "1")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    import uvicorn
    uvicorn.run(create_app(args.bug_profile, args.require_auth, args.seed),
                host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()