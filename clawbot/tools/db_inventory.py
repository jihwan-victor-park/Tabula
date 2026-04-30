"""
MongoDB repository for Inventory Agent — items and stock transactions.

Collections (database: $MONGODB_DB, default "clawbot"):
  inventory          — one document per SKU/barcode (_id = barcode)
  stock_transactions — append-only log of quantity changes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from clawbot.schemas.inventory import InventoryItem, LowStockAlert, StockTransaction
from clawbot.tools.mongodb import get_col


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _doc_to_item(doc: dict) -> InventoryItem:
    return InventoryItem(
        id=doc["_id"],
        name=doc["name"],
        brand=doc.get("brand"),
        category=doc.get("category"),
        description=doc.get("description"),
        image_url=doc.get("image_url"),
        quantity=doc.get("quantity", 0),
        reorder_point=doc.get("reorder_point", 5),
        cost_price=doc.get("cost_price"),
        sell_price=doc.get("sell_price"),
        currency=doc.get("currency", "USD"),
        last_updated=doc.get("last_updated"),
    )


def _doc_to_transaction(doc: dict) -> StockTransaction:
    return StockTransaction(
        id=str(doc["_id"]),
        item_id=doc["item_id"],
        quantity_change=doc["quantity_change"],
        reason=doc.get("reason", "adjustment"),
        notes=doc.get("notes"),
        recorded_at=doc["recorded_at"],
    )


# ---------------------------------------------------------------------------
# Schema bootstrap (indexes)
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create indexes on inventory collections."""
    inv = get_col("inventory")
    inv.create_index([("category", ASCENDING)])
    inv.create_index([("quantity", ASCENDING)])
    inv.create_index([("name", ASCENDING)])

    tx = get_col("stock_transactions")
    tx.create_index([("item_id", ASCENDING)])
    tx.create_index([("recorded_at", DESCENDING)])


# ---------------------------------------------------------------------------
# Inventory items CRUD
# ---------------------------------------------------------------------------


def list_items(category: str | None = None, low_stock_only: bool = False) -> list[InventoryItem]:
    col = get_col("inventory")
    query: dict[str, Any] = {}
    if low_stock_only:
        query["$expr"] = {"$lte": ["$quantity", "$reorder_point"]}
    elif category:
        query["category"] = {"$regex": category, "$options": "i"}

    sort = [("quantity", ASCENDING)] if low_stock_only else [("name", ASCENDING)]
    return [_doc_to_item(d) for d in col.find(query).sort(sort)]


def get_item(item_id: str) -> InventoryItem:
    doc = get_col("inventory").find_one({"_id": item_id})
    if doc is None:
        raise KeyError(f"Unknown inventory item: {item_id}")
    return _doc_to_item(doc)


def upsert_item(item: InventoryItem) -> InventoryItem:
    now = _utc_now()
    doc = {
        "_id": item.id,
        "name": item.name,
        "brand": item.brand,
        "category": item.category,
        "description": item.description,
        "image_url": item.image_url,
        "quantity": item.quantity,
        "reorder_point": item.reorder_point,
        "cost_price": item.cost_price,
        "sell_price": item.sell_price,
        "currency": item.currency or "USD",
        "last_updated": item.last_updated or now,
    }
    get_col("inventory").replace_one({"_id": item.id}, doc, upsert=True)
    return get_item(item.id)


def adjust_stock(
    item_id: str,
    quantity_change: int,
    reason: str = "adjustment",
    notes: str | None = None,
) -> InventoryItem:
    """Atomically increment/decrement quantity and record the transaction."""
    now = _utc_now()
    result = get_col("inventory").update_one(
        {"_id": item_id},
        {"$inc": {"quantity": quantity_change}, "$set": {"last_updated": now}},
    )
    if result.matched_count == 0:
        raise KeyError(f"Unknown inventory item: {item_id}")

    tx_id = f"tx-{item_id}-{now.replace(':', '').replace('-', '').replace('Z', '')}"
    get_col("stock_transactions").insert_one({
        "_id": tx_id,
        "item_id": item_id,
        "quantity_change": quantity_change,
        "reason": reason,
        "notes": notes,
        "recorded_at": now,
    })
    return get_item(item_id)


def get_low_stock_items() -> list[LowStockAlert]:
    """Return items where quantity <= reorder_point, using a MongoDB expression query."""
    docs = get_col("inventory").find(
        {"$expr": {"$lte": ["$quantity", "$reorder_point"]}},
    ).sort("quantity", ASCENDING)
    alerts = []
    for doc in docs:
        item = _doc_to_item(doc)
        alerts.append(LowStockAlert(
            item_id=item.id,
            name=item.name,
            brand=item.brand,
            category=item.category,
            quantity=item.quantity,
            reorder_point=item.reorder_point,
            units_below_threshold=item.reorder_point - item.quantity,
        ))
    return alerts


def list_transactions(item_id: str | None = None, limit: int = 50) -> list[StockTransaction]:
    query: dict[str, Any] = {}
    if item_id:
        query["item_id"] = item_id
    docs = (
        get_col("stock_transactions")
        .find(query)
        .sort("recorded_at", DESCENDING)
        .limit(limit)
    )
    return [_doc_to_transaction(d) for d in docs]
