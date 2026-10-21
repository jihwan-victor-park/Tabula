"""
What happened to an order after it was handed to the supplier (spec 10).

`po_lines` are written once, from the approved revision, when the order is handed
over (captured, or possibly delivered by a real transport). From then on only a
supplier reply a person reviewed (supplier_replies) and receipts (receiving)
change them. Quantities are in order units.

How a line counts in the plan (gather.py):

  unconfirmed — the supplier has not said yes or no: held against reordering,
                never projected as arriving.
  outstanding — confirmed and not yet arrived (incl. confirmed replacements):
                projected to arrive on the ETA.
  rejected / cancelled — no longer expected; the plan recomputes without them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clawbot.domain import audit, data_version
from clawbot.domain.errors import StateConflict, ValidationFailed
from clawbot.persistence.models import PoLine, PurchaseOrder, ReceiptIssue
from clawbot.policies.permissions import Actor, authorize

ZERO = Decimal(0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LineState:
    unconfirmed: Decimal
    outstanding: Decimal
    sellable_received: Decimal
    answered: bool


def state(line: PoLine) -> LineState:
    if line.confirmed_qty is None:
        # No answer on the order itself, but a replacement the supplier confirmed (for damage) is expected.
        remaining = max(line.ordered_qty + line.replacement_qty - line.rejected_qty - line.cancelled_qty
                        - line.received_qty, ZERO)
        outstanding = min(line.replacement_qty, remaining)
        unconfirmed = remaining - outstanding
    else:
        expected = line.confirmed_qty + line.replacement_qty - line.cancelled_qty
        # Goods beyond what was confirmed (e.g. a backordered remainder that turned up) settle the unconfirmed part.
        beyond = max(line.received_qty - expected, ZERO)
        unconfirmed = max(line.ordered_qty - line.confirmed_qty - line.rejected_qty - beyond, ZERO)
        outstanding = max(expected - line.received_qty, ZERO)
    answered = line.confirmed_qty is not None or line.rejected_qty >= line.ordered_qty
    return LineState(unconfirmed, outstanding, line.received_qty - line.damaged_qty, answered)


def lines(session: Session, po: PurchaseOrder, *, for_update: bool = False) -> list[PoLine]:
    stmt = select(PoLine).where(PoLine.tenant_id == po.tenant_id, PoLine.po_id == po.id).order_by(PoLine.line_no)
    if for_update:
        stmt = stmt.with_for_update()
    return list(session.scalars(stmt))


def hand_over(session: Session, po: PurchaseOrder, content: dict[str, Any], *, status: str) -> None:
    """The approved revision left Tabula (captured, or a transport may have delivered it): record what was ordered."""
    existing = lines(session, po, for_update=True)
    if existing and existing[0].revision != po.current_revision:
        # An earlier revision that never reached the supplier (resolved as not delivered); nothing was received on it.
        if any(l.received_qty > 0 or l.confirmed_qty is not None for l in existing):
            raise StateConflict("The supplier already acted on an earlier revision of this order")
        for l in existing:
            session.delete(l)
        session.flush()
        existing = []
    if not existing:
        for l in content["lines"]:
            session.add(PoLine(
                tenant_id=po.tenant_id, po_id=po.id, line_no=l["line_no"], revision=po.current_revision,
                variant_id=uuid.UUID(l["variant_id"]), supplier_item_id=uuid.UUID(l["supplier_item_id"]),
                sku=l["sku"], supplier_sku=l["supplier_sku"], order_uom=l["order_uom"],
                units_per_order_uom=Decimal(l["units_per_order_uom"]), unit_price=Decimal(l["unit_price"]),
                ordered_qty=Decimal(l["order_qty"]), rejected_qty=ZERO, cancelled_qty=ZERO, received_qty=ZERO,
                damaged_qty=ZERO, replacement_qty=ZERO))
    po.status, po.sent_at, po.ack_status, po.updated_at = status, po.sent_at or _now(), "pending", _now()
    data_version.bump(session, po.tenant_id)  # the plan now holds these quantities


def open_issues(session: Session, po: PurchaseOrder) -> int:
    return session.scalar(select(func.count()).select_from(ReceiptIssue).where(
        ReceiptIssue.tenant_id == po.tenant_id, ReceiptIssue.po_id == po.id, ReceiptIssue.status == "open")) or 0


def recompute(session: Session, po: PurchaseOrder) -> None:
    """Derive acknowledgement and order status from the lines (after a reply, decision or receipt)."""
    rows = lines(session, po)
    states = [state(l) for l in rows]
    if any(l.proposal for l in rows):
        ack = "counteroffer"
    elif not any(s.answered for s in states):
        ack = "pending"
    elif all(l.confirmed_qty in (None, ZERO) and l.rejected_qty >= l.ordered_qty for l in rows):
        ack = "rejected"
    elif all(l.confirmed_qty is not None and l.confirmed_qty >= l.ordered_qty for l in rows):
        ack = "accepted"
    else:
        ack = "partially_accepted"
    received = any(l.received_qty > 0 for l in rows)
    nothing_left = all(s.unconfirmed == 0 and s.outstanding == 0 for s in states)
    if ack == "counteroffer":
        status = "changes_proposed"
    elif nothing_left and (received or ack == "rejected"):
        status = "received" if received and open_issues(session, po) else "closed"
    elif received:
        status = "partially_received"
    elif ack != "pending":
        status = "supplier_confirmed"
    else:
        status = po.status if po.status in ("test_sent", "delivery_unknown") else "test_sent"
    po.ack_status, po.status, po.updated_at = ack, status, _now()


def resolve_not_delivered(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID,
                          note: str) -> PurchaseOrder:
    """
    An order in delivery_unknown that the owner has confirmed with the supplier was
    never received: release what the plan held for it and let it be re-approved.
    Never automatic — a transport that may have delivered is not resent by itself.
    """
    from clawbot.domain import purchasing

    authorize(actor, "po.approve")
    po = purchasing.get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=True)
    if po.status != "delivery_unknown":
        raise StateConflict(f"Only an order whose delivery is unknown can be resolved this way (this one is {po.status})")
    if not note.strip():
        raise ValidationFailed("Say how you confirmed the supplier did not receive it")
    for line in lines(session, po, for_update=True):
        line.cancelled_qty = line.ordered_qty
    po.status, po.updated_at = "failed", _now()
    data_version.bump(session, tenant_id)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.delivery_resolved", object_type="purchase_order",
                 object_id=po.id, after={"outcome": "not_received"}, reason=note)
    return po
