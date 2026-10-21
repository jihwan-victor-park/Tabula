"""v1 API schemas for file imports and the records they create."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ImportKind = Literal["supplier_price_list", "inventory", "sales", "open_orders"]
SalesSource = Literal["square", "shopify", "clover", "lightspeed", "toast", "woocommerce", "amazon", "faire",
                      "other_pos", "manual"]


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ImportOut(_Orm):
    id: uuid.UUID
    kind: str
    status: str
    file_name: str
    file_sha256: str
    file_size: int
    file_format: str
    header: list[str]
    row_count: int
    context: dict[str, Any]
    mapping: dict[str, Any]
    mapping_revision: int
    accept_row_errors: bool
    summary: dict[str, Any]
    failure: str | None
    confirmed_by_user_id: uuid.UUID | None
    confirmed_at: datetime | None
    applied_at: datetime | None
    created_at: datetime


class MappingUpdate(BaseModel):
    revision: int = Field(description="The mapping revision you are editing")
    columns: dict[str, str] = Field(description="field name → column name from the file header")
    settings: dict[str, Any] = Field(default_factory=dict, description="Meanings the columns cannot settle (see preview)")


class ConfirmImport(BaseModel):
    revision: int = Field(description="The mapping revision you previewed; 409 if it changed since")
    accept_row_errors: bool = Field(default=False, description="Apply valid rows and leave rows with errors out")
    declared: dict[str, Any] = Field(
        default_factory=dict,
        description="Restate the meaning settings shown in preview (`declared_settings`); 422 if they differ",
    )


class RejectImport(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class SalesLineOut(_Orm):
    id: uuid.UUID
    variant_id: uuid.UUID
    location_id: uuid.UUID
    source_system: str
    external_order_id: str
    external_line_key: str
    sold_at: datetime
    line_type: str
    quantity: Decimal
    unit_price: Decimal | None
    currency: str | None
    import_id: uuid.UUID | None


class SnapshotOut(_Orm):
    id: uuid.UUID
    variant_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal
    as_of: datetime
    source_system: str
    source_ref: str


class OpenOrderLineOut(_Orm):
    id: uuid.UUID
    supplier_id: uuid.UUID
    variant_id: uuid.UUID
    location_id: uuid.UUID
    external_po_number: str
    outstanding_qty: Decimal
    ordered_at: datetime | None
    expected_at: datetime | None
    supplier_confirmed: bool
    import_id: uuid.UUID | None
