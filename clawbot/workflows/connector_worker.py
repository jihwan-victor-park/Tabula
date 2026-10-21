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

from clawbot.connectors.square import service as square
from clawbot.domain import outbox
from clawbot.persistence.db import transaction
from clawbot.persistence.models import ConnectorEvent

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
    if kind == "catalog":
        square.sync_catalog(session, account)
    elif kind == "inventory":
        square.sync_inventory(session, account)
    elif kind == "sales":
        square.sync_sales(session, account, start=datetime.fromisoformat(payload["start"]),
                          end=datetime.fromisoformat(payload["end"]))
    else:
        raise ValueError(f"Unknown sync kind {kind!r}")
    square.record_sync(session, account, None)


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
                    square.record_sync(session, account, f"{topic}: {type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001
                    pass
    return len(claimed)


def main() -> None:  # pragma: no cover - process loop
    logging.basicConfig(level=logging.INFO)
    while True:
        if run_once() == 0:
            time.sleep(2)


if __name__ == "__main__":  # pragma: no cover
    main()
