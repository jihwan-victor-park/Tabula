"""
Sales lines from their origin system (spec 6.3). The same sale arriving twice —
two CSV exports, or a CSV now and the POS connector later — counts once, because
lines are keyed by origin system + order ID + line key.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.domain import catalog, data_version, tenancy
from clawbot.domain.errors import NotFound, StateConflict, ValidationFailed
from clawbot.domain.units import QTY_SCALE, validate_currency
from clawbot.persistence.models import SALES_KEY_SCHEMES, SALES_SOURCES, SalesCoverage, SalesLine
from clawbot.policies.permissions import Actor, authorize


@dataclass(frozen=True)
class RecordedLine:
    line: SalesLine
    outcome: str  # created | unchanged | conflict (different numbers) | other_path (order known under another key scheme)


def feed_at(location, moment: datetime) -> str:
    """Which source owned this location's sales at `moment` (files before any switch)."""
    owner = "files"
    for entry in location.sales_feed_history or []:
        if datetime.fromisoformat(entry["since"]) <= moment:
            owner = entry["feed"]
        else:
            break
    return owner


def feed_problem(location, *, sold_at: datetime, from_connector: bool) -> str | None:
    """
    One sales source per location for every moment (CSV ↔ Square ownership, CHECKPOINTS D4).
    The owner of the sale's own moment decides — from the switch history, so switching back
    never reopens a period the other source already recorded.
    """
    owner = feed_at(location, sold_at)
    if from_connector and owner != "square":
        return f"{location.name}'s sales at {sold_at.isoformat()} come from uploaded files"
    if not from_connector and owner == "square":
        return f"Square records {location.name}'s sales at {sold_at.isoformat()}; this file's sale is in that period"
    return None


def set_feed(session: Session, *, tenant_id: uuid.UUID, actor: Actor, location_id: uuid.UUID, feed: str,
             since: datetime) -> Any:
    """
    Switch a location's sales source at `since`. Refused if the new source would overlap sales
    already recorded by the old one after that moment (pick a later switch time instead).
    """
    from clawbot.domain import audit as _audit
    from clawbot.persistence.models import ConnectorLocationLink

    authorize(actor, "location.edit")
    if feed not in ("files", "square"):
        raise ValidationFailed("feed must be files or square")
    if since.tzinfo is None:
        raise ValidationFailed("since must include a timezone")
    from clawbot.persistence.models import Location

    location = session.scalars(select(Location).where(Location.tenant_id == tenant_id, Location.id == location_id)
                               .with_for_update()).one_or_none()
    if location is None:
        raise NotFound(f"Location not found: {location_id}")
    if feed == "square" and session.scalar(select(ConnectorLocationLink.location_id).where(
            ConnectorLocationLink.tenant_id == tenant_id, ConnectorLocationLink.location_id == location_id)) is None:
        raise StateConflict("Link this location to a Square location first")
    history = list(location.sales_feed_history or [])
    if history and since <= datetime.fromisoformat(history[-1]["since"]):
        raise StateConflict("A switch can only take effect after the last one "
                            f"({history[-1]['since']}); past periods keep their source",
                            details={"last_switch": history[-1]["since"]})
    if feed_at(location, since) == feed:
        raise StateConflict(f"Sales already come from {feed} at that time")
    other_scheme = SalesLine.key_scheme != "provider_line" if feed == "square" else SalesLine.key_scheme == "provider_line"
    overlap = session.scalar(select(func.max(SalesLine.sold_at)).where(
        SalesLine.tenant_id == tenant_id, SalesLine.location_id == location_id, other_scheme, SalesLine.sold_at >= since))
    if overlap is not None:
        raise StateConflict(f"Sales from the current source are already recorded up to {overlap.isoformat()}; "
                            "switch at a later time so no sale is counted twice",
                            details={"latest_recorded": overlap.isoformat()})
    before = {"feed": location.sales_feed, "since": location.sales_feed_since.isoformat() if location.sales_feed_since else None}
    location.sales_feed, location.sales_feed_since = feed, since
    location.sales_feed_history = [*history, {"feed": feed, "since": since.isoformat()}]
    if feed == "square":
        # Sync from the switch time even if the connection has been syncing (and recording nothing) since then.
        from clawbot.persistence.models import ConnectorAccount, ConnectorLocationLink

        for account in session.scalars(select(ConnectorAccount).join(ConnectorLocationLink, (
                ConnectorLocationLink.tenant_id == ConnectorAccount.tenant_id) & (
                ConnectorLocationLink.connector_account_id == ConnectorAccount.id)).where(
                ConnectorLocationLink.tenant_id == tenant_id, ConnectorLocationLink.location_id == location_id)
                .with_for_update(of=ConnectorAccount)):
            state = dict(account.sync_state or {})
            if state.get("sales_synced_through", "") > since.astimezone(timezone.utc).isoformat():
                state["sales_synced_through"] = since.astimezone(timezone.utc).isoformat()
            account.sync_state = state
    data_version.bump(session, tenant_id)
    _audit.record(session, tenant_id=tenant_id, actor=actor, action="location.sales_feed_set", object_type="location",
                  object_id=location.id, before=before, after={"feed": feed, "since": since.isoformat()})
    return location


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
    restock: bool | None = None,
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
    # Share lock: a switch of the sales source (set_feed, FOR UPDATE) waits for sales being written now.
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id, for_share=True)
    problem = feed_problem(location, sold_at=sold_at, from_connector=key_scheme == "provider_line")
    if problem:
        raise ValidationFailed(problem)
    if line_type != "refund":
        restock = None

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
            import_id=import_id, restock=restock,
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
        data_version.bump(session, tenant_id)
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


def record_coverage(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    location_id: uuid.UUID,
    source_system: str,
    source_ref: str,
    starts_on: date,
    ends_on: date,
) -> None:
    """Declare that `source_system` reported every sale at this location for these local dates."""
    authorize(actor, "sales.record")
    if ends_on < starts_on:
        raise ValidationFailed("ends_on must be on or after starts_on")
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    session.execute(
        insert(SalesCoverage)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, location_id=location_id, source_system=source_system,
                source_ref=source_ref, starts_on=starts_on, ends_on=ends_on)
        .on_conflict_do_nothing(index_elements=["tenant_id", "location_id", "source_system", "source_ref"])
    )
    data_version.bump(session, tenant_id)


def covered_dates(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID, start: date, end: date) -> set[date] | None:
    """
    Covered local dates in [start, end], or None if the location has no coverage records.

    Every origin that reports sales here is expected from its first covered day
    onwards (an origin never silently stops). A date counts as covered only if
    every origin expected on that date reported it — so one origin's export can
    never make another origin's missing days look like zero sales.
    """
    from datetime import timedelta

    by_origin: dict[str, list[tuple[date, date]]] = {}
    for origin, a, b in session.execute(
        select(SalesCoverage.source_system, SalesCoverage.starts_on, SalesCoverage.ends_on)
        .where(SalesCoverage.tenant_id == tenant_id, SalesCoverage.location_id == location_id)
        .order_by(SalesCoverage.source_system, SalesCoverage.starts_on)
    ):
        by_origin.setdefault(origin, []).append((a, b))
    if not by_origin:
        return None
    first = {origin: min(a for a, _ in ranges) for origin, ranges in by_origin.items()}
    days: set[date] = set()
    day = start
    while day <= end:
        expected = [o for o, f in first.items() if f <= day]
        if expected and all(any(a <= day <= b for a, b in by_origin[o]) for o in expected):
            days.add(day)
        day += timedelta(days=1)
    return days
