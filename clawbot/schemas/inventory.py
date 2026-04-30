"""
Inventory Agent — Pydantic v2 schemas for inventory items, barcode results, and reports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Barcode lookup result
# ---------------------------------------------------------------------------


class BarcodeResult(BaseModel):
    """Product info returned from a barcode lookup API."""

    barcode: str
    name: str
    brand: str | None = None
    category: str | None = None
    description: str | None = None
    image_url: str | None = None
    market_price: float | None = None
    source: str = "upcitemdb"


# ---------------------------------------------------------------------------
# Inventory item
# ---------------------------------------------------------------------------


class InventoryItem(BaseModel):
    """A product tracked in the store's inventory."""

    id: str = Field(description="Barcode / UPC used as primary key")
    name: str
    brand: str | None = None
    category: str | None = None
    description: str | None = None
    image_url: str | None = None
    quantity: int = 0
    reorder_point: int = Field(5, description="Alert when quantity falls below this")
    cost_price: float | None = None
    sell_price: float | None = None
    currency: str = "USD"
    last_updated: str | None = None


# ---------------------------------------------------------------------------
# Stock transaction
# ---------------------------------------------------------------------------


class StockTransaction(BaseModel):
    """A record of stock being added or removed."""

    id: str
    item_id: str
    quantity_change: int = Field(description="Positive = stock added, negative = stock removed")
    reason: str = Field(description="'restock', 'sale', 'adjustment', 'scan'")
    notes: str | None = None
    recorded_at: str


# ---------------------------------------------------------------------------
# Low stock alert
# ---------------------------------------------------------------------------


class LowStockAlert(BaseModel):
    """Item whose quantity has fallen below its reorder point."""

    item_id: str
    name: str
    brand: str | None = None
    category: str | None = None
    quantity: int
    reorder_point: int
    units_below_threshold: int


# ---------------------------------------------------------------------------
# Inventory report
# ---------------------------------------------------------------------------


class InventoryReport(BaseModel):
    """Full output from one run of the inventory agent."""

    scan_date: str = Field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d")
    )
    total_items: int = 0
    low_stock_count: int = 0
    low_stock_items: list[LowStockAlert] = Field(default_factory=list)
    recently_updated: list[InventoryItem] = Field(default_factory=list)
    executive_summary: str = ""
