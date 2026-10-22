"""CORE-02 / INV-01: atomic, idempotent inventory ledger."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from clawbot.domain import inventory
from clawbot.domain.errors import IdempotencyConflict
from clawbot.persistence.db import transaction
from clawbot.persistence.models import AuditEvent, InventoryMovement
from clawbot.policies.permissions import system
from tests.conftest import idem, new_store, seed_variant_and_location


@pytest.fixture
def store(client):
    api = new_store(client, "owner@example.com")
    variant_id, location_id = seed_variant_and_location(api)
    return api, uuid.UUID(api.tenant_id), uuid.UUID(variant_id), uuid.UUID(location_id)


def _move(tenant_id, variant_id, location_id, delta, key, reason="count"):
    with transaction() as s:
        return inventory.record_movement(
            s,
            tenant_id=tenant_id,
            variant_id=variant_id,
            location_id=location_id,
            delta=Decimal(delta),
            reason=reason,
            source="test",
            source_event_id=key,
            actor=system("test"),
        )


def _on_hand(tenant_id, variant_id, location_id) -> Decimal:
    with transaction() as s:
        pos = inventory.get_position(s, tenant_id=tenant_id, variant_id=variant_id, location_id=location_id)
        return pos.on_hand if pos else Decimal(0)


def _movement_count(tenant_id) -> int:
    with transaction() as s:
        return s.scalar(
            select(func.count()).select_from(InventoryMovement).where(InventoryMovement.tenant_id == tenant_id)
        )


def test_same_event_ten_times_applies_once_via_api(store):
    api, tenant_id, variant_id, location_id = store
    key = idem()
    body = {"variant_id": str(variant_id), "location_id": str(location_id), "delta": "18", "reason": "count"}

    first = api.post("/v1/inventory/movements", body, headers={"Idempotency-Key": key})
    assert first.status_code == 201 and first.json()["applied"] is True
    for _ in range(9):
        again = api.post("/v1/inventory/movements", body, headers={"Idempotency-Key": key})
        assert again.status_code == 200
        assert again.json()["applied"] is False
        assert again.json()["movement"]["id"] == first.json()["movement"]["id"]

    assert _on_hand(tenant_id, variant_id, location_id) == Decimal(18)
    assert _movement_count(tenant_id) == 1


def test_same_key_different_payload_is_conflict(store):
    api, tenant_id, variant_id, location_id = store
    key = idem()
    body = {"variant_id": str(variant_id), "location_id": str(location_id), "delta": "5", "reason": "count"}
    assert api.post("/v1/inventory/movements", body, headers={"Idempotency-Key": key}).status_code == 201

    body["delta"] = "50"
    resp = api.post("/v1/inventory/movements", body, headers={"Idempotency-Key": key})
    assert resp.status_code == 409
    assert _on_hand(tenant_id, variant_id, location_id) == Decimal(5)


def test_idempotency_key_required(store):
    api, _, variant_id, location_id = store
    body = {"variant_id": str(variant_id), "location_id": str(location_id), "delta": "5", "reason": "count"}
    assert api.post("/v1/inventory/movements", body).status_code == 422


def test_zero_delta_rejected_except_a_count_that_confirms_stock(store):
    api, _, variant_id, location_id = store
    body = {"variant_id": str(variant_id), "location_id": str(location_id), "delta": "0", "reason": "adjustment"}
    assert api.post("/v1/inventory/movements", body, headers={"Idempotency-Key": idem()}).status_code == 422
    # A count that finds exactly what was expected is still a fresh reading.
    body["reason"] = "count"
    assert api.post("/v1/inventory/movements", body, headers={"Idempotency-Key": idem()}).status_code == 201


def test_concurrent_distinct_movements_sum_exactly(store):
    _, tenant_id, variant_id, location_id = store
    deltas = [Decimal(d) for d in ([3, -1, 2, 5, -2] * 10)]

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda d: _move(tenant_id, variant_id, location_id, d, idem()), deltas))

    assert _on_hand(tenant_id, variant_id, location_id) == sum(deltas)
    assert _movement_count(tenant_id) == len(deltas)
    with transaction() as s:
        pos = inventory.get_position(s, tenant_id=tenant_id, variant_id=variant_id, location_id=location_id)
        assert pos.version == len(deltas)


def test_concurrent_same_key_applies_once(store):
    _, tenant_id, variant_id, location_id = store
    key = idem()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: _move(tenant_id, variant_id, location_id, "12", key), range(10)))

    assert sum(r.applied for r in results) == 1
    assert len({r.movement.id for r in results}) == 1
    assert _on_hand(tenant_id, variant_id, location_id) == Decimal(12)


def test_failed_transaction_leaves_no_partial_write(store):
    """Ledger row and position update commit together or not at all."""
    _, tenant_id, variant_id, location_id = store
    with pytest.raises(RuntimeError), transaction() as s:
        inventory.record_movement(
            s,
            tenant_id=tenant_id,
            variant_id=variant_id,
            location_id=location_id,
            delta=Decimal(7),
            reason="receipt",
            source="test",
            source_event_id=idem(),
            actor=system("test"),
        )
        raise RuntimeError("crash after write, before commit")

    assert _on_hand(tenant_id, variant_id, location_id) == Decimal(0)
    assert _movement_count(tenant_id) == 0


def test_replay_with_different_payload_raises_in_service(store):
    _, tenant_id, variant_id, location_id = store
    key = idem()
    _move(tenant_id, variant_id, location_id, "4", key)
    with pytest.raises(IdempotencyConflict):
        _move(tenant_id, variant_id, location_id, "4", key, reason="receipt")


def test_movement_is_audited(store):
    api, tenant_id, variant_id, location_id = store
    _move(tenant_id, variant_id, location_id, "10", idem())
    _move(tenant_id, variant_id, location_id, "-3", idem(), reason="damage")

    events = api.get("/v1/audit-events", params={"object_type": "inventory_movement"}).json()
    assert [(e["before"]["on_hand"], e["after"]["on_hand"]) for e in reversed(events)] == [
        ("0.0000", "10.0000"),
        ("10.0000", "7.0000"),
    ]
    with transaction() as s:
        assert s.scalar(select(func.count()).select_from(AuditEvent)) >= 2
