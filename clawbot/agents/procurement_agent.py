"""
Procurement Agent — Claude Sonnet with a tool-use loop.

The agent receives a business name and location, scans all active procurement
items, searches for wholesale suppliers, records quotes, then emits a final
ProcurementReport with the best sourcing recommendation per item.
"""

from __future__ import annotations

from clawbot.agents.limits import agent_steps

import json
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

import httpx

from clawbot.schemas.procurement import (
    OrderLineItem,
    ProcurementItem,
    ProcurementOrder,
    ProcurementRecommendation,
    ProcurementReport,
    QuoteRequest,
    SupplierQuote,
)
from clawbot.tools.db_procurement import (
    find_catalog_entry,
    get_item,
    init_db,
    insert_quote,
    list_items,
    list_quotes,
    touch_item,
    upsert_item,
)
from clawbot.tools.order import send_order_imsg
from clawbot.tools.supplier_search import search_suppliers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_procurement_list",
        "description": (
            "Return all active procurement items — the products the business wants to source. "
            "Call this first to know what needs to be procured."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "description": "If true, return only active items (default true).",
                    "default": True,
                }
            },
            "required": [],
        },
    },
    {
        "name": "search_suppliers",
        "description": (
            "Search the market for wholesale suppliers for a product. "
            "Returns up to 5 supplier results with per-unit prices, MOQs, and URLs. "
            "Call this for every active procurement item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Product search term, e.g. 'wooden pull-along toy train wholesale'",
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
        "name": "record_quote",
        "description": (
            "Record a supplier quote for a procurement item. "
            "Call this once per supplier found, after searching for suppliers. "
            "Compares the quote price to the item's budget_per_unit if set."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "ID of the procurement item this quote belongs to",
                },
                "supplier": {
                    "type": "string",
                    "description": "Name of the wholesale supplier",
                },
                "price_per_unit": {
                    "type": "number",
                    "description": "Quoted price per unit",
                },
                "moq": {
                    "type": "integer",
                    "description": "Minimum order quantity (if known)",
                },
                "url": {
                    "type": "string",
                    "description": "URL to the supplier listing",
                },
                "confidence": {
                    "type": "string",
                    "description": "'high', 'medium', or 'low'",
                    "default": "medium",
                },
            },
            "required": ["item_id", "supplier", "price_per_unit"],
        },
    },
    {
        "name": "get_quotes",
        "description": (
            "Return all recorded quotes, optionally filtered by item_id. "
            "Use this at the end to confirm what was found and build recommendations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "Filter quotes for a specific procurement item",
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
    if name == "get_procurement_list":
        active_only = inputs.get("active_only", True)
        items = list_items(active_only=active_only, item_ids=_ITEM_ID_FILTER)
        return json.dumps([item.model_dump() for item in items])

    if name == "search_suppliers":
        result = search_suppliers(
            query=inputs["query"],
            region=inputs["region"],
        )
        return result.model_dump_json()

    if name == "record_quote":
        req = QuoteRequest(
            item_id=inputs["item_id"],
            supplier=inputs["supplier"],
            price_per_unit=float(inputs["price_per_unit"]),
            moq=inputs.get("moq"),
            url=inputs.get("url"),
            confidence=inputs.get("confidence", "medium"),
        )

        try:
            item = get_item(req.item_id)
        except KeyError as exc:
            return json.dumps({"error": str(exc)})

        found_at = _utc_now()
        supplier_slug = req.supplier.lower().replace(" ", "-")[:30]
        quote_id = f"quote-{req.item_id}-{supplier_slug}-{found_at.replace(':', '').replace('-', '')}"

        quote = SupplierQuote(
            id=quote_id,
            item_id=req.item_id,
            supplier=req.supplier,
            price_per_unit=req.price_per_unit,
            currency=item.currency,
            moq=req.moq,
            url=req.url,
            confidence=req.confidence,
            found_at=found_at,
        )
        insert_quote(quote)
        touch_item(req.item_id, last_sourced_at=found_at)

        savings_pct = None
        if item.budget_per_unit:
            savings_pct = round(
                ((item.budget_per_unit - req.price_per_unit) / item.budget_per_unit) * 100, 2
            )

        return json.dumps({
            "quote": quote.model_dump(),
            "budget_per_unit": item.budget_per_unit,
            "savings_vs_budget_pct": savings_pct,
        })

    if name == "get_quotes":
        item_id = inputs.get("item_id")
        quotes = list_quotes(item_id=item_id)
        return json.dumps([q.model_dump() for q in quotes])

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a Procurement Agent for small business owners.
Your job is to find the best wholesale suppliers for products the business needs to source.

Workflow (follow this exactly):
1. Call get_procurement_list to retrieve all active procurement items.

2. For EACH active procurement item:
   - Call search_suppliers(query=item.name + " wholesale", region=<location>)
     to find up to 5 wholesale/bulk suppliers with per-unit pricing.
   - For EACH supplier result returned, call record_quote with:
       item_id: the procurement item id
       supplier: supplier name
       price_per_unit: quoted price
       moq: minimum order quantity (if available)
       url: listing URL
       confidence: from the search result

3. After all items are sourced, call get_quotes() to review all recorded quotes.

4. Emit a final JSON report:
{
  "business_name": "<business name>",
  "location": "<location>",
  "scan_date": "<YYYY-MM-DD>",
  "items_sourced": <total items processed>,
  "recommendations": [
    {
      "item_id": "<id>",
      "product_name": "<name>",
      "recommended_supplier": "<best supplier name>",
      "price_per_unit": <lowest price found>,
      "currency": "USD",
      "moq": <minimum order quantity or null>,
      "url": "<supplier URL>",
      "savings_vs_budget_pct": <pct savings vs budget, or null if no budget set>,
      "confidence": "<high/medium/low>",
      "notes": "<one line: why this supplier is recommended>",
      "all_quotes": [<list of all supplier quote objects for this item>]
    }
  ],
  "executive_summary": "<2-3 sentence summary: best sourcing opportunities, any items over budget, recommended next steps>"
}

Rules:
- Always record at least one quote per item before moving to the next.
- Recommend the supplier with the lowest price_per_unit that meets the business's quantity_needed.
- If budget_per_unit is set, flag items where the best quote exceeds it.
- Keep language plain — the audience is a small business owner, not a procurement analyst.
- Output ONLY the JSON block — no extra commentary outside the JSON."""


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------


_ITEM_ID_FILTER: list[str] | None = None


def run_procurement_agent(
    business_name: str,
    location: str,
    item_ids: list[str] | None = None,
) -> ProcurementReport:
    """
    Run the full Procurement Agent loop for the given business and location.

    Uses Claude Sonnet with tool use. Iterates until the model stops calling
    tools and emits a final JSON report, which is parsed into a ProcurementReport.
    """
    global _ITEM_ID_FILTER
    _ITEM_ID_FILTER = item_ids

    init_db()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = (
        f"Business: {business_name}\n"
        f"Location: {location}\n"
        f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        "Please source all active procurement items and produce a report."
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    raw_reasoning = ""

    for _step in agent_steps():  # bounded: max tool steps + total timeout
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        for block in response.content:
            if hasattr(block, "text"):
                raw_reasoning += block.text + "\n"

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result_json = _dispatch_tool(block.name, block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_json,
            })

        if not tool_results:
            break

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

    recommendations = [
        ProcurementRecommendation(**r) for r in raw_data.get("recommendations", [])
    ]

    return ProcurementReport(
        business_name=raw_data.get("business_name", business_name),
        location=raw_data.get("location", location),
        scan_date=raw_data.get("scan_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        items_sourced=raw_data.get("items_sourced", len(recommendations)),
        recommendations=recommendations,
        executive_summary=raw_data.get("executive_summary", ""),
        raw_agent_reasoning=raw_reasoning.strip() or None,
    )


# ---------------------------------------------------------------------------
# Inventory ingestion
# ---------------------------------------------------------------------------


def ingest_low_stock_items(inventory_url: str) -> list[ProcurementItem]:
    """
    Fetch low-stock items from the Inventory Agent API and upsert them as
    active procurement items.

    Each item's quantity_needed is set to enough units to bring stock back
    up to twice the reorder point (a common "order-to-safety-stock" heuristic).
    """
    try:
        resp = httpx.get(f"{inventory_url.rstrip('/')}/low-stock", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    ingested: list[ProcurementItem] = []
    for alert in data.get("items", []):
        qty_to_order = max(alert["reorder_point"] * 2 - alert["quantity"], 1)
        item = ProcurementItem(
            id=f"inv-{alert['item_id']}",
            name=alert["name"],
            quantity_needed=qty_to_order,
            active=True,
            notes=f"Auto-ingested: {alert['units_below_threshold']} units below reorder point",
        )
        upsert_item(item)
        ingested.append(item)

    return ingested


# ---------------------------------------------------------------------------
# Order form generation
# ---------------------------------------------------------------------------


def generate_order_form(
    report: ProcurementReport, items: list[ProcurementItem]
) -> ProcurementOrder:
    """
    Build a ProcurementOrder from a ProcurementReport.

    Matches each recommendation with its procurement item to get quantity_needed,
    then computes per-line and total costs.
    """
    items_by_id = {item.id: item for item in items}

    line_items: list[OrderLineItem] = []
    for rec in report.recommendations:
        item = items_by_id.get(rec.item_id)
        quantity = item.quantity_needed if item else 1
        total = round(rec.price_per_unit * quantity, 2)

        # Margin analysis: look up the business's supplier catalog for this product
        catalog = find_catalog_entry(rec.product_name)
        known_cost = catalog.cost_per_unit if catalog else None
        sell_price = catalog.typical_sell_price if catalog else None
        margin_pct: float | None = None
        margin_viable: bool | None = None
        if sell_price and sell_price > 0:
            margin_pct = round((sell_price - rec.price_per_unit) / sell_price * 100, 1)
            target = catalog.target_margin_pct if catalog else 30.0
            margin_viable = margin_pct >= target

        line_items.append(
            OrderLineItem(
                item_id=rec.item_id,
                product_name=rec.product_name,
                quantity=quantity,
                supplier=rec.recommended_supplier,
                price_per_unit=rec.price_per_unit,
                total_cost=total,
                currency=rec.currency,
                moq=rec.moq,
                url=rec.url,
                confidence=rec.confidence,
                known_cost_per_unit=known_cost,
                typical_sell_price=sell_price,
                margin_pct=margin_pct,
                margin_viable=margin_viable,
            )
        )

    total_cost = round(sum(li.total_cost for li in line_items), 2)
    order_id = f"order-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    return ProcurementOrder(
        order_id=order_id,
        business_name=report.business_name,
        location=report.location,
        created_at=_utc_now(),
        line_items=line_items,
        total_cost=total_cost,
        currency="USD",
    )


# ---------------------------------------------------------------------------
# Full procure-and-confirm orchestrator
# ---------------------------------------------------------------------------


def run_full_procurement(
    business_name: str,
    location: str,
    recipient: str,
    inventory_url: str | None = None,
    send_confirmation: bool = True,
    item_ids: list[str] | None = None,
) -> ProcurementOrder:
    """
    End-to-end procurement flow:

    1. (Optional) Pull low-stock items from the Inventory Agent and add them
       as active procurement items.
    2. Run the Procurement Agent to search for suppliers and build a report.
    3. Generate a structured ProcurementOrder (order form) from the report.
    4. Send the order form to the owner via iMessage for confirmation.
    5. Return the ProcurementOrder with delivery status.
    """
    init_db()

    # Step 1 — ingest low-stock items from inventory if a URL was provided
    if inventory_url:
        ingest_low_stock_items(inventory_url)

    # Step 2 — run sourcing agent (optionally scoped to specific items)
    report = run_procurement_agent(
        business_name=business_name, location=location, item_ids=item_ids
    )

    # Step 3 — build order form (fetch only the relevant items for quantity_needed)
    all_items = list_items(item_ids=item_ids) if item_ids else list_items(active_only=True)
    order = generate_order_form(report, all_items)

    # Step 4 — send iMessage confirmation (skip if orchestrator will compose its own)
    if send_confirmation:
        sent, message_text = send_order_imsg(order, recipient)
        order.confirmation_sent = sent
        order.confirmation_recipient = recipient
        order.imsg_text = message_text
        if not sent:
            order.error = (
                "iMessage delivery failed. Ensure the running process has Automation permission "
                "to control Messages.app (System Settings → Privacy & Security → Automation)."
            )

    return order
