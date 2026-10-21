"""
Transactional outbox.

enqueue() is called inside the same transaction as the business decision
(e.g. PO approval), so the side effect is recorded iff the decision commits.

Workers lease rows with FOR UPDATE SKIP LOCKED and get a fencing token; only
the holder of the current token may complete or fail the message, so a worker
that resumes after its lease expired cannot overwrite a newer attempt.

When a lease expires the worker may have crashed *after* the external call
went out. Spec 16.2: unknown outcome → do not resend blindly. Such messages
move to `unknown` for a person (or a status lookup) to resolve, unless the
message was enqueued as `retry_safe` (the external call is itself idempotent
on operation_key), in which case it is re-leased until max_attempts.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.domain.errors import DomainError, IdempotencyConflict
from clawbot.persistence.models import OutboxMessage

BASE_BACKOFF = timedelta(seconds=30)
MAX_BACKOFF = timedelta(hours=1)


class LeaseLost(DomainError):
    """This worker no longer holds the message's lease; its result must be discarded."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    topic: str,
    operation_key: str,
    payload: dict[str, Any],
    max_attempts: int = 8,
    retry_safe: bool = False,
) -> OutboxMessage:
    """
    Idempotent on operation_key: enqueueing the same operation again returns the
    first message. The same key with a different topic or payload is a bug in
    the caller and raises IdempotencyConflict.
    """
    # Compare what JSONB will hand back (tuples become lists, keys become strings).
    payload = json.loads(json.dumps(payload))
    session.execute(
        insert(OutboxMessage)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            topic=topic,
            operation_key=operation_key,
            payload=payload,
            max_attempts=max_attempts,
            retry_safe=retry_safe,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "operation_key"])
    )
    message = session.scalars(
        select(OutboxMessage).where(
            OutboxMessage.tenant_id == tenant_id, OutboxMessage.operation_key == operation_key
        )
    ).one()
    if (message.topic, message.payload, message.max_attempts, message.retry_safe) != (
        topic, payload, max_attempts, retry_safe,
    ):
        raise IdempotencyConflict(f"Operation {operation_key} was already enqueued with different content")
    return message


def _expire_leases(session: Session, now: datetime) -> None:
    expired = session.scalars(
        select(OutboxMessage)
        .where(OutboxMessage.status == "in_flight", OutboxMessage.locked_until < now)
        .with_for_update(skip_locked=True)
    )
    for message in expired:
        message.locked_until = None
        message.last_error = "lease expired before the worker reported a result"
        if not message.retry_safe:
            # Keep the token: the late worker may still report what actually happened.
            message.status = "unknown"
            continue
        message.lease_token = None
        if message.attempts >= message.max_attempts:
            message.status = "dead"
        else:
            message.status = "pending"
            message.available_at = now


def claim_batch(
    session: Session,
    *,
    limit: int = 10,
    lease: timedelta = timedelta(minutes=5),
    topics: tuple[str, ...] | None = None,
) -> list[OutboxMessage]:
    """Lease up to `limit` due messages (optionally only `topics`). Commit promptly so other workers see the lease."""
    now = _now()
    _expire_leases(session, now)
    session.flush()
    stmt = select(OutboxMessage).where(OutboxMessage.status == "pending", OutboxMessage.available_at <= now)
    if topics is not None:
        stmt = stmt.where(OutboxMessage.topic.in_(topics))
    rows = list(
        session.scalars(stmt.order_by(OutboxMessage.available_at).limit(limit).with_for_update(skip_locked=True))
    )
    for row in rows:
        row.status = "in_flight"
        row.attempts += 1
        row.locked_until = now + lease
        row.lease_token = uuid.uuid4()
    session.flush()
    return rows


def _held(session: Session, message_id: uuid.UUID, lease_token: uuid.UUID) -> OutboxMessage:
    message = session.scalars(
        select(OutboxMessage).where(OutboxMessage.id == message_id).with_for_update()
    ).one()
    # A worker whose lease expired into `unknown` may still report the real outcome.
    if message.status not in ("in_flight", "unknown") or message.lease_token != lease_token:
        raise LeaseLost(f"Outbox message {message_id} is no longer leased by this worker")
    return message


def mark_done(session: Session, message_id: uuid.UUID, lease_token: uuid.UUID) -> OutboxMessage:
    message = _held(session, message_id, lease_token)
    message.status = "done"
    message.completed_at = _now()
    message.locked_until = None
    message.lease_token = None
    message.last_error = None
    session.flush()
    return message


def mark_failed(
    session: Session, message_id: uuid.UUID, lease_token: uuid.UUID, error: str, *, outcome_unknown: bool = False
) -> OutboxMessage:
    """
    A failure the worker observed. `outcome_unknown=True` (e.g. a timeout after
    sending) parks the message in `unknown` instead of retrying. Otherwise retry
    with exponential backoff, or `dead` after max_attempts.
    """
    message = _held(session, message_id, lease_token)
    message.last_error = error[:4000]
    message.locked_until = None
    message.lease_token = None
    if outcome_unknown:
        message.status = "unknown"
    elif message.attempts >= message.max_attempts:
        message.status = "dead"
    else:
        backoff = min(BASE_BACKOFF * (2 ** (message.attempts - 1)), MAX_BACKOFF)
        message.status = "pending"
        message.available_at = _now() + backoff
    session.flush()
    return message
