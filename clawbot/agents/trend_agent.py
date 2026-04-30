"""
Trend Analyst Agent — Claude Sonnet with a tool-use loop.

The agent receives a TrendRequest, calls its tools to gather signals,
then synthesizes a structured TrendReport.
"""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic

from clawbot.schemas.trend import (
    CategoryAnalysis,
    SkuRecommendation,
    TrendDirection,
    TrendReport,
    TrendRequest,
)
from clawbot.agents.recommendation_memory import get_preference_context, record_recommendations
from clawbot.tools.google_trends import get_google_trends
from clawbot.tools.local_events import get_local_events
from clawbot.tools.product_images import get_product_image
from clawbot.tools.reddit_trends import get_reddit_trends
from clawbot.tools.sales_history import get_sales_history
from clawbot.tools.store_inventory import scrape_store_inventory

# ---------------------------------------------------------------------------
# Tool definitions (sent to Claude so it knows what it can call)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "scrape_store_inventory",
        "description": (
            "Fetch the store's website and extract its current product catalog. "
            "Call this FIRST (before any trend tools) when a store_url is provided. "
            "Parse the returned text to identify what products and categories the store currently sells. "
            "This tells you which recommendations are for existing products vs new products to source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "store_url": {
                    "type": "string",
                    "description": "The store's website URL, e.g. 'https://pebblestoys.com'",
                },
            },
            "required": ["store_url"],
        },
    },
    {
        "name": "get_google_trends",
        "description": (
            "Fetch Google Trends interest-over-time data for a keyword. "
            "Returns a direction label (trending/stable/fading), change percentage, "
            "peak interest, and raw weekly data points. Use this first for every category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search term, e.g. 'power tools' or 'cordless drill'",
                },
                "location": {
                    "type": "string",
                    "description": "City/region, e.g. 'Austin, TX'",
                },
                "lookback_days": {
                    "type": "integer",
                    "description": "Days of history: 7, 30, 90, 180, or 365",
                    "default": 90,
                },
            },
            "required": ["keyword", "location"],
        },
    },
    {
        "name": "get_reddit_trends",
        "description": (
            "Search Reddit for recent posts mentioning a keyword in relevant subreddits. "
            "Useful as a social-signal cross-check. Returns top posts and a sentiment summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Product or category term to search for",
                },
                "category": {
                    "type": "string",
                    "description": "Product category hint for subreddit selection",
                    "default": "default",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_local_events",
        "description": (
            "Fetch upcoming local events (expos, fairs, festivals) near the business "
            "location that could drive demand for a product category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City/region, e.g. 'Austin, TX'",
                },
                "category": {
                    "type": "string",
                    "description": "Product category to match events against",
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Days into the future to search (default 60)",
                    "default": 60,
                },
            },
            "required": ["location", "category"],
        },
    },
    {
        "name": "get_sales_history",
        "description": (
            "Query the owner's historical sales database for a product category. "
            "Returns total units sold, revenue, top SKUs, and seasonality data. "
            "Always call this to ground trend signals in actual store performance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Product category (case-insensitive)",
                },
                "lookback_days": {
                    "type": "integer",
                    "description": "Days of history to include (default 90)",
                    "default": 90,
                },
            },
            "required": ["category"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def _dispatch_tool(name: str, inputs: dict[str, Any]) -> str:
    """Call the appropriate Python tool and return JSON-serialized result."""
    if name == "scrape_store_inventory":
        result = scrape_store_inventory(**inputs)
    elif name == "get_google_trends":
        result = get_google_trends(**inputs)
    elif name == "get_reddit_trends":
        result = get_reddit_trends(**inputs)
    elif name == "get_local_events":
        result = get_local_events(**inputs)
    elif name == "get_sales_history":
        result = get_sales_history(**inputs)
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})

    return result.model_dump_json()


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Trend Analyst Agent for small business owners (mom-and-pop shops).
Your job is to analyze product category trends and produce actionable inventory recommendations.

STEP 0 — If a store_url is provided, call scrape_store_inventory FIRST.
Parse the returned text carefully to build a list of products the store currently sells.
You will use this catalog throughout the analysis to distinguish existing products from new ones.

For EACH category in the request, you MUST:
1. Call get_google_trends to get search-interest direction.
2. Call get_reddit_trends to get social buzz signals.
3. Call get_local_events to check for nearby demand-driving events.
4. Call get_sales_history to ground your analysis in actual store sales.

After gathering all signals, produce a final JSON report. The JSON must match this exact shape:

{
  "categories": [
    {
      "name": "<category name>",
      "status": "trending" | "stable" | "fading",
      "confidence": <0.0-1.0>,
      "signals": ["<signal 1>", "<signal 2>", ...],
      "end_of_trend_warning": true | false,
      "recommendations": [
        {
          "action": "stock" | "increase" | "reduce" | "drop",
          "sku": "<existing SKU from sales history, or null>",
          "product_name": "<exact product name — use real names from the store catalog or scraped web data>",
          "reason": "<one-sentence rationale>",
          "confidence": <0.0-1.0>,
          "is_existing_product": true | false
        }
      ]
    }
  ],
  "executive_summary": "<2-3 sentence plain-English summary for the business owner>"
}

Rules:
- status=trending means Google Trends +10% or more AND at least one other positive signal.
- status=fading means Google Trends -10% or more AND declining sales history.
- end_of_trend_warning=true when a category was recently trending but signals now show reversal.
- is_existing_product=true when the product appears in the scraped store catalog or sales history.
- is_existing_product=false for new products the store should consider sourcing.
- For existing products: action is "increase", "reduce", or "drop" based on trend signals.
- For new products: action is always "stock". Use real, specific product names from trend data.
- Keep language plain — the audience is a small business owner, not a data analyst.
- Output ONLY the JSON block — no extra commentary outside the JSON."""


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------

def run_trend_agent(request: TrendRequest) -> TrendReport:
    """
    Run the full trend analyst agent loop for the given request.

    Uses Claude Sonnet with tool use. Iterates until the model stops calling tools
    and emits a final JSON report, which is parsed into a TrendReport.

    Args:
        request: Describes the business, location, and categories to analyze.

    Returns:
        TrendReport — structured, ready to serve via the API.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = (
        f"Business: {request.business_name}\n"
        f"Location: {request.location}\n"
        f"Categories to analyze: {', '.join(request.categories)}\n"
        f"Lookback period: {request.lookback_days} days\n"
    )
    if request.store_url:
        user_message += f"Store website: {request.store_url}\n"
    if request.extra_context:
        user_message += f"Owner notes: {request.extra_context}\n"

    preference_context = get_preference_context()
    if preference_context:
        user_message += f"\nOwner preference history (learned from past interactions):\n{preference_context}\n"

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    raw_reasoning = ""

    # Agentic loop — keep going until the model stops using tools
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Collect any text the model produced this turn
        for block in response.content:
            if hasattr(block, "text"):
                raw_reasoning += block.text + "\n"

        # If no tool calls, we're done — extract the JSON report
        if response.stop_reason == "end_turn":
            break

        # Process tool calls and feed results back
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result_json = _dispatch_tool(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_json,
                }
            )

        if not tool_results:
            # Model finished without tool calls mid-loop — shouldn't happen, but safe exit
            break

        # Append assistant turn + tool results
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # ---------------------------------------------------------------------------
    # Parse the final JSON from the last assistant message
    # ---------------------------------------------------------------------------
    final_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_text = block.text
            break

    # Extract JSON block (model might wrap it in a code fence)
    json_str = final_text.strip()
    if "```" in json_str:
        json_str = json_str.split("```")[1]
        if json_str.startswith("json"):
            json_str = json_str[4:]
    json_str = json_str.strip()

    raw_data = json.loads(json_str)

    # ---------------------------------------------------------------------------
    # Map raw JSON → Pydantic TrendReport
    # ---------------------------------------------------------------------------
    categories = []
    for cat in raw_data.get("categories", []):
        recs = [
            SkuRecommendation(
                action=r["action"],
                sku=r.get("sku"),
                product_name=r["product_name"],
                reason=r["reason"],
                confidence=float(r.get("confidence", 0.7)),
                is_existing_product=bool(r.get("is_existing_product", False)),
            )
            for r in cat.get("recommendations", [])
        ]
        categories.append(
            CategoryAnalysis(
                name=cat["name"],
                status=TrendDirection(cat["status"]),
                confidence=float(cat.get("confidence", 0.7)),
                signals=cat.get("signals", []),
                end_of_trend_warning=cat.get("end_of_trend_warning", False),
                recommendations=recs,
            )
        )

    report = TrendReport(
        business_name=request.business_name,
        location=request.location,
        categories=categories,
        executive_summary=raw_data.get("executive_summary", ""),
        raw_agent_reasoning=raw_reasoning.strip() or None,
    )

    # ---------------------------------------------------------------------------
    # Save recommendations to memory + enrich with images (post-processing)
    # ---------------------------------------------------------------------------
    for cat in report.categories:
        rec_dicts = [{"product_name": r.product_name, "action": r.action} for r in cat.recommendations]
        ids = record_recommendations(cat.name, rec_dicts, report.analysis_date)
        for rec, rec_id in zip(cat.recommendations, ids):
            rec.recommendation_id = rec_id
            rec.image_url = get_product_image(rec.product_name)

    return report
