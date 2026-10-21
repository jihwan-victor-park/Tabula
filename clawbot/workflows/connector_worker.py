"""
Worker for connector jobs (outbox topics `square.sync` and `square.event`).

Sync and event processing are idempotent (Square IDs/UIDs and snapshot refs are
unique keys), so jobs are enqueued retry_safe. Each job's work and its "done"
mark commit together. Errors are recorded on the connection for the
Connections screen.

Run continuously:  python -m clawbot.workflows.connector_worker
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from clawbot.connectors.square import service as square
from clawbot.connectors.square.client import SquareError
from clawbot.domain import outbox
from clawbot.domain.errors import IdempotencyConflict
from clawbot.persistence.db import transaction
from clawbot.persistence.models import ConnectorAccount, ConnectorEvent

log = logging.getLogger(__name__)
TOPICS = ("square.sync", "square.event")


def _run_job(session, topic: str, tenant_id: uuid.UUID, payload: dict) -> None:
    account = square.get_account(session, tenant_id=tenant_id, account_id=uuid.UUID(payload["account_id"]))
    if account.status != "active":
        return  # revoked since enqueue: nothing to do
    if topic == "square.event":
        event = session.get(ConnectorEvent, uuid.UUID(payload["connector_event_id"]))
        if event is None or event.status == "processed":
            return
        square.handle_event(session, account, event)
        event.status, event.processed_at = "processed", datetime.now(timezone.utc)
        return
    kind = payload["kind"]
    if kind == "refresh_token":
        square.refresh_token(session, account)
        return
    if account.token_expires_at and account.token_expires_at - datetime.now(timezone.utc) < square.REFRESH_BEFORE:
        square.refresh_token(session, account)  # never call Square with a token about to expire
        if account.status != "active":
            return
    if kind == "reconcile":
        _reconcile(session, account, payload)
    elif kind == "catalog":
        square.sync_catalog(session, account)
    elif kind == "inventory":
        square.sync_inventory(session, account)
    elif kind == "sales":
        square.sync_sales(session, account, start=datetime.fromisoformat(payload["start"]),
                          end=datetime.fromisoformat(payload["end"]))
    else:
        raise ValueError(f"Unknown sync kind {kind!r}")
    square.record_sync(session, account, None)


def _reconcile(session, account, payload: dict) -> None:
    """
    Nightly: re-read the last few whole days from Square and the current stock. Webhooks can be lost;
    anything this pass records that was missing before is counted and kept on the connection.
    """
    start, end = datetime.fromisoformat(payload["start"]), datetime.fromisoformat(payload["end"])
    sales_result = square.sync_sales(session, account, start=start, end=end)
    inv = square.sync_inventory(session, account)
    state = dict(account.sync_state)
    history = state.get("reconciliations", [])[-13:]
    history.append({"at": datetime.now(timezone.utc).isoformat(), "window": f"{start.isoformat()}/{end.isoformat()}",
                    "recovered_sales_lines": sales_result.counts.get("created", 0),
                    "unmapped_items": sales_result.counts.get("unmapped_item", 0),
                    "stock_readings": inv.counts.get("recorded", 0)})
    state["reconciliations"] = history
    account.sync_state = state


SALES_EVERY = timedelta(minutes=15)
INVENTORY_EVERY = timedelta(minutes=30)
RECONCILE_DAYS = 3


def schedule_due(now: datetime | None = None, *, account_ids: set[uuid.UUID] | None = None) -> list[str]:
    """
    Enqueue what is due for every active Square connection. Operation keys name the time slot,
    so two schedulers (or a restart) never enqueue the same run twice; jobs are idempotent anyway.
      - sales every 15 min, from (last synced − 2 h overlap) to now
      - stock every 30 min
      - once a day (after 03:00 UTC): reconcile the last 3 whole days + stock
      - a token refresh once the token is within 7 days of expiry
    """
    now = now or datetime.now(timezone.utc)
    queued: list[str] = []
    with transaction() as session:
        for account in session.scalars(select(ConnectorAccount).where(ConnectorAccount.status == "active")):
            if account_ids is not None and account.id not in account_ids:
                continue
            state = account.sync_state or {}

            def due(kind: str, every: timedelta, payload: dict) -> None:
                slot = int(now.timestamp() // every.total_seconds())
                key = f"square:{account.id}:{kind}:slot:{slot}"
                if session.scalar(select(outbox.OutboxMessage.id).where(
                        outbox.OutboxMessage.tenant_id == account.tenant_id, outbox.OutboxMessage.operation_key == key)):
                    return  # this slot's run is already queued (or done)
                try:
                    with session.begin_nested():
                        outbox.enqueue(session, tenant_id=account.tenant_id, topic="square.sync", operation_key=key,
                                       payload={"account_id": str(account.id), "kind": kind, **payload}, retry_safe=True)
                except IdempotencyConflict:
                    return  # another scheduler queued this slot a moment ago
                queued.append(key)

            if account.refresh_token_enc and account.token_expires_at and account.token_expires_at - now < square.REFRESH_BEFORE:
                due("refresh_token", timedelta(hours=1), {})
            if not square.has_links(session, account):
                continue
            due("inventory", INVENTORY_EVERY, {})
            if not square.square_owns_sales(session, account):
                continue  # every linked store takes its sales from files: nothing to sync
            last = state.get("sales_synced_through")
            start = (datetime.fromisoformat(last) - timedelta(hours=2)) if last else now - timedelta(days=90)
            due("sales", SALES_EVERY, {"start": start.isoformat(), "end": now.isoformat()})
            if now.hour >= 3:
                # UTC-day slots, re-reading one extra day so every store's own last 3 local days are covered.
                day = now.replace(hour=0, minute=0, second=0, microsecond=0)
                due("reconcile", timedelta(days=1), {"start": (day - timedelta(days=RECONCILE_DAYS + 1)).isoformat(),
                                                     "end": now.isoformat()})
    return queued


def run_once(*, limit: int = 5, lease: timedelta = timedelta(minutes=10)) -> int:
    with transaction() as session:
        claimed = [(m.id, m.lease_token, m.tenant_id, m.topic, m.payload)
                   for m in outbox.claim_batch(session, limit=limit, lease=lease, topics=TOPICS)]
    for message_id, token, tenant_id, topic, payload in claimed:
        try:
            with transaction() as session:
                _run_job(session, topic, tenant_id, payload)
                outbox.mark_done(session, message_id, token)
        except outbox.LeaseLost:
            log.warning("connector job %s lost its lease", message_id)
        except Exception as exc:  # noqa: BLE001 — retried with backoff, then dead-lettered
            log.exception("connector job %s failed", message_id)
            with transaction() as session:
                try:
                    outbox.mark_failed(session, message_id, token, f"{type(exc).__name__}: {exc}")
                except outbox.LeaseLost:
                    continue
                try:
                    account = square.get_account(session, tenant_id=tenant_id, account_id=uuid.UUID(payload["account_id"]))
                    if isinstance(exc, SquareError) and exc.status == 401:
                        square.mark_needs_reauth(session, account, f"Square refused the token ({exc.category}); reconnect")
                    else:
                        square.record_sync(session, account, f"{topic}: {type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001
                    pass
    return len(claimed)


def main() -> None:  # pragma: no cover - process loop
    logging.basicConfig(level=logging.INFO)
    next_schedule = 0.0
    while True:
        if time.monotonic() >= next_schedule:
            try:
                schedule_due()
            except Exception:  # noqa: BLE001 — scheduling must not stop job processing
                log.exception("connector scheduling failed")
            next_schedule = time.monotonic() + 60
        if run_once() == 0:
            time.sleep(2)


if __name__ == "__main__":  # pragma: no cover
    main()
