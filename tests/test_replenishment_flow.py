"""
PLAN-01 end to end: data arrives through CP3 imports (sales, stock count, open
orders, price list) and the plan is computed from that normalized data.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from clawbot.domain.replenishment import service
from clawbot.persistence.db import transaction
from clawbot.policies.permissions import agent, system
from tests.conftest import new_store
from tests.test_imports import _apply, _csv, _mapping, _upload
from tests.test_suppliers import _approvable_supplier, _confirm, _item, _price

NY = ZoneInfo("America/New_York")


@pytest.fixture
def shop(client):
    """Spec 7.3 set-up: 28 days of 6/day, 18 counted now, lead 4, review 7, safety 12, case of 12."""
    api = new_store(client, "owner@example.com", "Paws & Co")
    api.location_id = api.post("/v1/locations", {"name": "Main St", "timezone": "America/New_York"}).json()["id"]
    api.variant = api.post("/v1/variants", {"sku": "LITTER-20", "name": "Clumping cat litter 20lb"}).json()
    supplier = _approvable_supplier(api)  # lead 4 days, delivers Tue/Thu — reset to any day, no cutoff below
    api.client.patch(f"/v1/suppliers/{supplier['id']}", json={
        "version": supplier["version"], "delivery_weekdays": [], "order_cutoff_local": None, "min_order_amount": "0",
    }, headers=api.headers())
    api.supplier = api.get(f"/v1/suppliers/{supplier['id']}").json()
    item = _confirm(api, _item(api, supplier["id"], per="12"), api.variant["id"])
    _price(api, item["id"], "30.00")

    today = datetime.now(NY).date()
    rows = [["Date", "Transaction ID", "SKU", "Qty"]]
    for n in range(28, 0, -1):
        day = today - timedelta(days=n)
        rows.append([f"{day.isoformat()}T12:00:00", f"T-{day.isoformat()}", "LITTER-20", "6"])
    _mapping_and_apply(api, _upload(api, "sales", _csv(rows), location_id=api.location_id, source_system="square").json())

    count = _upload(api, "inventory", _csv([["SKU", "Qty"], ["LITTER-20", "18"]]), location_id=api.location_id).json()
    _mapping(api, count, as_of=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat())
    _apply(api, count)
    api.client.put(f"/v1/replenishment/items/{api.variant['id']}",
                   json={"location_id": api.location_id, "safety_stock": "12"}, headers=api.headers())
    return api


def _mapping_and_apply(api, imp):
    _apply(api, imp)


def _iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _movement(api, delta, reason):
    import uuid as _uuid

    body = {"variant_id": api.variant["id"], "location_id": api.location_id, "delta": str(delta), "reason": reason}
    resp = api.post("/v1/inventory/movements", body, headers={"Idempotency-Key": f"k-{_uuid.uuid4()}"})
    assert resp.status_code == 201, resp.text


def _run(api, **body):
    resp = api.post("/v1/replenishment-runs", {"location_id": api.location_id, **body})
    assert resp.status_code in (200, 201), resp.text
    return resp


def _line(run, sku="LITTER-20"):
    return next(l for l in run["lines"] if l["sku"] == sku)


def test_spec_example_through_imports(shop):
    run = _run(shop).json()
    line = _line(run)
    assert (line["status"], line["order_qty"], line["order_uom"], line["base_qty"]) == ("order", "5", "case", "60")
    assert (line["target"], line["position"], line["need"], line["daily_demand"]) == ("78", "18", "60", "6")
    assert line["stockout_days"] == [4]
    assert line["line_cost"] == "150" and line["supplier"] == "Phillips Pet"
    # Explanation: data times, calculation, policy, and why it needs review.
    assert line["data_as_of"]["stock_source"] == "Tabula ledger (last count)" and line["data_as_of"]["sales_through"]
    assert [s["label"] for s in line["steps"]][:3] == ["Stock on hand (estimated now)", "Daily demand", "Order arrives (usable from)"]
    assert [r["code"] for r in line["reasons"]] == ["stockout_before_delivery"]
    assert run["policy_version"] == 0 and run["engine_version"] == "repl-2" and run["input_digest"]
    assert run["computed_by"]["kind"] == "human"


def test_unconfirmed_open_order_is_not_ordered_again(shop):
    rows = [["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"], ["Phillips Pet", "PO-80", "LITTER-20", "60", "no"]]
    imp = _upload(shop, "open_orders", _csv(rows), location_id=shop.location_id).json()
    _mapping(shop, imp, quantity_unit="base", as_of=_iso(), complete_scope="none")
    _apply(shop, imp)
    line = _line(_run(shop).json())
    assert (line["status"], line["order_qty"], line["position"]) == ("on_hold", "0", "78")
    assert (line["need_before_held"], line["held_qty"]) == ("60", "60")
    assert {r["code"] for r in line["reasons"]} == {"unconfirmed_open_order", "reorder_on_hold", "stockout_risk_unconfirmed"}


def test_confirmed_open_order_with_eta_counts_as_arriving(shop):
    eta = (datetime.now(NY).date() + timedelta(days=1)).isoformat()  # usable on day 3
    rows = [["Supplier", "PO #", "SKU", "Qty Remaining", "ETA", "Confirmed"],
            ["Phillips Pet", "PO-81", "LITTER-20", "24", eta, "yes"]]
    imp = _upload(shop, "open_orders", _csv(rows), location_id=shop.location_id).json()
    _mapping(shop, imp, quantity_unit="base", as_of=_iso(), complete_scope="none")
    _apply(shop, imp)
    line = _line(_run(shop).json())
    assert (line["position"], line["order_qty"]) == ("42", "3")
    assert line["stockout_days"] == []


def test_sales_after_the_count_are_subtracted(shop):
    sold_now = datetime.now(NY) - timedelta(minutes=1)
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [sold_now.isoformat(), "T-today", "LITTER-20", "6"]]
    _apply(shop, _upload(shop, "sales", _csv(rows), name="today.csv", location_id=shop.location_id, source_system="square").json())
    line = _line(_run(shop).json())
    assert line["position"] == "12"
    assert "6 sold since" in line["steps"][0]["formula"]


def test_same_data_same_plan_and_concurrent_runs_leave_one_plan(shop):
    first = _run(shop)
    second = _run(shop)
    assert (first.status_code, second.status_code) == (201, 200) and first.json()["id"] == second.json()["id"]

    tenant, location = uuid.UUID(shop.tenant_id), uuid.UUID(shop.location_id)
    ids, errors = [], []

    def run(actor):
        try:
            with transaction() as s:
                ids.append(service.create_run(s, tenant_id=tenant, actor=actor, location_id=location)[0].id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    owner = service  # noqa: F841 — scheduler (system) and a person race
    from clawbot.domain import tenancy
    with transaction() as s:
        person = tenancy.actor_for(s, tenant_id=tenant, user_id=uuid.UUID(shop.get("/v1/me").json()["user_id"]))
    threads = [threading.Thread(target=run, args=(a,)) for a in (system("scheduler"), person)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with transaction() as s:
        from clawbot.persistence.models import ReplenishmentRun
        current = s.query(ReplenishmentRun).filter_by(location_id=location, status="current").all()
        assert len(current) == 1


def test_stored_lines_replay_exactly(shop):
    run = _run(shop).json()
    with transaction() as s:
        r = service.get_run(s, tenant_id=uuid.UUID(shop.tenant_id), run_id=uuid.UUID(run["id"]))
        for line in service.run_lines(s, r):
            replayed = service._result_json(service.replay(line, r))
            assert replayed == line.result


def test_policy_versions_and_new_data_mark_the_plan_stale(shop):
    shop.client.put("/v1/replenishment/policy", json={"changes": {"review_period_days": 14}}, headers=shop.headers())
    assert shop.get("/v1/replenishment/policy").json()["version"] == 1
    run = _run(shop).json()
    assert run["policy_version"] == 1 and _line(run)["target"] == str(6 * (4 + 14) + 12)
    rec = shop.get("/v1/recommendations", params={"location_id": shop.location_id}).json()
    assert rec["stale"] is False
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [(datetime.now(NY) - timedelta(minutes=1)).isoformat(), "T-x", "LITTER-20", "1"]]
    _apply(shop, _upload(shop, "sales", _csv(rows), name="x.csv", location_id=shop.location_id, source_system="square").json())
    rec = shop.get("/v1/recommendations", params={"location_id": shop.location_id}).json()
    assert rec["stale"] is True and "newer_sales" in rec["stale_reasons"]


def test_agents_cannot_run_or_change_policy_but_a_scheduler_can(shop):
    from clawbot.domain.errors import PermissionDenied

    tenant, location = uuid.UUID(shop.tenant_id), uuid.UUID(shop.location_id)
    with pytest.raises(PermissionDenied), transaction() as s:
        service.create_run(s, tenant_id=tenant, actor=agent("purchasing-assistant"), location_id=location)
    with pytest.raises(PermissionDenied), transaction() as s:
        service.set_policy(s, tenant_id=tenant, actor=system("scheduler"), changes={"review_period_days": 1})
    with transaction() as s:
        run, _ = service.create_run(s, tenant_id=tenant, actor=system("scheduler"), location_id=location)
        assert run.actor_kind == "system"


def test_plans_are_tenant_private(client, shop):
    run = _run(shop).json()
    other = new_store(client, "rival@example.com", "Rival")
    assert other.get(f"/v1/replenishment-runs/{run['id']}").status_code == 404
    assert other.post("/v1/replenishment-runs", {"location_id": shop.location_id}).status_code == 404


def test_pos_owned_location_uses_snapshot_minus_later_sales(client):
    api = new_store(client, "pos@example.com", "POS Pets")
    loc = api.post("/v1/locations", {"name": "POS", "timezone": "America/New_York", "inventory_write_owner": "square"}).json()
    api.post("/v1/variants", {"sku": "TREATS", "name": "Treats"})
    count = _upload(api, "inventory", _csv([["SKU", "Qty"], ["TREATS", "40"]]), location_id=loc["id"]).json()
    _mapping(api, count, as_of=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
    _apply(api, count)
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [(datetime.now(NY) - timedelta(minutes=30)).isoformat(), "T-1", "TREATS", "5"]]
    today = datetime.now(NY).date()
    rows += [[f"{(today - timedelta(days=n)).isoformat()}T12:00:00", f"T-h{n}", "TREATS", "2"] for n in range(20, 0, -1)]
    _apply(api, _upload(api, "sales", _csv(rows), location_id=loc["id"], source_system="square").json())
    run = api.post("/v1/replenishment-runs", {"location_id": loc["id"]}).json()
    line = _line(run, "TREATS")
    assert line["data_as_of"]["stock_source"] == "manual import (no POS reading)"
    assert line["position"] == "35" and line["status"] == "no_supplier"



# ---------------------------------------------------------------------------
# CP5 review regressions (through real data paths)
# ---------------------------------------------------------------------------


def _sell(api, n, minutes_ago=1, name=None):
    at = (datetime.now(NY) - timedelta(minutes=minutes_ago)).isoformat()
    rows = [["Date", "Transaction ID", "SKU", "Qty"], [at, f"T-now-{n}-{minutes_ago}", "LITTER-20", str(n)]]
    _apply(api, _upload(api, "sales", _csv(rows), name=name or f"s{n}{minutes_ago}.csv", location_id=api.location_id,
                        source_system="square").json())


def test_r1_damage_after_the_count_keeps_sales_since_the_count(shop):
    _sell(shop, 10, minutes_ago=3)
    _movement(shop, -1, "damage")  # recorded after the sales
    line = _line(_run(shop).json())
    assert line["position"] == "7"  # 18 − 1 damaged − 10 sold
    assert "1 other stock changes since" in line["steps"][0]["formula"] and "10 sold since" in line["steps"][0]["formula"]


def test_r2_gap_between_sales_exports_is_not_zero_demand(client):
    api = new_store(client, "gap@example.com", "Gap Pets")
    loc = api.post("/v1/locations", {"name": "G", "timezone": "America/New_York"}).json()["id"]
    api.post("/v1/variants", {"sku": "LITTER-20", "name": "Litter"})
    today = datetime.now(NY).date()
    for days, name in ((range(60, 50, -1), "old.csv"), (range(10, 0, -1), "new.csv")):
        rows = [["Date", "Transaction ID", "SKU", "Qty"]] + [
            [f"{(today - timedelta(days=n)).isoformat()}T12:00:00", f"T-{n}", "LITTER-20", "6"] for n in days]
        _apply(api, _upload(api, "sales", _csv(rows), name=name, location_id=loc, source_system="square").json())
    count = _upload(api, "inventory", _csv([["SKU", "Qty"], ["LITTER-20", "18"]]), location_id=loc).json()
    _mapping(api, count, as_of=_iso(minutes=-5))
    _apply(api, count)
    line = _line(api.post("/v1/replenishment-runs", {"location_id": loc}).json())
    assert line["daily_demand"] == "6"  # 20 covered days at 6/day; the 40-day gap is missing data


def test_r3_historical_run_never_becomes_the_current_plan(shop):
    now_run = _run(shop).json()
    past = _run(shop, as_of=_iso(days=-20)).json()
    assert past["status"] == "historical" and now_run["status"] == "current"
    rec = shop.get("/v1/recommendations", params={"location_id": shop.location_id}).json()
    assert rec["run"]["id"] == now_run["id"]
    again = _run(shop).json()
    assert again["id"] == now_run["id"]  # reused: recent and nothing changed
    assert shop.post("/v1/replenishment-runs", {"location_id": shop.location_id, "as_of": _iso(days=1)}).status_code == 422


def test_r8_policy_values_are_typed(shop):
    put = lambda changes: shop.client.put("/v1/replenishment/policy", json={"changes": changes}, headers=shop.headers())
    assert put({"safety_days": 0.1}).status_code == 422
    assert put({"weekday_pattern": "no"}).status_code == 422
    assert put({"review_period_days": 7.5}).status_code == 422
    ok = put({"safety_days": "1.5", "weekly_budget": "500", "budget_currency": "usd"})
    assert ok.status_code == 200 and ok.json()["budget_currency"] == "USD" and ok.json()["safety_days"] == "1.5"


def _open_orders(api, rows, as_of, complete):
    header = ["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"]
    imp = _upload(api, "open_orders", _csv([header, *rows]), name=f"oo-{as_of}.csv", location_id=api.location_id).json()
    _mapping(api, imp, quantity_unit="base", as_of=as_of, complete_scope=complete)
    return _apply(api, imp)


def test_5_12_complete_report_closes_missing_lines_and_older_reports_do_not_overwrite(shop):
    _open_orders(shop, [["Phillips Pet", "PO-1", "LITTER-20", "60", "no"]], _iso(hours=-2), complete="none")
    assert len(shop.get("/v1/open-orders").json()) == 1
    # A newer complete report no longer lists PO-1 (received) → closed, so it stops blocking reorders.
    done = _open_orders(shop, [["Phillips Pet", "PO-2", "LITTER-20", "12", "yes"]], _iso(hours=-1), complete="suppliers_in_file")
    assert done["summary"]["closed_missing_lines"] == 1
    assert [l["external_po_number"] for l in shop.get("/v1/open-orders").json()] == ["PO-2"]
    # An older report cannot overwrite the newer state.
    older = _open_orders(shop, [["Phillips Pet", "PO-2", "LITTER-20", "99", "yes"]], _iso(hours=-3), complete="none")
    assert older["summary"]["applied_counts"] == {"skipped": 1}
    assert shop.get("/v1/open-orders").json()[0]["outstanding_qty"] == "12.0000"


def test_5_12_open_order_files_must_declare_time_and_completeness(shop):
    imp = _upload(shop, "open_orders", _csv([["Supplier", "PO #", "SKU", "Qty Remaining"],
                                             ["Phillips Pet", "PO-1", "LITTER-20", "6"]]), location_id=shop.location_id).json()
    _mapping(shop, imp, quantity_unit="base")
    assert {"declare_as_of", "declare_complete_scope"} <= set(shop.get(f"/v1/imports/{imp['id']}/preview").json()["blocking_issues"])


# ---------------------------------------------------------------------------
# CP5 review round 2
# ---------------------------------------------------------------------------


def test_r2_1_change_dated_before_the_count_is_not_applied_twice(shop):
    import uuid as _uuid

    body = {"variant_id": shop.variant["id"], "location_id": shop.location_id, "delta": "-1", "reason": "damage",
            "occurred_at": _iso(hours=-1)}  # before the count (5 min ago), entered now
    assert shop.post("/v1/inventory/movements", body, headers={"Idempotency-Key": f"k-{_uuid.uuid4()}"}).status_code == 201
    assert _line(_run(shop).json())["position"] == "18"


def test_r2_2_one_origin_cannot_fill_another_origins_gap(client):
    api = new_store(client, "two@example.com", "Two Origins")
    loc = api.post("/v1/locations", {"name": "T", "timezone": "America/New_York"}).json()["id"]
    for sku in ("A", "B"):
        api.post("/v1/variants", {"sku": sku, "name": sku})
    today = datetime.now(NY).date()
    rows = [["Date", "Transaction ID", "SKU", "Qty"]] + [
        [f"{(today - timedelta(days=n)).isoformat()}T12:00:00", f"T-{n}-{sku}", sku, "6"]
        for n in range(28, 14, -1) for sku in ("A", "B")]
    _apply(api, _upload(api, "sales", _csv(rows), name="sq.csv", location_id=loc, source_system="square").json())
    small = [["Date", "Transaction ID", "SKU", "Qty"], [f"{(today - timedelta(days=14)).isoformat()}T12:00:00", "S-1", "A", "1"],
             [f"{(today - timedelta(days=1)).isoformat()}T12:00:00", "S-2", "A", "1"]]
    _apply(api, _upload(api, "sales", _csv(small), name="shop.csv", location_id=loc, source_system="shopify").json())
    count = _upload(api, "inventory", _csv([["SKU", "Qty"], ["A", "5"], ["B", "5"]]), location_id=loc).json()
    _mapping(api, count, as_of=_iso(minutes=-5))
    _apply(api, count)
    run = api.post("/v1/replenishment-runs", {"location_id": loc}).json()
    demand = {l["sku"]: l["daily_demand"] for l in run["lines"]}
    assert demand == {"A": "6", "B": "6"}  # square's missing last 14 days are not zeros


def test_r2_3_same_po_number_at_two_locations_stays_separate(shop):
    other = shop.post("/v1/locations", {"name": "Second", "timezone": "America/New_York"}).json()["id"]
    for loc, qty in ((shop.location_id, "24"), (other, "12")):
        imp = _upload(shop, "open_orders", _csv([["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"],
                                                 ["Phillips Pet", "PO-1", "LITTER-20", qty, "no"]]),
                      name=f"oo-{loc}.csv", location_id=loc).json()
        _mapping(shop, imp, quantity_unit="base", as_of=_iso(), complete_scope="none")
        _apply(shop, imp)
    assert sorted(l["outstanding_qty"] for l in shop.get("/v1/open-orders").json()) == ["12.0000", "24.0000"]


def test_r2_4_all_suppliers_report_closes_a_supplier_with_no_rows(shop):
    other = shop.post("/v1/suppliers", {"name": "Other Dist", "currency": "USD", "timezone": "America/New_York"}).json()
    _open_orders(shop, [["Other Dist", "PO-9", "LITTER-20", "6", "no"]], _iso(hours=-2), complete="none")
    imp = _upload(shop, "open_orders", _csv([["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"],
                                             ["Phillips Pet", "PO-2", "LITTER-20", "12", "yes"]]),
                  name="all.csv", location_id=shop.location_id).json()
    _mapping(shop, imp, quantity_unit="base", as_of=_iso(hours=-1), complete_scope="all_suppliers")
    done = _apply(shop, imp)
    assert done["summary"]["closed_missing_lines"] == 1
    assert [l["external_po_number"] for l in shop.get("/v1/open-orders").json()] == ["PO-2"]
    assert other


def test_r2_5_policy_garbage_is_422_and_older_runs_never_replace_newer(shop):
    put = lambda changes: shop.client.put("/v1/replenishment/policy", json={"changes": changes}, headers=shop.headers())
    assert put({"safety_days": "abc"}).status_code == 422
    now_run = _run(shop).json()
    earlier = _run(shop, as_of=_iso(minutes=-3)).json()
    assert earlier["status"] == "historical"
    assert shop.get("/v1/recommendations", params={"location_id": shop.location_id}).json()["run"]["id"] == now_run["id"]


def test_plan_line_states_stock_and_the_three_arrival_dates(shop):
    """Lead 4, ordered today: delivered at the end of day 4 (today + 3), on the shelf from day 5 (today + 4)."""
    line = _line(_run(shop).json())
    today = datetime.now(NY).date()
    assert line["on_hand"] == "18"
    assert line["arrival"] == {"order_date": today.isoformat(), "delivery_date": (today + timedelta(days=3)).isoformat(),
                               "usable_date": (today + timedelta(days=4)).isoformat()}
    assert next(d for d in line["projection"] if Decimal(d["arriving"]) > 0)["date"] == (today + timedelta(days=3)).isoformat()
