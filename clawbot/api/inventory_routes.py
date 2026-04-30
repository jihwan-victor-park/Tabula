"""FastAPI app — exposes the Inventory Agent as a REST API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

from clawbot.agents.inventory_agent import run_inventory_agent, scan_barcode
from clawbot.schemas.inventory import InventoryItem, InventoryReport, StockTransaction
from clawbot.tools.barcode_lookup import lookup_barcode
from clawbot.tools.db_inventory import (
    adjust_stock,
    get_item,
    get_low_stock_items,
    init_db,
    list_items,
    list_transactions,
    upsert_item,
)
from clawbot.tools.mongodb import get_col


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example → .env and fill it in."
        )
    init_db()
    yield


app = FastAPI(
    title="Inventory Agent API",
    description=(
        "Inventory management for small toy stores. "
        "Scan barcodes to look up products, track stock levels, and get low-stock alerts."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Mobile barcode scanner UI
# ---------------------------------------------------------------------------

_SCANNER_HTML = Path(__file__).parent.parent / "static" / "scanner.html"


@app.get("/scanner", response_class=HTMLResponse, include_in_schema=False)
def get_scanner() -> HTMLResponse:
    """Serve the mobile barcode scanner web UI."""
    return HTMLResponse(content=_SCANNER_HTML.read_text(), status_code=200)


# ---------------------------------------------------------------------------
# Barcode lookup
# ---------------------------------------------------------------------------


@app.get("/barcode/{barcode}", summary="Look up product info by barcode")
def get_barcode(barcode: str) -> dict[str, Any]:
    """Look up product name, brand, category, and market price from a UPC/EAN barcode."""
    result = lookup_barcode(barcode)
    return result.model_dump()


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------


@app.get("/items", response_model=list[InventoryItem], summary="List all inventory items")
def get_items(
    category: str | None = None,
    low_stock_only: bool = Query(False, alias="low_stock"),
) -> list[InventoryItem]:
    return list_items(category=category, low_stock_only=low_stock_only)


@app.get("/items/{item_id}", response_model=InventoryItem, summary="Get a single inventory item")
def get_inventory_item(item_id: str) -> InventoryItem:
    try:
        return get_item(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")


@app.post("/items", response_model=InventoryItem, summary="Add or update an inventory item")
def post_item(item: InventoryItem) -> InventoryItem:
    try:
        return upsert_item(item)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Scan (barcode → auto lookup + stock update)
# ---------------------------------------------------------------------------


class ScanBody(BaseModel):
    barcode: str
    quantity_change: int = 1
    reason: str = "scan"
    sell_price: float | None = None
    reorder_point: int = 5


@app.post("/scan", summary="Scan a barcode to add/remove stock")
def post_scan(body: ScanBody) -> dict[str, Any]:
    """
    Scan a barcode to update inventory.
    Automatically looks up product info if the item is new.
    quantity_change: positive = add stock, negative = remove stock.
    """
    try:
        return scan_barcode(
            barcode=body.barcode,
            quantity_change=body.quantity_change,
            reason=body.reason,
            sell_price=body.sell_price,
            reorder_point=body.reorder_point,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Stock adjustment
# ---------------------------------------------------------------------------


class AdjustBody(BaseModel):
    quantity_change: int
    reason: str = "adjustment"
    notes: str | None = None


@app.post("/items/{item_id}/adjust", response_model=InventoryItem, summary="Adjust stock for an item")
def post_adjust(item_id: str, body: AdjustBody) -> InventoryItem:
    try:
        return adjust_stock(
            item_id=item_id,
            quantity_change=body.quantity_change,
            reason=body.reason,
            notes=body.notes,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")


# ---------------------------------------------------------------------------
# Low stock
# ---------------------------------------------------------------------------


@app.get("/low-stock", summary="Get items below reorder point")
def get_low_stock() -> dict[str, Any]:
    alerts = get_low_stock_items()
    return {
        "count": len(alerts),
        "items": [a.model_dump() for a in alerts],
    }


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


@app.get("/transactions", response_model=list[StockTransaction], summary="List stock transactions")
def get_transactions(item_id: str | None = None, limit: int = 50) -> list[StockTransaction]:
    return list_transactions(item_id=item_id, limit=limit)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@app.get("/summary", summary="High-level inventory counts")
def get_summary() -> dict[str, Any]:
    all_items = list_items()
    low_stock = get_low_stock_items()
    out_of_stock = [i for i in all_items if i.quantity == 0]
    return {
        "total_items": len(all_items),
        "low_stock": len(low_stock),
        "out_of_stock": len(out_of_stock),
    }


# ---------------------------------------------------------------------------
# Full agent report
# ---------------------------------------------------------------------------


@app.post("/report", response_model=InventoryReport, summary="Run full inventory agent report")
def post_report() -> InventoryReport:
    """Run the Claude inventory agent to produce a full stock analysis report."""
    try:
        return run_inventory_agent()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Dashboard data endpoints (all collections via MongoDB)
# ---------------------------------------------------------------------------


def _strip_id(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id", ""))
    return doc


@app.get("/db/inventory", include_in_schema=False)
def db_inventory() -> list[dict]:
    return [_strip_id(d) for d in get_col("inventory").find().sort("name", 1)]


@app.get("/db/transactions", include_in_schema=False)
def db_transactions() -> list[dict]:
    return [_strip_id(d) for d in get_col("stock_transactions").find().sort("recorded_at", -1).limit(200)]


@app.get("/db/price-watchlist", include_in_schema=False)
def db_price_watchlist() -> list[dict]:
    return [_strip_id(d) for d in get_col("price_watchlist").find().sort("label", 1)]


@app.get("/db/price-alerts", include_in_schema=False)
def db_price_alerts() -> list[dict]:
    return [_strip_id(d) for d in get_col("price_alerts").find().sort("created_at", -1)]


@app.get("/db/procurement", include_in_schema=False)
def db_procurement() -> list[dict]:
    return [_strip_id(d) for d in get_col("procurement_items").find().sort("name", 1)]


@app.get("/db/suppliers", include_in_schema=False)
def db_suppliers() -> list[dict]:
    return [_strip_id(d) for d in get_col("known_suppliers").find().sort("name", 1)]


@app.get("/db/sales", include_in_schema=False)
def db_sales() -> list[dict]:
    return [_strip_id(d) for d in get_col("sales").find().sort("sale_date", -1).limit(300)]


# ---------------------------------------------------------------------------
# Dashboard UI
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = Path(__file__).parent.parent / "static" / "dashboard.html"
_DISPLAY_HTML   = Path(__file__).parent.parent / "static" / "display.html"


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def get_dashboard() -> HTMLResponse:
    return HTMLResponse(content=_DASHBOARD_HTML.read_text(), status_code=200)


@app.get("/display", response_class=HTMLResponse, include_in_schema=False)
def get_display() -> HTMLResponse:
    return HTMLResponse(content=_DISPLAY_HTML.read_text(), status_code=200)
