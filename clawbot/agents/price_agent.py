"""
PriceScout Agent — Claude Sonnet with a tool-use loop.

The agent receives a business name and location, scans all active watch items,
compares market prices to each item's baseline, records findings, triggers alerts
when savings exceed the configured threshold, then emits a final PriceReport.
"""

from __future__ import annotations

from clawbot.agents.limits import agent_steps

import json
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

from clawbot.schemas.price import (
    Alert,
    Baseline,
    BestOption,
    Finding,
    PriceReport,
    ScanRequest,
)
from clawbot.tools.db_price import (
    append_alert,
    get_watch_item,
    init_db,
    list_alerts,
    list_watch_items,
    touch_watch_item,
    upsert_finding,
)
from clawbot.tools.scrape_page import scrape_page
from clawbot.tools.web_search import search_market_prices


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tool definitions (sent to Claude so it knows what it can call)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_watchlist",
        "description": (
            "Return all active watch items from the database. "
            "Call this first to know which products/suppliers to scan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "description": "If true, return only active watch items (default true).",
                    "default": True,
                }
            },
            "required": [],
        },
    },
    {
        "name": "search_market_prices",
        "description": (
            "Search the market for current prices for a product. "
            "Returns up to 5 supplier results with prices, URLs, and confidence levels. "
            "Call this for every active watch item to find the best available price."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Product search term, e.g. 'corrugated boxes 12x12x12'",
                },
                "region": {
                    "type": "string",
                    "description": "City/region, e.g. 'Austin, TX'",
                },
            },
            "required": ["query", "region"],
        },
    },
    {
        "name": "record_finding",
        "description": (
            "Record the price discovery result for one specific product. "
            "Call this once per product after BOTH stages are complete: "
            "(1) scraped the source site for the product's listed price, "
            "(2) searched the market for competing prices. "
            "Compares the best market price to the watch item baseline; "
            "triggers an alert if savings >= threshold_pct."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "watch_id": {
                    "type": "string",
                    "description": "ID of the watch item this product belongs to",
                },
                "product_name": {
                    "type": "string",
                    "description": "Specific product name from the source site, e.g. 'Pebble Bear Plush 12in'",
                },
                "scraped_price": {
                    "type": "number",
                    "description": "Price shown on the source/competitor site",
                },
                "supplier": {
                    "type": "string",
                    "description": "Vendor offering the best market price found via search",
                },
                "price": {
                    "type": "number",
                    "description": "Best market price found across all vendors",
                },
                "url": {
                    "type": "string",
                    "description": "URL to the best market listing (optional)",
                },
                "notes": {
                    "type": "string",
                    "description": "One-line comparison: source site price vs best market price",
                },
                "confidence": {
                    "type": "string",
                    "description": "'high', 'medium', or 'low'",
                    "default": "medium",
                },
                "candidates": {
                    "type": "array",
                    "description": "All vendor candidates from market search (list of objects with supplier, price, url)",
                    "items": {"type": "object"},
                },
            },
            "required": ["watch_id", "product_name", "scraped_price", "supplier", "price"],
        },
    },
    {
        "name": "scrape_page",
        "description": (
            "Fetch a product or catalog page from a URL and return its cleaned text. "
            "Use this when a watch item's query starts with 'http'. "
            "Returns the full page text — extract individual product names and prices from it, "
            "then for EACH product call search_market_prices, then call record_finding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch, e.g. 'https://pebblestoys.com/products/bear'",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_alerts",
        "description": (
            "Return the current list of alerts. "
            "Use this at the end to summarize how many alerts were triggered."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'new', 'acknowledged', or omit for all",
                }
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------


def _dispatch_tool(name: str, inputs: dict[str, Any]) -> str:
    """Call the appropriate Python tool and return a JSON-serialised result."""
    if name == "get_watchlist":
        active_only = inputs.get("active_only", True)
        items = list_watch_items(active_only=active_only)
        return json.dumps([item.model_dump() for item in items])

    if name == "scrape_page":
        result = scrape_page(url=inputs["url"])
        return result.model_dump_json()

    if name == "search_market_prices":
        result = search_market_prices(
            query=inputs["query"],
            region=inputs["region"],
        )
        return result.model_dump_json()

    if name == "record_finding":
        req = ScanRequest(
            watch_id=inputs["watch_id"],
            product_name=inputs["product_name"],
            scraped_price=float(inputs["scraped_price"]),
            supplier=inputs["supplier"],
            price=float(inputs["price"]),
            url=inputs.get("url"),
            notes=inputs.get("notes"),
            confidence=inputs.get("confidence", "medium"),
            candidates=inputs.get("candidates", []),
        )

        try:
            watch_item = get_watch_item(req.watch_id)
        except KeyError as exc:
            return json.dumps({"error": str(exc)})

        scanned_at = _utc_now()
        baseline_price = watch_item.baseline.price if watch_item.baseline else 0.0
        delta_pct = (
            round(((baseline_price - req.price) / baseline_price) * 100, 2)
            if baseline_price
            else 0.0
        )

        # ID is per-product so multiple products from one site each get their own row
        product_slug = req.product_name.lower().replace(" ", "-")[:40]
        finding_id = f"finding-{req.watch_id}-{product_slug}-{scanned_at.replace(':', '').replace('-', '')}"
        finding = Finding(
            id=finding_id,
            watch_id=req.watch_id,
            product_name=req.product_name,
            label=watch_item.label,
            scanned_at=scanned_at,
            scraped_price=req.scraped_price,
            baseline=watch_item.baseline,
            best_option=BestOption(
                supplier=req.supplier,
                price=req.price,
                currency=watch_item.baseline.currency if watch_item.baseline else "USD",
                unit=watch_item.baseline.unit if watch_item.baseline else None,
                url=req.url,
            ),
            candidates=req.candidates,
            confidence=req.confidence,
            notes=req.notes,
            delta_pct=delta_pct,
        )
        upsert_finding(finding)
        touch_watch_item(req.watch_id, last_scan_at=scanned_at)

        alert = None
        threshold = watch_item.threshold_pct
        if delta_pct >= threshold:
            alert_id = f"alert-{req.watch_id}-{scanned_at.replace(':', '').replace('-', '')}"
            currency = watch_item.baseline.currency if watch_item.baseline else "USD"
            unit = watch_item.baseline.unit if watch_item.baseline else ""
            alert = Alert(
                id=alert_id,
                watch_id=req.watch_id,
                status="new",
                created_at=scanned_at,
                summary=(
                    f"{watch_item.label}: {delta_pct:.1f}% below baseline "
                    f"with {req.supplier} at {req.price} {currency}/{unit}."
                ),
                baseline=watch_item.baseline,
                best_option=finding.best_option,
                delta_pct=delta_pct,
                notes=req.notes,
            )
            append_alert(alert)
            touch_watch_item(req.watch_id, last_alert_at=scanned_at)

        return json.dumps(
            {
                "finding": finding.model_dump(),
                "alert": alert.model_dump() if alert else None,
                "delta_pct": delta_pct,
                "threshold_pct": threshold,
                "alert_triggered": alert is not None,
            }
        )

    if name == "get_alerts":
        status = inputs.get("status")
        alerts = list_alerts(status=status)
        return json.dumps([a.model_dump() for a in alerts])

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a PriceScout Agent for small business owners.
Your job is to discover real market prices for products and compare them to the owner's baselines.

Workflow (follow this exactly):
1. Call get_watchlist to retrieve all active watch items.

2. For EACH active watch item, run price discovery:

   STAGE 1 — Initial search:
   - If the item's query starts with "http": call scrape_page(url=query) directly.
     Extract every product name and price from the page text.
   - Otherwise: call search_market_prices(query=item.query, region=<location>).
     This returns supplier candidates with names, prices, and URLs.

   STAGE 2 — Deep scrape (ALWAYS do this):
   - After search_market_prices, pick the URL from the result with the lowest price.
   - Call scrape_page(url=that_url) to verify the price directly on the site.
   - This always runs — it is how we confirm and refine the price found in Stage 1.

   STAGE 3 — Find the best price:
   - Combine prices from Stage 1 search results and the Stage 2 scrape.
   - Identify the lowest confirmed price and best supplier.

   STAGE 4 — Record the finding:
   - Call record_finding with:
       watch_id: the watch item id
       product_name: the product name
       scraped_price: the price from the source (Stage 1)
       supplier: the vendor with the lowest price found
       price: the lowest price found
       notes: one line summary e.g. "Current: $29.99 | Best found: $18.50 at WholesaleToys (38% cheaper)"
       candidates: all vendor candidates found

3. After all watch items are recorded, call get_alerts(status="new").

4. Emit a final JSON report:
{
  "business_name": "<business name>",
  "location": "<location>",
  "scan_date": "<YYYY-MM-DD>",
  "items_scanned": <total products recorded>,
  "alerts_triggered": <integer>,
  "executive_summary": "<2-3 sentence summary: which products have the biggest price gaps, what action to take>"
}

Rules:
- Always call scrape_page in Stage 2 — never skip it.
- Keep language plain — the audience is a small business owner, not a data analyst.
- Output ONLY the JSON block — no extra commentary outside the JSON."""


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------


def run_price_agent(business_name: str, location: str) -> PriceReport:
    """
    Run the full PriceScout agent loop for the given business and location.

    Uses Claude Sonnet with tool use. Iterates until the model stops calling tools
    and emits a final JSON report, which is parsed into a PriceReport.

    Args:
        business_name: Name of the small business (for the report header).
        location: City/region string, e.g. 'Austin, TX'.

    Returns:
        PriceReport — structured, ready to serve via the API.
    """
    init_db()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = (
        f"Business: {business_name}\n"
        f"Location: {location}\n"
        f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        "Please scan all active watch items and produce a price report."
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    raw_reasoning = ""

    # Agentic loop — keep going until the model stops using tools
    for _step in agent_steps():  # bounded: max tool steps + total timeout
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
            # Model finished without tool calls mid-loop — safe exit
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

    json_str = final_text.strip()
    if "```" in json_str:
        json_str = json_str.split("```")[1]
        if json_str.startswith("json"):
            json_str = json_str[4:]
    json_str = json_str.strip()

    raw_data = json.loads(json_str)

    # ---------------------------------------------------------------------------
    # Hydrate findings and alerts from the DB for the full report
    # ---------------------------------------------------------------------------
    from clawbot.tools.db_price import list_findings

    all_findings = list_findings()
    all_alerts = list_alerts(status="new")

    return PriceReport(
        business_name=raw_data.get("business_name", business_name),
        location=raw_data.get("location", location),
        scan_date=raw_data.get("scan_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        items_scanned=raw_data.get("items_scanned", len(all_findings)),
        alerts_triggered=raw_data.get("alerts_triggered", len(all_alerts)),
        findings=all_findings,
        alerts=all_alerts,
        executive_summary=raw_data.get("executive_summary", ""),
        raw_agent_reasoning=raw_reasoning.strip() or None,
    )
