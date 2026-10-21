"""v1 API schemas for suppliers, supplier items, prices and offers."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SupplierType = Literal["distributor", "brand_direct", "wholesaler", "marketplace", "other"]
SupplierStatus = Literal["candidate", "approved", "suspended", "archived"]
OrderingChannel = Literal["email", "portal", "api", "edi", "phone"]
PaymentTerms = Literal["unknown", "prepaid", "cod", "net", "card_on_file"]
PriceType = Literal["contract", "price_list", "invoice", "quote", "public_listing"]
Weekday = Literal[1, 2, 3, 4, 5, 6, 7]


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _SupplierFields(BaseModel):
    supplier_type: SupplierType | None = None
    ordering_channel: OrderingChannel | None = None
    portal_url: str | None = Field(default=None, max_length=500)
    merchant_account_number: str | None = Field(default=None, max_length=120)
    merchant_account_required: bool | None = Field(
        default=None, description="Set false only if this supplier issues no account numbers"
    )
    payment_terms: PaymentTerms | None = None
    payment_net_days: int | None = Field(default=None, gt=0, le=365)
    credit_hold: bool | None = None
    min_order_amount: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=4, description="0 = no minimum (an explicit answer)"
    )
    free_shipping_threshold: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    freight_notes: str | None = Field(default=None, max_length=2000)
    order_cutoff_local: time | None = Field(default=None, description="Local time in the supplier's timezone")
    delivery_weekdays: list[Weekday] | None = Field(default=None, description="ISO weekdays, 1 = Monday")
    default_lead_time_days: int | None = Field(default=None, ge=0, le=365)
    notes: str | None = Field(default=None, max_length=4000)


class SupplierCreate(_SupplierFields):
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3, examples=["USD"])
    timezone: str = Field(examples=["America/New_York"])


class SupplierUpdate(_SupplierFields):
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = None
    reason: str | None = Field(default=None, max_length=500)


class SupplierStatusChange(BaseModel):
    version: int
    status: SupplierStatus
    reason: str | None = Field(default=None, max_length=500)


class SupplierOut(_Orm):
    id: uuid.UUID
    name: str
    supplier_type: str
    relationship_status: str
    ordering_channel: str | None
    portal_url: str | None
    merchant_account_number: str | None
    merchant_account_required: bool
    currency: str
    payment_terms: str
    payment_net_days: int | None
    credit_hold: bool
    min_order_amount: Decimal | None
    free_shipping_threshold: Decimal | None
    freight_notes: str | None
    timezone: str
    order_cutoff_local: time | None
    delivery_weekdays: list[int]
    default_lead_time_days: int | None
    notes: str | None
    verified_at: datetime | None
    verified_by_user_id: uuid.UUID | None
    version: int
    created_at: datetime
    updated_at: datetime


class ApprovalCheckOut(BaseModel):
    approvable: bool
    blockers: list[str]


class ContactCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=80)
    is_order_recipient: bool = False


class ContactOut(_Orm):
    id: uuid.UUID
    name: str | None
    email: str | None
    phone: str | None
    role: str | None
    is_order_recipient: bool
    verified_at: datetime | None
    verified_by_user_id: uuid.UUID | None
    created_at: datetime


class CoverageSet(BaseModel):
    location_ids: list[uuid.UUID]


class CoverageOut(BaseModel):
    location_ids: list[uuid.UUID]


class ClosureCreate(BaseModel):
    starts_on: date
    ends_on: date
    reason: str | None = Field(default=None, max_length=200)


class ClosureOut(_Orm):
    id: uuid.UUID
    starts_on: date
    ends_on: date
    reason: str | None


class SupplierItemCreate(BaseModel):
    supplier_sku: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    order_uom: str = Field(min_length=1, max_length=20, examples=["case"])
    units_per_order_uom: Decimal = Field(gt=0, max_digits=18, decimal_places=4, examples=["12"])
    order_multiple: Decimal = Field(default=Decimal(1), gt=0, max_digits=18, decimal_places=4)
    min_order_qty: Decimal = Field(default=Decimal(1), gt=0, max_digits=18, decimal_places=4)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    suggested_variant_id: uuid.UUID | None = Field(
        default=None, description="Suggestion only; a person must confirm the mapping"
    )


class SupplierItemUpdate(BaseModel):
    version: int
    description: str | None = Field(default=None, max_length=300)
    order_uom: str | None = Field(default=None, min_length=1, max_length=20)
    units_per_order_uom: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    order_multiple: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    min_order_qty: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    status: Literal["active", "discontinued", "unavailable"] | None = None
    reason: str | None = Field(default=None, max_length=500)


class ItemMappingDecision(BaseModel):
    version: int
    decision: Literal["confirmed", "rejected"]
    variant_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class SupplierItemOut(_Orm):
    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_sku: str
    description: str | None
    variant_id: uuid.UUID | None
    mapping_status: str
    mapping_decided_by_user_id: uuid.UUID | None
    mapping_decided_at: datetime | None
    order_uom: str
    units_per_order_uom: Decimal
    order_multiple: Decimal
    min_order_qty: Decimal
    lead_time_days: int | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class PriceCreate(BaseModel):
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4, description="Price per order unit")
    currency: str = Field(min_length=3, max_length=3)
    price_type: PriceType
    order_uom: str = Field(min_length=1, max_length=20, description="Unit the price was quoted per, e.g. case")
    units_per_order_uom: Decimal = Field(
        gt=0, max_digits=18, decimal_places=4, description="Pack the price was quoted for; must match the item"
    )
    source_ref: str | None = Field(default=None, max_length=500, description="Invoice number, file name, URL")
    valid_from: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None


class PriceOut(_Orm):
    id: uuid.UUID
    currency: str
    unit_price: Decimal
    units_per_order_uom: Decimal
    price_type: str
    valid_from: datetime
    expires_at: datetime | None
    superseded_at: datetime | None
    source_ref: str | None
    recorded_by_user_id: uuid.UUID | None
    created_at: datetime


class OrderQuantityOut(BaseModel):
    requested_base_qty: Decimal
    order_qty: Decimal
    order_uom: str
    base_qty: Decimal
    extra_base_qty: Decimal
    constraints_applied: list[str]


class OfferOut(BaseModel):
    supplier_item_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str
    supplier_sku: str
    order_uom: str
    units_per_order_uom: Decimal
    order_multiple: Decimal
    min_order_qty: Decimal
    lead_time_days: int | None
    price: PriceOut | None
    unit_cost_per_base: Decimal | None
    eligible: bool
    blockers: list[str]
