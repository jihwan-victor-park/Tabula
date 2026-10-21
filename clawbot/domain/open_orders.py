"""
Orders placed outside Tabula that have not fully arrived (spec 3.4, 6.4).

They exist so replenishment never re-orders what is already on the way. Only
lines the supplier confirmed count as confirmed inbound; unconfirmed ones only
suppress duplicate orders.

Reports are snapshots: each carries the time it was true (`reported_at`). An
older report never overwrites a newer one, and a report declared *complete* for
a supplier closes that supplier's lines it no longer lists (they were received
or cancelled) — otherwise received orders would block reorders forever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.domain import audit, catalog, suppliers, tenancy
from clawbot.domain.errors import ValidationFailed
from clawbot.domain.units import QTY_SCALE
from clawbot.persistence.models import ExternalOpenOrderLine
from clawbot.policies.permissions import Actor, authorize


@dataclass(frozen=True)
class UpsertedLine:
    line: ExternalOpenOrderLine
    outcome: str  # "created" | "updated" | "unchanged" | "older_report"


def upsert_open_order_line(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
    external_po_number: str,
    outstanding_qty: Decimal,
    supplier_confirmed: bool,
    ordered_at: datetime | None = None,
    expected_at: datetime | None = None,
    import_id: uuid.UUID | None = None,
    reported_at: datetime | None = None,
) -> UpsertedLine:
    authorize(actor, "orders.record_external")
    if outstanding_qty < 0 or outstanding_qty != outstanding_qty.quantize(QTY_SCALE):
        raise ValidationFailed("outstanding_qty must be ≥ 0 with at most 4 decimal places")
    for value in (ordered_at, expected_at, reported_at):
        if value is not None and value.tzinfo is None:
            raise ValidationFailed("dates must include a timezone")
    suppliers.get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)

    line = session.scalars(
        select(ExternalOpenOrderLine)
        .where(
            ExternalOpenOrderLine.tenant_id == tenant_id,
            ExternalOpenOrderLine.supplier_id == supplier_id,
            ExternalOpenOrderLine.external_po_number == external_po_number,
            ExternalOpenOrderLine.variant_id == variant_id,
        )
        .with_for_update()
    ).one_or_none()
    fields = dict(
        location_id=location_id, outstanding_qty=outstanding_qty, supplier_confirmed=supplier_confirmed,
        ordered_at=ordered_at, expected_at=expected_at,
    )
    if line is not None and line.reported_at and reported_at and reported_at < line.reported_at:
        return UpsertedLine(line, "older_report")
    if line is None:
        line = ExternalOpenOrderLine(
            tenant_id=tenant_id, supplier_id=supplier_id, variant_id=variant_id,
            external_po_number=external_po_number, import_id=import_id, reported_at=reported_at, **fields,
        )
        session.add(line)
        session.flush()
        return UpsertedLine(line, "created")
    reopened = line.closed_at is not None
    if all(getattr(line, k) == val for k, val in fields.items()) and not reopened:
        if reported_at and (line.reported_at is None or reported_at > line.reported_at):
            line.reported_at = reported_at
        return UpsertedLine(line, "unchanged")
    for k, val in fields.items():
        setattr(line, k, val)
    line.import_id, line.closed_at = import_id, None
    if reported_at:
        line.reported_at = reported_at
    line.updated_at = datetime.now(timezone.utc)
    session.flush()
    return UpsertedLine(line, "updated")


def list_open_order_lines(session: Session, *, tenant_id: uuid.UUID) -> list[ExternalOpenOrderLine]:
    return list(
        session.scalars(
            select(ExternalOpenOrderLine)
            .where(ExternalOpenOrderLine.tenant_id == tenant_id, ExternalOpenOrderLine.outstanding_qty > 0)
            .order_by(ExternalOpenOrderLine.expected_at.nulls_last())
        )
    )


def close_missing_from_report(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    location_id: uuid.UUID,
    listed: set[tuple[str, uuid.UUID]],
    reported_at: datetime,
    source_ref: str,
) -> int:
    """A complete report for this supplier and location: close older open lines it does not list."""
    authorize(actor, "orders.record_external")
    stale = list(session.scalars(
        select(ExternalOpenOrderLine).where(
            ExternalOpenOrderLine.tenant_id == tenant_id, ExternalOpenOrderLine.supplier_id == supplier_id,
            ExternalOpenOrderLine.location_id == location_id, ExternalOpenOrderLine.outstanding_qty > 0,
            ExternalOpenOrderLine.closed_at.is_(None),
        ).with_for_update()
    ))
    closed = 0
    for line in stale:
        if (line.external_po_number, line.variant_id) in listed:
            continue
        if line.reported_at is not None and line.reported_at >= reported_at:
            continue  # a newer report listed it
        before = {"outstanding_qty": str(line.outstanding_qty)}
        line.outstanding_qty, line.closed_at = Decimal(0), datetime.now(timezone.utc)
        line.updated_at = line.closed_at
        closed += 1
        audit.record(session, tenant_id=tenant_id, actor=actor, action="open_order.closed_by_report",
                     object_type="external_open_order_line", object_id=line.id, before=before,
                     after={"outstanding_qty": "0"}, reason=f"Not listed in complete report {source_ref}")
    session.flush()
    return closed
