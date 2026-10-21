"""After sending (CP7/CP8): supplier replies, owner decisions on changes, receiving, damage issues."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, require_permission
from clawbot.domain import po_progress, purchasing, receiving, supplier_replies
from clawbot.persistence.models import PurchaseOrder, Receipt, ReceiptIssue, ReceiptLine, SupplierReply

router = APIRouter(tags=["supplier replies and receiving"])


def _n(d: Decimal | None) -> str | None:
    return None if d is None else f"{d.normalize():f}"


def progress(session: Session, po: PurchaseOrder) -> dict[str, Any] | None:
    """Per-line ordered / confirmed / received / outstanding, replies, receipts and issues of a sent order."""
    rows = po_progress.lines(session, po)
    if not rows:
        return None
    pos_pending = receiving.pos_unconfirmed(session, tenant_id=po.tenant_id, location_id=po.location_id)
    lines = []
    for l in rows:
        st = po_progress.state(l)
        lines.append({
            "line_no": l.line_no, "sku": l.sku, "supplier_sku": l.supplier_sku, "order_uom": l.order_uom,
            "units_per_order_uom": _n(l.units_per_order_uom), "unit_price": _n(l.unit_price),
            "ordered": _n(l.ordered_qty), "confirmed": _n(l.confirmed_qty), "rejected": _n(l.rejected_qty),
            "cancelled": _n(l.cancelled_qty), "received": _n(l.received_qty), "damaged": _n(l.damaged_qty),
            "sellable_received": _n(st.sellable_received), "replacement": _n(l.replacement_qty),
            "unconfirmed": _n(st.unconfirmed), "outstanding": _n(st.outstanding),
            "eta": l.eta.isoformat() if l.eta else None, "proposal": l.proposal, "replaces_line_no": l.replaces_line_no,
            "pos_pending": pos_pending.get(l.variant_id, []),
        })
    replies = session.scalars(select(SupplierReply).where(SupplierReply.tenant_id == po.tenant_id,
                                                          SupplierReply.po_id == po.id)
                              .order_by(SupplierReply.replied_at.desc(), SupplierReply.created_at.desc())).all()
    receipts = session.scalars(select(Receipt).where(Receipt.tenant_id == po.tenant_id, Receipt.po_id == po.id)
                               .order_by(Receipt.received_at)).all()
    receipt_lines = {r.id: [] for r in receipts}
    for rl in session.scalars(select(ReceiptLine).where(ReceiptLine.tenant_id == po.tenant_id,
                                                        ReceiptLine.receipt_id.in_(list(receipt_lines)))):
        receipt_lines[rl.receipt_id].append(rl)
    line_no = {l.id: l.line_no for l in rows}
    issues = session.scalars(select(ReceiptIssue).where(ReceiptIssue.tenant_id == po.tenant_id, ReceiptIssue.po_id == po.id)
                             .order_by(ReceiptIssue.created_at)).all()
    return {
        "sent_at": po.sent_at.isoformat() if po.sent_at else None, "ack_status": po.ack_status,
        "last_reply_at": po.last_reply_at.isoformat() if po.last_reply_at else None,
        "lines": lines,
        "replies": [{"id": str(r.id), "source": r.source, "file_name": r.file_name,
                     "status": "stale" if r.status == "pending_review" and po.last_reply_at and r.replied_at < po.last_reply_at
                     else r.status,
                     "replied_at": r.replied_at.isoformat(), "recorded_at": r.created_at.isoformat(),
                     "raw_text": r.raw_text, "parsed": r.parsed, "applied": r.applied} for r in replies],
        "receipts": [{"id": str(r.id), "receipt_key": r.receipt_key, "received_at": r.received_at.isoformat(),
                      "notes": r.notes, "lines": [
                          {"id": str(rl.id), "line_no": line_no.get(rl.po_line_id), "arrived": _n(rl.arrived_qty),
                           "damaged": _n(rl.damaged_qty), "sellable_units": _n(rl.sellable_base_qty),
                           "pos_status": rl.pos_status} for rl in receipt_lines[r.id]]} for r in receipts],
        "issues": [{"id": str(i.id), "line_no": line_no.get(i.po_line_id), "kind": i.kind, "qty": _n(i.qty),
                    "status": i.status, "resolution_qty": _n(i.resolution_qty),
                    "resolution_eta": i.resolution_eta.isoformat() if i.resolution_eta else None, "note": i.note}
                   for i in issues],
    }


def _detail(session: Session, po_id: uuid.UUID, tenant_id: uuid.UUID) -> dict[str, Any]:
    from clawbot.api.v1.purchasing import _detail as po_detail

    return po_detail(session, purchasing.get_po(session, tenant_id=tenant_id, po_id=po_id))


# ---------------------------------------------------------------- replies


class ReplyBody(BaseModel):
    source: Literal["paste", "mock"]
    text: str | None = Field(default=None, max_length=200_000)
    scenario: Literal[supplier_replies.MOCK_SCENARIOS] | None = None  # type: ignore[valid-type]
    replied_at: datetime | None = Field(default=None, description="When the supplier sent it, if the text has no Date line")


@router.post("/purchase-orders/{po_id}/replies", status_code=201)
def post_reply(po_id: uuid.UUID, body: ReplyBody, response: Response, session: Session = DbSession,
               ctx: TenantContext = Depends(require_permission("po.reply"))) -> dict[str, Any]:
    """Record a reply (pasted or, in capture mode, a generated mock). The same text again returns the same reply (200)."""
    reply, created = supplier_replies.record(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id,
                                             source=body.source, text=body.text, replied_at=body.replied_at,
                                             scenario=body.scenario)
    if not created:
        response.status_code = 200
    return {"reply_id": str(reply.id), "created": created, "order": _detail(session, po_id, ctx.tenant_id)}


@router.post("/purchase-orders/{po_id}/replies/upload", status_code=201)
async def post_reply_upload(po_id: uuid.UUID, response: Response, file: UploadFile = File(...),
                            replied_at: datetime | None = Form(None), session: Session = DbSession,
                            ctx: TenantContext = Depends(require_permission("po.reply"))) -> dict[str, Any]:
    """A reply as a file: .txt, .eml (its Date header is used) or a .csv confirmation sheet."""
    data = await file.read(supplier_replies.MAX_REPLY_BYTES + 1)
    reply, created = supplier_replies.record(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id,
                                             source="upload", file_name=file.filename or "reply.txt", data=data,
                                             replied_at=replied_at)
    if not created:
        response.status_code = 200
    return {"reply_id": str(reply.id), "created": created, "order": _detail(session, po_id, ctx.tenant_id)}


class Change(BaseModel):
    kind: Literal["price", "pack", "substitute", "qty_increase"]
    unit_price: Decimal | None = None
    units_per_order_uom: Decimal | None = None
    substitute_sku: str | None = Field(default=None, max_length=120)
    qty: Decimal | None = None


class Decision(BaseModel):
    line_no: int
    action: Literal["accept", "partial", "reject", "eta", "cancel_remaining", "change", "none", "unclear"]
    confirmed_qty: Decimal | None = None
    eta: date | None = None
    backorder: bool = False
    change: Change | None = None


class ApplyBody(BaseModel):
    decisions: list[Decision]


@router.post("/supplier-replies/{reply_id}/apply")
def post_apply(reply_id: uuid.UUID, body: ApplyBody, session: Session = DbSession,
               ctx: TenantContext = Depends(require_permission("po.reply"))) -> dict[str, Any]:
    """Apply what a person decided the reply says. Repeating the same review changes nothing."""
    decisions = [{"line_no": d.line_no, "action": d.action,
                  "confirmed_qty": _n(d.confirmed_qty), "eta": d.eta.isoformat() if d.eta else None,
                  "backorder": d.backorder,
                  "change": None if d.change is None else {k: (_n(v) if isinstance(v, Decimal) else v)
                                                           for k, v in d.change.model_dump().items() if v is not None}}
                 for d in body.decisions]
    reply = supplier_replies.apply(session, tenant_id=ctx.tenant_id, actor=ctx.actor, reply_id=reply_id, decisions=decisions)
    return _detail(session, reply.po_id, ctx.tenant_id)


class DismissBody(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


@router.post("/supplier-replies/{reply_id}/dismiss")
def post_dismiss(reply_id: uuid.UUID, body: DismissBody, session: Session = DbSession,
                 ctx: TenantContext = Depends(require_permission("po.reply"))) -> dict[str, Any]:
    reply = supplier_replies.dismiss(session, tenant_id=ctx.tenant_id, actor=ctx.actor, reply_id=reply_id, reason=body.reason)
    return _detail(session, reply.po_id, ctx.tenant_id)


class ProposalBody(BaseModel):
    decision: Literal["accept", "decline"]
    proposal_digest: str = Field(min_length=64, max_length=64)


@router.post("/purchase-orders/{po_id}/lines/{line_no}/proposal")
def post_proposal(po_id: uuid.UUID, line_no: int, body: ProposalBody, session: Session = DbSession,
                  ctx: TenantContext = Depends(require_permission("po.approve"))) -> dict[str, Any]:
    """Owner only: accept or decline a supplier's change to price, product, pack or quantity."""
    supplier_replies.decide_proposal(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id, line_no=line_no,
                                     decision=body.decision, proposal_digest=body.proposal_digest)
    return _detail(session, po_id, ctx.tenant_id)


class NotDeliveredBody(BaseModel):
    outcome: Literal["not_received"]
    note: str = Field(min_length=1, max_length=500)


@router.post("/purchase-orders/{po_id}/delivery-outcome")
def post_delivery_outcome(po_id: uuid.UUID, body: NotDeliveredBody, session: Session = DbSession,
                          ctx: TenantContext = Depends(require_permission("po.approve"))) -> dict[str, Any]:
    """Owner only, for delivery_unknown: the supplier confirmed it never arrived. (If it did arrive, record their reply.)"""
    po_progress.resolve_not_delivered(session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id, note=body.note)
    return _detail(session, po_id, ctx.tenant_id)


# ---------------------------------------------------------------- receiving


class ReceiveLineBody(BaseModel):
    line_no: int
    arrived_qty: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    damaged_qty: Decimal = Field(default=Decimal(0), ge=0, max_digits=18, decimal_places=4)


class ReceiptBody(BaseModel):
    receipt_key: str = Field(min_length=1, max_length=100, description="Generated when the form opens; a resubmit reuses it")
    received_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)
    lines: list[ReceiveLineBody] = Field(min_length=1)


@router.post("/purchase-orders/{po_id}/receipts", status_code=201)
def post_receipt(po_id: uuid.UUID, body: ReceiptBody, response: Response, session: Session = DbSession,
                 ctx: TenantContext = Depends(require_permission("receiving.record"))) -> dict[str, Any]:
    receipt, created = receiving.record_receipt(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, po_id=po_id, receipt_key=body.receipt_key,
        received_at=body.received_at, notes=body.notes,
        lines=[receiving.ReceiveLine(l.line_no, l.arrived_qty, l.damaged_qty) for l in body.lines])
    if not created:
        response.status_code = 200
    return {"receipt_id": str(receipt.id), "created": created, "order": _detail(session, po_id, ctx.tenant_id)}


class ResolveBody(BaseModel):
    resolution: Literal["replacement_confirmed", "credit_confirmed", "written_off"]
    qty: Decimal | None = Field(default=None, gt=0)
    eta: date | None = None
    note: str | None = Field(default=None, max_length=500)


@router.post("/receipt-issues/{issue_id}/resolve")
def post_resolve(issue_id: uuid.UUID, body: ResolveBody, session: Session = DbSession,
                 ctx: TenantContext = Depends(require_permission("receiving.resolve"))) -> dict[str, Any]:
    issue = receiving.resolve_issue(session, tenant_id=ctx.tenant_id, actor=ctx.actor, issue_id=issue_id,
                                    resolution=body.resolution, qty=body.qty, eta=body.eta, note=body.note)
    return _detail(session, issue.po_id, ctx.tenant_id)


@router.post("/receipt-lines/{line_id}/pos-entered")
def post_pos_entered(line_id: uuid.UUID, session: Session = DbSession,
                     ctx: TenantContext = Depends(require_permission("receiving.record"))) -> dict[str, Any]:
    """The person entered this receipt in the POS; cleared when a newer POS stock reading arrives."""
    rl = receiving.report_entered_in_pos(session, tenant_id=ctx.tenant_id, actor=ctx.actor, receipt_line_id=line_id)
    receipt = session.get(Receipt, rl.receipt_id)
    return _detail(session, receipt.po_id, ctx.tenant_id)
