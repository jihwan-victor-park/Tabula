from __future__ import annotations

import argparse
import json
from typing import Any

from clawbot.agents.price_discovery_agent import PriceDiscoveryAgent
from clawbot.api.server import serve


JsonDict = dict[str, Any]


def parse_candidate(value: str) -> JsonDict:
    parts = value.split("|")
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(
            "Candidate must be 'supplier|price|optional-url'."
        )
    supplier = parts[0].strip()
    try:
        price = float(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Candidate price must be numeric.") from exc
    url = parts[2].strip() if len(parts) > 2 else None
    return {"supplier": supplier, "price": price, "url": url}


def print_json(payload: JsonDict) -> None:
    print(json.dumps(payload, indent=2))


def cmd_list_watch(_: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(agent.list_watch())
    return 0


def cmd_add_watch(args: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(
        agent.add_watch(
            watch_id=args.watch_id,
            label=args.label,
            mode=args.mode,
            region=args.region,
            query=args.query,
            supplier=args.supplier,
            price=args.price,
            currency=args.currency,
            unit=args.unit,
            quantity=args.quantity,
            threshold_pct=args.threshold_pct,
            notes=args.notes,
            last_verified_at=args.last_verified_at,
            active=args.active,
        )
    )
    return 0


def cmd_set_watch_status(args: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(agent.set_watch_status(args.watch_id, args.active))
    return 0


def cmd_list_alerts(args: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(agent.list_alerts(status=args.status))
    return 0


def cmd_ack_alert(args: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(agent.acknowledge_alert(args.alert_id))
    return 0


def cmd_list_findings(_: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(agent.list_findings())
    return 0


def cmd_record_scan(args: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(
        agent.record_scan(
            watch_id=args.watch_id,
            supplier=args.supplier,
            price=args.price,
            url=args.url,
            notes=args.notes,
            confidence=args.confidence,
            candidates=args.candidate,
            scanned_at=args.scanned_at,
        )
    )
    return 0


def cmd_summary(_: argparse.Namespace, agent: PriceDiscoveryAgent) -> int:
    print_json(agent.summary())
    return 0


def cmd_serve_api(args: argparse.Namespace, _: PriceDiscoveryAgent) -> int:
    serve(
        host=args.host,
        port=args.port,
        watch_recipients=args.watch_recipient or [],
        forward_url=args.forward_url,
        business_name=args.business_name,
        business_location=args.business_location,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PriceScout hackathon CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_watch = subparsers.add_parser("list-watch", help="Print the current watchlist.")
    list_watch.set_defaults(func=cmd_list_watch)

    add_watch = subparsers.add_parser("add-watch", help="Add or replace a watch item.")
    add_watch.add_argument("--watch-id", required=True)
    add_watch.add_argument("--label", required=True)
    add_watch.add_argument("--mode", choices=["vendor", "competitor"], default="vendor")
    add_watch.add_argument("--region", required=True)
    add_watch.add_argument("--query", required=True)
    add_watch.add_argument("--supplier", required=True)
    add_watch.add_argument("--price", required=True, type=float)
    add_watch.add_argument("--currency", default="USD")
    add_watch.add_argument("--unit", default="per unit")
    add_watch.add_argument("--quantity", required=True, type=int)
    add_watch.add_argument("--threshold-pct", default=5.0, type=float)
    add_watch.add_argument("--last-verified-at")
    add_watch.add_argument("--notes")
    add_watch.add_argument("--active", action="store_true")
    add_watch.set_defaults(func=cmd_add_watch)

    activate = subparsers.add_parser("activate-watch", help="Activate a watch item.")
    activate.add_argument("--watch-id", required=True)
    activate.set_defaults(
        func=lambda args, agent: cmd_set_watch_status(
            argparse.Namespace(watch_id=args.watch_id, active=True),
            agent,
        )
    )

    deactivate = subparsers.add_parser("deactivate-watch", help="Deactivate a watch item.")
    deactivate.add_argument("--watch-id", required=True)
    deactivate.set_defaults(
        func=lambda args, agent: cmd_set_watch_status(
            argparse.Namespace(watch_id=args.watch_id, active=False),
            agent,
        )
    )

    list_alerts = subparsers.add_parser("list-alerts", help="Print alerts.")
    list_alerts.add_argument("--status", choices=["new", "acknowledged"])
    list_alerts.set_defaults(func=cmd_list_alerts)

    ack_alert = subparsers.add_parser("ack-alert", help="Acknowledge an alert.")
    ack_alert.add_argument("--alert-id", required=True)
    ack_alert.set_defaults(func=cmd_ack_alert)

    list_findings = subparsers.add_parser("list-findings", help="Print stored findings.")
    list_findings.set_defaults(func=cmd_list_findings)

    record_scan = subparsers.add_parser(
        "record-scan",
        help="Record a discovered market result and generate an alert if warranted.",
    )
    record_scan.add_argument("--watch-id", required=True)
    record_scan.add_argument("--supplier", required=True)
    record_scan.add_argument("--price", required=True, type=float)
    record_scan.add_argument("--url")
    record_scan.add_argument("--notes")
    record_scan.add_argument("--confidence", default="medium")
    record_scan.add_argument("--candidate", action="append", type=parse_candidate)
    record_scan.add_argument("--scanned-at")
    record_scan.set_defaults(func=cmd_record_scan)

    summary = subparsers.add_parser("summary", help="Print a simple operating summary.")
    summary.set_defaults(func=cmd_summary)

    serve_api = subparsers.add_parser("serve-api", help="Run the local demo API server.")
    serve_api.add_argument("--host", default="127.0.0.1")
    serve_api.add_argument("--port", default=8007, type=int)
    serve_api.add_argument(
        "--watch-recipient",
        action="append",
        metavar="PHONE",
        help="iMessage number to watch for inbound replies (repeatable).",
    )
    serve_api.add_argument(
        "--forward-url",
        default="http://localhost:8006/ask",
        help="URL to POST inbound messages to (default: universal agent).",
    )
    serve_api.add_argument("--business-name", default="My Store")
    serve_api.add_argument("--business-location", default="US")
    serve_api.set_defaults(func=cmd_serve_api)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    agent = PriceDiscoveryAgent()
    return args.func(args, agent)


if __name__ == "__main__":
    raise SystemExit(main())
