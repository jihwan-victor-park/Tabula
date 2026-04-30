"""FastAPI app — exposes the PriceScout Agent as a REST API."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()  # load .env before anything else imports os.environ

from clawbot.agents.price_agent import run_price_agent
from clawbot.schemas.price import Alert, Finding, PriceReport, WatchItem
from clawbot.tools.db_price import (
    acknowledge_alert,
    init_db,
    list_alerts,
    list_findings,
    list_watch_items,
    set_watch_status,
    upsert_watch_item,
)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example → .env and fill it in."
        )
    init_db()
    yield


app = FastAPI(
    title="PriceScout API",
    description=(
        "Claude-powered agent that monitors supplier and competitor prices for small businesses. "
        "Compares market prices against configured baselines and triggers alerts on savings opportunities."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/live-session")
def live_session() -> dict:
    """Return the active Browserbase session URL, or null if no session is running."""
    from clawbot.tools.session_state import get_session
    session = get_session()
    return session if session else {"session_id": None, "live_view_url": None}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


@app.get("/watchlist", response_model=list[WatchItem], summary="List all watch items")
def get_watchlist() -> list[WatchItem]:
    """Return all watch items (active and inactive)."""
    return list_watch_items(active_only=False)


@app.post("/watchlist", response_model=WatchItem, summary="Add or update a watch item")
def post_watchlist(item: WatchItem) -> WatchItem:
    """Insert or replace a watch item. Uses item.id as the primary key."""
    try:
        return upsert_watch_item(item)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.patch(
    "/watchlist/{watch_id}/activate",
    response_model=WatchItem,
    summary="Activate a watch item",
)
def activate_watch(watch_id: str) -> WatchItem:
    try:
        return set_watch_status(watch_id, active=True)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Watch item not found: {watch_id}")


@app.patch(
    "/watchlist/{watch_id}/deactivate",
    response_model=WatchItem,
    summary="Deactivate a watch item",
)
def deactivate_watch(watch_id: str) -> WatchItem:
    try:
        return set_watch_status(watch_id, active=False)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Watch item not found: {watch_id}")


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@app.get("/findings", response_model=list[Finding], summary="List all findings")
def get_findings(watch_id: str | None = None) -> list[Finding]:
    """Return all recorded findings, optionally filtered by watch_id."""
    return list_findings(watch_id=watch_id)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@app.get("/alerts", response_model=list[Alert], summary="List alerts")
def get_alerts(status: str | None = None) -> list[Alert]:
    """Return alerts, optionally filtered by status ('new' or 'acknowledged')."""
    return list_alerts(status=status)


@app.patch(
    "/alerts/{alert_id}/acknowledge",
    response_model=Alert,
    summary="Acknowledge an alert",
)
def patch_acknowledge(alert_id: str) -> Alert:
    try:
        return acknowledge_alert(alert_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Alert not found: {alert_id}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@app.get("/summary", summary="Return high-level counts")
def get_summary() -> dict[str, Any]:
    """Return summary counts: active/total watch items, new/total alerts, total findings."""
    all_items = list_watch_items(active_only=False)
    active_items = [i for i in all_items if i.active]
    all_alerts = list_alerts()
    new_alerts = [a for a in all_alerts if a.status == "new"]
    all_findings = list_findings()
    return {
        "watch_items": {
            "active": len(active_items),
            "total": len(all_items),
        },
        "alerts": {
            "new": len(new_alerts),
            "total": len(all_alerts),
        },
        "findings": {
            "total": len(all_findings),
        },
    }


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


class ScanBody(BaseModel):
    business_name: str
    location: str


@app.post("/scan", response_model=PriceReport, summary="Run a full price scan")
def post_scan(body: ScanBody) -> PriceReport:
    """
    Run the PriceScout Agent for the given business and location.

    The agent will:
    - Retrieve all active watch items
    - Search market prices for each item
    - Record findings and trigger alerts where savings exceed thresholds
    - Return a structured PriceReport
    """
    try:
        return run_price_agent(
            business_name=body.business_name,
            location=body.location,
        )
    except KeyError as exc:
        raise HTTPException(status_code=500, detail=f"Missing configuration: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
