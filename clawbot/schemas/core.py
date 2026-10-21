"""v1 API schemas for tenancy, locations, inventory ledger and audit."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Role = Literal["owner", "manager", "receiver", "bookkeeper"]
# Reasons a person may record by hand; receipts and transfers come from their own flows.
ManualMovementReason = Literal["adjustment", "count", "damage", "return"]
InventoryWriteOwner = Literal["tabula", "square", "shopify", "clover", "lightspeed", "other"]


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantMembershipOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    role: Role


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    memberships: list[TenantMembershipOut]


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(examples=["America/New_York"])
    inventory_write_owner: InventoryWriteOwner = Field(
        default="tabula", description="System that owns stock counts here; Tabula never double-writes a POS-owned location"
    )


class LocationAddress(BaseModel):
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, min_length=2, max_length=2, description="ISO country code, e.g. US")


class LocationOut(_Orm):
    id: uuid.UUID
    name: str
    timezone: str
    inventory_write_owner: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    sales_feed: str
    sales_feed_since: datetime | None
    created_at: datetime


class MovementCreate(BaseModel):
    variant_id: uuid.UUID
    location_id: uuid.UUID
    delta: Decimal = Field(max_digits=18, decimal_places=4)
    reason: ManualMovementReason
    notes: str | None = Field(default=None, max_length=2000)
    occurred_at: AwareDatetime | None = None


class MovementOut(_Orm):
    id: uuid.UUID
    variant_id: uuid.UUID
    location_id: uuid.UUID
    delta: Decimal
    reason: str
    source: str
    source_event_id: str
    notes: str | None
    occurred_at: datetime
    recorded_at: datetime


class PositionOut(_Orm):
    variant_id: uuid.UUID
    location_id: uuid.UUID
    on_hand: Decimal
    version: int
    updated_at: datetime


class MovementResultOut(BaseModel):
    applied: bool
    movement: MovementOut
    position: PositionOut


class MemberSet(BaseModel):
    auth_subject: str = Field(min_length=1, max_length=255, description="Identity provider subject (Auth0 `sub`)")
    email: str | None = Field(default=None, max_length=320)
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    role: Role


class AuditEventOut(_Orm):
    id: uuid.UUID
    actor_kind: str
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    action: str
    object_type: str
    object_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    created_at: datetime
