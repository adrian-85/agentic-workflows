import httpx
import pytest

pytestmark = pytest.mark.usefixtures("p2p_api")


def _base(request) -> str:
    return request.getfixturevalue("p2p_api")


def _setup_received(c, vid, price=1000, qty=1, received=None):
    """Create vendor + PO, submit, receive; returns (vendor_id, po_id, po)."""
    po = c.post("/purchase-orders", json={"vendor_id": vid, "line_items": [
        {"sku": "S", "description": "d", "unit_price_cents": price, "quantity": qty}]})
    po.raise_for_status()
    po_id = po.json()["id"]
    c.post(f"/purchase-orders/{po_id}/submit").raise_for_status()
    received = qty if received is None else received
    c.post(f"/purchase-orders/{po_id}/receive",
           json={"lines": [{"sku": "S", "quantity_received": received}]}).raise_for_status()
    return vid, po_id


def test_create_vendor_then_list(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        r = c.post("/vendors", json={"name": "NewCo", "status": "active"})
        assert r.status_code == 201, r.text
        vid = r.json()["id"]
        assert any(v["id"] == vid for v in c.get("/vendors").json())


def test_happy_path_end_to_end(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "HappyCo", "status": "active"}).json()["id"]
        poj = c.post("/purchase-orders", json={"vendor_id": vid, "line_items": [
            {"sku": "SKU-1", "description": "Widget", "unit_price_cents": 500, "quantity": 10}]}).json()
        po_id = poj["id"]
        assert poj["status"] == "draft"
        c.post(f"/purchase-orders/{po_id}/submit").raise_for_status()
        c.post(f"/purchase-orders/{po_id}/receive",
               json={"lines": [{"sku": "SKU-1", "quantity_received": 4}]}).raise_for_status()
        inv = c.post("/invoices", json={"invoice_number": "INV-001", "vendor_id": vid,
                                        "po_id": po_id, "amount_cents": 2000}).json()
        m = c.post(f"/invoices/{inv['id']}/match")
        assert m.status_code == 200, m.text
        body = m.json()
        assert body["match"]["partial"] is True
        assert body["match"]["received_value_cents"] == 2000
        a = c.post(f"/invoices/{inv['id']}/approve")
        assert a.status_code == 200, a.text
        gl = a.json()["gl_post"]
        assert gl["balanced"] is True
        assert sum(e["debit_cents"] for e in gl["entries"]) == sum(e["credit_cents"] for e in gl["entries"])


def test_rule1_overpayment_rejected(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "OverCo", "status": "active"}).json()["id"]
        _, po_id = _setup_received(c, vid)
        inv = c.post("/invoices", json={"invoice_number": "INV-OVR", "vendor_id": vid,
                                        "po_id": po_id, "amount_cents": 1001}).json()
        r = c.post(f"/invoices/{inv['id']}/match")
        assert r.status_code == 400          # received 10.00, invoiced 10.01 -> +1 cent
        assert "received" in r.json()["detail"].lower()


def test_rule1_equality_legal(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "ExactCo", "status": "active"}).json()["id"]
        _, po_id = _setup_received(c, vid)
        inv = c.post("/invoices", json={"invoice_number": "INV-EX", "vendor_id": vid,
                                        "po_id": po_id, "amount_cents": 1000}).json()
        assert c.post(f"/invoices/{inv['id']}/match").status_code == 200


def test_rule2_approve_without_match(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "GateCo", "status": "active"}).json()["id"]
        _, po_id = _setup_received(c, vid)
        inv = c.post("/invoices", json={"invoice_number": "INV-NM", "vendor_id": vid,
                                        "po_id": po_id, "amount_cents": 1000}).json()
        r = c.post(f"/invoices/{inv['id']}/approve")
        assert r.status_code == 400
        assert "matched" in r.json()["detail"].lower()


def test_rule4_inactive_vendor_po(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        r = c.post("/purchase-orders", json={"vendor_id": 2, "line_items": [
            {"sku": "S", "description": "d", "unit_price_cents": 1000, "quantity": 1}]})
        assert r.status_code == 400
        assert "inactive" in r.json()["detail"].lower()


def test_rule5_gl_balanced(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "BalCo", "status": "active"}).json()["id"]
        _, po_id = _setup_received(c, vid, price=700, qty=2)
        inv = c.post("/invoices", json={"invoice_number": "INV-GL", "vendor_id": vid,
                                        "po_id": po_id, "amount_cents": 1400}).json()
        c.post(f"/invoices/{inv['id']}/match").raise_for_status()
        gl = c.post(f"/invoices/{inv['id']}/approve").json()["gl_post"]
        assert gl["balanced"] is True


def test_rule6_duplicate_invoice_rejected(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "DupCo", "status": "active"}).json()["id"]
        _, po_id = _setup_received(c, vid)
        ok = c.post("/invoices", json={"invoice_number": "INV-DUP", "vendor_id": vid,
                                       "po_id": po_id, "amount_cents": 1000})
        assert ok.status_code == 201
        dup = c.post("/invoices", json={"invoice_number": "INV-DUP", "vendor_id": vid,
                                        "po_id": po_id, "amount_cents": 1000})
        assert dup.status_code == 400
        assert "duplicate" in dup.json()["detail"].lower()


def test_miscredit_account_code_rejected(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "FraudCo", "status": "active"}).json()["id"]
        _, po_id = _setup_received(c, vid)
        # account_code owned by another vendor (ACC-999 not this vendor's) is rejected at create
        r = c.post("/invoices", json={"invoice_number": "INV-FRAUD", "vendor_id": vid,
                                      "po_id": po_id, "amount_cents": 1000,
                                      "account_code": "ACC-999"})
        assert r.status_code == 400
        assert "account" in r.json()["detail"].lower()


def test_over_receipt_rejected(request):
    base = _base(request)
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "RecvCo", "status": "active"}).json()["id"]
        po = c.post("/purchase-orders", json={"vendor_id": vid, "line_items": [
            {"sku": "S", "description": "d", "unit_price_cents": 1000, "quantity": 5}]}).json()
        c.post(f"/purchase-orders/{po['id']}/submit").raise_for_status()
        r = c.post(f"/purchase-orders/{po['id']}/receive",
                   json={"lines": [{"sku": "S", "quantity_received": 6}]})
        assert r.status_code == 400