"""
CP3 / IMP-01: file imports. The files below are synthetic but shaped like real
exports (distributor price list, POS item-sales export, stock count sheet).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from clawbot.domain.imports import values as v
from clawbot.domain.imports.export import safe_cell
from clawbot.domain.imports.files import parse_csv, parse_file
from clawbot.domain.errors import ValidationFailed
from clawbot.persistence.db import transaction
from clawbot.workflows import import_worker
from tests.conftest import add_member, idem, new_store
from tests.test_suppliers import _approvable_supplier, _confirm


def _csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode()


@pytest.fixture
def store(client):
    api = new_store(client, "owner@example.com", "Paws & Co")
    api.location_id = api.post("/v1/locations", {"name": "Main St", "timezone": "America/New_York"}).json()["id"]
    api.litter = api.post("/v1/variants", {"sku": "LITTER-20", "name": "Clumping cat litter 20lb",
                                           "barcode": "036000291452"}).json()
    api.food = api.post("/v1/variants", {"sku": "FOOD-5", "name": "Dog food 5lb"}).json()
    return api


def _period_of(content: bytes) -> tuple[str, str] | None:
    """Test helper: declare a sales file's period as the span of its own dates (a person would state it)."""
    from datetime import date as _date

    days = []
    for row in list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))[1:]:
        cell = row[0][:10] if row else ""
        for parse in (lambda c: _date.fromisoformat(c), lambda c: datetime.strptime(c, "%m/%d/%Y").date()):
            try:
                days.append(parse(cell))
                break
            except ValueError:
                continue
    return (min(days).isoformat(), max(days).isoformat()) if days else None


def _upload(store, kind, content, name="file.csv", **form):
    data = {"kind": kind, **{k: str(val) for k, val in form.items()}}
    resp = store.client.post("/v1/imports", data=data, files={"file": (name, content, "text/csv")},
                             headers=store.headers())
    if kind == "sales" and resp.status_code == 201 and (period := _period_of(content)):
        _mapping(store, resp.json(), period_start=period[0], period_end=period[1])
    return resp


def _mapping(store, imp, columns=None, **settings):
    current = store.get(f"/v1/imports/{imp['id']}").json()
    merged = {**current["mapping"].get("settings", {}), **settings}
    body = {"revision": current["mapping_revision"], "columns": columns or current["mapping"]["columns"],
            "settings": merged}
    resp = store.client.put(f"/v1/imports/{imp['id']}/mapping", json=body, headers=store.headers())
    assert resp.status_code == 200, resp.text
    return resp.json()


def _confirm_import(store, imp, accept_row_errors=False, declared=None):
    current = store.get(f"/v1/imports/{imp['id']}").json()
    if declared is None:  # the person restates what preview shows they declared
        declared = store.get(f"/v1/imports/{imp['id']}/preview").json()["declared_settings"]
    return store.post(f"/v1/imports/{imp['id']}/confirm-mapping",
                      {"revision": current["mapping_revision"], "accept_row_errors": accept_row_errors,
                       "declared": declared})


def _apply(store, imp, accept_row_errors=False, expect="applied"):
    resp = _confirm_import(store, imp, accept_row_errors=accept_row_errors)
    assert resp.status_code == 202, resp.text
    assert import_worker.run_once() >= 1
    done = store.get(f"/v1/imports/{imp['id']}").json()
    assert done["status"] == expect, f"{done['status']}: {done['failure']} {done['summary']}"
    return done


def _preview(store, imp):
    return store.get(f"/v1/imports/{imp['id']}/preview").json()


PRICE_LIST = [
    ["Item #", "Description", "UPC", "Case Pack", "Unit", "Case Cost", "MOQ"],
    ["PH-LIT-20", "Clumping litter 20lb", "036000291452", "12", "case", "$30.00", "2"],
    ["PH-FD-5", "Dog food 5lb", "", "6", "case", "41.10", ""],
]


# ---------------------------------------------------------------------------
# Supplier price lists — CP3 gate: a wrong unit is stopped before anything applies
# ---------------------------------------------------------------------------


def test_price_list_draft_mapping_and_explicit_price_basis(store):
    supplier = _approvable_supplier(store)
    resp = _upload(store, "supplier_price_list", _csv(PRICE_LIST), supplier_id=supplier["id"])
    assert resp.status_code == 201, resp.text
    imp = resp.json()
    assert imp["mapping"]["columns"] == {
        "supplier_sku": "Item #", "unit_price": "Case Cost", "units_per_order_uom": "Case Pack", "order_uom": "Unit",
        "description": "Description", "barcode": "UPC", "min_order_qty": "MOQ",
    }
    # "Case Cost" could be per case or per each: never guessed.
    assert _preview(store, imp)["blocking_issues"] == ["declare_price_basis"]
    assert _confirm_import(store, imp).status_code == 422

    _mapping(store, imp, price_basis="per_order_unit")
    p = _preview(store, imp)
    assert p["blocking_issues"] == [] and p["counts"] == {"rows": 2, "valid": 2, "with_errors": 0, "with_warnings": 1}
    assert p["rows"][0]["interpretation"] == "PH-LIT-20: case of 12 at 30.00 USD = 2.5000 each"


def test_price_list_without_pack_is_blocked_until_declared(store):
    supplier = _approvable_supplier(store)
    rows = [["Item #", "Price"], ["PH-LIT-20", "30.00"]]
    imp = _upload(store, "supplier_price_list", _csv(rows), supplier_id=supplier["id"]).json()
    _mapping(store, imp, price_basis="per_order_unit")
    assert set(_preview(store, imp)["blocking_issues"]) == {"declare_units_per_order_uom", "declare_order_uom"}
    _mapping(store, imp, price_basis="per_order_unit", units_per_order_uom="12", order_uom="case")
    assert _preview(store, imp)["counts"]["valid"] == 1


def test_price_list_applies_items_prices_and_only_suggests_mappings(store):
    supplier = _approvable_supplier(store)
    imp = _upload(store, "supplier_price_list", _csv(PRICE_LIST), supplier_id=supplier["id"]).json()
    _mapping(store, imp, price_basis="per_order_unit")
    done = _apply(store, imp)
    assert done["summary"]["applied_counts"] == {"applied": 2}

    items = {i["supplier_sku"]: i for i in store.get(f"/v1/suppliers/{supplier['id']}/items").json()}
    litter = items["PH-LIT-20"]
    assert (litter["mapping_status"], litter["variant_id"]) == ("suggested", store.litter["id"])  # UPC matched, not confirmed
    assert litter["units_per_order_uom"] == "12.0000" and litter["min_order_qty"] == "2.0000"
    assert items["PH-FD-5"]["mapping_status"] == "unmapped"
    (price,) = store.get(f"/v1/supplier-items/{litter['id']}/prices").json()
    assert price["unit_price"] == "30.0000" and price["source_ref"].startswith(f"import:{imp['id']}")

    # Not orderable until a person confirms the suggested mapping.
    assert store.get(f"/v1/variants/{store.litter['id']}/offers").json()[0]["blockers"] == ["mapping_suggested"]


def test_per_each_price_is_converted_to_per_case(store):
    supplier = _approvable_supplier(store)
    rows = [["Item #", "Case Pack", "Unit", "Each Cost"], ["PH-LIT-20", "12", "case", "2.50"]]
    imp = _upload(store, "supplier_price_list", _csv(rows), supplier_id=supplier["id"]).json()
    _mapping(store, imp, columns={"supplier_sku": "Item #", "units_per_order_uom": "Case Pack", "order_uom": "Unit",
                                  "unit_price": "Each Cost"}, price_basis="per_base_unit")
    assert _preview(store, imp)["rows"][0]["interpretation"] == "PH-LIT-20: case of 12 at 30.00 USD = 2.5000 each"
    _apply(store, imp)
    (item,) = store.get(f"/v1/suppliers/{supplier['id']}/items").json()
    assert store.get(f"/v1/supplier-items/{item['id']}/prices").json()[0]["unit_price"] == "30.0000"


def test_pack_change_in_new_price_list_is_an_error_unless_accepted(store):
    """Spec 19.2: the supplier's new list says 24 per case."""
    supplier = _approvable_supplier(store)
    first = _upload(store, "supplier_price_list", _csv(PRICE_LIST), supplier_id=supplier["id"]).json()
    _mapping(store, first, price_basis="per_order_unit")
    _apply(store, first)
    item = next(i for i in store.get(f"/v1/suppliers/{supplier['id']}/items").json() if i["supplier_sku"] == "PH-LIT-20")
    _confirm(store, item, store.litter["id"])

    new_list = [PRICE_LIST[0], ["PH-LIT-20", "Clumping litter 20lb", "036000291452", "24", "case", "55.00", "2"]]
    imp = _upload(store, "supplier_price_list", _csv(new_list), supplier_id=supplier["id"]).json()
    _mapping(store, imp, price_basis="per_order_unit")
    (row,) = _preview(store, imp)["rows"]
    assert "Pack changed: we have case of 12, file says case of 24" in row["errors"][0]["message"]
    assert _confirm_import(store, imp).status_code == 422

    _mapping(store, imp, price_basis="per_order_unit", update_pack_on_change=True)
    _apply(store, imp)
    after = store.get(f"/v1/supplier-items/{item['id']}").json()
    assert after["units_per_order_uom"] == "24.0000" and after["mapping_status"] == "suggested"
    current = [p for p in store.get(f"/v1/supplier-items/{item['id']}/prices").json() if p["superseded_at"] is None]
    assert [(p["unit_price"], p["units_per_order_uom"]) for p in current] == [("55.0000", "24.0000")]


def test_same_prices_again_change_nothing(store):
    supplier = _approvable_supplier(store)
    first = _upload(store, "supplier_price_list", _csv(PRICE_LIST), supplier_id=supplier["id"]).json()
    _mapping(store, first, price_basis="per_order_unit")
    _apply(store, first)
    reordered = [PRICE_LIST[0], PRICE_LIST[2], PRICE_LIST[1]]  # different bytes, same content
    second = _upload(store, "supplier_price_list", _csv(reordered), supplier_id=supplier["id"]).json()
    assert second["id"] != first["id"]
    _mapping(store, second, price_basis="per_order_unit")
    assert _apply(store, second)["summary"]["applied_counts"] == {"unchanged": 2}


def test_currency_symbol_contradicting_supplier_currency_is_an_error(store):
    supplier = _approvable_supplier(store)
    rows = [["Item #", "Case Pack", "Unit", "Case Cost"], ["PH-LIT-20", "12", "case", "₩40,000"]]
    imp = _upload(store, "supplier_price_list", _csv(rows), supplier_id=supplier["id"]).json()
    _mapping(store, imp, price_basis="per_order_unit")
    (row,) = _preview(store, imp)["rows"]
    assert row["errors"][0]["message"] == "Price shows KRW but this import is in USD"


# ---------------------------------------------------------------------------
# Sales — CP3 gate: the same sales uploaded twice count once
# ---------------------------------------------------------------------------

SALES = [
    ["Date", "Transaction ID", "SKU", "Qty", "Gross Sales"],
    ["2026-10-01T10:15:00", "T-1001", "LITTER-20", "2", "$41.98"],
    ["2026-10-01T10:15:00", "T-1001", "FOOD-5", "1", "$12.99"],
    ["2026-10-02T15:40:00", "T-1002", "LITTER-20", "1", "$20.99"],
    ["2026-10-03T09:05:00", "T-1003", "LITTER-20", "-1", "-$20.99"],  # refund
]


def _sales_upload(store, rows, name="sales.csv"):
    return _upload(store, "sales", _csv(rows), name=name, location_id=store.location_id, source_system="square")


def test_same_sales_file_twice_is_one_import(store):
    first = _sales_upload(store, SALES)
    second = _sales_upload(store, SALES, name="sales (1).csv")
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]


def test_overlapping_sales_exports_count_each_sale_once(store):
    imp = _sales_upload(store, SALES).json()
    assert imp["mapping"]["columns"]["order_id"] == "Transaction ID"
    _apply(store, imp)
    overlapping = [SALES[0], *SALES[3:], ["2026-10-04T11:00:00", "T-1004", "FOOD-5", "3", "$38.97"]]
    second = _sales_upload(store, overlapping, name="sales-oct-3-4.csv").json()
    assert _apply(store, second)["summary"]["applied_counts"] == {"unchanged": 2, "applied": 1}

    lines = store.get("/v1/sales-lines").json()
    assert len(lines) == 5
    litter = [l for l in lines if l["variant_id"] == store.litter["id"]]
    assert sorted(Decimal(l["quantity"]) for l in litter) == [Decimal(-1), Decimal(1), Decimal(2)]
    refund = next(l for l in litter if l["external_order_id"] == "T-1003")
    assert refund["line_type"] == "refund"
    assert datetime.fromisoformat(refund["sold_at"]) == datetime(2026, 10, 3, 13, 5, tzinfo=timezone.utc)  # 09:05 New York


def test_same_item_twice_in_one_order_is_two_lines_and_reimports_line_up(store):
    rows = [SALES[0], SALES[1], ["2026-10-01T10:15:00", "T-1001", "LITTER-20", "3", "$62.97"]]
    imp = _sales_upload(store, rows).json()
    _apply(store, imp)
    lines = store.get("/v1/sales-lines").json()
    assert sorted(l["quantity"] for l in lines) == ["2.0000", "3.0000"]
    assert {l["external_line_key"] for l in lines} == {"sku:LITTER-20:sale:1", "sku:LITTER-20:sale:2"}
    again = _sales_upload(store, [SALES[0], *rows[1:], SALES[2]], name="again.csv").json()
    assert _apply(store, again)["summary"]["applied_counts"] == {"unchanged": 2, "applied": 1}


def test_conflicting_resend_of_a_recorded_sale_is_reported(store):
    _apply(store, _sales_upload(store, SALES[:2]).json())
    changed = [SALES[0], ["2026-10-01T10:15:00", "T-1001", "LITTER-20", "4", "$83.96"]]
    imp = _sales_upload(store, changed, name="edited.csv").json()
    done = _apply(store, imp, expect="failed")  # all-or-nothing: the person did not accept partial imports
    assert "nothing was applied" in done["failure"]
    errors = store.client.get(f"/v1/imports/{imp['id']}/errors.csv", headers=store.headers()).text
    assert "already recorded with quantity 2.0000" in errors


def test_us_dates_need_a_declared_format(store):
    rows = [["Date", "Transaction ID", "SKU", "Qty"], ["10/03/2026 2:15 PM", "T-9", "FOOD-5", "1"]]
    imp = _sales_upload(store, rows).json()
    (row,) = _preview(store, imp)["rows"]
    assert "declare the file's date format" in row["errors"][0]["message"]
    _mapping(store, imp, date_format="MM/DD/YYYY")
    _apply(store, imp)
    (line,) = store.get("/v1/sales-lines").json()
    assert datetime.fromisoformat(line["sold_at"]) == datetime(2026, 10, 3, 18, 15, tzinfo=timezone.utc)  # 2:15 PM EDT


def test_unknown_skus_block_unless_accepted_and_offer_candidates_only(store):
    rows = [SALES[0], SALES[1], ["2026-10-01T10:15:00", "T-1001", "DOG-FOOD-5LB", "1", "$12.99"]]
    imp = _sales_upload(store, rows).json()
    resp = _confirm_import(store, imp)
    assert resp.status_code == 422 and resp.json()["details"]["counts"]["with_errors"] == 1
    resp = _confirm_import(store, imp, accept_row_errors=True)
    assert resp.status_code == 202
    import_worker.run_once()
    assert store.get(f"/v1/imports/{imp['id']}").json()["summary"]["applied_counts"] == {"applied": 1, "error": 1}


# ---------------------------------------------------------------------------
# Stock counts
# ---------------------------------------------------------------------------


def _xlsx(rows: list[list[object]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _inventory(store):
    return {p["variant_id"]: Decimal(p["on_hand"]) for p in store.get("/v1/inventory").json()}


def test_xlsx_stock_count_sets_levels_and_creates_new_items_when_asked(store):
    as_of = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    content = _xlsx([["SKU", "Item name", "On Hand"], ["LITTER-20", "Litter", 18], ["FOOD-5", "Dog food", 7],
                     ["TREATS-1", "Chicken treats", 30]])
    imp = _upload(store, "inventory", content, name="count.xlsx", location_id=store.location_id).json()
    assert imp["file_format"] == "xlsx"
    _mapping(store, imp, as_of=as_of)
    p = _preview(store, imp)
    assert p["counts"]["with_errors"] == 1  # unknown TREATS-1
    unknown = next(r for r in p["rows"] if r["errors"])
    assert "candidates" in unknown  # look-alikes offered (may be empty), never auto-applied
    _mapping(store, imp, as_of=as_of, create_missing_variants=True)
    _apply(store, imp)

    levels = _inventory(store)
    assert levels[store.litter["id"]] == 18 and levels[store.food["id"]] == 7
    treats = next(v for v in store.get("/v1/variants").json() if v["sku"] == "TREATS-1")
    assert levels[treats["id"]] == 30
    assert len(store.get("/v1/inventory-snapshots").json()) == 3

    # A later count applies the difference as a count correction.
    later = _xlsx([["SKU", "On Hand"], ["LITTER-20", 12]])
    imp2 = _upload(store, "inventory", later, name="count2.xlsx", location_id=store.location_id).json()
    _mapping(store, imp2, as_of=datetime.now(timezone.utc).isoformat())
    _apply(store, imp2)
    assert _inventory(store)[store.litter["id"]] == 12


def test_count_older_than_recorded_changes_is_saved_but_not_applied(store):
    body = {"variant_id": store.litter["id"], "location_id": store.location_id, "delta": "5", "reason": "count"}
    store.post("/v1/inventory/movements", body, headers={"Idempotency-Key": idem()})
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    imp = _upload(store, "inventory", _csv([["SKU", "Qty"], ["LITTER-20", "40"]]), location_id=store.location_id).json()
    _mapping(store, imp, as_of=yesterday)
    assert _apply(store, imp)["summary"]["applied_counts"] == {"skipped": 1}
    assert _inventory(store)[store.litter["id"]] == 5


def test_pos_owned_location_gets_snapshots_only(store):
    pos = store.post("/v1/locations", {"name": "POS store", "timezone": "America/New_York",
                                       "inventory_write_owner": "square"}).json()
    imp = _upload(store, "inventory", _csv([["SKU", "Qty"], ["LITTER-20", "9"]]), location_id=pos["id"]).json()
    _mapping(store, imp, as_of=datetime.now(timezone.utc).isoformat())
    _apply(store, imp)
    assert store.get("/v1/inventory").json() == []
    (snap,) = store.get("/v1/inventory-snapshots", params={"location_id": pos["id"]}).json()
    assert snap["quantity"] == "9.0000"


# ---------------------------------------------------------------------------
# Open orders
# ---------------------------------------------------------------------------


def test_open_orders_convert_cases_via_confirmed_supplier_item(store):
    supplier = _approvable_supplier(store)
    item = store.post(f"/v1/suppliers/{supplier['id']}/items",
                      {"supplier_sku": "PH-LIT-20", "order_uom": "case", "units_per_order_uom": "12"}).json()
    rows = [["Supplier", "PO #", "SKU", "Qty Remaining", "ETA", "Confirmed"],
            ["Phillips Pet", "PO-77", "LITTER-20", "2", "2026-10-24", "yes"]]
    imp = _upload(store, "open_orders", _csv(rows), location_id=store.location_id).json()
    assert _preview(store, imp)["blocking_issues"] == ["declare_quantity_unit", "declare_as_of", "declare_complete_scope"]
    _mapping(store, imp, quantity_unit="order_unit", as_of=datetime.now(timezone.utc).isoformat(), complete_scope="none")
    (row,) = _preview(store, imp)["rows"]
    assert "no pack for this item" in row["errors"][0]["message"]  # mapping not confirmed yet

    _confirm(store, item, store.litter["id"])
    (row,) = _preview(store, imp)["rows"]
    assert row["interpretation"] == "PO-77: 2 case × 12 = 24 each outstanding"
    _apply(store, imp)
    (line,) = store.get("/v1/open-orders").json()
    assert (line["outstanding_qty"], line["supplier_confirmed"]) == ("24.0000", True)


# ---------------------------------------------------------------------------
# Lifecycle, permissions, safety
# ---------------------------------------------------------------------------


def test_confirm_is_bound_to_the_previewed_revision(store):
    imp = _sales_upload(store, SALES).json()
    resp = store.post(f"/v1/imports/{imp['id']}/confirm-mapping", {"revision": 0})
    assert resp.status_code == 409


def test_agent_drafts_mapping_but_only_a_person_confirms(store):
    from clawbot.domain.errors import PermissionDenied
    from clawbot.domain.imports import service
    from clawbot.policies.permissions import agent

    imp = _sales_upload(store, SALES).json()
    tenant = uuid.UUID(store.tenant_id)
    current = store.get(f"/v1/imports/{imp['id']}").json()
    with transaction() as s:
        service.update_mapping(s, tenant_id=tenant, actor=agent("onboarding-agent"), import_id=uuid.UUID(imp["id"]),
                               expected_revision=current["mapping_revision"], columns=current["mapping"]["columns"],
                               settings=current["mapping"]["settings"])
    with pytest.raises(PermissionDenied), transaction() as s:
        service.confirm(s, tenant_id=tenant, actor=agent("onboarding-agent"), import_id=uuid.UUID(imp["id"]),
                        expected_revision=current["mapping_revision"] + 1, accept_row_errors=False)
    actions = [(e["action"], e["actor_kind"]) for e in store.get("/v1/audit-events", params={"object_type": "import"}).json()]
    assert ("import.mapping_updated", "agent") in actions


def test_bookkeeper_cannot_create_supplier_items_through_an_import(store):
    supplier = _approvable_supplier(store)
    books = add_member(store, "books@example.com", "bookkeeper")
    imp = _upload(books, "supplier_price_list", _csv(PRICE_LIST), supplier_id=supplier["id"]).json()
    _mapping(books, imp, price_basis="per_order_unit")
    assert _confirm_import(books, imp).status_code == 403


def test_imports_are_tenant_private(client, store):
    imp = _sales_upload(store, SALES).json()
    other = new_store(client, "rival@example.com", "Rival")
    assert other.get(f"/v1/imports/{imp['id']}").status_code == 404
    assert other.get(f"/v1/imports/{imp['id']}/preview").status_code == 404
    other_loc = other.post("/v1/locations", {"name": "X", "timezone": "UTC"}).json()
    assert _upload(other, "sales", _csv(SALES), location_id=store.location_id, source_system="square").status_code == 404
    assert other_loc


def test_rejected_import_cannot_be_confirmed(store):
    imp = _sales_upload(store, SALES).json()
    assert store.post(f"/v1/imports/{imp['id']}/reject", {"reason": "wrong file"}).json()["status"] == "rejected"
    assert _confirm_import(store, imp).status_code == 409


def test_retried_apply_job_is_a_no_op(store):
    from clawbot.domain import outbox
    from clawbot.domain.imports.apply import apply_import

    imp = _sales_upload(store, SALES).json()
    assert _confirm_import(store, imp).status_code == 202
    tenant, import_id = uuid.UUID(store.tenant_id), uuid.UUID(imp["id"])
    with transaction() as s:  # worker applies but crashes before marking the job done
        (msg,) = outbox.claim_batch(s, lease=timedelta(seconds=-1), topics=("import.apply",))
        apply_import(s, tenant_id=tenant, import_id=import_id)
    assert import_worker.run_once() == 1  # lease expired; retry_safe job is re-run
    assert len(store.get("/v1/sales-lines").json()) == 4


def test_errors_csv_is_safe_to_open_in_a_spreadsheet(store):
    rows = [["Date", "Transaction ID", "SKU", "Qty"], ["2026-10-01", "T-1", '=HYPERLINK("http://evil","x")', "1"]]
    imp = _sales_upload(store, rows).json()
    body = store.client.get(f"/v1/imports/{imp['id']}/errors.csv", headers=store.headers()).text
    parsed = list(csv.reader(io.StringIO(body)))
    assert parsed[1][0] == "2" and all(not cell.startswith("=") for cell in parsed[1])
    assert safe_cell("+1") == "'+1" and safe_cell("-5") == "'-5" and safe_cell("@x") == "'@x" and safe_cell("ok") == "ok"


# ---------------------------------------------------------------------------
# Parsing and values
# ---------------------------------------------------------------------------


def test_csv_parsing_bom_semicolons_blank_lines():
    content = "﻿SKU;Qty\nA;1\n\nB;2\n".encode()
    parsed = parse_csv(content)
    assert parsed.header == ["SKU", "Qty"] and parsed.rows == [(2, ["A", "1"]), (4, ["B", "2"])]


@pytest.mark.parametrize(
    "name, content, message",
    [
        ("book.xlsm", b"PK..", "macro-free"),
        ("data.json", b"{}", "Upload a .csv or .xlsx"),
        ("a.csv", b"SKU,SKU\n1,2\n", "appears twice"),
        ("a.csv", b"SKU,Qty\nA,1,extra\n", "more values than there are column names"),
        ("a.csv", b"SKU,Qty\n", "no data rows"),
        ("a.csv", "SKU\n\xe9\n".encode("latin-1"), "UTF-8"),
        ("a.xlsx", b"not a zip", "readable .xlsx"),
    ],
)
def test_bad_files_are_refused_with_a_reason(name, content, message):
    with pytest.raises(ValidationFailed, match=message):
        parse_file(name, content)


@pytest.mark.parametrize(
    "raw, expected",
    [("1,234.50", Decimal("1234.50")), ("(5)", Decimal(-5)), ("$30.00", Decimal("30.00")), ("-2", Decimal(-2)),
     ("12 USD", Decimal(12))],
)
def test_numbers(raw, expected):
    assert v.decimal(raw, currency="USD") == expected


@pytest.mark.parametrize("raw", ["1,5", "12abc", "", "--1", "€5"])
def test_bad_numbers(raw):
    with pytest.raises(v.CellError):
        v.decimal(raw, currency="USD")


def test_spreadsheet_mangled_barcode_is_flagged():
    with pytest.raises(v.CellError, match="scientific notation"):
        v.barcode("3.60003E+11")


def test_unknown_item_preview_offers_look_alike_candidates(store):
    rows = [["SKU", "Item name", "Qty"], ["CL-20", "Clumping cat litter 20 lb", "4"]]
    imp = _upload(store, "inventory", _csv(rows), location_id=store.location_id).json()
    _mapping(store, imp, as_of=datetime.now(timezone.utc).isoformat())
    (row,) = _preview(store, imp)["rows"]
    assert row["errors"] and row["candidates"][0]["sku"] == "LITTER-20"
