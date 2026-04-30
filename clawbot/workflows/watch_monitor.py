from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from clawbot.tools.json_store import utc_now
from clawbot.tools.price_discovery_tool import JsonDict, PriceScoutRepository


@dataclass
class ScanInput:
    watch_id: str
    supplier: str
    price: float
    url: str | None = None
    notes: str | None = None
    confidence: str = "medium"
    candidates: list[JsonDict] | None = None
    scanned_at: str | None = None


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def _hours_since(previous: str | None, current: str) -> float | None:
    previous_dt = _parse_utc(previous)
    current_dt = _parse_utc(current)
    if previous_dt is None or current_dt is None:
        return None
    return (current_dt - previous_dt) / timedelta(hours=1)


class WatchMonitorWorkflow:
    def __init__(self, repository: PriceScoutRepository | None = None) -> None:
        self.repository = repository or PriceScoutRepository()

    def process_scan(self, scan: ScanInput) -> JsonDict:
        scanned_at = scan.scanned_at or utc_now()
        settings = self.repository.load_settings()
        watch_item = self.repository.get_watch_item(scan.watch_id)

        baseline = float(watch_item["baseline"]["price"])
        threshold_pct = float(
            watch_item.get("thresholdPct")
            or settings["monitoring"]["defaultSavingsThresholdPct"]
        )
        savings_pct = ((baseline - scan.price) / baseline) * 100 if baseline else 0.0

        finding = {
            "id": f"finding-{scan.watch_id}",
            "watchId": scan.watch_id,
            "label": watch_item["label"],
            "scannedAt": scanned_at,
            "baseline": watch_item["baseline"],
            "bestOption": {
                "supplier": scan.supplier,
                "price": scan.price,
                "currency": watch_item["baseline"]["currency"],
                "unit": watch_item["baseline"]["unit"],
                "url": scan.url,
            },
            "candidates": scan.candidates or [],
            "confidence": scan.confidence,
            "notes": scan.notes or "",
            "deltaPct": round(savings_pct, 2),
        }
        self.repository.upsert_finding(finding)
        self.repository.touch_watch_item(scan.watch_id, last_scan_at=scanned_at)

        alert = None
        if savings_pct >= threshold_pct and self._cooldown_elapsed(
            watch_item.get("lastAlertAt"),
            scanned_at,
            settings["monitoring"]["minHoursBetweenAlerts"],
        ):
            alert = {
                "id": f"alert-{scan.watch_id}-{scanned_at.replace(':', '').replace('-', '')}",
                "watchId": scan.watch_id,
                "status": "new",
                "createdAt": scanned_at,
                "summary": (
                    f"{watch_item['label']}: {round(savings_pct, 2)}% below baseline "
                    f"with {scan.supplier} at {scan.price} {watch_item['baseline']['currency']} "
                    f"{watch_item['baseline']['unit']}."
                ),
                "baseline": watch_item["baseline"],
                "bestOption": finding["bestOption"],
                "deltaPct": round(savings_pct, 2),
                "notes": scan.notes or "",
            }
            self.repository.append_alert(alert)
            self.repository.touch_watch_item(scan.watch_id, last_alert_at=scanned_at)

        return {
            "watchItem": self.repository.get_watch_item(scan.watch_id),
            "finding": finding,
            "alert": alert,
        }

    def _cooldown_elapsed(
        self,
        previous_alert_at: str | None,
        current_time: str,
        minimum_hours_between_alerts: float,
    ) -> bool:
        hours_since = _hours_since(previous_alert_at, current_time)
        if hours_since is None:
            return True
        return hours_since >= minimum_hours_between_alerts
