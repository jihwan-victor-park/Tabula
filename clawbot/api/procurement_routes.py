"""FastAPI app — exposes the Procurement Agent as a REST API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from clawbot.agents.procurement_agent import run_full_procurement, run_procurement_agent
from clawbot.schemas.procurement import (
    CatalogEntry,
    KnownSupplier,
    ProcurementItem,
    ProcurementOrder,
    ProcurementReport,
    ProcureRequest,
    SupplierQuote,
)
from clawbot.tools.db_procurement import (
    init_db,
    list_catalog_entries,
    list_items,
    list_known_suppliers,
    list_quotes,
    set_item_status,
    upsert_catalog_entry,
    upsert_item,
    upsert_known_supplier,
)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example → .env and fill it in."
        )
    init_db()
    yield


app = FastAPI(
    title="Procurement Agent API",
    description=(
        "Claude-powered agent that finds wholesale suppliers for small business procurement. "
        "Searches the market, records quotes, and recommends the best sourcing options."
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
# Procurement items
# ---------------------------------------------------------------------------


@app.get("/items", response_model=list[ProcurementItem], summary="List all procurement items")
def get_items() -> list[ProcurementItem]:
    return list_items(active_only=False)


@app.post("/items", response_model=ProcurementItem, summary="Add or update a procurement item")
def post_item(item: ProcurementItem) -> ProcurementItem:
    try:
        return upsert_item(item)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.patch(
    "/items/{item_id}/activate",
    response_model=ProcurementItem,
    summary="Activate a procurement item",
)
def activate_item(item_id: str) -> ProcurementItem:
    try:
        return set_item_status(item_id, active=True)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")


@app.patch(
    "/items/{item_id}/deactivate",
    response_model=ProcurementItem,
    summary="Deactivate a procurement item",
)
def deactivate_item(item_id: str) -> ProcurementItem:
    try:
        return set_item_status(item_id, active=False)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item not found: {item_id}")


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


@app.get("/quotes", response_model=list[SupplierQuote], summary="List all supplier quotes")
def get_quotes(item_id: str | None = None) -> list[SupplierQuote]:
    return list_quotes(item_id=item_id)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@app.get("/summary", summary="Return high-level counts")
def get_summary() -> dict[str, Any]:
    all_items = list_items(active_only=False)
    active_items = [i for i in all_items if i.active]
    all_quotes = list_quotes()
    return {
        "procurement_items": {
            "active": len(active_items),
            "total": len(all_items),
        },
        "quotes": {
            "total": len(all_quotes),
        },
    }


# ---------------------------------------------------------------------------
# Source (run the agent)
# ---------------------------------------------------------------------------


class SourceBody(BaseModel):
    business_name: str
    location: str


@app.post("/source", response_model=ProcurementReport, summary="Run a full procurement sourcing scan")
def post_source(body: SourceBody) -> ProcurementReport:
    """
    Run the Procurement Agent for the given business and location.

    The agent will:
    - Retrieve all active procurement items
    - Search for wholesale suppliers for each item
    - Record quotes and compare to budget targets
    - Return a structured ProcurementReport with recommendations
    """
    try:
        return run_procurement_agent(
            business_name=body.business_name,
            location=body.location,
        )
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing configuration: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Procure (source + order form + iMessage confirmation)
# ---------------------------------------------------------------------------


@app.post(
    "/procure",
    response_model=ProcurementOrder,
    summary="Source suppliers, generate order form, and send iMessage for confirmation",
)
def post_procure(body: ProcureRequest) -> ProcurementOrder:
    """
    Full end-to-end procurement flow:

    1. If `inventory_url` is provided, fetch low-stock items from the Inventory
       Agent and auto-add them as active procurement items.
    2. Run the Procurement Agent to find wholesale suppliers for all active items.
    3. Build a structured order form (ProcurementOrder) with quantities and costs.
    4. Send the order form to the owner via iMessage asking for YES/NO confirmation.
    5. Return the ProcurementOrder including delivery status and the message text.
    """
    try:
        return run_full_procurement(
            business_name=body.business_name,
            location=body.location,
            recipient=body.recipient,
            inventory_url=body.inventory_url,
            send_confirmation=body.send_confirmation,
            item_ids=body.item_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing configuration: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Known suppliers
# ---------------------------------------------------------------------------


@app.get("/suppliers", response_model=list[KnownSupplier], summary="List known suppliers")
def get_suppliers() -> list[KnownSupplier]:
    return list_known_suppliers()


@app.post("/suppliers", response_model=KnownSupplier, summary="Add or update a known supplier")
def post_supplier(supplier: KnownSupplier) -> KnownSupplier:
    try:
        return upsert_known_supplier(supplier)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Supplier catalog
# ---------------------------------------------------------------------------


@app.get("/catalog", response_model=list[CatalogEntry], summary="List supplier catalog entries")
def get_catalog(supplier_id: str | None = None) -> list[CatalogEntry]:
    return list_catalog_entries(supplier_id=supplier_id)


@app.post(
    "/catalog",
    response_model=CatalogEntry,
    summary="Add or update a catalog entry (product keyword + cost + margin target)",
)
def post_catalog(entry: CatalogEntry) -> CatalogEntry:
    try:
        return upsert_catalog_entry(entry)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
