"""
iMessage Agent — Pydantic v2 schemas for digest requests and results.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DigestRequest(BaseModel):
    """Request payload for building and sending a business digest via iMessage."""

    business_name: str = Field(..., description="Name of the small business")
    location: str = Field(..., description="City/region, e.g. 'Austin, TX'")
    categories: list[str] = Field(
        default_factory=list,
        description="Product categories to include in trend analysis",
    )
    price_scout_url: str = Field(
        "http://127.0.0.1:8000",
        description="Base URL of the running PriceScout API",
    )
    trend_url: str = Field(
        "http://127.0.0.1:8001",
        description="Base URL of the running Trend Analyst API",
    )
    procurement_url: str = Field(
        "http://127.0.0.1:8003",
        description="Base URL of the running Procurement Agent API",
    )
    recipient: str = Field(
        ...,
        description="iMessage handle to send the digest to, e.g. '+15551234567'",
    )
    include_trends: bool = Field(
        True,
        description="Whether to include trend analysis in the digest",
    )
    include_procurement: bool = Field(
        True,
        description="Whether to include procurement recommendations in the digest",
    )


class DigestResult(BaseModel):
    """Result of a digest send attempt."""

    sent: bool
    recipient: str
    message_text: str
    price_alert_count: int = 0
    trend_summary: str | None = None
    procurement_summary: str | None = None
    error: str | None = None
