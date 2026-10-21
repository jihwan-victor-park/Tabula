from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, require_permission
from clawbot.persistence.models import AuditEvent
from clawbot.schemas.core import AuditEventOut

router = APIRouter(tags=["audit"])


@router.get("/audit-events", response_model=list[AuditEventOut])
def get_audit_events(
    object_type: str | None = None,
    limit: int = 100,
    session: Session = DbSession,
    ctx: TenantContext = Depends(require_permission("audit.read")),
) -> list[AuditEventOut]:
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == ctx.tenant_id)
    if object_type:
        stmt = stmt.where(AuditEvent.object_type == object_type)
    stmt = stmt.order_by(AuditEvent.created_at.desc()).limit(min(max(limit, 1), 500))
    return [AuditEventOut.model_validate(e) for e in session.scalars(stmt)]
