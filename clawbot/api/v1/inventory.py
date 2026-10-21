from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.domain import inventory
from clawbot.schemas.core import MovementCreate, MovementOut, MovementResultOut, PositionOut

router = APIRouter(prefix="/inventory", tags=["inventory"])

_can_move_stock = require_permission("inventory.move")


@router.get("", response_model=list[PositionOut])
def get_inventory(
    location_id: uuid.UUID | None = None,
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[PositionOut]:
    positions = inventory.list_positions(session, tenant_id=ctx.tenant_id, location_id=location_id)
    return [PositionOut.model_validate(p) for p in positions]


@router.post("/movements", response_model=MovementResultOut, status_code=201)
def post_movement(
    body: MovementCreate,
    response: Response,
    idempotency_key: str = Header(min_length=8, max_length=255),
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_move_stock),
) -> MovementResultOut:
    """Record a manual stock change. Retrying with the same Idempotency-Key is safe."""
    result = inventory.record_movement(
        session,
        tenant_id=ctx.tenant_id,
        variant_id=body.variant_id,
        location_id=body.location_id,
        delta=body.delta,
        reason=body.reason,
        source="manual",
        source_event_id=idempotency_key,
        actor=ctx.actor,
        notes=body.notes,
        occurred_at=body.occurred_at,
    )
    if not result.applied:
        response.status_code = 200
    return MovementResultOut(
        applied=result.applied,
        movement=MovementOut.model_validate(result.movement),
        position=PositionOut.model_validate(result.position),
    )


@router.get("/movements", response_model=list[MovementOut])
def get_movements(
    variant_id: uuid.UUID | None = None,
    limit: int = 50,
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[MovementOut]:
    movements = inventory.list_movements(
        session, tenant_id=ctx.tenant_id, variant_id=variant_id, limit=min(max(limit, 1), 500)
    )
    return [MovementOut.model_validate(m) for m in movements]
