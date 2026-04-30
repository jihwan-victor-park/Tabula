from __future__ import annotations

from typing import Any

from clawbot.tools.price_discovery_tool import PriceScoutRepository


JsonDict = dict[str, Any]


def build_daily_summary(repository: PriceScoutRepository | None = None) -> JsonDict:
    repo = repository or PriceScoutRepository()
    watch_items = repo.list_watch_items()
    alerts = repo.list_alerts()
    findings = repo.load_findings()["items"]

    return {
        "watchItems": {
            "total": len(watch_items),
            "active": len([item for item in watch_items if item.get("active")]),
        },
        "alerts": {
            "total": len(alerts),
            "new": len([item for item in alerts if item.get("status") == "new"]),
            "acknowledged": len(
                [item for item in alerts if item.get("status") == "acknowledged"]
            ),
        },
        "findings": {
            "total": len(findings),
        },
    }
