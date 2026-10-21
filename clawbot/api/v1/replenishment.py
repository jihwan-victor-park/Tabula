from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.domain.replenishment import codec, service
from clawbot.persistence.models import ReplenishmentLine, ReplenishmentRun, Supplier, Variant

router = APIRouter(tags=["replenishment"])


class PolicyChange(BaseModel):
    changes: dict[str, Any] = Field(description="Fields of the replenishment policy to change; creates a new version")


class ItemSettingBody(BaseModel):
    location_id: uuid.UUID
    safety_stock: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    min_qty: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    max_qty: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    excluded: bool = False


class RunRequest(BaseModel):
    location_id: uuid.UUID
    as_of: AwareDatetime | None = Field(default=None, description="Plan as of this moment (default: now)")


def _line_view(line: ReplenishmentLine, sku: str, supplier: str | None) -> dict[str, Any]:
    inputs = line.inputs
    chosen = next((o for o in inputs["offers"] if o["supplier_item_id"] == str(line.supplier_item_id)), None)
    return {
        "variant_id": str(line.variant_id), "sku": sku, "status": line.status, "needs_review": line.needs_review,
        "order_qty": codec.dumps(line.order_qty), "order_uom": line.order_uom, "base_qty": codec.dumps(line.base_qty),
        "line_cost": None if line.line_cost is None else codec.dumps(line.line_cost), "currency": line.currency,
        "supplier_id": str(line.supplier_id) if line.supplier_id else None, "supplier": supplier,
        "supplier_item_id": str(line.supplier_item_id) if line.supplier_item_id else None,
        "data_as_of": {"stock": inputs["stock_as_of"], "stock_source": inputs["stock_source"],
                       "sales_through": inputs["sales_through"],
                       "price": chosen["price_as_of"] if chosen else None},
        **line.result,
    }


def _run_view(session: Session, run: ReplenishmentRun) -> dict[str, Any]:
    lines = service.run_lines(session, run)
    skus = dict(session.execute(select(Variant.id, Variant.sku).where(Variant.tenant_id == run.tenant_id)).all())
    names = dict(session.execute(select(Supplier.id, Supplier.name).where(Supplier.tenant_id == run.tenant_id)).all())
    order = {"order": 0, "no_supplier": 1, "insufficient_data": 2, "no_order": 3, "excluded": 4}
    lines.sort(key=lambda l: (order[l.status], not l.needs_review, skus.get(l.variant_id, "")))
    return {
        "id": str(run.id), "location_id": str(run.location_id), "status": run.status,
        "cutoff": run.cutoff.isoformat(), "planning_date": run.planning_date.isoformat(),
        "computed_at": run.created_at.isoformat(), "policy_version": run.policy_version,
        "engine_version": run.engine_version, "input_digest": run.input_digest, "policy": run.policy,
        "computed_by": {"kind": run.actor_kind, "user_id": str(run.actor_user_id) if run.actor_user_id else None,
                        "name": run.actor_name},
        "summary": run.summary, "plan_notes": run.plan_notes,
        "lines": [_line_view(l, skus.get(l.variant_id, "?"), names.get(l.supplier_id)) for l in lines],
    }


@router.get("/replenishment/policy")
def get_policy(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    return codec.dumps(service.current_policy(session, tenant_id=ctx.tenant_id))


@router.put("/replenishment/policy")
def put_policy(body: PolicyChange, session: Session = DbSession,
               ctx: TenantContext = Depends(require_permission("replenishment.policy"))) -> dict[str, Any]:
    return codec.dumps(service.set_policy(session, tenant_id=ctx.tenant_id, actor=ctx.actor, changes=body.changes))


@router.put("/replenishment/items/{variant_id}")
def put_item_setting(variant_id: uuid.UUID, body: ItemSettingBody, session: Session = DbSession,
                     ctx: TenantContext = Depends(require_permission("replenishment.policy"))) -> dict[str, Any]:
    row = service.set_item_setting(session, tenant_id=ctx.tenant_id, actor=ctx.actor, variant_id=variant_id,
                                   **body.model_dump())
    return {"variant_id": str(row.variant_id), "location_id": str(row.location_id),
            "safety_stock": codec.dumps(row.safety_stock), "min_qty": codec.dumps(row.min_qty),
            "max_qty": codec.dumps(row.max_qty), "excluded": row.excluded}


@router.post("/replenishment-runs", status_code=201)
def post_run(body: RunRequest, response: Response, session: Session = DbSession,
             ctx: TenantContext = Depends(require_permission("replenishment.run"))) -> dict[str, Any]:
    """Compute a plan. The same data and policy return the existing plan (200)."""
    run, created = service.create_run(session, tenant_id=ctx.tenant_id, actor=ctx.actor,
                                      location_id=body.location_id, as_of=body.as_of)
    if not created:
        response.status_code = 200
    return _run_view(session, run)


@router.get("/replenishment-runs/{run_id}")
def get_run(run_id: uuid.UUID, session: Session = DbSession,
            ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    return _run_view(session, service.get_run(session, tenant_id=ctx.tenant_id, run_id=run_id))


@router.get("/recommendations")
def get_recommendations(location_id: uuid.UUID, session: Session = DbSession,
                        ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """The current plan for a location, with how fresh it is."""
    run = service.current_run(session, tenant_id=ctx.tenant_id, location_id=location_id)
    if run is None:
        return {"location_id": str(location_id), "run": None, "stale": True, "stale_reasons": ["no_plan_yet"]}
    newer = service.newer_data_since(session, run)
    age_hours = (datetime.now(timezone.utc) - run.cutoff).total_seconds() / 3600
    reasons = [f"newer_{n}" for n in newer] + (["older_than_24h"] if age_hours > 24 else [])
    return {"location_id": str(location_id), "stale": bool(reasons), "stale_reasons": reasons,
            "run": _run_view(session, run)}
