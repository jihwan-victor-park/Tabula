"""
Worker crash points for import.apply jobs.

  A. dies before the apply transaction commits  → nothing applied; retried later, applied once
  B. dies after the apply committed, before the job was reported done
     (the job lease then expires)               → never marked failed, never applied twice
  C. finishes applying but lost its lease       → its whole transaction rolls back; the
                                                   current lease holder applies exactly once
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from clawbot.domain import outbox
from clawbot.domain.imports import apply as apply_mod
from clawbot.domain.imports.apply import apply_import
from clawbot.persistence.db import transaction
from clawbot.persistence.models import OutboxMessage
from clawbot.workflows import import_worker
from tests.test_imports import SALES, _confirm_import, _sales_upload, store  # noqa: F401


def _status(store, imp):
    return store.get(f"/v1/imports/{imp['id']}").json()


def _lines(store):
    return store.get("/v1/sales-lines").json()


def _make_due():
    with transaction() as s:
        s.query(OutboxMessage).filter(OutboxMessage.status == "pending").update(
            {"available_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        )


def test_a_crash_before_commit_applies_nothing_then_retry_applies_once(store, monkeypatch):
    imp = _sales_upload(store, SALES).json()
    assert _confirm_import(store, imp).status_code == 202

    real = apply_mod._apply_sales_row
    calls = {"n": 0}

    def dies_on_third_row(*args):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("process killed mid-apply")  # not a DomainError: the job fails
        return real(*args)

    monkeypatch.setattr(apply_mod, "_ROW_APPLIERS", {**apply_mod._ROW_APPLIERS, "sales": dies_on_third_row})
    import_worker.run_once()
    assert _lines(store) == []  # rows 1–2 were rolled back with the transaction
    assert _status(store, imp)["status"] == "confirmed"

    monkeypatch.setattr(apply_mod, "_ROW_APPLIERS", {**apply_mod._ROW_APPLIERS, "sales": real})
    _make_due()
    import_worker.run_once()
    assert _status(store, imp)["status"] == "applied"
    assert len(_lines(store)) == 4


def test_b_crash_after_commit_is_never_marked_failed_or_reapplied(store):
    imp = _sales_upload(store, SALES).json()
    assert _confirm_import(store, imp).status_code == 202
    with transaction() as s:
        s.query(OutboxMessage).update({"max_attempts": 1})  # so the expired lease goes straight to dead
    tenant, import_id = uuid.UUID(store.tenant_id), uuid.UUID(imp["id"])
    with transaction() as s:  # worker claims, applies and commits …
        outbox.claim_batch(s, lease=timedelta(seconds=-1), topics=("import.apply",))
        apply_import(s, tenant_id=tenant, import_id=import_id)
    # … and dies before reporting the job done. Lease expiry → dead → dead-job sweep.
    import_worker.run_once()
    import_worker.run_once()
    done = _status(store, imp)
    assert done["status"] == "applied" and done["failure"] is None
    assert len(_lines(store)) == 4
    with transaction() as s:
        assert s.query(OutboxMessage).one().status == "dead"  # the job record says what happened to the job


def test_b2_retry_safe_rerun_after_commit_is_a_no_op(store):
    imp = _sales_upload(store, SALES).json()
    assert _confirm_import(store, imp).status_code == 202
    tenant, import_id = uuid.UUID(store.tenant_id), uuid.UUID(imp["id"])
    with transaction() as s:
        outbox.claim_batch(s, lease=timedelta(seconds=-1), topics=("import.apply",))
        apply_import(s, tenant_id=tenant, import_id=import_id)
    assert import_worker.run_once() == 1  # expired lease re-queued (retry_safe) and re-run
    with transaction() as s:
        assert s.query(OutboxMessage).one().status == "done"
    assert _status(store, imp)["status"] == "applied" and len(_lines(store)) == 4


def test_c_worker_that_lost_its_lease_rolls_back_its_own_apply(store):
    imp = _sales_upload(store, SALES).json()
    assert _confirm_import(store, imp).status_code == 202
    tenant, import_id = uuid.UUID(store.tenant_id), uuid.UUID(imp["id"])
    with transaction() as s:  # worker A takes the job; its lease expires while it is still working
        ((mid, old_token),) = [(m.id, m.lease_token) for m in
                               outbox.claim_batch(s, lease=timedelta(seconds=-1), topics=("import.apply",))]
    with transaction() as s:  # worker B takes over
        ((_, new_token),) = [(m.id, m.lease_token) for m in outbox.claim_batch(s, topics=("import.apply",))]
    try:
        with transaction() as s:  # A finishes applying, then tries to report with its stale token
            apply_import(s, tenant_id=tenant, import_id=import_id)
            outbox.mark_done(s, mid, old_token)
    except outbox.LeaseLost:
        pass
    assert _lines(store) == [] and _status(store, imp)["status"] == "confirmed"
    with transaction() as s:  # B applies and reports
        apply_import(s, tenant_id=tenant, import_id=import_id)
        outbox.mark_done(s, mid, new_token)
    assert _status(store, imp)["status"] == "applied" and len(_lines(store)) == 4
