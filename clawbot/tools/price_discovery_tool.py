from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawbot.config.settings import AppPaths, get_paths
from clawbot.tools.json_store import load_json, save_json, utc_now


JsonDict = dict[str, Any]


@dataclass
class PriceScoutRepository:
    paths: AppPaths | None = None

    def __post_init__(self) -> None:
        if self.paths is None:
            self.paths = get_paths()

    def load_settings(self) -> JsonDict:
        assert self.paths is not None
        return load_json(
            self.paths.settings_path,
            {
                "version": 1,
                "owner": {},
                "monitoring": {
                    "enabled": False,
                    "defaultSavingsThresholdPct": 5,
                    "maxItemsPerRun": 1,
                    "minHoursBetweenAlerts": 24,
                    "maxFindingAgeHours": 168,
                },
            },
        )

    def load_watchlist(self) -> JsonDict:
        assert self.paths is not None
        return load_json(self.paths.watchlist_path, {"version": 1, "items": []})

    def save_watchlist(self, payload: JsonDict) -> None:
        assert self.paths is not None
        save_json(self.paths.watchlist_path, payload)

    def list_watch_items(self, active_only: bool = False) -> list[JsonDict]:
        items = self.load_watchlist()["items"]
        if active_only:
            return [item for item in items if item.get("active")]
        return items

    def get_watch_item(self, watch_id: str) -> JsonDict:
        for item in self.list_watch_items():
            if item.get("id") == watch_id:
                return item
        raise KeyError(f"Unknown watch id: {watch_id}")

    def upsert_watch_item(self, item: JsonDict) -> JsonDict:
        payload = self.load_watchlist()
        payload["items"] = [
            existing for existing in payload["items"] if existing.get("id") != item.get("id")
        ]
        payload["items"].append(item)
        self.save_watchlist(payload)
        return item

    def set_watch_status(self, watch_id: str, active: bool) -> JsonDict:
        payload = self.load_watchlist()
        for item in payload["items"]:
            if item.get("id") == watch_id:
                item["active"] = active
                self.save_watchlist(payload)
                return item
        raise KeyError(f"Unknown watch id: {watch_id}")

    def touch_watch_item(
        self,
        watch_id: str,
        *,
        last_scan_at: str | None = None,
        last_alert_at: str | None = None,
    ) -> JsonDict:
        payload = self.load_watchlist()
        for item in payload["items"]:
            if item.get("id") == watch_id:
                if last_scan_at is not None:
                    item["lastScanAt"] = last_scan_at
                if last_alert_at is not None:
                    item["lastAlertAt"] = last_alert_at
                self.save_watchlist(payload)
                return item
        raise KeyError(f"Unknown watch id: {watch_id}")

    def load_findings(self) -> JsonDict:
        assert self.paths is not None
        return load_json(self.paths.findings_path, {"version": 1, "items": []})

    def save_findings(self, payload: JsonDict) -> None:
        assert self.paths is not None
        save_json(self.paths.findings_path, payload)

    def upsert_finding(self, finding: JsonDict) -> JsonDict:
        payload = self.load_findings()
        payload["items"] = [
            existing
            for existing in payload["items"]
            if existing.get("watchId") != finding.get("watchId")
        ]
        payload["items"].append(finding)
        self.save_findings(payload)
        return finding

    def load_alerts(self) -> JsonDict:
        assert self.paths is not None
        return load_json(self.paths.alerts_path, {"version": 1, "items": []})

    def save_alerts(self, payload: JsonDict) -> None:
        assert self.paths is not None
        save_json(self.paths.alerts_path, payload)

    def list_alerts(self, status: str | None = None) -> list[JsonDict]:
        items = self.load_alerts()["items"]
        if status is None:
            return items
        return [item for item in items if item.get("status") == status]

    def append_alert(self, alert: JsonDict) -> JsonDict:
        payload = self.load_alerts()
        payload["items"].append(alert)
        self.save_alerts(payload)
        return alert

    def acknowledge_alert(self, alert_id: str) -> JsonDict:
        payload = self.load_alerts()
        for item in payload["items"]:
            if item.get("id") == alert_id:
                item["status"] = "acknowledged"
                item["acknowledgedAt"] = utc_now()
                self.save_alerts(payload)
                return item
        raise KeyError(f"Unknown alert id: {alert_id}")
