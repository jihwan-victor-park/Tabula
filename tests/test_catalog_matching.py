"""CAT-01 (identity half): variants, GTIN, identity priority, text candidates, external mappings."""

from __future__ import annotations

import pytest

from tests.conftest import new_store


@pytest.fixture
def store(client):
    return new_store(client, "owner@example.com", "Paws & Co")


def _variant(store, sku, name, **extra):
    resp = store.post("/v1/variants", {"sku": sku, "name": name, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _match(store, **body):
    resp = store.post("/v1/item-matches", body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_variant_creates_product_and_normalises_gtin(store):
    v = _variant(store, "SHAMPOO-50", "Oatmeal shampoo 50ml", barcode="036000291452", size_value="50", size_unit="ml")
    assert v["gtin"] == "00036000291452"
    assert v["barcode"] == "036000291452"
    assert v["status"] == "active" and v["version"] == 1
    products = store.get("/v1/products").json()
    assert [p["id"] for p in products] == [v["product_id"]]


def test_same_gtin_in_another_format_is_rejected_as_duplicate(store):
    _variant(store, "A", "Item A", barcode="036000291452")
    resp = store.post("/v1/variants", {"sku": "B", "name": "Item B", "barcode": "0036000291452"})
    assert resp.status_code == 422
    assert "existing_variant_id" in resp.json()["details"]


def test_sizes_are_separate_variants_under_one_product(store):
    small = _variant(store, "SH-50", "Oatmeal shampoo 50ml", size_value="50", size_unit="ml")
    big = _variant(store, "SH-100", "Oatmeal shampoo 100ml", size_value="100", size_unit="ml", product_id=small["product_id"])
    assert small["id"] != big["id"] and small["product_id"] == big["product_id"]


def test_size_requires_unit_and_identity_is_immutable(store):
    assert store.post("/v1/variants", {"sku": "X", "name": "X", "size_value": "50"}).status_code == 422
    v = _variant(store, "SH-50", "Shampoo 50ml", size_value="50", size_unit="ml")
    # PATCH ignores identity fields entirely (not in the schema) — size stays.
    resp = store.client.patch(
        f"/v1/variants/{v['id']}",
        json={"version": 1, "size_value": "100", "name": "Shampoo 50 ml"},
        headers=store.headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["size_value"] == "50.0000" and resp.json()["name"] == "Shampoo 50 ml"


def test_variant_update_is_optimistic(store):
    v = _variant(store, "A", "Item A")
    ok = store.client.patch(f"/v1/variants/{v['id']}", json={"version": 1, "status": "discontinued"}, headers=store.headers())
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = store.client.patch(f"/v1/variants/{v['id']}", json={"version": 1, "name": "B"}, headers=store.headers())
    assert stale.status_code == 409


def test_upc_scan_finds_variant_stored_as_ean13(store):
    v = _variant(store, "FOOD", "Dog food", barcode="0036000291452")
    m = _match(store, barcode="036000291452")
    assert (m["variant_id"], m["method"], m["needs_review"]) == (v["id"], "gtin", False)


def test_identity_priority_and_conflicts(store):
    by_sku = _variant(store, "SKU-1", "Cat treats chicken")
    by_gtin = _variant(store, "SKU-2", "Cat treats tuna", barcode="4006381333931")

    m = _match(store, sku="SKU-1", barcode="4006381333931")
    assert m["variant_id"] == by_sku["id"] and m["method"] == "merchant_sku"
    assert m["conflicts"] == [{"method": "gtin", "variant_id": by_gtin["id"]}]
    assert m["needs_review"] is True


def test_only_confirmed_external_mappings_resolve(store):
    v = _variant(store, "SKU-1", "Cat litter 20lb")
    other = _variant(store, "SKU-2", "Cat litter 40lb")
    proposal = store.post(
        "/v1/external-mappings",
        {"source_system": "square", "source_account": "M1", "external_id": "ITEM_9", "variant_id": v["id"], "match_method": "text_candidate"},
    ).json()
    assert proposal["status"] == "suggested"
    assert _match(store, source_system="square", source_account="M1", external_id="ITEM_9")["variant_id"] is None

    store.post(f"/v1/external-mappings/{proposal['id']}/decision", {"decision": "confirmed", "variant_id": v["id"]})
    m = _match(store, source_system="square", source_account="M1", external_id="ITEM_9", sku="SKU-2")
    assert m["variant_id"] == v["id"] and m["method"] == "provider_id"
    assert m["conflicts"] == [{"method": "merchant_sku", "variant_id": other["id"]}]


def test_confirmed_mapping_is_not_overwritten_by_a_new_proposal(store):
    a = _variant(store, "A", "Item A")
    b = _variant(store, "B", "Item B")
    body = {"source_system": "square", "external_id": "X", "match_method": "manual"}
    m = store.post("/v1/external-mappings", {**body, "variant_id": a["id"]}).json()
    store.post(f"/v1/external-mappings/{m['id']}/decision", {"decision": "confirmed", "variant_id": a["id"]})

    resp = store.post("/v1/external-mappings", {**body, "variant_id": b["id"]})
    assert resp.status_code == 409

    store.post(f"/v1/external-mappings/{m['id']}/decision", {"decision": "rejected", "variant_id": a["id"], "reason": "wrong item"})
    again = store.post("/v1/external-mappings", {**body, "variant_id": b["id"]}).json()
    assert again["id"] == m["id"] and again["status"] == "suggested" and again["variant_id"] == b["id"]


def test_rejected_proposal_for_same_variant_stays_rejected(store):
    a = _variant(store, "A", "Item A")
    body = {"source_system": "csv", "external_id": "row-key-1", "variant_id": a["id"], "match_method": "text_candidate"}
    m = store.post("/v1/external-mappings", body).json()
    store.post(f"/v1/external-mappings/{m['id']}/decision", {"decision": "rejected", "variant_id": a["id"]})
    assert store.post("/v1/external-mappings", body).json()["status"] == "rejected"


def test_text_similarity_never_resolves_and_flags_size_and_pack(store):
    _variant(store, "SH-50", "Oatmeal Dog Shampoo 50ml", size_value="50", size_unit="ml")
    _variant(store, "SH-100", "Oatmeal Dog Shampoo 100ml", size_value="100", size_unit="ml")
    _variant(store, "CHEW-1", "Bully stick chew")
    _variant(store, "CHEW-12", "Bully stick chew 12 pack", pack_count=12)

    m = _match(store, name="oatmeal dog shampoo 100 ml")
    assert m["variant_id"] is None and m["needs_review"] is True
    by_sku = {c["sku"]: c for c in m["candidates"]}
    assert by_sku["SH-100"]["warnings"] == []
    assert by_sku["SH-50"]["warnings"] == ["size_conflict"]
    assert m["candidates"][0]["sku"] == "SH-100"  # clean candidates rank first

    m = _match(store, name="Bully stick chew 12pk")
    by_sku = {c["sku"]: c for c in m["candidates"]}
    assert by_sku["CHEW-12"]["warnings"] == []
    assert by_sku["CHEW-1"]["warnings"] == ["pack_count_conflict"]


def test_litre_and_millilitre_compare_equal(store):
    _variant(store, "BIG", "Pet shampoo 1L", size_value="1", size_unit="l")
    m = _match(store, name="Pet shampoo 1000ml")
    assert m["candidates"][0]["warnings"] == []


def test_tenant_isolation_for_catalog(client):
    a = new_store(client, "a@example.com", "A")
    b = new_store(client, "b@example.com", "B")
    va = _variant(a, "SAME-SKU", "Dog food", barcode="036000291452")
    # Same SKU and GTIN are fine in another tenant…
    _variant(b, "SAME-SKU", "Dog food", barcode="036000291452")
    # …and B never resolves to A's variant.
    assert _match(b, sku="SAME-SKU")["variant_id"] != va["id"]
    resp = b.post(
        "/v1/external-mappings",
        {"source_system": "square", "external_id": "X", "variant_id": va["id"], "match_method": "manual"},
    )
    assert resp.status_code == 404
