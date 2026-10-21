"""
Local demo workspace for the CP6 browser flow.

Creates, through the real /v1 API (so every domain rule applies), a store with
a ship-to address, two approved suppliers with verified order emails, items,
pack sizes and current prices. Sales, a stock count and open orders are written
as CSV files for you to import in the browser — that is the first step of the
flow. `--import` applies them too, for a quick start.

    DATABASE_URL=postgresql+psycopg://localhost/tabula_dev \
    TABULA_AUTH_MODE=dev TABULA_ENV=development \
    .venv/bin/python -m clawbot.devtools.seed_demo [--import]

Everything here is fictional; the supplier emails use reserved example.com
domains and sends run in capture mode only.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

OWNER = "owner@pawsandco.example"
MANAGER = "manager@pawsandco.example"
STORE_TZ = "America/New_York"
OUT_DIR = Path(__file__).resolve().parents[2] / "var" / "demo"

# sku, name, daily sales, counted stock
ITEMS = [
    ("LITTER-20", "Clumping cat litter 20lb", 6, 18),
    ("CATFOOD-3", "Salmon cat food 3oz can", 4, 10),
    ("TOY-BALL", "Rubber fetch ball", 1, 60),
    ("DOGFOOD-30", "Lamb & rice dog food 30lb", 3, 8),
    ("TREATS-6", "Chicken jerky treats 6oz", 5, 12),
    ("BIRD-SEED", "Wild bird seed 5lb", 2, 5),
]
SUPPLIERS = [
    {
        "body": {"name": "Phillips Pet Supply", "currency": "USD", "timezone": STORE_TZ, "ordering_channel": "email",
                 "payment_terms": "net", "payment_net_days": 30, "default_lead_time_days": 4,
                 "delivery_weekdays": [2, 4], "order_cutoff_local": "14:00:00", "merchant_account_number": "ACCT-77",
                 "min_order_amount": "150", "freight_notes": "Free delivery over $250, else $15"},
        "email": "orders@phillips.example.com",
        # sku, supplier sku, order unit, units per order unit, order multiple, price per order unit
        "items": [("LITTER-20", "PH-LIT-20", "case", "12", "1", "30.00"),
                  ("CATFOOD-3", "PH-CF-3", "case", "24", "1", "54.00"),
                  ("TOY-BALL", "PH-TB-1", "case", "12", "1", "18.00")],
    },
    {
        "body": {"name": "Coastal Feed Co", "currency": "USD", "timezone": STORE_TZ, "ordering_channel": "email",
                 "payment_terms": "net", "payment_net_days": 15, "default_lead_time_days": 3,
                 "merchant_account_number": "CF-20931", "min_order_amount": "100",
                 "freight_notes": "Flat $20 delivery"},
        "email": "po@coastalfeed.example.com",
        "items": [("DOGFOOD-30", "CF-DF-30", "bag", "1", "1", "42.00"),
                  ("TREATS-6", "CF-TR-6", "case", "6", "1", "21.00")],
    },
]
OPEN_ORDERS = [("Phillips Pet Supply", "PO-80", "CATFOOD-3", "72", "no")]


def _client():
    from fastapi.testclient import TestClient

    from clawbot.api.app import create_app

    return TestClient(create_app())


class Api:
    def __init__(self, client, user: str, tenant_id: str | None = None):
        self.client, self.user, self.tenant_id = client, user, tenant_id

    def headers(self) -> dict[str, str]:
        h = {"X-Dev-User": self.user}
        if self.tenant_id:
            h["X-Tenant-Id"] = self.tenant_id
        return h

    def call(self, method: str, path: str, body=None, ok=(200, 201, 202)):
        resp = self.client.request(method, f"/v1{path}", json=body, headers=self.headers())
        if resp.status_code not in ok:
            raise SystemExit(f"{method} {path} -> {resp.status_code}: {resp.text}")
        return resp.json()


def _csv(rows) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def write_samples(today) -> dict[str, Path]:
    """Sales for the 28 full days before today, a count from an hour ago, one unconfirmed open order."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = today - timedelta(days=28)
    sales = [["Date", "Transaction ID", "SKU", "Qty"]]
    for n in range(28):
        day = start + timedelta(days=n)
        for i, (sku, _, per_day, _) in enumerate(ITEMS):
            wobble = (-1, 0, 1, 0)[(n + i) % 4] if per_day > 1 else 0  # a little day-to-day noise, same average
            sales.append([f"{day.isoformat()}T{11 + i}:15:00", f"T-{day.isoformat()}-{i}", sku, str(per_day + wobble)])
    files = {
        "sales": OUT_DIR / "sales_last_28_days.csv",
        "inventory": OUT_DIR / "stock_count.csv",
        "open_orders": OUT_DIR / "open_orders.csv",
    }
    files["sales"].write_text(_csv(sales))
    files["inventory"].write_text(_csv([["SKU", "Qty"], *[[sku, str(qty)] for sku, _, _, qty in ITEMS]]))
    files["open_orders"].write_text(_csv([["Supplier", "PO #", "SKU", "Qty Remaining", "Confirmed"], *OPEN_ORDERS]))
    return files


def seed(apply_files: bool) -> None:
    client = _client()
    me = Api(client, OWNER)
    tenant = me.call("POST", "/tenants", {"name": "Paws & Co (demo)"})
    api = Api(client, OWNER, tenant["tenant_id"])
    api.call("PUT", "/members", {"auth_subject": f"dev|{MANAGER}", "email": MANAGER, "role": "manager"})

    loc = api.call("POST", "/locations", {"name": "Main St", "timezone": STORE_TZ})
    api.call("PUT", f"/locations/{loc['id']}/address", {
        "address_line1": "12 Main St", "city": "Brooklyn", "region": "NY", "postal_code": "11201", "country": "US"})

    variants = {sku: api.call("POST", "/variants", {"sku": sku, "name": name})["id"] for sku, name, _, _ in ITEMS}
    for spec in SUPPLIERS:
        s = api.call("POST", "/suppliers", spec["body"])
        c = api.call("POST", f"/suppliers/{s['id']}/contacts", {"email": spec["email"], "is_order_recipient": True})
        api.call("POST", f"/suppliers/{s['id']}/contacts/{c['id']}/verify")
        api.call("PUT", f"/suppliers/{s['id']}/coverage", {"location_ids": [loc["id"]]})
        s = api.call("GET", f"/suppliers/{s['id']}")
        api.call("POST", f"/suppliers/{s['id']}/status", {"version": s["version"], "status": "approved"})
        for sku, supplier_sku, uom, per, multiple, price in spec["items"]:
            item = api.call("POST", f"/suppliers/{s['id']}/items", {
                "supplier_sku": supplier_sku, "order_uom": uom, "units_per_order_uom": per, "order_multiple": multiple})
            api.call("POST", f"/supplier-items/{item['id']}/mapping-decision",
                     {"version": item["version"], "decision": "confirmed", "variant_id": variants[sku]})
            api.call("POST", f"/supplier-items/{item['id']}/prices", {
                "unit_price": price, "currency": "USD", "price_type": "price_list", "order_uom": uom,
                "units_per_order_uom": per, "source_ref": f"{spec['body']['name']} price list"})
    api.call("PUT", f"/replenishment/items/{variants['LITTER-20']}", {"location_id": loc["id"], "safety_stock": "12"})

    today = datetime.now(ZoneInfo(STORE_TZ)).date()
    files = write_samples(today)
    period = (today - timedelta(days=28), today - timedelta(days=1))
    count_as_of = datetime.now(timezone.utc) - timedelta(hours=1)
    if apply_files:
        _import_all(api, loc["id"], files, period, count_as_of)

    print(f"\nWorkspace  Paws & Co (demo)  tenant {tenant['tenant_id']}")
    print(f"Owner      {OWNER}   (approves orders)")
    print(f"Manager    {MANAGER} (can draft, cannot approve)")
    print(f"Location   Main St, 12 Main St, Brooklyn NY 11201  id {loc['id']}")
    print("Suppliers  Phillips Pet Supply <orders@phillips.example.com>, Coastal Feed Co <po@coastalfeed.example.com>")
    print("           (capture mode: nothing is delivered to these addresses)")
    print("\nSample files to import" + (" (already imported)" if apply_files else "") + ":")
    print(f"  Sales history  {files['sales']}  -> declare period {period[0]} to {period[1]}")
    print(f"  Stock count    {files['inventory']}  -> declare 'true at' {count_as_of.astimezone(ZoneInfo(STORE_TZ)):%Y-%m-%d %H:%M} (store time)")
    print(f"  Open orders    {files['open_orders']}  -> declare 'true at' now, quantities in base units, scope suppliers_in_file")


def _import_all(api: Api, location_id: str, files, period, count_as_of) -> None:
    from clawbot.workflows import import_worker

    settings = {
        "sales": {"period_start": period[0].isoformat(), "period_end": period[1].isoformat()},
        "inventory": {"as_of": count_as_of.isoformat()},
        "open_orders": {"as_of": datetime.now(timezone.utc).isoformat(), "complete_scope": "suppliers_in_file",
                        "quantity_unit": "base"},
    }
    for kind in ("sales", "inventory", "open_orders"):
        path = files[kind]
        data = {"kind": kind, "location_id": location_id}
        if kind == "sales":
            data["source_system"] = "square"
        resp = api.client.post("/v1/imports", data=data, files={"file": (path.name, path.read_bytes(), "text/csv")},
                               headers=api.headers())
        if resp.status_code != 201:
            raise SystemExit(f"upload {kind}: {resp.status_code} {resp.text}")
        imp = resp.json()
        api.call("PUT", f"/imports/{imp['id']}/mapping", {
            "revision": imp["mapping_revision"], "columns": imp["mapping"]["columns"],
            "settings": {**imp["mapping"]["settings"], **settings[kind]}})
        preview = api.call("GET", f"/imports/{imp['id']}/preview")
        if preview["blocking_issues"] or preview["counts"]["with_errors"]:
            raise SystemExit(f"{kind} import is not clean: {preview['blocking_issues']} {preview['counts']}")
        api.call("POST", f"/imports/{imp['id']}/confirm-mapping", {
            "revision": preview["mapping_revision"], "declared": preview["declared_settings"], "accept_row_errors": False})
        import_worker.run_once()
        done = api.call("GET", f"/imports/{imp['id']}")
        if done["status"] != "applied":
            raise SystemExit(f"{kind} import ended {done['status']}: {done['failure']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--import", dest="apply_files", action="store_true", help="also import the sample files")
    args = parser.parse_args(argv)
    if os.getenv("TABULA_ENV") not in ("development", "test") or os.getenv("TABULA_AUTH_MODE") != "dev":
        print("seed_demo runs only with TABULA_ENV=development and TABULA_AUTH_MODE=dev", file=sys.stderr)
        return 2
    seed(args.apply_files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
