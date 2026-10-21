"""
Supplier master, supplier items, price history and orderable offers.

Rules (spec 5.1, 5.5, 6.2)
- Suppliers are per-merchant relationships. Nothing here is visible to another tenant.
- A supplier starts as `candidate`. Only a person can approve it, and only once
  the approval checklist passes. Changing how orders reach the supplier sends it
  back to `candidate`; any other edit that would break the checklist is refused.
- A supplier item's link to a variant must be confirmed by a person. Changing the
  pack size un-confirms the link and retires its prices, because a price per
  "case" means something else once the case holds 24 instead of 12.
- Prices are append-only history and always state the pack they were quoted
  for. A future-dated price takes over at its start; until then the current
  price stays valid. Public listings are recorded but never orderable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from clawbot.domain import audit, catalog, tenancy
from clawbot.domain.errors import NotFound, StaleVersion, StateConflict, ValidationFailed
from clawbot.domain.units import (
    CurrencyMismatch,
    normalize_uom,
    require_same_currency,
    unit_cost_per_base,
    validate_currency,
)
from clawbot.persistence.models import (
    ORDERING_CHANNELS,
    PAYMENT_TERMS,
    PRICE_TYPES,
    SUPPLIER_ITEM_STATUSES,
    SUPPLIER_TYPES,
    Supplier,
    SupplierClosure,
    SupplierContact,
    SupplierItem,
    SupplierItemPrice,
    SupplierLocationCoverage,
)
from clawbot.policies.permissions import Actor, authorize

# Fields whose change alters where/how a PO is delivered → re-approval required.
_ORDER_ROUTING_FIELDS = {"ordering_channel", "portal_url", "merchant_account_number"}
_EDITABLE_FIELDS = {
    "name", "supplier_type", "ordering_channel", "portal_url", "merchant_account_number",
    "merchant_account_required", "currency", "payment_terms", "payment_net_days", "credit_hold",
    "min_order_amount", "free_shipping_threshold", "freight_notes", "timezone", "order_cutoff_local",
    "delivery_weekdays", "default_lead_time_days", "notes",
}
_NON_NULL_SUPPLIER_FIELDS = {
    "name", "supplier_type", "merchant_account_required", "currency", "payment_terms", "credit_hold",
    "timezone", "delivery_weekdays",
}
_PACK_FIELDS = {"order_uom", "units_per_order_uom"}
_ITEM_EDITABLE = _PACK_FIELDS | {"description", "order_multiple", "min_order_qty", "lead_time_days", "status", "source_ref"}
_NON_NULL_ITEM_FIELDS = {"order_uom", "units_per_order_uom", "order_multiple", "min_order_qty", "status"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None, field: str) -> datetime | None:
    if value is not None and value.tzinfo is None:
        raise ValidationFailed(f"{field} must include a timezone")
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, (Decimal, uuid.UUID, datetime, date, time)):
        return str(value)
    return value


def _reject_nulls(changes: dict[str, Any], non_null: set[str]) -> None:
    nulls = sorted(k for k, v in changes.items() if v is None and k in non_null)
    if nulls:
        raise ValidationFailed(f"These fields cannot be cleared: {nulls}")


def supplier_snapshot(s: Supplier) -> dict[str, Any]:
    fields = sorted(_EDITABLE_FIELDS | {"relationship_status", "version"})
    return {f: _jsonable(getattr(s, f)) for f in fields}


def _validate_supplier_fields(fields: dict[str, Any]) -> dict[str, Any]:
    _reject_nulls(fields, _NON_NULL_SUPPLIER_FIELDS)
    out = dict(fields)
    if "name" in out:
        out["name"] = out["name"].strip()
        if not out["name"]:
            raise ValidationFailed("name must not be blank")
    if "currency" in out:
        out["currency"] = validate_currency(out["currency"])
    if "supplier_type" in out and out["supplier_type"] not in SUPPLIER_TYPES:
        raise ValidationFailed(f"Unknown supplier_type: {out['supplier_type']}")
    if out.get("ordering_channel") is not None and out["ordering_channel"] not in ORDERING_CHANNELS:
        raise ValidationFailed(f"Unknown ordering_channel: {out['ordering_channel']}")
    if "payment_terms" in out and out["payment_terms"] not in PAYMENT_TERMS:
        raise ValidationFailed(f"Unknown payment_terms: {out['payment_terms']}")
    if "timezone" in out:
        try:
            ZoneInfo(out["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationFailed(f"Unknown timezone: {out['timezone']}")
    if "delivery_weekdays" in out:
        days = out["delivery_weekdays"]
        if any(d not in range(1, 8) for d in days):
            raise ValidationFailed("delivery_weekdays are ISO weekdays 1 (Mon) … 7 (Sun)")
        out["delivery_weekdays"] = sorted(set(days))
    for money_field in ("min_order_amount", "free_shipping_threshold"):
        if out.get(money_field) is not None and out[money_field] < 0:
            raise ValidationFailed(f"{money_field} must not be negative")
    if out.get("default_lead_time_days") is not None and out["default_lead_time_days"] < 0:
        raise ValidationFailed("default_lead_time_days must not be negative")
    return out


def _ensure_name_free(session: Session, *, tenant_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> None:
    stmt = select(Supplier.id).where(Supplier.tenant_id == tenant_id, Supplier.name == name)
    if exclude is not None:
        stmt = stmt.where(Supplier.id != exclude)
    if session.scalars(stmt).first():
        raise ValidationFailed(f"Supplier already exists: {name}")


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


def create_supplier(
    session: Session, *, tenant_id: uuid.UUID, actor: Actor, name: str, **fields: Any
) -> Supplier:
    """New suppliers are always `candidate`, whoever creates them."""
    authorize(actor, "supplier.edit")
    unknown = set(fields) - _EDITABLE_FIELDS
    if unknown:
        raise ValidationFailed(f"Unknown supplier fields: {sorted(unknown)}")
    fields = _validate_supplier_fields({"name": name, **fields})
    if fields.get("payment_terms") == "net" and not fields.get("payment_net_days"):
        raise ValidationFailed("payment_net_days is required when payment_terms is 'net'")
    _ensure_name_free(session, tenant_id=tenant_id, name=fields["name"])
    supplier = Supplier(tenant_id=tenant_id, relationship_status="candidate", **fields)
    session.add(supplier)
    session.flush()
    session.refresh(supplier)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="supplier.created",
        object_type="supplier",
        object_id=supplier.id,
        after=supplier_snapshot(supplier),
    )
    return supplier


def get_supplier(
    session: Session, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID, for_update: bool = False
) -> Supplier:
    stmt = select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.id == supplier_id)
    if for_update:
        stmt = stmt.with_for_update()
    supplier = session.scalars(stmt).one_or_none()
    if supplier is None:
        raise NotFound(f"Supplier not found: {supplier_id}")
    return supplier


def list_suppliers(session: Session, *, tenant_id: uuid.UUID, status: str | None = None) -> list[Supplier]:
    stmt = select(Supplier).where(Supplier.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(Supplier.relationship_status == status)
    return list(session.scalars(stmt.order_by(Supplier.name)))


def update_supplier(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    reason: str | None = None,
) -> Supplier:
    """
    Routing changes (channel, portal, account number) demote an approved
    supplier to `candidate`. Any other change that would break the approval
    checklist of an approved supplier is refused rather than silently accepted.
    """
    authorize(actor, "supplier.edit")
    unknown = set(changes) - _EDITABLE_FIELDS
    if unknown:
        raise ValidationFailed(f"Fields cannot be edited here: {sorted(unknown)}")
    supplier = get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id, for_update=True)
    if supplier.version != expected_version:
        raise StaleVersion(f"Supplier is at version {supplier.version}, not {expected_version}")
    changes = _validate_supplier_fields(changes)
    changed = {k for k, v in changes.items() if getattr(supplier, k) != v}
    if not changed:
        return supplier
    if "name" in changed:
        _ensure_name_free(session, tenant_id=tenant_id, name=changes["name"], exclude=supplier_id)
    if "currency" in changed and _has_live_prices(session, tenant_id=tenant_id, supplier_id=supplier_id):
        raise StateConflict("Retire this supplier's current prices before changing its currency")

    before = supplier_snapshot(supplier)
    blockers_before = set(approval_blockers(session, supplier))
    for key in changed:
        setattr(supplier, key, changes[key])
    if supplier.payment_terms != "net":
        supplier.payment_net_days = None
    elif not supplier.payment_net_days:
        raise ValidationFailed("payment_net_days is required when payment_terms is 'net'")

    action = "supplier.updated"
    if supplier.relationship_status == "approved":
        if changed & _ORDER_ROUTING_FIELDS:
            supplier.relationship_status = "candidate"
            supplier.verified_at = None
            supplier.verified_by_user_id = None
            action = "supplier.updated_needs_reapproval"
        else:
            # Refuse only what this edit breaks; pre-existing gaps never block an
            # unrelated edit (e.g. putting the supplier on credit hold).
            session.flush()
            introduced = [b for b in approval_blockers(session, supplier) if b not in blockers_before]
            if introduced:
                raise StateConflict(
                    "This change would leave an approved supplier unable to receive orders",
                    details={"blockers": introduced},
                )
    supplier.version += 1
    supplier.updated_at = _now()
    session.flush()
    session.refresh(supplier)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        object_type="supplier",
        object_id=supplier.id,
        before=before,
        after=supplier_snapshot(supplier),
        reason=reason,
    )
    return supplier


def approval_blockers(session: Session, supplier: Supplier) -> list[str]:
    """
    Everything that must be known before this supplier can receive Tabula POs
    (spec 5.5). "None" answers are explicit: min_order_amount = 0 means no
    minimum; merchant_account_required = false means the supplier issues none.
    Payee verification is a payments concern (CP14), not an ordering one.
    """
    blockers: list[str] = []
    if supplier.ordering_channel is None:
        blockers.append("ordering_channel_missing")
    elif supplier.ordering_channel == "email":
        has_verified = session.scalars(
            select(SupplierContact.id).where(
                SupplierContact.tenant_id == supplier.tenant_id,
                SupplierContact.supplier_id == supplier.id,
                SupplierContact.is_order_recipient.is_(True),
                SupplierContact.email.is_not(None),
                SupplierContact.verified_at.is_not(None),
            )
        ).first()
        if not has_verified:
            blockers.append("no_verified_order_email")
    elif supplier.ordering_channel == "portal" and not supplier.portal_url:
        blockers.append("portal_url_missing")
    if supplier.merchant_account_required and not supplier.merchant_account_number:
        blockers.append("merchant_account_missing")
    if supplier.payment_terms == "unknown":
        blockers.append("payment_terms_unknown")
    if supplier.default_lead_time_days is None:
        blockers.append("lead_time_missing")
    if supplier.min_order_amount is None:
        blockers.append("min_order_terms_missing")
    if not (supplier.freight_notes or "").strip():
        blockers.append("freight_terms_missing")
    covered = session.scalars(
        select(SupplierLocationCoverage.location_id).where(
            SupplierLocationCoverage.tenant_id == supplier.tenant_id,
            SupplierLocationCoverage.supplier_id == supplier.id,
        )
    ).first()
    if not covered:
        blockers.append("no_location_coverage")
    return blockers


def set_supplier_status(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    expected_version: int,
    status: str,
    reason: str | None = None,
) -> Supplier:
    """approve / suspend / archive / back to candidate. Approval is always a person's decision."""
    if status not in ("approved", "candidate", "suspended", "archived"):
        raise ValidationFailed(f"Unknown status: {status}")
    authorize(actor, "supplier.approve" if status == "approved" else "supplier.edit")
    supplier = get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id, for_update=True)
    if supplier.version != expected_version:
        raise StaleVersion(f"Supplier is at version {supplier.version}, not {expected_version}")
    if supplier.relationship_status == status:
        return supplier
    before = supplier_snapshot(supplier)
    if status == "approved":
        blockers = approval_blockers(session, supplier)
        if blockers:
            raise ValidationFailed("Supplier cannot be approved yet", details={"blockers": blockers})
        supplier.verified_at = _now()
        supplier.verified_by_user_id = actor.user_id
    elif status == "candidate":
        supplier.verified_at = None
        supplier.verified_by_user_id = None
    supplier.relationship_status = status
    supplier.version += 1
    supplier.updated_at = _now()
    session.flush()
    session.refresh(supplier)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=f"supplier.{status}",
        object_type="supplier",
        object_id=supplier.id,
        before=before,
        after=supplier_snapshot(supplier),
        reason=reason,
    )
    return supplier


def _ensure_still_approvable(session: Session, supplier: Supplier, what: str) -> None:
    if supplier.relationship_status == "approved":
        blockers = approval_blockers(session, supplier)
        if blockers:
            raise StateConflict(
                f"{what} would leave an approved supplier unable to receive orders",
                details={"blockers": blockers},
            )


# ---------------------------------------------------------------------------
# Contacts, coverage, closures
# ---------------------------------------------------------------------------


def add_contact(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    name: str | None,
    email: str | None,
    phone: str | None,
    role: str | None,
    is_order_recipient: bool,
) -> SupplierContact:
    """New contacts are unverified. POs are only ever sent to verified order recipients (CP7)."""
    authorize(actor, "supplier.edit")
    get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    email = email.strip().lower() if email else None
    if not email and not phone:
        raise ValidationFailed("A contact needs an email or a phone number")
    if email and session.scalars(
        select(SupplierContact.id).where(
            SupplierContact.tenant_id == tenant_id,
            SupplierContact.supplier_id == supplier_id,
            SupplierContact.email == email,
        )
    ).first():
        raise ValidationFailed(f"Contact already exists: {email}")
    contact = SupplierContact(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        name=name,
        email=email,
        phone=phone,
        role=role,
        is_order_recipient=is_order_recipient,
    )
    session.add(contact)
    session.flush()
    session.refresh(contact)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="supplier_contact.added",
        object_type="supplier_contact",
        object_id=contact.id,
        after={"supplier_id": str(supplier_id), "email": email, "is_order_recipient": is_order_recipient},
    )
    return contact


def _get_contact(session: Session, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID, contact_id: uuid.UUID):
    contact = session.scalars(
        select(SupplierContact).where(
            SupplierContact.tenant_id == tenant_id,
            SupplierContact.supplier_id == supplier_id,
            SupplierContact.id == contact_id,
        )
    ).one_or_none()
    if contact is None:
        raise NotFound(f"Contact not found: {contact_id}")
    return contact


def list_contacts(session: Session, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> list[SupplierContact]:
    get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    return list(
        session.scalars(
            select(SupplierContact)
            .where(SupplierContact.tenant_id == tenant_id, SupplierContact.supplier_id == supplier_id)
            .order_by(SupplierContact.created_at)
        )
    )


def verify_contact(
    session: Session, *, tenant_id: uuid.UUID, actor: Actor, supplier_id: uuid.UUID, contact_id: uuid.UUID
) -> SupplierContact:
    """The merchant confirms this address really is the supplier's ordering address."""
    authorize(actor, "supplier.verify_contact")
    contact = _get_contact(session, tenant_id=tenant_id, supplier_id=supplier_id, contact_id=contact_id)
    if contact.verified_at is None:
        contact.verified_at = _now()
        contact.verified_by_user_id = actor.user_id
        session.flush()
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="supplier_contact.verified",
            object_type="supplier_contact",
            object_id=contact.id,
            after={"email": contact.email},
        )
    return contact


def remove_contact(
    session: Session, *, tenant_id: uuid.UUID, actor: Actor, supplier_id: uuid.UUID, contact_id: uuid.UUID
) -> None:
    authorize(actor, "supplier.edit")
    supplier = get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id, for_update=True)
    contact = _get_contact(session, tenant_id=tenant_id, supplier_id=supplier_id, contact_id=contact_id)
    snapshot = {"email": contact.email, "phone": contact.phone, "verified": contact.verified_at is not None}
    session.delete(contact)
    session.flush()
    _ensure_still_approvable(session, supplier, "Removing this contact")
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="supplier_contact.removed",
        object_type="supplier_contact",
        object_id=contact_id,
        before=snapshot,
    )


def set_coverage(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    location_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    authorize(actor, "supplier.edit")
    supplier = get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id, for_update=True)
    for location_id in location_ids:
        tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    before = sorted(str(x) for x in coverage(session, tenant_id=tenant_id, supplier_id=supplier_id))
    session.execute(
        delete(SupplierLocationCoverage).where(
            SupplierLocationCoverage.tenant_id == tenant_id, SupplierLocationCoverage.supplier_id == supplier_id
        )
    )
    for location_id in set(location_ids):
        session.add(SupplierLocationCoverage(tenant_id=tenant_id, supplier_id=supplier_id, location_id=location_id))
    session.flush()
    _ensure_still_approvable(session, supplier, "Removing all delivery locations")
    after = sorted(str(x) for x in set(location_ids))
    if before != after:
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="supplier.coverage_set",
            object_type="supplier",
            object_id=supplier_id,
            before={"location_ids": before},
            after={"location_ids": after},
        )
    return [uuid.UUID(x) for x in after]


def coverage(session: Session, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(SupplierLocationCoverage.location_id).where(
                SupplierLocationCoverage.tenant_id == tenant_id, SupplierLocationCoverage.supplier_id == supplier_id
            )
        )
    )


def add_closure(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    starts_on: date,
    ends_on: date,
    reason: str | None,
) -> SupplierClosure:
    authorize(actor, "supplier.edit")
    get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    if ends_on < starts_on:
        raise ValidationFailed("ends_on must be on or after starts_on")
    closure = SupplierClosure(
        tenant_id=tenant_id, supplier_id=supplier_id, starts_on=starts_on, ends_on=ends_on, reason=reason
    )
    session.add(closure)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="supplier.closure_added",
        object_type="supplier",
        object_id=supplier_id,
        after={"starts_on": str(starts_on), "ends_on": str(ends_on), "reason": reason},
    )
    return closure


def list_closures(session: Session, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> list[SupplierClosure]:
    get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    return list(
        session.scalars(
            select(SupplierClosure)
            .where(SupplierClosure.tenant_id == tenant_id, SupplierClosure.supplier_id == supplier_id)
            .order_by(SupplierClosure.starts_on)
        )
    )


# ---------------------------------------------------------------------------
# Supplier items
# ---------------------------------------------------------------------------


def item_snapshot(i: SupplierItem) -> dict[str, Any]:
    fields = (
        "supplier_sku", "description", "variant_id", "mapping_status", "order_uom", "units_per_order_uom",
        "order_multiple", "min_order_qty", "lead_time_days", "status", "source_ref", "version",
    )
    return {f: _jsonable(getattr(i, f)) for f in fields}


def _validate_pack(units_per: Decimal, multiple: Decimal, moq: Decimal) -> None:
    if units_per <= 0:
        raise ValidationFailed("units_per_order_uom must be positive")
    if multiple <= 0 or moq <= 0:
        raise ValidationFailed("order_multiple and min_order_qty must be positive")


def create_supplier_item(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    supplier_sku: str,
    order_uom: str,
    units_per_order_uom: Decimal,
    description: str | None = None,
    order_multiple: Decimal = Decimal(1),
    min_order_qty: Decimal = Decimal(1),
    lead_time_days: int | None = None,
    suggested_variant_id: uuid.UUID | None = None,
    source_ref: str | None = None,
) -> SupplierItem:
    """Create a supplier item. A variant given here is only a suggestion until a person confirms it."""
    authorize(actor, "supplier_item.edit")
    get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    supplier_sku = supplier_sku.strip()
    order_uom = normalize_uom(order_uom)
    if not supplier_sku or not order_uom:
        raise ValidationFailed("supplier_sku and order_uom must not be blank")
    _validate_pack(units_per_order_uom, order_multiple, min_order_qty)
    if lead_time_days is not None and lead_time_days < 0:
        raise ValidationFailed("lead_time_days must not be negative")
    if suggested_variant_id is not None:
        catalog.get_variant(session, tenant_id=tenant_id, variant_id=suggested_variant_id)
    if session.scalars(
        select(SupplierItem.id).where(
            SupplierItem.tenant_id == tenant_id,
            SupplierItem.supplier_id == supplier_id,
            SupplierItem.supplier_sku == supplier_sku,
        )
    ).first():
        raise ValidationFailed(f"Supplier SKU already exists for this supplier: {supplier_sku}")

    item = SupplierItem(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        supplier_sku=supplier_sku,
        description=description,
        variant_id=suggested_variant_id,
        mapping_status="suggested" if suggested_variant_id else "unmapped",
        order_uom=order_uom,
        units_per_order_uom=units_per_order_uom,
        order_multiple=order_multiple,
        min_order_qty=min_order_qty,
        lead_time_days=lead_time_days,
        source_ref=source_ref,
    )
    session.add(item)
    session.flush()
    session.refresh(item)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="supplier_item.created",
        object_type="supplier_item",
        object_id=item.id,
        after=item_snapshot(item),
    )
    return item


def get_supplier_item(
    session: Session, *, tenant_id: uuid.UUID, item_id: uuid.UUID, for_update: bool = False
) -> SupplierItem:
    stmt = select(SupplierItem).where(SupplierItem.tenant_id == tenant_id, SupplierItem.id == item_id)
    if for_update:
        stmt = stmt.with_for_update()
    item = session.scalars(stmt).one_or_none()
    if item is None:
        raise NotFound(f"Supplier item not found: {item_id}")
    return item


def list_supplier_items(session: Session, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> list[SupplierItem]:
    get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    return list(
        session.scalars(
            select(SupplierItem)
            .where(SupplierItem.tenant_id == tenant_id, SupplierItem.supplier_id == supplier_id)
            .order_by(SupplierItem.supplier_sku)
        )
    )


def decide_item_mapping(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    item_id: uuid.UUID,
    expected_version: int,
    decision: str,
    variant_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> SupplierItem:
    """
    confirm: link to `variant_id` (or the suggested variant) — a person's decision.
    reject:  mark the suggestion wrong; the item stays unorderable until re-mapped.
    """
    authorize(actor, "mapping.decide")
    item = get_supplier_item(session, tenant_id=tenant_id, item_id=item_id, for_update=True)
    if item.version != expected_version:
        raise StaleVersion(f"Supplier item is at version {item.version}, not {expected_version}")
    before = item_snapshot(item)
    if decision == "confirmed":
        target = variant_id or item.variant_id
        if target is None:
            raise ValidationFailed("variant_id is required to confirm an unmapped item")
        catalog.get_variant(session, tenant_id=tenant_id, variant_id=target)
        item.variant_id = target
    elif decision == "rejected":
        if variant_id is not None:
            raise ValidationFailed("variant_id is not used when rejecting")
    else:
        raise ValidationFailed("decision must be 'confirmed' or 'rejected'")
    item.mapping_status = decision
    item.mapping_decided_by_user_id = actor.user_id
    item.mapping_decided_at = _now()
    item.version += 1
    item.updated_at = _now()
    session.flush()
    session.refresh(item)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=f"supplier_item.mapping_{decision}",
        object_type="supplier_item",
        object_id=item.id,
        before=before,
        after=item_snapshot(item),
        reason=reason,
    )
    return item


def update_supplier_item(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    item_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
    reason: str | None = None,
) -> SupplierItem:
    authorize(actor, "supplier_item.edit")
    unknown = set(changes) - _ITEM_EDITABLE
    if unknown:
        raise ValidationFailed(f"Fields cannot be edited here: {sorted(unknown)}")
    _reject_nulls(changes, _NON_NULL_ITEM_FIELDS)
    item = get_supplier_item(session, tenant_id=tenant_id, item_id=item_id, for_update=True)
    if item.version != expected_version:
        raise StaleVersion(f"Supplier item is at version {item.version}, not {expected_version}")
    if "status" in changes and changes["status"] not in SUPPLIER_ITEM_STATUSES:
        raise ValidationFailed(f"Unknown status: {changes['status']}")
    if changes.get("lead_time_days") is not None and changes["lead_time_days"] < 0:
        raise ValidationFailed("lead_time_days must not be negative")
    if "order_uom" in changes:
        changes["order_uom"] = normalize_uom(changes["order_uom"])
        if not changes["order_uom"]:
            raise ValidationFailed("order_uom must not be blank")
    _validate_pack(
        changes.get("units_per_order_uom", item.units_per_order_uom),
        changes.get("order_multiple", item.order_multiple),
        changes.get("min_order_qty", item.min_order_qty),
    )

    before = item_snapshot(item)
    changed = {k for k, v in changes.items() if getattr(item, k) != v}
    if not changed:
        return item
    for key in changed:
        setattr(item, key, changes[key])

    action = "supplier_item.updated"
    if changed & _PACK_FIELDS:
        # Prices and the confirmation were both for the old pack.
        _retire_prices(session, tenant_id=tenant_id, item_id=item.id)
        if item.mapping_status == "confirmed":
            item.mapping_status = "suggested"
            item.mapping_decided_by_user_id = None
            item.mapping_decided_at = None
        action = "supplier_item.pack_changed"
    item.version += 1
    item.updated_at = _now()
    session.flush()
    session.refresh(item)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        object_type="supplier_item",
        object_id=item.id,
        before=before,
        after=item_snapshot(item),
        reason=reason,
    )
    return item


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def _orderable_prices():
    return SupplierItemPrice.price_type != "public_listing"


def current_price(
    session: Session, *, tenant_id: uuid.UUID, item_id: uuid.UUID, at: datetime | None = None
) -> SupplierItemPrice | None:
    """The orderable price in force at `at`: started, and not yet superseded."""
    at = at or _now()
    return session.scalars(
        select(SupplierItemPrice)
        .where(
            SupplierItemPrice.tenant_id == tenant_id,
            SupplierItemPrice.supplier_item_id == item_id,
            _orderable_prices(),
            SupplierItemPrice.valid_from <= at,
            or_(SupplierItemPrice.superseded_at.is_(None), SupplierItemPrice.superseded_at > at),
        )
        .order_by(SupplierItemPrice.valid_from.desc())
        .limit(1)
    ).one_or_none()


def _latest_price(session: Session, *, tenant_id: uuid.UUID, item_id: uuid.UUID) -> SupplierItemPrice | None:
    """The newest orderable price, possibly scheduled for the future (the open end of the chain)."""
    return session.scalars(
        select(SupplierItemPrice).where(
            SupplierItemPrice.tenant_id == tenant_id,
            SupplierItemPrice.supplier_item_id == item_id,
            _orderable_prices(),
            SupplierItemPrice.superseded_at.is_(None),
        )
    ).one_or_none()


def _retire_prices(session: Session, *, tenant_id: uuid.UUID, item_id: uuid.UUID) -> None:
    """End every orderable price that is current or scheduled, as of now."""
    now = _now()
    live = session.scalars(
        select(SupplierItemPrice).where(
            SupplierItemPrice.tenant_id == tenant_id,
            SupplierItemPrice.supplier_item_id == item_id,
            _orderable_prices(),
            or_(SupplierItemPrice.superseded_at.is_(None), SupplierItemPrice.superseded_at > now),
        )
    )
    for price in live:
        # A not-yet-started price ends the moment it would have started.
        price.superseded_at = max(now, price.valid_from)


def _has_live_prices(session: Session, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> bool:
    return (
        session.scalars(
            select(SupplierItemPrice.id)
            .join(
                SupplierItem,
                (SupplierItem.tenant_id == SupplierItemPrice.tenant_id)
                & (SupplierItem.id == SupplierItemPrice.supplier_item_id),
            )
            .where(
                SupplierItem.tenant_id == tenant_id,
                SupplierItem.supplier_id == supplier_id,
                SupplierItemPrice.superseded_at.is_(None),
                _orderable_prices(),
            )
        ).first()
        is not None
    )


def record_price(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    item_id: uuid.UUID,
    unit_price: Decimal,
    currency: str,
    price_type: str,
    order_uom: str,
    units_per_order_uom: Decimal,
    source_ref: str | None = None,
    valid_from: datetime | None = None,
    expires_at: datetime | None = None,
) -> SupplierItemPrice:
    """
    Append a price quoted for a stated pack ("$55 per case of 24"). The quoted
    pack must match the item's current pack: if the supplier changed the case
    size, update the item first (which un-confirms its mapping) — a price is
    never silently re-interpreted against a different pack.

    An orderable price takes over from the previous one at its `valid_from`
    (now, or a future date). Orderable prices must be in the supplier's
    currency so PO totals never mix currencies.
    """
    authorize(actor, "price.record")
    if price_type not in PRICE_TYPES:
        raise ValidationFailed(f"Unknown price_type: {price_type}")
    if unit_price < 0:
        raise ValidationFailed("unit_price must not be negative")
    currency = validate_currency(currency)
    _aware(valid_from, "valid_from")
    _aware(expires_at, "expires_at")
    item = get_supplier_item(session, tenant_id=tenant_id, item_id=item_id, for_update=True)
    if (normalize_uom(order_uom), Decimal(units_per_order_uom)) != (item.order_uom, item.units_per_order_uom):
        raise ValidationFailed(
            f"Price was quoted per {order_uom} of {units_per_order_uom}, but this item is ordered per "
            f"{item.order_uom} of {item.units_per_order_uom}; update the item's pack first",
            details={
                "quoted": {"order_uom": order_uom, "units_per_order_uom": str(units_per_order_uom)},
                "item": {"order_uom": item.order_uom, "units_per_order_uom": str(item.units_per_order_uom)},
            },
        )
    valid_from = valid_from or _now()
    if expires_at is not None and expires_at <= valid_from:
        raise ValidationFailed("expires_at must be after valid_from")

    previous = None
    if price_type != "public_listing":
        supplier = get_supplier(session, tenant_id=tenant_id, supplier_id=item.supplier_id)
        if currency != supplier.currency:
            raise CurrencyMismatch(
                f"Orderable prices for {supplier.name} must be in {supplier.currency}, not {currency}"
            )
        # History is append-only: a new price may not start before anything already
        # recorded for this item started or ended (that would rewrite the past).
        last_change = session.scalar(
            select(func.max(func.greatest(SupplierItemPrice.valid_from, SupplierItemPrice.superseded_at))).where(
                SupplierItemPrice.tenant_id == tenant_id,
                SupplierItemPrice.supplier_item_id == item_id,
                _orderable_prices(),
            )
        )
        if last_change is not None and valid_from <= last_change:
            raise ValidationFailed(
                "This item already has price history at or after this date; back-dated prices are not supported"
            )
        previous = _latest_price(session, tenant_id=tenant_id, item_id=item_id)
        if previous is not None:
            previous.superseded_at = valid_from
            session.flush()

    price = SupplierItemPrice(
        tenant_id=tenant_id,
        supplier_item_id=item_id,
        currency=currency,
        unit_price=unit_price,
        units_per_order_uom=item.units_per_order_uom,
        price_type=price_type,
        valid_from=valid_from,
        expires_at=expires_at,
        source_ref=source_ref,
        recorded_by_user_id=actor.user_id,
    )
    session.add(price)
    session.flush()
    session.refresh(price)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="supplier_item.price_recorded",
        object_type="supplier_item",
        object_id=item_id,
        before=None if previous is None else {"unit_price": str(previous.unit_price), "currency": previous.currency},
        after={
            "unit_price": str(unit_price), "currency": currency, "price_type": price_type,
            "valid_from": valid_from.isoformat(), "source_ref": source_ref,
        },
    )  # object_type supplier_item → bumps the data version
    return price


def price_history(session: Session, *, tenant_id: uuid.UUID, item_id: uuid.UUID) -> list[SupplierItemPrice]:
    get_supplier_item(session, tenant_id=tenant_id, item_id=item_id)
    return list(
        session.scalars(
            select(SupplierItemPrice)
            .where(SupplierItemPrice.tenant_id == tenant_id, SupplierItemPrice.supplier_item_id == item_id)
            .order_by(SupplierItemPrice.valid_from.desc(), SupplierItemPrice.created_at.desc())
        )
    )


# ---------------------------------------------------------------------------
# Orderable offers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Offer:
    supplier_item: SupplierItem
    supplier: Supplier
    price: SupplierItemPrice | None
    unit_cost_per_base: Decimal | None
    lead_time_days: int | None
    blockers: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.blockers


def offers_for_variant(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    location_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> list[Offer]:
    """
    Every supplier item linked to this variant, with the reasons it cannot be
    ordered automatically. Replenishment only uses offers with no blockers.
    """
    at = at or _now()
    variant = catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    if location_id is not None:
        tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    rows = session.execute(
        select(SupplierItem, Supplier)
        .join(Supplier, (Supplier.tenant_id == SupplierItem.tenant_id) & (Supplier.id == SupplierItem.supplier_id))
        .where(SupplierItem.tenant_id == tenant_id, SupplierItem.variant_id == variant_id)
        .order_by(Supplier.name, SupplierItem.supplier_sku)
    ).all()

    offers = []
    for item, supplier in rows:
        blockers: list[str] = []
        if supplier.relationship_status != "approved":
            blockers.append(f"supplier_{supplier.relationship_status}")
        if supplier.credit_hold:
            blockers.append("supplier_credit_hold")
        if item.mapping_status != "confirmed":
            blockers.append(f"mapping_{item.mapping_status}")
        if item.status != "active":
            blockers.append(f"item_{item.status}")
        if variant.status != "active":
            blockers.append(f"variant_{variant.status}")
        if location_id is not None and location_id not in coverage(
            session, tenant_id=tenant_id, supplier_id=supplier.id
        ):
            blockers.append("not_delivering_to_location")

        price = current_price(session, tenant_id=tenant_id, item_id=item.id, at=at)
        unit_cost = None
        if price is None:
            blockers.append("no_current_price")
        else:
            if price.expires_at is not None and price.expires_at <= at:
                blockers.append("price_expired")
            if price.units_per_order_uom != item.units_per_order_uom:
                blockers.append("price_pack_mismatch")
            unit_cost = unit_cost_per_base(price.unit_price, item.units_per_order_uom)

        lead = item.lead_time_days if item.lead_time_days is not None else supplier.default_lead_time_days
        if lead is None:
            blockers.append("lead_time_unknown")
        offers.append(Offer(item, supplier, price, unit_cost, lead, tuple(blockers)))
    return offers


def cheapest_eligible(offers: list[Offer]) -> Offer | None:
    """Lowest base-unit cost among eligible offers. Refuses to compare across currencies."""
    eligible = [o for o in offers if o.eligible]
    if not eligible:
        return None
    require_same_currency(*(o.price.currency for o in eligible if o.price))
    return min(eligible, key=lambda o: o.unit_cost_per_base)
