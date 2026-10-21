"""
SQLAlchemy models for the operational database (CP1 foundation).

Conventions
- Every tenant-owned row carries tenant_id and a UUID primary key.
- Tenant-owned parents expose UNIQUE (tenant_id, id) so children reference them
  with a composite foreign key: a row in tenant A can never point at a row in
  tenant B, even if application code passes the wrong ID.
- Quantities are Numeric (Decimal), never float.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

QTY = Numeric(18, 4)
# Supplier unit costs can carry sub-cent precision (e.g. $0.4167/each); currency
# rounding happens when an amount is presented or billed, not when stored.
MONEY = Numeric(18, 4)

ROLES = ("owner", "manager", "receiver", "bookkeeper")
VARIANT_STATUSES = ("active", "discontinued")
MAPPING_STATUSES = ("suggested", "confirmed", "rejected")
SUPPLIER_TYPES = ("distributor", "brand_direct", "wholesaler", "marketplace", "other")
SUPPLIER_STATUSES = ("candidate", "approved", "suspended", "archived")
ORDERING_CHANNELS = ("email", "portal", "api", "edi", "phone")
PAYMENT_TERMS = ("unknown", "prepaid", "cod", "net", "card_on_file")
SUPPLIER_ITEM_MAPPING_STATUSES = ("unmapped", "suggested", "confirmed", "rejected")
SUPPLIER_ITEM_STATUSES = ("active", "discontinued", "unavailable")
PRICE_TYPES = ("contract", "price_list", "invoice", "quote", "public_listing")
IMPORT_KINDS = ("supplier_price_list", "inventory", "sales", "open_orders")
# uploaded → (mapping edited) → confirmed → applying → applied | failed; rejected = discarded by a person
IMPORT_STATUSES = ("uploaded", "confirmed", "applying", "applied", "failed", "rejected")
IMPORT_ROW_STATUSES = ("pending", "applied", "unchanged", "error", "skipped")
ImportStatusPending = ("confirmed", "applying")
SALES_LINE_TYPES = ("sale", "refund")
# Origin systems a sales line can come from. Fixed so that "square" and
# "square-export" can never be two names for one origin (spec 6.3).
SALES_SOURCES = ("square", "shopify", "clover", "lightspeed", "toast", "woocommerce", "amazon", "faire",
                 "other_pos", "manual")
# How a line's external_line_key was built. One origin order must only ever be
# recorded under one scheme, or the same sale could be counted twice.
SALES_KEY_SCHEMES = ("csv_line_id", "csv_item_ordinal", "provider_line")
MOVEMENT_REASONS = (
    "receipt",
    "adjustment",
    "count",
    "damage",
    "return",
    "transfer_in",
    "transfer_out",
)
# unknown: a lease expired mid-send, so the external outcome is unknown and a
# person must check before anything is re-sent (spec 16.2).
OUTBOX_STATUSES = ("pending", "in_flight", "done", "dead", "unknown")
CONNECTOR_EVENT_STATUSES = ("received", "processed", "failed", "ignored")
ACTOR_KINDS = ("human", "agent", "system")
# Which system is the source of truth for stock counts at a location (spec 3.3, 6.3).
INVENTORY_WRITE_OWNERS = ("tabula", "square", "shopify", "clover", "lightspeed", "other")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# Identity and tenancy
# ---------------------------------------------------------------------------


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = _created_at()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(_in("role", ROLES), name="role_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(_in("inventory_write_owner", INVENTORY_WRITE_OWNERS), name="write_owner_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # Ship-to address for purchase orders.
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(2))
    # When a POS owns stock counts, Tabula never writes its own movements here;
    # it reads the POS and posts receipts through the connector instead.
    inventory_write_owner: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tabula", server_default="tabula"
    )
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class Product(Base):
    """A merchandising grouping (brand + name). Identity for ordering lives on Variant."""

    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class Variant(Base):
    """
    One sellable item. Different size, flavour, colour, pack count or regional
    spec is a different variant, even under the same brand and product.
    """

    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "sku"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["products.tenant_id", "products.id"]),
        Index("uq_variants_tenant_gtin", "tenant_id", "gtin", unique=True, postgresql_where=text("gtin IS NOT NULL")),
        # Trigram index for fuzzy candidate search (pg_trgm, created in migration 0004).
        Index("ix_variants_name_trgm", func.lower(text("name")), postgresql_using="gin", postgresql_ops={"lower_1": "gin_trgm_ops"}),
        CheckConstraint(_in("status", VARIANT_STATUSES), name="status_valid"),
        CheckConstraint("size_value IS NULL OR size_value > 0", name="size_positive"),
        CheckConstraint("(size_value IS NULL) = (size_unit IS NULL)", name="size_pair"),
        CheckConstraint("pack_count >= 1", name="pack_count_positive"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(64))  # as entered
    gtin: Mapped[str | None] = mapped_column(String(14))  # check-digit-valid, zero-padded GTIN-14
    base_uom: Mapped[str] = mapped_column(String(20), nullable=False, default="each")
    size_value: Mapped[Decimal | None] = mapped_column(QTY)
    size_unit: Mapped[str | None] = mapped_column(String(16))
    pack_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # units inside one sellable each
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalItemMapping(Base):
    """Provider/import object ↔ variant. Only `confirmed` rows are used to resolve identity."""

    __tablename__ = "external_item_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_system", "source_account", "external_id"),
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        CheckConstraint(_in("status", MAPPING_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    source_system: Mapped[str] = mapped_column(String(40), nullable=False)  # square, shopify, csv, ...
    source_account: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="suggested")
    match_method: Mapped[str] = mapped_column(String(30), nullable=False)
    external_sku: Mapped[str | None] = mapped_column(String(120))
    external_barcode: Mapped[str | None] = mapped_column(String(64))
    external_name: Mapped[str | None] = mapped_column(String(300))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Suppliers (per-merchant relationships; never shared across tenants)
# ---------------------------------------------------------------------------


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint(_in("supplier_type", SUPPLIER_TYPES), name="type_valid"),
        CheckConstraint(_in("relationship_status", SUPPLIER_STATUSES), name="status_valid"),
        CheckConstraint(
            f"ordering_channel IS NULL OR {_in('ordering_channel', ORDERING_CHANNELS)}", name="channel_valid"
        ),
        CheckConstraint(_in("payment_terms", PAYMENT_TERMS), name="terms_valid"),
        CheckConstraint(
            "(payment_terms = 'net') = (payment_net_days IS NOT NULL)", name="net_days_iff_net"
        ),
        CheckConstraint("payment_net_days IS NULL OR payment_net_days > 0", name="net_days_positive"),
        CheckConstraint("min_order_amount IS NULL OR min_order_amount >= 0", name="min_order_nonneg"),
        CheckConstraint(
            "free_shipping_threshold IS NULL OR free_shipping_threshold >= 0", name="free_ship_nonneg"
        ),
        CheckConstraint("default_lead_time_days IS NULL OR default_lead_time_days >= 0", name="lead_nonneg"),
        CheckConstraint("delivery_weekdays <@ ARRAY[1,2,3,4,5,6,7]::smallint[]", name="weekdays_iso"),
        CheckConstraint(
            "(relationship_status <> 'approved') OR (verified_at IS NOT NULL)", name="approved_is_verified"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    supplier_type: Mapped[str] = mapped_column(String(20), nullable=False, default="distributor")
    relationship_status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    ordering_channel: Mapped[str | None] = mapped_column(String(20))
    portal_url: Mapped[str | None] = mapped_column(String(500))
    merchant_account_number: Mapped[str | None] = mapped_column(String(120))
    # False only when the merchant states the supplier issues no account numbers.
    merchant_account_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_terms: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    payment_net_days: Mapped[int | None] = mapped_column(Integer)
    credit_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_order_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    free_shipping_threshold: Mapped[Decimal | None] = mapped_column(MONEY)
    freight_notes: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    order_cutoff_local: Mapped[time | None] = mapped_column(Time)
    delivery_weekdays: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, default=list, server_default=text("'{}'::smallint[]")
    )
    default_lead_time_days: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SupplierContact(Base):
    __tablename__ = "supplier_contacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "supplier_id", "email"),
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="reachable"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str | None] = mapped_column(String(80))
    is_order_recipient: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Set when the merchant confirms this is the supplier's real ordering address.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


class SupplierLocationCoverage(Base):
    """Which of the merchant's locations this supplier delivers to."""

    __tablename__ = "supplier_location_coverage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)


class SupplierClosure(Base):
    __tablename__ = "supplier_closures"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"], ondelete="CASCADE"
        ),
        CheckConstraint("ends_on >= starts_on", name="range_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class SupplierItem(Base):
    """
    What a supplier sells, in the supplier's own SKU and order unit.
    `units_per_order_uom` converts one order unit (e.g. case) into the variant's base unit.
    """

    __tablename__ = "supplier_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "supplier_id", "supplier_sku"),
        ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"]),
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        CheckConstraint(_in("mapping_status", SUPPLIER_ITEM_MAPPING_STATUSES), name="mapping_status_valid"),
        CheckConstraint(
            "variant_id IS NOT NULL OR mapping_status IN ('unmapped', 'rejected')", name="mapped_has_variant"
        ),
        CheckConstraint(_in("status", SUPPLIER_ITEM_STATUSES), name="status_valid"),
        CheckConstraint("units_per_order_uom > 0", name="units_per_positive"),
        CheckConstraint("order_multiple > 0", name="multiple_positive"),
        CheckConstraint("min_order_qty > 0", name="moq_positive"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_nonneg"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_sku: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mapping_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unmapped")
    mapping_decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    mapping_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_uom: Mapped[str] = mapped_column(String(20), nullable=False)
    units_per_order_uom: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    order_multiple: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=Decimal(1))
    min_order_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=Decimal(1))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # Where the pack and terms came from (e.g. "import:<id>", "invoice INV-1042").
    source_ref: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SupplierItemPrice(Base):
    """
    Append-only price history per supplier item. `unit_price` is per order unit.

    superseded_at — set by Tabula when a newer price replaces this one (history)
    expires_at    — validity end stated by the supplier ("valid until 12/31")

    At most one current (non-superseded) orderable price per item; public
    listings are tracked apart and are never orderable.
    """

    __tablename__ = "supplier_item_prices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "supplier_item_id"], ["supplier_items.tenant_id", "supplier_items.id"]
        ),
        CheckConstraint(_in("price_type", PRICE_TYPES), name="type_valid"),
        CheckConstraint("unit_price >= 0", name="price_nonneg"),
        CheckConstraint("expires_at IS NULL OR expires_at > valid_from", name="expiry_after_start"),
        CheckConstraint("superseded_at IS NULL OR superseded_at >= valid_from", name="superseded_after_start"),
        CheckConstraint("units_per_order_uom > 0", name="units_per_positive"),
        Index(
            "uq_supplier_item_prices_one_current",
            "tenant_id",
            "supplier_item_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL AND price_type <> 'public_listing'"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    supplier_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Pack size the price was quoted for; a later pack change invalidates the price.
    units_per_order_uom: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    price_type: Mapped[str] = mapped_column(String(20), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Inventory ledger
# ---------------------------------------------------------------------------


class InventoryPosition(Base):
    """Read model: current Tabula-tracked quantity per variant and location."""

    __tablename__ = "inventory_positions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    on_hand: Mapped[Decimal] = mapped_column(QTY, nullable=False, default=Decimal(0))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InventoryMovement(Base):
    """Append-only ledger. One row per real-world stock change, deduplicated by source event."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "source_event_id"),
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
        CheckConstraint(_in("reason", MOVEMENT_REASONS), name="reason_valid"),
        CheckConstraint("delta <> 0", name="delta_nonzero"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delta: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # For counts: the absolute level the count established. Stock is anchored on this,
    # so changes that happened before the count (even if entered later) are never applied twice.
    counted_qty: Mapped[Decimal | None] = mapped_column(QTY)
    recorded_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Integration plumbing
# ---------------------------------------------------------------------------


class ConnectorEvent(Base):
    """Raw inbound provider event, stored before ack so it can be replayed."""

    __tablename__ = "connector_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "external_event_id"),
        CheckConstraint(_in("status", CONNECTOR_EVENT_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(120))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    received_at: Mapped[datetime] = _created_at()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxMessage(Base):
    """External side effects queued in the same transaction as the decision that caused them."""

    __tablename__ = "outbox"
    __table_args__ = (
        UniqueConstraint("tenant_id", "operation_key"),
        CheckConstraint(_in("status", OUTBOX_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Fencing token: only the worker holding the current lease may complete or fail it.
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # True only for handlers whose external call is idempotent on operation_key, so a
    # crashed attempt may be retried blindly. Otherwise an expired lease → `unknown`.
    retry_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (CheckConstraint(_in("actor_kind", ACTOR_KINDS), name="actor_kind_valid"),)

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    actor_name: Mapped[str | None] = mapped_column(String(80))  # agent/system name
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    object_type: Mapped[str] = mapped_column(String(60), nullable=False)
    object_id: Mapped[str] = mapped_column(String(255), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Imports (CP3)
# ---------------------------------------------------------------------------


class Import(Base):
    """
    One uploaded file. Nothing is applied until a person confirms the column
    mapping at a given revision; applying is an idempotent job.
    """

    __tablename__ = "imports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # The same file for the same context is one import while it is live; a
        # rejected or failed import does not block uploading the file again.
        Index(
            "uq_imports_live_file", "tenant_id", "kind", "file_sha256", "context_key", unique=True,
            postgresql_where=text("status NOT IN ('rejected', 'failed')"),
        ),
        CheckConstraint(_in("kind", IMPORT_KINDS), name="kind_valid"),
        CheckConstraint(_in("status", IMPORT_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)  # csv | xlsx
    header: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Kind-specific context chosen at upload: supplier_id, location_id, source_system …
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    context_key: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256 of the canonical context
    # {"columns": {field: header}, "settings": {...}}; drafts are machine-made, confirmation is a person's
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    mapping_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    accept_row_errors: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    failure: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_role: Mapped[str | None] = mapped_column(String(20))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        UniqueConstraint("import_id", "row_number"),
        ForeignKeyConstraint(["tenant_id", "import_id"], ["imports.tenant_id", "imports.id"], ondelete="CASCADE"),
        CheckConstraint(_in("status", IMPORT_ROW_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    import_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based, as shown in a spreadsheet
    cells: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # Digest of the row's interpretation when a person confirmed it; apply refuses rows that no longer match.
    confirmed_digest: Mapped[str | None] = mapped_column(String(64))
    result_ref: Mapped[str | None] = mapped_column(String(255))


class InventorySnapshot(Base):
    """A stock count reported by a source (POS, import, count) at a point in time."""

    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_system", "source_ref", "location_id", "variant_id"),
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class SalesLine(Base):
    """
    One sold (or refunded) item line from its origin system. Uniqueness on the
    origin identifiers means the same sale imported twice counts once.
    """

    __tablename__ = "sales_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_system", "external_order_id", "external_line_key"),
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
        CheckConstraint(_in("line_type", SALES_LINE_TYPES), name="line_type_valid"),
        CheckConstraint(_in("source_system", SALES_SOURCES), name="source_valid"),
        CheckConstraint(_in("key_scheme", SALES_KEY_SCHEMES), name="key_scheme_valid"),
        Index("ix_sales_lines_order", "tenant_id", "source_system", "external_order_id"),
        CheckConstraint(
            "(line_type = 'sale' AND quantity > 0) OR (line_type = 'refund' AND quantity < 0)", name="sign_matches_type"
        ),
        Index("ix_sales_lines_variant_sold_at", "tenant_id", "variant_id", "sold_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False)  # origin channel: square, csv:shopify-export …
    external_order_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_line_key: Mapped[str] = mapped_column(String(255), nullable=False)
    key_scheme: Mapped[str] = mapped_column(String(20), nullable=False)
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    line_type: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)  # base units; refunds negative
    unit_price: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    import_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class SalesCoverage(Base):
    """
    Local dates a sales source is known to have reported completely for a location
    (one row per import file or connector sync window). A day inside coverage with
    no sales is a zero-sales day; a day outside it is missing data (spec 3.4, 5.1).
    """

    __tablename__ = "sales_coverage"
    __table_args__ = (
        UniqueConstraint("tenant_id", "location_id", "source_system", "source_ref"),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
        CheckConstraint("ends_on >= starts_on", name="range_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_system: Mapped[str] = mapped_column(String(40), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ExternalOpenOrderLine(Base):
    """
    An order already placed outside Tabula and not yet fully received. Used to
    avoid ordering the same thing twice; only `supplier_confirmed` lines count as
    confirmed inbound (spec 6.4).
    """

    __tablename__ = "external_open_order_lines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", "location_id", "external_po_number", "variant_id"),
        ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"]),
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
        CheckConstraint("outstanding_qty >= 0", name="outstanding_nonneg"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    external_po_number: Mapped[str] = mapped_column(String(120), nullable=False)
    outstanding_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)  # base units
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supplier_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # When the report this line came from was true; an older report never overwrites a newer one.
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a later complete report no longer listed the line (received or cancelled).
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    import_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# Replenishment (CP5)
# ---------------------------------------------------------------------------

REPLENISHMENT_RUN_STATUSES = ("current", "superseded", "historical")
# on_hold: stock is needed, but already-ordered quantity that is not reliably arriving
# (unconfirmed / overdue / no ETA) covers it — reordering waits for that order to be checked.
REPLENISHMENT_LINE_STATUSES = ("order", "on_hold", "no_order", "no_supplier", "insufficient_data", "excluded")


class ReplenishmentPolicy(Base):
    """Versioned merchant policy; a run records the version it used."""

    __tablename__ = "replenishment_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "version"),)

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


class ReplenishmentItemSetting(Base):
    """Per item and location: merchant safety stock, min/max, or exclusion."""

    __tablename__ = "replenishment_item_settings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"], ondelete="CASCADE"),
        CheckConstraint("safety_stock IS NULL OR safety_stock >= 0", name="safety_nonneg"),
        CheckConstraint("min_qty IS NULL OR min_qty >= 0", name="min_nonneg"),
        CheckConstraint("max_qty IS NULL OR max_qty > 0", name="max_positive"),
        CheckConstraint("min_qty IS NULL OR max_qty IS NULL OR min_qty < max_qty", name="min_below_max"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    safety_stock: Mapped[Decimal | None] = mapped_column(QTY)
    min_qty: Mapped[Decimal | None] = mapped_column(QTY)
    max_qty: Mapped[Decimal | None] = mapped_column(QTY)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ReplenishmentRun(Base):
    """
    One deterministic plan for one location. `input_digest` covers every input
    and the policy, so the same data and policy are recognised as the same plan.
    Only the newest run per location is `current`.
    """

    __tablename__ = "replenishment_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "location_id", "input_digest"),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
        CheckConstraint(_in("status", REPLENISHMENT_RUN_STATUSES), name="status_valid"),
        CheckConstraint(_in("actor_kind", ACTOR_KINDS), name="actor_kind_valid"),
        Index("uq_replenishment_runs_one_current", "tenant_id", "location_id", unique=True,
              postgresql_where=text("status = 'current'")),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planning_date: Mapped[date] = mapped_column(Date, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="current")
    actor_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    actor_name: Mapped[str | None] = mapped_column(String(80))
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # tenant data version the plan read
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    plan_notes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = _created_at()


class ReplenishmentLine(Base):
    __tablename__ = "replenishment_lines"
    __table_args__ = (
        UniqueConstraint("run_id", "variant_id"),
        ForeignKeyConstraint(["tenant_id", "run_id"], ["replenishment_runs.tenant_id", "replenishment_runs.id"],
                             ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "variant_id"], ["variants.tenant_id", "variants.id"]),
        CheckConstraint(_in("status", REPLENISHMENT_LINE_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    order_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    order_uom: Mapped[str | None] = mapped_column(String(20))
    base_qty: Mapped[Decimal] = mapped_column(QTY, nullable=False)
    line_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str | None] = mapped_column(String(3))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    supplier_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # replayable snapshot
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # steps, reasons, projection


# ---------------------------------------------------------------------------
# Connectors (CP4)
# ---------------------------------------------------------------------------

CONNECTOR_PROVIDERS = ("square",)
CONNECTOR_ENVIRONMENTS = ("mock", "sandbox", "production")
CONNECTOR_STATUSES = ("active", "needs_reauth", "revoked", "error")


class ConnectorAccount(Base):
    """
    One provider account connected to one tenant. Tokens are encrypted at rest
    (clawbot/security/secrets.py); a provider merchant connects to one tenant only,
    so webhooks route unambiguously.
    """

    __tablename__ = "connector_accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        # One live connection per provider account; a revoked one does not block reconnecting elsewhere.
        Index("uq_connector_accounts_live_merchant", "provider", "environment", "external_merchant_id", unique=True,
              postgresql_where=text("status <> 'revoked'")),
        CheckConstraint(_in("provider", CONNECTOR_PROVIDERS), name="provider_valid"),
        CheckConstraint(_in("environment", CONNECTOR_ENVIRONMENTS), name="environment_valid"),
        CheckConstraint(_in("status", CONNECTOR_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    external_merchant_id: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConnectorLocationLink(Base):
    """A provider location chosen by the merchant for a Tabula location (never auto-summed, spec 3.2)."""

    __tablename__ = "connector_location_links"
    __table_args__ = (
        UniqueConstraint("tenant_id", "location_id"),
        ForeignKeyConstraint(["tenant_id", "connector_account_id"], ["connector_accounts.tenant_id", "connector_accounts.id"],
                             ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
    )

    connector_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    external_location_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class OAuthState(Base):
    """Single-use, short-lived state binding an OAuth redirect to the tenant and person who started it."""

    __tablename__ = "oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    environment: Mapped[str] = mapped_column(String(20), nullable=False)
    # Hash of a random value set as an HttpOnly cookie in the browser that started the flow:
    # the callback must come from that same browser (a forwarded link cannot connect another account).
    browser_binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()



class TenantDataVersion(Base):
    """See clawbot/domain/data_version.py."""

    __tablename__ = "tenant_data_versions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TenantCounter(Base):
    """Human-readable sequences per tenant (e.g. PO numbers)."""

    __tablename__ = "tenant_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------------------
# Purchase orders (CP6)
# ---------------------------------------------------------------------------

# draft → awaiting_approval → (owner approves: approval + send job in one transaction) → queued
# → test_sent (captured, never delivered to a supplier) | failed. Editing goes back to draft.
PO_STATUSES = ("draft", "awaiting_approval", "queued", "test_sent", "failed", "cancelled")
PO_OPEN_STATUSES = ("draft", "awaiting_approval", "queued")
# Not sent and not cancelled: can still be refreshed, edited, re-approved or cancelled.
PO_ACTIVE_STATUSES = (*PO_OPEN_STATUSES, "failed")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "number"),
        ForeignKeyConstraint(["tenant_id", "location_id"], ["locations.tenant_id", "locations.id"]),
        ForeignKeyConstraint(["tenant_id", "supplier_id"], ["suppliers.tenant_id", "suppliers.id"]),
        CheckConstraint(_in("status", PO_STATUSES), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    data_version: Mapped[int] = mapped_column(Integer, nullable=False)  # inputs the quantities were checked against
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PoRevision(Base):
    """Immutable content of one PO version: supplier, recipient, ship-to, lines, totals. Approval binds to its digest."""

    __tablename__ = "po_revisions"
    __table_args__ = (
        UniqueConstraint("po_id", "revision"),
        ForeignKeyConstraint(["tenant_id", "po_id"], ["purchase_orders.tenant_id", "purchase_orders.id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    created_by_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()


class PoApproval(Base):
    __tablename__ = "po_approvals"
    __table_args__ = (
        UniqueConstraint("po_id", "revision"),
        ForeignKeyConstraint(["tenant_id", "po_id"], ["purchase_orders.tenant_id", "purchase_orders.id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_role: Mapped[str] = mapped_column(String(20), nullable=False)
    data_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_at: Mapped[datetime] = _created_at()


class PoSendAttempt(Base):
    """Execution log of every send attempt (spec 16.7)."""

    __tablename__ = "po_send_attempts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "po_id"], ["purchase_orders.tenant_id", "purchase_orders.id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    po_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(320))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # captured | refused | blocked | failed | skipped | unknown
    detail: Mapped[str | None] = mapped_column(Text)
    outbox_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class CapturedMessage(Base):
    """A message the capture transport kept instead of delivering (nothing leaves the machine)."""

    __tablename__ = "captured_messages"

    id: Mapped[uuid.UUID] = _pk()
    tenant_id: Mapped[uuid.UUID] = _tenant_fk()
    po_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    revision: Mapped[int | None] = mapped_column(Integer)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_name: Mapped[str | None] = mapped_column(String(200))
    attachment_csv: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
