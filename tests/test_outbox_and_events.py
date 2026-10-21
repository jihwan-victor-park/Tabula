"""Outbox leasing/fencing/retry semantics and connector raw-event dedupe."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from clawbot.domain import connector_events, outbox
from clawbot.domain.errors import IdempotencyConflict
from clawbot.persistence.db import transaction
from clawbot.persistence.models import OutboxMessage
from tests.conftest import new_store


@pytest.fixture
def tenant_id(client) -> uuid.UUID:
    return uuid.UUID(new_store(client, "owner@example.com").tenant_id)


def _enqueue(tenant_id, key="k", **kw):
    with transaction() as s:
        return outbox.enqueue(s, tenant_id=tenant_id, topic="po.send", operation_key=key, payload={"po": 1}, **kw)


def _claim(**kw):
    with transaction() as s:
        return [(m.id, m.lease_token, m.attempts) for m in outbox.claim_batch(s, **kw)]


def _status(message_id):
    with transaction() as s:
        return s.get(OutboxMessage, message_id).status


def test_enqueue_is_idempotent_on_operation_key(tenant_id):
    a = _enqueue(tenant_id, "po:1:rev:1:send")
    b = _enqueue(tenant_id, "po:1:rev:1:send")
    assert a.id == b.id


def test_same_key_different_payload_is_a_conflict(tenant_id):
    _enqueue(tenant_id, "po:1:rev:1:send")
    with pytest.raises(IdempotencyConflict), transaction() as s:
        outbox.enqueue(s, tenant_id=tenant_id, topic="po.send", operation_key="po:1:rev:1:send", payload={"po": 2})


def test_enqueue_rolls_back_with_its_transaction(tenant_id):
    with pytest.raises(RuntimeError), transaction() as s:
        outbox.enqueue(s, tenant_id=tenant_id, topic="po.send", operation_key="k", payload={})
        raise RuntimeError("approval failed")
    assert _claim() == []


def test_two_workers_never_lease_the_same_message(tenant_id):
    for i in range(20):
        _enqueue(tenant_id, f"k{i}")

    claimed: list[list[uuid.UUID]] = [[], []]
    barrier = threading.Barrier(2)

    def worker(slot: int) -> None:
        with transaction() as s:
            barrier.wait()
            claimed[slot] = [m.id for m in outbox.claim_batch(s, limit=15)]

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not set(claimed[0]) & set(claimed[1])
    assert len(claimed[0]) + len(claimed[1]) == 20


def test_failure_backs_off_then_dies_after_max_attempts(tenant_id):
    _enqueue(tenant_id, max_attempts=2)
    ((mid, token, _),) = _claim()
    with transaction() as s:
        msg = outbox.mark_failed(s, mid, token, "smtp 451 try later")
        assert msg.status == "pending" and msg.available_at > datetime.now(timezone.utc)

    assert _claim() == []  # still backing off
    with transaction() as s:
        s.get(OutboxMessage, mid).available_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    ((mid, token, attempts),) = _claim()
    assert attempts == 2
    with transaction() as s:
        assert outbox.mark_failed(s, mid, token, "smtp 451 try later").status == "dead"


def test_expired_lease_on_unsafe_send_becomes_unknown_not_resent(tenant_id):
    """Spec 16.2: the worker may have sent before crashing — never resend blindly."""
    _enqueue(tenant_id)
    ((mid, _, _),) = _claim(lease=timedelta(seconds=-1))  # worker "crashed"
    assert _claim() == []
    assert _status(mid) == "unknown"


def test_expired_lease_on_retry_safe_message_is_retried_until_dead(tenant_id):
    _enqueue(tenant_id, retry_safe=True, max_attempts=2)
    ((mid, _, _),) = _claim(lease=timedelta(seconds=-1))
    ((again, _, attempts),) = _claim(lease=timedelta(seconds=-1))
    assert again == mid and attempts == 2
    assert _claim() == []
    assert _status(mid) == "dead"


def test_stale_worker_cannot_complete_or_fail_a_newer_lease(tenant_id):
    _enqueue(tenant_id, retry_safe=True)
    ((mid, old_token, _),) = _claim(lease=timedelta(seconds=-1))  # worker A stalls
    ((_, new_token, _),) = _claim()  # worker B takes over
    with pytest.raises(outbox.LeaseLost), transaction() as s:
        outbox.mark_failed(s, mid, old_token, "A woke up late")
    with pytest.raises(outbox.LeaseLost), transaction() as s:
        outbox.mark_done(s, mid, old_token)
    with transaction() as s:
        assert outbox.mark_done(s, mid, new_token).status == "done"


def test_timeout_after_send_is_parked_as_unknown(tenant_id):
    _enqueue(tenant_id)
    ((mid, token, _),) = _claim()
    with transaction() as s:
        outbox.mark_failed(s, mid, token, "read timeout after POST", outcome_unknown=True)
    assert _status(mid) == "unknown"
    assert _claim() == []


def test_duplicate_connector_events_collapse(tenant_id):
    results = []
    for _ in range(10):
        with transaction() as s:
            results.append(
                connector_events.store_event(
                    s,
                    tenant_id=tenant_id,
                    provider="square",
                    external_event_id="evt_123",
                    event_type="inventory.count.updated",
                    payload={"data": 1},
                )
            )
    assert [r.is_new for r in results] == [True] + [False] * 9
    assert len({r.event.id for r in results}) == 1
