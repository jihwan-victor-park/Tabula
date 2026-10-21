"""
Sales lines from their origin system (spec 6.3). The same sale arriving twice —
two CSV exports, or a CSV now and the POS connector later — counts once, because
lines are keyed by origin system + order ID + line key.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.domain import catalog, tenancy
from clawbot.domain.errors import ValidationFailed
from clawbot.domain.units import QTY_SCALE, validate_currency
from clawbot.persistence.models import SALES_KEY_SCHEMES, SALES_SOURCES, SalesLine
from clawbot.policies.permissions import Actor, authorize


@dataclass(frozen=True)
class RecordedLine:
    line: SalesLine
    outcome: str  # created | unchanged | conflict (different numbers) | other_path (order known under another key scheme)


def record_sales_line(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
    source_system: str,
    external_order_id: str,
    external_line_key: str,
    key_scheme: str,
    sold_at: datetime,
    quantity: Decimal,
    line_type: str,
    unit_price: Decimal | None = None,
    currency: str | None = None,
    import_id: uuid.UUID | None = None,
) -> RecordedLine:
    authorize(actor, "sales.record")
    if sold_at.tzinfo is None:
        raise ValidationFailed("sold_at must include a timezone")
    if quantity != quantity.quantize(QTY_SCALE) or quantity == 0:
        raise ValidationFailed("quantity must be non-zero with at most 4 decimal places")
    if (line_type == "sale") != (quantity > 0):
        raise ValidationFailed("sales have positive quantities and refunds negative ones")
    if currency is not None:
        currency = validate_currency(currency)
    if source_system not in SALES_SOURCES or key_scheme not in SALES_KEY_SCHEMES:
        raise ValidationFailed("Unknown sales source or key scheme")
    catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)

    # One origin order is only ever recorded under one key scheme: a CSV keyed by
    # item and a POS feed keyed by line UID would otherwise both count it. The
    # advisory lock makes check-then-insert atomic per (tenant, origin, order).
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"sales:{tenant_id}:{source_system}:{external_order_id}", 0)))
    )
    other = session.scalars(
        select(SalesLine).where(
            SalesLine.tenant_id == tenant_id,
            SalesLine.source_system == source_system,
            SalesLine.external_order_id == external_order_id,
            SalesLine.key_scheme != key_scheme,
        ).limit(1)
    ).first()
    if other is not None:
        return RecordedLine(other, "other_path")

    inserted = session.execute(
        insert(SalesLine)
        .values(
            id=uuid.uuid4(), tenant_id=tenant_id, variant_id=variant_id, location_id=location_id,
            source_system=source_system, external_order_id=external_order_id, external_line_key=external_line_key,
            key_scheme=key_scheme, sold_at=sold_at, quantity=quantity, line_type=line_type, unit_price=unit_price, currency=currency,
            import_id=import_id,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "source_system", "external_order_id", "external_line_key"])
        .returning(SalesLine.id)
    ).scalar_one_or_none()
    line = session.scalars(
        select(SalesLine).where(
            SalesLine.tenant_id == tenant_id,
            SalesLine.source_system == source_system,
            SalesLine.external_order_id == external_order_id,
            SalesLine.external_line_key == external_line_key,
        )
    ).one()
    if inserted is not None:
        return RecordedLine(line, "created")
    same = (line.variant_id, line.quantity, line.line_type, line.sold_at) == (variant_id, quantity, line_type, sold_at)
    return RecordedLine(line, "unchanged" if same else "conflict")


def list_sales_lines(
    session: Session, *, tenant_id: uuid.UUID, variant_id: uuid.UUID | None = None, limit: int = 500
) -> list[SalesLine]:
    stmt = select(SalesLine).where(SalesLine.tenant_id == tenant_id)
    if variant_id is not None:
        stmt = stmt.where(SalesLine.variant_id == variant_id)
    return list(session.scalars(stmt.order_by(SalesLine.sold_at.desc()).limit(limit)))
