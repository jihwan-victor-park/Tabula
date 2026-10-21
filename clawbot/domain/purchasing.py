"""
Purchase orders (CP6, spec 9, 10, 16.3).

- Drafts are built from a current, fresh replenishment plan, one PO per
  (supplier, ship-to location, currency).
- Every change creates an immutable revision; its digest covers supplier,
  recipient, ship-to, lines (SKU, pack, quantity, price) and totals.
- Approval is an owner's decision about one exact revision + digest. The
  approval row, the PO status change and the send job (outbox) are written in
  one transaction; the outbox operation key (po, revision, send) means double
  clicks, two approvers or a re-run worker can never queue two sends.
- Before approving, the inputs the quantities were based on are re-checked by
  data version (commit-ordered, so uncommitted writes at plan time are caught):
  if anything changed, the plan is recomputed and approval only proceeds when
  the recommendations for these lines are unchanged. While imports or syncs are
  still being applied, approval waits.
- Sending is capture-only in this build (clawbot/policies/supplier_contact.py).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.domain import audit, data_version, outbox, suppliers, tenancy
from clawbot.domain.errors import NotFound, StaleVersion, StateConflict, ValidationFailed
from clawbot.domain.replenishment import service as replenishment
from clawbot.domain.units import round_money, to_base_qty
from clawbot.persistence.models import (
    PO_ACTIVE_STATUSES,
    PoApproval,
    PoRevision,
    PurchaseOrder,
    ReplenishmentLine,
    SupplierContact,
    TenantCounter,
    Variant,
)
from clawbot.policies.permissions import Actor, authorize

SEND_TOPIC = "po.send"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: Decimal) -> str:
    return f"{value:f}"


def _digest(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _next_number(session: Session, tenant_id: uuid.UUID) -> str:
    value = session.execute(
        insert(TenantCounter).values(tenant_id=tenant_id, name="po", value=1)
        .on_conflict_do_update(index_elements=["tenant_id", "name"], set_={"value": TenantCounter.value + 1})
        .returning(TenantCounter.value)
    ).scalar_one()
    return f"PO-{value:05d}"


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def _order_recipient(session: Session, supplier) -> str | None:
    return session.scalars(
        select(SupplierContact.email).where(
            SupplierContact.tenant_id == supplier.tenant_id, SupplierContact.supplier_id == supplier.id,
            SupplierContact.is_order_recipient.is_(True), SupplierContact.verified_at.is_not(None),
            SupplierContact.email.is_not(None),
        ).order_by(SupplierContact.created_at)
    ).first()


def build_content(session: Session, po: PurchaseOrder, lines: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Snapshot everything the owner approves. `lines` carry supplier_item_id,
    order_qty and the recommendation they came from; prices and packs are read
    *now*, so a refreshed revision always shows current terms.
    """
    tenant_id = po.tenant_id
    supplier = suppliers.get_supplier(session, tenant_id=tenant_id, supplier_id=po.supplier_id)
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=po.location_id)
    recipient = _order_recipient(session, supplier)
    notices: list[dict[str, str]] = []
    blockers: list[str] = []
    # Received in Tabula but the POS (which owns the stock) does not show it yet: the plan's stock is
    # understated, so ordering more of it waits until the POS catches up (receiving.py).
    from clawbot.domain import receiving

    pos_pending = receiving.pos_unconfirmed(session, tenant_id=tenant_id, location_id=po.location_id)

    out_lines = []
    subtotal = Decimal(0)
    for n, spec in enumerate(sorted(lines, key=lambda l: l["sku"]), start=1):
        item = suppliers.get_supplier_item(session, tenant_id=tenant_id, item_id=uuid.UUID(spec["supplier_item_id"]))
        variant = session.get(Variant, item.variant_id) if item.variant_id else None
        price = suppliers.current_price(session, tenant_id=tenant_id, item_id=item.id)
        order_qty = Decimal(spec["order_qty"])
        line_blockers = []
        if item.mapping_status != "confirmed":
            line_blockers.append("mapping_not_confirmed")
        if item.status != "active":
            line_blockers.append(f"supplier_item_{item.status}")
        if price is None:
            line_blockers.append("no_current_price")
        elif price.currency != po.currency:
            line_blockers.append("price_currency_differs")
        if item.variant_id in pos_pending:
            line_blockers.append("stock_not_confirmed_in_pos")
        if order_qty <= 0:
            line_blockers.append("quantity_not_positive")
        elif order_qty % item.order_multiple != 0 or order_qty < item.min_order_qty:
            line_blockers.append("quantity_breaks_multiple_or_minimum")
        unit_price = price.unit_price if price else Decimal(0)
        line_total = round_money(order_qty * unit_price, po.currency)
        subtotal += line_total
        recommended = spec.get("recommendation") or {}
        if recommended.get("price_id") and price and recommended["price_id"] != str(price.id):
            notices.append({"code": "price_changed_since_plan", "message": f"{spec['sku']}: price changed since the plan"})
        out_lines.append({
            "line_no": n,
            "variant_id": str(item.variant_id) if item.variant_id else None,
            "sku": variant.sku if variant else spec["sku"], "name": variant.name if variant else spec.get("name"),
            "supplier_item_id": str(item.id), "supplier_item_version": item.version, "supplier_sku": item.supplier_sku,
            "order_uom": item.order_uom, "units_per_order_uom": _money(item.units_per_order_uom.normalize()),
            "order_multiple": _money(item.order_multiple.normalize()), "min_order_qty": _money(item.min_order_qty.normalize()),
            "order_qty": _money(order_qty.normalize()),
            "base_qty": _money(to_base_qty(order_qty, item.units_per_order_uom).normalize()),
            "unit_price": _money(unit_price.normalize()), "line_total": _money(line_total),
            "price": None if price is None else {
                "id": str(price.id), "type": price.price_type, "source": price.source_ref,
                "valid_from": price.valid_from.isoformat(),
                "basis": f"{_money(price.unit_price.normalize())} {price.currency} per {item.order_uom} of "
                         f"{_money(item.units_per_order_uom.normalize())}",
            },
            "recommendation": recommended,
            "edited": Decimal(spec["order_qty"]) != Decimal(recommended.get("order_qty", spec["order_qty"])),
            "blockers": line_blockers,
        })
        blockers += [f"line {n}: {b}" for b in line_blockers]

    if supplier.relationship_status != "approved":
        blockers.append(f"supplier_{supplier.relationship_status}")
    if supplier.credit_hold:
        blockers.append("supplier_credit_hold")
    if recipient is None:
        blockers.append("no_verified_order_email")
    address = [location.address_line1, location.city, location.region, location.postal_code, location.country]
    if not all([location.address_line1, location.city, location.postal_code, location.country]):
        blockers.append("ship_to_address_missing")
    subtotal = round_money(subtotal, po.currency)
    if supplier.min_order_amount is not None and subtotal < supplier.min_order_amount:
        notices.append({"code": "below_supplier_minimum",
                        "message": f"Subtotal {subtotal} {po.currency} is below {supplier.name}'s minimum "
                                   f"{_money(supplier.min_order_amount.normalize())}"})
    for line in out_lines:
        rec = line["recommendation"]
        if rec.get("status") == "other_supplier":
            notices.append({"code": "plan_prefers_other_supplier",
                            "message": f"{line['sku']}: the current plan buys this item from another supplier"})
        elif line["edited"]:
            notices.append({"code": "differs_from_recommendation",
                            "message": f"{line['sku']}: ordering {line['order_qty']} {line['order_uom']}, "
                                       f"the plan recommends {rec.get('order_qty', '0')}"})
        for reason in rec.get("reasons", []):
            notices.append({"code": reason["code"], "message": f"{line['sku']}: {reason['message']}"})

    return {
        "po_number": po.number,
        "currency": po.currency,
        "supplier": {
            "id": str(supplier.id), "name": supplier.name, "account_number": supplier.merchant_account_number,
            "order_email": recipient, "ordering_channel": supplier.ordering_channel,
            "payment_terms": supplier.payment_terms + (f" {supplier.payment_net_days}" if supplier.payment_net_days else ""),
            "status": supplier.relationship_status,
        },
        "ship_to": {
            "location_id": str(location.id), "name": location.name, "address_line1": location.address_line1,
            "address_line2": location.address_line2, "city": location.city, "region": location.region,
            "postal_code": location.postal_code, "country": location.country,
            "complete": all([location.address_line1, location.city, location.postal_code, location.country]),
        },
        "lines": out_lines,
        "totals": {
            "subtotal": _money(subtotal),
            "shipping": {"status": "not_confirmed", "amount": None, "note": supplier.freight_notes},
            "tax": {"status": "not_estimated", "amount": None},
            "estimated_total": _money(subtotal),
            "estimate_note": "Items only. Shipping and tax are not confirmed and are not included.",
        },
        "notices": notices,
        "blockers": blockers,
        "address_text": ", ".join(p for p in address if p),
    }


def _add_revision(session: Session, po: PurchaseOrder, content: dict[str, Any], actor: Actor, reason: str) -> PoRevision:
    rev = PoRevision(tenant_id=po.tenant_id, po_id=po.id, revision=po.current_revision, content=content,
                     digest=_digest(content), reason=reason, created_by_kind=actor.kind, created_by_user_id=actor.user_id)
    session.add(rev)
    session.flush()
    return rev


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_po(session: Session, *, tenant_id: uuid.UUID, po_id: uuid.UUID, for_update: bool = False) -> PurchaseOrder:
    stmt = select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.id == po_id)
    if for_update:
        stmt = stmt.with_for_update()
    po = session.scalars(stmt).one_or_none()
    if po is None:
        raise NotFound(f"Purchase order not found: {po_id}")
    return po


def revision(session: Session, po: PurchaseOrder, number: int | None = None) -> PoRevision:
    return session.scalars(select(PoRevision).where(
        PoRevision.tenant_id == po.tenant_id, PoRevision.po_id == po.id,
        PoRevision.revision == (number or po.current_revision))).one()


def list_pos(session: Session, *, tenant_id: uuid.UUID) -> list[PurchaseOrder]:
    return list(session.scalars(select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id)
                                .order_by(PurchaseOrder.created_at.desc())))


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def _ensure_plan_fresh(session: Session, run) -> None:
    if run.status != "current":
        raise StateConflict("This plan is not the current plan; open the latest recommendations")
    pending = data_version.pending_inputs(session, run.tenant_id)
    if pending:
        raise StateConflict("Data is still being updated; try again when it finishes", details={"pending": pending})
    if run.data_version != data_version.current(session, run.tenant_id):
        raise StateConflict("Data changed after this plan was computed; recompute the plan first",
                            details={"plan_version": run.data_version,
                                     "current_version": data_version.current(session, run.tenant_id)})


def _recommendation(line: ReplenishmentLine, supplier_item_id: str | None = None) -> dict[str, Any]:
    """
    What the plan said about this item, as seen from the PO line's supplier item.
    If the plan now buys the item from a different supplier, this supplier's
    recommended quantity is 0 and the line says so.
    """
    r = line.result
    sid = supplier_item_id or str(line.supplier_item_id)
    chosen = next((o for o in line.inputs["offers"] if o["supplier_item_id"] == sid), None)
    ordering_here = line.status == "order" and str(line.supplier_item_id) == sid
    return {
        "run_line_id": str(line.id) if line.id else None, "status": line.status if ordering_here or line.status != "order" else "other_supplier",
        "order_qty": f"{line.order_qty.normalize():f}" if ordering_here else "0",
        "base_qty": f"{line.base_qty.normalize():f}" if ordering_here else "0", "on_hand": line.inputs["on_hand"],
        "stock_as_of": line.inputs["stock_as_of"], "stock_source": line.inputs["stock_source"],
        "sales_through": line.inputs["sales_through"],
        "daily_demand": r.get("daily_demand"), "target": r.get("target"), "position": r.get("position"),
        "need": r.get("need"), "need_before_held": r.get("need_before_held"), "held_qty": r.get("held_qty"),
        "stockout_days": r.get("stockout_days"), "steps": r.get("steps"), "reasons": r.get("reasons", []),
        "price_id": chosen.get("price_id") if chosen else None,
        "order_date": chosen.get("order_date") if chosen else None,
        "delivery_date": chosen.get("delivery_date") if chosen else None,
        "usable_date": chosen.get("usable_date") if chosen else None,
    }


def _plan_now(session: Session, po: PurchaseOrder) -> replenishment.Evaluation:
    """This order's check of the plan: computed now, never saved as the location's plan."""
    return replenishment.evaluate(session, tenant_id=po.tenant_id, location_id=po.location_id)


def _moved(content: dict[str, Any], by_variant: dict[uuid.UUID, ReplenishmentLine]) -> list[dict[str, Any]]:
    """Lines whose recommendation for this supplier item differs from the one the order shows."""
    changed = []
    for line in content["lines"]:
        new = by_variant.get(uuid.UUID(line["variant_id"])) if line["variant_id"] else None
        now = _recommendation(new, line["supplier_item_id"]) if new is not None else {"order_qty": "0", "status": "missing"}
        was = line["recommendation"].get("order_qty")
        if now["order_qty"] != was:
            changed.append({"sku": line["sku"], "was": was, "now": now["order_qty"], "status": now["status"]})
    return changed


def create_drafts_from_run(session: Session, *, tenant_id: uuid.UUID, actor: Actor, run_id: uuid.UUID,
                           variant_ids: list[uuid.UUID] | None = None) -> list[PurchaseOrder]:
    """Group the plan's order lines into one draft per (supplier, location, currency)."""
    authorize(actor, "po.draft")
    run = replenishment.get_run(session, tenant_id=tenant_id, run_id=run_id)
    _ensure_plan_fresh(session, run)
    lines = [l for l in replenishment.run_lines(session, run) if l.status == "order"
             and (variant_ids is None or l.variant_id in set(variant_ids))]
    if not lines:
        raise ValidationFailed("The plan has nothing to order for the selected items")

    # Two people (or tabs) drafting at once: the second waits, then sees the first one's orders.
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"po-draft:{tenant_id}:{run.location_id}", 0))))
    # Never put an item on a second active order for the same location, whichever supplier.
    already = set(open_po_numbers(session, tenant_id=tenant_id, location_id=run.location_id))
    groups: dict[tuple[uuid.UUID, str], list[ReplenishmentLine]] = {}
    for line in lines:
        if line.variant_id in already:
            continue
        groups.setdefault((line.supplier_id, line.currency), []).append(line)
    if not groups:
        raise StateConflict("Every selected item is already on an open purchase order")

    skus = dict(session.execute(select(Variant.id, Variant.sku).where(Variant.tenant_id == tenant_id)).all())
    created = []
    version = data_version.current(session, tenant_id)
    for (supplier_id, currency), group in sorted(groups.items(), key=lambda g: str(g[0])):
        po = PurchaseOrder(tenant_id=tenant_id, number=_next_number(session, tenant_id), location_id=run.location_id,
                           supplier_id=supplier_id, currency=currency, status="draft", current_revision=1,
                           run_id=run.id, data_version=version, created_by_user_id=actor.user_id)
        session.add(po)
        session.flush()
        specs = [{"supplier_item_id": str(l.supplier_item_id), "sku": skus.get(l.variant_id, "?"),
                  "order_qty": f"{l.order_qty.normalize():f}", "recommendation": _recommendation(l)} for l in group]
        _add_revision(session, po, build_content(session, po, specs), actor, "Drafted from replenishment plan")
        audit.record(session, tenant_id=tenant_id, actor=actor, action="po.drafted", object_type="purchase_order",
                     object_id=po.id, after={"number": po.number, "run_id": str(run.id), "lines": len(group)})
        created.append(po)
    return created


def open_po_numbers(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Items on an active (not yet sent, not cancelled) order at this location -> PO number."""
    out: dict[uuid.UUID, str] = {}
    for po in session.scalars(select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.location_id == location_id,
            PurchaseOrder.status.in_(PO_ACTIVE_STATUSES)).order_by(PurchaseOrder.number)):
        for l in revision(session, po).content["lines"]:
            if l["variant_id"]:
                out.setdefault(uuid.UUID(l["variant_id"]), po.number)
    return out


def _new_revision(session: Session, po: PurchaseOrder, actor: Actor, lines: list[dict[str, Any]], reason: str) -> PoRevision:
    """Any content change: next revision, back to draft (an approval of an older revision no longer counts)."""
    before = {"status": po.status, "revision": po.current_revision}
    po.current_revision += 1
    po.status = "draft"
    po.updated_at = _now()
    rev = _add_revision(session, po, build_content(session, po, lines), actor, reason)
    audit.record(session, tenant_id=po.tenant_id, actor=actor, action="po.revised", object_type="purchase_order",
                 object_id=po.id, before=before, after={"status": po.status, "revision": po.current_revision},
                 reason=reason)
    return rev


def _editable(po: PurchaseOrder, expected_revision: int) -> None:
    if po.status not in PO_ACTIVE_STATUSES:
        raise StateConflict(f"A {po.status.replace('_', ' ')} purchase order cannot be changed")
    if po.current_revision != expected_revision:
        raise StaleVersion(f"The order is at revision {po.current_revision}; reload it",
                           details={"current_revision": po.current_revision})


def edit_quantities(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, expected_revision: int,
                    quantities: dict[int, Decimal], remove: list[int], reason: str | None) -> PoRevision:
    authorize(actor, "po.draft")
    po = get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=True)
    _editable(po, expected_revision)
    current = revision(session, po).content["lines"]
    known = {l["line_no"] for l in current}
    unknown = (set(quantities) | set(remove)) - known
    if unknown:
        raise ValidationFailed(f"Unknown line numbers: {sorted(unknown)}")
    lines = []
    for l in current:
        if l["line_no"] in remove:
            continue
        qty = quantities.get(l["line_no"], Decimal(l["order_qty"]))
        if qty <= 0:
            raise ValidationFailed(f"Line {l['line_no']}: quantity must be positive (remove the line instead)")
        if qty % Decimal(l["order_multiple"]) != 0 or qty < Decimal(l["min_order_qty"]):
            raise ValidationFailed(f"Line {l['line_no']}: {l['supplier_sku']} is ordered in multiples of "
                                   f"{l['order_multiple']} {l['order_uom']}, minimum {l['min_order_qty']}")
        lines.append({"supplier_item_id": l["supplier_item_id"], "sku": l["sku"], "order_qty": f"{qty.normalize():f}",
                      "recommendation": l["recommendation"]})
    if not lines:
        raise ValidationFailed("A purchase order needs at least one line; cancel it instead")
    return _new_revision(session, po, actor, lines, reason or "Quantities edited")


def refresh(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, expected_revision: int) -> PoRevision:
    """
    Re-read current prices, packs, recipient and address, and recompute the plan so
    every line shows today's recommendation next to the quantity on the order. The
    quantities are kept as they are; where they now differ from the recommendation
    the line is marked and the owner decides.
    """
    authorize(actor, "po.draft")
    po = get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=True)
    _editable(po, expected_revision)
    pending = data_version.pending_inputs(session, tenant_id)
    if pending:
        raise StateConflict("Data is still being updated; refresh when it finishes", details={"pending": pending})
    ev = _plan_now(session, po)
    by_variant = ev.lines
    lines = []
    for l in revision(session, po).content["lines"]:
        new = by_variant.get(uuid.UUID(l["variant_id"])) if l["variant_id"] else None
        lines.append({"supplier_item_id": l["supplier_item_id"], "sku": l["sku"], "order_qty": l["order_qty"],
                      "recommendation": _recommendation(new, l["supplier_item_id"]) if new is not None
                      else {**l["recommendation"], "order_qty": "0", "status": "missing", "reasons": []}})
    po.data_version = ev.data_version
    return _new_revision(session, po, actor, lines, "Refreshed with current prices, details and recommendation")


def submit(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, expected_revision: int) -> PurchaseOrder:
    authorize(actor, "po.draft")
    po = get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=True)
    _editable(po, expected_revision)
    if po.status != "draft":
        raise StateConflict(f"Only drafts can be submitted (this one is {po.status})")
    blockers = revision(session, po).content["blockers"]
    if blockers:
        raise ValidationFailed("Fix these before submitting", details={"blockers": blockers})
    po.status, po.updated_at = "awaiting_approval", _now()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.submitted", object_type="purchase_order",
                 object_id=po.id, after={"revision": po.current_revision})
    return po


def cancel(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, reason: str | None) -> PurchaseOrder:
    authorize(actor, "po.draft")
    po = get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=True)
    if po.status not in PO_ACTIVE_STATUSES:
        raise StateConflict(f"A {po.status.replace('_', ' ')} purchase order cannot be cancelled here")
    before = po.status
    po.status, po.updated_at = "cancelled", _now()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.cancelled", object_type="purchase_order",
                 object_id=po.id, before={"status": before}, after={"status": "cancelled"}, reason=reason)
    return po


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


def _revalidate_terms(session: Session, po: PurchaseOrder, content: dict[str, Any]) -> list[str]:
    """Things that may have changed since the revision was built and must still hold."""
    problems = []
    fresh = build_content(session, po, [
        {"supplier_item_id": l["supplier_item_id"], "sku": l["sku"], "order_qty": l["order_qty"],
         "recommendation": l["recommendation"]} for l in content["lines"]])
    if fresh["blockers"]:
        problems += fresh["blockers"]
    for old, new in zip(content["lines"], fresh["lines"]):
        if (old["unit_price"], old["units_per_order_uom"], old["order_uom"], old["supplier_item_version"]) != (
                new["unit_price"], new["units_per_order_uom"], new["order_uom"], new["supplier_item_version"]):
            problems.append(f"{old['sku']}: price or pack changed since this revision; refresh it")
    if fresh["supplier"]["order_email"] != content["supplier"]["order_email"]:
        problems.append("The supplier's verified order email changed; refresh the order")
    if fresh["ship_to"] != content["ship_to"]:
        problems.append("The ship-to address changed; refresh the order")
    return problems


def _recheck_quantities(session: Session, po: PurchaseOrder, content: dict[str, Any], checked_version: int) -> int:
    """
    `checked_version` is the version the order's numbers were computed from. If inputs
    changed since, recompute the plan and require every line's recommendation to be
    unchanged. Returns the version the order is now known to be consistent with.
    The caller holds a share lock on the version row, so in-flight input writes
    have committed (or are not yet started) and none can commit until we finish.
    """
    current = data_version.current(session, po.tenant_id, lock=True)
    if current == checked_version:
        return current
    ev = _plan_now(session, po)
    changed = _moved(content, ev.lines)
    if changed:
        raise StateConflict("Stock, sales or orders changed since these numbers were computed and the recommendation "
                            "moved. Use “Refresh” to load the new recommendation, then review and approve again",
                            details={"changed": changed})
    return ev.data_version


def approve(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, expected_revision: int,
            expected_digest: str) -> tuple[PurchaseOrder, bool]:
    """
    Owner approves exactly what they saw. Returns (po, newly_approved). A repeat of
    the same approval (double click, second approver) returns the PO unchanged.
    """
    authorize(actor, "po.approve")
    po = get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=True)  # serialises approvers
    existing = session.scalars(select(PoApproval).where(PoApproval.po_id == po.id,
                                                        PoApproval.revision == expected_revision)).one_or_none()
    if existing is not None and existing.digest == expected_digest and po.current_revision == expected_revision:
        return po, False
    if po.status != "awaiting_approval":
        raise StateConflict(f"Only orders awaiting approval can be approved (this one is {po.status.replace('_', ' ')})")
    rev = revision(session, po)
    if po.current_revision != expected_revision or rev.digest != expected_digest:
        raise StaleVersion("The order changed after you opened it; review the current revision",
                           details={"current_revision": po.current_revision})
    problems = _revalidate_terms(session, po, rev.content)
    if problems:
        raise StateConflict("This revision can no longer be approved as is", details={"problems": problems})
    pending = data_version.pending_inputs(session, tenant_id)
    if pending:
        raise StateConflict("Data is still being updated; approve when it finishes", details={"pending": pending})
    checked_version = _recheck_quantities(session, po, rev.content, po.data_version)

    session.add(PoApproval(tenant_id=tenant_id, po_id=po.id, revision=rev.revision, digest=rev.digest,
                           approved_by_user_id=actor.user_id, approved_role=actor.role, data_version=checked_version))
    po.status, po.data_version, po.updated_at = "queued", checked_version, _now()
    message = outbox.enqueue(session, tenant_id=tenant_id, topic=SEND_TOPIC,
                             operation_key=f"po:{po.id}:rev:{rev.revision}:send",
                             payload={"po_id": str(po.id), "revision": rev.revision, "digest": rev.digest})
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.approved", object_type="purchase_order",
                 object_id=po.id, after={"revision": rev.revision, "digest": rev.digest,
                                         "total": rev.content["totals"]["estimated_total"],
                                         "recipient": rev.content["supplier"]["order_email"],
                                         "send_job": str(message.id)})
    session.flush()
    return po, True


def send_check(session: Session, po: PurchaseOrder, approval: PoApproval) -> list[str]:
    """
    Re-checked by the sender right before sending: terms, recipient and supplier
    status still hold, and the recommendation has not moved since the approval.
    Any problem stops the send; the owner refreshes and approves again.
    """
    content = revision(session, po).content
    problems = _revalidate_terms(session, po, content)
    try:
        _recheck_quantities(session, po, content, approval.data_version)
    except StateConflict as exc:
        problems += [f"{c['sku']}: recommendation moved from {c['was']} to {c['now']}" for c in exc.details["changed"]]
    return problems
