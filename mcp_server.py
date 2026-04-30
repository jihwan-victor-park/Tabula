"""
YHack MCP Server — exposes PriceScout, Procurement, and iMessage digest
as MCP tools that Claude can call directly.

No HTTP servers required — tools call agent logic and SQLite directly.

Register in Claude Code:
    claude mcp add yhack -- python /Users/mmm/Downloads/yhack/mcp_server.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Ensure repo root is on the path
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

mcp = FastMCP("yhack")

IMSG_BINARY = "/Users/mmm/.local/bin/imsg"


# ---------------------------------------------------------------------------
# PriceScout tools
# ---------------------------------------------------------------------------


@mcp.tool()
def scan_prices(business_name: str, location: str) -> str:
    """
    Run the PriceScout agent to scan all active watch items for price opportunities.
    Searches the market, records findings, triggers alerts when savings exceed thresholds.
    Returns a full price report with executive summary and alerts.
    """
    from clawbot.agents.price_agent import run_price_agent

    report = run_price_agent(business_name=business_name, location=location)
    return json.dumps({
        "business_name": report.business_name,
        "scan_date": report.scan_date,
        "items_scanned": report.items_scanned,
        "alerts_triggered": report.alerts_triggered,
        "executive_summary": report.executive_summary,
        "alerts": [a.model_dump() for a in report.alerts],
        "findings": [f.model_dump() for f in report.findings[:10]],
    }, indent=2)


@mcp.tool()
def add_watch_item(
    id: str,
    label: str,
    query: str,
    baseline_price: float,
    baseline_supplier: str,
    threshold_pct: float = 5.0,
    mode: str = "competitor",
    region: str = "US",
) -> str:
    """
    Add or update a product in the PriceScout watchlist.
    Use mode='competitor' to track a competitor's catalog URL,
    or mode='vendor' to track a specific product search term.
    threshold_pct is the minimum savings % to trigger an alert.
    """
    from clawbot.schemas.price import Baseline, WatchItem
    from clawbot.tools.db_price import init_db, upsert_watch_item

    init_db()
    item = WatchItem(
        id=id,
        label=label,
        mode=mode,
        active=True,
        region=region,
        query=query,
        baseline=Baseline(
            supplier=baseline_supplier,
            price=baseline_price,
            currency="USD",
        ),
        threshold_pct=threshold_pct,
    )
    upsert_watch_item(item)
    return f"Watch item '{label}' (id={id}) saved successfully."


@mcp.tool()
def get_alerts(status: str = "new") -> str:
    """
    Get price alerts. status can be 'new', 'acknowledged', or 'all'.
    Returns a list of triggered alerts with supplier, price, and savings %.
    """
    from clawbot.tools.db_price import init_db, list_alerts

    init_db()
    alerts = list_alerts(status=status if status != "all" else None)
    if not alerts:
        return f"No {status} alerts found."
    return json.dumps([a.model_dump() for a in alerts], indent=2)


@mcp.tool()
def get_watchlist() -> str:
    """
    Get all items currently in the PriceScout watchlist.
    """
    from clawbot.tools.db_price import init_db, list_watch_items

    init_db()
    items = list_watch_items(active_only=False)
    if not items:
        return "No watch items configured."
    return json.dumps([i.model_dump() for i in items], indent=2)


# ---------------------------------------------------------------------------
# Procurement tools
# ---------------------------------------------------------------------------


@mcp.tool()
def source_suppliers(business_name: str, location: str) -> str:
    """
    Run the Procurement agent to find wholesale suppliers for all active procurement items.
    Searches for bulk/wholesale pricing, records quotes, and recommends the best option per item.
    Returns a full procurement report with recommendations.
    """
    from clawbot.agents.procurement_agent import run_procurement_agent

    report = run_procurement_agent(business_name=business_name, location=location)
    return json.dumps({
        "business_name": report.business_name,
        "scan_date": report.scan_date,
        "items_sourced": report.items_sourced,
        "executive_summary": report.executive_summary,
        "recommendations": [r.model_dump() for r in report.recommendations],
    }, indent=2)


@mcp.tool()
def add_procurement_item(
    id: str,
    name: str,
    quantity_needed: int = 1,
    budget_per_unit: float | None = None,
    notes: str | None = None,
) -> str:
    """
    Add or update a product the business wants to procure.
    The procurement agent will search for wholesale suppliers for this item.
    budget_per_unit is optional — if set, the agent will flag quotes that exceed it.
    """
    from clawbot.schemas.procurement import ProcurementItem
    from clawbot.tools.db_procurement import init_db, upsert_item

    init_db()
    item = ProcurementItem(
        id=id,
        name=name,
        quantity_needed=quantity_needed,
        budget_per_unit=budget_per_unit,
        notes=notes,
        active=True,
    )
    upsert_item(item)
    return f"Procurement item '{name}' (id={id}) saved successfully."


@mcp.tool()
def get_quotes(item_id: str | None = None) -> str:
    """
    Get supplier quotes recorded by the procurement agent.
    Optionally filter by item_id to see quotes for a specific product.
    """
    from clawbot.tools.db_procurement import init_db, list_quotes

    init_db()
    quotes = list_quotes(item_id=item_id)
    if not quotes:
        return "No quotes recorded yet."
    return json.dumps([q.model_dump() for q in quotes], indent=2)


@mcp.tool()
def get_procurement_items() -> str:
    """
    Get all items currently in the procurement list.
    """
    from clawbot.tools.db_procurement import init_db, list_items

    init_db()
    items = list_items(active_only=False)
    if not items:
        return "No procurement items configured."
    return json.dumps([i.model_dump() for i in items], indent=2)


# ---------------------------------------------------------------------------
# iMessage digest tool
# ---------------------------------------------------------------------------


@mcp.tool()
def send_digest(
    recipient: str,
    business_name: str,
    location: str,
    include_procurement: bool = True,
) -> str:
    """
    Build and send an iMessage digest to the recipient.
    Pulls price alerts and procurement quotes directly from the local database,
    synthesizes a concise plain-text summary with Claude, and sends it via iMessage.
    recipient should be a phone number like '+15551234567'.
    """
    import anthropic

    from clawbot.tools.db_price import list_alerts, list_watch_items
    from clawbot.tools.db_procurement import list_items, list_quotes

    # Gather price data
    alerts = list_alerts(status="new")
    watch_items = list_watch_items(active_only=True)

    # Gather procurement data
    proc_items = list_items(active_only=True) if include_procurement else []
    quotes = list_quotes() if include_procurement else []

    # Build best-quote-per-item summary
    best_quotes: dict[str, dict] = {}
    for q in quotes:
        if q.item_id not in best_quotes or q.price_per_unit < best_quotes[q.item_id]["price"]:
            best_quotes[q.item_id] = {"supplier": q.supplier, "price": q.price_per_unit, "moq": q.moq}

    payload = {
        "price_watch_items": len(watch_items),
        "new_price_alerts": [
            {"summary": a.summary, "savings_pct": a.delta_pct} for a in alerts
        ],
        "procurement_items": [
            {
                "name": item.name,
                "qty_needed": item.quantity_needed,
                "budget": item.budget_per_unit,
                "best_quote": best_quotes.get(item.id),
            }
            for item in proc_items
        ] if include_procurement else [],
    }

    system_prompt = (
        "You are a business digest writer for small business owners. "
        "Given price alerts and procurement data, write a concise iMessage-ready summary. "
        "Maximum 5 bullet points. Plain text only — no markdown, no asterisks, no pound signs. "
        "Lead with the most actionable item. Keep each bullet under 300 characters."
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": (
                f"Business: {business_name}, {location}\n\n"
                f"Data:\n{json.dumps(payload, indent=2)}\n\n"
                "Write the iMessage digest now."
            ),
        }],
    )

    message_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            message_text = block.text.strip()
            break

    if not message_text:
        return "Error: Claude returned an empty digest."

    if not os.path.isfile(IMSG_BINARY):
        return f"Digest (not sent — imsg binary not found):\n\n{message_text}"

    result = subprocess.run(
        [IMSG_BINARY, "send", "--to", recipient, "--text", message_text],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode == 0:
        return f"Sent to {recipient}.\n\nMessage:\n{message_text}"
    else:
        return f"Send failed.\n\nMessage would have been:\n{message_text}"


# ---------------------------------------------------------------------------
# Inventory tools
# ---------------------------------------------------------------------------


@mcp.tool()
def scan_barcode(barcode: str, quantity_change: int = 1, reason: str = "scan", sell_price: float | None = None, reorder_point: int = 5) -> str:
    """
    Scan a product barcode to add or remove stock.
    Automatically looks up product name, brand, and category from UPC Item DB.
    quantity_change: positive = adding stock, negative = removing stock.
    reason: 'restock', 'sale', 'adjustment', or 'scan'.
    Returns the updated item and a low-stock warning if applicable.
    """
    from clawbot.agents.inventory_agent import scan_barcode as _scan

    result = _scan(
        barcode=barcode,
        quantity_change=quantity_change,
        reason=reason,
        sell_price=sell_price,
        reorder_point=reorder_point,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
def lookup_barcode(barcode: str) -> str:
    """
    Look up product info for a barcode without updating inventory.
    Returns product name, brand, category, description, image URL, and market price.
    Uses UPC Item DB (free, no auth required).
    """
    from clawbot.tools.barcode_lookup import lookup_barcode as _lookup

    result = _lookup(barcode)
    return result.model_dump_json(indent=2)


@mcp.tool()
def get_inventory(category: str | None = None, low_stock_only: bool = False) -> str:
    """
    Get current inventory items.
    Optionally filter by category (e.g. 'LEGO', 'Puzzles') or show only low-stock items.
    """
    from clawbot.tools.db_inventory import init_db, list_items

    init_db()
    items = list_items(category=category, low_stock_only=low_stock_only)
    if not items:
        return "No inventory items found."
    return json.dumps([i.model_dump() for i in items], indent=2)


@mcp.tool()
def get_low_stock() -> str:
    """
    Get all inventory items that are at or below their reorder point.
    Use this to identify what needs restocking urgently.
    """
    from clawbot.tools.db_inventory import get_low_stock_items, init_db

    init_db()
    alerts = get_low_stock_items()
    if not alerts:
        return "All items are adequately stocked."
    return json.dumps([a.model_dump() for a in alerts], indent=2)


# ---------------------------------------------------------------------------
# Summary tool
# ---------------------------------------------------------------------------


@mcp.tool()
def get_summary() -> str:
    """
    Get a high-level summary across all agents: active watch items,
    new price alerts, procurement items, quotes on file, and inventory counts.
    """
    from clawbot.tools.db_inventory import get_low_stock_items, list_items as inv_list_items
    from clawbot.tools.db_price import list_alerts, list_watch_items
    from clawbot.tools.db_procurement import list_items, list_quotes

    watch_items = list_watch_items(active_only=False)
    active_watch = [i for i in watch_items if i.active]
    alerts = list_alerts(status="new")
    proc_items = list_items(active_only=False)
    active_proc = [i for i in proc_items if i.active]
    quotes = list_quotes()
    inv_items = inv_list_items()
    low_stock = get_low_stock_items()

    return json.dumps({
        "price_scout": {
            "watch_items_active": len(active_watch),
            "watch_items_total": len(watch_items),
            "new_alerts": len(alerts),
        },
        "procurement": {
            "items_active": len(active_proc),
            "items_total": len(proc_items),
            "quotes_on_file": len(quotes),
        },
        "inventory": {
            "total_items": len(inv_items),
            "low_stock": len(low_stock),
            "out_of_stock": len([i for i in inv_items if i.quantity == 0]),
        },
    }, indent=2)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
