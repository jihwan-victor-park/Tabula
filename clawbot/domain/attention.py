"""
"What needs me?" for one store: every open decision or stale input, with why and the next step.

Read-only. Each item names the screen where it is resolved, so nothing waits silently:
an order that is held, a receipt nobody reconciled with the POS, a reply nobody reviewed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clawbot.domain import data_version, open_orders, po_progress
from clawbot.persistence.models import (
    PO_SENT_STATUSES,
    ConnectorAccount,
    ConnectorLocationLink,
    Import,
    InventoryMovement,
    InventorySnapshot,
    Location,
    PurchaseOrder,
    Receipt,
    ReceiptIssue,
    ReceiptLine,
    ReplenishmentLine,
    ReplenishmentRun,
    SalesLine,
    SupplierReply,
    Variant,
)

STOCK_STALE = timedelta(days=7)
SALES_STALE = timedelta(days=2)
REPLY_OVERDUE = timedelta(days=2)


def _item(kind: str, severity: str, title: str, why: str, action: str, href: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "severity": severity, "title": title, "why": why, "action": action, "href": href, **extra}


def _age(at: datetime | None, now: datetime) -> str:
    if at is None:
        return "never"
    days = (now - at).days
    return f"{days} day(s) ago" if days else "today"


def for_location(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    skus = dict(session.execute(select(Variant.id, Variant.sku).where(Variant.tenant_id == tenant_id)).all())

    # --- connections
    for acct in session.scalars(select(ConnectorAccount).join(ConnectorLocationLink, (
            ConnectorLocationLink.tenant_id == ConnectorAccount.tenant_id) & (
            ConnectorLocationLink.connector_account_id == ConnectorAccount.id)).where(
            ConnectorAccount.tenant_id == tenant_id, ConnectorLocationLink.location_id == location_id)):
        if acct.status != "active":
            out.append(_item("connection", "high", f"Square connection is {acct.status.replace('_', ' ')}",
                             acct.last_error or "Square stopped accepting Tabula's access.", "Reconnect", "/ops/connections"))
        elif acct.last_error:
            out.append(_item("connection", "medium", "Square sync is failing", acct.last_error[:300], "Open connections",
                             "/ops/connections"))

    # --- inputs
    pending_imports = session.scalars(select(Import).where(Import.tenant_id == tenant_id, Import.status == "uploaded")).all()
    for imp in pending_imports:
        if imp.context.get("location_id") not in (None, str(location_id)):
            continue  # another store's file
        out.append(_item("import", "medium", f"Review {imp.file_name}", "Uploaded but not confirmed; nothing from it is used yet.",
                         "Review the file", "/ops/imports", ref=str(imp.id)))
    location = session.get(Location, location_id)
    if location.inventory_write_owner == "tabula":
        last_stock = max(filter(None, [
            session.scalar(select(func.max(InventoryMovement.occurred_at)).where(
                InventoryMovement.tenant_id == tenant_id, InventoryMovement.location_id == location_id,
                InventoryMovement.reason == "count")),
            session.scalar(select(func.max(InventorySnapshot.as_of)).where(
                InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.location_id == location_id))]), default=None)
    else:  # the POS owns stock: only its own readings count
        last_stock = session.scalar(select(func.max(InventorySnapshot.as_of)).where(
            InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.location_id == location_id,
            InventorySnapshot.source_system == location.inventory_write_owner))
    if last_stock is None or now - last_stock > STOCK_STALE:
        out.append(_item("stale_stock", "high" if last_stock is None else "medium",
                         "Stock count is missing" if last_stock is None else "Stock count is old",
                         f"Last stock reading{' from ' + location.inventory_write_owner if location.inventory_write_owner != 'tabula' else ''}: "
                         f"{_age(last_stock, now)}. Recommendations use it as the starting stock.",
                         "Upload a stock count" if location.inventory_write_owner == "tabula" else "Sync stock from the POS",
                         "/ops/imports" if location.inventory_write_owner == "tabula" else "/ops/connections"))
    last_sale = session.scalar(select(func.max(SalesLine.sold_at)).where(
        SalesLine.tenant_id == tenant_id, SalesLine.location_id == location_id))
    if last_sale is None or now - last_sale > SALES_STALE:
        out.append(_item("stale_sales", "high" if last_sale is None else "medium",
                         "No sales yet" if last_sale is None else "Sales are not up to date",
                         f"Latest sale recorded: {_age(last_sale, now)}. Demand is estimated from sales.",
                         "Sync sales from Square" if location.sales_feed == "square" else "Import sales or connect Square",
                         "/ops/connections" if location.sales_feed == "square" else "/ops/imports"))

    # --- the plan
    run = session.scalars(select(ReplenishmentRun).where(
        ReplenishmentRun.tenant_id == tenant_id, ReplenishmentRun.location_id == location_id,
        ReplenishmentRun.status == "current")).one_or_none()
    if run is None:
        out.append(_item("plan", "medium", "No plan yet", "Compute a plan once sales and a stock count are in.",
                         "Compute plan", "/ops/today"))
    else:
        if run.data_version != data_version.current(session, tenant_id):
            out.append(_item("plan", "medium", "Plan is out of date",
                             "Stock, sales, orders or supplier answers changed after it was computed.",
                             "Recompute plan", "/ops/today"))
        for line in session.scalars(select(ReplenishmentLine).where(
                ReplenishmentLine.run_id == run.id, ReplenishmentLine.status == "on_hold")):
            refs = [r["message"] for r in line.result.get("reasons", []) if r["code"] in ("unconfirmed_open_order",
                                                                                         "confirmed_order_without_eta",
                                                                                         "overdue_delivery")]
            out.append(_item("held", "medium", f"{skus.get(line.variant_id, '?')}: reorder on hold",
                             "Already ordered, but not confirmed or not arriving on schedule. " + " ".join(refs[:2]),
                             "Record the supplier's answer", "/ops/orders"))

    # --- orders
    for po in session.scalars(select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.location_id == location_id,
            PurchaseOrder.status.in_(("awaiting_approval", "changes_proposed", "delivery_unknown", "failed", "test_sent",
                                      "supplier_confirmed", "partially_received")))):
        href = f"/ops/orders/{po.id}"
        if po.status == "awaiting_approval":
            out.append(_item("approve", "medium", f"{po.number} is waiting for the owner's approval", "", "Review and approve", href))
        elif po.status == "changes_proposed":
            out.append(_item("changes", "high", f"{po.number}: the supplier proposed changes",
                             "Price, product, pack or quantity changed; the owner decides.", "Decide changes", href))
        elif po.status == "delivery_unknown":
            out.append(_item("delivery_unknown", "high", f"{po.number}: delivery to the supplier is unknown",
                             "The sender stopped after handing it over; it may have arrived. Not resent automatically.",
                             "Check with the supplier", href))
        elif po.status == "failed":
            out.append(_item("failed", "medium", f"{po.number} was not sent", "See the order's send log for why.",
                             "Refresh and approve again", href))
        elif po.status == "test_sent" and po.sent_at and now - po.sent_at > REPLY_OVERDUE:
            out.append(_item("no_reply", "medium", f"{po.number}: no answer from the supplier",
                             f"Sent {_age(po.sent_at, now)}. Its quantities hold reordering until the supplier answers.",
                             "Record their reply", href))
        if po.status in PO_SENT_STATUSES:
            overdue = [l for l in po_progress.lines(session, po)
                       if l.eta and l.eta < now.date() and po_progress.state(l).outstanding > 0]
            if overdue:
                out.append(_item("late", "medium", f"{po.number}: delivery is late",
                                 f"{len(overdue)} line(s) were due by {min(l.eta for l in overdue).isoformat()}.",
                                 "Record a delivery or the supplier's new date", f"/ops/receiving/{po.id}"))
    for reply in session.scalars(select(SupplierReply).join(PurchaseOrder, (PurchaseOrder.tenant_id == SupplierReply.tenant_id) & (
            PurchaseOrder.id == SupplierReply.po_id)).where(
            SupplierReply.tenant_id == tenant_id, PurchaseOrder.location_id == location_id,
            SupplierReply.status == "pending_review")):
        out.append(_item("reply", "high", "A supplier reply is waiting for review",
                         "Nothing changes on the order until you confirm what the reply says.", "Review reply",
                         f"/ops/orders/{reply.po_id}"))

    # --- receiving
    for rl, po_id in session.execute(select(ReceiptLine, Receipt.po_id).join(Receipt, (Receipt.tenant_id == ReceiptLine.tenant_id) & (
            Receipt.id == ReceiptLine.receipt_id)).where(
            ReceiptLine.tenant_id == tenant_id, ReceiptLine.location_id == location_id,
            ReceiptLine.pos_status.in_(("pending_pos", "pos_reported")))):
        out.append(_item("pos_mismatch", "high", f"{skus.get(rl.variant_id, '?')}: received in Tabula, not reconciled with the POS",
                         ("Entered in the POS; compare the POS readings and sign off." if rl.pos_status == "pos_reported"
                          else "Enter the delivery in the POS, then reconcile.")
                         + f" New orders for this item are blocked meanwhile. Received {_age(rl.created_at, now)}.",
                         "Reconcile", f"/ops/receiving/{po_id}", ref=str(rl.id)))
    for issue in session.scalars(select(ReceiptIssue).join(PurchaseOrder, (PurchaseOrder.tenant_id == ReceiptIssue.tenant_id) & (
            PurchaseOrder.id == ReceiptIssue.po_id)).where(
            ReceiptIssue.tenant_id == tenant_id, PurchaseOrder.location_id == location_id, ReceiptIssue.status == "open")):
        out.append(_item("damage", "low", "Damaged goods to settle with the supplier",
                         "Not counted as coming again until the supplier confirms a replacement.", "Resolve",
                         f"/ops/receiving/{issue.po_id}"))

    # --- possible duplicate orders between an export and Tabula
    for (supplier_id, number), link in open_orders.links(session, tenant_id=tenant_id, location_id=location_id).items():
        if link.status == "suggested":
            out.append(_item("link", "high", f"Is open order {number} the same as {', '.join(link.candidates)}?",
                             "The numbers nearly match. It is not counted until you decide.", "Decide",
                             "/ops/today#links", supplier_id=str(supplier_id), external_po_number=number,
                             candidates=list(link.candidates)))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda i: order[i["severity"]])
