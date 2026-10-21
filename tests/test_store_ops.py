"""
Real-store readiness: linking export orders to Tabula POs by number only, reconciling receipts
with a POS that Tabula cannot write, one sales source per location, refunds vs restock,
Square token refresh / reconnect / scheduled reconciliation, and the "needs attention" list.
All against mock Square; Sandbox verification is scripts/square_sandbox_check.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select, text

from clawbot.domain import inventory, receiving
from clawbot.persistence.db import transaction
from clawbot.policies.permissions import system
from tests.test_fulfilment import _as_read, _apply, _plan_line, _receipt, _reply, _send
from tests.test_imports import _apply as apply_import, _csv, _mapping, _upload
from tests.test_purchasing import ready  # noqa: F401
from tests.test_replenishment_flow import NY, shop  # noqa: F401


def _open_orders(api, number, qty="60", confirmed="no"):
    rows = [["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"], ["Phillips Pet", number, "LITTER-20", qty, confirmed]]
    imp = _upload(api, "open_orders", _csv(rows), name=f"open-{number}.csv", location_id=api.location_id).json()
    _mapping(api, imp, as_of=datetime.now(timezone.utc).isoformat(), complete_scope="none", quantity_unit="base")
    apply_import(api, imp)


# ---------------------------------------------------------------------------
# Export orders vs Tabula POs: by number only, a person decides near matches
# ---------------------------------------------------------------------------


def test_a_near_matching_number_is_not_counted_until_a_person_decides(ready):
    po = _send(ready)  # PO-00001, 5 cases = 60 held
    _open_orders(ready, "PO00001")
    plan = _plan_line(ready)
    assert plan["held_qty"] == "60"  # not 120: the near match is not added on top …
    assert any(r["code"] == "input_needs_decision" and "PO00001" in r["message"] for r in plan["reasons"])  # … and it says so
    links = ready.get("/v1/open-order-links", params={"location_id": ready.location_id}).json()
    (link,) = links
    assert (link["status"], [c["number"] for c in link["candidates"]]) == ("suggested", ["PO-00001"])
    attention = ready.get("/v1/attention", params={"location_id": ready.location_id}).json()
    assert any(a["kind"] == "link" for a in attention)
    body = {"location_id": ready.location_id, "supplier_id": link["supplier_id"], "external_po_number": "PO00001"}
    # "A different order": counted as its own (held, unconfirmed) order.
    ready.post("/v1/open-order-links", {**body, "decision": "different_order", "note": "their own reference"})
    assert _plan_line(ready)["held_qty"] == "120"
    # "The same order": counted once.
    ready.post("/v1/open-order-links", {**body, "decision": "same_order", "po_id": po["id"]})
    assert _plan_line(ready)["held_qty"] == "60"


def test_same_items_and_quantities_never_make_two_orders_one(ready):
    _send(ready)
    _open_orders(ready, "INV-7781")  # LITTER-20 × 60, like PO-00001 — a different order all the same
    links = ready.get("/v1/open-order-links", params={"location_id": ready.location_id}).json()
    assert links[0]["status"] == "separate"
    assert _plan_line(ready)["held_qty"] == "120"


def test_a_link_decision_needs_a_sent_order_from_the_same_supplier(ready):
    po = _draft = ready.post("/v1/purchase-orders/from-run", {"run_id": ready.run["id"]}).json()[0]
    _open_orders(ready, "PO00001")
    link = ready.get("/v1/open-order-links", params={"location_id": ready.location_id}).json()[0]
    resp = ready.post("/v1/open-order-links", {"location_id": ready.location_id, "supplier_id": link["supplier_id"],
                                               "external_po_number": "PO00001", "decision": "same_order", "po_id": po["id"]})
    assert resp.status_code == 422  # a draft was never sent; it cannot be the supplier's open order


# ---------------------------------------------------------------------------
# Receipts at a POS-owned location: evidence + a person's sign-off
# ---------------------------------------------------------------------------


def _pos_owned(api):
    with transaction() as s:
        s.execute(text("UPDATE locations SET inventory_write_owner = 'square' WHERE id = :id"), {"id": api.location_id})


def _pos_reading(api, qty, at):
    with transaction() as s:
        inventory.record_snapshot(s, tenant_id=uuid.UUID(api.tenant_id), actor=system("square-sync"),
                                  variant_id=uuid.UUID(api.variant["id"]), location_id=uuid.UUID(api.location_id),
                                  quantity=Decimal(qty), as_of=at, source_system="square", source_ref=f"r-{at.isoformat()}")


def test_a_newer_pos_reading_alone_does_not_clear_a_receipt(ready):
    po = _send(ready, qty="10")
    _pos_owned(ready)
    now = datetime.now(timezone.utc)
    _pos_reading(ready, 18, now - timedelta(minutes=5))
    order = _receipt(ready, po, "pos", "4").json()["order"]  # 48 sellable units
    rl = order["progress"]["receipts"][0]["lines"][0]["id"]
    ready.post(f"/v1/receipt-lines/{rl}/pos-entered", {})
    _pos_reading(ready, 18, now + timedelta(seconds=2))  # the POS still shows 18: the delivery never got in
    ev = ready.get(f"/v1/receipt-lines/{rl}/pos-evidence").json()
    assert (ev["assessment"], ev["expected_after"], ev["unexplained"]) == ("receipt_missing_in_pos", "66", "-48")
    attention = ready.get("/v1/attention", params={"location_id": ready.location_id}).json()
    assert any(a["kind"] == "pos_mismatch" for a in attention)  # still flagged, with where to go
    resp = ready.post(f"/v1/receipt-lines/{rl}/pos-reconcile", {"outcome": "matches"})
    assert resp.status_code == 422  # the evidence does not support "matches" without saying what was checked
    manager_ok = ready.post(f"/v1/receipt-lines/{rl}/pos-reconcile",
                            {"outcome": "corrected_in_pos", "note": "Entered the 48 units in Square at 3pm"})
    assert manager_ok.status_code == 200
    rec = manager_ok.json()["progress"]["receipts"][0]["lines"][0]
    assert rec["pos_status"] == "pos_reconciled"


def test_sales_and_restocked_refunds_between_readings_are_accounted_for(ready):
    po = _send(ready, qty="10")
    _pos_owned(ready)
    now = datetime.now(timezone.utc)
    _pos_reading(ready, 18, now - timedelta(minutes=30))
    order = _receipt(ready, po, "pos", "4").json()["order"]
    rl = order["progress"]["receipts"][0]["lines"][0]["id"]
    rows = [["Date", "Transaction ID", "SKU", "Qty", "Type", "Restocked"],
            [(now - timedelta(minutes=10)).isoformat(), "S-1", "LITTER-20", "5", "sale", ""],
            [(now - timedelta(minutes=9)).isoformat(), "S-2", "LITTER-20", "2", "refund", "yes"],
            [(now - timedelta(minutes=8)).isoformat(), "S-3", "LITTER-20", "1", "refund", ""]]
    apply_import(ready, _upload(ready, "sales", _csv(rows), name="between.csv", location_id=ready.location_id,
                                source_system="square").json())
    ready.post(f"/v1/receipt-lines/{rl}/pos-entered", {})
    _pos_reading(ready, 18 + 48 - 5 + 2, now + timedelta(seconds=2))
    ev = ready.get(f"/v1/receipt-lines/{rl}/pos-evidence").json()
    assert (ev["units_sold"], ev["refunds_restocked"], ev["refunds_restock_unknown"]) == ("5", "2", "1")
    # 18 + 48 received − 5 sold + 2 restocked = 63 = the reading. But one refund's restock is unknown,
    # so a zero difference is not taken as proof on its own.
    assert (ev["expected_after"], ev["unexplained"], ev["assessment"]) == ("63", "0", "consistent_if_refunds_not_restocked")
    assert ready.post(f"/v1/receipt-lines/{rl}/pos-reconcile", {"outcome": "matches"}).status_code == 422


# ---------------------------------------------------------------------------
# Refunds are not restock
# ---------------------------------------------------------------------------


def test_a_refund_adds_stock_only_when_it_was_restocked(shop):
    now = datetime.now(NY)
    rows = [["Date", "Transaction ID", "SKU", "Qty", "Type", "Restocked"],
            [(now - timedelta(minutes=3)).isoformat(), "RF-1", "LITTER-20", "2", "refund", "no"],
            [(now - timedelta(minutes=2)).isoformat(), "RF-2", "LITTER-20", "3", "refund", ""],
            [(now - timedelta(minutes=1)).isoformat(), "RF-3", "LITTER-20", "4", "refund", "yes"]]
    apply_import(shop, _upload(shop, "sales", _csv(rows), name="refunds.csv", location_id=shop.location_id,
                                    source_system="square").json())
    line = _plan_line(shop)
    assert line["on_hand"] == "22"  # 18 counted + 4 restocked; the other 5 refunded units are not assumed back


# ---------------------------------------------------------------------------
# Imports suggest what the file shows (the person still confirms)
# ---------------------------------------------------------------------------


def test_the_preview_suggests_the_files_own_date_range(shop):
    rows = [["Date", "Transaction ID", "SKU", "Qty"], ["2026-09-02T12:00:00", "A", "LITTER-20", "1"],
            ["2026-09-09T12:00:00", "B", "LITTER-20", "1"]]
    imp = shop.client.post("/v1/imports", headers=shop.headers(), data={
        "kind": "sales", "location_id": shop.location_id, "source_system": "square"},
        files={"file": ("p.csv", _csv(rows), "text/csv")}).json()
    preview = shop.get(f"/v1/imports/{imp['id']}/preview").json()
    assert preview["suggested_settings"]["period_start"] == "2026-09-02"
    assert preview["suggested_settings"]["period_end"] == "2026-09-09"
    assert "declare_period" in " ".join(preview["blocking_issues"])  # still the person's call


# ---------------------------------------------------------------------------
# Review regressions (store-readiness phase)
# ---------------------------------------------------------------------------


def test_a_pos_reading_at_the_very_moment_of_the_delivery_does_not_hide_it(ready):
    po = _send(ready, qty="10")
    _pos_owned(ready)
    at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=10)
    _pos_reading(ready, 18, at)
    order = ready.post(f"/v1/purchase-orders/{po['id']}/receipts", {
        "receipt_key": "same-moment", "received_at": at.isoformat(), "lines": [{"line_no": 1, "arrived_qty": "4"}]}).json()["order"]
    rl = order["progress"]["receipts"][0]["lines"][0]["id"]
    _pos_reading(ready, 18, at + timedelta(minutes=5))  # never entered: the POS still shows 18
    ev = ready.get(f"/v1/receipt-lines/{rl}/pos-evidence").json()
    assert (ev["assessment"], ev["unexplained"]) == ("receipt_missing_in_pos", "-48")
    assert ready.post(f"/v1/receipt-lines/{rl}/pos-reconcile", {"outcome": "matches"}).status_code == 422


def test_digits_alone_do_not_suggest_another_numbering_scheme(ready):
    _send(ready)  # PO-00001
    _open_orders(ready, "INV-1")  # the supplier's own invoice numbering
    (link,) = ready.get("/v1/open-order-links", params={"location_id": ready.location_id}).json()
    assert link["status"] == "separate"
