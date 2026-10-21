"""
Inventory ledger.

record_movement() writes the ledger row and updates the position in the
caller's transaction, so a crash can never leave one without the other
(the legacy Mongo adjust_stock() did these as two separate writes).

Each movement is keyed by (tenant_id, source, source_event_id). Replaying the
same event returns the original movement and does not change stock again.

Write ownership (spec 3.3, 6.3): a location whose stock counts belong to a POS
accepts no Tabula movements — Tabula reads the POS and posts receipts through
the connector, so one physical change is never counted twice. People recording
changes by hand may adjust, count-correct, write off damage or record returns;
receipts and transfers only come from their own flows (receiving, transfers).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from clawbot.domain import audit, catalog, tenancy
from clawbot.domain.errors import IdempotencyConflict, StateConflict, ValidationFailed
from clawbot.domain.units import QTY_SCALE
from clawbot.persistence.models import MOVEMENT_REASONS, InventoryMovement, InventoryPosition, InventorySnapshot
from clawbot.policies.permissions import Actor, authorize

MANUAL_SOURCE = "manual"
MANUAL_REASONS = ("adjustment", "count", "damage", "return")


@dataclass(frozen=True)
class MovementResult:
    movement: InventoryMovement
    position: InventoryPosition
    applied: bool  # False when this call was a replay of an already-recorded event


def record_movement(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
    delta: Decimal,
    reason: str,
    source: str,
    source_event_id: str,
    actor: Actor,
    notes: str | None = None,
    occurred_at: datetime | None = None,
) -> MovementResult:
    authorize(actor, "inventory.move")
    delta = Decimal(delta)
    if delta != delta.quantize(QTY_SCALE):
        raise ValidationFailed("delta supports at most 4 decimal places")
    if delta == 0:
        raise ValidationFailed("delta must be non-zero")
    if reason not in MOVEMENT_REASONS:
        raise ValidationFailed(f"Unknown reason: {reason}")
    if (actor.kind == "human" or source == MANUAL_SOURCE) and reason not in MANUAL_REASONS:
        raise ValidationFailed(
            f"'{reason}' cannot be recorded by hand; it comes from its own flow (receiving, transfers)"
        )
    if occurred_at is not None and occurred_at.tzinfo is None:
        raise ValidationFailed("occurred_at must include a timezone")
    # Raises NotFound for IDs outside this tenant; the composite FKs are the backstop.
    catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    # A replay of an already-recorded event returns the original result even if the
    # location has since moved to POS ownership.
    replay = _existing(session, tenant_id=tenant_id, source=source, source_event_id=source_event_id)
    if replay is not None:
        return _replayed(session, replay, variant_id, location_id, delta, reason, notes, occurred_at)
    if location.inventory_write_owner != "tabula":
        raise StateConflict(
            f"Stock at {location.name} is owned by {location.inventory_write_owner}; change it there",
            details={"inventory_write_owner": location.inventory_write_owner},
        )

    movement_id = uuid.uuid4()
    inserted = session.execute(
        insert(InventoryMovement)
        .values(
            id=movement_id,
            tenant_id=tenant_id,
            variant_id=variant_id,
            location_id=location_id,
            delta=delta,
            reason=reason,
            source=source,
            source_event_id=source_event_id,
            actor_user_id=actor.user_id,
            notes=notes,
            occurred_at=occurred_at or datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "source", "source_event_id"])
        .returning(InventoryMovement.id)
    ).scalar_one_or_none()

    if inserted is None:  # a concurrent request recorded the same event first
        existing = _existing(session, tenant_id=tenant_id, source=source, source_event_id=source_event_id)
        assert existing is not None
        return _replayed(session, existing, variant_id, location_id, delta, reason, notes, occurred_at)

    # Single-statement upsert takes the row lock, so concurrent movements serialize here.
    position = session.execute(
        insert(InventoryPosition)
        .values(
            tenant_id=tenant_id,
            variant_id=variant_id,
            location_id=location_id,
            on_hand=delta,
            version=1,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "variant_id", "location_id"],
            set_={
                "on_hand": InventoryPosition.on_hand + delta,
                "version": InventoryPosition.version + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        .returning(InventoryPosition)
        .execution_options(populate_existing=True)
    ).scalar_one()

    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="inventory.movement_recorded",
        object_type="inventory_movement",
        object_id=movement_id,
        before={"on_hand": str(position.on_hand - delta)},
        after={"on_hand": str(position.on_hand), "delta": str(delta), "reason": reason},
        reason=notes,
    )
    movement = session.get(InventoryMovement, movement_id)
    assert movement is not None
    return MovementResult(movement=movement, position=position, applied=True)


def _existing(
    session: Session, *, tenant_id: uuid.UUID, source: str, source_event_id: str
) -> InventoryMovement | None:
    return session.scalars(
        select(InventoryMovement).where(
            InventoryMovement.tenant_id == tenant_id,
            InventoryMovement.source == source,
            InventoryMovement.source_event_id == source_event_id,
        )
    ).one_or_none()


def _replayed(
    session: Session,
    existing: InventoryMovement,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
    delta: Decimal,
    reason: str,
    notes: str | None,
    occurred_at: datetime | None,
) -> MovementResult:
    same = (existing.variant_id, existing.location_id, existing.delta, existing.reason, existing.notes) == (
        variant_id, location_id, delta, reason, notes,
    ) and (occurred_at is None or existing.occurred_at == occurred_at)
    if not same:
        raise IdempotencyConflict(
            f"Event {existing.source}:{existing.source_event_id} was already recorded with a different payload"
        )
    position = get_position(
        session, tenant_id=existing.tenant_id, variant_id=existing.variant_id, location_id=existing.location_id
    )
    assert position is not None
    return MovementResult(movement=existing, position=position, applied=False)


def get_position(
    session: Session, *, tenant_id: uuid.UUID, variant_id: uuid.UUID, location_id: uuid.UUID
) -> InventoryPosition | None:
    return session.get(InventoryPosition, (tenant_id, variant_id, location_id))


def list_positions(
    session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID | None = None
) -> list[InventoryPosition]:
    stmt = select(InventoryPosition).where(InventoryPosition.tenant_id == tenant_id)
    if location_id is not None:
        stmt = stmt.where(InventoryPosition.location_id == location_id)
    return list(session.scalars(stmt))


def list_movements(
    session: Session, *, tenant_id: uuid.UUID, variant_id: uuid.UUID | None = None, limit: int = 50
) -> list[InventoryMovement]:
    stmt = select(InventoryMovement).where(InventoryMovement.tenant_id == tenant_id)
    if variant_id is not None:
        stmt = stmt.where(InventoryMovement.variant_id == variant_id)
    stmt = stmt.order_by(InventoryMovement.recorded_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def record_snapshot(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
    quantity: Decimal,
    as_of: datetime,
    source_system: str,
    source_ref: str,
) -> tuple[InventorySnapshot, bool]:
    """Record a reported stock level. Idempotent per (source, ref, location, variant). Returns (row, is_new)."""
    authorize(actor, "inventory.snapshot")
    if as_of.tzinfo is None:
        raise ValidationFailed("as_of must include a timezone")
    if Decimal(quantity) != Decimal(quantity).quantize(QTY_SCALE):
        raise ValidationFailed("quantity supports at most 4 decimal places")
    catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    inserted = session.execute(
        insert(InventorySnapshot)
        .values(
            id=uuid.uuid4(), tenant_id=tenant_id, variant_id=variant_id, location_id=location_id,
            quantity=quantity, as_of=as_of, source_system=source_system, source_ref=source_ref,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "source_system", "source_ref", "location_id", "variant_id"])
        .returning(InventorySnapshot.id)
    ).scalar_one_or_none()
    snapshot = session.scalars(
        select(InventorySnapshot).where(
            InventorySnapshot.tenant_id == tenant_id,
            InventorySnapshot.source_system == source_system,
            InventorySnapshot.source_ref == source_ref,
            InventorySnapshot.location_id == location_id,
            InventorySnapshot.variant_id == variant_id,
        )
    ).one()
    return snapshot, inserted is not None


def latest_snapshots(
    session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID | None = None
) -> list[InventorySnapshot]:
    stmt = (
        select(InventorySnapshot)
        .where(InventorySnapshot.tenant_id == tenant_id)
        .ext(distinct_on(InventorySnapshot.location_id, InventorySnapshot.variant_id))
        .order_by(InventorySnapshot.location_id, InventorySnapshot.variant_id, InventorySnapshot.as_of.desc())
    )
    if location_id is not None:
        stmt = stmt.where(InventorySnapshot.location_id == location_id)
    return list(session.scalars(stmt))
