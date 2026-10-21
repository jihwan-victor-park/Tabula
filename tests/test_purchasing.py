"""
CP6 / PO-01, PO-02: purchase order drafts, revisions, owner approval, capture-only send.
Data arrives through CP3 imports; the plan comes from CP5.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from clawbot.domain import purchasing, sales, tenancy
from clawbot.persistence.db import new_session, transaction
from clawbot.persistence.models import CapturedMessage, OutboxMessage, PoApproval
from clawbot.policies.permissions import system
from clawbot.workflows import po_worker
from tests.conftest import add_member
from tests.test_imports import _apply, _csv, _mapping, _upload
from tests.test_replenishment_flow import NY, _iso, shop  # noqa: F401


@pytest.fixture
def ready(shop):
    shop.client.put(f"/v1/locations/{shop.location_id}/address", json={
        "address_line1": "12 Main St", "city": "Brooklyn", "region": "NY", "postal_code": "11201", "country": "us",
    }, headers=shop.headers())
    shop.run = shop.post("/v1/replenishment-runs", {"location_id": shop.location_id}).json()
    return shop


def _draft(api) -> dict:
    resp = api.post("/v1/purchase-orders/from-run", {"run_id": api.run["id"]})
    assert resp.status_code == 201, resp.text
    (po,) = resp.json()
    return api.get(f"/v1/purchase-orders/{po['id']}").json()


def _submit(api, po) -> dict:
    resp = api.post(f"/v1/purchase-orders/{po['id']}/submit", {"revision": po["revision"]})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _approve(api, po):
    return api.post(f"/v1/purchase-orders/{po['id']}/approve", {"revision": po["revision"], "digest": po["digest"]})


def _outbox_count(po_id) -> int:
    with transaction() as s:
        return s.scalar(select(func.count()).select_from(OutboxMessage).where(OutboxMessage.payload["po_id"].astext == po_id))


# ---------------------------------------------------------------------------
# Draft content
# ---------------------------------------------------------------------------


def test_draft_shows_what_the_owner_needs_to_decide(ready):
    po = _draft(ready)
    c = po["content"]
    assert (po["status"], po["revision"], po["number"]) == ("draft", 1, "PO-00001")
    assert c["supplier"] == {**c["supplier"], "name": "Phillips Pet", "account_number": "ACCT-77",
                             "order_email": "orders@phillips.example"}
    assert c["ship_to"]["complete"] and c["address_text"] == "12 Main St, Brooklyn, NY, 11201, US"
    (line,) = c["lines"]
    assert (line["supplier_sku"], line["order_qty"], line["order_uom"], line["units_per_order_uom"], line["base_qty"]) == (
        "PH-LIT-20", "5", "case", "12", "60")
    assert (line["unit_price"], line["line_total"]) == ("30", "150.00")
    assert line["price"]["basis"] == "30 USD per case of 12" and line["price"]["type"] == "price_list"
    assert line["recommendation"]["on_hand"] == "18" and line["recommendation"]["order_qty"] == "5"
    t = c["totals"]
    assert (t["subtotal"], t["estimated_total"], t["shipping"]["status"], t["tax"]["status"]) == (
        "150.00", "150.00", "not_confirmed", "not_estimated")
    assert any(n["code"] == "stockout_before_delivery" for n in c["notices"])
    assert c["blockers"] == []


def test_missing_ship_to_address_blocks_submission(shop):
    shop.run = shop.post("/v1/replenishment-runs", {"location_id": shop.location_id}).json()
    po = _draft(shop)
    assert "ship_to_address_missing" in po["content"]["blockers"]
    resp = shop.post(f"/v1/purchase-orders/{po['id']}/submit", {"revision": 1})
    assert resp.status_code == 422 and "ship_to_address_missing" in resp.json()["details"]["blockers"]


def test_items_already_on_an_open_order_are_not_drafted_twice(ready):
    _draft(ready)
    assert ready.post("/v1/purchase-orders/from-run", {"run_id": ready.run["id"]}).status_code == 409


def test_two_people_drafting_at_once_get_one_order(ready):
    """Review CP6 #2: concurrent "Create PO drafts" must not create two approvable orders for one item."""
    results = []

    def draft():
        results.append(ready.post("/v1/purchase-orders/from-run", {"run_id": ready.run["id"]}).status_code)

    threads = [threading.Thread(target=draft) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409, 409]
    assert len(ready.get("/v1/purchase-orders").json()) == 1


def test_plan_marks_items_already_on_an_active_order(ready):
    po = _draft(ready)
    line = next(l for l in ready.get("/v1/recommendations", params={"location_id": ready.location_id}).json()["run"]["lines"]
                if l["sku"] == "LITTER-20")
    assert line["open_po"] == po["number"]
    ready.post(f"/v1/purchase-orders/{po['id']}/cancel", {"reason": "test"})
    line = next(l for l in ready.get("/v1/recommendations", params={"location_id": ready.location_id}).json()["run"]["lines"]
                if l["sku"] == "LITTER-20")
    assert line["open_po"] is None


def test_plan_must_be_fresh_to_draft(ready):
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [(datetime.now(NY) - timedelta(minutes=1)).isoformat(), "T-n", "LITTER-20", "1"]]
    _apply(ready, _upload(ready, "sales", _csv(rows), name="n.csv", location_id=ready.location_id, source_system="square").json())
    resp = ready.post("/v1/purchase-orders/from-run", {"run_id": ready.run["id"]})
    assert resp.status_code == 409 and "recompute" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Revisions and approval binding
# ---------------------------------------------------------------------------


def test_editing_creates_a_revision_and_respects_pack_rules(ready):
    po = _draft(ready)
    bad = ready.client.patch(f"/v1/purchase-orders/{po['id']}/lines", json={"revision": 1, "lines": [{"line_no": 1, "order_qty": "2.5"}]},
                             headers=ready.headers())
    assert bad.status_code == 422
    edited = ready.client.patch(f"/v1/purchase-orders/{po['id']}/lines",
                                json={"revision": 1, "lines": [{"line_no": 1, "order_qty": "6"}], "reason": "promo next week"},
                                headers=ready.headers()).json()
    line = edited["content"]["lines"][0]
    assert (edited["revision"], line["order_qty"], line["base_qty"], line["line_total"], line["edited"]) == (2, "6", "72", "180.00", True)
    assert edited["digest"] != po["digest"]
    stale = ready.client.patch(f"/v1/purchase-orders/{po['id']}/lines", json={"revision": 1, "lines": [{"line_no": 1, "order_qty": "7"}]},
                               headers=ready.headers())
    assert stale.status_code == 409


def test_only_the_owner_approves_and_only_the_revision_they_saw(ready):
    po = _submit(ready, _draft(ready))
    manager = add_member(ready, "mgr@example.com", "manager")
    assert _approve(manager, po).status_code == 403
    wrong = ready.post(f"/v1/purchase-orders/{po['id']}/approve", {"revision": po["revision"], "digest": "0" * 64})
    assert wrong.status_code == 409
    ok = _approve(ready, po)
    assert ok.status_code == 201
    body = ok.json()
    assert body["status"] == "queued" and body["approvals"][0]["role"] == "owner"
    assert _outbox_count(po["id"]) == 1


def test_double_click_and_two_approvers_queue_one_send(ready):
    po = _submit(ready, _draft(ready))
    with transaction() as s:  # a second owner
        user = tenancy.get_or_create_user(s, auth_subject="dev|owner2@example.com", email="owner2@example.com")
    ready.client.put("/v1/members", json={"auth_subject": "dev|owner2@example.com", "role": "owner"}, headers=ready.headers())
    from tests.conftest import Api

    owner2 = Api(ready.client, "owner2@example.com", ready.tenant_id)
    results = []

    def approve(api):
        results.append(_approve(api, po).status_code)

    threads = [threading.Thread(target=approve, args=(a,)) for a in (ready, owner2, ready)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 200, 201]  # exactly one new approval, two repeats
    with transaction() as s:
        assert s.scalar(select(func.count()).select_from(PoApproval)) == 1
    assert _outbox_count(po["id"]) == 1 and user


def test_change_after_approval_requires_a_new_approval_and_old_job_never_sends(ready):
    po = _submit(ready, _draft(ready))
    _approve(ready, po)
    edited = ready.client.patch(f"/v1/purchase-orders/{po['id']}/lines", json={"revision": 1, "lines": [{"line_no": 1, "order_qty": "6"}]},
                                headers=ready.headers()).json()
    assert (edited["status"], edited["revision"]) == ("draft", 2)
    po_worker.run_once()  # the job for revision 1 runs
    after = ready.get(f"/v1/purchase-orders/{po['id']}").json()
    assert after["status"] == "draft" and after["captured_message"] is None
    assert after["send_attempts"][0]["outcome"] == "skipped"
    po2 = _submit(ready, after)
    assert _approve(ready, po2).status_code in (200, 201)
    po_worker.run_once()
    done = ready.get(f"/v1/purchase-orders/{po['id']}").json()
    assert done["status"] == "test_sent" and done["captured_message"]["revision"] == 2
    assert "6 case" in done["captured_message"]["body"]


def test_capture_send_is_recorded_and_never_called_a_supplier_receipt(ready):
    po = _submit(ready, _draft(ready))
    _approve(ready, po)
    po_worker.run_once()
    po_worker.run_once()  # re-run: nothing new
    done = ready.get(f"/v1/purchase-orders/{po['id']}").json()
    assert done["status"] == "test_sent"
    assert done["captured_message"]["note"] == "Captured in Tabula — not delivered to the supplier"
    assert [a["outcome"] for a in done["send_attempts"]] == ["captured"]
    assert "PH-LIT-20" in done["captured_message"]["attachment_csv"]
    with transaction() as s:
        assert s.scalar(select(func.count()).select_from(CapturedMessage)) == 1
    actions = [h["action"] for h in done["history"]]
    assert actions[:4] == ["po.drafted", "po.submitted", "po.approved", "po.test_sent"]


def test_live_mode_is_refused_and_marked_failed(ready, monkeypatch):
    po = _submit(ready, _draft(ready))
    _approve(ready, po)
    monkeypatch.setenv("TABULA_SUPPLIER_SEND_MODE", "live")
    po_worker.run_once()
    done = ready.get(f"/v1/purchase-orders/{po['id']}").json()
    assert done["status"] == "failed" and done["send_attempts"][0]["outcome"] == "refused"
    assert done["captured_message"] is None


# ---------------------------------------------------------------------------
# Fresh inputs at approval (spec 13.3, 16.9)
# ---------------------------------------------------------------------------


def test_unrelated_change_rechecks_and_still_approves(ready):
    po = _submit(ready, _draft(ready))
    ready.client.put("/v1/replenishment/policy", json={"changes": {"max_unconfirmed_age_days": 10}}, headers=ready.headers())
    resp = _approve(ready, po)
    assert resp.status_code in (200, 201) and resp.json()["status"] == "queued"


def test_change_that_moves_the_recommendation_blocks_approval(ready):
    po = _submit(ready, _draft(ready))
    count = _upload(ready, "inventory", _csv([["SKU", "Qty"], ["LITTER-20", "2"]]), name="recount.csv",
                    location_id=ready.location_id).json()
    _mapping(ready, count, as_of=_iso(minutes=-1))
    _apply(ready, count)
    resp = _approve(ready, po)
    assert resp.status_code == 409
    assert resp.json()["details"]["changed"] == [{"sku": "LITTER-20", "was": "5", "now": "7", "status": "order"}]
    assert "new_plan_id" not in resp.json()["details"]  # that plan was rolled back with the request


def test_refresh_loads_the_new_recommendation_instead_of_hiding_it(ready):
    """Review CP6 #1: Refresh must not stamp the new data version onto the old recommendation."""
    po = _submit(ready, _draft(ready))
    count = _upload(ready, "inventory", _csv([["SKU", "Qty"], ["LITTER-20", "2"]]), name="recount.csv",
                    location_id=ready.location_id).json()
    _mapping(ready, count, as_of=_iso(minutes=-1))
    _apply(ready, count)
    assert _approve(ready, po).status_code == 409
    refreshed = ready.post(f"/v1/purchase-orders/{po['id']}/refresh", {"revision": po["revision"]}).json()
    (line,) = refreshed["content"]["lines"]
    assert (refreshed["status"], line["order_qty"], line["recommendation"]["order_qty"], line["edited"]) == ("draft", "5", "7", True)
    assert any(n["code"] == "differs_from_recommendation" and "recommends 7" in n["message"]
               for n in refreshed["content"]["notices"])
    # The owner now approves 5 knowingly: the screen (and the digest) carries "recommends 7".
    resp = _approve(ready, _submit(ready, refreshed))
    assert resp.status_code == 201 and resp.json()["status"] == "queued"


def test_write_uncommitted_at_plan_time_is_still_caught(ready):
    """A sale recorded in a transaction that was open while the plan and draft were made."""
    tenant, variant, location = (uuid.UUID(x) for x in (ready.tenant_id, ready.variant["id"], ready.location_id))
    with transaction() as s:  # this location's sales come from the POS (the late sale is a Square sale)
        s.execute(text("UPDATE locations SET sales_feed = 'square', sales_feed_since = now() - interval '30 days', "
                       "sales_feed_history = jsonb_build_array(jsonb_build_object('feed', 'square', 'since', "
                       "to_char((now() - interval '30 days') AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"+00:00\"'))) "
                       "WHERE id = :id"), {"id": ready.location_id})
    open_tx = new_session()
    open_tx.begin()
    sales.record_sales_line(open_tx, tenant_id=tenant, actor=system("square-sync"), variant_id=variant,
                            location_id=location, source_system="square", external_order_id="LATE-1",
                            external_line_key="u1", key_scheme="provider_line",
                            sold_at=datetime.now(timezone.utc) - timedelta(minutes=2), quantity=Decimal(12), line_type="sale")
    try:
        ready.run = ready.post("/v1/replenishment-runs", {"location_id": ready.location_id}).json()
        po = _submit(ready, _draft(ready))
    finally:
        open_tx.commit()  # commits after the draft, with a transaction start time before it
        open_tx.close()
    detail = ready.get(f"/v1/purchase-orders/{po['id']}").json()
    assert detail["data"]["changed_since_check"] is True
    assert _approve(ready, po).status_code == 409  # 12 fewer on hand → recommendation moved


def test_approval_waits_while_an_import_is_being_applied(ready):
    po = _submit(ready, _draft(ready))
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [(datetime.now(NY) - timedelta(minutes=1)).isoformat(), "T-p", "LITTER-20", "1"]]
    imp = _upload(ready, "sales", _csv(rows), name="p.csv", location_id=ready.location_id, source_system="square").json()
    from tests.test_imports import _confirm_import

    assert _confirm_import(ready, imp).status_code == 202  # confirmed, worker not run yet
    resp = _approve(ready, po)
    assert resp.status_code == 409 and resp.json()["details"]["pending"]


def test_send_rechecks_inputs_and_stops_if_the_recommendation_moved(ready):
    """Review CP6 #5: approval is not the last check; the sender re-checks right before sending."""
    po = _submit(ready, _draft(ready))
    assert _approve(ready, po).status_code == 201
    count = _upload(ready, "inventory", _csv([["SKU", "Qty"], ["LITTER-20", "2"]]), name="late.csv",
                    location_id=ready.location_id).json()
    _mapping(ready, count, as_of=_iso(minutes=-1))
    _apply(ready, count)
    po_worker.run_once()
    done = ready.get(f"/v1/purchase-orders/{po['id']}").json()
    assert done["status"] == "failed" and done["captured_message"] is None
    (attempt,) = done["send_attempts"]
    assert attempt["outcome"] == "blocked" and "moved from 5 to 7" in attempt["detail"]
    # Recoverable: refresh -> new revision -> approve again -> captured.
    refreshed = ready.post(f"/v1/purchase-orders/{po['id']}/refresh", {"revision": done["revision"]}).json()
    assert refreshed["status"] == "draft" and refreshed["revision"] == 2
    assert _approve(ready, _submit(ready, refreshed)).status_code == 201
    po_worker.run_once()
    assert ready.get(f"/v1/purchase-orders/{po['id']}").json()["status"] == "test_sent"


def test_send_job_that_ends_without_a_result_does_not_leave_the_order_queued(ready):
    """Review CP6 #7: a lease that expired mid-send parks the job in `unknown`; the order must not stay Queued."""
    po = _submit(ready, _draft(ready))
    _approve(ready, po)
    with transaction() as s:
        # A capture-mode worker claimed it (and recorded the mode), then its lease ran out.
        s.execute(text("UPDATE outbox SET status = 'unknown', payload = payload || '{\"send_mode\": \"capture\"}' "
                       "WHERE topic = 'po.send'"))
    po_worker.run_once()
    done = ready.get(f"/v1/purchase-orders/{po['id']}").json()
    assert done["status"] == "failed" and done["captured_message"] is None
    assert done["send_attempts"][-1]["outcome"] == "unknown"
    assert "nothing was sent" in done["send_attempts"][-1]["detail"]


def test_a_sync_waiting_out_a_retry_does_not_block_approval(ready):
    """Review CP6 #8: only running or due input jobs hold approvals."""
    from clawbot.domain import data_version, outbox

    tenant = uuid.UUID(ready.tenant_id)
    with transaction() as s:
        message = outbox.enqueue(s, tenant_id=tenant, topic="square.sync", operation_key="sync-backoff", payload={})
        message.available_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    with transaction() as s:
        assert data_version.pending_inputs(s, tenant) == []
        s.execute(text("UPDATE outbox SET available_at = now() - interval '1 second' WHERE operation_key = 'sync-backoff'"))
    with transaction() as s:
        assert data_version.pending_inputs(s, tenant) == ["square.sync job running"]


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


def test_purchase_orders_are_tenant_private_and_receivers_cannot_draft(client, ready):
    po = _draft(ready)
    from tests.conftest import new_store

    other = new_store(client, "rival@example.com", "Rival")
    assert other.get(f"/v1/purchase-orders/{po['id']}").status_code == 404
    receiver = add_member(ready, "recv@example.com", "receiver")
    assert receiver.post("/v1/purchase-orders/from-run", {"run_id": ready.run["id"]}).status_code == 403
    assert receiver.get(f"/v1/purchase-orders/{po['id']}").status_code == 200


def test_dev_sign_in_only_from_this_computer(client):
    resp = client.get("/v1/me", headers={"X-Dev-User": "a@example.com", "X-Forwarded-For": "203.0.113.9"})
    assert resp.status_code == 403
    # DNS rebinding: a loopback connection addressed to some other site's name.
    assert client.get("/v1/me", headers={"X-Dev-User": "a@example.com", "Host": "evil.example:5173"}).status_code == 403
    assert client.get("/v1/me", headers={"X-Dev-User": "a@example.com", "Host": "127.0.0.1:5173"}).status_code == 200
