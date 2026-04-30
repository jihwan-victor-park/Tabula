"""
Orchestrator Agent — wires natural language owner messages through the full
trend → procurement pipeline and sends a rich iMessage confirmation.

Flow:
1. Claude extracts product intent from the owner's message.
2. Call the Trend Agent to confirm demand signals.
3. Add the product as an active procurement item.
4. Call the Procurement Agent to source suppliers and build an order form.
5. Claude composes a plain-text iMessage with trend context + order + margin analysis.
6. Deliver via osascript (Messages.app).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic
import httpx

from clawbot.tools.messaging import send_message
from clawbot.schemas.orchestrator import (
    ExtractedIntent,
    InboundMessage,
    OrchestratorResult,
)

# ---------------------------------------------------------------------------
# Intent extraction
# ---------------------------------------------------------------------------

_INTENT_SYSTEM = """You are an assistant that helps small business owners identify product procurement needs.

Given a message from a business owner, extract the following as JSON:
{
  "product_name": "the specific product or product line mentioned",
  "category": "broad product category, e.g. Books, Toys, Electronics",
  "quantity_estimate": <integer, how many units to order — default 20 if unclear>,
  "confidence": <float 0.0-1.0, how clearly the message expresses a procurement need>,
  "reasoning": "one sentence explaining your interpretation"
}

Output ONLY the JSON object — no commentary."""


def extract_intent(
    message: str, business_name: str, location: str
) -> ExtractedIntent:
    """Use Claude to extract structured procurement intent from a natural language message."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_INTENT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Business: {business_name}, {location}\n"
                    f"Owner message: {message}"
                ),
            }
        ],
    )
    raw = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw = block.text.strip()
            break

    # Strip markdown fences if present
    if "```" in raw:
        raw = re.sub(r"```(?:json)?", "", raw).strip()

    data = json.loads(raw)
    return ExtractedIntent(**data)


# ---------------------------------------------------------------------------
# Agent API calls
# ---------------------------------------------------------------------------


def _fetch_trend(
    trend_url: str, business_name: str, location: str, category: str
) -> dict[str, Any] | None:
    try:
        resp = httpx.post(
            f"{trend_url.rstrip('/')}/analyze",
            json={
                "business_name": business_name,
                "location": location,
                "categories": [category],
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _add_procurement_item(
    procurement_url: str, item_id: str, product_name: str, quantity: int
) -> None:
    try:
        httpx.post(
            f"{procurement_url.rstrip('/')}/items",
            json={
                "id": item_id,
                "name": product_name,
                "quantity_needed": quantity,
                "active": True,
            },
            timeout=15,
        )
    except Exception:
        pass  # Non-fatal — item may already exist


def _source_suppliers(
    procurement_url: str,
    business_name: str,
    location: str,
    recipient: str,
    item_ids: list[str],
) -> dict[str, Any] | None:
    """
    Run procurement sourcing for only the specified items and without sending
    the iMessage — the orchestrator composes and sends its own richer message.
    """
    try:
        resp = httpx.post(
            f"{procurement_url.rstrip('/')}/procure",
            json={
                "business_name": business_name,
                "location": location,
                "recipient": recipient,
                "send_confirmation": False,
                "item_ids": item_ids,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Rich iMessage composition
# ---------------------------------------------------------------------------

_COMPOSE_SYSTEM = """You write concise iMessage confirmations for small business owners.
Plain text only — no markdown, no asterisks, no pound signs, no emojis.
Max 5 lines. Max 300 characters per line.
Lead with the trend insight, then the order details, then a YES/NO ask."""


def _compose_message(
    business_name: str,
    intent: ExtractedIntent,
    trend_data: dict[str, Any] | None,
    order: dict[str, Any] | None,
) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    payload: dict[str, Any] = {
        "business": business_name,
        "product": intent.product_name,
        "category": intent.category,
        "quantity": intent.quantity_estimate,
    }

    if trend_data:
        cats = trend_data.get("categories", [])
        if cats:
            c = cats[0]
            payload["trend"] = {
                "status": c.get("status"),
                "confidence": c.get("confidence"),
                "signals": c.get("signals", [])[:2],
                "summary": trend_data.get("executive_summary", ""),
            }

    if order:
        items = order.get("line_items", [])
        payload["order"] = {
            "total_cost": order.get("total_cost"),
            "currency": order.get("currency", "USD"),
            "items": [
                {
                    "product": li.get("product_name"),
                    "qty": li.get("quantity"),
                    "supplier": li.get("supplier"),
                    "cost_per_unit": li.get("price_per_unit"),
                    "total": li.get("total_cost"),
                    "margin_pct": li.get("margin_pct"),
                    "margin_ok": li.get("margin_viable"),
                    "sell_price": li.get("typical_sell_price"),
                }
                for li in items
            ],
        }

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_COMPOSE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "Write an iMessage confirmation for this procurement opportunity:\n\n"
                    f"{json.dumps(payload, indent=2)}\n\n"
                    "Include: what's trending and why, the order details with cost, "
                    "margin info if available, and ask YES to confirm or NO to skip."
                ),
            }
        ],
    )
    for block in response.content:
        if hasattr(block, "text"):
            return block.text.strip()
    return ""


# ---------------------------------------------------------------------------
# iMessage delivery
# ---------------------------------------------------------------------------


def _send_imsg(recipient: str, message: str) -> bool:
    sent, _ = send_message(recipient, message)
    return sent


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_orchestrator(request: InboundMessage) -> OrchestratorResult:
    """
    End-to-end pipeline:
    1. Extract intent from owner's message.
    2. Confirm demand via Trend Agent.
    3. Add product to procurement list.
    4. Source suppliers via Procurement Agent.
    5. Compose rich iMessage and send for confirmation.
    """
    # Step 1 — extract intent
    try:
        intent = extract_intent(
            message=request.message,
            business_name=request.business_name,
            location=request.location,
        )
    except Exception as exc:
        return OrchestratorResult(
            message_received=request.message,
            error=f"Intent extraction failed: {exc}",
        )

    # Step 2 — trend analysis
    trend_data = _fetch_trend(
        trend_url=request.trend_url,
        business_name=request.business_name,
        location=request.location,
        category=intent.category,
    )

    trend_summary: str | None = None
    trend_direction: str | None = None
    trend_confidence: float | None = None
    if trend_data:
        trend_summary = trend_data.get("executive_summary")
        cats = trend_data.get("categories", [])
        if cats:
            trend_direction = cats[0].get("status")
            trend_confidence = cats[0].get("confidence")

    # Step 3 — add product as a procurement item
    item_id = re.sub(r"[^a-z0-9-]", "-", intent.product_name.lower())[:40].strip("-")
    _add_procurement_item(
        procurement_url=request.procurement_url,
        item_id=item_id,
        product_name=intent.product_name,
        quantity=intent.quantity_estimate,
    )

    # Step 4 — source suppliers for only this item (iMessage suppressed)
    order = _source_suppliers(
        procurement_url=request.procurement_url,
        business_name=request.business_name,
        location=request.location,
        recipient=request.recipient,
        item_ids=[item_id],
    )

    # Step 5 — compose and send rich iMessage
    try:
        imsg_text = _compose_message(
            business_name=request.business_name,
            intent=intent,
            trend_data=trend_data,
            order=order,
        )
    except Exception as exc:
        imsg_text = ""
        error = f"Message composition failed: {exc}"
    else:
        error = None

    sent = False
    if imsg_text:
        sent = _send_imsg(request.recipient, imsg_text)
        if not sent and error is None:
            error = (
                "iMessage delivery failed. Grant Automation → Messages permission in "
                "System Settings → Privacy & Security → Automation."
            )

    return OrchestratorResult(
        message_received=request.message,
        extracted_intent=intent,
        trend_summary=trend_summary,
        trend_direction=trend_direction,
        trend_confidence=trend_confidence,
        order=order,
        confirmation_sent=sent,
        confirmation_recipient=request.recipient,
        imsg_text=imsg_text,
        error=error,
    )
