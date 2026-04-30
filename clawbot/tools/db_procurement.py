"""
MongoDB repository for Procurement Agent — items, quotes, suppliers, catalog.

Collections (database: $MONGODB_DB, default "clawbot"):
  procurement_items  — products the business wants to source
  supplier_quotes    — price quotes found for each item
  known_suppliers    — existing supplier relationships
  supplier_catalog   — supplier product catalog with cost/margin targets
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from clawbot.schemas.procurement import (
    CatalogEntry,
    KnownSupplier,
    ProcurementItem,
    SupplierQuote,
)
from clawbot.tools.mongodb import get_col


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _doc_to_item(doc: dict) -> ProcurementItem:
    return ProcurementItem(
        id=doc["_id"],
        name=doc["name"],
        quantity_needed=doc.get("quantity_needed", 1),
        budget_per_unit=doc.get("budget_per_unit"),
        currency=doc.get("currency", "USD"),
        notes=doc.get("notes"),
        active=doc.get("active", True),
        last_sourced_at=doc.get("last_sourced_at"),
    )


def _doc_to_quote(doc: dict) -> SupplierQuote:
    return SupplierQuote(
        id=doc["_id"],
        item_id=doc["item_id"],
        supplier=doc["supplier"],
        price_per_unit=doc["price_per_unit"],
        currency=doc.get("currency", "USD"),
        moq=doc.get("moq"),
        url=doc.get("url"),
        confidence=doc.get("confidence", "medium"),
        found_at=doc["found_at"],
    )


def _doc_to_supplier(doc: dict) -> KnownSupplier:
    return KnownSupplier(
        id=doc["_id"],
        name=doc["name"],
        categories=doc.get("categories", []),
        contact_email=doc.get("contact_email"),
        contact_phone=doc.get("contact_phone"),
        notes=doc.get("notes"),
        active=doc.get("active", True),
    )


def _doc_to_catalog_entry(doc: dict) -> CatalogEntry:
    return CatalogEntry(
        id=doc["_id"],
        supplier_id=doc["supplier_id"],
        product_keyword=doc["product_keyword"],
        cost_per_unit=doc["cost_per_unit"],
        currency=doc.get("currency", "USD"),
        moq=doc.get("moq"),
        typical_sell_price=doc.get("typical_sell_price"),
        target_margin_pct=doc.get("target_margin_pct", 30.0),
        last_updated=doc.get("last_updated"),
    )


# ---------------------------------------------------------------------------
# Schema bootstrap (indexes)
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create indexes on procurement collections."""
    get_col("procurement_items").create_index([("name", ASCENDING)])
    get_col("procurement_items").create_index([("active", ASCENDING)])
    get_col("supplier_quotes").create_index([("item_id", ASCENDING)])
    get_col("supplier_quotes").create_index([("price_per_unit", ASCENDING)])
    get_col("supplier_quotes").create_index([("found_at", DESCENDING)])
    get_col("known_suppliers").create_index([("name", ASCENDING)])
    get_col("known_suppliers").create_index([("categories", ASCENDING)])
    get_col("supplier_catalog").create_index([("supplier_id", ASCENDING)])
    get_col("supplier_catalog").create_index([("product_keyword", ASCENDING)])


# ---------------------------------------------------------------------------
# Items CRUD
# ---------------------------------------------------------------------------


def list_items(
    active_only: bool = False,
    item_ids: list[str] | None = None,
) -> list[ProcurementItem]:
    query: dict[str, Any] = {}
    if item_ids:
        query["_id"] = {"$in": item_ids}
    elif active_only:
        query["active"] = True
    docs = get_col("procurement_items").find(query).sort("name", ASCENDING)
    return [_doc_to_item(d) for d in docs]


def get_item(item_id: str) -> ProcurementItem:
    doc = get_col("procurement_items").find_one({"_id": item_id})
    if doc is None:
        raise KeyError(f"Unknown procurement item id: {item_id}")
    return _doc_to_item(doc)


def upsert_item(item: ProcurementItem) -> ProcurementItem:
    doc = {
        "_id": item.id,
        "name": item.name,
        "quantity_needed": item.quantity_needed,
        "budget_per_unit": item.budget_per_unit,
        "currency": item.currency or "USD",
        "notes": item.notes,
        "active": item.active,
        "last_sourced_at": item.last_sourced_at,
    }
    get_col("procurement_items").replace_one({"_id": item.id}, doc, upsert=True)
    return get_item(item.id)


def set_item_status(item_id: str, active: bool) -> ProcurementItem:
    result = get_col("procurement_items").update_one(
        {"_id": item_id}, {"$set": {"active": active}}
    )
    if result.matched_count == 0:
        raise KeyError(f"Unknown item id: {item_id}")
    return get_item(item_id)


def touch_item(item_id: str, last_sourced_at: str) -> ProcurementItem:
    get_col("procurement_items").update_one(
        {"_id": item_id}, {"$set": {"last_sourced_at": last_sourced_at}}
    )
    return get_item(item_id)


# ---------------------------------------------------------------------------
# Quotes CRUD
# ---------------------------------------------------------------------------


def insert_quote(quote: SupplierQuote) -> SupplierQuote:
    doc = {
        "_id": quote.id,
        "item_id": quote.item_id,
        "supplier": quote.supplier,
        "price_per_unit": quote.price_per_unit,
        "currency": quote.currency or "USD",
        "moq": quote.moq,
        "url": quote.url,
        "confidence": quote.confidence,
        "found_at": quote.found_at,
    }
    try:
        get_col("supplier_quotes").insert_one(doc)
    except Exception:
        pass  # duplicate — already recorded
    return quote


def list_quotes(item_id: str | None = None) -> list[SupplierQuote]:
    query: dict[str, Any] = {"item_id": item_id} if item_id else {}
    sort = [("price_per_unit", ASCENDING)] if item_id else [("found_at", DESCENDING)]
    docs = get_col("supplier_quotes").find(query).sort(sort)
    return [_doc_to_quote(d) for d in docs]


# ---------------------------------------------------------------------------
# Known suppliers CRUD
# ---------------------------------------------------------------------------


def list_known_suppliers(active_only: bool = False) -> list[KnownSupplier]:
    query: dict[str, Any] = {"active": True} if active_only else {}
    docs = get_col("known_suppliers").find(query).sort("name", ASCENDING)
    return [_doc_to_supplier(d) for d in docs]


def get_known_supplier(supplier_id: str) -> KnownSupplier:
    doc = get_col("known_suppliers").find_one({"_id": supplier_id})
    if doc is None:
        raise KeyError(f"Unknown supplier id: {supplier_id}")
    return _doc_to_supplier(doc)


def upsert_known_supplier(supplier: KnownSupplier) -> KnownSupplier:
    doc = {
        "_id": supplier.id,
        "name": supplier.name,
        "categories": supplier.categories,
        "contact_email": supplier.contact_email,
        "contact_phone": supplier.contact_phone,
        "notes": supplier.notes,
        "active": supplier.active,
    }
    get_col("known_suppliers").replace_one({"_id": supplier.id}, doc, upsert=True)
    return get_known_supplier(supplier.id)


# ---------------------------------------------------------------------------
# Supplier catalog CRUD
# ---------------------------------------------------------------------------


def list_catalog_entries(supplier_id: str | None = None) -> list[CatalogEntry]:
    query: dict[str, Any] = {"supplier_id": supplier_id} if supplier_id else {}
    docs = get_col("supplier_catalog").find(query).sort("product_keyword", ASCENDING)
    return [_doc_to_catalog_entry(d) for d in docs]


def upsert_catalog_entry(entry: CatalogEntry) -> CatalogEntry:
    doc = {
        "_id": entry.id,
        "supplier_id": entry.supplier_id,
        "product_keyword": entry.product_keyword,
        "cost_per_unit": entry.cost_per_unit,
        "currency": entry.currency or "USD",
        "moq": entry.moq,
        "typical_sell_price": entry.typical_sell_price,
        "target_margin_pct": entry.target_margin_pct,
        "last_updated": entry.last_updated or _utc_now(),
    }
    get_col("supplier_catalog").replace_one({"_id": entry.id}, doc, upsert=True)
    doc = get_col("supplier_catalog").find_one({"_id": entry.id})
    return _doc_to_catalog_entry(doc)


def find_catalog_entry(product_name: str) -> CatalogEntry | None:
    """
    Find the best matching catalog entry using case-insensitive regex on product_keyword.
    Returns the first match or None.
    """
    docs = get_col("supplier_catalog").find(
        {"product_keyword": {"$regex": product_name, "$options": "i"}}
    ).limit(1)
    for doc in docs:
        return _doc_to_catalog_entry(doc)
    # fallback: check if any keyword is a substring of product_name
    for entry in list_catalog_entries():
        if entry.product_keyword.lower() in product_name.lower():
            return entry
    return None
