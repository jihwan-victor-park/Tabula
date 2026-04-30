"""
PriceScout CLI — rich-formatted command-line interface for the PriceScout API.

Usage examples:
    python cli.py scan --business "Mike's Hardware" --location "Austin, TX"
    python cli.py watchlist
    python cli.py alerts --status new
    python cli.py findings
    python cli.py summary
    python cli.py --url http://127.0.0.1:8000 watchlist
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

STATUS_STYLE = {
    "new": "bold yellow",
    "acknowledged": "dim green",
}

ALERT_ICON = {
    "new": "! NEW",
    "acknowledged": "✓ ACK",
}

CONFIDENCE_STYLE = {
    "high": "green",
    "medium": "yellow",
    "low": "red",
}

DEFAULT_URL = "http://127.0.0.1:8000"


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
            f"[bold red]Could not connect to PriceScout API at {url}.[/bold red]\n"
            "  Is it running?  uvicorn price_scout.api.main:app --port 8000"
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
            f"[bold red]Could not connect to PriceScout API at {url}.[/bold red]\n"
            "  Is it running?  uvicorn price_scout.api.main:app --port 8000"
        )
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[bold red]API error {exc.response.status_code}:[/bold red] {exc.response.text}")
        sys.exit(1)


def _patch(url: str, path: str) -> dict:
    try:
        resp = httpx.patch(f"{url}{path}", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        console.print(f"[bold red]Could not connect to PriceScout API at {url}.[/bold red]")
        sys.exit(1)
    except httpx.HTTPStatusError as exc:
        console.print(f"[bold red]API error {exc.response.status_code}:[/bold red] {exc.response.text}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command: scan
# ---------------------------------------------------------------------------


def cmd_scan(args: argparse.Namespace) -> None:
    console.print(
        f"\n[bold]Running PriceScout for [cyan]{args.business}[/cyan] "
        f"in [cyan]{args.location}[/cyan]...[/bold]\n"
    )

    with console.status("[bold green]Agent is scanning market prices...[/bold green]"):
        data = _post(args.url, "/scan", {"business_name": args.business, "location": args.location})

    # Executive summary panel
    console.print(
        Panel(
            data.get("executive_summary", "No summary available."),
            title="[bold]Executive Summary[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )
    console.print()

    # Stats row
    console.print(
        f"[bold]Items scanned:[/bold] {data.get('items_scanned', 0)}   "
        f"[bold]Alerts triggered:[/bold] {data.get('alerts_triggered', 0)}   "
        f"[dim]Scan date: {data.get('scan_date', '—')}[/dim]"
    )
    console.print()

    # Findings table
    findings = data.get("findings", [])
    if findings:
        console.print(Rule("[bold]Findings[/bold]", style="dim"))
        t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
        t.add_column("Label", width=30)
        t.add_column("Baseline", justify="right", width=12)
        t.add_column("Best Price", justify="right", width=12)
        t.add_column("Supplier")
        t.add_column("Savings", justify="right", width=10)
        t.add_column("Confidence", justify="center", width=10)

        for f in findings:
            baseline_price = ""
            if f.get("baseline"):
                baseline_price = f"${f['baseline'].get('price', 0):.2f}"
            best = f.get("best_option") or {}
            best_price = f"${best.get('price', 0):.2f}" if best else "—"
            delta = f.get("delta_pct", 0.0)
            delta_str = f"{delta:+.1f}%" if delta else "0.0%"
            delta_style = "green" if delta >= 5 else ("yellow" if delta > 0 else "red")
            conf = f.get("confidence", "medium")
            t.add_row(
                f.get("label", "—"),
                baseline_price,
                best_price,
                best.get("supplier", "—"),
                Text(delta_str, style=delta_style),
                Text(conf, style=CONFIDENCE_STYLE.get(conf, "white")),
            )

        console.print(t)
        console.print()

    # Alerts table
    alerts = data.get("alerts", [])
    if alerts:
        console.print(Rule("[bold]Alerts Triggered[/bold]", style="dim"))
        for alert in alerts:
            console.print(
                Panel(
                    alert.get("summary", ""),
                    title=f"[bold yellow]{alert.get('watch_id', '')}[/bold yellow]  "
                    f"[dim]{alert.get('delta_pct', 0):.1f}% savings[/dim]",
                    border_style="yellow",
                    padding=(0, 2),
                )
            )
        console.print()


# ---------------------------------------------------------------------------
# Command: watchlist
# ---------------------------------------------------------------------------


def cmd_watchlist(args: argparse.Namespace) -> None:
    data = _get(args.url, "/watchlist")
    items = data if isinstance(data, list) else []

    console.print(Rule("[bold]Watch Items[/bold]", style="dim"))

    if not items:
        console.print("[dim]No watch items configured.[/dim]")
        return

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    t.add_column("ID", width=20)
    t.add_column("Label", width=28)
    t.add_column("Mode", width=10)
    t.add_column("Active", justify="center", width=7)
    t.add_column("Baseline", justify="right", width=12)
    t.add_column("Threshold", justify="right", width=10)
    t.add_column("Last Scan", width=12)

    for item in items:
        active = "[green]yes[/green]" if item.get("active") else "[red]no[/red]"
        baseline = item.get("baseline") or {}
        price = f"${baseline.get('price', 0):.2f}" if baseline else "—"
        last_scan = (item.get("last_scan_at") or "—")[:10]
        t.add_row(
            item.get("id", ""),
            item.get("label", ""),
            item.get("mode", "vendor"),
            active,
            price,
            f"{item.get('threshold_pct', 5.0):.1f}%",
            last_scan,
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Command: alerts
# ---------------------------------------------------------------------------


def cmd_alerts(args: argparse.Namespace) -> None:
    params = {}
    if args.status:
        params["status"] = args.status

    data = _get(args.url, "/alerts", params=params or None)
    alerts = data if isinstance(data, list) else []

    label = f"Alerts" + (f" [{args.status}]" if args.status else "")
    console.print(Rule(f"[bold]{label}[/bold]", style="dim"))

    if not alerts:
        console.print("[dim]No alerts found.[/dim]")
        return

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    t.add_column("ID", width=42)
    t.add_column("Watch", width=20)
    t.add_column("Status", width=12)
    t.add_column("Savings", justify="right", width=9)
    t.add_column("Summary")

    for alert in alerts:
        status = alert.get("status", "new")
        style = STATUS_STYLE.get(status, "white")
        icon = ALERT_ICON.get(status, status.upper())
        delta = alert.get("delta_pct", 0.0)
        t.add_row(
            alert.get("id", ""),
            alert.get("watch_id", ""),
            Text(icon, style=style),
            f"{delta:.1f}%",
            (alert.get("summary") or "")[:60],
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Command: findings
# ---------------------------------------------------------------------------


def cmd_findings(args: argparse.Namespace) -> None:
    data = _get(args.url, "/findings")
    findings = data if isinstance(data, list) else []

    console.print(Rule("[bold]Findings[/bold]", style="dim"))

    if not findings:
        console.print("[dim]No findings recorded yet.[/dim]")
        return

    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    t.add_column("Label", width=28)
    t.add_column("Scanned", width=11)
    t.add_column("Baseline", justify="right", width=10)
    t.add_column("Best Price", justify="right", width=10)
    t.add_column("Supplier", width=20)
    t.add_column("Savings", justify="right", width=9)
    t.add_column("Confidence", width=10)

    for f in findings:
        baseline = f.get("baseline") or {}
        best = f.get("best_option") or {}
        baseline_price = f"${baseline.get('price', 0):.2f}" if baseline else "—"
        best_price = f"${best.get('price', 0):.2f}" if best else "—"
        delta = f.get("delta_pct", 0.0)
        delta_str = f"{delta:+.1f}%"
        delta_style = "green" if delta >= 5 else ("yellow" if delta > 0 else "dim")
        conf = f.get("confidence", "medium")
        t.add_row(
            f.get("label", "—"),
            (f.get("scanned_at") or "—")[:10],
            baseline_price,
            best_price,
            best.get("supplier", "—"),
            Text(delta_str, style=delta_style),
            Text(conf, style=CONFIDENCE_STYLE.get(conf, "white")),
        )

    console.print(t)


# ---------------------------------------------------------------------------
# Command: summary
# ---------------------------------------------------------------------------


def cmd_summary(args: argparse.Namespace) -> None:
    data = _get(args.url, "/summary")

    watch = data.get("watch_items", {})
    alerts_info = data.get("alerts", {})
    findings_info = data.get("findings", {})

    lines = [
        f"Watch items:  [bold]{watch.get('active', 0)}[/bold] active / {watch.get('total', 0)} total",
        f"Alerts:       [bold yellow]{alerts_info.get('new', 0)}[/bold yellow] new / {alerts_info.get('total', 0)} total",
        f"Findings:     {findings_info.get('total', 0)} recorded",
    ]

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]PriceScout Summary[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="price-scout",
        description="PriceScout CLI — monitor supplier prices for your business",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"PriceScout API base URL (default: {DEFAULT_URL})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = subparsers.add_parser("scan", help="Run a full price scan and show the report")
    p_scan.add_argument("--business", required=True, help="Business name")
    p_scan.add_argument("--location", required=True, help="City/state, e.g. 'Austin, TX'")
    p_scan.set_defaults(func=cmd_scan)

    # watchlist
    p_wl = subparsers.add_parser("watchlist", help="List all watch items")
    p_wl.set_defaults(func=cmd_watchlist)

    # alerts
    p_al = subparsers.add_parser("alerts", help="List alerts")
    p_al.add_argument("--status", choices=["new", "acknowledged"], help="Filter by status")
    p_al.set_defaults(func=cmd_alerts)

    # findings
    p_fi = subparsers.add_parser("findings", help="List all findings")
    p_fi.set_defaults(func=cmd_findings)

    # summary
    p_su = subparsers.add_parser("summary", help="Show high-level summary counts")
    p_su.set_defaults(func=cmd_summary)

    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
