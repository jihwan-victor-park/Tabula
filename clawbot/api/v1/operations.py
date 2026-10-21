"""Store-level operations: what needs attention, and decisions about export orders vs Tabula POs."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.domain import attention, open_orders, tenancy
from clawbot.persistence.models import ExternalOpenOrderLine, PurchaseOrder, Supplier, Variant

router = APIRouter(tags=["operations"])


@router.get("/attention")
def get_attention(location_id: uuid.UUID, session: Session = DbSession,
                  ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    """Everything waiting on a person at this store, most urgent first, each with why and where to resolve it."""
    tenancy.get_location(session, tenant_id=ctx.tenant_id, location_id=location_id)
    return attention.for_location(session, tenant_id=ctx.tenant_id, location_id=location_id)


@router.get("/open-order-links")
def get_links(location_id: uuid.UUID, session: Session = DbSession,
              ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    """Each order number in open-order exports and whether it is one of Tabula's POs (and why)."""
    links = open_orders.links(session, tenant_id=ctx.tenant_id, location_id=location_id)
    names = dict(session.execute(select(Supplier.id, Supplier.name).where(Supplier.tenant_id == ctx.tenant_id)).all())
    skus = dict(session.execute(select(Variant.id, Variant.sku).where(Variant.tenant_id == ctx.tenant_id)).all())
    pos = {po.number: po for po in session.scalars(select(PurchaseOrder).where(
        PurchaseOrder.tenant_id == ctx.tenant_id, PurchaseOrder.location_id == location_id))}
    out = []
    for (supplier_id, number), link in sorted(links.items(), key=lambda kv: (kv[1].status != "suggested", kv[0][1])):
        lines = session.scalars(select(ExternalOpenOrderLine).where(
            ExternalOpenOrderLine.tenant_id == ctx.tenant_id, ExternalOpenOrderLine.location_id == location_id,
            ExternalOpenOrderLine.supplier_id == supplier_id, ExternalOpenOrderLine.external_po_number == number)).all()
        out.append({
            "supplier_id": str(supplier_id), "supplier": names.get(supplier_id), "external_po_number": number,
            "status": link.status, "po_number": link.po_number, "candidates": [
                {"po_id": str(pos[c].id), "number": c, "status": pos[c].status} for c in link.candidates if c in pos],
            "lines": [{"sku": skus.get(l.variant_id), "outstanding": f"{l.outstanding_qty.normalize():f}",
                       "confirmed": l.supplier_confirmed} for l in lines],
        })
    return out


class LinkBody(BaseModel):
    location_id: uuid.UUID
    supplier_id: uuid.UUID
    external_po_number: str = Field(min_length=1, max_length=120)
    decision: Literal["same_order", "different_order"]
    po_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=300)


@router.post("/open-order-links")
def post_link(body: LinkBody, session: Session = DbSession,
              ctx: TenantContext = Depends(require_permission("po.draft"))) -> dict[str, Any]:
    link = open_orders.decide_link(session, tenant_id=ctx.tenant_id, actor=ctx.actor, location_id=body.location_id,
                                   supplier_id=body.supplier_id, external_po_number=body.external_po_number,
                                   decision=body.decision, po_id=body.po_id, note=body.note)
    return {"id": str(link.id), "decision": link.decision}
