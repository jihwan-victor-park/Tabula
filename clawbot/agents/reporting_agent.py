from __future__ import annotations

from typing import Any


JsonDict = dict[str, Any]


def format_alert_message(alert: JsonDict) -> str:
    baseline = alert["baseline"]
    option = alert["bestOption"]
    return (
        "Bottom line: better price found.\n"
        f"- Item: {alert['watchId']}\n"
        f"- Baseline: {baseline['supplier']} at {baseline['price']} {baseline['currency']} {baseline['unit']}\n"
        f"- Best option: {option['supplier']} at {option['price']} {option['currency']} {option['unit']}\n"
        f"- Savings: {alert['deltaPct']}%\n"
        "Recommendation: refresh the shortlist and verify MOQ, freight, and lead time."
    )


def format_daily_summary(summary: JsonDict) -> str:
    return (
        "Bottom line: PriceScout status snapshot.\n"
        f"- Watch items: {summary['watchItems']['active']} active / {summary['watchItems']['total']} total\n"
        f"- Alerts: {summary['alerts']['new']} new / {summary['alerts']['total']} total\n"
        f"- Findings: {summary['findings']['total']} tracked\n"
        "Recommendation: review any new alerts first."
    )
