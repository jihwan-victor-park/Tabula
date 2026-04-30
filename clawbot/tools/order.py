"""
Order confirmation helper — formats a ProcurementOrder as a plain-text message
and delivers it via the shared messaging utility (Twilio → osascript fallback).
"""

from __future__ import annotations

from clawbot.tools.messaging import send_message


def format_order_message(order: "ProcurementOrder") -> str:  # type: ignore[name-defined]
    lines: list[str] = []
    lines.append(f"Order approval needed for {order.business_name}:")
    lines.append("")

    for i, li in enumerate(order.line_items, 1):
        line = (
            f"{i}. {li.product_name} - {li.quantity} units from {li.supplier} "
            f"at ${li.price_per_unit:.2f}/unit = ${li.total_cost:.2f}"
        )
        if len(line) > 300:
            line = line[:297] + "..."
        lines.append(line)

    lines.append("")
    lines.append(f"Total order cost: ${order.total_cost:.2f}")
    lines.append("Reply YES to confirm or NO to cancel.")
    return "\n".join(lines)


def send_order_imsg(order: "ProcurementOrder", recipient: str) -> tuple[bool, str]:  # type: ignore[name-defined]
    message = format_order_message(order)
    sent, _ = send_message(recipient, message)
    return sent, message
