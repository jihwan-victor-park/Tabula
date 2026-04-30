"""
Inventory Agent CLI — rich-formatted command-line interface for the Inventory API.

Usage examples:
    python inventory_cli.py scan --barcode 0673419376396 --qty 10
    python inventory_cli.py lookup --barcode 0673419376396
    python inventory_cli.py items
    python inventory_cli.py items --low-stock
    python inventory_cli.py low-stock
    python inventory_cli.py adjust --barcode 0673419376396 --qty -1 --reason sale
    python inventory_cli.py report
    python inventory_cli.py summary
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

DEFAULT_URL = "http://127.0.0.1:8004"


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
            f"[bold red]Could not connect to Inventory API at {url}.[/bold red]\n"
            "  Is it running?  uvicorn inventory_agent.api.main:app --port 8004"
        )
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[bold red]API error {exc.response.status_code}:[/bold red] {exc.response.text}")
        sys.exit(1)


def _post(url: str, path: str, body: dict, timeout: int = 30) -> dict:
    try:
        resp = httpx.post(f"{url}{path}", json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print(
            f"[bold red]Could not connect to Inventory API at {url}.[/bold red]\n"
            "  Is it running?  uvicorn inventory_agent.api.main:app --port 8004"
        )
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[bold red]API error {exc.response.status_code}:[/bold red] {exc.response.text}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command: lookup
# ---------------------------------------------------------------------------


def cmd_lookup(args: argparse.Namespace) -> None:
    data = _get(args.url, f"/barcode/{args.barcode}")

    console.print(
        Panel(
            f"[bold]{data.get('name', 'Unknown')}[/bold]\n"
            f"Brand:    {data.get('brand') or '—'}\n"
            f"Category: {data.get('category') or '—'}\n"
            f"Price:    {'$' + str(data['market_price']) if data.get('market_price') else '—'}\n"
            f"Source:   {data.get('source', '—')}",
            title=f"[bold cyan]Barcode {args.barcode}[/bold cyan]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


# ---------------------------------------------------------------------------
# Command: scan
# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> None:
    with console.status(f"[bold green]Scanning barcode {args.barcode}...[/bold green]"):
        data = _post(args.url, "/scan", {
            "barcode": args.barcode,
            "quantity_change": args.qty,
            "reason": args.reason,
            "sell_price": args.price,
            "reorder_point": args.reorder,
        })

    item = data.get("item", {})
    low_stock = data.get("low_stock", False)
    border = "red" if low_stock else "green"

    console.print(
        Panel(
            f"[bold]{item.get('name', 'Unknown')}[/bold]\n"
            f"Brand:    {item.get('brand') or '—'}\n"
            f"Category: {item.get('category') or '—'}\n"
            f"Quantity: [bold]{ item.get('quantity', 0) }[/bold] in stock\n"
            + ("[bold red]LOW STOCK — reorder soon![/bold red]" if low_stock else "[green]Stock OK[/green]"),
            title=f"[bold]Scanned: {args.barcode}[/bold]",
            border_style=border,
            padding=(0, 2),
        )
    )


# ---------------------------------------------------------------------------
# Command: items
# ---------------------------------------------------------------------------


def cmd_items(args: argparse.Namespace) -> None:
    params = {}
    if args.low_stock:
        params["low_stock"] = "true"
    if args.category:
        params["category"] = args.category

    data = _get(args.url, "/items", params=params or None)
    items = data if isinstance(data, list) else []

    title = "Inventory" + (" [Low Stock]" if args.low_stock else "")
    console.print(Rule(f"[bold]{title}[/bold]", style="dim"))

    if not items:
        console.print("[dim]No items found.[/dim]")
        return

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    t.add_column("Barcode", width=16)
    t.add_column("Name", width=32)
    t.add_column("Brand", width=16)
    t.add_column("Category", width=14)
    t.add_column("Qty", justify="right", width=6)
    t.add_column("Reorder", justify="right", width=8)
    t.add_column("Sell Price", justify="right", width=10)

    for item in items:
        qty = item.get("quantity", 0)
        reorder = item.get("reorder_point", 5)
        qty_style = "red" if qty <= reorder else ("yellow" if qty <= reorder * 2 else "green")
        sell = f"${item['sell_price']:.2f}" if item.get("sell_price") else "—"
        t.add_row(
            item.get("id", ""),
            item.get("name", ""),
            item.get("brand") or "—",
            item.get("category") or "—",
            Text(str(qty), style=qty_style),
            str(reorder),
            sell,
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Command: low-stock
# ---------------------------------------------------------------------------


def cmd_low_stock(args: argparse.Namespace) -> None:
    data = _get(args.url, "/low-stock")
    alerts = data.get("items", [])

    console.print(Rule("[bold red]Low Stock Alerts[/bold red]", style="dim"))

    if not alerts:
        console.print("[green]All items are adequately stocked.[/green]")
        return

    for alert in alerts:
        qty = alert.get("quantity", 0)
        reorder = alert.get("reorder_point", 5)
        urgency = "[bold red]OUT OF STOCK[/bold red]" if qty == 0 else f"[yellow]{alert.get('units_below_threshold', 0)} below threshold[/yellow]"
        console.print(
            Panel(
                f"[bold]{alert.get('name', '—')}[/bold]  {alert.get('brand') or ''}\n"
                f"Category: {alert.get('category') or '—'}\n"
                f"Stock: [bold]{qty}[/bold] / Reorder at: {reorder}\n"
                f"{urgency}",
                title=f"[dim]{alert.get('item_id', '')}[/dim]",
                border_style="red" if qty == 0 else "yellow",
                padding=(0, 2),
            )
        )


# ---------------------------------------------------------------------------
# Command: adjust
# ---------------------------------------------------------------------------


def cmd_adjust(args: argparse.Namespace) -> None:
    data = _post(args.url, f"/items/{args.barcode}/adjust", {
        "quantity_change": args.qty,
        "reason": args.reason,
        "notes": args.notes,
    })
    console.print(
        f"[green]Adjusted[/green] '{data.get('name', args.barcode)}': "
        f"now [bold]{data.get('quantity', 0)}[/bold] in stock."
    )


# ---------------------------------------------------------------------------
# Command: report
# ---------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> None:
    console.print("\n[bold]Running Inventory Agent...[/bold]\n")

    with console.status("[bold green]Analyzing stock levels...[/bold green]"):
        data = _post(args.url, "/report", {}, timeout=120)

    console.print(
        Panel(
            data.get("executive_summary", "No summary available."),
            title="[bold]Inventory Report[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print(
        f"\n[bold]Total items:[/bold] {data.get('total_items', 0)}   "
        f"[bold red]Low stock:[/bold red] {data.get('low_stock_count', 0)}   "
        f"[dim]Date: {data.get('scan_date', '—')}[/dim]\n"
    )


# ---------------------------------------------------------------------------
# Command: summary
# ---------------------------------------------------------------------------


def cmd_summary(args: argparse.Namespace) -> None:
    data = _get(args.url, "/summary")
    console.print(
        Panel(
            f"Total items:   [bold]{data.get('total_items', 0)}[/bold]\n"
            f"Low stock:     [bold yellow]{data.get('low_stock', 0)}[/bold yellow]\n"
            f"Out of stock:  [bold red]{data.get('out_of_stock', 0)}[/bold red]",
            title="[bold]Inventory Summary[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inventory",
        description="Inventory Agent CLI — manage toy store inventory by barcode",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Inventory API base URL (default: {DEFAULT_URL})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # lookup
    p_lu = subparsers.add_parser("lookup", help="Look up product info from a barcode")
    p_lu.add_argument("--barcode", required=True, help="UPC/EAN barcode")
    p_lu.set_defaults(func=cmd_lookup)

    # scan
    p_sc = subparsers.add_parser("scan", help="Scan a barcode to add/remove stock")
    p_sc.add_argument("--barcode", required=True, help="UPC/EAN barcode")
    p_sc.add_argument("--qty", type=int, default=1, help="Units to add (+) or remove (-), default 1")
    p_sc.add_argument("--reason", default="scan", choices=["scan", "restock", "sale", "adjustment"])
    p_sc.add_argument("--price", type=float, default=None, help="Your selling price (optional)")
    p_sc.add_argument("--reorder", type=int, default=5, help="Reorder threshold (default 5)")
    p_sc.set_defaults(func=cmd_scan)

    # items
    p_it = subparsers.add_parser("items", help="List inventory items")
    p_it.add_argument("--low-stock", action="store_true", help="Only show low stock items")
    p_it.add_argument("--category", help="Filter by category")
    p_it.set_defaults(func=cmd_items)

    # low-stock
    p_ls = subparsers.add_parser("low-stock", help="Show all low stock alerts")
    p_ls.set_defaults(func=cmd_low_stock)

    # adjust
    p_adj = subparsers.add_parser("adjust", help="Manually adjust stock quantity")
    p_adj.add_argument("--barcode", required=True, help="Item barcode/ID")
    p_adj.add_argument("--qty", type=int, required=True, help="Quantity change (+/-)")
    p_adj.add_argument("--reason", default="adjustment", choices=["restock", "sale", "adjustment"])
    p_adj.add_argument("--notes", help="Optional note")
    p_adj.set_defaults(func=cmd_adjust)

    # report
    p_rp = subparsers.add_parser("report", help="Run full AI inventory report")
    p_rp.set_defaults(func=cmd_report)

    # summary
    p_su = subparsers.add_parser("summary", help="Show inventory counts")
    p_su.set_defaults(func=cmd_summary)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
