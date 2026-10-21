"""
Regression tests for the CP1/CP2 independent review (one test per finding).
A1–A11 are confirmed bugs; B1 is the domain-layer permission gap; C2 is stock write ownership.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from jose import jwt

from clawbot.domain import catalog, inventory, suppliers
from clawbot.domain.errors import PermissionDenied, StateConflict, ValidationFailed
from clawbot.domain.matching import _sizes
from clawbot.persistence.db import transaction
from clawbot.policies.permissions import agent, human, system
from tests.conftest import add_member, idem, new_store, seed_variant_and_location
from tests.test_suppliers import _approvable_supplier, _confirm, _item, _offers, _price, _supplier


@pytest.fixture
def store(client):
    api = new_store(client, "owner@example.com", "Paws & Co")
    loc = api.post("/v1/locations", {"name": "Main St", "timezone": "America/New_York"}).json()
    var = api.post("/v1/variants", {"sku": "LITTER-20", "name": "Clumping cat litter 20lb"}).json()
    api.location_id, api.variant_id = loc["id"], var["id"]
    return api


def _patch(store, path, body):
    return store.client.patch(path, json=body, headers=store.headers())


# A1 — approved supplier cannot silently lose approval conditions
def test_a1_edit_breaking_checklist_is_refused(store):
    s = _approvable_supplier(store)
    for change in ({"payment_terms": "unknown"}, {"default_lead_time_days": None}, {"freight_notes": ""}):
        resp = _patch(store, f"/v1/suppliers/{s['id']}", {"version": s["version"], **change})
        assert resp.status_code == 409, (change, resp.text)
        assert resp.json()["details"]["blockers"]
    assert store.get(f"/v1/suppliers/{s['id']}").json()["relationship_status"] == "approved"


# A2 — a price must state its pack; a "case of 24" price is refused on a case-of-12 item
def test_a2_price_quoted_for_other_pack_is_refused(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"], per="12"))
    resp = _price(store, item["id"], "55.00", per="24")
    assert resp.status_code == 422
    assert resp.json()["details"]["quoted"]["units_per_order_uom"] == "24"
    assert _offers(store)[0]["blockers"] == ["no_current_price"]


# A3 — future-dated price keeps the current one in force until it starts
def test_a3_future_price_does_not_retire_current_price(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    assert _price(store, item["id"], "33.00", valid_from=future).status_code == 201

    (offer,) = _offers(store)
    assert offer["eligible"] and offer["price"]["unit_price"] == "30.0000"
    with transaction() as session:
        later = suppliers.offers_for_variant(
            session, tenant_id=uuid.UUID(store.tenant_id), variant_id=uuid.UUID(store.variant_id),
            at=datetime.now(timezone.utc) + timedelta(days=11),
        )
        assert later[0].price.unit_price == Decimal("33.0000")

    # …and a pack change afterwards retires both without violating constraints (was a 500).
    item = store.get(f"/v1/supplier-items/{item['id']}").json()
    resp = _patch(store, f"/v1/supplier-items/{item['id']}", {"version": item["version"], "units_per_order_uom": "24"})
    assert resp.status_code == 200
    with transaction() as session:
        later = suppliers.offers_for_variant(
            session, tenant_id=uuid.UUID(store.tenant_id), variant_id=uuid.UUID(store.variant_id),
            at=datetime.now(timezone.utc) + timedelta(days=11),
        )
        assert "no_current_price" in later[0].blockers


# A4 — explicit nulls on required fields are 422, not 500
def test_a4_nulls_on_required_fields_are_rejected(store):
    s = _supplier(store)
    for field in ("currency", "timezone", "name", "credit_hold"):
        resp = _patch(store, f"/v1/suppliers/{s['id']}", {"version": s["version"], field: None})
        assert resp.status_code == 422, (field, resp.status_code)
    item = _item(store, s["id"])
    for field in ("units_per_order_uom", "order_uom"):
        resp = _patch(store, f"/v1/supplier-items/{item['id']}", {"version": item["version"], field: None})
        assert resp.status_code == 422, (field, resp.status_code)


# A5 — duplicates are 4xx: rename onto an existing name, and the DB backstop maps to 409
def test_a5_duplicate_name_and_unique_backstop(store):
    _supplier(store, "Alpha")
    b = _supplier(store, "Beta")
    assert _patch(store, f"/v1/suppliers/{b['id']}", {"version": b["version"], "name": "Alpha"}).status_code == 422

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from clawbot.api.app import create_app
    from clawbot.api.deps import DbSession
    from clawbot.persistence.models import Supplier

    app = create_app()

    @app.get("/boom")
    def boom(session: Session = DbSession):
        # No flush: the violation only surfaces when the request transaction commits.
        session.add(Supplier(tenant_id=uuid.UUID(store.tenant_id), name="Alpha", currency="USD", timezone="UTC"))
        return {"ok": True}

    resp = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert resp.status_code == 409 and resp.json()["details"]["constraint"] == "uq_suppliers_tenant_id_name"


# A6 — naive datetimes are rejected
def test_a6_naive_datetimes_rejected(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")
    assert _price(store, item["id"], "31.00", valid_from="2030-01-01T00:00:00").status_code == 422
    body = {"variant_id": store.variant_id, "location_id": store.location_id, "delta": "1", "reason": "count",
            "occurred_at": "2026-10-01T09:00:00"}
    assert store.post("/v1/inventory/movements", body, headers={"Idempotency-Key": idem()}).status_code == 422


# A7 — a mistaken rejection can be reversed by a person
def test_a7_rejected_mapping_can_be_confirmed(store):
    m = store.post("/v1/external-mappings", {"source_system": "square", "external_id": "X",
                                             "variant_id": store.variant_id, "match_method": "manual"}).json()
    for decision in ("confirmed", "rejected", "confirmed"):
        resp = store.post(f"/v1/external-mappings/{m['id']}/decision", {"decision": decision, "variant_id": store.variant_id})
        assert resp.status_code == 200 and resp.json()["status"] == decision


# A9 — sub-0.0001 precision is refused in the service, so connector replays stay idempotent
def test_a9_movement_precision_enforced_in_service(store):
    tenant, variant, location = (uuid.UUID(x) for x in (store.tenant_id, store.variant_id, store.location_id))
    for delta in (Decimal("1.23456"), Decimal("0.00001")):
        with pytest.raises(ValidationFailed), transaction() as s:
            inventory.record_movement(s, tenant_id=tenant, variant_id=variant, location_id=location, delta=delta,
                                      reason="count", source="square", source_event_id=idem(), actor=system("sync"))


# A10 — Auth0 path works end to end and picks up a rotated signing key without restart
def test_a10_auth0_tokens_and_key_rotation(client, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jose import jwk

    from clawbot.auth import auth0

    def keypair(kid):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        public = jwk.construct(key.public_key().public_bytes(serialization.Encoding.PEM,
                               serialization.PublicFormat.SubjectPublicKeyInfo), "RS256").to_dict()
        public.update({"kid": kid, "use": "sig", "alg": "RS256"})
        return pem, {k: (v.decode() if isinstance(v, bytes) else v) for k, v in public.items()}

    def token(pem, kid, sub):
        claims = {"sub": sub, "aud": "tabula-api", "iss": "https://tabula.test/", "exp": int(time.time()) + 300,
                  "email": "auth0user@example.com"}
        return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})

    old_pem, old_pub = keypair("k1")
    new_pem, new_pub = keypair("k2")
    published = {"keys": [old_pub]}
    monkeypatch.setenv("TABULA_AUTH_MODE", "auth0")
    monkeypatch.setenv("AUTH0_DOMAIN", "tabula.test")
    monkeypatch.setenv("AUTH0_AUDIENCE", "tabula-api")
    monkeypatch.setattr(auth0, "_fetch_jwks", lambda domain: published)
    monkeypatch.setattr(auth0, "JWKS_MIN_REFRESH_SECONDS", 0)
    auth0.reset_jwks_cache()

    ok = client.get("/v1/me", headers={"Authorization": f"Bearer {token(old_pem, 'k1', 'auth0|abc')}"})
    assert ok.status_code == 200 and ok.json()["email"] == "auth0user@example.com"
    assert client.get("/v1/me").status_code == 401
    bad = token(old_pem, "k1", "auth0|abc")[:-4] + "AAAA"
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401

    published["keys"] = [new_pub]  # Auth0 rotates; cache still holds k1
    rotated = client.get("/v1/me", headers={"Authorization": f"Bearer {token(new_pem, 'k2', 'auth0|abc')}"})
    assert rotated.status_code == 200
    auth0.reset_jwks_cache()


# A11 — non-ASCII digits are not GTINs; thousands separators parse correctly
def test_a11_unicode_digits_and_thousands(store):
    resp = store.post("/v1/variants", {"sku": "U", "name": "Unicode", "barcode": "01234567890²"})
    assert resp.status_code == 201 and resp.json()["gtin"] is None
    assert _sizes("Shampoo 1,000ml") == {("volume", Decimal(1000))}


# B1 — permissions are enforced in the domain, for agents and systems too
def test_b1_agents_can_propose_but_never_decide(store):
    tenant, variant = uuid.UUID(store.tenant_id), uuid.UUID(store.variant_id)
    bot = agent("onboarding-agent")
    with transaction() as s:
        m = catalog.propose_external_mapping(s, tenant_id=tenant, actor=bot, source_system="csv", external_id="row-1",
                                             variant_id=variant, match_method="text_candidate")
        mapping_id = m.id
    s_id = uuid.UUID(_supplier(store)["id"])
    forbidden = [
        lambda s: catalog.decide_external_mapping(s, tenant_id=tenant, actor=bot, mapping_id=mapping_id,
                                                  decision="confirmed", expected_variant_id=variant),
        lambda s: suppliers.create_supplier(s, tenant_id=tenant, actor=bot, name="Found online", currency="USD", timezone="UTC"),
        lambda s: suppliers.set_supplier_status(s, tenant_id=tenant, actor=bot, supplier_id=s_id, expected_version=1, status="approved"),
        lambda s: catalog.create_variant(s, tenant_id=tenant, actor=system("square-sync"), sku="X", name="X"),
    ]
    for call in forbidden:
        with pytest.raises(PermissionDenied), transaction() as s:
            call(s)

    (event,) = store.get("/v1/audit-events", params={"object_type": "external_item_mapping"}).json()
    assert (event["action"], event["actor_kind"], event["actor_name"], event["actor_user_id"]) == (
        "external_mapping.proposed", "agent", "onboarding-agent", None,
    )
    assert store.get("/v1/external-mappings").json()[0]["status"] == "suggested"


def test_b1_bookkeeper_records_prices_but_cannot_approve(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    bookkeeper = add_member(store, "books@example.com", "bookkeeper")
    assert _price(bookkeeper, item["id"], "30.00").status_code == 201
    assert bookkeeper.post(f"/v1/suppliers/{s['id']}/status", {"version": s["version"], "status": "suspended"}).status_code == 403


def test_b1_last_owner_cannot_be_demoted(store):
    resp = store.client.put("/v1/members", json={"auth_subject": "dev|owner@example.com", "role": "manager"},
                            headers=store.headers())
    assert resp.status_code == 409
    manager = add_member(store, "mgr@example.com", "manager")
    assert manager.client.put("/v1/members", json={"auth_subject": "dev|x@example.com", "role": "owner"},
                              headers=manager.headers()).status_code == 403
    assert {m["role"] for m in store.get("/v1/members").json()} == {"owner", "manager"}


# C2 — stock write ownership and manual-receipt restriction
def test_c2_pos_owned_location_rejects_tabula_movements(store):
    pos_loc = store.post("/v1/locations", {"name": "POS store", "timezone": "America/New_York",
                                           "inventory_write_owner": "square"}).json()
    body = {"variant_id": store.variant_id, "location_id": pos_loc["id"], "delta": "3", "reason": "count"}
    resp = store.post("/v1/inventory/movements", body, headers={"Idempotency-Key": idem()})
    assert resp.status_code == 409 and resp.json()["details"]["inventory_write_owner"] == "square"


def test_c2_receipts_cannot_be_entered_by_hand(store):
    body = {"variant_id": store.variant_id, "location_id": store.location_id, "delta": "12", "reason": "receipt"}
    assert store.post("/v1/inventory/movements", body, headers={"Idempotency-Key": idem()}).status_code == 422
    tenant, variant, location = (uuid.UUID(x) for x in (store.tenant_id, store.variant_id, store.location_id))
    owner = human(uuid.UUID(store.get("/v1/me").json()["user_id"]), "owner")
    with pytest.raises(ValidationFailed), transaction() as s:
        inventory.record_movement(s, tenant_id=tenant, variant_id=variant, location_id=location, delta=Decimal(12),
                                  reason="receipt", source="manual", source_event_id=idem(), actor=owner)


# ---------------------------------------------------------------------------
# Second review round
# ---------------------------------------------------------------------------


def test_r2_1a_decision_refused_if_mapping_changed_under_reviewer(store):
    other = store.post("/v1/variants", {"sku": "LITTER-40", "name": "Clumping cat litter 40lb"}).json()
    m = store.post("/v1/external-mappings", {"source_system": "square", "external_id": "SQ1",
                                             "variant_id": store.variant_id, "match_method": "manual"}).json()
    with transaction() as s:  # agent re-proposes while the person is looking at LITTER-20
        catalog.propose_external_mapping(s, tenant_id=uuid.UUID(store.tenant_id), actor=agent("onboarding-agent"),
                                         source_system="square", external_id="SQ1",
                                         variant_id=uuid.UUID(other["id"]), match_method="text_candidate")
    resp = store.post(f"/v1/external-mappings/{m['id']}/decision", {"decision": "confirmed", "variant_id": store.variant_id})
    assert resp.status_code == 409 and resp.json()["details"]["current_variant_id"] == other["id"]
    assert store.get("/v1/external-mappings").json()[0]["status"] == "suggested"


def test_r2_1b_preexisting_gap_does_not_block_credit_hold(store):
    s = _approvable_supplier(store)
    with transaction() as session:  # simulate a supplier approved before the checklist grew
        sup = suppliers.get_supplier(session, tenant_id=uuid.UUID(store.tenant_id), supplier_id=uuid.UUID(s["id"]))
        sup.freight_notes = None
    resp = _patch(store, f"/v1/suppliers/{s['id']}", {"version": s["version"], "credit_hold": True})
    assert resp.status_code == 200 and resp.json()["credit_hold"] is True
    # …but an edit that adds a new gap is still refused
    resp = _patch(store, f"/v1/suppliers/{s['id']}", {"version": resp.json()["version"], "payment_terms": "unknown"})
    assert resp.status_code == 409 and resp.json()["details"]["blockers"] == ["payment_terms_unknown"]


def test_r2_1b_migration_demotes_noncompliant_approved_suppliers(store):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from tests.conftest import TEST_DB_URL

    s = _approvable_supplier(store)
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = TEST_DB_URL
    command.downgrade(cfg, "0002")
    try:
        with transaction() as session:
            session.execute(text("UPDATE suppliers SET freight_notes = NULL WHERE id = :id"), {"id": s["id"]})
    finally:
        command.upgrade(cfg, "head")
    after = store.get(f"/v1/suppliers/{s['id']}").json()
    assert after["relationship_status"] == "candidate" and after["verified_at"] is None
    events = store.get("/v1/audit-events", params={"object_type": "supplier"}).json()
    assert events[0]["actor_kind"] == "system" and events[0]["actor_name"] == "migration-0003"


def test_r2_1c_permission_denied_is_403(store):
    from fastapi.testclient import TestClient

    from clawbot.api.app import create_app

    app = create_app()

    @app.get("/deny")
    def deny():
        from clawbot.policies.permissions import authorize
        authorize(agent("x"), "supplier.approve")

    assert TestClient(app, raise_server_exceptions=False).get("/deny").status_code == 403


def test_r2_2a_outbox_payload_normalised_and_options_compared(store):
    from clawbot.domain import outbox
    from clawbot.domain.errors import IdempotencyConflict

    tenant = uuid.UUID(store.tenant_id)
    with transaction() as s:
        outbox.enqueue(s, tenant_id=tenant, topic="po.send", operation_key="k", payload={"lines": (1, 2)})
    with transaction() as s:
        outbox.enqueue(s, tenant_id=tenant, topic="po.send", operation_key="k", payload={"lines": [1, 2]})
    with pytest.raises(IdempotencyConflict), transaction() as s:
        outbox.enqueue(s, tenant_id=tenant, topic="po.send", operation_key="k", payload={"lines": [1, 2]}, retry_safe=True)


def test_r2_2b_late_worker_can_resolve_unknown(store):
    from clawbot.domain import outbox
    from clawbot.persistence.models import OutboxMessage

    tenant = uuid.UUID(store.tenant_id)
    with transaction() as s:
        outbox.enqueue(s, tenant_id=tenant, topic="po.send", operation_key="k", payload={})
    with transaction() as s:
        (msg,) = outbox.claim_batch(s, lease=timedelta(seconds=-1))
        mid, token = msg.id, msg.lease_token
    with transaction() as s:
        assert outbox.claim_batch(s) == []
        assert s.get(OutboxMessage, mid).status == "unknown"
    with transaction() as s:
        assert outbox.mark_done(s, mid, token).status == "done"


def test_r2_2c_no_backdating_after_pack_change(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")
    item = store.get(f"/v1/supplier-items/{item['id']}").json()
    _patch(store, f"/v1/supplier-items/{item['id']}", {"version": item["version"], "units_per_order_uom": "24"})
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert _price(store, item["id"], "55.00", per="24", valid_from=old).status_code == 422
    assert _price(store, item["id"], "55.00", per="24").status_code == 201


def test_r2_2e_members_hidden_from_receivers_and_humans_cannot_fake_receipts(store):
    receiver = add_member(store, "recv@example.com", "receiver")
    assert receiver.get("/v1/members").status_code == 403
    tenant, variant, location = (uuid.UUID(x) for x in (store.tenant_id, store.variant_id, store.location_id))
    with transaction() as s:
        from clawbot.domain import tenancy
        me = tenancy.actor_for(s, tenant_id=tenant, user_id=uuid.UUID(store.get("/v1/me").json()["user_id"]))
    with pytest.raises(ValidationFailed), transaction() as s:
        inventory.record_movement(s, tenant_id=tenant, variant_id=variant, location_id=location, delta=Decimal(12),
                                  reason="receipt", source="anything-else", source_event_id=idem(), actor=me)


def test_r2_2e_replay_survives_change_to_pos_ownership(store):
    from clawbot.persistence.models import Location

    key = idem()
    body = {"variant_id": store.variant_id, "location_id": store.location_id, "delta": "5", "reason": "count"}
    first = store.post("/v1/inventory/movements", body, headers={"Idempotency-Key": key})
    with transaction() as s:
        s.get(Location, uuid.UUID(store.location_id)).inventory_write_owner = "square"
    again = store.post("/v1/inventory/movements", body, headers={"Idempotency-Key": key})
    assert again.status_code == 200 and again.json()["movement"]["id"] == first.json()["movement"]["id"]
    new = store.post("/v1/inventory/movements", body, headers={"Idempotency-Key": idem()})
    assert new.status_code == 409


def test_r2_1d_actor_for_uses_membership_role(store, client):
    from clawbot.domain import tenancy
    from clawbot.domain.errors import PermissionDenied as Denied

    outsider = new_store(client, "other@example.com", "Other")
    tenant = uuid.UUID(store.tenant_id)
    with transaction() as s:
        other_user = uuid.UUID(outsider.get("/v1/me").json()["user_id"])
        with pytest.raises(Denied):
            tenancy.actor_for(s, tenant_id=tenant, user_id=other_user)


def test_r2_jwks_outage_serves_last_good_keys(monkeypatch):
    import httpx

    from clawbot.auth import auth0

    monkeypatch.setenv("AUTH0_DOMAIN", "tabula.test")
    calls = {"n": 0}

    def fetch(domain):
        calls["n"] += 1
        if calls["n"] > 1:
            raise httpx.ConnectError("down")
        return {"keys": [{"kid": "k1"}]}

    monkeypatch.setattr(auth0, "_fetch_jwks", fetch)
    auth0.reset_jwks_cache()
    assert auth0._get_jwks() == {"keys": [{"kid": "k1"}]}
    monkeypatch.setattr(auth0, "JWKS_TTL_SECONDS", -1)  # force staleness
    assert auth0._get_jwks() == {"keys": [{"kid": "k1"}]}
    auth0.reset_jwks_cache()
