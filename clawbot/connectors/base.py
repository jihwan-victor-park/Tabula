"""
Connector contract (spec 15.2) and the normalized records every POS adapter
produces. Adapters only translate; all writes go through domain services with a
`system` actor, so the same tenant, idempotency and audit rules apply as for
people and imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Capabilities:
    """What the provider actually supports for this connection (no imaginary tools)."""

    sales_read: bool = False
    inventory_read: bool = False
    inventory_write: bool = False
    catalog_read: bool = False
    supplier_read: bool = False
    po_read: bool = False
    po_write: bool = False


@dataclass(frozen=True)
class ExternalLocation:
    external_id: str
    name: str
    timezone: str | None
    currency: str | None
    active: bool


@dataclass(frozen=True)
class ExternalVariant:
    external_id: str  # provider's variation ID
    sku: str | None
    barcode: str | None
    name: str
    parent_name: str | None = None


@dataclass(frozen=True)
class ExternalSaleLine:
    order_id: str
    line_key: str  # provider line UID (or return UID + line UID for refunds)
    external_variant_id: str | None
    external_location_id: str
    sold_at: datetime
    quantity: Decimal  # positive sale, negative refund
    line_type: str  # sale | refund
    unit_price: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class ExternalCount:
    external_variant_id: str
    external_location_id: str
    quantity: Decimal
    calculated_at: datetime


@dataclass
class Page:
    items: list = field(default_factory=list)
    cursor: str | None = None
