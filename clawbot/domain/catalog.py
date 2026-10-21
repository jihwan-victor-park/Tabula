"""
Products, variants and external item mappings.

Identity fields of a variant (size, pack count, attributes such as flavour or
colour) are fixed at creation: a different size is a different variant, so
"fixing" a size means creating the right variant, not mutating this one.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.domain import audit
from clawbot.domain.errors import NotFound, StaleVersion, StateConflict, ValidationFailed
from clawbot.domain.gtin import normalize_gtin
from clawbot.persistence.models import (
    VARIANT_STATUSES,
    ExternalItemMapping,
    Product,
    Variant,
)
from clawbot.policies.permissions import Actor, authorize

# Accepted size units → (dimension, factor to the dimension's canonical unit).
SIZE_UNITS: dict[str, tuple[str, Decimal]] = {
    "ml": ("volume", Decimal(1)),
    "l": ("volume", Decimal(1000)),
    "fl_oz": ("volume", Decimal("29.5735295625")),
    "g": ("mass", Decimal(1)),
    "kg": ("mass", Decimal(1000)),
    "oz": ("mass", Decimal("28.349523125")),
    "lb": ("mass", Decimal("453.59237")),
}

MATCH_METHODS = ("provider_id", "merchant_sku", "gtin", "barcode", "supplier_sku", "text_candidate", "manual")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def variant_snapshot(v: Variant) -> dict[str, Any]:
    return {
        "sku": v.sku,
        "name": v.name,
        "barcode": v.barcode,
        "gtin": v.gtin,
        "size_value": None if v.size_value is None else str(v.size_value),
        "size_unit": v.size_unit,
        "pack_count": v.pack_count,
        "attributes": v.attributes,
        "status": v.status,
        "version": v.version,
    }


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


def create_product(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    name: str,
    brand: str | None = None,
    category: str | None = None,
) -> Product:
    authorize(actor, "catalog.edit")
    product = Product(tenant_id=tenant_id, name=name, brand=brand, category=category)
    session.add(product)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="product.created",
        object_type="product",
        object_id=product.id,
        after={"name": name, "brand": brand, "category": category},
    )
    return product


def get_product(session: Session, *, tenant_id: uuid.UUID, product_id: uuid.UUID) -> Product:
    product = session.scalars(
        select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id)
    ).one_or_none()
    if product is None:
        raise NotFound(f"Product not found: {product_id}")
    return product


def list_products(session: Session, *, tenant_id: uuid.UUID) -> list[Product]:
    return list(session.scalars(select(Product).where(Product.tenant_id == tenant_id).order_by(Product.name)))


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------


def create_variant(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    sku: str,
    name: str,
    product_id: uuid.UUID | None = None,
    brand: str | None = None,
    category: str | None = None,
    barcode: str | None = None,
    base_uom: str = "each",
    size_value: Decimal | None = None,
    size_unit: str | None = None,
    pack_count: int = 1,
    attributes: dict[str, Any] | None = None,
) -> Variant:
    authorize(actor, "catalog.edit")
    sku = sku.strip()
    if not sku:
        raise ValidationFailed("SKU must not be blank")
    if (size_value is None) != (size_unit is None):
        raise ValidationFailed("size_value and size_unit must be given together")
    if size_unit is not None and size_unit not in SIZE_UNITS:
        raise ValidationFailed(f"Unknown size unit: {size_unit} (use one of {sorted(SIZE_UNITS)})")
    if size_value is not None and size_value <= 0:
        raise ValidationFailed("size_value must be positive")
    if pack_count < 1:
        raise ValidationFailed("pack_count must be at least 1")

    if session.scalars(select(Variant.id).where(Variant.tenant_id == tenant_id, Variant.sku == sku)).first():
        raise ValidationFailed(f"SKU already exists: {sku}")
    barcode = barcode.strip() if barcode else None
    gtin = normalize_gtin(barcode)
    if gtin is not None:
        clash = session.scalars(
            select(Variant).where(Variant.tenant_id == tenant_id, Variant.gtin == gtin)
        ).first()
        if clash is not None:
            raise ValidationFailed(
                f"GTIN {gtin} already belongs to SKU {clash.sku}",
                details={"existing_variant_id": str(clash.id)},
            )

    if product_id is None:
        product_id = create_product(
            session, tenant_id=tenant_id, actor=actor, name=name, brand=brand, category=category
        ).id
    else:
        get_product(session, tenant_id=tenant_id, product_id=product_id)

    variant = Variant(
        tenant_id=tenant_id,
        product_id=product_id,
        sku=sku,
        name=name,
        barcode=barcode,
        gtin=gtin,
        base_uom=base_uom,
        size_value=size_value,
        size_unit=size_unit,
        pack_count=pack_count,
        attributes=attributes or {},
    )
    session.add(variant)
    session.flush()
    session.refresh(variant)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="variant.created",
        object_type="variant",
        object_id=variant.id,
        after=variant_snapshot(variant),
    )
    return variant


def update_variant(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    variant_id: uuid.UUID,
    expected_version: int,
    name: str | None = None,
    barcode: str | None = None,
    status: str | None = None,
    reason: str | None = None,
) -> Variant:
    """Edit non-identity fields. Size, pack count and attributes are immutable."""
    authorize(actor, "catalog.edit")
    variant = get_variant(session, tenant_id=tenant_id, variant_id=variant_id, for_update=True)
    if variant.version != expected_version:
        raise StaleVersion(f"Variant is at version {variant.version}, not {expected_version}")
    before = variant_snapshot(variant)

    if status is not None:
        if status not in VARIANT_STATUSES:
            raise ValidationFailed(f"Unknown status: {status}")
        variant.status = status
    if name is not None:
        variant.name = name
    if barcode is not None:
        barcode = barcode.strip() or None
        gtin = normalize_gtin(barcode)
        if gtin is not None:
            clash = session.scalars(
                select(Variant).where(
                    Variant.tenant_id == tenant_id, Variant.gtin == gtin, Variant.id != variant_id
                )
            ).first()
            if clash is not None:
                raise ValidationFailed(f"GTIN {gtin} already belongs to SKU {clash.sku}")
        variant.barcode, variant.gtin = barcode, gtin

    variant.version += 1
    variant.updated_at = _now()
    session.flush()
    session.refresh(variant)
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="variant.updated",
        object_type="variant",
        object_id=variant.id,
        before=before,
        after=variant_snapshot(variant),
        reason=reason,
    )
    return variant


def list_variants(session: Session, *, tenant_id: uuid.UUID) -> list[Variant]:
    return list(session.scalars(select(Variant).where(Variant.tenant_id == tenant_id).order_by(Variant.sku)))


def get_variant(
    session: Session, *, tenant_id: uuid.UUID, variant_id: uuid.UUID, for_update: bool = False
) -> Variant:
    stmt = select(Variant).where(Variant.tenant_id == tenant_id, Variant.id == variant_id)
    if for_update:
        stmt = stmt.with_for_update()
    variant = session.scalars(stmt).one_or_none()
    if variant is None:
        raise NotFound(f"Variant not found: {variant_id}")
    return variant


# ---------------------------------------------------------------------------
# External item mappings
# ---------------------------------------------------------------------------


def _mapping_snapshot(m: ExternalItemMapping) -> dict[str, Any]:
    return {"variant_id": str(m.variant_id), "status": m.status, "match_method": m.match_method}


def get_external_mapping(
    session: Session, *, tenant_id: uuid.UUID, mapping_id: uuid.UUID, for_update: bool = False
) -> ExternalItemMapping:
    stmt = select(ExternalItemMapping).where(
        ExternalItemMapping.tenant_id == tenant_id, ExternalItemMapping.id == mapping_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    mapping = session.scalars(stmt).one_or_none()
    if mapping is None:
        raise NotFound(f"Mapping not found: {mapping_id}")
    return mapping


def list_external_mappings(
    session: Session, *, tenant_id: uuid.UUID, status: str | None = None
) -> list[ExternalItemMapping]:
    stmt = select(ExternalItemMapping).where(ExternalItemMapping.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(ExternalItemMapping.status == status)
    return list(session.scalars(stmt.order_by(ExternalItemMapping.created_at)))


def propose_external_mapping(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    source_system: str,
    external_id: str,
    variant_id: uuid.UUID,
    match_method: str,
    source_account: str = "",
    external_sku: str | None = None,
    external_barcode: str | None = None,
    external_name: str | None = None,
) -> ExternalItemMapping:
    """
    Record a *suggested* mapping. Proposals never confirm themselves and never
    overwrite a confirmed mapping or resurrect a rejected one for the same variant.
    """
    authorize(actor, "mapping.propose")
    if match_method not in MATCH_METHODS:
        raise ValidationFailed(f"Unknown match method: {match_method}")
    get_variant(session, tenant_id=tenant_id, variant_id=variant_id)

    inserted = session.execute(
        insert(ExternalItemMapping)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            source_system=source_system,
            source_account=source_account,
            external_id=external_id,
            variant_id=variant_id,
            status="suggested",
            match_method=match_method,
            external_sku=external_sku,
            external_barcode=external_barcode,
            external_name=external_name,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "source_system", "source_account", "external_id"])
        .returning(ExternalItemMapping.id)
    ).scalar_one_or_none()
    mapping = session.scalars(
        select(ExternalItemMapping)
        .where(
            ExternalItemMapping.tenant_id == tenant_id,
            ExternalItemMapping.source_system == source_system,
            ExternalItemMapping.source_account == source_account,
            ExternalItemMapping.external_id == external_id,
        )
        .with_for_update()
    ).one()

    if inserted is not None:
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="external_mapping.proposed",
            object_type="external_item_mapping",
            object_id=mapping.id,
            after=_mapping_snapshot(mapping),
        )
        return mapping
    if mapping.variant_id == variant_id:
        return mapping  # the same proposal again, whatever its status
    if mapping.status == "confirmed":
        raise StateConflict(
            "This external item is already confirmed to another variant; reject that mapping first",
            details={"mapping_id": str(mapping.id), "variant_id": str(mapping.variant_id)},
        )
    before = _mapping_snapshot(mapping)
    mapping.variant_id = variant_id
    mapping.status = "suggested"
    mapping.match_method = match_method
    mapping.decided_by_user_id = None
    mapping.decided_at = None
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="external_mapping.reproposed",
        object_type="external_item_mapping",
        object_id=mapping.id,
        before=before,
        after=_mapping_snapshot(mapping),
    )
    return mapping


def decide_external_mapping(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    mapping_id: uuid.UUID,
    decision: str,
    expected_variant_id: uuid.UUID,
    reason: str | None = None,
) -> ExternalItemMapping:
    """
    A person confirms or rejects a mapping. Any decision can be reversed by a
    later decision (a confirmed mapping can be rejected; a mistaken rejection can
    be confirmed), and every decision is audited.

    `expected_variant_id` is the variant the person was shown. If the mapping was
    re-proposed to another variant in the meantime (e.g. by an agent), the
    decision is refused, so nobody confirms an item they never saw.
    """
    authorize(actor, "mapping.decide")
    if decision not in ("confirmed", "rejected"):
        raise ValidationFailed("decision must be 'confirmed' or 'rejected'")
    mapping = get_external_mapping(session, tenant_id=tenant_id, mapping_id=mapping_id, for_update=True)
    if mapping.variant_id != expected_variant_id:
        raise StaleVersion(
            "This mapping now points at a different variant than the one you reviewed",
            details={"current_variant_id": str(mapping.variant_id)},
        )
    if mapping.status == decision:
        return mapping
    before = _mapping_snapshot(mapping)
    mapping.status = decision
    mapping.decided_by_user_id = actor.user_id
    mapping.decided_at = _now()
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=f"external_mapping.{decision}",
        object_type="external_item_mapping",
        object_id=mapping.id,
        before=before,
        after=_mapping_snapshot(mapping),
        reason=reason,
    )
    return mapping
