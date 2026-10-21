"""
Square Sandbox verification — one command, after the Square settings are in the environment
(docs/SQUARE_SETUP.md §2) and a Sandbox seller was connected through the app once (Connections →
Connect Square). Calls the real Sandbox API; never prints tokens or secrets.

    set -a; source .env; set +a      # SQUARE_ENVIRONMENT=sandbox and the rest
    .venv/bin/python scripts/square_sandbox_check.py [--tenant <workspace id>]

Writes var/square_sandbox_report.json. Each check is pass / fail / skip with what was seen, so
docs/CHECKPOINTS.md can record "Sandbox verified" per item only for what actually passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clawbot.connectors.square import config as square_config  # noqa: E402
from clawbot.connectors.square import service as square  # noqa: E402
from clawbot.persistence.db import transaction  # noqa: E402
from clawbot.persistence.models import ConnectorAccount, ConnectorEvent, InventorySnapshot, SalesLine  # noqa: E402
from clawbot.workflows import connector_worker  # noqa: E402

results: list[dict] = []


def check(name: str, fn) -> None:
    try:
        status, seen = fn()
    except Exception as exc:  # noqa: BLE001
        status, seen = "fail", f"{type(exc).__name__}: {exc}"[:500]
        if os.getenv("DEBUG"):
            traceback.print_exc()
    results.append({"check": name, "status": status, "seen": seen})
    print(f"[{status:>4}] {name}: {seen}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", help="workspace id (default: the only workspace with a sandbox connection)")
    args = parser.parse_args()
    if os.getenv("SQUARE_ENVIRONMENT") != "sandbox":
        print("Set SQUARE_ENVIRONMENT=sandbox (and the other values in docs/SQUARE_SETUP.md §2) first.")
        return 2
    cfg = square_config.load()
    check("settings present", lambda: ("pass", "application id, secret, redirect URL, webhook key and URL are set")
          if all([cfg.application_id, cfg.application_secret, cfg.redirect_url, cfg.webhook_signature_key, cfg.webhook_url])
          else ("fail", "missing: " + ", ".join(k for k, v in {
              "SQUARE_APPLICATION_ID": cfg.application_id, "SQUARE_APPLICATION_SECRET": cfg.application_secret,
              "SQUARE_REDIRECT_URL": cfg.redirect_url, "SQUARE_WEBHOOK_SIGNATURE_KEY": cfg.webhook_signature_key,
              "SQUARE_WEBHOOK_URL": cfg.webhook_url}.items() if not v)))

    with transaction() as s:
        q = select(ConnectorAccount).where(ConnectorAccount.environment == "sandbox", ConnectorAccount.status == "active")
        if args.tenant:
            q = q.where(ConnectorAccount.tenant_id == args.tenant)
        accounts = list(s.scalars(q))
        account_id = accounts[0].id if len(accounts) == 1 else None
        tenant_id = accounts[0].tenant_id if len(accounts) == 1 else None
    if account_id is None:
        check("OAuth connection", lambda: ("fail", f"{len(accounts)} active sandbox connection(s); connect exactly one in "
                                                   "the app (Connections → Connect Square) or pass --tenant"))
        _write()
        return 1
    check("OAuth connection", lambda: ("pass", "an active sandbox connection exists (OAuth code exchange and token "
                                               "storage worked)"))

    def with_account(fn):
        with transaction() as s:
            acct = s.get(ConnectorAccount, account_id)
            return fn(s, acct)

    def merchant():
        def go(s, acct):
            client = square.client_for(acct)
            try:
                m = client.merchant()
            finally:
                client.close()
            return "pass", f"merchant {m.get('id')} ({m.get('business_name')})"
        return with_account(go)

    def locations():
        return with_account(lambda s, acct: ("pass", f"{len(square.external_locations(acct))} location(s); linked: "
                                                     f"{len(square._links(s, acct))}"))

    def catalog():
        def go(s, acct):
            r = square.sync_catalog(s, acct)
            return ("pass" if r.counts else "skip"), f"catalog sync counts {dict(r.counts)} (add items in the Sandbox seller first if empty)"
        return with_account(go)

    def orders():
        def go(s, acct):
            if not square.has_links(s, acct):
                return "skip", "link a Square location to a Tabula location first"
            end = datetime.now(timezone.utc)
            r = square.sync_sales(s, acct, start=end - timedelta(days=30), end=end)
            refunds = s.scalar(select(func.count()).select_from(SalesLine).where(
                SalesLine.tenant_id == tenant_id, SalesLine.source_system == "square", SalesLine.line_type == "refund"))
            return "pass", f"orders sync counts {dict(r.counts)}; refund lines stored: {refunds} (make a refund in the Sandbox to check returns)"
        return with_account(go)

    def counts():
        def go(s, acct):
            r = square.sync_inventory(s, acct)
            n = s.scalar(select(func.count()).select_from(InventorySnapshot).where(
                InventorySnapshot.tenant_id == tenant_id, InventorySnapshot.source_system == "square"))
            return ("pass" if n else "skip"), f"inventory counts {dict(r.counts)}; snapshots stored: {n}"
        return with_account(go)

    def refresh():
        def go(s, acct):
            before = acct.token_expires_at
            ok = square.refresh_token(s, acct, force=True)
            return ("pass" if ok else "fail"), f"refreshed={ok}; expiry {before} → {acct.token_expires_at}; status {acct.status}"
        return with_account(go)

    def webhooks():
        with transaction() as s:
            n = s.scalar(select(func.count()).select_from(ConnectorEvent).where(ConnectorEvent.tenant_id == tenant_id))
            types = sorted(set(s.scalars(select(ConnectorEvent.event_type).where(ConnectorEvent.tenant_id == tenant_id))))
        return ("pass" if n else "skip"), (f"{n} signed webhook event(s) stored: {types}. Duplicates are dropped by event id. "
                                           "(Trigger events in the Sandbox — e.g. a payment — with the tunnel running.)")

    def scheduled():
        queued = connector_worker.schedule_due(account_ids={account_id})
        again = connector_worker.schedule_due(account_ids={account_id})
        ran = 0
        for _ in range(10):
            n = connector_worker.run_once()
            ran += n
            if n == 0:
                break
        return "pass", f"queued {len(queued)} job(s), second scheduling queued {len(again)} (same slots), ran {ran}"

    for name, fn in [("merchant read", merchant), ("locations", locations), ("catalog", catalog),
                     ("orders and refunds", orders), ("inventory counts", counts), ("token refresh", refresh),
                     ("webhooks received", webhooks), ("scheduled sync", scheduled)]:
        check(name, fn)
    _write()
    return 0 if all(r["status"] != "fail" for r in results) else 1


def _write() -> None:
    out = ROOT / "var" / "square_sandbox_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2))
    print(f"\nreport: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
