"""
Procurement Agent — Pydantic v2 schemas for procurement items, quotes, and reports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Procurement item (what the business wants to source)
# ---------------------------------------------------------------------------


class ProcurementItem(BaseModel):
    """A product the business wants to procure from a supplier."""

    id: str
    name: str
    quantity_needed: int = 1
    budget_per_unit: float | None = None
    currency: str = "USD"
    notes: str | None = None
    active: bool = True
    last_sourced_at: str | None = None


# ---------------------------------------------------------------------------
# Supplier quote
# ---------------------------------------------------------------------------


class SupplierQuote(BaseModel):
    """A price quote from a supplier for a procurement item."""

    id: str
    item_id: str
    supplier: str
    price_per_unit: float
    currency: str = "USD"
    moq: int | None = Field(None, description="Minimum order quantity")
    url: str | None = None
    confidence: str = "medium"
    found_at: str


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


class ProcurementRecommendation(BaseModel):
    """Best sourcing recommendation for one procurement item."""

    item_id: str
    product_name: str
    recommended_supplier: str
    price_per_unit: float
    currency: str = "USD"
    moq: int | None = None
    url: str | None = None
    savings_vs_budget_pct: float | None = None
    confidence: str = "medium"
    notes: str | None = None
    all_quotes: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Source request (agent → tool)
# ---------------------------------------------------------------------------


class QuoteRequest(BaseModel):
    """Payload the agent sends when recording a supplier quote."""

    item_id: str
    supplier: str
    price_per_unit: float
    moq: int | None = None
    url: str | None = None
    confidence: str = "medium"


# ---------------------------------------------------------------------------
# Procurement report (agent final output)
# ---------------------------------------------------------------------------


class ProcurementReport(BaseModel):
    """Full output from one run of the procurement agent."""

    business_name: str
    location: str
    scan_date: str = Field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d")
    )
    items_sourced: int = 0
    recommendations: list[ProcurementRecommendation] = Field(default_factory=list)
    executive_summary: str = ""
    raw_agent_reasoning: str | None = Field(
        None, description="Agent chain-of-thought, useful for debugging"
    )


# ---------------------------------------------------------------------------
# Known suppliers (the business's existing supplier relationships)
# ---------------------------------------------------------------------------


class KnownSupplier(BaseModel):
    """A supplier the business already has a relationship with."""

    id: str
    name: str
    categories: list[str] = Field(
        default_factory=list,
        description="Product categories this supplier covers, e.g. ['Books', 'Toys']",
    )
    contact_email: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    active: bool = True


class CatalogEntry(BaseModel):
    """A product in a known supplier's catalog, with cost and margin targets."""

    id: str
    supplier_id: str
    product_keyword: str = Field(
        description="Keyword matched against product names (case-insensitive substring match)"
    )
    cost_per_unit: float
    currency: str = "USD"
    moq: int | None = None
    typical_sell_price: float | None = Field(
        None, description="What the business typically charges customers for this product"
    )
    target_margin_pct: float = Field(
        30.0, description="Minimum acceptable gross margin percentage"
    )
    last_updated: str | None = None


# ---------------------------------------------------------------------------
# Order form (generated from a ProcurementReport)
# ---------------------------------------------------------------------------


class OrderLineItem(BaseModel):
    """One line in a procurement order."""

    item_id: str
    product_name: str
    quantity: int
    supplier: str
    price_per_unit: float
    total_cost: float
    currency: str = "USD"
    moq: int | None = None
    url: str | None = None
    confidence: str = "medium"
    # Margin analysis (populated when a CatalogEntry match is found)
    known_cost_per_unit: float | None = Field(
        None, description="Cost from the business's existing supplier catalog"
    )
    typical_sell_price: float | None = None
    margin_pct: float | None = Field(
        None, description="(sell_price - cost_price) / sell_price * 100"
    )
    margin_viable: bool | None = Field(
        None, description="True when margin_pct >= catalog target_margin_pct"
    )


class ProcurementOrder(BaseModel):
    """A purchase order generated from a ProcurementReport, pending owner confirmation."""

    order_id: str
    business_name: str
    location: str
    created_at: str
    line_items: list[OrderLineItem] = Field(default_factory=list)
    total_cost: float = 0.0
    currency: str = "USD"
    confirmation_sent: bool = False
    confirmation_recipient: str | None = None
    imsg_text: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Procure request (POST /procure)
# ---------------------------------------------------------------------------


class ProcureRequest(BaseModel):
    """Request body for the full procure-and-confirm flow."""

    business_name: str
    location: str
    recipient: str = Field(description="iMessage phone number or Apple ID to notify")
    inventory_url: str | None = Field(
        None,
        description="Base URL of the Inventory Agent API (e.g. http://localhost:8004). "
                    "If provided, low-stock items are auto-ingested as procurement items.",
    )
    send_confirmation: bool = Field(
        True,
        description="If False, generate the order form but skip sending the iMessage. "
                    "Useful when an orchestrator will compose and send its own richer message.",
    )
    item_ids: list[str] | None = Field(
        None,
        description="If provided, only source these specific item IDs. "
                    "Useful when the orchestrator adds a single product and wants to avoid "
                    "re-sourcing all existing procurement items.",
    )
