"""
Worker for `import.apply` outbox jobs.

Applying an import and marking its job done happen in one transaction, so a
crash leaves either both or neither. A retried job finds the import already
applied and does nothing.

Run continuously:  python -m clawbot.workflows.import_worker
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import timedelta

from sqlalchemy import select

from clawbot.domain import outbox
from clawbot.domain.imports.apply import apply_import
from clawbot.domain.imports.service import APPLY_TOPIC, get_import
from clawbot.persistence.db import transaction
from clawbot.persistence.models import OutboxMessage

log = logging.getLogger(__name__)


def fail_dead_imports() -> int:
    """
    A worker that died mid-job leaves no one to mark its import failed; once the
    outbox gives up on the job (dead), say so on the import.
    """
    with transaction() as session:
        dead = session.scalars(
            select(OutboxMessage).where(OutboxMessage.topic == APPLY_TOPIC, OutboxMessage.status == "dead")
        ).all()
        changed = 0
        for message in dead:
            imp = get_import(session, tenant_id=message.tenant_id, import_id=uuid.UUID(message.payload["import_id"]),
                             for_update=True)
            if imp.status in ("confirmed", "applying"):
                imp.status = "failed"
                imp.failure = f"Could not be applied after {message.attempts} attempts: {message.last_error}"
                changed += 1
        return changed


def run_once(*, limit: int = 5, lease: timedelta = timedelta(minutes=15)) -> int:
    """Process up to `limit` due import jobs. Returns how many were handled."""
    with transaction() as session:
        claimed = [(m.id, m.lease_token, m.tenant_id, m.payload) for m in
                   outbox.claim_batch(session, limit=limit, lease=lease, topics=(APPLY_TOPIC,))]
    fail_dead_imports()  # after claiming: claim_batch is where expired leases become dead
    for message_id, token, tenant_id, payload in claimed:
        try:
            with transaction() as session:
                apply_import(session, tenant_id=tenant_id, import_id=uuid.UUID(payload["import_id"]))
                outbox.mark_done(session, message_id, token)
        except outbox.LeaseLost:
            log.warning("import job %s lost its lease; another worker owns it", message_id)
        except Exception as exc:  # noqa: BLE001 — any failure is retried with backoff, then dead-lettered
            log.exception("import job %s failed", message_id)
            with transaction() as session:
                try:
                    message = outbox.mark_failed(session, message_id, token, f"{type(exc).__name__}: {exc}")
                except outbox.LeaseLost:
                    continue
                if message.status == "dead":
                    # Out of retries: say so on the import instead of leaving it "confirmed" forever.
                    imp = get_import(session, tenant_id=tenant_id, import_id=uuid.UUID(payload["import_id"]), for_update=True)
                    if imp.status in ("confirmed", "applying"):
                        imp.status = "failed"
                        imp.failure = f"Could not be applied after {message.attempts} attempts: {type(exc).__name__}"
    return len(claimed)


def main() -> None:  # pragma: no cover - process loop
    logging.basicConfig(level=logging.INFO)
    while True:
        if run_once() == 0:
            time.sleep(2)


if __name__ == "__main__":  # pragma: no cover
    main()
