from __future__ import annotations

from typing import Any

from clawbot.agents.reporting_agent import format_alert_message, format_daily_summary
from clawbot.memory.session_memory import SessionMemory
from clawbot.tools.json_store import utc_now
from clawbot.tools.price_discovery_tool import PriceScoutRepository
from clawbot.workflows.daily_ops import build_daily_summary
from clawbot.workflows.watch_monitor import ScanInput, WatchMonitorWorkflow


JsonDict = dict[str, Any]


class PriceDiscoveryAgent:
    def __init__(self, repository: PriceScoutRepository | None = None) -> None:
        self.repository = repository or PriceScoutRepository()
        self.memory = SessionMemory(self.repository.paths)
        self.watch_monitor = WatchMonitorWorkflow(self.repository)

    def list_watch(self) -> JsonDict:
        return self.repository.load_watchlist()

    def add_watch(
        self,
        *,
        watch_id: str,
        label: str,
        mode: str,
        region: str,
        query: str,
        supplier: str,
        price: float,
        currency: str,
        unit: str,
        quantity: int,
        threshold_pct: float,
        notes: str | None,
        last_verified_at: str | None,
        active: bool,
    ) -> JsonDict:
        item = {
            "id": watch_id,
            "label": label,
            "mode": mode,
            "active": active,
            "region": region,
            "query": query,
            "notes": notes or "",
            "baseline": {
                "supplier": supplier,
                "price": price,
                "currency": currency,
                "unit": unit,
                "quantity": quantity,
                "lastVerifiedAt": last_verified_at,
            },
            "thresholdPct": threshold_pct,
            "lastScanAt": None,
            "lastAlertAt": None,
        }
        self.memory.append_note(f"Updated watch item {watch_id}.")
        return self.repository.upsert_watch_item(item)

    def set_watch_status(self, watch_id: str, active: bool) -> JsonDict:
        self.memory.append_note(
            f"{'Activated' if active else 'Deactivated'} watch item {watch_id}."
        )
        return self.repository.set_watch_status(watch_id, active)

    def list_alerts(self, status: str | None = None) -> JsonDict:
        return {"version": 1, "items": self.repository.list_alerts(status=status)}

    def list_findings(self) -> JsonDict:
        return self.repository.load_findings()

    def acknowledge_alert(self, alert_id: str) -> JsonDict:
        self.memory.append_note(f"Acknowledged alert {alert_id}.")
        return self.repository.acknowledge_alert(alert_id)

    def record_scan(
        self,
        *,
        watch_id: str,
        supplier: str,
        price: float,
        url: str | None,
        notes: str | None,
        confidence: str,
        candidates: list[JsonDict] | None = None,
        scanned_at: str | None = None,
    ) -> JsonDict:
        result = self.watch_monitor.process_scan(
            ScanInput(
                watch_id=watch_id,
                supplier=supplier,
                price=price,
                url=url,
                notes=notes,
                confidence=confidence,
                candidates=candidates,
                scanned_at=scanned_at,
            )
        )
        self.memory.append_note(
            f"Recorded scan for {watch_id} at {utc_now()} with supplier {supplier}."
        )
        if result["alert"]:
            result["alertMessage"] = format_alert_message(result["alert"])
        return result

    def summary(self) -> JsonDict:
        summary = build_daily_summary(self.repository)
        return {"summary": summary, "message": format_daily_summary(summary)}
