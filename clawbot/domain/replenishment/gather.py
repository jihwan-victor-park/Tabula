"""
Collect engine inputs for one location as of a cutoff, from the normalized data
CP3 imports and connectors write.

  stock   Tabula-owned location: anchored on the latest stock *count* in the ledger —
          level at that count + other movements since (damage, adjustments, returns)
          − units sold since. POS-owned: the latest POS snapshot (a manual import only
          if there is no POS reading) − units sold since. Refunds after the reading are
          not added back: whether refunded goods went back on the shelf is unknown.
  demand  sales_lines bucketed by the store's local date, only over dates a source
          declared complete (sales_coverage); uncovered days are missing data, not
          zero sales. Days a snapshot showed zero stock are excluded from the average.
  inbound external open orders (supplier-confirmed vs not, with their age).
  supply  every eligible supplier offer (one currency), with calendar-based arrival.

Every query is ordered, so the same database state always yields the same inputs.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clawbot.domain import sales, suppliers, tenancy
from clawbot.domain.replenishment.calendar import SupplierCalendar, arrival_day_for_eta, arrival_for_order_now
from clawbot.domain.replenishment.engine import ZERO, InboundLine, ItemInputs, OfferInputs, Policy, SupplierTerms
from clawbot.domain.units import require_same_currency, CurrencyMismatch
from clawbot.persistence.models import (
    ExternalOpenOrderLine,
    InventoryMovement,
    InventorySnapshot,
    ReplenishmentItemSetting,
    SalesLine,
    Supplier,
    SupplierClosure,
    Variant,
)


@dataclass
class Gathered:
    items: list[ItemInputs]
    suppliers: dict[str, SupplierTerms]
    planning_date: date


@dataclass(frozen=True)
class _Reading:
    quantity: Decimal  # level at the anchor, plus non-count movements after it
    at: datetime
    source: str
    counted: bool
    moves_since: Decimal = ZERO


def _hours(a: datetime, b: datetime) -> Decimal:
    return (Decimal((a - b).total_seconds()) / Decimal(3600)).quantize(Decimal("0.01"))


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def _ledger_readings(session: Session, tenant_id, location_id, cutoff: datetime) -> dict[uuid.UUID, _Reading]:
    moves = defaultdict(list)
    for vid, delta, reason, at in session.execute(
        select(InventoryMovement.variant_id, InventoryMovement.delta, InventoryMovement.reason, InventoryMovement.occurred_at)
        .where(InventoryMovement.tenant_id == tenant_id, InventoryMovement.location_id == location_id,
               InventoryMovement.occurred_at <= cutoff)
        .order_by(InventoryMovement.variant_id, InventoryMovement.occurred_at, InventoryMovement.id)
    ):
        moves[vid].append((delta, reason, at))
    readings = {}
    for vid, rows in moves.items():
        counts = [at for _, reason, at in rows if reason == "count"]
        if counts:
            anchor = counts[-1]
            level = sum((d for d, _, at in rows if at <= anchor), ZERO)
            after = sum((d for d, _, at in rows if at > anchor), ZERO)
            readings[vid] = _Reading(level + after, anchor, "Tabula ledger (last count)", True, after)
        else:
            readings[vid] = _Reading(sum((d for d, _, _ in rows), ZERO), rows[-1][2], "Tabula ledger (never counted)", False)
    return readings


def _snapshot_readings(session: Session, tenant_id, location_id, cutoff: datetime) -> dict[uuid.UUID, _Reading]:
    readings: dict[uuid.UUID, _Reading] = {}
    for snap in session.scalars(
        select(InventorySnapshot)
        .where(InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.location_id == location_id,
               InventorySnapshot.as_of <= cutoff)
        .order_by(InventorySnapshot.variant_id, InventorySnapshot.as_of.desc(), InventorySnapshot.source_system,
                  InventorySnapshot.id)
    ):
        current = readings.get(snap.variant_id)
        is_pos = snap.source_system != "import"
        # Newest POS reading wins; a manual import only when no POS reading exists.
        if current is None or (is_pos and current.source.startswith("manual")):
            readings[snap.variant_id] = _Reading(
                snap.quantity, snap.as_of, f"{snap.source_system} snapshot" if is_pos else "manual import (no POS reading)",
                True)
    return readings


def gather(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID, cutoff: datetime, policy: Policy) -> Gathered:
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    tz = ZoneInfo(location.timezone)
    planning_date = cutoff.astimezone(tz).date()
    day_start = _local_midnight(planning_date, tz)
    yesterday = planning_date - timedelta(days=1)
    window_start_date = planning_date - timedelta(days=policy.long_window_days)

    # ---- which days have complete sales data
    covered = sales.covered_dates(session, tenant_id=tenant_id, location_id=location_id,
                                  start=window_start_date, end=yesterday)
    first_sale, last_sale = session.execute(
        select(func.min(SalesLine.sold_at), func.max(SalesLine.sold_at)).where(
            SalesLine.tenant_id == tenant_id, SalesLine.location_id == location_id, SalesLine.sold_at <= cutoff)
    ).one()
    coverage_inferred = covered is None
    if covered is None:  # no coverage records (e.g. lines written directly): fall back to first..last sale
        covered = set()
        if first_sale and last_sale:
            day = max(first_sale.astimezone(tz).date(), window_start_date)
            while day <= min(last_sale.astimezone(tz).date(), yesterday):
                covered.add(day)
                day += timedelta(days=1)
    covered_days = sorted(covered)
    if covered_days and not coverage_inferred:
        sales_through_dt = _local_midnight(covered_days[-1] + timedelta(days=1), tz)
    else:
        sales_through_dt = last_sale

    # ---- daily net sales per variant (local dates, before today)
    local_day = func.date(func.timezone(location.timezone, SalesLine.sold_at))
    daily: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(dict)
    for vid, day, qty in session.execute(
        select(SalesLine.variant_id, local_day, func.sum(SalesLine.quantity))
        .where(SalesLine.tenant_id == tenant_id, SalesLine.location_id == location_id,
               SalesLine.sold_at >= _local_midnight(window_start_date, tz), SalesLine.sold_at < day_start)
        .group_by(SalesLine.variant_id, local_day)
    ):
        daily[vid][day] = qty

    # ---- stock readings as of the cutoff
    readings = (_ledger_readings(session, tenant_id, location_id, cutoff) if location.inventory_write_owner == "tabula"
                else _snapshot_readings(session, tenant_id, location_id, cutoff))
    sold_since: dict[uuid.UUID, Decimal] = {}
    if readings:
        earliest = min(r.at for r in readings.values())
        for vid, sold_at, qty in session.execute(
            select(SalesLine.variant_id, SalesLine.sold_at, SalesLine.quantity).where(
                SalesLine.tenant_id == tenant_id, SalesLine.location_id == location_id, SalesLine.line_type == "sale",
                SalesLine.sold_at > earliest, SalesLine.sold_at <= cutoff)
        ):
            if vid in readings and sold_at > readings[vid].at:
                sold_since[vid] = sold_since.get(vid, ZERO) + qty

    # ---- days a snapshot showed nothing on the shelf (excluded from demand)
    stockouts: dict[uuid.UUID, set[date]] = defaultdict(set)
    for vid, as_of in session.execute(
        select(InventorySnapshot.variant_id, InventorySnapshot.as_of).where(
            InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.location_id == location_id,
            InventorySnapshot.quantity <= 0, InventorySnapshot.as_of >= _local_midnight(window_start_date, tz),
            InventorySnapshot.as_of < day_start)
    ):
        stockouts[vid].add(as_of.astimezone(tz).date())

    # ---- open orders placed outside Tabula
    inbound: dict[uuid.UUID, list[InboundLine]] = defaultdict(list)
    supplier_names = {s.id: s.name for s in session.scalars(select(Supplier).where(Supplier.tenant_id == tenant_id))}
    for line in session.scalars(
        select(ExternalOpenOrderLine).where(
            ExternalOpenOrderLine.tenant_id == tenant_id, ExternalOpenOrderLine.location_id == location_id,
            ExternalOpenOrderLine.outstanding_qty > 0)
        .order_by(ExternalOpenOrderLine.external_po_number, ExternalOpenOrderLine.supplier_id, ExternalOpenOrderLine.id)
    ):
        arrival = (arrival_day_for_eta(eta=line.expected_at, now=cutoff, store_timezone=location.timezone)
                   if line.expected_at else None)
        since = line.ordered_at or line.created_at
        inbound[line.variant_id].append(InboundLine(
            reference=f"{line.external_po_number} ({supplier_names.get(line.supplier_id, 'supplier')})",
            quantity=line.outstanding_qty, confirmed=line.supplier_confirmed, arrival_day=arrival,
            age_days=max((cutoff - since).days, 0) if since else None,
        ))

    settings = {s.variant_id: s for s in session.scalars(
        select(ReplenishmentItemSetting).where(ReplenishmentItemSetting.tenant_id == tenant_id,
                                               ReplenishmentItemSetting.location_id == location_id))}
    closures: dict[uuid.UUID, list[tuple[date, date]]] = defaultdict(list)
    for c in session.scalars(select(SupplierClosure).where(SupplierClosure.tenant_id == tenant_id)
                             .order_by(SupplierClosure.starts_on, SupplierClosure.id)):
        closures[c.supplier_id].append((c.starts_on, c.ends_on))

    # Items worth planning: active ones, plus discontinued ones that still sell or are on order.
    variants = [v for v in session.scalars(select(Variant).where(Variant.tenant_id == tenant_id).order_by(Variant.sku))
                if v.status == "active" or v.id in daily or v.id in inbound]

    items: list[ItemInputs] = []
    terms: dict[str, SupplierTerms] = {}
    for v in variants:
        series = tuple((d, daily.get(v.id, {}).get(d, ZERO)) for d in covered_days)
        reading = readings.get(v.id)
        since = sold_since.get(v.id, ZERO)

        offers = [o for o in suppliers.offers_for_variant(session, tenant_id=tenant_id, variant_id=v.id,
                                                          location_id=location_id, at=cutoff) if o.eligible]
        offer_inputs: list[OfferInputs] = []
        blockers: tuple[str, ...] = ()
        try:
            require_same_currency(*(o.price.currency for o in offers)) if offers else None
        except CurrencyMismatch:
            offers, blockers = [], ("mixed_currency_offers",)
        for o in offers:
            s = o.supplier
            arrival = arrival_for_order_now(
                now=cutoff, store_timezone=location.timezone, lead_time_days=o.lead_time_days,
                cal=SupplierCalendar(s.timezone, s.order_cutoff_local, tuple(s.delivery_weekdays),
                                     tuple(closures.get(s.id, []))),
            )
            offer_inputs.append(OfferInputs(
                supplier_item_id=str(o.supplier_item.id), supplier_id=str(s.id), supplier_name=s.name,
                order_uom=o.supplier_item.order_uom, units_per_order_uom=o.supplier_item.units_per_order_uom,
                order_multiple=o.supplier_item.order_multiple, min_order_qty=o.supplier_item.min_order_qty,
                unit_price=o.price.unit_price, currency=o.price.currency, price_as_of=o.price.valid_from.isoformat(),
                arrival_day=arrival.arrival_day, calendar_notes=arrival.notes,
            ))
            terms[str(s.id)] = SupplierTerms(str(s.id), s.name, s.currency, s.min_order_amount, s.free_shipping_threshold)
        if not offer_inputs and not blockers:
            all_offers = suppliers.offers_for_variant(session, tenant_id=tenant_id, variant_id=v.id,
                                                      location_id=location_id, at=cutoff)
            blockers = tuple(sorted({b for o in all_offers for b in o.blockers})) or ("no_supplier_item",)

        st = settings.get(v.id)
        items.append(ItemInputs(
            variant_id=str(v.id), sku=v.sku, planning_date=planning_date, variant_active=v.status == "active",
            on_hand=None if reading is None else reading.quantity - since,
            stock_source=reading.source if reading else None,
            stock_as_of=reading.at.isoformat() if reading else None,
            stock_age_hours=_hours(cutoff, reading.at) if reading else None,
            stock_counted=reading.counted if reading else True,
            sales_since_reading=since, moves_since_reading=reading.moves_since if reading else ZERO,
            daily_sales=series, stockout_dates=tuple(sorted(stockouts.get(v.id, ()))),
            history_days=len(series), coverage_inferred=coverage_inferred,
            sales_through=sales_through_dt.isoformat() if sales_through_dt else None,
            sales_age_hours=_hours(cutoff, sales_through_dt) if sales_through_dt else None,
            inbound=tuple(sorted(inbound.get(v.id, ()), key=lambda i: (i.reference, i.quantity))),
            offers=tuple(sorted(offer_inputs, key=lambda o: o.supplier_item_id)), offer_blockers=blockers,
            safety_stock=st.safety_stock if st else None, min_qty=st.min_qty if st else None,
            max_qty=st.max_qty if st else None, excluded=st.excluded if st else False,
        ))
    return Gathered(items=items, suppliers=dict(sorted(terms.items())), planning_date=planning_date)
