from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class TrendRequest(BaseModel):
    """Request payload sent to the trend analyst agent."""

    business_name: str = Field(..., description="Name of the small business")
    location: str = Field(..., description="City/region, e.g. 'Austin, TX'")
    categories: list[str] = Field(
        ...,
        description="Product categories to analyze, e.g. ['power tools', 'gardening']",
    )
    store_url: str | None = Field(
        None,
        description="Optional URL of the store's website to scrape current product catalog",
    )
    lookback_days: int = Field(
        90,
        ge=7,
        le=365,
        description="Days of sales history to include in the analysis",
    )
    extra_context: str | None = Field(
        None,
        description="Optional free-text context the owner wants the agent to consider",
    )


# ---------------------------------------------------------------------------
# Individual signal shapes (returned by tools, consumed by agent)
# ---------------------------------------------------------------------------


class TrendDirection(str, Enum):
    trending = "trending"
    stable = "stable"
    fading = "fading"


class GoogleTrendPoint(BaseModel):
    date: str
    interest: int = Field(..., ge=0, le=100, description="0-100 relative interest")


class GoogleTrendResult(BaseModel):
    keyword: str
    geo: str
    timeframe: str
    direction: TrendDirection
    peak_interest: int
    current_interest: int
    change_pct: float = Field(..., description="% change over timeframe")
    data_points: list[GoogleTrendPoint]


class RedditSignal(BaseModel):
    subreddit: str
    post_title: str
    score: int
    num_comments: int
    url: str
    created_utc: str


class RedditTrendResult(BaseModel):
    keyword: str
    top_posts: list[RedditSignal]
    mention_count: int
    sentiment_summary: str


class LocalEvent(BaseModel):
    name: str
    date: str
    venue: str | None = None
    category: str | None = None
    relevance_note: str | None = None


class LocalEventsResult(BaseModel):
    location: str
    events: list[LocalEvent]


class SalesRecord(BaseModel):
    sku: str
    product_name: str
    category: str
    quantity_sold: int
    revenue: float
    period_start: str
    period_end: str


class SeasonalityResult(BaseModel):
    category: str
    peak_months: list[int] = Field(..., description="1-12")
    trough_months: list[int] = Field(..., description="1-12")
    notes: str


class SalesHistoryResult(BaseModel):
    category: str
    period_start: str
    period_end: str
    total_units: int
    total_revenue: float
    top_skus: list[SalesRecord]
    seasonality: SeasonalityResult | None = None


class StoreInventoryResult(BaseModel):
    store_url: str
    pages_scraped: list[str]
    raw_text: str
    success: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class SkuRecommendation(BaseModel):
    action: str = Field(..., description="'stock', 'increase', 'reduce', or 'drop'")
    sku: str | None = Field(None, description="Existing SKU from sales history, if known")
    product_name: str
    reason: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    is_existing_product: bool = Field(
        False,
        description="True if this product is already in the store's catalog; False if it's a new product to source",
    )
    recommendation_id: str | None = Field(
        None,
        description="Unique ID for tracking owner feedback on this recommendation",
    )
    image_url: str | None = Field(None, description="Product image URL from Google Custom Search")


class CategoryAnalysis(BaseModel):
    name: str
    status: TrendDirection
    confidence: float = Field(..., ge=0.0, le=1.0)
    signals: list[str] = Field(
        ..., description="Human-readable signal descriptions driving the verdict"
    )
    recommendations: list[SkuRecommendation]
    end_of_trend_warning: bool = Field(
        False, description="True when the category shows late-cycle fading signals"
    )


class TrendReport(BaseModel):
    """Full output from the trend analyst agent."""

    analysis_date: str = Field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d")
    )
    business_name: str
    location: str
    categories: list[CategoryAnalysis]
    executive_summary: str
    raw_agent_reasoning: str | None = Field(
        None, description="Agent's chain-of-thought, useful for debugging"
    )
