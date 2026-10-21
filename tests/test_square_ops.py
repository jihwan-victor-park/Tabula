"""
Square connector, store-level rules: one sales source per location, token refresh, reconnect,
scheduled sync and nightly reconciliation — against mock Square. The same checks against the real
Sandbox: scripts/square_sandbox_check.py (needs the settings in docs/SQUARE_SETUP.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from clawbot.connectors.square import service as square
from clawbot.persistence.db import transaction
from clawbot.persistence.models import ConnectorAccount
from clawbot.workflows import connector_worker
from tests.test_imports import _csv, _upload
from tests.test_square_connector import _connect, _iso, _ready, _square_sales, _sync, fake, shop  # noqa: F401


# ---------------------------------------------------------------------------
# Square: one sales source, token refresh, reconnect, scheduled reconciliation
# ---------------------------------------------------------------------------


def test_switching_sales_to_square_needs_a_linked_location(shop, fake):
    resp = shop.client.put(f"/v1/locations/{shop.location_id}/sales-feed", json={"feed": "square"},
                                  headers=shop.headers())
    assert resp.status_code == 409


def test_after_the_switch_files_for_that_period_are_refused(shop, fake):
    _ready(shop, fake)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    _square_sales(shop, since)
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [(since + timedelta(hours=1)).isoformat(), "X-1", "LITTER-20", "1"]]
    imp = _upload(shop, "sales", _csv(rows), name="late.csv", location_id=shop.location_id,
                  source_system="square").json()
    preview = shop.get(f"/v1/imports/{imp['id']}/preview").json()
    assert any("Square records" in e["message"] for e in preview["rows"][0]["errors"])


def test_an_expiring_token_is_refreshed_and_a_refused_refresh_asks_to_reconnect(shop, fake):
    account = _ready(shop, fake)
    with transaction() as s:
        s.execute(text("UPDATE connector_accounts SET token_expires_at = now() + interval '2 days'"))
    queued = connector_worker.schedule_due()
    assert any(":refresh_token:" in k for k in queued)
    connector_worker.run_once()
    with transaction() as s:
        acct = s.get(ConnectorAccount, uuid.UUID(account["id"]))
        assert acct.status == "active" and acct.token_expires_at.year == 2099 and fake.refreshes == 1
    fake.revoked = True  # the seller removed the app in Square
    with transaction() as s:
        acct = s.get(ConnectorAccount, uuid.UUID(account["id"]))
        assert square.refresh_token(s, acct, force=True) is False
        assert acct.status == "needs_reauth"


def test_reconnecting_after_a_disconnect_keeps_the_location_links(shop, fake):
    account = _ready(shop, fake)
    shop.client.delete(f"/v1/connectors/{account['id']}", headers=shop.headers())
    again = _connect(shop)
    assert again["id"] == account["id"] and again["status"] == "active"
    assert again["locations"] == [{"external_location_id": "LOC_MAIN", "location_id": shop.location_id}]


def test_scheduled_runs_are_queued_once_per_slot_and_reconciliation_recovers_a_lost_webhook(shop, fake):
    account = _ready(shop, fake)
    _square_sales(shop, datetime.now(timezone.utc) - timedelta(days=10))
    first = connector_worker.schedule_due()
    assert connector_worker.schedule_due() == []  # same slots: nothing new
    assert {k.split(":")[2] for k in first} >= {"sales", "inventory"}
    for _ in range(5):
        connector_worker.run_once()
    # An order whose webhook never arrived (two days ago) …
    two_days_ago = datetime.now(timezone.utc).replace(hour=15) - timedelta(days=2)
    fake.add_order("LOST-1", _iso(two_days_ago), [("L1", "VAR_LITTER_20", "3", 2099)])
    _sync(shop, account, "reconcile")
    lines = shop.get("/v1/sales-lines").json()
    assert [l["external_order_id"] for l in lines] == ["LOST-1"]
    with transaction() as s:
        state = s.get(ConnectorAccount, uuid.UUID(account["id"])).sync_state
    assert state["reconciliations"][-1]["recovered_sales_lines"] == 1




def test_switching_back_never_reopens_a_period_the_other_source_recorded(shop, fake):
    account = _ready(shop, fake)
    now = datetime.now(timezone.utc)
    t1, t2 = now - timedelta(days=5), now - timedelta(days=2)
    _square_sales(shop, t1)
    fake.add_order("SQ-IN", _iso(t1 + timedelta(hours=1)), [("L1", "VAR_LITTER_20", "1", 2099)])
    fake.add_order("SQ-OLD", _iso(t1 - timedelta(hours=1)), [("L1", "VAR_LITTER_20", "1", 2099)])
    _sync(shop, account, "sales", start=(now - timedelta(days=7)).isoformat(), end=now.isoformat())
    back = shop.client.put(f"/v1/locations/{shop.location_id}/sales-feed", json={"feed": "files", "since": t2.isoformat()},
                           headers=shop.headers())
    assert back.status_code == 200
    # A file covering Square's period is refused; files after t2 are fine.
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [(t1 + timedelta(hours=1)).isoformat(), "CSV-9", "LITTER-20", "1"],
            [(t2 + timedelta(hours=1)).isoformat(), "CSV-10", "LITTER-20", "1"]]
    imp = _upload(shop, "sales", _csv(rows), name="mixed.csv", location_id=shop.location_id, source_system="square").json()
    preview = shop.get(f"/v1/imports/{imp['id']}/preview").json()
    assert [bool(r["errors"]) for r in preview["rows"]] == [True, False]
    # Square's copy of an order from the files era is still not recorded.
    _sync(shop, account, "sales", start=(now - timedelta(days=7)).isoformat(), end=now.isoformat())
    assert [l["external_order_id"] for l in shop.get("/v1/sales-lines").json()] == ["SQ-IN"]
    # And history cannot be rewritten: a switch before the last one is refused.
    again = shop.client.put(f"/v1/locations/{shop.location_id}/sales-feed",
                            json={"feed": "square", "since": (t2 - timedelta(hours=1)).isoformat()}, headers=shop.headers())
    assert again.status_code == 409


def test_switching_to_square_from_a_past_time_syncs_from_that_time(shop, fake):
    account = _ready(shop, fake)
    connector_worker.schedule_due()  # files-fed: no sales job, but the connection keeps running
    with transaction() as s:
        acct = s.get(ConnectorAccount, uuid.UUID(account["id"]))
        acct.sync_state = {**acct.sync_state, "sales_synced_through": datetime.now(timezone.utc).isoformat()}
    since = datetime.now(timezone.utc) - timedelta(days=20)
    _square_sales(shop, since)
    with transaction() as s:
        through = s.get(ConnectorAccount, uuid.UUID(account["id"])).sync_state["sales_synced_through"]
    assert datetime.fromisoformat(through) <= since + timedelta(seconds=1)
