"""
Receiving (spec 10, CP8): what physically arrived against a sent order.

A receipt records, per PO line, how much arrived and how much of that was
damaged. Sellable units go into stock exactly once:

- Tabula owns the location's stock: one ledger movement (reason `receipt`) per
  receipt line, keyed by the receipt line, so a replay cannot add it twice.
- The POS owns the stock (e.g. Square, read-only in this build): Tabula cannot
  write it, so the receipt stays `pending_pos` until someone enters it in the POS
  and a POS stock reading newer than that report arrives. Until then the item is
  flagged as a stock mismatch and new orders containing it cannot be sent.

Damaged goods become an open issue to settle with the supplier. A replacement
counts as inbound only after the supplier confirms it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from clawbot.domain import audit, data_version, inventory, po_progress, tenancy
from clawbot.domain.errors import IdempotencyConflict, NotFound, StateConflict, ValidationFailed
from clawbot.domain.units import to_base_qty
from clawbot.persistence.models import (
    PO_SENT_STATUSES,
    InventorySnapshot,
    PoLine,
    Receipt,
    ReceiptIssue,
    ReceiptLine,
)
from clawbot.policies.permissions import Actor, authorize, system

ZERO = Decimal(0)
LEDGER_ACTOR = system("receiving")  # receipts reach the ledger only through this flow (inventory.MANUAL_REASONS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ReceiveLine:
    line_no: int
    arrived_qty: Decimal  # order units
    damaged_qty: Decimal = ZERO


def _digest(lines: list[ReceiveLine], received_at: datetime | None, notes: str | None) -> str:
    body = {"lines": sorted([[l.line_no, f"{l.arrived_qty.normalize():f}", f"{l.damaged_qty.normalize():f}"] for l in lines]),
            "received_at": received_at.isoformat() if received_at else None, "notes": notes or None}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def record_receipt(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, receipt_key: str,
                   lines: list[ReceiveLine], received_at: datetime | None = None,
                   notes: str | None = None) -> tuple[Receipt, bool]:
    """
    Returns (receipt, created). The same receipt_key with the same content returns
    the first receipt (a double submit or retry); with different content it is refused.
    """
    from clawbot.domain import purchasing

    authorize(actor, "receiving.record")
    if not receipt_key or len(receipt_key) > 100:
        raise ValidationFailed("receipt_key is required (1–100 characters)")
    if received_at is not None and received_at.tzinfo is None:
        raise ValidationFailed("received_at must include a timezone")
    if received_at is not None and received_at > _now():
        raise ValidationFailed("received_at cannot be in the future")
    digest = _digest(lines, received_at, notes)
    po = purchasing.get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=True)  # serialises receipts per order
    existing = session.scalars(select(Receipt).where(Receipt.tenant_id == tenant_id, Receipt.po_id == po.id,
                                                     Receipt.receipt_key == receipt_key)).one_or_none()
    if existing is not None:
        if existing.request_digest != digest:
            raise IdempotencyConflict("This receipt was already recorded with different quantities")
        return existing, False
    if po.status not in PO_SENT_STATUSES:
        raise StateConflict(f"Nothing is expected on a {po.status.replace('_', ' ')} order")
    if not lines:
        raise ValidationFailed("Record at least one line")
    by_no = {l.line_no: l for l in po_progress.lines(session, po, for_update=True)}
    seen: set[int] = set()
    for l in lines:
        if l.line_no in seen or l.line_no not in by_no:
            raise ValidationFailed(f"Unknown or repeated line {l.line_no}")
        seen.add(l.line_no)
        if l.arrived_qty <= 0 or l.damaged_qty < 0 or l.damaged_qty > l.arrived_qty:
            raise ValidationFailed(f"Line {l.line_no}: arrived must be positive and damaged between 0 and arrived")
        s = po_progress.state(by_no[l.line_no])
        expected = s.unconfirmed + s.outstanding
        if l.arrived_qty > expected:
            raise ValidationFailed(f"Line {l.line_no}: {l.arrived_qty.normalize():f} arrived but only "
                                   f"{expected.normalize():f} {by_no[l.line_no].order_uom} is still expected; "
                                   "record extra goods with the supplier first",
                                   details={"line_no": l.line_no, "expected": f"{expected.normalize():f}"})

    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=po.location_id)
    receipt = Receipt(tenant_id=tenant_id, po_id=po.id, receipt_key=receipt_key, request_digest=digest,
                      received_at=received_at or _now(), notes=notes, recorded_by_user_id=actor.user_id)
    session.add(receipt)
    session.flush()
    summary = []
    for l in lines:
        line = by_no[l.line_no]
        sellable = to_base_qty(l.arrived_qty - l.damaged_qty, line.units_per_order_uom)
        rl = ReceiptLine(tenant_id=tenant_id, receipt_id=receipt.id, po_line_id=line.id, variant_id=line.variant_id,
                         location_id=po.location_id, arrived_qty=l.arrived_qty, damaged_qty=l.damaged_qty,
                         sellable_base_qty=sellable,
                         pos_status="ledger_posted" if location.inventory_write_owner == "tabula" else "pending_pos")
        session.add(rl)
        session.flush()
        if location.inventory_write_owner == "tabula" and sellable > 0:
            inventory.record_movement(
                session, tenant_id=tenant_id, variant_id=line.variant_id, location_id=po.location_id, delta=sellable,
                reason="receipt", source="po_receipt", source_event_id=str(rl.id), actor=LEDGER_ACTOR,
                notes=f"{po.number} line {line.line_no}", occurred_at=receipt.received_at)
        line.received_qty += l.arrived_qty
        line.damaged_qty += l.damaged_qty
        line.updated_at = _now()
        if l.damaged_qty > 0:
            session.add(ReceiptIssue(tenant_id=tenant_id, po_id=po.id, po_line_id=line.id, receipt_line_id=rl.id,
                                     kind="damaged", qty=l.damaged_qty, status="open"))
        summary.append({"line_no": l.line_no, "arrived": f"{l.arrived_qty.normalize():f}",
                        "damaged": f"{l.damaged_qty.normalize():f}", "sellable_units": f"{sellable.normalize():f}"})
    session.flush()
    po_progress.recompute(session, po)
    data_version.bump(session, tenant_id)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.received", object_type="purchase_order",
                 object_id=po.id, after={"receipt_id": str(receipt.id), "lines": summary, "status": po.status})
    return receipt, True


ISSUE_RESOLUTIONS = ("replacement_confirmed", "credit_confirmed", "written_off")


def resolve_issue(session: Session, *, tenant_id: uuid.UUID, actor: Actor, issue_id: uuid.UUID, resolution: str,
                  qty: Decimal | None = None, eta: date | None = None, note: str | None = None) -> ReceiptIssue:
    """Record what the supplier confirmed about damaged goods. Only a confirmed replacement becomes inbound."""
    from clawbot.domain import purchasing

    authorize(actor, "receiving.resolve")
    issue = session.scalars(select(ReceiptIssue).where(ReceiptIssue.tenant_id == tenant_id,
                                                       ReceiptIssue.id == issue_id)).one_or_none()
    if issue is None:
        raise NotFound("Issue not found")
    po = purchasing.get_po(session, tenant_id=tenant_id, po_id=issue.po_id, for_update=True)
    session.refresh(issue, with_for_update=True)
    if issue.status != "open":
        raise StateConflict(f"This issue is already {issue.status.replace('_', ' ')}")
    if resolution not in ISSUE_RESOLUTIONS:
        raise ValidationFailed(f"resolution must be one of {', '.join(ISSUE_RESOLUTIONS)}")
    if resolution == "replacement_confirmed":
        qty = issue.qty if qty is None else qty
        if qty <= 0 or qty > issue.qty:
            raise ValidationFailed(f"A replacement is between 0 and the {issue.qty.normalize():f} damaged")
        line = session.get(PoLine, issue.po_line_id, with_for_update=True)
        line.replacement_qty += qty
        if eta is not None and (line.eta is None or eta > line.eta):
            line.eta = eta  # conservative: the remaining quantity is expected by the later date
        line.updated_at = _now()
    issue.status, issue.resolution_qty, issue.resolution_eta, issue.note = resolution, qty, eta, note
    issue.resolved_by_user_id, issue.resolved_at = actor.user_id, _now()
    po_progress.recompute(session, po)
    data_version.bump(session, tenant_id)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.issue_resolved", object_type="purchase_order",
                 object_id=po.id, after={"issue_id": str(issue.id), "resolution": resolution,
                                         "qty": f"{qty.normalize():f}" if qty is not None else None,
                                         "eta": eta.isoformat() if eta else None}, reason=note)
    return issue


def report_entered_in_pos(session: Session, *, tenant_id: uuid.UUID, actor: Actor, receipt_line_id: uuid.UUID) -> ReceiptLine:
    """A person says they entered this receipt in the POS. Still to be reconciled (reconcile_pos)."""
    authorize(actor, "receiving.record")
    rl = _receipt_line(session, tenant_id, receipt_line_id, for_update=True)
    if rl.pos_status == "ledger_posted":
        raise StateConflict("This receipt was posted to Tabula's own stock ledger; there is nothing to enter in a POS")
    if rl.pos_status == "pending_pos":
        rl.pos_status, rl.pos_reported_at, rl.pos_reported_by_user_id = "pos_reported", _now(), actor.user_id
        audit.record(session, tenant_id=tenant_id, actor=actor, action="receipt.pos_reported", object_type="receipt_line",
                     object_id=rl.id, after={"pos_status": rl.pos_status})
    return rl


def pos_unconfirmed(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID) -> dict[uuid.UUID, list[str]]:
    """
    Items received in Tabula that nobody has yet reconciled against the POS, by variant.
    A newer POS reading alone does not clear it — sales, refunds and adjustments in between
    could hide a receipt that was never entered — an owner or manager signs off with the
    evidence (pos_evidence / reconcile_pos).
    """
    out: dict[uuid.UUID, list[str]] = {}
    rows = session.scalars(select(ReceiptLine).where(
        ReceiptLine.tenant_id == tenant_id, ReceiptLine.location_id == location_id,
        ReceiptLine.pos_status.in_(("pending_pos", "pos_reported")))).all()
    for rl in rows:
        out.setdefault(rl.variant_id, []).append(
            "entered in the POS — waiting for someone to reconcile it" if rl.pos_status == "pos_reported"
            else "received in Tabula, not entered in the POS yet")
    return out


def _receipt_line(session: Session, tenant_id: uuid.UUID, receipt_line_id: uuid.UUID, *, for_update: bool = False) -> ReceiptLine:
    stmt = select(ReceiptLine).where(ReceiptLine.tenant_id == tenant_id, ReceiptLine.id == receipt_line_id)
    rl = session.scalars(stmt.with_for_update() if for_update else stmt).one_or_none()
    if rl is None:
        raise NotFound("Receipt line not found")
    return rl


def pos_evidence(session: Session, *, tenant_id: uuid.UUID, receipt_line_id: uuid.UUID) -> dict[str, Any]:
    """
    What the POS readings say about one receipt, with everything else that moved stock in between:

        expected after = reading before + units received (this and other receipts in the window)
                         − units sold + refunds known to be restocked
        unexplained    = reading after − expected

    Refunds whose restock is unknown are listed separately (they may or may not be back on the
    shelf), so a zero difference is never taken as proof on its own.
    """
    from clawbot.persistence.models import SalesLine

    rl = _receipt_line(session, tenant_id, receipt_line_id)
    receipt = session.get(Receipt, rl.receipt_id)
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=rl.location_id)
    source = location.inventory_write_owner
    snaps = list(session.scalars(select(InventorySnapshot).where(
        InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.location_id == rl.location_id,
        InventorySnapshot.variant_id == rl.variant_id, InventorySnapshot.source_system == source)
        .order_by(InventorySnapshot.as_of)))
    before = next((sn for sn in reversed(snaps) if sn.as_of <= receipt.received_at), None)
    since = rl.pos_reported_at or receipt.received_at
    after = next((sn for sn in snaps if sn.as_of > since), None)
    out: dict[str, Any] = {
        "source": source, "received_at": receipt.received_at.isoformat(),
        "reported_entered_at": rl.pos_reported_at.isoformat() if rl.pos_reported_at else None,
        "this_receipt_units": _n(rl.sellable_base_qty),
        "reading_before": None if before is None else {"qty": _n(before.quantity), "at": before.as_of.isoformat()},
        "reading_after": None if after is None else {"qty": _n(after.quantity), "at": after.as_of.isoformat()},
        "latest_reading": None if not snaps else {"qty": _n(snaps[-1].quantity), "at": snaps[-1].as_of.isoformat()},
    }
    if before is None or after is None:
        out["assessment"] = "no_reading_before" if before is None else "no_reading_after"
        out["explanation"] = ("There is no POS stock reading from before this delivery, so the POS cannot be compared; "
                              "check the item's stock history in the POS." if before is None else
                              "No POS stock reading since the receipt was entered; sync the POS (or wait for the next "
                              "sync) to compare, or check the POS directly.")
        return out
    lo, hi = before.as_of, after.as_of
    sold = refunds_restocked = refunds_unknown = ZERO
    for line in session.scalars(select(SalesLine).where(
            SalesLine.tenant_id == tenant_id, SalesLine.location_id == rl.location_id, SalesLine.variant_id == rl.variant_id,
            SalesLine.sold_at > lo, SalesLine.sold_at <= hi)):
        if line.line_type == "sale":
            sold += line.quantity
        elif line.restock:
            refunds_restocked += -line.quantity
        elif line.restock is None:
            refunds_unknown += -line.quantity
    # This receipt always counts (a POS reading taken at the very moment of the delivery must not hide it);
    # other deliveries of the item count when they fall inside the window.
    others = sum((r.sellable_base_qty for r in session.scalars(select(ReceiptLine).join(
        Receipt, and_(Receipt.tenant_id == ReceiptLine.tenant_id, Receipt.id == ReceiptLine.receipt_id)).where(
        ReceiptLine.tenant_id == tenant_id, ReceiptLine.location_id == rl.location_id, ReceiptLine.variant_id == rl.variant_id,
        ReceiptLine.id != rl.id, Receipt.received_at > lo, Receipt.received_at <= hi))), ZERO)
    received = rl.sellable_base_qty + others
    expected = before.quantity + received - sold + refunds_restocked
    diff = after.quantity - expected
    out.update(window={"from": lo.isoformat(), "to": hi.isoformat()}, units_received_in_window=_n(received),
               units_sold=_n(sold), refunds_restocked=_n(refunds_restocked), refunds_restock_unknown=_n(refunds_unknown),
               expected_after=_n(expected), unexplained=_n(diff))
    if diff == 0 and refunds_unknown == 0:
        out["assessment"], out["explanation"] = "consistent", (
            "The reading after matches the reading before plus what was received, minus what sold. "
            "An adjustment in the POS that happens to cancel out would not show here.")
    elif diff == 0:
        out["assessment"], out["explanation"] = "consistent_if_refunds_not_restocked", (
            f"Matches if the {_n(refunds_unknown)} refunded unit(s) of unknown restock did not go back on the shelf; "
            "if they did, a unit is missing. Check the POS.")
    elif diff == refunds_unknown:
        out["assessment"], out["explanation"] = "explained_if_refunds_restocked", (
            f"The difference equals {_n(refunds_unknown)} refunded unit(s) whose restock is unknown; it fits if they went back on the shelf.")
    elif diff == -rl.sellable_base_qty and rl.sellable_base_qty > 0:
        out["assessment"], out["explanation"] = "receipt_missing_in_pos", (
            "The POS stock moved exactly as if this delivery was never entered.")
    else:
        out["assessment"], out["explanation"] = "difference", (
            f"{_n(diff)} unit(s) are unexplained by sales, refunds and receipts — an adjustment, a count, "
            "or a receipt entered with a different quantity.")
    return out


RECONCILE_OUTCOMES = ("matches", "corrected_in_pos", "accepted_difference")


def reconcile_pos(session: Session, *, tenant_id: uuid.UUID, actor: Actor, receipt_line_id: uuid.UUID, outcome: str,
                  note: str | None) -> ReceiptLine:
    """
    An owner or manager signs off a receipt against the POS. The evidence at that moment is
    stored with the decision. Anything other than a consistent comparison needs a note.
    """
    authorize(actor, "receiving.resolve")
    if outcome not in RECONCILE_OUTCOMES:
        raise ValidationFailed(f"outcome must be one of {', '.join(RECONCILE_OUTCOMES)}")
    rl = _receipt_line(session, tenant_id, receipt_line_id, for_update=True)
    if rl.pos_status not in ("pending_pos", "pos_reported"):
        raise StateConflict(f"Nothing to reconcile (this receipt is {rl.pos_status.replace('_', ' ')})")
    evidence = pos_evidence(session, tenant_id=tenant_id, receipt_line_id=receipt_line_id)
    if (outcome != "matches" or evidence["assessment"] != "consistent") and not (note or "").strip():
        raise ValidationFailed("Say what you checked in the POS: the evidence does not settle it on its own",
                               details={"assessment": evidence["assessment"]})
    rl.pos_status, rl.pos_reconciled_at, rl.pos_reconciled_by_user_id = "pos_reconciled", _now(), actor.user_id
    rl.pos_reconciliation = {"outcome": outcome, "note": note, "evidence": evidence}
    data_version.bump(session, tenant_id)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="receipt.pos_reconciled", object_type="receipt_line",
                 object_id=rl.id, after={"outcome": outcome, "assessment": evidence["assessment"],
                                         "unexplained": evidence.get("unexplained")}, reason=note)
    return rl


def _n(d: Decimal | None) -> str | None:
    return None if d is None else f"{d.normalize():f}"
