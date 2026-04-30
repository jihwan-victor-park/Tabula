"""
Universal Agent — single iMessage agent with two modes:

  Reactive  (/ask)    — responds when the owner texts it
  Proactive (/digest) — pushes a briefing on a schedule

Both modes share the same identity (SOUL.md + TOOLS.md + MEMORY.md),
the same specialist agents, and the same iMessage delivery layer.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic
import httpx

from clawbot.agents import pending_orders
from clawbot.schemas.imsg import DigestRequest, DigestResult
from clawbot.schemas.universal import UniversalResult, UserMessage
from clawbot.tools.messaging import send_message

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENCLAW_DIR = REPO_ROOT / ".openclaw"


# ---------------------------------------------------------------------------
# Identity — load per-user IDENTITY.md, SOUL.md, MEMORY.md + shared TOOLS.md
# ---------------------------------------------------------------------------

def _safe_filename(recipient: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_+]", "_", recipient)


def _load_context(recipient: str = "") -> str:
    sections: list[str] = []

    # Per-user files (identity, soul, memory) — fall back to shared if not found
    for label, per_user_name, shared_name in [
        ("IDENTITY.md", f"identity_{_safe_filename(recipient)}.md", "IDENTITY.md"),
        ("SOUL.md",     f"soul_{_safe_filename(recipient)}.md",     "SOUL.md"),
        ("MEMORY.md",   f"memory_{_safe_filename(recipient)}.md",   "MEMORY.md"),
    ]:
        per_user_path = OPENCLAW_DIR / per_user_name
        shared_path = REPO_ROOT / shared_name
        path = per_user_path if per_user_path.exists() else (shared_path if shared_path.exists() else None)
        if path:
            content = path.read_text(encoding="utf-8").strip()
            sections.append(f"--- {label} ---\n{content}")

    # Shared TOOLS.md always loaded
    tools_path = REPO_ROOT / "TOOLS.md"
    if tools_path.exists():
        content = tools_path.read_text(encoding="utf-8").strip()
        sections.append(f"--- TOOLS.md ---\n{content}")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_REACTIVE_INSTRUCTIONS = """
--- Reactive Mode ---
You are responding to a direct message from the business owner.
Call the relevant specialist agents, then call send_response ONCE with a plain-text reply.

Available specialists:
- analyze_trends: demand signals, what's trending, what to stock
- check_inventory: current stock levels, low-stock alerts
- find_suppliers: wholesale sourcing, order forms, pricing
- check_prices: competitor pricing, price alerts

Handling YES / NO replies:
- YES/yep/ok/sure → get_pending_order, confirm_order, send_response
- NO/nope/cancel  → cancel_order, send_response

Rules for send_response:
- Plain text only — no markdown, no asterisks, no pound signs
- Max 5 lines, max 300 characters per line
- Lead with the most actionable insight
- When presenting a new order: include total cost, end with "Reply YES to place or NO to cancel"
- Be direct — the owner is busy
"""

_DIGEST_INSTRUCTIONS = """
--- Proactive Digest Mode ---
You are writing an unprompted briefing for the business owner.
Given price alerts, trend signals, and procurement data:
- Maximum 5 bullet points, plain text only
- No markdown, no asterisks, no pound signs
- Lead with the most actionable item
- Keep each bullet under 300 characters
- Apply the iMessage style and tone from SOUL.md above
"""

def _reactive_system(recipient: str = "") -> str:
    ctx = _load_context(recipient)
    return (ctx + "\n\n" + _REACTIVE_INSTRUCTIONS.strip()) if ctx else _REACTIVE_INSTRUCTIONS.strip()

def _digest_system(recipient: str = "") -> str:
    ctx = _load_context(recipient)
    return (ctx + "\n\n" + _DIGEST_INSTRUCTIONS.strip()) if ctx else _DIGEST_INSTRUCTIONS.strip()


# ---------------------------------------------------------------------------
# Reactive — tool definitions
# ---------------------------------------------------------------------------

def _tool_definitions(req: UserMessage) -> list[dict[str, Any]]:
    return [
        {
            "name": "analyze_trends",
            "description": (
                "Check demand trends for one or more product categories. "
                "Use when the owner asks about what's trending, what to stock, "
                "or mentions customer demand for a product."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Product categories to analyse, e.g. ['Books', 'Toys']",
                    },
                    "extra_context": {
                        "type": "string",
                        "description": "Any extra context from the owner's message",
                    },
                },
                "required": ["categories"],
            },
        },
        {
            "name": "check_inventory",
            "description": (
                "Get current stock levels and low-stock alerts. "
                "Use when the owner asks about inventory, what's running low, "
                "or what needs restocking."
            ),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "find_suppliers",
            "description": (
                "Search for wholesale suppliers for a product and generate a "
                "draft order form with pricing. Use when the owner wants to "
                "source or restock a specific product."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string"},
                    "quantity": {
                        "type": "integer",
                        "description": "Units to order — default 20 if unclear",
                    },
                },
                "required": ["product_name"],
            },
        },
        {
            "name": "check_prices",
            "description": (
                "Get price alerts and competitor pricing data from the price scout. "
                "Use when the owner asks about pricing, competitor prices, or deals."
            ),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_pending_order",
            "description": (
                "Retrieve the last pending order waiting for owner confirmation. "
                "Use this when the owner replies YES or NO."
            ),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "confirm_order",
            "description": "Mark the pending order as confirmed after the owner replies YES.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "cancel_order",
            "description": "Cancel the pending order after the owner replies NO.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "send_response",
            "description": (
                "Send the final reply to the owner via iMessage. "
                "Call this ONCE at the end. Plain text only — no markdown, no asterisks."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to send. Plain text, max 5 lines.",
                    }
                },
                "required": ["message"],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Reactive — tool dispatcher
# ---------------------------------------------------------------------------

def _dispatch(
    name: str,
    inputs: dict[str, Any],
    req: UserMessage,
    agents_called: list[str],
) -> str:
    if name == "analyze_trends":
        agents_called.append("trend")
        try:
            resp = httpx.post(
                f"{req.trend_url}/analyze",
                json={
                    "business_name": req.business_name,
                    "location": req.location,
                    "categories": inputs["categories"],
                    "extra_context": inputs.get("extra_context", ""),
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            return json.dumps({
                "executive_summary": data.get("executive_summary", ""),
                "categories": [
                    {
                        "name": c["name"],
                        "status": c["status"],
                        "confidence": c["confidence"],
                        "signals": c.get("signals", [])[:3],
                        "recommendations": [
                            {"action": r["action"], "product_name": r["product_name"], "reason": r["reason"]}
                            for r in c.get("recommendations", [])[:3]
                        ],
                    }
                    for c in data.get("categories", [])
                ],
            })
        except Exception as exc:
            return json.dumps({"error": f"Trend agent unavailable: {exc}"})

    if name == "check_inventory":
        agents_called.append("inventory")
        try:
            resp = httpx.get(f"{req.inventory_url}/low-stock", timeout=15)
            resp.raise_for_status()
            low = resp.json()
            summary_resp = httpx.get(f"{req.inventory_url}/summary", timeout=15)
            summary = summary_resp.json() if summary_resp.status_code == 200 else {}
            return json.dumps({"summary": summary, "low_stock_items": low.get("items", [])})
        except Exception as exc:
            return json.dumps({"error": f"Inventory agent unavailable: {exc}"})

    if name == "find_suppliers":
        agents_called.append("procurement")
        product = inputs["product_name"]
        quantity = inputs.get("quantity", 20)
        item_id = product.lower().replace(" ", "-")[:40]
        try:
            httpx.post(
                f"{req.procurement_url}/items",
                json={"id": item_id, "name": product, "quantity_needed": quantity, "active": True},
                timeout=15,
            )
            resp = httpx.post(
                f"{req.procurement_url}/procure",
                json={
                    "business_name": req.business_name,
                    "location": req.location,
                    "recipient": req.recipient,
                    "send_confirmation": False,
                    "item_ids": [item_id],
                },
                timeout=180,
            )
            resp.raise_for_status()
            order = resp.json()
            result = {
                "order_id": order.get("order_id"),
                "total_cost": order.get("total_cost"),
                "line_items": [
                    {
                        "product": li["product_name"],
                        "supplier": li["supplier"],
                        "qty": li["quantity"],
                        "price_per_unit": li["price_per_unit"],
                        "total": li["total_cost"],
                        "margin_pct": li.get("margin_pct"),
                        "margin_viable": li.get("margin_viable"),
                    }
                    for li in order.get("line_items", [])
                ],
            }
            if result.get("line_items"):
                pending_orders.save(req.recipient, result)
            return json.dumps(result)
        except Exception as exc:
            return json.dumps({"error": f"Procurement agent unavailable: {exc}"})

    if name == "check_prices":
        agents_called.append("price_scout")
        try:
            # Trigger a fresh scan (kicks off Browserbase for URL-based watch items)
            httpx.post(
                f"{req.price_scout_url}/scan",
                json={"business_name": req.business_name, "location": req.location},
                timeout=180,
            )
        except Exception:
            pass  # If scan fails, still return existing data
        try:
            summary = httpx.get(f"{req.price_scout_url}/summary", timeout=15).json()
            alerts = httpx.get(
                f"{req.price_scout_url}/alerts", params={"status": "new"}, timeout=15
            ).json()
            return json.dumps({"summary": summary, "new_alerts": alerts[:5]})
        except Exception as exc:
            return json.dumps({"error": f"Price scout unavailable: {exc}"})

    if name == "get_pending_order":
        order = pending_orders.get(req.recipient)
        return json.dumps(order if order else {"pending": False})

    if name == "confirm_order":
        order = pending_orders.get(req.recipient)
        if order:
            pending_orders.clear(req.recipient)
            return json.dumps({"confirmed": True, "order": order})
        return json.dumps({"confirmed": False, "reason": "No pending order found"})

    if name == "cancel_order":
        pending_orders.clear(req.recipient)
        return json.dumps({"cancelled": True})

    if name == "send_response":
        return json.dumps({"queued": True, "message": inputs.get("message", "")})

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Reactive entry point — responds to an inbound owner message
# ---------------------------------------------------------------------------

def run_universal_agent(req: UserMessage) -> UniversalResult:
    """Handle an inbound iMessage from the owner and reply."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    agents_called: list[str] = []
    final_response_text = ""

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Business: {req.business_name}, {req.location}\n"
                f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
                f"Owner message: {req.message}"
            ),
        }
    ]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_reactive_system(req.recipient),
            tools=_tool_definitions(req),
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            raw_result = _dispatch(block.name, block.input, req, agents_called)
            if block.name == "send_response":
                try:
                    final_response_text = json.loads(raw_result).get("message", "")
                except Exception:
                    pass
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": raw_result,
            })

        if not tool_results:
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    sent = False
    error: str | None = None
    if final_response_text:
        sent, error = send_message(req.recipient, final_response_text)

    return UniversalResult(
        message_received=req.message,
        agents_called=list(dict.fromkeys(agents_called)),
        response_text=final_response_text,
        confirmation_sent=sent,
        recipient=req.recipient,
        error=error,
    )


# ---------------------------------------------------------------------------
# Proactive digest data fetchers
# ---------------------------------------------------------------------------

def _fetch_price_summary(base_url: str) -> dict[str, Any]:
    try:
        resp = httpx.get(f"{base_url}/summary", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def _fetch_new_alerts(base_url: str) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(f"{base_url}/alerts", params={"status": "new"}, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def _fetch_procurement_summary(base_url: str) -> dict[str, Any] | None:
    try:
        resp = httpx.get(f"{base_url}/summary", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _fetch_procurement_quotes(base_url: str) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(f"{base_url}/quotes", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def _fetch_trend_analysis(
    trend_url: str, business_name: str, location: str, categories: list[str]
) -> dict[str, Any] | None:
    if not categories:
        return None
    try:
        resp = httpx.post(
            f"{trend_url}/analyze",
            json={"business_name": business_name, "location": location, "categories": categories},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Proactive entry point — builds and sends an unprompted digest
# ---------------------------------------------------------------------------

def send_digest(request: DigestRequest) -> DigestResult:
    """Gather business data, synthesize a digest with Claude, send via iMessage."""
    price_summary = _fetch_price_summary(request.price_scout_url)
    alerts = _fetch_new_alerts(request.price_scout_url)

    trend_data: dict[str, Any] | None = None
    trend_summary: str | None = None
    if request.include_trends and request.categories:
        trend_data = _fetch_trend_analysis(
            trend_url=request.trend_url,
            business_name=request.business_name,
            location=request.location,
            categories=request.categories,
        )
        if trend_data:
            trend_summary = trend_data.get("executive_summary")

    procurement_data: dict[str, Any] | None = None
    procurement_summary: str | None = None
    if request.include_procurement:
        proc_summary = _fetch_procurement_summary(request.procurement_url)
        proc_quotes = _fetch_procurement_quotes(request.procurement_url)
        if proc_summary or proc_quotes:
            procurement_data = {"summary": proc_summary, "recent_quotes": proc_quotes[:10]}
            items_active = (proc_summary or {}).get("procurement_items", {}).get("active", 0)
            quotes_total = (proc_summary or {}).get("quotes", {}).get("total", 0)
            procurement_summary = f"{items_active} items being sourced, {quotes_total} quotes on file"

    payload: dict[str, Any] = {"price_summary": price_summary, "new_alerts": alerts}
    if trend_data:
        payload["trend_analysis"] = {
            "executive_summary": trend_data.get("executive_summary", ""),
            "categories": [
                {"name": c.get("name"), "status": c.get("status"), "signals": c.get("signals", [])[:3]}
                for c in trend_data.get("categories", [])
            ],
        }
    if procurement_data:
        payload["procurement"] = procurement_data

    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=_digest_system(request.recipient),
            messages=[{
                "role": "user",
                "content": (
                    "Here is the latest business intelligence data:\n\n"
                    f"{json.dumps(payload, indent=2)}\n\n"
                    "Write a concise iMessage digest. Max 5 bullets. Plain text only."
                ),
            }],
        )
        message_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                message_text = block.text.strip()
                break
    except Exception as exc:
        return DigestResult(
            sent=False, recipient=request.recipient, message_text="",
            price_alert_count=len(alerts), trend_summary=trend_summary,
            procurement_summary=procurement_summary,
            error=f"Claude synthesis failed: {exc}",
        )

    if not message_text:
        return DigestResult(
            sent=False, recipient=request.recipient, message_text="",
            price_alert_count=len(alerts), trend_summary=trend_summary,
            procurement_summary=procurement_summary, error="Claude returned an empty digest.",
        )

    sent, err = send_message(request.recipient, message_text)
    return DigestResult(
        sent=sent, recipient=request.recipient, message_text=message_text,
        price_alert_count=len(alerts), trend_summary=trend_summary,
        procurement_summary=procurement_summary,
        error=err if not sent else None,
    )
