"""
iMessage Digest CLI — build and send a business digest via iMessage.

Usage:
    python imsg_cli.py send \\
        --business "Mike's Hardware" \\
        --location "Austin, TX" \\
        --categories "power tools" "hardware" \\
        --recipient "+15551234567"

    # Run a fresh price scan first, then send the digest:
    python imsg_cli.py send \\
        --business "Mike's Hardware" \\
        --location "Austin, TX" \\
        --recipient "+15551234567" \\
        --run-scan-first

    python imsg_cli.py send \\
        --business "Mike's Hardware" \\
        --location "Austin, TX" \\
        --recipient "+15551234567" \\
        --no-trends
"""

from __future__ import annotations

import argparse
import sys

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

console = Console()


def _run_scan(price_scout_url: str, business: str, location: str) -> None:
    """Hit POST /scan and wait for the agent to finish before building the digest."""
    console.print("[bold]Running fresh price scan...[/bold]")
    try:
        with console.status("[bold green]Price agent scanning watchlist...[/bold green]"):
            resp = httpx.post(
                f"{price_scout_url}/scan",
                json={"business_name": business, "location": location},
                timeout=180,
            )
        if resp.status_code >= 400:
            console.print(f"[bold red]Scan failed (HTTP {resp.status_code}):[/bold red] {resp.text}")
            sys.exit(1)
        data = resp.json()
        items = data.get("items_scanned", "?")
        alerts = data.get("alerts_triggered", "?")
        console.print(f"[green]Scan complete[/green] — {items} items scanned, {alerts} alerts triggered.\n")
    except httpx.ConnectError:
        console.print(
            "[bold red]Could not connect to PriceScout API.[/bold red] "
            "Is it running?\n  uvicorn price_scout.api.main:app --port 8000"
        )
        sys.exit(1)


def cmd_send(args: argparse.Namespace) -> None:
    from clawbot.agents.universal_agent import send_digest as build_digest
    from clawbot.schemas.imsg import DigestRequest

    if args.run_scan_first:
        _run_scan(args.price_scout_url, args.business, args.location)

    request = DigestRequest(
        business_name=args.business,
        location=args.location,
        categories=args.categories or [],
        price_scout_url=args.price_scout_url,
        trend_url=args.trend_url,
        procurement_url=args.procurement_url,
        recipient=args.recipient,
        include_trends=not args.no_trends,
        include_procurement=not args.no_procurement,
    )

    console.print(
        f"\n[bold]Building digest for [cyan]{args.business}[/cyan] → "
        f"[cyan]{args.recipient}[/cyan]...[/bold]\n"
    )

    with console.status("[bold green]Fetching data and synthesizing digest...[/bold green]"):
        result = build_digest(request)

    # Display the message text
    console.print(
        Panel(
            result.message_text or "[dim](empty)[/dim]",
            title="[bold]Digest Message[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Status line
    if result.sent:
        console.print(f"\n[bold green]Sent successfully[/bold green] to {result.recipient}")
    else:
        console.print(f"\n[bold red]Send failed[/bold red] — {result.error or 'unknown error'}")

    # Stats
    console.print(
        f"[dim]Price alerts: {result.price_alert_count}  |  "
        f"Trends: {'included' if result.trend_summary else 'skipped'}  |  "
        f"Procurement: {'included' if result.procurement_summary else 'skipped'}[/dim]\n"
    )

    if result.trend_summary:
        console.print(f"[dim]Trend summary: {result.trend_summary[:120]}...[/dim]\n")

    if result.procurement_summary:
        console.print(f"[dim]Procurement: {result.procurement_summary}[/dim]\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imsg-digest",
        description="iMessage Digest CLI — send a business digest via iMessage",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_send = subparsers.add_parser("send", help="Build and send a digest")
    p_send.add_argument("--business", required=True, help="Business name")
    p_send.add_argument("--location", required=True, help="City/state, e.g. 'Austin, TX'")
    p_send.add_argument(
        "--categories",
        nargs="*",
        default=[],
        help="Product categories for trend analysis",
    )
    p_send.add_argument("--recipient", required=True, help="iMessage handle, e.g. '+15551234567'")
    p_send.add_argument(
        "--price-scout-url",
        default="http://127.0.0.1:8000",
        help="PriceScout API base URL (default: http://127.0.0.1:8000)",
    )
    p_send.add_argument(
        "--trend-url",
        default="http://127.0.0.1:8001",
        help="Trend Analyst API base URL (default: http://127.0.0.1:8001)",
    )
    p_send.add_argument(
        "--procurement-url",
        default="http://127.0.0.1:8003",
        help="Procurement Agent API base URL (default: http://127.0.0.1:8003)",
    )
    p_send.add_argument(
        "--no-trends",
        action="store_true",
        help="Skip trend analysis and only include price alerts",
    )
    p_send.add_argument(
        "--no-procurement",
        action="store_true",
        help="Skip procurement data from the digest",
    )
    p_send.add_argument(
        "--run-scan-first",
        action="store_true",
        help="Run a fresh POST /scan before building the digest (ensures up-to-date prices)",
    )
    p_send.set_defaults(func=cmd_send)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
