"""
CP4 / CON-01, CON-02: Square connector against an in-memory Square (no credentials).
Real Sandbox verification is a separate, manual step (docs/SQUARE_SETUP.md).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, text

from clawbot.connectors.square import service as square
from clawbot.connectors.square.client import SquareClient
from clawbot.connectors.square.config import load as load_config
from clawbot.connectors.square.mock import FakeSquare
from clawbot.connectors.square.webhooks import SIGNATURE_HEADER, sign
from clawbot.persistence.db import transaction
from clawbot.persistence.models import ConnectorAccount
from clawbot.workflows import connector_worker
from tests.conftest import new_store
from tests.test_imports import _apply, _csv, _upload

WEBHOOK_URL = "https://tabula.test/v1/connectors/square/webhook"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.fixture
def fake():
    sq = FakeSquare.demo()
    square.use_transport(sq.transport())
    yield sq
    square.use_transport(None)


@pytest.fixture
def shop(client, fake):
    api = new_store(client, "owner@example.com", "Paws & Co")
    api.location_id = api.post("/v1/locations", {"name": "Main St", "timezone": "America/New_York"}).json()["id"]
    api.litter = api.post("/v1/variants", {"sku": "LITTER-20", "name": "Clumping cat litter 20lb",
                                           "barcode": "036000291452"}).json()
    return api


def _connect(api) -> dict:
    url = api.post("/v1/connectors/square/authorize").json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    resp = api.client.get("/v1/connectors/square/callback", params={"state": state, "code": "mock-code"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _link(api, account):
    resp = api.post(f"/v1/connectors/{account['id']}/locations",
                    {"external_location_id": "LOC_MAIN", "location_id": api.location_id})
    assert resp.status_code == 201, resp.text


def _sync(api, account, kind, **body):
    resp = api.post(f"/v1/connectors/{account['id']}/sync", {"kind": kind, **body})
    assert resp.status_code == 202, resp.text
    connector_worker.run_once()


def _confirm_proposals(api):
    for m in api.get("/v1/external-mappings", params={"status": "suggested"}).json():
        api.post(f"/v1/external-mappings/{m['id']}/decision", {"decision": "confirmed", "variant_id": m["variant_id"]})


def _ready(api, fake) -> dict:
    account = _connect(api)
    _link(api, account)
    _sync(api, account, "catalog")
    _confirm_proposals(api)
    return account


# ---------------------------------------------------------------------------
# OAuth and credentials
# ---------------------------------------------------------------------------


def test_oauth_connects_and_stores_tokens_encrypted(shop, fake):
    account = _connect(shop)
    assert (account["status"], account["merchant_id"], account["environment"]) == ("active", fake.merchant_id, "mock")
    assert account["capabilities"]["inventory_write"] is False  # read-only scopes in CP4
    with transaction() as s:
        raw = s.execute(text("SELECT access_token_enc, refresh_token_enc FROM connector_accounts")).one()
    assert fake.access_token not in raw[0] and "mock-refresh-token" not in raw[1]


def test_oauth_state_is_single_use_and_bound(shop, fake):
    url = shop.post("/v1/connectors/square/authorize").json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert shop.client.get("/v1/connectors/square/callback", params={"state": "forged", "code": "mock-code"}).status_code == 403
    assert shop.client.get("/v1/connectors/square/callback", params={"state": state, "code": "wrong"}).status_code == 403
    # The state was consumed by the failed attempt: it cannot be replayed.
    assert shop.client.get("/v1/connectors/square/callback", params={"state": state, "code": "mock-code"}).status_code == 403


def test_one_square_account_cannot_join_two_workspaces(client, shop, fake):
    _connect(shop)
    other = new_store(client, "rival@example.com", "Rival")
    url = other.post("/v1/connectors/square/authorize").json()["authorize_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert other.client.get("/v1/connectors/square/callback", params={"state": state, "code": "mock-code"}).status_code == 409


def test_production_needs_explicit_production_env(monkeypatch):
    from clawbot.domain.errors import ValidationFailed

    monkeypatch.setenv("SQUARE_ENVIRONMENT", "production")
    monkeypatch.delenv("TABULA_ENV", raising=False)
    with pytest.raises(ValidationFailed, match="requires TABULA_ENV=production"):
        load_config()


def test_revoke_deletes_tokens(shop, fake):
    account = _connect(shop)
    revoked = shop.client.delete(f"/v1/connectors/{account['id']}", headers=shop.headers()).json()
    assert revoked["status"] == "revoked" and fake.revoked
    with transaction() as s:
        assert s.scalar(select(ConnectorAccount.access_token_enc)) is None


def test_receiver_cannot_connect(client, shop):
    from tests.conftest import add_member

    receiver = add_member(shop, "recv@example.com", "receiver")
    assert receiver.post("/v1/connectors/square/authorize").status_code == 403


# ---------------------------------------------------------------------------
# Locations, catalog, sales, inventory
# ---------------------------------------------------------------------------


def test_linking_a_location_hands_its_stock_to_square(shop, fake):
    account = _connect(shop)
    assert [l["external_id"] for l in shop.get(f"/v1/connectors/{account['id']}/external-locations").json()] == ["LOC_MAIN"]
    _link(shop, account)
    loc = next(l for l in shop.get("/v1/locations").json() if l["id"] == shop.location_id)
    assert loc["inventory_write_owner"] == "square"
    bad = shop.post(f"/v1/connectors/{account['id']}/locations", {"external_location_id": "NOPE", "location_id": shop.location_id})
    assert bad.status_code in (409, 422)


def test_catalog_sync_only_proposes_mappings_and_people_adopt_the_rest(shop, fake):
    account = _connect(shop)
    _link(shop, account)
    _sync(shop, account, "catalog")
    proposals = shop.get("/v1/external-mappings").json()
    assert [(m["external_id"], m["status"], m["match_method"]) for m in proposals] == [("VAR_LITTER_20", "suggested", "merchant_sku")]
    adopted = shop.post(f"/v1/connectors/{account['id']}/adopt-items", {"external_ids": ["VAR_FOOD_5"]}).json()
    food = shop.get(f"/v1/variants/{adopted['variant_ids'][0]}").json()
    assert (food["sku"], food["name"]) == ("FOOD-5", "Dog food 5lb")


def test_sales_sync_records_sales_and_refunds_once(shop, fake):
    now = datetime.now(timezone.utc)
    fake.add_order("ORD1", _iso(now - timedelta(days=2)), [("L1", "VAR_LITTER_20", "2", 2099)])
    fake.add_order("ORD2", _iso(now - timedelta(days=1)), [("L1", "VAR_LITTER_20", "1", 2099)],
                   returns=[("R1", "VAR_LITTER_20", "1", 2099)])
    fake.add_order("ORD3", _iso(now - timedelta(days=1)), [("L1", "VAR_UNKNOWN", "5", 100)])
    fake.add_order("ORD4", _iso(now - timedelta(hours=5)), [("L1", "VAR_LITTER_20", "3", 2099)], location_id="LOC_OTHER")
    account = _ready(shop, fake)
    window = {"start": (now - timedelta(days=7)).isoformat(), "end": now.isoformat()}
    _sync(shop, account, "sales", **window)
    lines = shop.get("/v1/sales-lines").json()
    assert sorted((l["external_order_id"], l["line_type"], l["quantity"]) for l in lines) == [
        ("ORD1", "sale", "2.0000"), ("ORD2", "refund", "-1.0000"), ("ORD2", "sale", "1.0000")]
    assert {l["unit_price"] for l in lines} == {"20.9900"}

    # The same window again (e.g. a retry or an overlapping backfill) adds nothing.
    shop.post(f"/v1/connectors/{account['id']}/sync", {"kind": "sales", **window})
    connector_worker.run_once()
    assert len(shop.get("/v1/sales-lines").json()) == 3


def test_sales_already_imported_by_csv_are_not_counted_twice(shop, fake):
    now = datetime.now(timezone.utc)
    fake.add_order("ORD1", _iso(now - timedelta(days=2)), [("L1", "VAR_LITTER_20", "2", 2099)])
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [(now - timedelta(days=2)).isoformat(), "ORD1", "LITTER-20", "2"]]
    _apply(shop, _upload(shop, "sales", _csv(rows), location_id=shop.location_id, source_system="square").json())
    account = _ready(shop, fake)
    _sync(shop, account, "sales", start=(now - timedelta(days=7)).isoformat(), end=now.isoformat())
    assert len(shop.get("/v1/sales-lines").json()) == 1  # Square's copy of ORD1 went to review instead


def test_inventory_sync_writes_snapshots_used_by_replenishment(shop, fake):
    at = datetime.now(timezone.utc) - timedelta(minutes=30)
    fake.set_count("VAR_LITTER_20", 18, _iso(at))
    account = _ready(shop, fake)
    _sync(shop, account, "inventory")
    _sync(shop, account, "inventory")  # unchanged count → no new snapshot
    snaps = shop.get("/v1/inventory-snapshots", params={"location_id": shop.location_id}).json()
    assert [(s["quantity"], s["source_system"]) for s in snaps] == [("18.0000", "square")]
    run = shop.post("/v1/replenishment-runs", {"location_id": shop.location_id}).json()
    line = next(l for l in run["lines"] if l["sku"] == "LITTER-20")
    assert line["data_as_of"]["stock_source"] == "square snapshot"
    assert line["status"] == "insufficient_data"  # stock known; no sales history yet to size an order


def test_client_retries_rate_limits_and_pages(shop, fake):
    for n in range(5):
        fake.add_item(f"ITEM_{n}", f"Item {n}", [(f"VAR_{n}", "Regular", f"SKU-{n}", None)])
    fake.fail_next = [429, 503]
    client = SquareClient(load_config(), fake.access_token, transport=fake.transport(), sleep=lambda s: None)
    items = list(client.catalog_items())
    assert len(items) == 7  # 2 demo items + 5, over several pages
    assert sum(1 for m, p in fake.requests if p == "/v2/catalog/list") == 2 + 4  # 2 retried + 4 pages


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def _webhook(api, payload: dict, key="test-signature-key"):
    body = json.dumps(payload).encode()
    return api.client.post("/v1/connectors/square/webhook", content=body,
                           headers={SIGNATURE_HEADER: sign(key, WEBHOOK_URL, body), "Content-Type": "application/json"})


def test_webhook_signature_is_required(shop, fake):
    _ready(shop, fake)
    event = {"merchant_id": fake.merchant_id, "type": "inventory.count.updated", "event_id": "E1", "data": {}}
    assert _webhook(shop, event, key="wrong-key").status_code == 403
    body = json.dumps(event).encode()
    assert shop.client.post("/v1/connectors/square/webhook", content=body).status_code == 403


def test_webhook_events_are_stored_once_and_reread_current_state(shop, fake):
    account = _ready(shop, fake)
    fake.set_count("VAR_LITTER_20", 11, _iso(datetime.now(timezone.utc) - timedelta(minutes=2)))
    # The event body claims 999; processing ignores it and re-reads Square.
    event = {"merchant_id": fake.merchant_id, "type": "inventory.count.updated", "event_id": "E-42",
             "data": {"object": {"inventory_counts": [{"catalog_object_id": "VAR_LITTER_20", "location_id": "LOC_MAIN",
                                                       "quantity": "999"}]}}}
    for _ in range(3):  # Square retries deliveries
        assert _webhook(shop, event).status_code == 200
    connector_worker.run_once()
    snaps = shop.get("/v1/inventory-snapshots", params={"location_id": shop.location_id}).json()
    assert [s["quantity"] for s in snaps] == ["11.0000"]
    with transaction() as s:
        assert s.execute(text("SELECT count(*), max(status) FROM connector_events")).one() == (1, "processed")
    assert account


def test_webhook_order_event_records_the_completed_order(shop, fake):
    _ready(shop, fake)
    fake.add_order("ORD9", _iso(datetime.now(timezone.utc) - timedelta(minutes=10)), [("L1", "VAR_LITTER_20", "4", 2099)])
    _webhook(shop, {"merchant_id": fake.merchant_id, "type": "order.updated", "event_id": "E-9",
                    "data": {"type": "order", "id": "ORD9"}})
    connector_worker.run_once()
    assert [l["quantity"] for l in shop.get("/v1/sales-lines").json()] == ["4.0000"]


def test_unknown_merchant_webhook_is_acknowledged_and_ignored(shop, fake):
    resp = _webhook(shop, {"merchant_id": "SOMEONE_ELSE", "type": "order.updated", "event_id": "E-x", "data": {}})
    assert resp.status_code == 200
    with transaction() as s:
        assert s.execute(text("SELECT count(*) FROM connector_events")).scalar() == 0
