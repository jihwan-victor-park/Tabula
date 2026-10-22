from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.api.v1 import fulfilment
from clawbot.domain import data_version, purchasing
from clawbot.persistence.models import (
    AuditEvent, CapturedMessage, Membership, OutboxMessage, PoApproval, PoRevision, PoSendAttempt, PurchaseOrder, User,
)

router = APIRouter(tags=["purchase orders"])


class FromRun(BaseModel):
    run_id: uuid.UUID
    variant_ids: list[uuid.UUID] | None = None
    quantities: dict[uuid.UUID, Decimal] | None = Field(default=None, description="Your quantity per item, in order units")


class RevisionRef(BaseModel):
    revision: int


class LineEdit(BaseModel):
    line_no: int
    order_qty: Decimal = Field(gt=0, max_digits=18, decimal_places=4)


class EditBody(BaseModel):
    revision: int
    lines: list[LineEdit] = Field(default_factory=list)
    remove: list[int] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=300)


class ApproveBody(BaseModel):
    revision: int
    digest: str = Field(min_length=64, max_length=64, description="Digest of the revision you reviewed")


class CancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


def _summary(session: Session, po: PurchaseOrder) -> dict[str, Any]:
    content = purchasing.revision(session, po).content
    return {
        "id": str(po.id), "number": po.number, "status": po.status, "revision": po.current_revision,
        "supplier": content["supplier"]["name"], "ship_to": content["ship_to"]["name"], "currency": po.currency,
        "lines": len(content["lines"]), "estimated_total": content["totals"]["estimated_total"],
        "needs_attention": bool(content["blockers"] or content["notices"]), "ack_status": po.ack_status,
        "sent_at": po.sent_at.isoformat() if po.sent_at else None, **_line_totals(session, po),
        "created_at": po.created_at.isoformat(), "updated_at": po.updated_at.isoformat(),
    }


def _line_totals(session: Session, po: PurchaseOrder) -> dict[str, Any]:
    """For lists: is anything still unconfirmed / expected, and are there open issues."""
    from clawbot.domain import po_progress

    rows = po_progress.lines(session, po)
    if not rows:
        return {"awaiting_reply": False, "expected_lines": 0, "open_issues": 0}
    states = [po_progress.state(l) for l in rows]
    return {"awaiting_reply": any(s.unconfirmed > 0 for s in states),
            "expected_lines": sum(1 for s in states if s.unconfirmed > 0 or s.outstanding > 0),
            "open_issues": po_progress.open_issues(session, po)}


def _detail(session: Session, po: PurchaseOrder) -> dict[str, Any]:
    rev = purchasing.revision(session, po)
    names = dict(session.execute(select(User.id, User.email).join(Membership, Membership.user_id == User.id)
                                 .where(Membership.tenant_id == po.tenant_id)).all())
    approvals = session.scalars(select(PoApproval).where(PoApproval.po_id == po.id).order_by(PoApproval.approved_at)).all()
    attempts = session.scalars(select(PoSendAttempt).where(PoSendAttempt.po_id == po.id)
                               .order_by(PoSendAttempt.created_at)).all()
    captured = session.scalars(select(CapturedMessage).where(CapturedMessage.po_id == po.id)
                               .order_by(CapturedMessage.created_at.desc())).first()
    revisions = session.scalars(select(PoRevision).where(PoRevision.po_id == po.id).order_by(PoRevision.revision)).all()
    events = session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == po.tenant_id,
                                                      AuditEvent.object_type == "purchase_order",
                                                      AuditEvent.object_id == str(po.id))
                             .order_by(AuditEvent.created_at)).all()
    job = session.scalars(select(OutboxMessage).where(
        OutboxMessage.tenant_id == po.tenant_id,
        OutboxMessage.operation_key == f"po:{po.id}:rev:{po.current_revision}:send")).one_or_none()
    current = data_version.current(session, po.tenant_id)
    return {
        **_summary(session, po),
        "digest": rev.digest,
        "content": rev.content,
        "data": {"checked_version": po.data_version, "current_version": current,
                 "changed_since_check": current != po.data_version,
                 "pending_updates": data_version.pending_inputs(session, po.tenant_id)},
        "send_job": None if job is None else {"status": job.status, "attempts": job.attempts, "last_error": job.last_error},
        "approvals": [{"revision": a.revision, "digest": a.digest, "by": names.get(a.approved_by_user_id),
                       "role": a.approved_role, "at": a.approved_at.isoformat()} for a in approvals],
        "send_attempts": [{"revision": a.revision, "mode": a.mode, "recipient": a.recipient, "outcome": a.outcome,
                           "detail": a.detail, "at": a.created_at.isoformat()} for a in attempts],
        "captured_message": None if captured is None else {
            "to": captured.to_address, "subject": captured.subject, "body": captured.body_text,
            "attachment_name": captured.attachment_name, "attachment_csv": captured.attachment_csv,
            "revision": captured.revision, "at": captured.created_at.isoformat(),
            "note": "Captured in Tabula — not delivered to the supplier"},
        "revisions": [{"revision": r.revision, "reason": r.reason, "at": r.created_at.isoformat(),
                       "by": names.get(r.created_by_user_id) or r.created_by_kind,
                       "total": r.content["totals"]["estimated_total"]} for r in revisions],
        "progress": fulfilment.progress(session, po),
        "history": [{"action": e.action, "by": names.get(e.actor_user_id) or e.actor_name or e.actor_kind,
                     "at": e.created_at.isoformat(), "reason": e.reason, "after": e.after} for e in events],
    }


@router.get("/purchase-orders")
def get_pos(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    return [_summary(session, po) for po in purchasing.list_pos(session, tenant_id=ctx.tenant_id)]


@router.get("/purchase-orders/{po_id}")
def get_po(po_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    return _detail(session, purchasing.get_po(session, tenant_id=ctx.tenant_id, po_id=po_id))


@router.post("/purchase-orders/from-run", status_code=201)
def post_from_run(body: FromRun, session: Session = DbSession,
                  ctx: TenantContext = Depends(require_permission("po.draft"))) -> list[dict[str, Any]]:
    """One draft per supplier, ship-to and currency, from the current plan."""
    pos = purchasing.create_drafts_from_run(session, tenant_id=ctx.tenant_id, actor=ctx.actor, run_id=body.run_id,
                                            variant_ids=body.variant_ids, quantities=body.quantities)
    return [_summary(session, po) for po in pos]


@router.patch("/purchase-orders/{po_id}/lines")
def patch_lines(po_id: uuid.UUID, body: EditBody, session: Session = DbSession,
                ctx: TenantContext = Depends(require_permission("po.draft"))) -> dict[str, Any]:
    """Change quantities (order units) or remove lines. Creates a new revision; any approval must be given again."""
    purchasing.edit_quantities(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id,
                               expected_revision=body.revision, quantities={l.line_no: l.order_qty for l in body.lines},
                               remove=body.remove, reason=body.reason)
    return _detail(session, purchasing.get_po(session, tenant_id=ctx.tenant_id, po_id=po_id))


@router.post("/purchase-orders/{po_id}/refresh")
def post_refresh(po_id: uuid.UUID, body: RevisionRef, session: Session = DbSession,
                 ctx: TenantContext = Depends(require_permission("po.draft"))) -> dict[str, Any]:
    purchasing.refresh(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id, expected_revision=body.revision)
    return _detail(session, purchasing.get_po(session, tenant_id=ctx.tenant_id, po_id=po_id))


@router.post("/purchase-orders/{po_id}/submit")
def post_submit(po_id: uuid.UUID, body: RevisionRef, session: Session = DbSession,
                ctx: TenantContext = Depends(require_permission("po.draft"))) -> dict[str, Any]:
    purchasing.submit(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id, expected_revision=body.revision)
    return _detail(session, purchasing.get_po(session, tenant_id=ctx.tenant_id, po_id=po_id))


@router.post("/purchase-orders/{po_id}/approve", status_code=201)
def post_approve(po_id: uuid.UUID, body: ApproveBody, response: Response, session: Session = DbSession,
                 ctx: TenantContext = Depends(require_permission("po.approve"))) -> dict[str, Any]:
    """Owner only. Approves exactly this revision + digest and queues one test send in the same transaction."""
    po, created = purchasing.approve(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id,
                                     expected_revision=body.revision, expected_digest=body.digest)
    if not created:
        response.status_code = 200
    return _detail(session, po)


@router.post("/purchase-orders/{po_id}/cancel")
def post_cancel(po_id: uuid.UUID, body: CancelBody, session: Session = DbSession,
                ctx: TenantContext = Depends(require_permission("po.draft"))) -> dict[str, Any]:
    purchasing.cancel(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id, reason=body.reason)
    return _detail(session, purchasing.get_po(session, tenant_id=ctx.tenant_id, po_id=po_id))
