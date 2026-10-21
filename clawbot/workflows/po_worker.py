"""
Sends approved purchase orders (outbox topic `po.send`).

The job carries (po, revision, digest). It sends only if that exact revision is
still the PO's current one, is approved with that digest, and the PO is queued —
so an order edited after approval is never sent from the stale job. The send
goes through the supplier contact gate; in this build that means `capture`
(stored, delivered to no one) — never a real supplier.

Jobs are not retry_safe: if a worker dies mid-send the outcome is unknown and the
message parks in `unknown` for a person, rather than possibly sending twice.

Run continuously:  python -m clawbot.workflows.po_worker
"""

from __future__ import annotations

import csv
import io
import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy import and_, func, select

from clawbot.domain import audit, outbox, purchasing
from clawbot.domain.errors import PermissionDenied
from clawbot.persistence.db import transaction
from clawbot.persistence.models import CapturedMessage, OutboxMessage, PoApproval, PoSendAttempt, PurchaseOrder
from clawbot.policies import supplier_contact
from clawbot.policies.permissions import authorize, system

log = logging.getLogger(__name__)
ACTOR = system("po-sender")


def render(content: dict) -> tuple[str, str, str]:
    """Subject, plain-text body and CSV attachment for a PO revision."""
    s, ship = content["supplier"], content["ship_to"]
    subject = f"Purchase order {content['po_number']} — {ship['name']}"
    lines = [f"{l['supplier_sku']}  {l['order_qty']} {l['order_uom']} (x{l['units_per_order_uom']})  "
             f"@ {l['unit_price']} {content['currency']} = {l['line_total']}" for l in content["lines"]]
    body = "\n".join([
        f"Purchase order {content['po_number']}", f"Account: {s['account_number'] or '-'}",
        f"Ship to: {ship['name']}, {content['address_text']}", "", *lines, "",
        f"Items subtotal: {content['totals']['subtotal']} {content['currency']}",
        "Shipping and tax: to be confirmed by supplier",
        "", "Please confirm quantities, prices and delivery date.",
    ])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["supplier_sku", "description", "order_qty", "order_uom", "units_per_order_uom", "unit_price", "line_total"])
    for l in content["lines"]:
        writer.writerow([l["supplier_sku"], l["name"], l["order_qty"], l["order_uom"], l["units_per_order_uom"],
                         l["unit_price"], l["line_total"]])
    return subject, body, buf.getvalue()


def _send(session, message) -> None:
    authorize(ACTOR, "po.send")
    payload = message.payload
    po = purchasing.get_po(session, tenant_id=message.tenant_id, po_id=uuid.UUID(payload["po_id"]), for_update=True)
    log_row = dict(tenant_id=po.tenant_id, po_id=po.id, revision=payload["revision"], outbox_message_id=message.id)
    approval = session.scalars(select(PoApproval).where(PoApproval.po_id == po.id,
                                                        PoApproval.revision == payload["revision"])).one_or_none()
    if (po.status != "queued" or po.current_revision != payload["revision"] or approval is None
            or approval.digest != payload["digest"]):
        session.add(PoSendAttempt(**log_row, mode="none", outcome="skipped",
                                  detail=f"Not sent: order is {po.status} at revision {po.current_revision}"))
        return
    content = purchasing.revision(session, po).content
    recipient = content["supplier"]["order_email"]
    problems = purchasing.send_check(session, po, approval)
    if problems:
        po.status = "failed"
        session.add(PoSendAttempt(**log_row, mode="none", recipient=recipient, outcome="blocked",
                                  detail="Not sent: " + "; ".join(problems) + ". Refresh the order and approve again."))
        audit.record(session, tenant_id=po.tenant_id, actor=ACTOR, action="po.send_blocked", object_type="purchase_order",
                     object_id=po.id, after={"revision": payload["revision"], "problems": problems})
        return
    try:
        decision = supplier_contact.check_send(recipient)
    except PermissionDenied as exc:
        po.status = "failed"
        session.add(PoSendAttempt(**log_row, mode=supplier_contact.send_mode(), recipient=recipient, outcome="refused",
                                  detail=str(exc)))
        audit.record(session, tenant_id=po.tenant_id, actor=ACTOR, action="po.send_refused", object_type="purchase_order",
                     object_id=po.id, after={"revision": payload["revision"]}, reason=str(exc))
        return
    if decision.delivers:  # no real transport exists in this build
        po.status = "failed"
        session.add(PoSendAttempt(**log_row, mode=decision.mode, recipient=recipient, outcome="refused",
                                  detail="No delivery transport is configured in this build"))
        audit.record(session, tenant_id=po.tenant_id, actor=ACTOR, action="po.send_refused", object_type="purchase_order",
                     object_id=po.id, after={"revision": payload["revision"]}, reason="no delivery transport")
        return
    subject, body, attachment = render(content)
    session.add(CapturedMessage(tenant_id=po.tenant_id, po_id=po.id, revision=payload["revision"], to_address=recipient,
                                subject=subject, body_text=body, attachment_name=f"{content['po_number']}.csv",
                                attachment_csv=attachment))
    po.status = "test_sent"
    session.add(PoSendAttempt(**log_row, mode=decision.mode, recipient=recipient, outcome="captured",
                              detail="Captured in Tabula; nothing was delivered to the supplier"))
    audit.record(session, tenant_id=po.tenant_id, actor=ACTOR, action="po.test_sent", object_type="purchase_order",
                 object_id=po.id, after={"revision": payload["revision"], "mode": decision.mode, "recipient": recipient})


def reconcile_stuck() -> int:
    """
    A queued order whose send job ended without a result (lease expired -> `unknown`,
    or `dead`) would stay "Queued" forever. In capture mode the capture and the job
    result commit together, so no captured message means nothing was captured:
    the order becomes failed with an explicit "outcome unknown" entry for the owner.
    (A live transport will need a provider status lookup here instead — CP7.)
    """
    fixed = 0
    with transaction() as session:
        stuck = session.execute(
            select(PurchaseOrder, OutboxMessage).join(OutboxMessage, and_(
                OutboxMessage.tenant_id == PurchaseOrder.tenant_id,
                OutboxMessage.operation_key == func.concat("po:", PurchaseOrder.id, ":rev:", PurchaseOrder.current_revision, ":send")))
            .where(PurchaseOrder.status == "queued", OutboxMessage.status.in_(("unknown", "dead")))
            .with_for_update(of=PurchaseOrder, skip_locked=True)).all()
        for po, message in stuck:
            captured = session.scalars(select(CapturedMessage.id).where(
                CapturedMessage.po_id == po.id, CapturedMessage.revision == po.current_revision)).first()
            po.status = "test_sent" if captured else "failed"
            session.add(PoSendAttempt(tenant_id=po.tenant_id, po_id=po.id, revision=po.current_revision, mode=supplier_contact.send_mode(),
                                      outcome="captured" if captured else "unknown", outbox_message_id=message.id,
                                      detail="The sender stopped before reporting a result. " + (
                                          "A capture was recorded." if captured else
                                          "No capture was recorded, so nothing was sent; refresh and approve again.")))
            audit.record(session, tenant_id=po.tenant_id, actor=ACTOR, action="po.send_reconciled", object_type="purchase_order",
                         object_id=po.id, after={"status": po.status, "job_status": message.status})
            fixed += 1
    return fixed


def run_once(*, limit: int = 10, lease: timedelta = timedelta(minutes=5)) -> int:
    reconcile_stuck()
    with transaction() as session:
        claimed = [(m.id, m.lease_token) for m in outbox.claim_batch(session, limit=limit, lease=lease, topics=(purchasing.SEND_TOPIC,))]
    for message_id, token in claimed:
        try:
            with transaction() as session:
                message = session.get(outbox.OutboxMessage, message_id)
                _send(session, message)
                outbox.mark_done(session, message_id, token)
        except outbox.LeaseLost:
            log.warning("po send job %s lost its lease", message_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("po send job %s failed", message_id)
            with transaction() as session:
                try:
                    outbox.mark_failed(session, message_id, token, f"{type(exc).__name__}: {exc}", outcome_unknown=True)
                except outbox.LeaseLost:
                    continue
                message = session.get(outbox.OutboxMessage, message_id)
                po = purchasing.get_po(session, tenant_id=message.tenant_id, po_id=uuid.UUID(message.payload["po_id"]))
                po.status = "failed"
                session.add(PoSendAttempt(tenant_id=po.tenant_id, po_id=po.id, revision=message.payload["revision"],
                                          mode=supplier_contact.send_mode(), outcome="failed", outbox_message_id=message_id,
                                          detail=f"{type(exc).__name__}: outcome unknown — check before resending"))
    return len(claimed)


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    while True:
        if run_once() == 0:
            time.sleep(2)


if __name__ == "__main__":  # pragma: no cover
    main()
