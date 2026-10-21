"""
Orders placed outside Tabula that have not fully arrived (spec 3.4, 6.4).

They exist so replenishment never re-orders what is already on the way. Only
lines the supplier confirmed count as confirmed inbound; unconfirmed ones only
suppress duplicate orders. The latest report for a (supplier, PO, item) wins.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.domain import catalog, suppliers, tenancy
from clawbot.domain.errors import ValidationFailed
from clawbot.domain.units import QTY_SCALE
from clawbot.persistence.models import ExternalOpenOrderLine
from clawbot.policies.permissions import Actor, authorize


@dataclass(frozen=True)
class UpsertedLine:
    line: ExternalOpenOrderLine
    outcome: str  # "created" | "updated" | "unchanged"


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
) -> UpsertedLine:
    authorize(actor, "orders.record_external")
    if outstanding_qty < 0 or outstanding_qty != outstanding_qty.quantize(QTY_SCALE):
        raise ValidationFailed("outstanding_qty must be ≥ 0 with at most 4 decimal places")
    for value in (ordered_at, expected_at):
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
    if line is None:
        line = ExternalOpenOrderLine(
            tenant_id=tenant_id, supplier_id=supplier_id, variant_id=variant_id,
            external_po_number=external_po_number, import_id=import_id, **fields,
        )
        session.add(line)
        session.flush()
        return UpsertedLine(line, "created")
    if all(getattr(line, k) == val for k, val in fields.items()):
        return UpsertedLine(line, "unchanged")
    for k, val in fields.items():
        setattr(line, k, val)
    line.import_id = import_id
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
