"""
Tenant data version: a counter every write to planning inputs bumps inside its
own transaction (spec 13.3, 16.9).

Why a counter and not timestamps: a row's created_at is its transaction's start
time, so a write that began before a plan but committed after it looks "older"
than the plan. The counter only changes when the writing transaction commits,
so comparing the version a plan saw with the version now catches every write
the plan did not see — including ones that were still uncommitted at the time.

Bumped at most once per transaction or savepoint (per tenant), so a large
import does not issue one update per row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, event, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, SessionTransaction

from clawbot.persistence.models import Import, ImportStatusPending, OutboxMessage, TenantDataVersion

_FLAG = "data_version_bumped"
INPUT_JOB_TOPICS = ("import.apply", "square.sync", "square.event")


@event.listens_for(Session, "after_transaction_end")
def _forget(session: Session, transaction: SessionTransaction) -> None:
    # Any transaction or savepoint ending forgets the bump: a rolled-back savepoint takes its
    # bump with it, so the next write must bump again (an extra bump is harmless, a missed one is not).
    session.info.pop(_FLAG, None)


def bump(session: Session, tenant_id: uuid.UUID) -> None:
    bumped = session.info.setdefault(_FLAG, set())
    if tenant_id in bumped:
        return
    session.execute(
        insert(TenantDataVersion).values(tenant_id=tenant_id, version=1)
        .on_conflict_do_update(index_elements=["tenant_id"], set_={"version": TenantDataVersion.version + 1})
    )
    bumped.add(tenant_id)


def current(session: Session, tenant_id: uuid.UUID, *, lock: bool = False) -> int:
    """
    lock=True takes a share lock on the counter row: it waits for any transaction
    that has bumped it (an input write in flight) to finish, then keeps new input
    writes from committing until this transaction ends. Use it where a decision
    must hold against the data as of the end of the transaction (approve, send).
    """
    stmt = select(TenantDataVersion.version).where(TenantDataVersion.tenant_id == tenant_id)
    if lock:
        stmt = stmt.with_for_update(read=True)
    return session.scalar(stmt) or 0


def pending_inputs(session: Session, tenant_id: uuid.UUID) -> list[str]:
    """Writes that are confirmed but not finished: approving now could act on half-updated data."""
    pending = []
    imports = session.scalars(select(Import.file_name).where(
        Import.tenant_id == tenant_id, Import.status.in_(ImportStatusPending))).all()
    pending += [f"import {name} is being applied" for name in imports]
    # A job waiting out a retry backoff is not running; it must not hold approvals for hours.
    jobs = session.scalars(select(OutboxMessage.topic).where(
        OutboxMessage.tenant_id == tenant_id, OutboxMessage.topic.in_(INPUT_JOB_TOPICS),
        or_(OutboxMessage.status == "in_flight",
            and_(OutboxMessage.status == "pending", OutboxMessage.available_at <= func.now())))).all()
    pending += [f"{topic} job running" for topic in jobs if topic != "import.apply"]
    return pending
