"""
Orders placed outside Tabula that have not fully arrived (spec 3.4, 6.4).

They exist so replenishment never re-orders what is already on the way. Only
lines the supplier confirmed count as confirmed inbound; unconfirmed ones only
suppress duplicate orders.

Reports are snapshots: each carries the time it was true (`reported_at`). An
older report never overwrites a newer one, and a report declared *complete* for
a supplier closes that supplier's lines it no longer lists (they were received
or cancelled) — otherwise received orders would block reorders forever.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.domain import audit, catalog, data_version, suppliers, tenancy
from clawbot.domain.errors import NotFound, ValidationFailed
from clawbot.domain.units import QTY_SCALE
from clawbot.persistence.models import ExternalOpenOrderLine, OpenOrderLink, PurchaseOrder
from clawbot.policies.permissions import Actor, authorize


@dataclass(frozen=True)
class UpsertedLine:
    line: ExternalOpenOrderLine
    outcome: str  # "created" | "updated" | "unchanged" | "older_report"


def upsert_open_order_line(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    variant_id: uuid.UUID,
    location_id: uuid.UUID,
    external_po_number: str,
    outstanding_qty: Decimal,
    supplier_confirmed: bool,
    ordered_at: datetime | None = None,
    expected_at: datetime | None = None,
    import_id: uuid.UUID | None = None,
    reported_at: datetime | None = None,
) -> UpsertedLine:
    authorize(actor, "orders.record_external")
    if outstanding_qty < 0 or outstanding_qty != outstanding_qty.quantize(QTY_SCALE):
        raise ValidationFailed("outstanding_qty must be ≥ 0 with at most 4 decimal places")
    for value in (ordered_at, expected_at, reported_at):
        if value is not None and value.tzinfo is None:
            raise ValidationFailed("dates must include a timezone")
    suppliers.get_supplier(session, tenant_id=tenant_id, supplier_id=supplier_id)
    catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)

    line = session.scalars(
        select(ExternalOpenOrderLine)
        .where(
            ExternalOpenOrderLine.tenant_id == tenant_id,
            ExternalOpenOrderLine.supplier_id == supplier_id,
            ExternalOpenOrderLine.location_id == location_id,
            ExternalOpenOrderLine.external_po_number == external_po_number,
            ExternalOpenOrderLine.variant_id == variant_id,
        )
        .with_for_update()
    ).one_or_none()
    fields = dict(
        location_id=location_id, outstanding_qty=outstanding_qty, supplier_confirmed=supplier_confirmed,
        ordered_at=ordered_at, expected_at=expected_at,
    )
    if line is not None and line.reported_at and reported_at and reported_at < line.reported_at:
        return UpsertedLine(line, "older_report")
    if line is None:
        line = ExternalOpenOrderLine(
            tenant_id=tenant_id, supplier_id=supplier_id, variant_id=variant_id,
            external_po_number=external_po_number, import_id=import_id, reported_at=reported_at, **fields,
        )
        session.add(line)
        session.flush()
        data_version.bump(session, tenant_id)
        return UpsertedLine(line, "created")
    reopened = line.closed_at is not None
    if all(getattr(line, k) == val for k, val in fields.items()) and not reopened:
        if reported_at and (line.reported_at is None or reported_at > line.reported_at):
            line.reported_at = reported_at
        return UpsertedLine(line, "unchanged")
    for k, val in fields.items():
        setattr(line, k, val)
    line.import_id, line.closed_at = import_id, None
    if reported_at:
        line.reported_at = reported_at
    line.updated_at = datetime.now(timezone.utc)
    session.flush()
    data_version.bump(session, tenant_id)
    return UpsertedLine(line, "updated")


def list_open_order_lines(session: Session, *, tenant_id: uuid.UUID) -> list[ExternalOpenOrderLine]:
    return list(
        session.scalars(
            select(ExternalOpenOrderLine)
            .where(ExternalOpenOrderLine.tenant_id == tenant_id, ExternalOpenOrderLine.outstanding_qty > 0)
            .order_by(ExternalOpenOrderLine.expected_at.nulls_last())
        )
    )


def close_missing_from_report(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    supplier_id: uuid.UUID,
    location_id: uuid.UUID,
    listed: set[tuple[str, uuid.UUID]],
    reported_at: datetime,
    source_ref: str,
) -> int:
    """A complete report for this supplier and location: close older open lines it does not list."""
    authorize(actor, "orders.record_external")
    stale = list(session.scalars(
        select(ExternalOpenOrderLine).where(
            ExternalOpenOrderLine.tenant_id == tenant_id, ExternalOpenOrderLine.supplier_id == supplier_id,
            ExternalOpenOrderLine.location_id == location_id, ExternalOpenOrderLine.outstanding_qty > 0,
            ExternalOpenOrderLine.closed_at.is_(None),
        ).with_for_update()
    ))
    closed = 0
    for line in stale:
        if (line.external_po_number, line.variant_id) in listed:
            continue
        if line.reported_at is not None and line.reported_at >= reported_at:
            continue  # a newer report listed it
        before = {"outstanding_qty": str(line.outstanding_qty)}
        line.outstanding_qty, line.closed_at = Decimal(0), datetime.now(timezone.utc)
        line.updated_at = line.closed_at
        closed += 1
        audit.record(session, tenant_id=tenant_id, actor=actor, action="open_order.closed_by_report",
                     object_type="external_open_order_line", object_id=line.id, before=before,
                     after={"outstanding_qty": "0"}, reason=f"Not listed in complete report {source_ref}")
    session.flush()
    return closed


# ---------------------------------------------------------------------------
# Is an export's order one of Tabula's own POs?
# ---------------------------------------------------------------------------


def _exact(number: str) -> str:
    return re.sub(r"\s+", "", number).upper()


def _alnum(number: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", number.upper())


def _digits(number: str) -> str:
    d = re.sub(r"\D", "", number)
    return d.lstrip("0") or ("0" if d else "")


def _prefix(number: str) -> str:
    """Letters before the digits ("PO-00080" → "PO", "INV-80" → "INV", "80" → "")."""
    return re.match(r"[A-Z]*", _alnum(number)).group(0)


@dataclasses.dataclass(frozen=True)
class Link:
    status: str  # linked_exact | linked_by_person | separate_by_person | suggested | separate
    po_id: uuid.UUID | None = None
    po_number: str | None = None
    candidates: tuple[str, ...] = ()


def links(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID) -> dict[tuple[uuid.UUID, str], Link]:
    """
    For every order number in open-order exports at this location: is it one of Tabula's POs?

    Only the supplier and the order number are compared — never products or quantities, so two
    different orders for the same item are never merged. Same supplier and the same number
    (ignoring spaces and case) → the same order, counted once from Tabula's own lines. A number that
    only matches after dropping punctuation or leading zeros ("PO00080", "80" vs "PO-00080") is a
    suggestion: it is not counted until a person decides, and the plan says so on that item.
    """
    numbers = session.execute(select(ExternalOpenOrderLine.supplier_id, ExternalOpenOrderLine.external_po_number).where(
        ExternalOpenOrderLine.tenant_id == tenant_id, ExternalOpenOrderLine.location_id == location_id,
        ExternalOpenOrderLine.outstanding_qty > 0).distinct()).all()
    if not numbers:
        return {}
    pos = session.execute(select(PurchaseOrder.id, PurchaseOrder.supplier_id, PurchaseOrder.number).where(
        PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.location_id == location_id,
        PurchaseOrder.sent_at.is_not(None))).all()
    decided = {(d.supplier_id, d.external_po_number): d for d in session.scalars(select(OpenOrderLink).where(
        OpenOrderLink.tenant_id == tenant_id, OpenOrderLink.location_id == location_id))}
    numbers_by_id = {pid: number for pid, _, number in pos}
    out: dict[tuple[uuid.UUID, str], Link] = {}
    for supplier_id, number in numbers:
        mine = [(pid, n) for pid, sid, n in pos if sid == supplier_id]
        d = decided.get((supplier_id, number))
        if d is not None:
            out[(supplier_id, number)] = (Link("linked_by_person", d.po_id, numbers_by_id.get(d.po_id))
                                          if d.decision == "same_order" else Link("separate_by_person"))
            continue
        exact = [(pid, n) for pid, n in mine if _exact(n) == _exact(number)]
        if exact:
            out[(supplier_id, number)] = Link("linked_exact", exact[0][0], exact[0][1])
            continue
        near = [n for _, n in mine if (_alnum(n) and _alnum(n) == _alnum(number))
                or (_digits(number) and _digits(n) == _digits(number)
                    and (not _prefix(number) or not _prefix(n) or _prefix(number) == _prefix(n)))]
        out[(supplier_id, number)] = Link("suggested", candidates=tuple(near)) if near else Link("separate")
    return out


def decide_link(session: Session, *, tenant_id: uuid.UUID, actor: Actor, location_id: uuid.UUID,
                supplier_id: uuid.UUID, external_po_number: str, decision: str, po_id: uuid.UUID | None,
                note: str | None) -> OpenOrderLink:
    """A person says whether an export's order number is one of Tabula's POs (or a different order)."""
    authorize(actor, "po.draft")
    if decision not in ("same_order", "different_order"):
        raise ValidationFailed("decision must be same_order or different_order")
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    exists = session.scalar(select(ExternalOpenOrderLine.id).where(
        ExternalOpenOrderLine.tenant_id == tenant_id, ExternalOpenOrderLine.location_id == location_id,
        ExternalOpenOrderLine.supplier_id == supplier_id, ExternalOpenOrderLine.external_po_number == external_po_number).limit(1))
    if exists is None:
        raise NotFound(f"No open order {external_po_number} from that supplier at this location")
    if decision == "same_order":
        po = session.scalars(select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == po_id)).one_or_none()
        if po is None or po.supplier_id != supplier_id or po.location_id != location_id or po.sent_at is None:
            raise ValidationFailed("Pick a sent Tabula order from the same supplier and location")
    else:
        po_id = None
    # Upsert: two people deciding the same number at once end with the later decision, not an error.
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    session.execute(pg_insert(OpenOrderLink).values(
        id=uuid.uuid4(), tenant_id=tenant_id, supplier_id=supplier_id, location_id=location_id,
        external_po_number=external_po_number, decision=decision, po_id=po_id, note=note,
        decided_by_user_id=actor.user_id, decided_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=["tenant_id", "supplier_id", "location_id", "external_po_number"],
        set_={"decision": decision, "po_id": po_id, "note": note, "decided_by_user_id": actor.user_id,
              "decided_at": datetime.now(timezone.utc)}))
    link = session.scalars(select(OpenOrderLink).where(
        OpenOrderLink.tenant_id == tenant_id, OpenOrderLink.supplier_id == supplier_id,
        OpenOrderLink.location_id == location_id, OpenOrderLink.external_po_number == external_po_number)
        .execution_options(populate_existing=True)).one()
    data_version.bump(session, tenant_id)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="open_order.link_decided", object_type="open_order_link",
                 object_id=link.id, after={"external_po_number": external_po_number, "decision": decision,
                                           "po_id": str(po_id) if po_id else None}, reason=note)
    return link
