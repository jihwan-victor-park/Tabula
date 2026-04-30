"""
PriceScout — Pydantic v2 schemas for watchlist, findings, alerts, and reports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


class Baseline(BaseModel):
    """Supplier baseline pricing snapshot."""

    supplier: str
    price: float
    currency: str = "USD"
    unit: str | None = None
    quantity: int | None = None
    last_verified_at: str | None = None


# ---------------------------------------------------------------------------
# Watch item
# ---------------------------------------------------------------------------


class WatchItem(BaseModel):
    """A product or supplier relationship being monitored for price changes."""

    id: str
    label: str
    mode: str = Field("vendor", description="'vendor' or 'competitor'")
    active: bool = True
    region: str | None = None
    query: str | None = None
    notes: str | None = None
    baseline: Baseline | None = None
    threshold_pct: float = Field(5.0, description="Minimum savings % to trigger alert")
    last_scan_at: str | None = None
    last_alert_at: str | None = None


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class BestOption(BaseModel):
    """Best market price found during a scan."""

    supplier: str
    price: float
    currency: str = "USD"
    unit: str | None = None
    url: str | None = None


class Finding(BaseModel):
    """Result of one market-price scan for a single product."""

    id: str
    watch_id: str
    product_name: str  # specific product found on the scraped page or searched
    label: str
    scanned_at: str
    scraped_price: float | None = None  # price shown on the source site (e.g. pebblestoys.com)
    baseline: Baseline | None = None
    best_option: BestOption | None = None  # best market price across all vendors
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "medium"
    notes: str | None = None
    delta_pct: float = 0.0  # savings vs baseline; negative = more expensive than baseline


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------


class Alert(BaseModel):
    """Triggered when savings exceed the watch item's threshold."""

    id: str
    watch_id: str
    status: str = Field("new", description="'new' or 'acknowledged'")
    created_at: str
    acknowledged_at: str | None = None
    summary: str
    baseline: Baseline | None = None
    best_option: BestOption | None = None
    delta_pct: float = 0.0
    notes: str | None = None


# ---------------------------------------------------------------------------
# Scan request (agent → tool)
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    """Payload the agent sends when recording a finding."""

    watch_id: str
    product_name: str  # specific product being recorded
    supplier: str      # vendor offering the best market price
    price: float       # best market price found
    scraped_price: float | None = None  # price shown on the source/competitor site
    url: str | None = None
    notes: str | None = None
    confidence: str = "medium"
    candidates: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Price report (agent final output)
# ---------------------------------------------------------------------------


class PriceReport(BaseModel):
    """Full output from one run of the price-scout agent."""

    business_name: str
    location: str
    scan_date: str = Field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d")
    )
    items_scanned: int = 0
    alerts_triggered: int = 0
    findings: list[Finding] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    executive_summary: str = ""
    raw_agent_reasoning: str | None = Field(
        None, description="Agent chain-of-thought, useful for debugging"
    )
