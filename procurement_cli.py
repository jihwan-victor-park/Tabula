"""
Procurement Agent CLI — rich-formatted command-line interface for the Procurement API.

Usage examples:
    python procurement_cli.py source --business "Mike's Hardware" --location "Austin, TX"
    python procurement_cli.py items
    python procurement_cli.py quotes
    python procurement_cli.py summary
    python procurement_cli.py --url http://127.0.0.1:8003 items
"""

from __future__ import annotations

import argparse
import sys

import httpx
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

load_dotenv()

console = Console()

CONFIDENCE_STYLE = {
    "high": "green",
    "medium": "yellow",
    "low": "red",
}

DEFAULT_URL = "http://127.0.0.1:8003"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(url: str, path: str, params: dict | None = None) -> dict | list:
    try:
        resp = httpx.get(f"{url}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print(
            f"[bold red]Could not connect to Procurement API at {url}.[/bold red]\n"
            "  Is it running?  uvicorn procurement_agent.api.main:app --port 8003"
        )
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[bold red]API error {exc.response.status_code}:[/bold red] {exc.response.text}")
        sys.exit(1)


def _post(url: str, path: str, body: dict) -> dict:
    try:
        resp = httpx.post(f"{url}{path}", json=body, timeout=180)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print(
            f"[bold red]Could not connect to Procurement API at {url}.[/bold red]\n"
            "  Is it running?  uvicorn procurement_agent.api.main:app --port 8003"
        )
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[bold red]API error {exc.response.status_code}:[/bold red] {exc.response.text}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command: source
# ---------------------------------------------------------------------------


def cmd_source(args: argparse.Namespace) -> None:
    console.print(
        f"\n[bold]Running Procurement Agent for [cyan]{args.business}[/cyan] "
        f"in [cyan]{args.location}[/cyan]...[/bold]\n"
    )

    with console.status("[bold green]Agent is searching for wholesale suppliers...[/bold green]"):
        data = _post(args.url, "/source", {"business_name": args.business, "location": args.location})

    console.print(
        Panel(
            data.get("executive_summary", "No summary available."),
            title="[bold]Executive Summary[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    console.print(
        f"[bold]Items sourced:[/bold] {data.get('items_sourced', 0)}   "
        f"[dim]Scan date: {data.get('scan_date', '—')}[/dim]"
    )
    console.print()

    recommendations = data.get("recommendations", [])
    if recommendations:
        console.print(Rule("[bold]Sourcing Recommendations[/bold]", style="dim"))
        for rec in recommendations:
            savings = rec.get("savings_vs_budget_pct")
            savings_str = f"{savings:+.1f}% vs budget" if savings is not None else "no budget set"
            savings_style = "green" if (savings or 0) >= 0 else "red"
            moq = rec.get("moq")
            moq_str = f"MOQ {moq}" if moq else "no MOQ"

            body = (
                f"[bold]{rec.get('recommended_supplier', '—')}[/bold]  "
                f"${rec.get('price_per_unit', 0):.2f}/unit  •  {moq_str}\n"
                f"[{savings_style}]{savings_str}[/{savings_style}]\n"
                f"[dim]{rec.get('notes', '')}[/dim]"
            )
            console.print(
                Panel(
                    body,
                    title=f"[bold cyan]{rec.get('product_name', rec.get('item_id', ''))}[/bold cyan]",
                    border_style="cyan",
                    padding=(0, 2),
                )
            )
        console.print()


# ---------------------------------------------------------------------------
# Command: items
# ---------------------------------------------------------------------------


def cmd_items(args: argparse.Namespace) -> None:
    data = _get(args.url, "/items")
    items = data if isinstance(data, list) else []

    console.print(Rule("[bold]Procurement Items[/bold]", style="dim"))

    if not items:
        console.print("[dim]No procurement items configured.[/dim]")
        return

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    t.add_column("ID", width=22)
    t.add_column("Name", width=30)
    t.add_column("Qty Needed", justify="right", width=10)
    t.add_column("Budget/Unit", justify="right", width=12)
    t.add_column("Active", justify="center", width=7)
    t.add_column("Last Sourced", width=12)

    for item in items:
        active = "[green]yes[/green]" if item.get("active") else "[red]no[/red]"
        budget = f"${item['budget_per_unit']:.2f}" if item.get("budget_per_unit") else "—"
        last = (item.get("last_sourced_at") or "—")[:10]
        t.add_row(
            item.get("id", ""),
            item.get("name", ""),
            str(item.get("quantity_needed", 1)),
            budget,
            active,
            last,
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Command: quotes
# ---------------------------------------------------------------------------


def cmd_quotes(args: argparse.Namespace) -> None:
    params = {}
    if args.item_id:
        params["item_id"] = args.item_id

    data = _get(args.url, "/quotes", params=params or None)
    quotes = data if isinstance(data, list) else []

    label = "Supplier Quotes" + (f" [{args.item_id}]" if args.item_id else "")
    console.print(Rule(f"[bold]{label}[/bold]", style="dim"))

    if not quotes:
        console.print("[dim]No quotes recorded yet.[/dim]")
        return

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    t.add_column("Item ID", width=22)
    t.add_column("Supplier", width=20)
    t.add_column("Price/Unit", justify="right", width=12)
    t.add_column("MOQ", justify="right", width=8)
    t.add_column("Confidence", justify="center", width=10)
    t.add_column("Found At", width=12)

    for q in quotes:
        moq = str(q.get("moq")) if q.get("moq") else "—"
        conf = q.get("confidence", "medium")
        t.add_row(
            q.get("item_id", "—"),
            q.get("supplier", "—"),
            f"${q.get('price_per_unit', 0):.2f}",
            moq,
            Text(conf, style=CONFIDENCE_STYLE.get(conf, "white")),
            (q.get("found_at") or "—")[:10],
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Command: summary
# ---------------------------------------------------------------------------


def cmd_summary(args: argparse.Namespace) -> None:
    data = _get(args.url, "/summary")

    items_info = data.get("procurement_items", {})
    quotes_info = data.get("quotes", {})

    lines = [
        f"Procurement items:  [bold]{items_info.get('active', 0)}[/bold] active / {items_info.get('total', 0)} total",
        f"Supplier quotes:    {quotes_info.get('total', 0)} recorded",
    ]

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Procurement Summary[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="procurement",
        description="Procurement Agent CLI — find wholesale suppliers for your business",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Procurement API base URL (default: {DEFAULT_URL})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # source
    p_src = subparsers.add_parser("source", help="Run a procurement sourcing scan")
    p_src.add_argument("--business", required=True, help="Business name")
    p_src.add_argument("--location", required=True, help="City/state, e.g. 'Austin, TX'")
    p_src.set_defaults(func=cmd_source)

    # items
    p_it = subparsers.add_parser("items", help="List all procurement items")
    p_it.set_defaults(func=cmd_items)

    # quotes
    p_qt = subparsers.add_parser("quotes", help="List supplier quotes")
    p_qt.add_argument("--item-id", dest="item_id", help="Filter by item ID")
    p_qt.set_defaults(func=cmd_quotes)

    # summary
    p_su = subparsers.add_parser("summary", help="Show high-level summary counts")
    p_su.set_defaults(func=cmd_summary)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
