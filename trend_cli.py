"""
Pretty-print CLI for the Trend Analyst Agent.

Usage:
    python cli.py --business "Mike's Hardware" --location "Austin, TX" --categories "power tools" "gardening"
    python cli.py --business "Mike's Hardware" --location "Austin, TX" --categories "power tools" --show-sources
"""

from __future__ import annotations

import argparse
import sys

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich import box
from rich.text import Text

load_dotenv()

console = Console()

STATUS_STYLE = {
    "trending": "bold green",
    "stable": "bold yellow",
    "fading": "bold red",
}

STATUS_ICON = {
    "trending": "▲ TRENDING",
    "stable": "● STABLE",
    "fading": "▼ FADING",
}

ACTION_STYLE = {
    "stock":    "green",
    "increase": "cyan",
    "reduce":   "yellow",
    "drop":     "red",
}

DIRECTION_STYLE = {
    "trending": "bold green",
    "stable":   "bold yellow",
    "fading":   "bold red",
}


def show_sources(location: str, categories: list[str], lookback: int) -> None:
    """Fetch and display raw data from each source before the agent runs."""
    from trend_agent.tools.google_trends import get_google_trends
    from trend_agent.tools.reddit_trends import get_reddit_trends
    from trend_agent.tools.local_events import get_local_events
    from trend_agent.tools.sales_history import get_sales_history

    console.print(Rule("[bold]Live Data Sources[/bold]", style="dim"))
    console.print()

    for category in categories:
        console.print(f"[bold cyan]── {category.upper()} ──[/bold cyan]\n")

        # Google Trends
        with console.status(f"  Fetching Google Trends for '{category}'..."):
            gt = get_google_trends(category, location, lookback)

        direction_style = DIRECTION_STYLE.get(gt.direction.value, "white")
        change_color = "green" if gt.change_pct >= 0 else "red"
        sign = "+" if gt.change_pct >= 0 else ""

        gt_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        gt_table.add_column("Key", style="dim", width=22)
        gt_table.add_column("Value")
        gt_table.add_row("Source", "[bold]Google Trends[/bold]  (pytrends — live)")
        gt_table.add_row("Keyword", gt.keyword)
        gt_table.add_row("Region", gt.geo)
        gt_table.add_row("Timeframe", gt.timeframe)
        gt_table.add_row("Direction", Text(gt.direction.value.upper(), style=direction_style))
        gt_table.add_row("Change", Text(f"{sign}{gt.change_pct}%", style=change_color))
        gt_table.add_row("Peak interest", str(gt.peak_interest))
        gt_table.add_row("Current interest", str(gt.current_interest))
        gt_table.add_row("Data points", str(len(gt.data_points)))
        console.print(gt_table)

        # Reddit
        with console.status(f"  Fetching Reddit signals for '{category}'..."):
            reddit = get_reddit_trends(category, category)

        reddit_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
        reddit_table.add_column("Subreddit", width=20)
        reddit_table.add_column("Post title")
        reddit_table.add_column("Score", justify="right", width=8)
        reddit_table.add_column("Comments", justify="right", width=10)

        source_label = "Reddit API (PRAW — live)" if "mock" not in reddit.sentiment_summary.lower() else "Reddit (mock — add credentials to .env)"
        console.print(f"  [bold]Reddit[/bold]  [dim]{source_label}[/dim]")
        for post in reddit.top_posts:
            reddit_table.add_row(
                f"r/{post.subreddit}",
                post.post_title[:60] + ("…" if len(post.post_title) > 60 else ""),
                str(post.score),
                str(post.num_comments),
            )
        console.print(reddit_table)

        # Local Events (shown once per location, not per category)
        if category == categories[0]:
            with console.status(f"  Fetching local events in {location}..."):
                events = get_local_events(location, category)

            import os
            source_label = "Ticketmaster Discovery API — live" if os.getenv("TICKETMASTER_API_KEY") else "Mock (add TICKETMASTER_API_KEY to .env)"
            console.print(f"  [bold]Local Events[/bold]  [dim]{source_label}[/dim]")
            evt_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
            evt_table.add_column("Event", width=40)
            evt_table.add_column("Date", width=12)
            evt_table.add_column("Venue")
            for e in events.events:
                evt_table.add_row(
                    e.name[:38] + ("…" if len(e.name) > 38 else ""),
                    e.date,
                    e.venue or "—",
                )
            console.print(evt_table)

        # Sales History
        with console.status(f"  Querying sales history for '{category}'..."):
            sales = get_sales_history(category, lookback)

        console.print(f"  [bold]Sales History[/bold]  [dim]SQLite DB — {sales.period_start} → {sales.period_end}[/dim]")
        sales_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
        sales_table.add_column("SKU", width=10)
        sales_table.add_column("Product")
        sales_table.add_column("Units", justify="right", width=8)
        sales_table.add_column("Revenue", justify="right", width=12)

        if sales.top_skus:
            for sku in sales.top_skus:
                sales_table.add_row(sku.sku, sku.product_name, str(sku.quantity_sold), f"${sku.revenue:,.2f}")
        else:
            sales_table.add_row("—", "No sales recorded in this period", "0", "$0.00")

        console.print(sales_table)
        console.print(f"  [dim]Total: {sales.total_units} units  |  ${sales.total_revenue:,.2f} revenue[/dim]\n")

    console.print(Rule("[bold]Agent Synthesis[/bold]", style="dim"))
    console.print()


def run(business: str, location: str, categories: list[str], lookback: int, url: str, store_url: str | None, sources: bool) -> None:
    console.print(f"\n[bold]Analyzing trends for [cyan]{business}[/cyan] in [cyan]{location}[/cyan]...[/bold]\n")

    if sources:
        show_sources(location, categories, lookback)

    payload: dict = {
        "business_name": business,
        "location": location,
        "categories": categories,
        "lookback_days": lookback,
    }
    if store_url:
        payload["store_url"] = store_url
        console.print(f"[dim]Scraping store catalog from {store_url}...[/dim]\n")

    with console.status("[bold green]Agent is synthesizing signals...[/bold green]"):
        try:
            resp = httpx.post(
                f"{url}/analyze",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
        except httpx.ConnectError:
            console.print("[bold red]Could not connect to API server.[/bold red] Is it running?\n  .venv/bin/uvicorn api.main:app --port 8000")
            sys.exit(1)

    data = resp.json()

    # Executive summary
    console.print(Panel(
        data["executive_summary"],
        title="[bold]Executive Summary[/bold]",
        border_style="blue",
        padding=(1, 2),
    ))
    console.print()

    # Per-category breakdown
    for cat in data["categories"]:
        status = cat["status"]
        style = STATUS_STYLE.get(status, "white")
        label = STATUS_ICON.get(status, status.upper())

        warning = "  [bold red][!] End-of-trend warning[/bold red]" if cat.get("end_of_trend_warning") else ""
        confidence_pct = f"{int(cat['confidence'] * 100)}%"

        title = Text()
        title.append(cat["name"].upper(), style="bold white")
        title.append("   ")
        title.append(label, style=style)
        title.append(f"   confidence: {confidence_pct}", style="dim")
        title.append(warning)

        signals_text = "\n".join(f"  • {s}" for s in cat["signals"])

        rec_table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
        rec_table.add_column("Action", style="bold", width=10)
        rec_table.add_column("Product")
        rec_table.add_column("Type", width=8)
        rec_table.add_column("Reason", style="dim")
        rec_table.add_column("Confidence", justify="right", width=11)

        for r in cat["recommendations"]:
            action = r["action"].upper()
            action_style = ACTION_STYLE.get(r["action"], "white")
            is_existing = r.get("is_existing_product", False)
            product_type = Text("existing", style="dim") if is_existing else Text("new", style="bold magenta")
            rec_table.add_row(
                Text(action, style=action_style),
                r["product_name"],
                product_type,
                r["reason"],
                f"{int(r['confidence'] * 100)}%",
            )

        console.print(Panel(
            f"[bold]Signals[/bold]\n{signals_text}\n\n[bold]Recommendations[/bold]",
            title=title,
            border_style=style,
            padding=(1, 2),
        ))
        console.print(rec_table)
        console.print()

    console.print(f"[dim]Analysis date: {data['analysis_date']}[/dim]\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trend Analyst Agent CLI")
    parser.add_argument("--business",      required=True,       help="Business name")
    parser.add_argument("--location",      required=True,       help="City/state, e.g. 'Austin, TX'")
    parser.add_argument("--categories",    required=True,       nargs="+", help="Product categories to analyze")
    parser.add_argument("--lookback",      default=90,          type=int, help="Days of sales history (default 90)")
    parser.add_argument("--url",           default="http://127.0.0.1:8001", help="Trend API base URL (default: http://127.0.0.1:8001)")
    parser.add_argument("--store-url",     default=None, help="Store website URL to scrape current product catalog")
    parser.add_argument("--show-sources",  action="store_true", help="Show raw data from each source before the report")
    return parser


if __name__ == "__main__":
    _parser = build_parser()
    _args = _parser.parse_args()
    run(_args.business, _args.location, _args.categories, _args.lookback, _args.url, _args.store_url, _args.show_sources)
