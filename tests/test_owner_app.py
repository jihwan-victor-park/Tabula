"""
The store owner's path: sign up → create a store → bring data → see stock → adjust by barcode
→ analysis → order suggestions → drafts. API level; the browser run is scripts/ui_walkthrough_owner.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from clawbot.api.app import create_app
from clawbot.domain.imports import google_sheets
from clawbot.persistence.db import transaction
from tests.test_imports import _apply, _csv, _mapping, _upload
from tests.test_replenishment_flow import NY, shop  # noqa: F401

WEB = {"X-Tabula-Client": "web"}


def _browser() -> TestClient:
    return TestClient(create_app())  # its own cookie jar


def _signup(c: TestClient, email="ann@corner.example", password="a long passphrase 1"):
    return c.post("/v1/auth/signup", json={"email": email, "password": password})


def _store(c: TestClient, **kw):
    body = {"name": "Corner Pets", "business_type": "pet", "timezone": "America/New_York", "currency": "USD", **kw}
    return c.post("/v1/stores", json=body, headers=WEB)


# ---------------------------------------------------------------------------
# Accounts and stores
# ---------------------------------------------------------------------------


def test_sign_up_creates_a_session_and_a_store_is_set_up_in_one_step():
    c = _browser()
    assert _signup(c).status_code == 201
    assert "tabula_session" in c.cookies
    store = _store(c).json()
    me = c.get("/v1/me").json()
    (m,) = me["memberships"]
    assert (m["tenant_name"], m["role"], m["business_type"], m["currency"], m["is_sample"]) == (
        "Corner Pets", "owner", "pet", "USD", False)
    locs = c.get("/v1/locations", headers={"X-Tenant-Id": store["tenant_id"]}).json()
    assert [(l["name"], l["timezone"]) for l in locs] == [("Corner Pets", "America/New_York")]


def test_passwords_sessions_and_lockout():
    c = _browser()
    assert _signup(c, password="short").status_code == 422
    _signup(c)
    assert _signup(_browser()).status_code == 409  # one account per email
    c.post("/v1/auth/logout", headers=WEB)
    assert c.get("/v1/me").status_code == 401  # session revoked server-side
    other = _browser()
    for _ in range(5):
        assert other.post("/v1/auth/login", json={"email": "ann@corner.example", "password": "wrong password!"}).status_code == 401
    locked = other.post("/v1/auth/login", json={"email": "ann@corner.example", "password": "a long passphrase 1"})
    assert locked.status_code == 401  # the failures were kept: even the right password waits
    unknown = other.post("/v1/auth/login", json={"email": "nobody@corner.example", "password": "a long passphrase 1"})
    assert locked.json()["detail"] == unknown.json()["detail"]  # a lock does not reveal that the email has an account
    with transaction() as s:
        s.execute(text("UPDATE user_credentials SET locked_until = NULL"))
    assert other.post("/v1/auth/login", json={"email": "ANN@corner.example", "password": "a long passphrase 1"}).status_code == 200


def test_cookie_sessions_need_the_client_header_for_changes():
    c = _browser()
    _signup(c)
    assert c.post("/v1/stores", json={"name": "X", "business_type": "pet", "timezone": "America/New_York"}).status_code == 403
    assert _store(c).status_code == 201


def test_another_account_cannot_see_the_store():
    a, b = _browser(), _browser()
    _signup(a)
    store = _store(a).json()
    _signup(b, email="bob@else.example")
    assert b.get("/v1/locations", headers={"X-Tenant-Id": store["tenant_id"]}).status_code == 403


def test_demo_sign_in_is_offered_only_in_dev_mode(monkeypatch):
    c = _browser()
    assert c.get("/v1/auth/options").json()["demo_sign_in"] is True
    monkeypatch.setenv("TABULA_AUTH_MODE", "password")
    assert c.get("/v1/auth/options").json()["demo_sign_in"] is False
    assert c.get("/v1/me", headers={"X-Dev-User": "x@y.example"}).status_code == 401  # header sign-in refused


# ---------------------------------------------------------------------------
# Stock, history, analytics, readiness
# ---------------------------------------------------------------------------


def test_stock_overview_says_how_fresh_each_number_is(shop):
    view = shop.get("/v1/stock/overview", params={"location_id": shop.location_id}).json()
    (row,) = view["items"]
    assert (row["sku"], row["on_hand"], row["daily_demand"], row["days_of_cover"]) == ("LITTER-20", "18", "6", "3")
    assert row["state"] == "at_risk" and row["stockout_date"]
    assert row["stock_as_of"] and row["stale"] is False and row["stock_source"]


def test_analytics_never_fills_days_without_data(shop):
    a = shop.get("/v1/analytics", params={"location_id": shop.location_id, "days": 28}).json()
    assert a["current"]["units"] == "168" and a["current"]["days_with_data"] == 28
    assert a["previous"]["units"] is None and a["previous"]["days_with_data"] == 0  # no data → no number
    assert a["top_sellers"][0]["sku"] == "LITTER-20"


def test_readiness_explains_what_is_missing(shop):
    r = shop.get("/v1/readiness", params={"location_id": shop.location_id}).json()
    features = {f["key"]: f for f in r["features"]}
    assert features["inventory"]["ready"] and features["suggestions"]["ready"]
    assert not features["orders"]["ready"]  # no ship-to address in this store
    assert any("address" in m["what"] for m in features["orders"]["missing"])


def test_without_sales_stock_works_but_suggestions_are_limited(client):
    from tests.conftest import new_store

    api = new_store(client, "new@corner.example", "New")
    api.location_id = api.post("/v1/locations", {"name": "Main", "timezone": "America/New_York"}).json()["id"]
    imp = _upload(api, "inventory", _csv([["SKU", "Name", "Qty", "Cost", "Supplier"], ["A-1", "Ball", "5", "2.10", "Acme"]]),
                  location_id=api.location_id).json()
    preview = api.get(f"/v1/imports/{imp['id']}/preview").json()
    assert {u["column"] for u in preview["unused_columns"]} == {"Cost", "Supplier"}
    _mapping(api, imp, as_of=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), create_missing_variants=True)
    _apply(api, imp)
    features = {f["key"]: f for f in api.get("/v1/readiness", params={"location_id": api.location_id}).json()["features"]}
    assert features["inventory"]["ready"] and not features["suggestions"]["ready"]
    row = api.get("/v1/stock/overview", params={"location_id": api.location_id}).json()["items"][0]
    assert (row["on_hand"], row["state"]) == ("5", "no_sales_data")


# ---------------------------------------------------------------------------
# Barcode actions
# ---------------------------------------------------------------------------


def _act(api, action, qty, key=None, **extra):
    return api.post("/v1/stock-actions", {"location_id": api.location_id, "variant_id": api.variant["id"], "action": action,
                                          "qty": qty, "request_key": key or f"k-{uuid.uuid4()}", **extra})


def _on_hand(api):
    return api.get("/v1/stock/overview", params={"location_id": api.location_id}).json()["items"][0]["on_hand"]


def test_a_scan_finds_the_item_and_only_the_chosen_action_changes_stock(shop):
    shop.client.patch(f"/v1/variants/{shop.variant['id']}", json={"version": shop.variant["version"], "barcode": "036000291452"},
                      headers=shop.headers())
    found = shop.get("/v1/items/lookup", params={"code": "036000291452", "location_id": shop.location_id}).json()
    assert found["found"] and found["sku"] == "LITTER-20" and found["stock"]["on_hand"] == "18"
    assert _on_hand(shop) == "18"  # looking it up changed nothing
    assert shop.get("/v1/items/lookup", params={"code": "999"}).json() == {"found": False, "code": "999"}
    assert _act(shop, "damaged", "2", note="torn bags").status_code == 201
    assert _on_hand(shop) == "16"
    recent = shop.get("/v1/stock-actions", params={"location_id": shop.location_id}).json()
    assert recent[0]["reason"] == "damage" and recent[0]["by"] == "owner@example.com"
    undo = shop.post(f"/v1/stock-actions/{recent[0]['id']}/undo", {"note": "wrong item"})
    again = shop.post(f"/v1/stock-actions/{recent[0]['id']}/undo", {"note": "wrong item"})
    assert undo.status_code == 201 and again.json()["movement_id"] == undo.json()["movement_id"]
    assert _on_hand(shop) == "18"
    key = f"k-{uuid.uuid4()}"
    assert _act(shop, "count", "20", key=key).status_code == 201
    assert _act(shop, "count", "20", key=key).status_code == 201  # same request again: one change
    assert _act(shop, "count", "21", key=key).status_code == 409  # same key, different number: not silently dropped
    assert _on_hand(shop) == "20"


def test_a_count_is_corrected_by_counting_again_not_by_undo(shop):
    stock_in = _act(shop, "stock_in", "3").json()
    count = _act(shop, "count", "4").json()
    refused = shop.post(f"/v1/stock-actions/{count['movement_id']}/undo", {"note": None})
    assert refused.status_code == 409 and "count" in refused.json()["detail"]
    # The count already includes the earlier stock-in; undoing it now would take the 3 off twice.
    assert shop.post(f"/v1/stock-actions/{stock_in['movement_id']}/undo", {"note": None}).status_code == 409
    row = shop.get("/v1/stock/overview", params={"location_id": shop.location_id}).json()["items"][0]
    assert row["on_hand"] == "4" and row["stock_counted"] is True


def test_an_item_never_counted_is_not_shown_as_current_after_a_scan(client):
    from tests.conftest import new_store

    api = new_store(client, "scan@corner.example", "Scan")
    api.location_id = api.post("/v1/locations", {"name": "Main", "timezone": "America/New_York"}).json()["id"]
    api.variant = api.post("/v1/variants", {"sku": "NEW-1", "name": "New thing"}).json()
    assert _act(api, "stock_in", "12").status_code == 201
    row = api.get("/v1/stock/overview", params={"location_id": api.location_id}).json()["items"][0]
    assert (row["on_hand"], row["stock_counted"], row["stale"]) == ("12", False, True)
    features = {f["key"]: f for f in api.get("/v1/readiness", params={"location_id": api.location_id}).json()["features"]}
    assert not features["inventory"]["ready"]  # a scan says what changed, not what is on the shelf


def test_square_owned_stock_is_not_changed_by_a_scan(shop):
    with transaction() as s:
        s.execute(text("UPDATE locations SET inventory_write_owner = 'square' WHERE id = :id"), {"id": shop.location_id})
    resp = _act(shop, "used", "1")
    assert resp.status_code == 409 and resp.json()["details"]["stock_owner"] == "square"


# ---------------------------------------------------------------------------
# Suggestions → drafts with the person's quantities
# ---------------------------------------------------------------------------


def test_drafts_take_the_quantities_the_owner_set(shop):
    run = shop.post("/v1/replenishment-runs", {"location_id": shop.location_id}).json()
    bad = shop.post("/v1/purchase-orders/from-run", {"run_id": run["id"], "quantities": {shop.variant["id"]: "2.5"}})
    assert bad.status_code == 422
    (po,) = shop.post("/v1/purchase-orders/from-run", {"run_id": run["id"], "quantities": {shop.variant["id"]: "7"}}).json()
    line = shop.get(f"/v1/purchase-orders/{po['id']}").json()["content"]["lines"][0]
    assert (line["order_qty"], line["recommendation"]["order_qty"], line["edited"]) == ("7", "5", True)


# ---------------------------------------------------------------------------
# Google Sheets (shared link) — Google hosts only
# ---------------------------------------------------------------------------


def test_sheet_links_become_csv_exports_and_only_google_is_contacted():
    url, _ = google_sheets.export_url("https://docs.google.com/spreadsheets/d/abc123/edit#gid=42")
    assert url == "https://docs.google.com/spreadsheets/d/abc123/export?format=csv&gid=42"
    with pytest.raises(Exception):
        google_sheets.export_url("https://evil.example/spreadsheets/d/abc/edit")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "docs.google.com":
            return httpx.Response(307, headers={"location": "https://doc-0s.googleusercontent.com/x.csv"})
        if request.url.host.endswith("googleusercontent.com"):
            return httpx.Response(200, headers={"content-type": "text/csv"}, content=b"SKU,Qty\nA,1\n")
        raise AssertionError("contacted a non-Google host")

    name, content = google_sheets.fetch_csv("https://docs.google.com/spreadsheets/d/abc123/edit",
                                            transport=httpx.MockTransport(handler))
    assert content.startswith(b"SKU,Qty")
    redirect_away = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/"}))
    with pytest.raises(Exception, match="unexpected"):
        google_sheets.fetch_csv("https://docs.google.com/spreadsheets/d/abc123/edit", transport=redirect_away)
    private = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"))
    with pytest.raises(Exception, match="isn't shared publicly"):
        google_sheets.fetch_csv("https://docs.google.com/spreadsheets/d/abc123/edit", transport=private)


def test_a_count_that_confirms_the_stock_still_refreshes_how_fresh_it_is(shop):
    before = shop.get("/v1/stock/overview", params={"location_id": shop.location_id}).json()["items"][0]
    assert _act(shop, "count", before["on_hand"]).status_code == 201
    after = shop.get("/v1/stock/overview", params={"location_id": shop.location_id}).json()["items"][0]
    assert after["on_hand"] == before["on_hand"] and after["stock_as_of"] > before["stock_as_of"]


def test_a_sample_store_is_owned_by_the_account_and_marked_as_a_sample():
    c = _browser()
    _signup(c)
    resp = c.post("/v1/sample-store", headers=WEB)
    assert resp.status_code == 201, resp.text
    (m,) = c.get("/v1/me").json()["memberships"]
    assert (m["is_sample"], m["role"], m["tenant_id"]) == (True, "owner", resp.json()["tenant_id"])
    members = c.get("/v1/members", headers={**WEB, "X-Tenant-Id": m["tenant_id"]}).json()
    assert [x["email"] for x in members] == ["ann@corner.example"]  # the builder left; no demo staff added
    again = c.post("/v1/sample-store", headers=WEB).json()  # one per account
    assert (again["tenant_id"], again["existing"]) == (m["tenant_id"], True)


def test_an_invitation_can_only_be_claimed_with_its_link():
    owner = _browser()
    _signup(owner)
    tenant = _store(owner).json()["tenant_id"]
    h = {**WEB, "X-Tenant-Id": tenant}
    assert owner.post("/v1/members/invite", json={"email": "bob@corner.example", "role": "owner"}, headers=h).status_code == 422
    invited = owner.post("/v1/members/invite", json={"email": "Bob@corner.example", "role": "manager"}, headers=h).json()
    assert invited["has_account"] is False and invited["invite_token"]
    stranger = _browser()  # knows the address, not the link
    taken = stranger.post("/v1/auth/signup", json={"email": "bob@corner.example", "password": "a long passphrase 2"})
    assert taken.status_code == 403
    guess = stranger.post("/v1/auth/signup", json={"email": "bob@corner.example", "password": "a long passphrase 2",
                                                    "invite": "not-the-token"})
    assert guess.status_code == 403
    bob = _browser()
    ok = bob.post("/v1/auth/signup", json={"email": "bob@corner.example", "password": "a long passphrase 2",
                                           "invite": invited["invite_token"]})
    assert ok.status_code == 201
    assert [(m["tenant_id"], m["role"]) for m in bob.get("/v1/me").json()["memberships"]] == [(tenant, "manager")]
    # Someone who already has an account is simply given access; no link to pass around.
    carol = _browser()
    _signup(carol, email="carol@corner.example")
    added = owner.post("/v1/members/invite", json={"email": "carol@corner.example", "role": "receiver"}, headers=h).json()
    assert (added["has_account"], added["invite_token"]) == (True, None)
