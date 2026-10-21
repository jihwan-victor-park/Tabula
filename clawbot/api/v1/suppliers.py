from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.domain import suppliers
from clawbot.domain.units import order_quantity_for
from clawbot.policies.permissions import allowed_roles
from clawbot.schemas.suppliers import (
    ApprovalCheckOut,
    ClosureCreate,
    ClosureOut,
    ContactCreate,
    ContactOut,
    CoverageOut,
    CoverageSet,
    ItemMappingDecision,
    OfferOut,
    OrderQuantityOut,
    PriceCreate,
    PriceOut,
    SupplierCreate,
    SupplierItemCreate,
    SupplierItemOut,
    SupplierItemUpdate,
    SupplierOut,
    SupplierStatusChange,
    SupplierUpdate,
)

router = APIRouter(tags=["suppliers"])

_can_manage_suppliers = require_permission("supplier.edit")
_can_verify_contacts = require_permission("supplier.verify_contact")
_can_edit_items = require_permission("supplier_item.edit")
_can_decide_mapping = require_permission("mapping.decide")
_can_record_prices = require_permission("price.record")


def offer_out(o: suppliers.Offer) -> OfferOut:
    return OfferOut(
        supplier_item_id=o.supplier_item.id,
        supplier_id=o.supplier.id,
        supplier_name=o.supplier.name,
        supplier_sku=o.supplier_item.supplier_sku,
        order_uom=o.supplier_item.order_uom,
        units_per_order_uom=o.supplier_item.units_per_order_uom,
        order_multiple=o.supplier_item.order_multiple,
        min_order_qty=o.supplier_item.min_order_qty,
        lead_time_days=o.lead_time_days,
        price=PriceOut.model_validate(o.price) if o.price else None,
        unit_cost_per_base=o.unit_cost_per_base,
        eligible=o.eligible,
        blockers=list(o.blockers),
    )


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


@router.get("/suppliers", response_model=list[SupplierOut])
def get_suppliers(
    status: Literal["candidate", "approved", "suspended", "archived"] | None = None,
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[SupplierOut]:
    return [SupplierOut.model_validate(s) for s in suppliers.list_suppliers(session, tenant_id=ctx.tenant_id, status=status)]


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def post_supplier(
    body: SupplierCreate, session: Session = DbSession, ctx: TenantContext = Depends(_can_manage_suppliers)
) -> SupplierOut:
    """New suppliers always start as `candidate`."""
    fields = body.model_dump(exclude_none=True, exclude={"name"})
    supplier = suppliers.create_supplier(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, name=body.name, **fields
    )
    return SupplierOut.model_validate(supplier)


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(
    supplier_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> SupplierOut:
    return SupplierOut.model_validate(suppliers.get_supplier(session, tenant_id=ctx.tenant_id, supplier_id=supplier_id))


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def patch_supplier(
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_manage_suppliers),
) -> SupplierOut:
    """Changing ordering channel, portal or account number sends an approved supplier back to `candidate`."""
    changes = body.model_dump(exclude_unset=True, exclude={"version", "reason"})
    supplier = suppliers.update_supplier(
        session,
        tenant_id=ctx.tenant_id,
        actor=ctx.actor,
        supplier_id=supplier_id,
        expected_version=body.version,
        changes=changes,
        reason=body.reason,
    )
    return SupplierOut.model_validate(supplier)


@router.get("/suppliers/{supplier_id}/approval-check", response_model=ApprovalCheckOut)
def get_approval_check(
    supplier_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> ApprovalCheckOut:
    supplier = suppliers.get_supplier(session, tenant_id=ctx.tenant_id, supplier_id=supplier_id)
    blockers = suppliers.approval_blockers(session, supplier)
    return ApprovalCheckOut(approvable=not blockers, blockers=blockers)


@router.post("/suppliers/{supplier_id}/status", response_model=SupplierOut)
def post_supplier_status(
    supplier_id: uuid.UUID,
    body: SupplierStatusChange,
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> SupplierOut:
    permission = "supplier.approve" if body.status == "approved" else "supplier.edit"
    if ctx.role not in allowed_roles(permission):
        raise HTTPException(status_code=403, detail=f"Role '{ctx.role}' may not {permission}")
    supplier = suppliers.set_supplier_status(
        session,
        tenant_id=ctx.tenant_id,
        actor=ctx.actor,
        supplier_id=supplier_id,
        expected_version=body.version,
        status=body.status,
        reason=body.reason,
    )
    return SupplierOut.model_validate(supplier)


# ---------------------------------------------------------------------------
# Contacts, coverage, closures
# ---------------------------------------------------------------------------


@router.get("/suppliers/{supplier_id}/contacts", response_model=list[ContactOut])
def get_contacts(
    supplier_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> list[ContactOut]:
    contacts = suppliers.list_contacts(session, tenant_id=ctx.tenant_id, supplier_id=supplier_id)
    return [ContactOut.model_validate(c) for c in contacts]


@router.post("/suppliers/{supplier_id}/contacts", response_model=ContactOut, status_code=201)
def post_contact(
    supplier_id: uuid.UUID,
    body: ContactCreate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_manage_suppliers),
) -> ContactOut:
    contact = suppliers.add_contact(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, supplier_id=supplier_id, **body.model_dump()
    )
    return ContactOut.model_validate(contact)


@router.post("/suppliers/{supplier_id}/contacts/{contact_id}/verify", response_model=ContactOut)
def post_verify_contact(
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_verify_contacts),
) -> ContactOut:
    """The merchant confirms this is the supplier's real ordering address."""
    contact = suppliers.verify_contact(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, supplier_id=supplier_id, contact_id=contact_id
    )
    return ContactOut.model_validate(contact)


@router.delete("/suppliers/{supplier_id}/contacts/{contact_id}", status_code=204)
def delete_contact(
    supplier_id: uuid.UUID,
    contact_id: uuid.UUID,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_manage_suppliers),
) -> Response:
    suppliers.remove_contact(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, supplier_id=supplier_id, contact_id=contact_id
    )
    return Response(status_code=204)


@router.get("/suppliers/{supplier_id}/coverage", response_model=CoverageOut)
def get_coverage(
    supplier_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> CoverageOut:
    suppliers.get_supplier(session, tenant_id=ctx.tenant_id, supplier_id=supplier_id)
    return CoverageOut(location_ids=suppliers.coverage(session, tenant_id=ctx.tenant_id, supplier_id=supplier_id))


@router.put("/suppliers/{supplier_id}/coverage", response_model=CoverageOut)
def put_coverage(
    supplier_id: uuid.UUID,
    body: CoverageSet,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_manage_suppliers),
) -> CoverageOut:
    """Replace the set of store locations this supplier delivers to."""
    ids = suppliers.set_coverage(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, supplier_id=supplier_id, location_ids=body.location_ids
    )
    return CoverageOut(location_ids=ids)


@router.get("/suppliers/{supplier_id}/closures", response_model=list[ClosureOut])
def get_closures(
    supplier_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> list[ClosureOut]:
    closures = suppliers.list_closures(session, tenant_id=ctx.tenant_id, supplier_id=supplier_id)
    return [ClosureOut.model_validate(c) for c in closures]


@router.post("/suppliers/{supplier_id}/closures", response_model=ClosureOut, status_code=201)
def post_closure(
    supplier_id: uuid.UUID,
    body: ClosureCreate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_manage_suppliers),
) -> ClosureOut:
    closure = suppliers.add_closure(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, supplier_id=supplier_id, **body.model_dump()
    )
    return ClosureOut.model_validate(closure)


# ---------------------------------------------------------------------------
# Supplier items and prices
# ---------------------------------------------------------------------------


@router.get("/suppliers/{supplier_id}/items", response_model=list[SupplierItemOut])
def get_supplier_items(
    supplier_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> list[SupplierItemOut]:
    items = suppliers.list_supplier_items(session, tenant_id=ctx.tenant_id, supplier_id=supplier_id)
    return [SupplierItemOut.model_validate(i) for i in items]


@router.post("/suppliers/{supplier_id}/items", response_model=SupplierItemOut, status_code=201)
def post_supplier_item(
    supplier_id: uuid.UUID,
    body: SupplierItemCreate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_edit_items),
) -> SupplierItemOut:
    item = suppliers.create_supplier_item(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, supplier_id=supplier_id, **body.model_dump()
    )
    return SupplierItemOut.model_validate(item)


@router.get("/supplier-items/{item_id}", response_model=SupplierItemOut)
def get_supplier_item(
    item_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> SupplierItemOut:
    return SupplierItemOut.model_validate(suppliers.get_supplier_item(session, tenant_id=ctx.tenant_id, item_id=item_id))


@router.patch("/supplier-items/{item_id}", response_model=SupplierItemOut)
def patch_supplier_item(
    item_id: uuid.UUID,
    body: SupplierItemUpdate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_edit_items),
) -> SupplierItemOut:
    """Changing order unit or pack size un-confirms the mapping and retires the current price."""
    changes = body.model_dump(exclude_unset=True, exclude={"version", "reason"})
    item = suppliers.update_supplier_item(
        session,
        tenant_id=ctx.tenant_id,
        actor=ctx.actor,
        item_id=item_id,
        expected_version=body.version,
        changes=changes,
        reason=body.reason,
    )
    return SupplierItemOut.model_validate(item)


@router.post("/supplier-items/{item_id}/mapping-decision", response_model=SupplierItemOut)
def post_item_mapping_decision(
    item_id: uuid.UUID,
    body: ItemMappingDecision,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_decide_mapping),
) -> SupplierItemOut:
    item = suppliers.decide_item_mapping(
        session,
        tenant_id=ctx.tenant_id,
        actor=ctx.actor,
        item_id=item_id,
        expected_version=body.version,
        decision=body.decision,
        variant_id=body.variant_id,
        reason=body.reason,
    )
    return SupplierItemOut.model_validate(item)


@router.get("/supplier-items/{item_id}/prices", response_model=list[PriceOut])
def get_prices(
    item_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> list[PriceOut]:
    return [PriceOut.model_validate(p) for p in suppliers.price_history(session, tenant_id=ctx.tenant_id, item_id=item_id)]


@router.post("/supplier-items/{item_id}/prices", response_model=PriceOut, status_code=201)
def post_price(
    item_id: uuid.UUID,
    body: PriceCreate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_record_prices),
) -> PriceOut:
    price = suppliers.record_price(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, item_id=item_id, **body.model_dump()
    )
    return PriceOut.model_validate(price)


@router.get("/supplier-items/{item_id}/order-quantity", response_model=OrderQuantityOut)
def get_order_quantity(
    item_id: uuid.UUID,
    base_qty: Decimal = Query(ge=0, max_digits=18, decimal_places=4, description="Quantity needed, in base units"),
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> OrderQuantityOut:
    """Preview: how many order units cover `base_qty`, after pack, multiple and MOQ rounding."""
    item = suppliers.get_supplier_item(session, tenant_id=ctx.tenant_id, item_id=item_id)
    q = order_quantity_for(
        base_qty,
        units_per_order_uom=item.units_per_order_uom,
        order_uom=item.order_uom,
        order_multiple=item.order_multiple,
        min_order_qty=item.min_order_qty,
    )
    return OrderQuantityOut(**{**q.__dict__, "constraints_applied": list(q.constraints_applied)})
