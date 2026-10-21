"""Square payloads → normalized connector records (pure, no I/O)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

from clawbot.connectors.base import ExternalCount, ExternalLocation, ExternalSaleLine, ExternalVariant
from clawbot.domain.units import CURRENCY_MINOR_UNITS


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _money(money: dict[str, Any] | None) -> tuple[Decimal | None, str | None]:
    """Square money is an integer amount in the currency's minor unit."""
    if not money or money.get("amount") is None:
        return None, None
    currency = money.get("currency")
    places = CURRENCY_MINOR_UNITS.get(currency, 2)
    return Decimal(money["amount"]).scaleb(-places), currency


def location(raw: dict[str, Any]) -> ExternalLocation:
    return ExternalLocation(raw["id"], raw.get("name", raw["id"]), raw.get("timezone"), raw.get("currency"),
                            raw.get("status", "ACTIVE") == "ACTIVE")


def variants(item: dict[str, Any]) -> Iterator[ExternalVariant]:
    data = item.get("item_data", {})
    for variation in data.get("variations", []):
        v = variation.get("item_variation_data", {})
        name = data.get("name", "")
        if v.get("name") and v["name"] != "Regular":
            name = f"{name} {v['name']}".strip()
        yield ExternalVariant(variation["id"], v.get("sku") or None, v.get("upc") or None, name, data.get("name"))


def sale_lines(order: dict[str, Any]) -> Iterator[ExternalSaleLine]:
    """
    Completed order → sale lines (one per line item) and refund lines (one per
    returned line item). Keys are Square's own UIDs so re-reading an order is idempotent.
    """
    if order.get("state") != "COMPLETED" or not order.get("closed_at"):
        return
    at, loc = _ts(order["closed_at"]), order["location_id"]
    for line in order.get("line_items", []):
        qty = Decimal(line.get("quantity", "0"))
        if qty <= 0:
            continue
        price, currency = _money(line.get("base_price_money"))
        yield ExternalSaleLine(order["id"], line["uid"], line.get("catalog_object_id"), loc, at, qty, "sale", price, currency)
    for ret in order.get("returns", []):
        for line in ret.get("return_line_items", []):
            qty = Decimal(line.get("quantity", "0"))
            if qty <= 0:
                continue
            price, currency = _money(line.get("base_price_money"))
            yield ExternalSaleLine(order["id"], f"{ret.get('uid', 'return')}:{line['uid']}", line.get("catalog_object_id"),
                                   loc, at, -qty, "refund", price, currency)


def count(raw: dict[str, Any]) -> ExternalCount | None:
    if raw.get("state") != "IN_STOCK" or raw.get("catalog_object_type", "ITEM_VARIATION") != "ITEM_VARIATION":
        return None
    return ExternalCount(raw["catalog_object_id"], raw["location_id"], Decimal(raw["quantity"]), _ts(raw["calculated_at"]))
