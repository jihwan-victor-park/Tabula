"""
Canonical JSON for engine inputs and policy: stored with each line so a plan
can be replayed exactly, and hashed into the run's input digest.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

from clawbot.domain.replenishment.engine import ENGINE_VERSION, InboundLine, ItemInputs, OfferInputs, Policy


def _encode(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {f.name: _encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Decimal):
        return f"{value.normalize():f}" if value != 0 else "0"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    return value


def dumps(value: Any) -> dict[str, Any]:
    return _encode(value)


def digest(*parts: Any) -> str:
    payload = json.dumps([ENGINE_VERSION, *[_encode(p) for p in parts]], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _dec(v: str | None) -> Decimal | None:
    return None if v is None else Decimal(v)


def load_policy(data: dict[str, Any]) -> Policy:
    kwargs = dict(data)
    for name in ("safety_days", "weekly_budget"):
        if kwargs.get(name) is not None:
            kwargs[name] = Decimal(kwargs[name])
    return Policy(**kwargs)


def _load_offer(offer: dict[str, Any]) -> OfferInputs:
    return OfferInputs(
        supplier_item_id=offer["supplier_item_id"], supplier_id=offer["supplier_id"],
        supplier_name=offer["supplier_name"], order_uom=offer["order_uom"],
        units_per_order_uom=Decimal(offer["units_per_order_uom"]), order_multiple=Decimal(offer["order_multiple"]),
        min_order_qty=Decimal(offer["min_order_qty"]), unit_price=Decimal(offer["unit_price"]),
        currency=offer["currency"], price_as_of=offer["price_as_of"], arrival_day=offer["arrival_day"],
        calendar_notes=tuple(offer["calendar_notes"]), price_id=offer.get("price_id"),
        price_type=offer.get("price_type"), price_source=offer.get("price_source"),
        order_date=offer.get("order_date"), delivery_date=offer.get("delivery_date"),
        usable_date=offer.get("usable_date"),
    )


def load_item(data: dict[str, Any]) -> ItemInputs:
    return ItemInputs(
        variant_id=data["variant_id"],
        sku=data["sku"],
        planning_date=date.fromisoformat(data["planning_date"]),
        variant_active=data["variant_active"],
        on_hand=_dec(data["on_hand"]),
        stock_source=data["stock_source"],
        stock_as_of=data["stock_as_of"],
        stock_age_hours=_dec(data["stock_age_hours"]),
        stock_counted=data["stock_counted"],
        sales_since_reading=Decimal(data["sales_since_reading"]),
        moves_since_reading=Decimal(data["moves_since_reading"]),
        daily_sales=tuple((date.fromisoformat(d), Decimal(q)) for d, q in data["daily_sales"]),
        stockout_dates=tuple(date.fromisoformat(d) for d in data["stockout_dates"]),
        history_days=data["history_days"],
        coverage_inferred=data["coverage_inferred"],
        sales_through=data["sales_through"],
        sales_age_hours=_dec(data["sales_age_hours"]),
        inbound=tuple(
            InboundLine(i["reference"], Decimal(i["quantity"]), i["confirmed"], i["arrival_day"], i.get("age_days"))
            for i in data["inbound"]
        ),
        offers=tuple(_load_offer(o) for o in data["offers"]),
        offer_blockers=tuple(data["offer_blockers"]),
        safety_stock=_dec(data["safety_stock"]),
        min_qty=_dec(data["min_qty"]),
        max_qty=_dec(data["max_qty"]),
        excluded=data["excluded"],
        notes=tuple(data.get("notes", ())),
    )
