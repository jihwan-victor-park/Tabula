"""
Inventory Agent — Claude Sonnet with a tool-use loop.

The agent scans the inventory database, identifies low-stock items,
looks up product info by barcode, and produces an InventoryReport
with actionable restock recommendations.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

from clawbot.schemas.inventory import (
    InventoryItem,
    InventoryReport,
    LowStockAlert,
)
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
        "name": "get_inventory",
        "description": (
            "Return all items in the inventory database. "
            "Optionally filter by category or return only low-stock items. "
            "Call this first to understand current stock levels."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by product category, e.g. 'LEGO', 'Puzzles'",
                },
                "low_stock_only": {
                    "type": "boolean",
                    "description": "If true, only return items at or below their reorder point",
                    "default": False,
                },
            },
            "required": [],
        },
    },
    {
        "name": "lookup_barcode",
        "description": (
            "Look up product info for a barcode using UPC Item DB. "
            "Returns product name, brand, category, description, image URL, and market price. "
            "Use this when adding a new product or when product details are missing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "barcode": {
                    "type": "string",
                    "description": "UPC or EAN barcode, e.g. '0673419376396'",
                }
            },
            "required": ["barcode"],
        },
    },
    {
        "name": "scan_item",
        "description": (
            "Scan a barcode to add or update an item in inventory. "
            "Looks up product info automatically, then adds the item if new "
            "or adjusts stock if it already exists. "
            "Use reason='restock' when adding stock, 'sale' when removing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "barcode": {
                    "type": "string",
                    "description": "UPC or EAN barcode",
                },
                "quantity_change": {
                    "type": "integer",
                    "description": "How many units to add (positive) or remove (negative)",
                },
                "reason": {
                    "type": "string",
                    "description": "'restock', 'sale', 'adjustment', or 'scan'",
                    "default": "scan",
                },
                "sell_price": {
                    "type": "number",
                    "description": "Your selling price for this item (optional)",
                },
                "reorder_point": {
                    "type": "integer",
                    "description": "Alert threshold — restock when quantity falls below this (default 5)",
                    "default": 5,
                },
            },
            "required": ["barcode", "quantity_change"],
        },
    },
    {
        "name": "get_low_stock",
        "description": (
            "Return all items where current quantity is at or below their reorder point. "
            "Use this to identify what needs restocking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_transactions",
        "description": (
            "Return recent stock transactions (restocks, sales, adjustments). "
            "Optionally filter by item_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "Barcode/ID to filter transactions for one item",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max transactions to return (default 20)",
                    "default": 20,
                },
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------


def _dispatch_tool(name: str, inputs: dict[str, Any]) -> str:
    if name == "get_inventory":
        items = list_items(
            category=inputs.get("category"),
            low_stock_only=inputs.get("low_stock_only", False),
        )
        return json.dumps([i.model_dump() for i in items])

    if name == "lookup_barcode":
        result = lookup_barcode(inputs["barcode"])
        return result.model_dump_json()

    if name == "scan_item":
        barcode = inputs["barcode"]
        quantity_change = int(inputs["quantity_change"])
        reason = inputs.get("reason", "scan")

        # Try to get existing item, or look up and create it
        try:
            item = get_item(barcode)
        except KeyError:
            # New item — look up product info
            barcode_data = lookup_barcode(barcode)
            item = InventoryItem(
                id=barcode,
                name=barcode_data.name,
                brand=barcode_data.brand,
                category=barcode_data.category,
                description=barcode_data.description,
                image_url=barcode_data.image_url,
                quantity=0,
                reorder_point=inputs.get("reorder_point", 5),
                sell_price=inputs.get("sell_price"),
                last_updated=_utc_now(),
            )
            upsert_item(item)

        updated = adjust_stock(
            item_id=barcode,
            quantity_change=quantity_change,
            reason=reason,
        )
        low_stock = updated.quantity <= updated.reorder_point
        return json.dumps({
            "item": updated.model_dump(),
            "low_stock": low_stock,
            "message": (
                f"{'Added' if quantity_change > 0 else 'Removed'} {abs(quantity_change)} units of "
                f"'{updated.name}'. Now have {updated.quantity} in stock."
                + (" LOW STOCK — reorder soon." if low_stock else "")
            ),
        })

    if name == "get_low_stock":
        alerts = get_low_stock_items()
        if not alerts:
            return json.dumps({"message": "All items are adequately stocked.", "alerts": []})
        return json.dumps({"alerts": [a.model_dump() for a in alerts]})

    if name == "get_transactions":
        txs = list_transactions(
            item_id=inputs.get("item_id"),
            limit=inputs.get("limit", 20),
        )
        return json.dumps([t.model_dump() for t in txs])

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an Inventory Agent for a small toy store.
Your job is to review current stock levels and produce a clear inventory report.

Workflow:
1. Call get_inventory to see all current stock.
2. Call get_low_stock to identify items that need restocking.
3. Call get_transactions(limit=20) to see recent stock movements.
4. Emit a final JSON report:
{
  "scan_date": "<YYYY-MM-DD>",
  "total_items": <total items in inventory>,
  "low_stock_count": <number of low stock items>,
  "low_stock_items": [
    {
      "item_id": "<barcode>",
      "name": "<product name>",
      "brand": "<brand>",
      "category": "<category>",
      "quantity": <current qty>,
      "reorder_point": <threshold>,
      "units_below_threshold": <how many below>
    }
  ],
  "recently_updated": [<up to 5 recently changed items>],
  "executive_summary": "<2-3 sentences: what needs restocking urgently, any trends in stock movements>"
}

Rules:
- Flag anything at 0 quantity as urgent.
- Keep language plain — the audience is a toy store owner.
- Output ONLY the JSON block — no extra commentary."""


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------


def run_inventory_agent() -> InventoryReport:
    """
    Run the Inventory Agent to review stock levels and identify low-stock items.
    Returns a structured InventoryReport.
    """
    init_db()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = (
        f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        "Please review the inventory and produce a stock report."
    )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    raw_reasoning = ""

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
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

    # Parse final JSON
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

    low_stock = [LowStockAlert(**item) for item in raw_data.get("low_stock_items", [])]
    recently_updated = list_items()[:5]

    return InventoryReport(
        scan_date=raw_data.get("scan_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        total_items=raw_data.get("total_items", 0),
        low_stock_count=raw_data.get("low_stock_count", len(low_stock)),
        low_stock_items=low_stock,
        recently_updated=recently_updated,
        executive_summary=raw_data.get("executive_summary", ""),
    )


# ---------------------------------------------------------------------------
# Convenience: scan a single barcode (no Claude needed)
# ---------------------------------------------------------------------------


def scan_barcode(barcode: str, quantity_change: int, reason: str = "scan", sell_price: float | None = None, reorder_point: int = 5) -> dict[str, Any]:
    """
    Directly scan a barcode to add/remove stock without running the full agent.
    Used by the CLI for fast barcode scanning.
    """
    init_db()
    result = json.loads(_dispatch_tool("scan_item", {
        "barcode": barcode,
        "quantity_change": quantity_change,
        "reason": reason,
        "sell_price": sell_price,
        "reorder_point": reorder_point,
    }))
    return result
