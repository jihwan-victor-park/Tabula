"""Customer-data preparation: anonymising exports and comparing real past orders with recommendations."""

from __future__ import annotations

import csv
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from clawbot.devtools import anonymize, compare_orders
from tests.test_replenishment_flow import NY, shop  # noqa: F401


def test_past_orders_are_compared_with_what_the_plan_would_have_said(shop):
    today = datetime.now(NY).date()
    now = datetime.now(NY)  # ordered just now: the stock count from a few minutes ago is known
    rows = [
        compare_orders.Row(2, today, "Phillips Pet", "PH-LIT-20", Decimal(5), "case", now),   # comparable
        compare_orders.Row(3, today, "Phillips Pet", "PH-LIT-20", Decimal(2), "box", now),    # unit mismatch
        compare_orders.Row(4, today, "Phillips Pet", "NOPE-1", Decimal(1), "each", now),      # unmapped
        compare_orders.Row(5, today - timedelta(days=7), "Phillips Pet", "PH-LIT-20", Decimal(5), "case"),  # before the count
    ]
    out = {r["row"]: r for r in compare_orders.compare(uuid.UUID(shop.tenant_id), uuid.UUID(shop.location_id), rows)}
    assert (out[2]["ordered_units"], out[2]["recommended_units"], out[2]["plan_status"]) == ("60", "60", "order")
    assert out[2]["difference_units"] == "0" and not out[2]["issues"]
    assert "unit mapping" in out[3]["issues"]
    assert "not mapped" in out[4]["issues"]
    assert "no stock reading before this date" in out[5]["issues"]
    # The store's current plan is untouched by these historical checks.
    assert shop.get("/v1/recommendations", params={"location_id": shop.location_id}).json()["run"] is None


def test_anonymising_drops_people_and_hashes_ids_consistently(tmp_path, monkeypatch):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text("Date,Transaction ID,Customer Name,Customer Email,SKU,Qty\n"
                   "2026-10-01,T-1,Ann Lee,ann@x.test,LITTER-20,2\n2026-10-01,T-1,Ann Lee,ann@x.test,FOOD-5,1\n")
    monkeypatch.setenv("PILOT_SALT", "a-long-test-salt-value")
    assert anonymize.main([str(src), str(dst)]) == 0
    header, *rows = list(csv.reader(open(dst)))
    assert header == ["Date", "Transaction ID", "SKU", "Qty"]
    assert rows[0][1] == rows[1][1] and rows[0][1].startswith("X") and "T-1" not in rows[0][1]
    assert [r[2] for r in rows] == ["LITTER-20", "FOOD-5"]
    monkeypatch.setenv("PILOT_SALT", "short")
    assert anonymize.main([str(src), str(dst)]) == 2


def test_anonymising_drops_shopify_style_personal_columns_and_unknown_ones(tmp_path, monkeypatch):
    src, dst = tmp_path / "in.csv", tmp_path / "out.csv"
    src.write_text("Name,Created at,Billing Name,Shipping Name,Recipient,Tags,PAN Suffix,Lineitem name,Lineitem quantity,"
                   "Lineitem sku,Mystery\n#1001,2026-10-01,Ann Lee,Ann Lee,Bob,vip,4242,Litter 20lb,2,LITTER-20,x\n")
    monkeypatch.setenv("PILOT_SALT", "a-long-test-salt-value")
    assert anonymize.main([str(src), str(dst)]) == 0
    header, row = list(csv.reader(open(dst)))
    assert header == ["Name", "Created at", "Lineitem name", "Lineitem quantity", "Lineitem sku"]
    assert row[0].startswith("X") and "Ann" not in ",".join(row) and "4242" not in ",".join(row)
    assert anonymize.main([str(src), str(dst), "--keep", "Mystery", "--keep", "Billing Name"]) == 0
    header, _ = list(csv.reader(open(dst)))
    assert "Mystery" in header and "Billing Name" not in header  # personal columns cannot be kept
