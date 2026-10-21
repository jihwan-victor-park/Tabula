"""v1 API schemas for products, variants, identity matching and external mappings."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SizeUnit = Literal["ml", "l", "fl_oz", "g", "kg", "oz", "lb"]
MatchMethod = Literal["provider_id", "merchant_sku", "gtin", "barcode", "supplier_sku", "text_candidate", "manual"]


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)


class ProductOut(_Orm):
    id: uuid.UUID
    name: str
    brand: str | None
    category: str | None
    created_at: datetime


class VariantCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=300)
    product_id: uuid.UUID | None = Field(
        default=None, description="Existing product; when omitted a product is created from name/brand/category"
    )
    brand: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    barcode: str | None = Field(default=None, max_length=64)
    base_uom: str = Field(default="each", max_length=20)
    size_value: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    size_unit: SizeUnit | None = None
    pack_count: int = Field(default=1, ge=1, description="Units inside one sellable item (a 12-pack sold as one = 12)")
    attributes: dict[str, str] = Field(default_factory=dict, description="Identity attributes, e.g. flavor, color")


class VariantUpdate(BaseModel):
    version: int = Field(description="Version you are editing; a mismatch returns 409")
    name: str | None = Field(default=None, min_length=1, max_length=300)
    barcode: str | None = Field(default=None, max_length=64)
    status: Literal["active", "discontinued"] | None = None
    reason: str | None = Field(default=None, max_length=500)


class VariantOut(_Orm):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    barcode: str | None
    gtin: str | None
    base_uom: str
    size_value: Decimal | None
    size_unit: str | None
    pack_count: int
    attributes: dict[str, Any]
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class MatchRequest(BaseModel):
    source_system: str | None = Field(default=None, max_length=40)
    source_account: str = Field(default="", max_length=255)
    external_id: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=120)
    barcode: str | None = Field(default=None, max_length=64)
    supplier_id: uuid.UUID | None = None
    supplier_sku: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, max_length=300)


class CandidateOut(BaseModel):
    variant_id: uuid.UUID
    sku: str
    name: str
    score: float
    warnings: list[str]


class MatchResultOut(BaseModel):
    variant_id: uuid.UUID | None
    method: str | None
    needs_review: bool
    ambiguous: bool
    conflicts: list[dict[str, str]]
    candidates: list[CandidateOut]


class ExternalMappingCreate(BaseModel):
    source_system: str = Field(min_length=1, max_length=40)
    source_account: str = Field(default="", max_length=255)
    external_id: str = Field(min_length=1, max_length=255)
    variant_id: uuid.UUID
    match_method: MatchMethod
    external_sku: str | None = Field(default=None, max_length=120)
    external_barcode: str | None = Field(default=None, max_length=64)
    external_name: str | None = Field(default=None, max_length=300)


class MappingDecision(BaseModel):
    decision: Literal["confirmed", "rejected"]
    variant_id: uuid.UUID = Field(description="The variant you reviewed; 409 if the mapping changed since")
    reason: str | None = Field(default=None, max_length=500)


class ExternalMappingOut(_Orm):
    id: uuid.UUID
    source_system: str
    source_account: str
    external_id: str
    variant_id: uuid.UUID
    status: str
    match_method: str
    external_sku: str | None
    external_barcode: str | None
    external_name: str | None
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime
