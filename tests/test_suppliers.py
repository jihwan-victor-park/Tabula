"""CAT-01 (supplier half): supplier master, approval, supplier items, prices, offers."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from clawbot.domain import suppliers
from clawbot.domain.units import CurrencyMismatch
from clawbot.persistence.db import transaction
from clawbot.policies.permissions import human, system
from tests.conftest import add_member, new_store


@pytest.fixture
def store(client):
    api = new_store(client, "owner@example.com", "Paws & Co")
    loc = api.post("/v1/locations", {"name": "Main St", "timezone": "America/New_York"}).json()
    var = api.post("/v1/variants", {"sku": "LITTER-20", "name": "Clumping cat litter 20lb"}).json()
    api.location_id, api.variant_id = loc["id"], var["id"]
    return api


def _supplier(store, name="Phillips Pet", **extra):
    body = {"name": name, "currency": "USD", "timezone": "America/New_York", **extra}
    resp = store.post("/v1/suppliers", body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approvable_supplier(store, name="Phillips Pet"):
    s = _supplier(
        store, name, ordering_channel="email", payment_terms="net", payment_net_days=30, default_lead_time_days=4,
        delivery_weekdays=[2, 4], order_cutoff_local="14:00:00", merchant_account_number="ACCT-77",
        min_order_amount="150", freight_notes="Free delivery over $250, else $15",
    )
    c = store.post(f"/v1/suppliers/{s['id']}/contacts", {"email": "Orders@Phillips.example", "is_order_recipient": True}).json()
    store.post(f"/v1/suppliers/{s['id']}/contacts/{c['id']}/verify")
    store.client.put(f"/v1/suppliers/{s['id']}/coverage", json={"location_ids": [store.location_id]}, headers=store.headers())
    s = store.get(f"/v1/suppliers/{s['id']}").json()
    approved = store.post(f"/v1/suppliers/{s['id']}/status", {"version": s["version"], "status": "approved"})
    assert approved.status_code == 200, approved.text
    return approved.json()


def _item(store, supplier_id, sku="PH-LIT-20", per="12", **extra):
    resp = store.post(
        f"/v1/suppliers/{supplier_id}/items",
        {"supplier_sku": sku, "order_uom": "case", "units_per_order_uom": per, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _confirm(store, item, variant_id=None):
    resp = store.post(
        f"/v1/supplier-items/{item['id']}/mapping-decision",
        {"version": item["version"], "decision": "confirmed", "variant_id": variant_id or store.variant_id},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _price(store, item_id, amount, price_type="price_list", currency="USD", per="12", **extra):
    return store.post(
        f"/v1/supplier-items/{item_id}/prices",
        {
            "unit_price": amount, "currency": currency, "price_type": price_type,
            "order_uom": "case", "units_per_order_uom": per, **extra,
        },
    )


def _offers(store, location_id=None):
    params = {"location_id": location_id} if location_id else None
    return store.get(f"/v1/variants/{store.variant_id}/offers", params=params).json()


# ---------------------------------------------------------------------------
# Supplier lifecycle
# ---------------------------------------------------------------------------


def test_new_supplier_is_candidate_and_lists_blockers(store):
    s = _supplier(store)
    assert s["relationship_status"] == "candidate" and s["verified_at"] is None
    check = store.get(f"/v1/suppliers/{s['id']}/approval-check").json()
    assert check == {
        "approvable": False,
        "blockers": [
            "ordering_channel_missing", "merchant_account_missing", "payment_terms_unknown", "lead_time_missing",
            "min_order_terms_missing", "freight_terms_missing", "no_location_coverage",
        ],
    }
    resp = store.post(f"/v1/suppliers/{s['id']}/status", {"version": s["version"], "status": "approved"})
    assert resp.status_code == 422 and "blockers" in resp.json()["details"]


def test_email_supplier_needs_verified_order_address(store):
    s = _supplier(
        store, ordering_channel="email", payment_terms="cod", default_lead_time_days=3,
        merchant_account_required=False, min_order_amount="0", freight_notes="Flat $10",
    )
    store.client.put(f"/v1/suppliers/{s['id']}/coverage", json={"location_ids": [store.location_id]}, headers=store.headers())
    c = store.post(f"/v1/suppliers/{s['id']}/contacts", {"email": "rep@phillips.example", "is_order_recipient": True}).json()
    assert store.get(f"/v1/suppliers/{s['id']}/approval-check").json()["blockers"] == ["no_verified_order_email"]
    store.post(f"/v1/suppliers/{s['id']}/contacts/{c['id']}/verify")
    assert store.get(f"/v1/suppliers/{s['id']}/approval-check").json() == {"approvable": True, "blockers": []}


def test_approval_records_who_and_when(store):
    s = _approvable_supplier(store)
    assert s["relationship_status"] == "approved" and s["verified_at"] is not None
    assert s["verified_by_user_id"] == store.get("/v1/me").json()["user_id"]


def test_changing_order_routing_requires_reapproval(store):
    s = _approvable_supplier(store)
    resp = store.client.patch(
        f"/v1/suppliers/{s['id']}",
        json={"version": s["version"], "merchant_account_number": "ACCT-NEW"},
        headers=store.headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["relationship_status"] == "candidate" and resp.json()["verified_at"] is None
    actions = [e["action"] for e in store.get("/v1/audit-events", params={"object_type": "supplier"}).json()]
    assert "supplier.updated_needs_reapproval" in actions


def test_non_routing_edit_keeps_approval(store):
    s = _approvable_supplier(store)
    resp = store.client.patch(
        f"/v1/suppliers/{s['id']}", json={"version": s["version"], "free_shipping_threshold": "250"}, headers=store.headers()
    )
    assert resp.json()["relationship_status"] == "approved"
    assert resp.json()["free_shipping_threshold"] == "250.0000"


def test_supplier_edit_is_optimistic(store):
    s = _supplier(store)
    first = store.client.patch(f"/v1/suppliers/{s['id']}", json={"version": 1, "notes": "a"}, headers=store.headers())
    assert first.status_code == 200
    stale = store.client.patch(f"/v1/suppliers/{s['id']}", json={"version": 1, "notes": "b"}, headers=store.headers())
    assert stale.status_code == 409


def test_cannot_remove_last_verified_order_email_from_approved_supplier(store):
    s = _approvable_supplier(store)
    (contact,) = store.get(f"/v1/suppliers/{s['id']}/contacts").json()
    resp = store.client.delete(f"/v1/suppliers/{s['id']}/contacts/{contact['id']}", headers=store.headers())
    assert resp.status_code == 409
    resp = store.client.put(f"/v1/suppliers/{s['id']}/coverage", json={"location_ids": []}, headers=store.headers())
    assert resp.status_code == 409


def test_net_terms_need_days_and_bad_inputs_rejected(store):
    base = {"currency": "USD", "timezone": "America/New_York"}
    assert store.post("/v1/suppliers", {"name": "A", **base, "payment_terms": "net"}).status_code == 422
    assert store.post("/v1/suppliers", {"name": "B", **base, "delivery_weekdays": [0]}).status_code == 422
    assert store.post("/v1/suppliers", {"name": "C", "currency": "ZZZ", "timezone": "America/New_York"}).status_code == 422
    assert store.post("/v1/suppliers", {"name": "D", "currency": "USD", "timezone": "Mars/Base"}).status_code == 422


def test_closures(store):
    s = _supplier(store)
    ok = store.post(f"/v1/suppliers/{s['id']}/closures", {"starts_on": "2026-12-24", "ends_on": "2026-12-26", "reason": "Holiday"})
    assert ok.status_code == 201
    bad = store.post(f"/v1/suppliers/{s['id']}/closures", {"starts_on": "2026-12-26", "ends_on": "2026-12-24"})
    assert bad.status_code == 422
    assert len(store.get(f"/v1/suppliers/{s['id']}/closures").json()) == 1


# ---------------------------------------------------------------------------
# Supplier items, mapping, pack size (CP2 gate: case of 12 matches order and receipt)
# ---------------------------------------------------------------------------


def test_case_of_12_converts_both_ways(store):
    s = _supplier(store)
    item = _item(store, s["id"], per="12")
    q = store.get(f"/v1/supplier-items/{item['id']}/order-quantity", params={"base_qty": "48"}).json()
    assert (q["order_qty"], q["base_qty"], q["extra_base_qty"]) == ("4.0000", "48.0000", "0.0000")
    q = store.get(f"/v1/supplier-items/{item['id']}/order-quantity", params={"base_qty": "60"}).json()
    assert q["order_qty"] == "5.0000" and q["order_uom"] == "case"


def test_suggested_variant_is_not_a_confirmed_mapping(store):
    s = _approvable_supplier(store)
    item = _item(store, s["id"], suggested_variant_id=store.variant_id)
    assert item["mapping_status"] == "suggested"
    _price(store, item["id"], "30.00")
    (offer,) = _offers(store)
    assert offer["eligible"] is False and offer["blockers"] == ["mapping_suggested"]


def test_fully_set_up_offer_is_eligible_with_base_unit_cost(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    assert _price(store, item["id"], "30.00", source_ref="INV-1042").status_code == 201
    (offer,) = _offers(store, store.location_id)
    assert offer["eligible"] is True and offer["blockers"] == []
    assert offer["unit_cost_per_base"] == "2.500000"
    assert offer["lead_time_days"] == 4 and offer["price"]["source_ref"] == "INV-1042"


def test_pack_change_12_to_24_unconfirms_mapping_and_retires_price(store):
    """Spec 19.2: supplier changes a 12-pack to a 24-pack."""
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")

    resp = store.client.patch(
        f"/v1/supplier-items/{item['id']}",
        json={"version": item["version"], "units_per_order_uom": "24", "reason": "supplier changed case size"},
        headers=store.headers(),
    )
    assert resp.status_code == 200
    changed = resp.json()
    assert changed["mapping_status"] == "suggested" and changed["units_per_order_uom"] == "24.0000"

    (offer,) = _offers(store)
    assert set(offer["blockers"]) == {"mapping_suggested", "no_current_price"}
    history = store.get(f"/v1/supplier-items/{item['id']}/prices").json()
    assert len(history) == 1 and history[0]["superseded_at"] is not None
    assert history[0]["units_per_order_uom"] == "12.0000"

    _confirm(store, changed)
    _price(store, item["id"], "58.00", per="24")
    (offer,) = _offers(store)
    assert offer["eligible"] and offer["unit_cost_per_base"] == "2.416667"


def test_non_pack_edit_keeps_mapping_and_price(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")
    resp = store.client.patch(
        f"/v1/supplier-items/{item['id']}", json={"version": item["version"], "lead_time_days": 6}, headers=store.headers()
    )
    assert resp.json()["mapping_status"] == "confirmed"
    (offer,) = _offers(store)
    assert offer["eligible"] and offer["lead_time_days"] == 6


def test_offer_blockers_cover_supplier_item_variant_location(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")
    other_loc = store.post("/v1/locations", {"name": "Second St", "timezone": "America/New_York"}).json()

    assert _offers(store, other_loc["id"])[0]["blockers"] == ["not_delivering_to_location"]

    s = store.get(f"/v1/suppliers/{s['id']}").json()
    store.client.patch(f"/v1/suppliers/{s['id']}", json={"version": s["version"], "credit_hold": True}, headers=store.headers())
    item = store.get(f"/v1/supplier-items/{item['id']}").json()
    store.client.patch(f"/v1/supplier-items/{item['id']}", json={"version": item["version"], "status": "discontinued"}, headers=store.headers())
    v = store.get(f"/v1/variants/{store.variant_id}").json()
    store.client.patch(f"/v1/variants/{store.variant_id}", json={"version": v["version"], "status": "discontinued"}, headers=store.headers())

    (offer,) = _offers(store)
    assert offer["blockers"] == ["supplier_credit_hold", "item_discontinued", "variant_discontinued"]


def test_public_listing_is_recorded_but_never_orderable(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    assert _price(store, item["id"], "21.99", price_type="public_listing", currency="USD").status_code == 201
    (offer,) = _offers(store)
    assert offer["blockers"] == ["no_current_price"]
    assert len(store.get(f"/v1/supplier-items/{item['id']}/prices").json()) == 1


def test_price_history_supersedes_and_rejects_backdating(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")
    _price(store, item["id"], "31.50", price_type="invoice", source_ref="INV-2001")
    history = store.get(f"/v1/supplier-items/{item['id']}/prices").json()
    assert [h["unit_price"] for h in history] == ["31.5000", "30.0000"]
    assert history[0]["superseded_at"] is None and history[1]["superseded_at"] is not None

    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    assert _price(store, item["id"], "29.00", valid_from=old).status_code == 422


def test_expired_price_blocks_ordering(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    start = datetime.now(timezone.utc) - timedelta(days=10)
    _price(store, item["id"], "30.00", valid_from=start.isoformat(), expires_at=(start + timedelta(days=5)).isoformat())
    (offer,) = _offers(store)
    assert offer["blockers"] == ["price_expired"]


def test_orderable_price_must_be_in_supplier_currency(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    resp = _price(store, item["id"], "40000", currency="KRW")
    assert resp.status_code == 422


def test_cheapest_eligible_refuses_mixed_currencies(store):
    usd = _approvable_supplier(store, "US Distributor")
    krw = _supplier(store, "Seoul Supply", currency="KRW", timezone="Asia/Seoul")
    tenant_id = uuid.UUID(store.tenant_id)
    with transaction() as session:
        # Force-approve the KRW supplier to isolate the comparison rule.
        sup = suppliers.get_supplier(session, tenant_id=tenant_id, supplier_id=uuid.UUID(krw["id"]))
        sup.relationship_status, sup.verified_at, sup.default_lead_time_days = "approved", datetime.now(timezone.utc), 10
    i1 = _confirm(store, _item(store, usd["id"], sku="U1"))
    i2 = _confirm(store, _item(store, krw["id"], sku="K1"))
    _price(store, i1["id"], "30.00")
    _price(store, i2["id"], "40000", currency="KRW")

    with transaction() as session:
        offers = suppliers.offers_for_variant(session, tenant_id=tenant_id, variant_id=uuid.UUID(store.variant_id))
        assert all(o.eligible for o in offers) and len(offers) == 2
        with pytest.raises(CurrencyMismatch):
            suppliers.cheapest_eligible(offers)


def test_cheapest_eligible_picks_lowest_base_unit_cost(store):
    a = _approvable_supplier(store, "A Dist")
    b = _approvable_supplier(store, "B Dist")
    ia = _confirm(store, _item(store, a["id"], sku="A12", per="12"))
    ib = _confirm(store, _item(store, b["id"], sku="B24", per="24"))
    _price(store, ia["id"], "30.00")  # 2.50 / each
    _price(store, ib["id"], "57.60", per="24")  # 2.40 / each
    with transaction() as session:
        offers = suppliers.offers_for_variant(
            session, tenant_id=uuid.UUID(store.tenant_id), variant_id=uuid.UUID(store.variant_id)
        )
        assert suppliers.cheapest_eligible(offers).supplier_item.supplier_sku == "B24"


def test_concurrent_price_updates_leave_exactly_one_current(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    tenant_id, item_id = uuid.UUID(store.tenant_id), uuid.UUID(item["id"])
    owner_id = uuid.UUID(store.get("/v1/me").json()["user_id"])

    def record(amount):
        with transaction() as session:
            suppliers.record_price(
                session, tenant_id=tenant_id, actor=human(owner_id, "owner"), item_id=item_id,
                unit_price=Decimal(amount), currency="USD", price_type="price_list",
                order_uom="case", units_per_order_uom=Decimal(12),
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(record, [str(30 + i) for i in range(8)]))

    history = store.get(f"/v1/supplier-items/{item['id']}/prices").json()
    assert len(history) == 8
    assert sum(h["superseded_at"] is None for h in history) == 1


def test_db_enforces_single_current_price(store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    from clawbot.persistence.models import SupplierItemPrice

    with pytest.raises(IntegrityError), transaction() as session:
        for amount in ("30", "31"):
            session.add(
                SupplierItemPrice(
                    tenant_id=uuid.UUID(store.tenant_id), supplier_item_id=uuid.UUID(item["id"]), currency="USD",
                    unit_price=Decimal(amount), units_per_order_uom=Decimal(12), price_type="price_list",
                    valid_from=datetime.now(timezone.utc),
                )
            )
            session.flush()


def test_supplier_sku_resolves_variant_only_once_confirmed(store):
    s = _supplier(store)
    item = _item(store, s["id"], sku="PH-77", suggested_variant_id=store.variant_id)
    m = store.post("/v1/item-matches", {"supplier_id": s["id"], "supplier_sku": "PH-77"}).json()
    assert m["variant_id"] is None
    _confirm(store, item)
    m = store.post("/v1/item-matches", {"supplier_id": s["id"], "supplier_sku": "PH-77"}).json()
    assert (m["variant_id"], m["method"]) == (store.variant_id, "supplier_sku")


# ---------------------------------------------------------------------------
# Tenant isolation (merchant A's prices are never visible to merchant B)
# ---------------------------------------------------------------------------


def test_supplier_data_is_tenant_private(client, store):
    s = _approvable_supplier(store)
    item = _confirm(store, _item(store, s["id"]))
    _price(store, item["id"], "30.00")

    other = new_store(client, "rival@example.com", "Rival Pets")
    other_var = other.post("/v1/variants", {"sku": "LITTER-20", "name": "Clumping cat litter 20lb"}).json()

    assert other.get("/v1/suppliers").json() == []
    assert other.get(f"/v1/suppliers/{s['id']}").status_code == 404
    assert other.get(f"/v1/supplier-items/{item['id']}").status_code == 404
    assert other.get(f"/v1/supplier-items/{item['id']}/prices").status_code == 404
    assert other.post(f"/v1/supplier-items/{item['id']}/prices", {"unit_price": "1", "currency": "USD", "price_type": "quote", "order_uom": "case", "units_per_order_uom": "12"}).status_code == 404
    assert other.get(f"/v1/variants/{other_var['id']}/offers").json() == []
    # B cannot map A's supplier item to its own variant, nor A's variant into B's supplier.
    resp = other.post(
        f"/v1/supplier-items/{item['id']}/mapping-decision",
        {"version": 2, "decision": "confirmed", "variant_id": other_var["id"]},
    )
    assert resp.status_code == 404
    b_sup = _supplier(other, "B Dist")
    resp = other.post(
        f"/v1/suppliers/{b_sup['id']}/items",
        {"supplier_sku": "X", "order_uom": "case", "units_per_order_uom": "12", "suggested_variant_id": store.variant_id},
    )
    assert resp.status_code == 404


def test_receiver_cannot_manage_suppliers(client, store):
    receiver = add_member(store, "recv@example.com", "receiver")
    assert receiver.get("/v1/suppliers").status_code == 200
    assert receiver.post("/v1/suppliers", {"name": "X", "currency": "USD", "timezone": "UTC"}).status_code == 403
