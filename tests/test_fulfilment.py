"""
CP7 / CP8: what happens after a PO is sent — supplier replies (reviewed by a person),
owner decisions on changes, receiving with damage, and how all of it feeds the plan.
The shop: LITTER-20, 18 on hand, 6/day, Phillips Pet case of 12 at $30, lead 4.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.utils import format_datetime

import pytest
from sqlalchemy import func, select, text

from clawbot.domain import inventory, purchasing, receiving
from clawbot.persistence.db import new_session, transaction
from clawbot.persistence.models import InventoryMovement, OutboxMessage, PoSendAttempt, PurchaseOrder
from clawbot.policies import supplier_contact
from clawbot.policies.permissions import system
from clawbot.workflows import po_worker
from tests.conftest import add_member
from tests.test_purchasing import _approve, _draft, _submit, ready  # noqa: F401
from tests.test_replenishment_flow import NY, shop  # noqa: F401


def _po(api, po_id) -> dict:
    return api.get(f"/v1/purchase-orders/{po_id}").json()


def _send(api, qty: str | None = None) -> dict:
    """Draft → (optional quantity edit) → submit → owner approval → worker captures it."""
    po = _draft(api)
    if qty is not None:
        po = api.client.patch(f"/v1/purchase-orders/{po['id']}/lines", json={
            "revision": po["revision"], "lines": [{"line_no": 1, "order_qty": qty}]}, headers=api.headers()).json()
    assert _approve(api, _submit(api, po)).status_code == 201
    po_worker.run_once()
    return _po(api, po["id"])


def _plan_line(api, sku="LITTER-20") -> dict:
    run = api.post("/v1/replenishment-runs", {"location_id": api.location_id}).json()
    return next(l for l in run["lines"] if l["sku"] == sku)


def _reply(api, po, body: str, when: datetime | None = None):
    """A pasted reply with a Date line (the supplier's own time), as a forwarded email has."""
    when = when or datetime.now(timezone.utc) - timedelta(seconds=30)
    return api.post(f"/v1/purchase-orders/{po['id']}/replies", {"source": "paste", "text": f"Date: {format_datetime(when)}\n{body}"})


def _apply(api, reply_id, decisions):
    return api.post(f"/v1/supplier-replies/{reply_id}/apply", {"decisions": decisions})


def _as_read(order, reply_id) -> list[dict]:
    """What the parser read, submitted unchanged (a person accepting the reading)."""
    reply = next(r for r in order["progress"]["replies"] if r["id"] == reply_id)
    return [{k: v for k, v in l.items() if k in ("line_no", "action", "confirmed_qty", "eta", "backorder", "change")}
            for l in reply["parsed"]["lines"]]


def _receipt(api, po, key, arrived, damaged="0"):
    return api.post(f"/v1/purchase-orders/{po['id']}/receipts", {
        "receipt_key": key, "lines": [{"line_no": 1, "arrived_qty": arrived, "damaged_qty": damaged}]})


def _on_hand(api) -> Decimal:
    with transaction() as s:
        return s.scalar(select(func.coalesce(func.sum(InventoryMovement.delta), 0)).where(
            InventoryMovement.tenant_id == uuid.UUID(api.tenant_id), InventoryMovement.reason == "receipt"))


# ---------------------------------------------------------------------------
# Sent ≠ accepted (plan holds, never projects)
# ---------------------------------------------------------------------------


def test_a_captured_order_holds_reordering_but_is_not_accepted_or_arriving(ready):
    po = _send(ready)
    assert (po["status"], po["progress"]["ack_status"]) == ("test_sent", "pending")
    (line,) = po["progress"]["lines"]
    assert (line["ordered"], line["confirmed"], line["unconfirmed"], line["outstanding"]) == ("5", None, "5", "0")
    plan = _plan_line(ready)
    assert plan["status"] == "on_hold" and plan["held_qty"] == "60"
    assert any("PO-00001" in r["message"] and "not confirmed" in r["message"] for r in plan["reasons"])
    assert all(d["arriving"] in ("0", "") or Decimal(d["arriving"]) == 0 for d in plan["projection"])


def test_partial_acceptance_counts_only_confirmed_inbound_and_releases_the_rest(ready):
    po = _send(ready)
    eta = (datetime.now(NY) + timedelta(days=3)).date()
    r = _reply(ready, po, f"PH-LIT-20: we can only ship 3 case, the remaining 2 cannot be supplied.\nDelivery {eta}.")
    assert r.status_code == 201
    order = r.json()["order"]
    reading = order["progress"]["replies"][0]["parsed"]["lines"][0]
    assert (reading["action"], reading["confirmed_qty"], reading["eta"]) == ("partial", "3", eta.isoformat())
    assert reading["evidence"][0]["text"].startswith("PH-LIT-20: we can only ship 3")  # the source line, shown to the person
    assert order["status"] == "test_sent"  # nothing applies until a person confirms the reading
    order = _apply(ready, r.json()["reply_id"], _as_read(order, r.json()["reply_id"])).json()
    (line,) = order["progress"]["lines"]
    assert (order["status"], order["progress"]["ack_status"]) == ("supplier_confirmed", "partially_accepted")
    assert (line["confirmed"], line["rejected"], line["unconfirmed"], line["outstanding"], line["eta"]) == (
        "3", "2", "0", "3", eta.isoformat())
    plan = _plan_line(ready)
    assert plan["status"] == "order"  # 2 cases will not come: the plan asks for more
    assert next(s for s in plan["steps"] if s["label"] == "Confirmed inbound arriving in the plan window")["value"] == "36"
    assert sum(Decimal(d["arriving"]) for d in plan["projection"] if d["arriving"]) >= 36


def test_full_acceptance_covering_the_need_is_not_called_enough_stock(ready):
    po = _send(ready)
    eta = (datetime.now(NY) + timedelta(days=3)).date()
    r = _reply(ready, po, f"We confirm your order {po['number']} in full. ETA {eta}.")
    _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"]))
    plan = _plan_line(ready)
    assert plan["status"] == "no_order"
    covered = next(x for x in plan["reasons"] if x["code"] == "covered_by_open_orders")
    assert "PO-00001" in covered["message"]


# ---------------------------------------------------------------------------
# Duplicate and out-of-order replies
# ---------------------------------------------------------------------------


def test_the_same_reply_twice_changes_nothing_and_an_older_reply_cannot_overwrite(ready):
    po = _send(ready)
    now = datetime.now(timezone.utc)
    newer = _reply(ready, po, "PH-LIT-20: confirmed 5 case.", when=now - timedelta(minutes=5))
    again = _reply(ready, po, "PH-LIT-20: confirmed 5 case.", when=now - timedelta(minutes=5))
    assert (newer.status_code, again.status_code) == (201, 200) and newer.json()["reply_id"] == again.json()["reply_id"]
    rid = newer.json()["reply_id"]
    decisions = _as_read(newer.json()["order"], rid)
    first = _apply(ready, rid, decisions).json()
    second = _apply(ready, rid, decisions)
    assert second.status_code == 200 and second.json()["progress"]["lines"] == first["progress"]["lines"]
    assert first["progress"]["lines"][0]["confirmed"] == "5"
    # A reply the supplier sent earlier, pasted later, says something else: it must not win.
    older = _reply(ready, po, "PH-LIT-20 is out of stock.", when=now - timedelta(hours=2))
    resp = _apply(ready, older.json()["reply_id"], _as_read(older.json()["order"], older.json()["reply_id"]))
    assert resp.status_code == 409 and "newer reply" in resp.json()["detail"]
    after = _po(ready, po["id"])
    assert after["progress"]["lines"][0]["confirmed"] == "5"
    assert next(r for r in after["progress"]["replies"] if r["id"] == older.json()["reply_id"])["status"] == "stale"


def test_a_reply_quoting_the_order_does_not_read_our_own_quantities_as_confirmation(ready):
    po = _send(ready)
    body = ("Thanks, we'll check stock.\n\n-----Original Message-----\n"
            "PH-LIT-20  5 case (x12)  @ 30 USD = 150.00\nPlease confirm quantities.")
    r = _reply(ready, po, body).json()
    reading = r["order"]["progress"]["replies"][0]["parsed"]
    assert reading["lines"][0]["action"] == "none" and reading["warnings"]


# ---------------------------------------------------------------------------
# Changes need the owner
# ---------------------------------------------------------------------------


def test_a_price_change_waits_for_the_owner_and_binds_to_the_proposal(ready):
    po = _send(ready)
    r = _reply(ready, po, "PH-LIT-20: price is now $33.00 per case.")
    order = _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"])).json()
    (line,) = order["progress"]["lines"]
    assert order["status"] == "changes_proposed" and line["confirmed"] is None
    assert line["proposal"]["kind"] == "price" and line["proposal"]["unit_price"] == "33"
    plan = _plan_line(ready)
    assert plan["status"] == "on_hold"  # still held, not counted as arriving at a price nobody accepted
    manager = add_member(ready, "mgr@example.com", "manager")
    body = {"decision": "accept", "proposal_digest": line["proposal"]["digest"]}
    assert manager.post(f"/v1/purchase-orders/{po['id']}/lines/1/proposal", body).status_code == 403
    assert ready.post(f"/v1/purchase-orders/{po['id']}/lines/1/proposal",
                      {**body, "proposal_digest": "0" * 64}).status_code == 409
    done = ready.post(f"/v1/purchase-orders/{po['id']}/lines/1/proposal", body).json()
    (line,) = done["progress"]["lines"]
    assert (done["status"], line["confirmed"], line["unit_price"], line["proposal"]) == ("supplier_confirmed", "5", "33", None)


def test_a_substitute_is_not_accepted_until_it_is_a_known_supplier_item(ready):
    po = _send(ready)
    r = _reply(ready, po, "PH-LIT-20 is discontinued; we can offer PH-LIT-20-ALT instead, 5 case.")
    order = _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"])).json()
    proposal = order["progress"]["lines"][0]["proposal"]
    assert (proposal["kind"], proposal["substitute_sku"]) == ("substitute", "PH-LIT-20-ALT")
    resp = ready.post(f"/v1/purchase-orders/{po['id']}/lines/1/proposal",
                      {"decision": "accept", "proposal_digest": proposal["digest"]})
    assert resp.status_code == 409 and "PH-LIT-20-ALT" in resp.json()["detail"]
    declined = ready.post(f"/v1/purchase-orders/{po['id']}/lines/1/proposal",
                          {"decision": "decline", "proposal_digest": proposal["digest"]}).json()
    assert declined["status"] == "closed" and declined["progress"]["ack_status"] == "rejected"
    assert _plan_line(ready)["status"] == "order"  # nothing is coming: order again


# ---------------------------------------------------------------------------
# Receiving: 10 ordered, 8 arrive, 1 damaged
# ---------------------------------------------------------------------------


def test_partial_receipt_with_damage_posts_sellable_once_and_keeps_the_rest_expected(ready):
    po = _send(ready, qty="10")
    r = _reply(ready, po, f"Order {po['number']} confirmed in full.")
    _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"]))
    resp = _receipt(ready, po, "rcv-1", "8", "1")
    assert resp.status_code == 201
    order = resp.json()["order"]
    (line,) = order["progress"]["lines"]
    assert (line["received"], line["damaged"], line["sellable_received"], line["outstanding"]) == ("8", "1", "7", "2")
    assert order["status"] == "partially_received"
    assert [(i["qty"], i["status"]) for i in order["progress"]["issues"]] == [("1", "open")]
    assert _on_hand(ready) == Decimal(84)  # 7 sellable cases × 12
    # The same submit again (double click, retry): same receipt, stock unchanged.
    again = _receipt(ready, po, "rcv-1", "8", "1")
    assert again.status_code == 200 and again.json()["receipt_id"] == resp.json()["receipt_id"]
    assert _on_hand(ready) == Decimal(84)
    assert _receipt(ready, po, "rcv-1", "7", "0").status_code == 409  # same key, different content
    # Damaged goods are not expected again until the supplier confirms a replacement.
    plan = _plan_line(ready)
    assert next(s for s in plan["steps"] if s["label"] == "Confirmed inbound arriving in the plan window")["value"] in ("24", "0")
    issue = order["progress"]["issues"][0]["id"]
    eta = (datetime.now(NY) + timedelta(days=2)).date().isoformat()
    after = ready.post(f"/v1/receipt-issues/{issue}/resolve", {"resolution": "replacement_confirmed", "qty": "1", "eta": eta}).json()
    assert after["progress"]["lines"][0]["outstanding"] == "3"
    # Too much arriving is refused, not silently absorbed.
    assert _receipt(ready, po, "rcv-2", "4").status_code == 422
    final = _receipt(ready, po, "rcv-3", "3").json()["order"]
    assert final["status"] == "closed" and final["progress"]["lines"][0]["outstanding"] == "0"


def test_receipts_wait_for_each_other_on_the_same_order(ready):
    """Controlled interleaving: a receipt is held mid-way while another one runs; the second sees the first."""
    po = _send(ready, qty="10")
    r = _reply(ready, po, "All items confirmed.")
    _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"]))
    holder = new_session()
    holder.begin()
    tenant, owner = uuid.UUID(ready.tenant_id), None
    with transaction() as s:
        owner = purchasing.get_po(s, tenant_id=tenant, po_id=uuid.UUID(po["id"])).created_by_user_id
    from clawbot.policies.permissions import human

    receiving.record_receipt(holder, tenant_id=tenant, actor=human(owner, "owner"), po_id=uuid.UUID(po["id"]),
                             receipt_key="held", lines=[receiving.ReceiveLine(1, Decimal(6))])  # holds the order's lock
    result: dict = {}
    started = threading.Event()

    def other():
        started.set()
        result["resp"] = _receipt(ready, po, "other", "6")

    t = threading.Thread(target=other)
    t.start()
    started.wait()
    t.join(timeout=0.5)
    assert t.is_alive()  # blocked behind the open receipt, not reading a stale "10 expected"
    holder.commit()
    holder.close()
    t.join()
    assert result["resp"].status_code == 422 and result["resp"].json()["details"]["expected"] == "4"
    assert _po(ready, po["id"])["progress"]["lines"][0]["received"] == "6"


def test_the_same_receipt_from_two_tabs_at_once_is_recorded_once(ready):
    po = _send(ready, qty="10")
    barrier, codes = threading.Barrier(2), []

    def submit():
        barrier.wait()
        codes.append(_receipt(ready, po, "tab", "5").status_code)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 201]
    assert _on_hand(ready) == Decimal(60)


# ---------------------------------------------------------------------------
# POS-owned stock: Tabula cannot write it
# ---------------------------------------------------------------------------


def test_receipt_at_a_pos_owned_location_flags_a_mismatch_and_blocks_new_orders_until_the_pos_shows_it(ready):
    po = _send(ready, qty="10")
    with transaction() as s:
        s.execute(text("UPDATE locations SET inventory_write_owner = 'square' WHERE id = :id"), {"id": ready.location_id})
    order = _receipt(ready, po, "pos-1", "4").json()["order"]
    (rl,) = order["progress"]["receipts"][0]["lines"]
    assert rl["pos_status"] == "pending_pos" and _on_hand(ready) == 0  # nothing written to stock Tabula does not own
    assert order["progress"]["lines"][0]["pos_pending"]
    tenant = uuid.UUID(ready.tenant_id)
    with transaction() as s:
        blocked = receiving.pos_unconfirmed(s, tenant_id=tenant, location_id=uuid.UUID(ready.location_id))
    assert uuid.UUID(ready.variant["id"]) in blocked
    reported = ready.post(f"/v1/receipt-lines/{rl['id']}/pos-entered", {}).json()
    assert reported["progress"]["receipts"][0]["lines"][0]["pos_status"] == "pos_reported"
    with transaction() as s:  # still pending: no POS reading since the report
        assert uuid.UUID(ready.variant["id"]) in receiving.pos_unconfirmed(s, tenant_id=tenant, location_id=uuid.UUID(ready.location_id))
        inventory.record_snapshot(s, tenant_id=tenant, actor=system("square-sync"), variant_id=uuid.UUID(ready.variant["id"]),
                                  location_id=uuid.UUID(ready.location_id), quantity=Decimal(66),
                                  as_of=datetime.now(timezone.utc) + timedelta(seconds=1), source_system="square",
                                  source_ref="inv-after")
    with transaction() as s:
        assert receiving.pos_unconfirmed(s, tenant_id=tenant, location_id=uuid.UUID(ready.location_id)) == {}


def test_a_pos_mismatch_is_a_blocker_on_new_drafts(ready):
    po = _send(ready, qty="10")
    with transaction() as s:
        s.execute(text("UPDATE locations SET inventory_write_owner = 'square' WHERE id = :id"), {"id": ready.location_id})
    _receipt(ready, po, "pos-2", "10")
    with transaction() as s:
        p = purchasing.get_po(s, tenant_id=uuid.UUID(ready.tenant_id), po_id=uuid.UUID(po["id"]))
        content = purchasing.build_content(s, p, [{"supplier_item_id": po["content"]["lines"][0]["supplier_item_id"],
                                                    "sku": "LITTER-20", "order_qty": "1", "recommendation": {}}])
    assert "line 1: stock_not_confirmed_in_pos" in content["blockers"]


# ---------------------------------------------------------------------------
# A transport that cannot prove what happened
# ---------------------------------------------------------------------------


def test_a_lost_send_on_a_real_transport_is_delivery_unknown_held_and_never_resent(ready, monkeypatch):
    po = _submit(ready, _draft(ready))
    _approve(ready, po)
    monkeypatch.setattr(supplier_contact, "outcome_verifiable", lambda mode: False)  # e.g. an email adapter
    with transaction() as s:
        s.execute(text("UPDATE outbox SET status = 'unknown' WHERE topic = 'po.send'"))
    po_worker.run_once()
    po_worker.run_once()
    order = _po(ready, po["id"])
    assert order["status"] == "delivery_unknown" and order["captured_message"] is None
    assert "may already have delivered" in order["send_attempts"][-1]["detail"]
    with transaction() as s:
        assert s.scalar(select(OutboxMessage.status).where(OutboxMessage.topic == "po.send")) == "unknown"
        assert s.scalar(select(func.count()).select_from(PoSendAttempt)) == 1  # not retried
    assert _plan_line(ready)["status"] == "on_hold"  # it may have arrived at the supplier: do not order twice
    resolved = ready.post(f"/v1/purchase-orders/{po['id']}/delivery-outcome",
                          {"outcome": "not_received", "note": "Phoned Phillips, no email received"}).json()
    assert resolved["status"] == "failed"
    assert _plan_line(ready)["status"] == "order"


# ---------------------------------------------------------------------------
# Scope and isolation
# ---------------------------------------------------------------------------


def test_checks_for_one_order_do_not_replace_the_stores_current_plan(ready):
    before = ready.get("/v1/recommendations", params={"location_id": ready.location_id}).json()["run"]["id"]
    po = _submit(ready, _draft(ready))
    ready.client.put("/v1/replenishment/policy", json={"changes": {"max_unconfirmed_age_days": 10}}, headers=ready.headers())
    assert _approve(ready, po).status_code == 201  # recomputed for the check
    po_worker.run_once()
    after = ready.get("/v1/recommendations", params={"location_id": ready.location_id}).json()
    assert after["run"]["id"] == before and after["stale"]  # same plan, marked out of date — not silently swapped


def test_another_workspace_cannot_touch_replies_or_receipts(client, ready):
    po = _send(ready)
    r = _reply(ready, po, "PH-LIT-20 confirmed.")
    from tests.conftest import new_store

    rival = new_store(client, "rival@example.com", "Rival")
    assert rival.post(f"/v1/purchase-orders/{po['id']}/replies", {"source": "paste", "text": "x"}).status_code == 404
    assert rival.post(f"/v1/supplier-replies/{r.json()['reply_id']}/apply", {"decisions": []}).status_code == 404
    assert _receipt(rival, po, "k", "1").status_code == 404
    receiver = add_member(ready, "recv@example.com", "receiver")
    assert _receipt(receiver, po, "k", "1").status_code == 201  # receivers record deliveries
    assert receiver.post(f"/v1/purchase-orders/{po['id']}/replies", {"source": "paste", "text": "x"}).status_code == 403


# ---------------------------------------------------------------------------
# Reading replies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("body, action, extra", [
    ("PH-LIT-20 confirmed, ships Oct 30", "accept", {}),
    ("PH-LIT-20: 3 cases now, 2 on backorder to follow", "partial", {"backorder": True}),
    ("PH-LIT-20 out of stock", "reject", {}),
    ("PH-LIT-20 now packed 24 per case", "change", {"kind": "pack"}),
    ("PH-LIT-20: we can send 7 cases", "change", {"kind": "qty_increase"}),
    ("Please cancel the remaining PH-LIT-20", "cancel_remaining", {}),
    ("PH-LIT-20 hmm let me check", "unclear", {}),
])
def test_reading_common_reply_phrasings(ready, body, action, extra):
    po = _send(ready)
    line = _reply(ready, po, body).json()["order"]["progress"]["replies"][0]["parsed"]["lines"][0]
    assert line["action"] == action
    if "backorder" in extra:
        assert line["backorder"] is True
    if "kind" in extra:
        assert line["change"]["kind"] == extra["kind"]


def test_a_csv_confirmation_sheet_is_read_per_row(ready):
    po = _send(ready)
    csv_ = "supplier_sku,status,qty,eta\nPH-LIT-20,partial,4,2026-11-02\nPH-XX-1,confirmed,1,\n"
    resp = ready.client.post(f"/v1/purchase-orders/{po['id']}/replies/upload", headers=ready.headers(),
                             data={"replied_at": datetime.now(timezone.utc).isoformat()},
                             files={"file": ("confirm.csv", csv_.encode(), "text/csv")})
    parsed = resp.json()["order"]["progress"]["replies"][0]["parsed"]
    assert (parsed["lines"][0]["action"], parsed["lines"][0]["confirmed_qty"], parsed["lines"][0]["eta"]) == (
        "partial", "4", "2026-11-02")
    assert any("PH-XX-1" in w for w in parsed["warnings"])


def test_a_backordered_remainder_that_turns_up_is_not_still_unconfirmed(ready):
    po = _send(ready)
    r = _reply(ready, po, "PH-LIT-20: 3 cases now, 2 on backorder to follow")
    _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"]))
    line = _receipt(ready, po, "all", "5").json()["order"]["progress"]["lines"][0]
    assert (line["confirmed"], line["unconfirmed"], line["outstanding"]) == ("3", "0", "0")


def test_our_own_po_in_an_open_orders_export_is_counted_once(ready):
    from tests.test_imports import _apply as apply_import, _csv, _mapping, _upload

    po = _send(ready)
    rows = [["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"], ["Phillips Pet", po["number"], "LITTER-20", "60", "no"]]
    imp = _upload(ready, "open_orders", _csv(rows), name="open.csv", location_id=ready.location_id).json()
    _mapping(ready, imp, as_of=datetime.now(timezone.utc).isoformat(), complete_scope="none", quantity_unit="base")
    apply_import(ready, imp)
    plan = _plan_line(ready)
    assert plan["held_qty"] == "60"  # not 120


# ---------------------------------------------------------------------------
# Review CP7/CP8 regressions
# ---------------------------------------------------------------------------


def test_a_manager_cannot_wave_a_price_change_through_as_accepted(ready):
    po = _send(ready)
    r = _reply(ready, po, "PH-LIT-20: price is now $33.00 per case.")
    manager = add_member(ready, "mgr@example.com", "manager")
    resp = _apply(manager, r.json()["reply_id"], [{"line_no": 1, "action": "accept"}])
    assert resp.status_code == 403
    assert _po(ready, po["id"])["progress"]["lines"][0]["confirmed"] is None
    owner = _apply(ready, r.json()["reply_id"], [{"line_no": 1, "action": "accept"}]).json()  # recorded override
    reply = owner["progress"]["replies"][0]
    assert reply["applied"]["owner_overrides"] == [1]


def test_a_pasted_reply_needs_the_suppliers_time(ready):
    po = _send(ready)
    resp = ready.post(f"/v1/purchase-orders/{po['id']}/replies", {"source": "paste", "text": "PH-LIT-20 confirmed"})
    assert resp.status_code == 422 and resp.json()["details"]["needs"] == "replied_at"


def test_the_same_email_with_or_without_headers_is_one_reply(ready):
    po = _send(ready)
    when = datetime.now(timezone.utc) - timedelta(minutes=1)
    a = _reply(ready, po, "Hello,\r\nPH-LIT-20   confirmed 5 case.\r\n", when=when)
    b = ready.post(f"/v1/purchase-orders/{po['id']}/replies", {
        "source": "paste", "text": "Hello,\nPH-LIT-20 confirmed 5 case.", "replied_at": when.isoformat()})
    assert b.status_code == 200 and b.json()["reply_id"] == a.json()["reply_id"]


def _add_substitute_item(api, sku="PH-LIT-20-ALT", price="31.00"):
    from tests.test_suppliers import _confirm, _item, _price

    alt = api.post("/v1/variants", {"sku": "LITTER-20-ALT", "name": "Litter 20lb unscented"}).json()
    item = _confirm(api, _item(api, api.supplier["id"], sku=sku, per="12"), alt["id"])
    _price(api, item["id"], price)
    return alt


def test_after_a_substitute_a_later_all_confirmed_reply_does_not_revive_the_replaced_line(ready):
    _add_substitute_item(ready)
    ready.run = ready.post("/v1/replenishment-runs", {"location_id": ready.location_id}).json()
    po = _send(ready)
    r = _reply(ready, po, "PH-LIT-20 is discontinued; we can offer PH-LIT-20-ALT instead, 5 case.",
               when=datetime.now(timezone.utc) - timedelta(minutes=10))
    order = _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"])).json()
    proposal = order["progress"]["lines"][0]["proposal"]
    assert proposal["substitute_unit_price"] == "31"  # shown to the owner before deciding
    order = ready.post(f"/v1/purchase-orders/{po['id']}/lines/1/proposal",
                       {"decision": "accept", "proposal_digest": proposal["digest"]}).json()
    later = _reply(ready, po, "All items confirmed, but delivery moves to 2026-12-01 — truck delayed.")
    reading = {l["line_no"]: l for l in later.json()["order"]["progress"]["replies"][0]["parsed"]["lines"]}
    assert reading[1]["action"] == "none" and reading[2]["action"] == "accept"
    done = _apply(ready, later.json()["reply_id"], _as_read(later.json()["order"], later.json()["reply_id"])).json()
    outstanding = sum(Decimal(l["outstanding"]) + Decimal(l["unconfirmed"]) for l in done["progress"]["lines"])
    assert outstanding == 5
    assert _apply(ready, later.json()["reply_id"], [{"line_no": 1, "action": "accept"}]).status_code in (409, 422)


@pytest.mark.parametrize("body, action", [
    ("PH-LIT-20 confirmed, ships in 2 days", "accept"),
    ("PH-LIT-20 will ship by 3pm", "accept"),
    ("PH-LIT-20 confirmed for PO 1042", "accept"),
    ("PH-LIT-20 ok, $30.00 each", "accept"),
    ("PH-LIT-20 confirmed 5 cases, total $150.00", "accept"),
    ("PH-LIT-20 we have 250 on hand", "unclear"),
    ("PH-LIT-20 Order #4471 ships Monday", "accept"),
])
def test_numbers_that_are_not_quantities_are_not_read_as_quantities(ready, body, action):
    po = _send(ready)
    line = _reply(ready, po, body).json()["order"]["progress"]["replies"][0]["parsed"]["lines"][0]
    assert line["action"] == action and (line["confirmed_qty"] in (None, "5"))


def test_declining_more_than_ordered_keeps_what_was_ordered(ready):
    po = _send(ready)
    r = _reply(ready, po, "PH-LIT-20: we can send 7 cases")
    order = _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"])).json()
    p = order["progress"]["lines"][0]["proposal"]
    done = ready.post(f"/v1/purchase-orders/{po['id']}/lines/1/proposal", {"decision": "decline", "proposal_digest": p["digest"]}).json()
    line = done["progress"]["lines"][0]
    assert (done["status"], line["confirmed"], line["rejected"]) == ("supplier_confirmed", "5", "0")


def test_a_confirmed_replacement_counts_even_if_the_supplier_never_answered_the_order(ready):
    po = _send(ready, qty="10")
    order = _receipt(ready, po, "early", "8", "1").json()["order"]  # goods arrive before any reply
    issue = order["progress"]["issues"][0]["id"]
    line = ready.post(f"/v1/receipt-issues/{issue}/resolve", {"resolution": "replacement_confirmed", "qty": "1"}).json()["progress"]["lines"][0]
    assert (line["unconfirmed"], line["outstanding"]) == ("2", "1")


def test_the_mode_a_job_was_sent_in_decides_a_lost_outcome(ready, monkeypatch):
    po = _submit(ready, _draft(ready))
    _approve(ready, po)
    monkeypatch.setattr(po_worker, "_send", lambda session, message: (_ for _ in ()).throw(RuntimeError("smtp died")))
    monkeypatch.setenv("TABULA_SUPPLIER_SEND_MODE", "test_only")  # a delivering transport
    po_worker.run_once()
    monkeypatch.setenv("TABULA_SUPPLIER_SEND_MODE", "capture")  # restarted in capture
    order = _po(ready, po["id"])
    assert order["status"] == "delivery_unknown"
    with transaction() as s:
        assert s.scalar(select(OutboxMessage.payload["send_mode"].astext).where(OutboxMessage.topic == "po.send")) == "test_only"


def test_an_old_export_does_not_revive_a_closed_tabula_order(ready):
    from tests.test_imports import _apply as apply_import, _csv, _mapping, _upload

    po = _send(ready)
    r = _reply(ready, po, "All items confirmed.")
    _apply(ready, r.json()["reply_id"], _as_read(r.json()["order"], r.json()["reply_id"]))
    assert _receipt(ready, po, "all", "5").json()["order"]["status"] == "closed"
    rows = [["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"], ["Phillips Pet", po["number"], "LITTER-20", "60", "yes"]]
    imp = _upload(ready, "open_orders", _csv(rows), name="old.csv", location_id=ready.location_id).json()
    _mapping(ready, imp, as_of=datetime.now(timezone.utc).isoformat(), complete_scope="none", quantity_unit="base")
    apply_import(ready, imp)
    plan = _plan_line(ready)
    assert not any(po["number"] in s.get("formula", "") for s in plan["steps"])
