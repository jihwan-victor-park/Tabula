"""
What the store owner sees: stock per item, one item's history, sales analysis, and which
features the store's data can support yet. Read-only views over the same calculation the
plan uses (replenishment.service.evaluate), so the numbers on the dashboard and in an order
suggestion never disagree.

Freshness is part of every number: stock is "as of" its last count / POS reading, and an
estimate since then (minus sales recorded since) is labelled as such — never shown as live.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clawbot.domain import sales, tenancy
from clawbot.domain.replenishment import service
from clawbot.persistence.models import (
    PO_SENT_STATUSES,
    InventoryMovement,
    InventorySnapshot,
    PoLine,
    PurchaseOrder,
    SalesLine,
    Supplier,
    SupplierItem,
    SupplierItemPrice,
    Variant,
)

ZERO = Decimal(0)
STALE_AFTER_HOURS = 24


def _n(d: Any) -> str | None:
    if d is None:
        return None
    d = Decimal(str(d))
    return f"{(d.quantize(Decimal('0.01')) if d != d.to_integral_value() else d).normalize():f}"


def overview(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID) -> dict[str, Any]:
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    ev = service.evaluate(session, tenant_id=tenant_id, location_id=location_id)
    variants = {v.id: v for v in session.scalars(select(Variant).where(Variant.tenant_id == tenant_id))}
    suppliers = dict(session.execute(select(Supplier.id, Supplier.name).where(Supplier.tenant_id == tenant_id)).all())
    from clawbot.domain import purchasing

    on_draft = purchasing.open_po_numbers(session, tenant_id=tenant_id, location_id=location_id)
    today = datetime.now(ZoneInfo(location.timezone)).date()
    rows = []
    for vid, line in ev.lines.items():
        v = variants.get(vid)
        if v is None:
            continue
        i, r = line.inputs, line.result
        on_hand = Decimal(i["on_hand"]) if i.get("on_hand") is not None else None
        demand = Decimal(r["daily_demand"]) if r.get("daily_demand") else None
        confirmed = sum((Decimal(x["quantity"]) for x in i.get("inbound", []) if x["confirmed"]), ZERO)
        unconfirmed = sum((Decimal(x["quantity"]) for x in i.get("inbound", []) if not x["confirmed"]), ZERO)
        without = r.get("stockout_days_without_order") or []
        stockout = (date.fromisoformat(i["planning_date"]) + timedelta(days=without[0] - 1)).isoformat() if without else None
        age = Decimal(i["stock_age_hours"]) if i.get("stock_age_hours") is not None else None
        counted = bool(i.get("stock_counted", True))
        if on_hand is None:
            state = "no_stock_data"
        elif on_hand <= 0:
            state = "out_of_stock"
        elif without and without[0] <= 7:
            state = "at_risk"
        elif demand is None:
            state = "no_sales_data"
        else:
            state = "ok"
        rows.append({
            "variant_id": str(vid), "sku": v.sku, "name": v.name, "barcode": v.barcode, "status": v.status,
            "on_hand": _n(on_hand), "incoming_confirmed": _n(confirmed), "incoming_unconfirmed": _n(unconfirmed),
            "daily_demand": _n(demand), "days_of_cover": _n(on_hand / demand) if on_hand is not None and demand else None,
            "stockout_date": stockout, "state": state, "plan_status": line.status,
            # What the plan would order now (same engine, not saved); a draft already holding the item is named.
            "reorder": {"qty": _n(line.order_qty), "uom": line.order_uom, "base_qty": _n(line.base_qty),
                        "cost": _n(line.line_cost), "currency": line.currency,
                        "supplier": suppliers.get(line.supplier_id) if line.supplier_id else None,
                        "on_draft": on_draft.get(vid)} if line.status == "order" else None,
            "stock_as_of": i.get("stock_as_of"), "stock_source": i.get("stock_source"),
            # A level built only from scans/adjustments was never counted: never shown as current.
            "stock_counted": counted, "stock_age_hours": _n(age), "stale": age is None or age > STALE_AFTER_HOURS or not counted,
            "estimated": bool(i.get("sales_since_reading") and Decimal(i["sales_since_reading"]) > 0)
                         or bool(i.get("moves_since_reading") and Decimal(i["moves_since_reading"]) != 0),
            "sales_through": i.get("sales_through"), "history_days": i.get("history_days", 0),
        })
    rows.sort(key=lambda x: ({"out_of_stock": 0, "at_risk": 1, "ok": 3}.get(x["state"], 2), x["name"].lower()))
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["state"]] += 1
    return {"location_id": str(location_id), "stock_owner": location.inventory_write_owner, "today": today.isoformat(),
            "computed_at": ev.cutoff.isoformat(), "counts": dict(counts), "items": rows}


def item_history(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID, variant_id: uuid.UUID,
                 days: int = 60) -> dict[str, Any]:
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    tz = ZoneInfo(location.timezone)
    today = datetime.now(tz).date()
    start = today - timedelta(days=days)
    covered = sales.covered_dates(session, tenant_id=tenant_id, location_id=location_id, start=start, end=today) or set()
    local_day = func.date(func.timezone(location.timezone, SalesLine.sold_at))
    per_day = dict(session.execute(select(local_day, func.sum(SalesLine.quantity)).where(
        SalesLine.tenant_id == tenant_id, SalesLine.location_id == location_id, SalesLine.variant_id == variant_id,
        SalesLine.sold_at >= datetime.combine(start, datetime.min.time(), tz)).group_by(local_day)).all())
    series = []
    for k in range(days + 1):
        d = start + timedelta(days=k)
        qty = per_day.get(d)
        series.append({"date": d.isoformat(), "units": _n(qty) if qty is not None else ("0" if d in covered else None),
                       "covered": d in covered or qty is not None})
    moves = session.execute(select(InventoryMovement).where(
        InventoryMovement.tenant_id == tenant_id, InventoryMovement.location_id == location_id,
        InventoryMovement.variant_id == variant_id).order_by(InventoryMovement.occurred_at.desc()).limit(100)).scalars().all()
    from clawbot.persistence.models import User

    actors = {m.actor_user_id for m in moves if m.actor_user_id}
    emails = dict(session.execute(select(User.id, User.email).where(User.id.in_(actors))).all()) if actors else {}
    snaps = session.scalars(select(InventorySnapshot).where(
        InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.location_id == location_id,
        InventorySnapshot.variant_id == variant_id).order_by(InventorySnapshot.as_of.desc()).limit(30)).all()
    po_lines = session.execute(select(PurchaseOrder, PoLine).join(PoLine, (PoLine.tenant_id == PurchaseOrder.tenant_id) & (
        PoLine.po_id == PurchaseOrder.id)).where(
        PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.location_id == location_id, PoLine.variant_id == variant_id,
        PurchaseOrder.status.in_(PO_SENT_STATUSES)).order_by(PurchaseOrder.created_at.desc())).all()
    from clawbot.domain import po_progress

    ev_line = service.evaluate(session, tenant_id=tenant_id, location_id=location_id).lines.get(variant_id)
    return {
        "sales": series,
        "movements": [{"id": str(m.id), "at": m.occurred_at.isoformat(), "reason": m.reason, "delta": _n(m.delta),
                       "source": m.source, "note": m.notes, "by": emails.get(m.actor_user_id),
                       "undo_of": m.source_event_id if m.source == "undo" else None} for m in moves],
        "pos_readings": [{"at": s.as_of.isoformat(), "qty": _n(s.quantity), "source": s.source_system} for s in snaps],
        "orders": [{"po_id": str(po.id), "number": po.number, "status": po.status, "ordered": _n(l.ordered_qty),
                    "outstanding": _n(po_progress.state(l).outstanding), "unconfirmed": _n(po_progress.state(l).unconfirmed),
                    "unit": l.order_uom, "eta": l.eta.isoformat() if l.eta else None} for po, l in po_lines],
        "projection": (ev_line.result.get("projection") or [])[:21] if ev_line is not None else [],
        "suppliers": _supplier_prices(session, tenant_id, variant_id),
    }


def _supplier_prices(session: Session, tenant_id: uuid.UUID, variant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Who sells this item (confirmed mappings) and the price in force now, per order unit."""
    now = datetime.now(timezone.utc)
    out = []
    for item, name in session.execute(select(SupplierItem, Supplier.name).join(
            Supplier, (Supplier.tenant_id == SupplierItem.tenant_id) & (Supplier.id == SupplierItem.supplier_id)).where(
            SupplierItem.tenant_id == tenant_id, SupplierItem.variant_id == variant_id,
            SupplierItem.mapping_status == "confirmed", SupplierItem.status == "active")):
        price = session.scalars(select(SupplierItemPrice).where(
            SupplierItemPrice.tenant_id == tenant_id, SupplierItemPrice.supplier_item_id == item.id,
            SupplierItemPrice.superseded_at.is_(None), SupplierItemPrice.valid_from <= now,
            (SupplierItemPrice.expires_at.is_(None)) | (SupplierItemPrice.expires_at > now))
            .order_by(SupplierItemPrice.valid_from.desc())).first()
        out.append({"supplier": name, "supplier_sku": item.supplier_sku, "order_uom": item.order_uom,
                    "units_per_order_uom": _n(item.units_per_order_uom), "lead_time_days": item.lead_time_days,
                    "price": None if price is None else {"amount": _n(price.unit_price), "currency": price.currency,
                                                          "per": item.order_uom,
                                                          "units_per": _n(price.units_per_order_uom), "type": price.price_type,
                                                          "since": price.valid_from.isoformat()}})
    return out


def analytics(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID, days: int = 28) -> dict[str, Any]:
    """
    Units (and revenue where prices are known) for the last `days` days vs the `days` before.
    Days without sales data (no coverage) are reported as missing, never as zero sales — and sales recorded
    on such a day (e.g. from one source while another expected source is missing) are left out of the totals,
    so a partial day never counts as a complete one. Revenue is shown only when every sale counted has a price.
    """
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    tz = ZoneInfo(location.timezone)
    today = datetime.now(tz).date()
    cur_start, prev_start = today - timedelta(days=days), today - timedelta(days=2 * days)
    covered = sales.covered_dates(session, tenant_id=tenant_id, location_id=location_id, start=prev_start, end=today) or set()
    local_day = func.date(func.timezone(location.timezone, SalesLine.sold_at))
    grouped = session.execute(select(SalesLine.variant_id, local_day, func.sum(SalesLine.quantity),
                                     func.sum(SalesLine.quantity * SalesLine.unit_price),
                                     func.count() - func.count(SalesLine.unit_price)).where(
        SalesLine.tenant_id == tenant_id, SalesLine.location_id == location_id,
        SalesLine.sold_at >= datetime.combine(prev_start, datetime.min.time(), tz),
        SalesLine.sold_at < datetime.combine(today, datetime.min.time(), tz)).group_by(SalesLine.variant_id, local_day)).all()
    rows = [(vid, d, q, m) for vid, d, q, m, _ in grouped if d in covered]
    unpriced = {d: n for _, d, _, _, n in grouped if d in covered and n}
    names = {v.id: (v.sku, v.name) for v in session.scalars(select(Variant).where(Variant.tenant_id == tenant_id))}

    def period(lo: date, hi: date) -> dict[str, Any]:
        days_in = [lo + timedelta(days=k) for k in range((hi - lo).days)]
        have = [d for d in days_in if d in covered]
        units = sum((q for _, d, q, _ in rows if lo <= d < hi), ZERO)
        revenue_rows = [m for _, d, _, m in rows if lo <= d < hi and m is not None]
        missing_prices = sum(n for d, n in unpriced.items() if lo <= d < hi)
        return {"from": lo.isoformat(), "to": (hi - timedelta(days=1)).isoformat(), "days": len(days_in),
                "days_with_data": len(have), "units": _n(units) if have else None,
                "revenue": _n(sum(revenue_rows, ZERO)) if have and revenue_rows and not missing_prices else None,
                "sales_without_price": missing_prices}

    current, previous = period(cur_start, today), period(prev_start, cur_start)
    daily = []
    for k in range(days):
        d = cur_start + timedelta(days=k)
        u = sum((q for _, dd, q, _ in rows if dd == d), ZERO)
        daily.append({"date": d.isoformat(), "units": _n(u) if d in covered else None})
    by_item: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    by_item_prev: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for vid, d, q, _ in rows:
        (by_item if d >= cur_start else by_item_prev)[vid] += q
    view = overview(session, tenant_id=tenant_id, location_id=location_id)
    stock = {uuid.UUID(r["variant_id"]): r for r in view["items"]}
    top = sorted(by_item.items(), key=lambda kv: -kv[1])[:10]
    slow = sorted(((vid, by_item.get(vid, ZERO)) for vid, r in stock.items()
                   if r["on_hand"] and Decimal(r["on_hand"]) > 0), key=lambda kv: kv[1])[:10]
    item = lambda vid, units: {"variant_id": str(vid), "sku": names.get(vid, ("?", ""))[0],  # noqa: E731
                               "name": names.get(vid, ("", "?"))[1], "units": _n(units),
                               "previous_units": _n(by_item_prev.get(vid, ZERO)),
                               "on_hand": stock.get(vid, {}).get("on_hand")}
    return {
        "days": days, "current": current, "previous": previous, "daily": daily,
        "has_data": bool(current["days_with_data"]),
        "top_sellers": [item(v, u) for v, u in top if u > 0],
        "slow_movers": [item(v, u) for v, u in slow] if current["days_with_data"] else [],
        "stockouts_ahead": [r for r in view["items"] if r["stockout_date"]][:15],
        "sales_through": max((r["sales_through"] for r in view["items"] if r["sales_through"]), default=None),
    }


def readiness(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID) -> dict[str, Any]:
    """Which parts of the app the store's data can support now, and what is missing for the rest."""
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    products = session.scalar(select(func.count()).select_from(Variant).where(Variant.tenant_id == tenant_id)) or 0
    # Stock is known from a count or a stock report — scans and adjustments alone don't say how many are there.
    readings = (session.scalar(select(func.count()).select_from(InventoryMovement).where(
        InventoryMovement.tenant_id == tenant_id, InventoryMovement.location_id == location_id,
        InventoryMovement.reason == "count")) or 0) + (
        session.scalar(select(func.count()).select_from(InventorySnapshot).where(
            InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.location_id == location_id)) or 0)
    today = datetime.now(ZoneInfo(location.timezone)).date()
    days = len(sales.covered_dates(session, tenant_id=tenant_id, location_id=location_id,
                                   start=today - timedelta(days=90), end=today) or set())
    suppliers = session.scalar(select(func.count()).select_from(Supplier).where(
        Supplier.tenant_id == tenant_id, Supplier.relationship_status == "approved")) or 0
    priced = session.scalar(select(func.count(func.distinct(SupplierItem.variant_id))).select_from(SupplierItem).join(
        SupplierItemPrice, (SupplierItemPrice.tenant_id == SupplierItem.tenant_id) & (SupplierItemPrice.supplier_item_id == SupplierItem.id))
        .where(SupplierItem.tenant_id == tenant_id, SupplierItem.mapping_status == "confirmed")) or 0
    address = all([location.address_line1, location.city, location.postal_code, location.country])

    def feature(key: str, label: str, missing: list[tuple[str, str]], partial: str | None = None) -> dict[str, Any]:
        return {"key": key, "label": label, "ready": not missing,
                "missing": [{"what": w, "how": h} for w, h in missing], "partial": partial if missing else None}

    return {"facts": {"products": products, "stock_readings": readings, "sales_days": days, "approved_suppliers": suppliers,
                      "priced_items": priced, "ship_to_address": address},
            "features": [
                feature("inventory", "Stock levels", [*([("products", "Import a stock file or product list")] if not products else []),
                                                      *([("a stock count", "Upload a stock count, or connect your POS")] if not readings else [])]),
                feature("trends", "Sales trends", [("at least 7 days of sales", "Import a sales export")] if days < 7 else []),
                feature("suggestions", "Order suggestions",
                        [*([("at least 14 days of sales", "Import a longer sales export")] if days < 14 else []),
                         *([("a stock count", "Upload a stock count")] if not readings else [])],
                        partial="Stock levels work without sales history; suggestions need sales to estimate demand."),
                feature("orders", "Purchase orders",
                        [*([("an approved supplier", "Add a supplier with an order email and terms")] if not suppliers else []),
                         *([("supplier prices", "Import a supplier price list")] if not priced else []),
                         *([("ship-to address", "Add the store address in Settings")] if not address else [])]),
            ]}
