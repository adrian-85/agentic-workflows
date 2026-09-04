"""Synthetic data stress test: generate ~50 randomized POs with varying
partial receipts and mismatched invoice amounts, run the adversarial probes
against each, and surface the per-rule failure rate (BREACHED / total).

Uses the mock app in-process via FastAPI TestClient (fast, no subprocess).
"""

import random

from fastapi.testclient import TestClient

from p2p_qa import config
from p2p_qa.mock_api import create_app

_SKUS = [
    ("BRICK-001", "Standard brick", 1200),
    ("CEM-002", "Portland cement 50kg", 850),
    ("LMB-003", "Lumber 2x4", 340),
    ("PLY-004", "Plywood sheet", 2400),
    ("GLU-005", "Construction adhesive", 700),
]

_MISMATCHES = ("exact", "plus_1_cent", "plus_10pct", "double", "zero")


def generate_po_plan(seed: int = 0, n: int = 50) -> list[dict]:
    """Randomized PO plans: qty 1-20, price from a small set, random partial
    receipt fraction (0, 25%, 50%, 100%), invoice amount = received value with
    a random mismatch (exact / +1 cent / +10% / 2x / zero)."""
    rng = random.Random(seed)
    plans = []
    for i in range(n):
        sku, desc, price = rng.choice(_SKUS)
        qty = rng.randint(1, 20)
        receipt_fraction = rng.choice([0.0, 0.25, 0.5, 1.0])
        invoice_mismatch = rng.choice(_MISMATCHES)
        plans.append({
            "vendor_name": f"StressVendor-{seed}-{i}",
            "line_items": [{"sku": sku, "description": desc,
                            "unit_price_cents": price, "quantity": qty}],
            "receipt_fraction": receipt_fraction,
            "invoice_mismatch": invoice_mismatch,
        })
    return plans


def _received_cents(plan: dict, received_qty: int) -> int:
    return plan["line_items"][0]["unit_price_cents"] * received_qty


def _invoice_amount_for(plan: dict, received_cents: int) -> int:
    m = plan["invoice_mismatch"]
    if m == "exact":
        return received_cents
    if m == "plus_1_cent":
        return received_cents + 1
    if m == "plus_10pct":
        return received_cents + received_cents // 10
    if m == "double":
        return received_cents * 2
    if m == "zero":
        return 0
    return received_cents


def _run_plan_probes(c, plan: dict, inv_no: str) -> dict:
    """Run the overpayment / partial / duplicate / mis-credit probes for one PO.
    Returns {rule: status} for that PO."""
    out: dict[str, str] = {}

    # vendor + PO
    v = c.post("/vendors", json={"name": plan["vendor_name"], "status": "active"}).json()
    po = c.post("/purchase-orders", json={
        "vendor_id": v["id"], "line_items": plan["line_items"]}).json()
    c.post(f"/purchase-orders/{po['id']}/submit").raise_for_status()

    # partial receipt
    qty = plan["line_items"][0]["quantity"]
    received_qty = int(qty * plan["receipt_fraction"])
    rec = c.post(f"/purchase-orders/{po['id']}/receive", json={
        "lines": [{"sku": plan["line_items"][0]["sku"],
                   "quantity_received": received_qty}]})
    if rec.status_code != 200:
        out["partial_receipt_flag"] = "BREACHED" if received_qty > 0 else "HELD"
        out["overpayment_protection"] = "NOT_TESTED"
        return out

    received_cents = _received_cents(plan, received_qty)
    amount = _invoice_amount_for(plan, received_cents)

    # overpayment probe
    inv = c.post("/invoices", json={"invoice_number": inv_no, "vendor_id": v["id"],
                                    "po_id": po["id"], "amount_cents": amount})
    if inv.status_code == 400:
        out["overpayment_protection"] = "HELD"   # rejected (incl. +1 cent / zero edge)
        out["partial_receipt_flag"] = "HELD"
        return out
    match = c.post(f"/invoices/{inv.json()['id']}/match")
    if amount > received_cents:
        out["overpayment_protection"] = "BREACHED" if match.status_code == 200 else "HELD"
    else:
        out["overpayment_protection"] = "HELD"
    # partial flag check when receipt was partial and match succeeded
    body = match.json() if match.status_code == 200 else {}
    is_partial = received_qty < qty
    if is_partial and match.status_code == 200:
        out["partial_receipt_flag"] = ("HELD" if (body.get("match") or {}).get("partial") is True
                                       else "BREACHED")
    elif is_partial and match.status_code == 400:
        out["partial_receipt_flag"] = "HELD"
    else:
        out["partial_receipt_flag"] = "HELD" if match.status_code == 200 else "NOT_TESTED"

    # duplicate probe: same invoice_number same vendor -> second must 400
    dup = c.post("/invoices", json={"invoice_number": inv_no, "vendor_id": v["id"],
                                    "po_id": po["id"], "amount_cents": amount})
    out["duplicate_detection"] = "HELD" if dup.status_code == 400 else "BREACHED"

    # mis-credit probe: account_code of another entity must be rejected
    mcr = c.post("/invoices", json={"invoice_number": inv_no + "-MC",
                                    "vendor_id": v["id"], "po_id": po["id"],
                                    "amount_cents": amount, "account_code": "ACC-999"})
    out["mis_credit"] = "HELD" if mcr.status_code == 400 else "BREACHED"
    return out


def run_stress(seed: int = 0, bug_profile: str = "clean", n: int = 50) -> dict:
    plans = generate_po_plan(seed=seed, n=n)
    app = create_app(bug_profile=bug_profile, seed=seed)
    c = TestClient(app)

    tally: dict[str, dict[str, int]] = {}
    for i, plan in enumerate(plans):
        inv_no = f"INV-STRESS-{seed}-{i}"
        try:
            verdicts = _run_plan_probes(c, plan, inv_no)
        except Exception:  # noqa: BLE001 — a plan that 500s is itself a failure signal
            verdicts = {"overpayment_protection": "BREACHED",
                        "duplicate_detection": "BREACHED"}
        for rule, status in verdicts.items():
            if status not in ("HELD", "BREACHED"):
                continue
            d = tally.setdefault(rule, {"tested": 0, "breached": 0})
            d["tested"] += 1
            if status == "BREACHED":
                d["breached"] += 1

    failure_rate = {}
    for rule, d in tally.items():
        failure_rate[rule] = round(d["breached"] / d["tested"], 3) if d["tested"] else 0.0
    return {"failure_rate": failure_rate, "total": n, "seed": seed,
            "bug_profile": bug_profile}