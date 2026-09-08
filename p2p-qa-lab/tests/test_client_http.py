# pylint: disable=missing-function-docstring,missing-class-docstring,missing-module-docstring,protected-access,too-many-lines,invalid-name
# unittest/pytest method names are self-documenting (no docstrings needed).
# protected-access: tests white-box the _ helpers they test — that IS the contract.
# too-many-lines: test files may exceed 1000 lines when they map 1:1 to a source file.
# invalid-name: OOXML fixture names (pPr, numId, ...) mirror the schema.

import pytest
from p2p_qa.client import P2PClient, double_verify

pytestmark = pytest.mark.usefixtures("p2p_api")


def test_wrapper_methods_against_clean(request):
    base = request.getfixturevalue("p2p_api")
    c = P2PClient(base)
    r = c.create_vendor("WrapCo", "active")
    assert r.status_code == 201
    vid = r.response_payload["id"]
    assert c.get_vendor(vid).status_code == 200
    assert c.list_vendors().status_code == 200


def test_4xx_returns_record_not_raise(request):
    base = request.getfixturevalue("p2p_api")
    c = P2PClient(base)
    r = c.create_po(999999, [{"sku": "S", "description": "d", "unit_price_cents": 100, "quantity": 1}])
    assert r.status_code == 400
    assert "detail" in r.response_payload


def test_double_verify_ok_when_persisted(request):
    base = request.getfixturevalue("p2p_api")
    c = P2PClient(base)
    create = c.create_vendor("VerifyCo", "active")
    vid = create.response_payload["id"]
    ok, get_rec, _ = double_verify(create, lambda: c.get_vendor(vid),
                                      {"name": "VerifyCo", "status": "active"})
    assert ok is True and get_rec.status_code == 200


@pytest.mark.parametrize("p2p_api", ["phantom_write"], indirect=True)
def test_double_verify_fails_on_phantom(request):
    base = request.getfixturevalue("p2p_api")
    c = P2PClient(base)
    create = c.create_vendor("GhostCo", "active")
    vid = create.response_payload["id"]
    ok, get_rec, _ = double_verify(create, lambda: c.get_vendor(vid), {"name": "GhostCo"})
    assert ok is False and get_rec.status_code == 404
