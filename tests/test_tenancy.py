"""CORE-01: tenant membership and route auth."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from clawbot.domain import inventory
from clawbot.domain.errors import NotFound
from clawbot.persistence.db import transaction
from clawbot.policies.permissions import system
from tests.conftest import Api, add_member, idem, new_store, seed_variant_and_location


def test_requires_authentication(client):
    assert client.get("/v1/me").status_code == 401


def test_creator_becomes_owner(client):
    store = new_store(client, "alice@example.com", "Alice Pets")
    me = store.get("/v1/me").json()
    assert me["memberships"] == [
        {"tenant_id": store.tenant_id, "tenant_name": "Alice Pets", "role": "owner",
         "business_type": None, "currency": "USD", "is_sample": False}
    ]


def test_non_member_cannot_use_tenant_header(client):
    alice = new_store(client, "alice@example.com")
    mallory = Api(client, "mallory@example.com", alice.tenant_id)
    assert mallory.get("/v1/variants").status_code == 403
    assert mallory.get("/v1/inventory").status_code == 403


def test_tenant_header_must_be_uuid(client):
    store = new_store(client, "alice@example.com")
    store.tenant_id = "not-a-uuid"
    assert store.get("/v1/variants").status_code == 400


def test_cross_tenant_object_ids_are_not_found(client):
    alice = new_store(client, "alice@example.com", "A")
    bob = new_store(client, "bob@example.com", "B")
    a_variant, a_location = seed_variant_and_location(alice)
    b_variant, b_location = seed_variant_and_location(bob)

    # Bob reads Alice's variant by ID through his own tenant: indistinguishable from missing.
    assert bob.get(f"/v1/variants/{a_variant}").status_code == 404

    # Bob mixes his location with Alice's variant (and vice versa).
    for variant_id, location_id in [(a_variant, b_location), (b_variant, a_location)]:
        resp = bob.post(
            "/v1/inventory/movements",
            {"variant_id": variant_id, "location_id": location_id, "delta": "5", "reason": "count"},
            headers={"Idempotency-Key": idem()},
        )
        assert resp.status_code == 404, resp.text

    assert bob.get("/v1/inventory").json() == []
    assert alice.get("/v1/inventory").json() == []


def test_agent_supplied_foreign_ids_rejected_by_service(client):
    """A tool call that passes another tenant's IDs fails even when it bypasses HTTP."""
    alice = new_store(client, "alice@example.com", "A")
    bob = new_store(client, "bob@example.com", "B")
    a_variant, a_location = seed_variant_and_location(alice)

    with pytest.raises(NotFound), transaction() as s:
        inventory.record_movement(
            s,
            tenant_id=uuid.UUID(bob.tenant_id),
            variant_id=uuid.UUID(a_variant),
            location_id=uuid.UUID(a_location),
            delta=1,
            reason="count",
            source="agent",
            source_event_id=idem(),
            actor=system("test-agent"),
        )


def test_composite_fk_blocks_cross_tenant_rows_at_db_level(client):
    """Backstop: even raw ORM writes cannot point tenant B rows at tenant A's variant."""
    from clawbot.persistence.models import InventoryPosition

    alice = new_store(client, "alice@example.com", "A")
    bob = new_store(client, "bob@example.com", "B")
    a_variant, _ = seed_variant_and_location(alice)
    _, b_location = seed_variant_and_location(bob)

    with pytest.raises(IntegrityError), transaction() as s:
        s.add(
            InventoryPosition(
                tenant_id=uuid.UUID(bob.tenant_id),
                variant_id=uuid.UUID(a_variant),
                location_id=uuid.UUID(b_location),
                on_hand=1,
                version=1,
            )
        )


def test_receiver_cannot_edit_catalog_but_can_move_stock(client):
    owner = new_store(client, "owner@example.com")
    variant_id, location_id = seed_variant_and_location(owner)
    receiver = add_member(owner, "recv@example.com", "receiver")
    assert receiver.post("/v1/variants", {"sku": "X", "name": "X"}).status_code == 403
    assert receiver.get("/v1/audit-events").status_code == 403
    resp = receiver.post(
        "/v1/inventory/movements",
        {"variant_id": variant_id, "location_id": location_id, "delta": "-1", "reason": "damage"},
        headers={"Idempotency-Key": idem()},
    )
    assert resp.status_code == 201, resp.text


def test_dev_auth_refused_in_production(monkeypatch):
    from clawbot.api.app import create_app

    monkeypatch.setenv("TABULA_ENV", "production")
    with pytest.raises(RuntimeError):
        create_app()
