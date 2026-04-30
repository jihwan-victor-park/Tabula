"""
MongoDB repository for PriceScout — watchlist, findings, and alerts.

Collections (database: $MONGODB_DB, default "clawbot"):
  price_watchlist — items being monitored for price changes
  price_findings  — price scan results
  price_alerts    — triggered savings alerts
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING

from clawbot.schemas.price import Alert, Baseline, BestOption, Finding, WatchItem
from clawbot.tools.mongodb import get_col


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _doc_to_watch_item(doc: dict) -> WatchItem:
    baseline = None
    b = doc.get("baseline")
    if b:
        baseline = Baseline(
            supplier=b.get("supplier", ""),
            price=b.get("price", 0.0),
            currency=b.get("currency", "USD"),
            unit=b.get("unit"),
            quantity=b.get("quantity"),
            last_verified_at=b.get("last_verified_at"),
        )
    return WatchItem(
        id=doc["_id"],
        label=doc["label"],
        mode=doc.get("mode", "vendor"),
        active=doc.get("active", True),
        region=doc.get("region"),
        query=doc.get("query"),
        notes=doc.get("notes"),
        baseline=baseline,
        threshold_pct=doc.get("threshold_pct", 5.0),
        last_scan_at=doc.get("last_scan_at"),
        last_alert_at=doc.get("last_alert_at"),
    )


def _doc_to_finding(doc: dict) -> Finding:
    b = doc.get("baseline")
    baseline = Baseline(supplier=b["supplier"], price=b.get("price", 0.0)) if b else None
    bo = doc.get("best_option")
    best_option = BestOption(
        supplier=bo["supplier"],
        price=bo.get("price", 0.0),
        currency=bo.get("currency", "USD"),
        unit=bo.get("unit"),
        url=bo.get("url"),
    ) if bo else None
    return Finding(
        id=doc["_id"],
        watch_id=doc["watch_id"],
        product_name=doc.get("product_name", ""),
        label=doc.get("label", ""),
        scanned_at=doc.get("scanned_at", _utc_now()),
        scraped_price=doc.get("scraped_price"),
        baseline=baseline,
        best_option=best_option,
        candidates=doc.get("candidates", []),
        confidence=doc.get("confidence", "medium"),
        notes=doc.get("notes"),
        delta_pct=doc.get("delta_pct", 0.0),
    )


def _doc_to_alert(doc: dict) -> Alert:
    b = doc.get("baseline")
    baseline = Baseline(supplier=b["supplier"], price=b.get("price", 0.0)) if b else None
    bo = doc.get("best_option")
    best_option = BestOption(supplier=bo["supplier"], price=bo.get("price", 0.0)) if bo else None
    return Alert(
        id=doc["_id"],
        watch_id=doc["watch_id"],
        status=doc.get("status", "new"),
        created_at=doc.get("created_at", _utc_now()),
        acknowledged_at=doc.get("acknowledged_at"),
        summary=doc.get("summary", ""),
        baseline=baseline,
        best_option=best_option,
        delta_pct=doc.get("delta_pct", 0.0),
        notes=doc.get("notes"),
    )


# ---------------------------------------------------------------------------
# Schema bootstrap (indexes)
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create indexes on price collections."""
    get_col("price_watchlist").create_index([("label", ASCENDING)])
    get_col("price_watchlist").create_index([("active", ASCENDING)])
    get_col("price_findings").create_index([("watch_id", ASCENDING)])
    get_col("price_findings").create_index([("scanned_at", DESCENDING)])
    get_col("price_alerts").create_index([("watch_id", ASCENDING)])
    get_col("price_alerts").create_index([("status", ASCENDING)])
    get_col("price_alerts").create_index([("created_at", DESCENDING)])


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------


def list_watch_items(active_only: bool = False) -> list[WatchItem]:
    query: dict[str, Any] = {"active": True} if active_only else {}
    docs = get_col("price_watchlist").find(query).sort("label", ASCENDING)
    return [_doc_to_watch_item(d) for d in docs]


def get_watch_item(watch_id: str) -> WatchItem:
    doc = get_col("price_watchlist").find_one({"_id": watch_id})
    if doc is None:
        raise KeyError(f"Unknown watch id: {watch_id}")
    return _doc_to_watch_item(doc)


def upsert_watch_item(item: WatchItem) -> WatchItem:
    b = item.baseline
    doc: dict[str, Any] = {
        "_id": item.id,
        "label": item.label,
        "mode": item.mode,
        "active": item.active,
        "region": item.region,
        "query": item.query,
        "notes": item.notes,
        "threshold_pct": item.threshold_pct,
        "last_scan_at": item.last_scan_at,
        "last_alert_at": item.last_alert_at,
    }
    if b:
        doc["baseline"] = {
            "supplier": b.supplier,
            "price": b.price,
            "currency": b.currency,
            "unit": b.unit,
            "quantity": b.quantity,
            "last_verified_at": b.last_verified_at,
        }
    get_col("price_watchlist").replace_one({"_id": item.id}, doc, upsert=True)
    return get_watch_item(item.id)


def set_watch_status(watch_id: str, active: bool) -> WatchItem:
    result = get_col("price_watchlist").update_one(
        {"_id": watch_id}, {"$set": {"active": active}}
    )
    if result.matched_count == 0:
        raise KeyError(f"Unknown watch id: {watch_id}")
    return get_watch_item(watch_id)


def touch_watch_item(
    watch_id: str,
    last_scan_at: str | None = None,
    last_alert_at: str | None = None,
) -> WatchItem:
    updates: dict[str, Any] = {}
    if last_scan_at is not None:
        updates["last_scan_at"] = last_scan_at
    if last_alert_at is not None:
        updates["last_alert_at"] = last_alert_at
    if updates:
        get_col("price_watchlist").update_one({"_id": watch_id}, {"$set": updates})
    return get_watch_item(watch_id)


# ---------------------------------------------------------------------------
# Findings CRUD
# ---------------------------------------------------------------------------


def upsert_finding(finding: Finding) -> Finding:
    b = finding.baseline
    bo = finding.best_option
    doc: dict[str, Any] = {
        "_id": finding.id,
        "watch_id": finding.watch_id,
        "product_name": finding.product_name,
        "label": finding.label,
        "scanned_at": finding.scanned_at,
        "scraped_price": finding.scraped_price,
        "candidates": finding.candidates,
        "confidence": finding.confidence,
        "notes": finding.notes,
        "delta_pct": finding.delta_pct,
    }
    if b:
        doc["baseline"] = {"supplier": b.supplier, "price": b.price}
    if bo:
        doc["best_option"] = {
            "supplier": bo.supplier,
            "price": bo.price,
            "currency": bo.currency,
            "unit": bo.unit,
            "url": bo.url,
        }
    get_col("price_findings").replace_one({"_id": finding.id}, doc, upsert=True)
    return finding


def list_findings(watch_id: str | None = None) -> list[Finding]:
    query: dict[str, Any] = {"watch_id": watch_id} if watch_id else {}
    docs = get_col("price_findings").find(query).sort("scanned_at", DESCENDING)
    return [_doc_to_finding(d) for d in docs]


# ---------------------------------------------------------------------------
# Alerts CRUD
# ---------------------------------------------------------------------------


def append_alert(alert: Alert) -> Alert:
    b = alert.baseline
    bo = alert.best_option
    doc: dict[str, Any] = {
        "_id": alert.id,
        "watch_id": alert.watch_id,
        "status": alert.status,
        "created_at": alert.created_at,
        "acknowledged_at": alert.acknowledged_at,
        "summary": alert.summary,
        "delta_pct": alert.delta_pct,
        "notes": alert.notes,
    }
    if b:
        doc["baseline"] = {"supplier": b.supplier, "price": b.price}
    if bo:
        doc["best_option"] = {"supplier": bo.supplier, "price": bo.price}
    # insert_one with ignore on duplicate key
    try:
        get_col("price_alerts").insert_one(doc)
    except Exception:
        pass  # duplicate — already recorded
    return alert


def list_alerts(status: str | None = None) -> list[Alert]:
    query: dict[str, Any] = {"status": status} if status else {}
    docs = get_col("price_alerts").find(query).sort("created_at", DESCENDING)
    return [_doc_to_alert(d) for d in docs]


def acknowledge_alert(alert_id: str) -> Alert:
    now = _utc_now()
    result = get_col("price_alerts").update_one(
        {"_id": alert_id},
        {"$set": {"status": "acknowledged", "acknowledged_at": now}},
    )
    if result.matched_count == 0:
        raise KeyError(f"Unknown alert id: {alert_id}")
    doc = get_col("price_alerts").find_one({"_id": alert_id})
    return _doc_to_alert(doc)
