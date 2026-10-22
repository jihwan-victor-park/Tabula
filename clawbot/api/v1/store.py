"""The store owner's screens: stock overview, item history, sales analysis, data readiness, scanning."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.domain import po_progress, stock_actions, stock_view, tenancy
from clawbot.persistence.models import PO_SENT_STATUSES, PoLine, PurchaseOrder

router = APIRouter(tags=["store"])


@router.get("/stock/overview")
def get_overview(location_id: uuid.UUID, session: Session = DbSession,
                 ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Every item: sellable stock (with how fresh it is), incoming, daily sales, days of cover, expected stockout."""
    return stock_view.overview(session, tenant_id=ctx.tenant_id, location_id=location_id)


@router.get("/items/{variant_id}/history")
def get_history(variant_id: uuid.UUID, location_id: uuid.UUID, days: int = Query(60, ge=7, le=365),
                session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    return stock_view.item_history(session, tenant_id=ctx.tenant_id, location_id=location_id, variant_id=variant_id, days=days)


@router.get("/analytics")
def get_analytics(location_id: uuid.UUID, days: int = Query(28, ge=7, le=180), session: Session = DbSession,
                  ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    return stock_view.analytics(session, tenant_id=ctx.tenant_id, location_id=location_id, days=days)


@router.get("/readiness")
def get_readiness(location_id: uuid.UUID, session: Session = DbSession,
                  ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    return stock_view.readiness(session, tenant_id=ctx.tenant_id, location_id=location_id)


@router.get("/items/lookup")
def get_lookup(code: str = Query(min_length=1, max_length=64), location_id: uuid.UUID | None = None,
               session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """A scanned or typed barcode / SKU → the item (or `found: false` so the app can offer to link or create one)."""
    v = stock_actions.lookup(session, tenant_id=ctx.tenant_id, code=code)
    if v is None:
        return {"found": False, "code": code}
    out: dict[str, Any] = {"found": True, "variant_id": str(v.id), "sku": v.sku, "name": v.name, "barcode": v.barcode,
                           "status": v.status, "version": v.version}
    if location_id is not None:
        location = tenancy.get_location(session, tenant_id=ctx.tenant_id, location_id=location_id)
        row = next((r for r in stock_view.overview(session, tenant_id=ctx.tenant_id, location_id=location_id)["items"]
                    if r["variant_id"] == str(v.id)), None)
        expected = []
        for po, line in session.execute(select(PurchaseOrder, PoLine).join(PoLine, (PoLine.tenant_id == PurchaseOrder.tenant_id) & (
                PoLine.po_id == PurchaseOrder.id)).where(
                PurchaseOrder.tenant_id == ctx.tenant_id, PurchaseOrder.location_id == location_id,
                PurchaseOrder.status.in_(PO_SENT_STATUSES), PoLine.variant_id == v.id)):
            st = po_progress.state(line)
            if st.outstanding + st.unconfirmed > 0:
                expected.append({"po_id": str(po.id), "number": po.number, "line_no": line.line_no,
                                 "expected": f"{(st.outstanding + st.unconfirmed).normalize():f}", "unit": line.order_uom})
        out.update(stock=row, stock_owner=location.inventory_write_owner, expected_orders=expected)
    return out


class StockAction(BaseModel):
    location_id: uuid.UUID
    variant_id: uuid.UUID
    action: Literal["stock_in", "used", "damaged", "count"]
    qty: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    note: str | None = Field(default=None, max_length=300)
    request_key: str = Field(min_length=8, max_length=100, description="Generated per action; a resubmit is the same change")


@router.post("/stock-actions", status_code=201)
def post_action(body: StockAction, session: Session = DbSession,
                ctx: TenantContext = Depends(require_permission("inventory.move"))) -> dict[str, Any]:
    m = stock_actions.apply(session, tenant_id=ctx.tenant_id, actor=ctx.actor, location_id=body.location_id,
                            variant_id=body.variant_id, action=body.action, qty=body.qty, note=body.note,
                            request_key=body.request_key)
    return {"movement_id": str(m.id), "delta": f"{m.delta.normalize():f}"}


class UndoBody(BaseModel):
    note: str | None = Field(default=None, max_length=300)


@router.post("/stock-actions/{movement_id}/undo", status_code=201)
def post_undo(movement_id: uuid.UUID, body: UndoBody, session: Session = DbSession,
              ctx: TenantContext = Depends(require_permission("inventory.move"))) -> dict[str, Any]:
    m = stock_actions.undo(session, tenant_id=ctx.tenant_id, actor=ctx.actor, movement_id=movement_id, note=body.note)
    return {"movement_id": str(m.id), "delta": f"{m.delta.normalize():f}"}


@router.get("/stock-actions")
def get_actions(location_id: uuid.UUID, session: Session = DbSession,
                ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    return stock_actions.recent(session, tenant_id=ctx.tenant_id, location_id=location_id)
