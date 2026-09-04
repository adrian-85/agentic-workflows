import httpx
import pytest

pytestmark = pytest.mark.usefixtures("p2p_api")


@pytest.mark.parametrize("p2p_api", ["overpayment_leak"], indirect=True)
def test_overpayment_leak_allows_breach(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "LeakCo", "status": "active"}).json()["id"]
        po = c.post("/purchase-orders", json={"vendor_id": vid, "line_items": [
            {"sku": "S", "description": "d", "unit_price_cents": 1000, "quantity": 1}]}).json()
        c.post(f"/purchase-orders/{po['id']}/submit").raise_for_status()
        c.post(f"/purchase-orders/{po['id']}/receive", json={"lines": [{"sku": "S", "quantity_received": 1}]}).raise_for_status()
        inv = c.post("/invoices", json={"invoice_number": "INV-LEAK", "vendor_id": vid,
                                        "po_id": po["id"], "amount_cents": 5000}).json()
        assert c.post(f"/invoices/{inv['id']}/match").status_code == 200  # engine bug: accepts 5x


@pytest.mark.parametrize("p2p_api", ["partial_flag_missing"], indirect=True)
def test_partial_flag_missing_hides_flag(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "FlagCo", "status": "active"}).json()["id"]
        po = c.post("/purchase-orders", json={"vendor_id": vid, "line_items": [
            {"sku": "S", "description": "d", "unit_price_cents": 1000, "quantity": 10}]}).json()
        c.post(f"/purchase-orders/{po['id']}/submit").raise_for_status()
        c.post(f"/purchase-orders/{po['id']}/receive", json={"lines": [{"sku": "S", "quantity_received": 3}]}).raise_for_status()
        inv = c.post("/invoices", json={"invoice_number": "INV-PART", "vendor_id": vid,
                                        "po_id": po["id"], "amount_cents": 3000}).json()
        body = c.post(f"/invoices/{inv['id']}/match").json()
        assert body["match"]["partial"] is not True  # bug: flag suppressed


@pytest.mark.parametrize("p2p_api", ["gl_unbalanced"], indirect=True)
def test_gl_unbalanced_posts_uneven(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "GlCo", "status": "active"}).json()["id"]
        po = c.post("/purchase-orders", json={"vendor_id": vid, "line_items": [
            {"sku": "S", "description": "d", "unit_price_cents": 1000, "quantity": 1}]}).json()
        c.post(f"/purchase-orders/{po['id']}/submit").raise_for_status()
        c.post(f"/purchase-orders/{po['id']}/receive", json={"lines": [{"sku": "S", "quantity_received": 1}]}).raise_for_status()
        inv = c.post("/invoices", json={"invoice_number": "INV-GLB", "vendor_id": vid,
                                        "po_id": po["id"], "amount_cents": 1000}).json()
        c.post(f"/invoices/{inv['id']}/match").raise_for_status()
        gl = c.post(f"/invoices/{inv['id']}/approve").json()["gl_post"]
        assert gl["balanced"] is not True  # bug: credit is amount-1


@pytest.mark.parametrize("p2p_api", ["duplicate_leak"], indirect=True)
def test_duplicate_leak_allows_dupe(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        vid = c.post("/vendors", json={"name": "DupCo", "status": "active"}).json()["id"]
        po = c.post("/purchase-orders", json={"vendor_id": vid, "line_items": [
            {"sku": "S", "description": "d", "unit_price_cents": 1000, "quantity": 1}]}).json()
        c.post(f"/purchase-orders/{po['id']}/submit").raise_for_status()
        c.post(f"/purchase-orders/{po['id']}/receive", json={"lines": [{"sku": "S", "quantity_received": 1}]}).raise_for_status()
        assert c.post("/invoices", json={"invoice_number": "INV-DUP", "vendor_id": vid,
                                         "po_id": po["id"], "amount_cents": 1000}).status_code == 201
        assert c.post("/invoices", json={"invoice_number": "INV-DUP", "vendor_id": vid,
                                         "po_id": po["id"], "amount_cents": 1000}).status_code == 201  # bug: dupe allowed


@pytest.mark.parametrize("p2p_api", ["phantom_write"], indirect=True)
def test_phantom_write_404s_on_get(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        r = c.post("/vendors", json={"name": "GhostCo", "status": "active"})
        assert r.status_code == 201
        assert c.get(f"/vendors/{r.json()['id']}").status_code == 404  # never persisted


@pytest.mark.parametrize("p2p_api", ["post_get_mismatch"], indirect=True)
def test_post_get_mismatch_differs(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        r = c.post("/vendors", json={"name": "LiarCo", "status": "active"})
        body = r.json()
        got = c.get(f"/vendors/{body['id']}").json()
        assert got["name"] != body["name"]  # POST lied, GET exposes truth


@pytest.mark.parametrize("p2p_api", ["pii_leak"], indirect=True)
def test_pii_leak_exposes_secret_fields(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        v = c.get("/vendors").json()[0]
        assert "password" in v or "bank_account_full" in v  # bug: full secrets exposed


@pytest.mark.require_auth
@pytest.mark.parametrize("p2p_api", ["clean"], indirect=True)
def test_require_auth_blocks_unauthenticated(request):
    base = request.getfixturevalue("p2p_api")
    with httpx.Client(base_url=base) as c:
        assert c.get("/vendors").status_code == 401
        assert c.get("/vendors", headers={"Authorization": "Bearer dev-token-1234"}).status_code == 200