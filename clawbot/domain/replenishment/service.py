"""
Replenishment runs: gather → deterministic engine → persist.

- A run is keyed by (location, input digest): the same cutoff, data and policy
  return the same run. A run requested "now" reuses the current plan if it was
  computed moments ago with the same policy and nothing has changed since.
- Runs for a location are serialised with an advisory lock, and exactly one run
  per location is `current` (a scheduler and a manual run can never leave two plans).
- Each line stores its full inputs, so `replay()` recomputes it bit-for-bit.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError
from sqlalchemy import func, select, update
from typing import Annotated
from sqlalchemy.orm import Session

from clawbot.domain import audit, catalog, tenancy
from clawbot.domain.errors import NotFound, ValidationFailed
from clawbot.domain.replenishment import codec
from clawbot.domain.replenishment.engine import ENGINE_VERSION, ItemResult, Policy, plan_checks, recommend
from clawbot.domain.replenishment.gather import gather
from clawbot.domain.units import validate_currency
from clawbot.persistence.models import (
    ExternalOpenOrderLine,
    InventoryMovement,
    InventorySnapshot,
    ReplenishmentItemSetting,
    ReplenishmentLine,
    ReplenishmentPolicy,
    ReplenishmentRun,
    SalesLine,
)
from clawbot.policies.permissions import Actor, authorize

def _no_float(value: Any) -> Any:
    if isinstance(value, float) or isinstance(value, bool):
        raise ValueError("send numbers as strings or integers (e.g. \"2.5\"), not floats")
    return Decimal(value) if isinstance(value, (str, int)) else value


DEFAULT_POLICY = Policy(version=0)
REUSE_SECONDS = 120
# A run whose cutoff is further in the past than this is a "what would we have
# ordered then" analysis: kept for comparison, never the current plan.
HISTORICAL_AFTER = timedelta(minutes=10)


class PolicyChanges(BaseModel):
    """Typed policy edits: whole numbers stay ints, money/quantities are Decimal (never float), bools are bools."""

    model_config = ConfigDict(extra="forbid", strict=True)
    review_period_days: int | None = None
    demand_window_days: int | None = None
    long_window_days: int | None = None
    min_history_days: int | None = None
    min_sale_days: int | None = None
    safety_days: Annotated[Decimal, BeforeValidator(_no_float)] | None = None
    weekday_pattern: bool | None = None
    weekday_min_weeks: int | None = None
    max_stock_age_hours: int | None = None
    max_sales_age_hours: int | None = None
    max_unconfirmed_age_days: int | None = None
    weekly_budget: Annotated[Decimal, BeforeValidator(_no_float)] | None = None
    budget_currency: Annotated[str, BeforeValidator(lambda v: v.upper() if isinstance(v, str) else v)] | None = None
_POLICY_FIELDS = {f.name for f in dataclasses.fields(Policy)} - {"version"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Policy and item settings
# ---------------------------------------------------------------------------


def current_policy(session: Session, *, tenant_id: uuid.UUID) -> Policy:
    row = session.scalars(
        select(ReplenishmentPolicy).where(ReplenishmentPolicy.tenant_id == tenant_id)
        .order_by(ReplenishmentPolicy.version.desc()).limit(1)
    ).first()
    if row is None:
        return DEFAULT_POLICY
    return codec.load_policy({**row.settings, "version": row.version})


def set_policy(session: Session, *, tenant_id: uuid.UUID, actor: Actor, changes: dict[str, Any]) -> Policy:
    """Policies are versioned, never edited: each change creates the next version."""
    authorize(actor, "replenishment.policy")
    unknown = set(changes) - _POLICY_FIELDS
    if unknown:
        raise ValidationFailed(f"Unknown policy fields: {sorted(unknown)}")
    clearable = {"weekly_budget", "budget_currency"}
    try:
        typed = PolicyChanges.model_validate(changes)
    except ValidationError as exc:
        raise ValidationFailed("Invalid policy", details={"errors": [
            {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]})
    changes = {k: v for k, v in typed.model_dump(exclude_unset=True).items() if v is not None or k in clearable}
    # Serialise version allocation per tenant.
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"repl-policy:{tenant_id}", 0))))
    base = current_policy(session, tenant_id=tenant_id)
    merged = {**codec.dumps(base), **{k: codec.dumps(v) if isinstance(v, Decimal) else v for k, v in changes.items()}}
    merged.pop("version")
    policy = codec.load_policy({**merged, "version": base.version + 1})
    _validate_policy(policy)
    session.add(ReplenishmentPolicy(
        tenant_id=tenant_id, version=policy.version,
        settings={k: v for k, v in codec.dumps(policy).items() if k != "version"},
        created_by_user_id=actor.user_id,
    ))
    session.flush()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="replenishment.policy_set",
                 object_type="replenishment_policy", object_id=policy.version,
                 before=codec.dumps(base), after=codec.dumps(policy))
    return policy


def _validate_policy(p: Policy) -> None:
    ints = ("review_period_days", "demand_window_days", "long_window_days", "min_history_days", "min_sale_days",
            "weekday_min_weeks", "max_stock_age_hours", "max_sales_age_hours")
    if any(not isinstance(getattr(p, n), int) or getattr(p, n) < 1 for n in ints):
        raise ValidationFailed("Day/hour settings must be whole numbers of at least 1")
    if p.review_period_days > 90 or p.long_window_days > 730 or p.demand_window_days > p.long_window_days:
        raise ValidationFailed("Windows are out of range (review ≤ 90 days, demand window ≤ long window ≤ 730 days)")
    if p.safety_days < 0 or p.safety_days > 60:
        raise ValidationFailed("safety_days must be between 0 and 60")
    if (p.weekly_budget is None) != (p.budget_currency is None):
        raise ValidationFailed("weekly_budget and budget_currency go together")
    if p.weekly_budget is not None:
        validate_currency(p.budget_currency)
        if p.weekly_budget <= 0:
            raise ValidationFailed("weekly_budget must be positive")


def set_item_setting(
    session: Session, *, tenant_id: uuid.UUID, actor: Actor, variant_id: uuid.UUID, location_id: uuid.UUID,
    safety_stock: Decimal | None, min_qty: Decimal | None, max_qty: Decimal | None, excluded: bool,
) -> ReplenishmentItemSetting:
    authorize(actor, "replenishment.policy")
    catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    if min_qty is not None and max_qty is not None and min_qty >= max_qty:
        raise ValidationFailed("min must be below max")
    row = session.get(ReplenishmentItemSetting, (tenant_id, variant_id, location_id), with_for_update=True)
    before = None if row is None else {"safety_stock": str(row.safety_stock), "min": str(row.min_qty),
                                       "max": str(row.max_qty), "excluded": row.excluded}
    if row is None:
        row = ReplenishmentItemSetting(tenant_id=tenant_id, variant_id=variant_id, location_id=location_id)
        session.add(row)
    row.safety_stock, row.min_qty, row.max_qty, row.excluded = safety_stock, min_qty, max_qty, excluded
    row.updated_by_user_id, row.updated_at = actor.user_id, _now()
    session.flush()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="replenishment.item_setting_set",
                 object_type="variant", object_id=variant_id, before=before,
                 after={"location_id": str(location_id), "safety_stock": str(safety_stock), "min": str(min_qty),
                        "max": str(max_qty), "excluded": excluded})
    return row


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def _result_json(r: ItemResult) -> dict[str, Any]:
    keys = ("daily_demand", "target", "position", "need", "stockout_days", "stockout_days_without_order",
            "days_of_cover", "priority", "reasons", "steps", "projection")
    return {k: codec.dumps(getattr(r, k)) for k in keys}


def create_run(
    session: Session, *, tenant_id: uuid.UUID, actor: Actor, location_id: uuid.UUID, as_of: datetime | None = None
) -> tuple[ReplenishmentRun, bool]:
    """Returns (run, created). Same inputs + policy → the existing run."""
    authorize(actor, "replenishment.run")
    tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    if as_of is not None and as_of.tzinfo is None:
        raise ValidationFailed("as_of must include a timezone")
    now = _now()
    cutoff = (as_of or now).astimezone(timezone.utc)
    if cutoff > now + timedelta(minutes=1):
        raise ValidationFailed("as_of cannot be in the future")
    historical = now - cutoff > HISTORICAL_AFTER
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"repl-run:{tenant_id}:{location_id}", 0))))

    policy = current_policy(session, tenant_id=tenant_id)
    if not historical:
        # A scheduler and a person pressing "plan" moments apart get the same plan.
        latest = current_run(session, tenant_id=tenant_id, location_id=location_id)
        if (latest is not None and latest.policy_version == policy.version
                and (now - latest.cutoff).total_seconds() < REUSE_SECONDS
                and not newer_data_since(session, latest)):
            return latest, False
    gathered = gather(session, tenant_id=tenant_id, location_id=location_id, cutoff=cutoff, policy=policy)
    input_digest = codec.digest(policy, cutoff.isoformat(), gathered.items, gathered.suppliers)

    existing = session.scalars(
        select(ReplenishmentRun).where(ReplenishmentRun.tenant_id == tenant_id,
                                       ReplenishmentRun.location_id == location_id,
                                       ReplenishmentRun.input_digest == input_digest)
    ).one_or_none()
    if existing is not None:
        return existing, False

    results = [recommend(item, policy) for item in gathered.items]
    notes = plan_checks(results, gathered.suppliers, policy)

    if not historical:
        session.execute(
            update(ReplenishmentRun)
            .where(ReplenishmentRun.tenant_id == tenant_id, ReplenishmentRun.location_id == location_id,
                   ReplenishmentRun.status == "current")
            .values(status="superseded")
        )
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    run = ReplenishmentRun(
        tenant_id=tenant_id, location_id=location_id, cutoff=cutoff, planning_date=gathered.planning_date,
        policy_version=policy.version, engine_version=ENGINE_VERSION, input_digest=input_digest,
        status="historical" if historical else "current",
        actor_kind=actor.kind, actor_user_id=actor.user_id, actor_name=actor.name, policy=codec.dumps(policy),
        summary={"lines": counts, "needs_review": sum(r.needs_review for r in results)}, plan_notes=notes,
    )
    session.add(run)
    session.flush()
    session.add_all(
        ReplenishmentLine(
            tenant_id=tenant_id, run_id=run.id, variant_id=uuid.UUID(r.variant_id), status=r.status,
            needs_review=r.needs_review, order_qty=r.order_qty, order_uom=r.order_uom, base_qty=r.base_qty,
            line_cost=r.line_cost, currency=r.currency,
            supplier_id=uuid.UUID(r.supplier_id) if r.supplier_id else None,
            supplier_item_id=uuid.UUID(r.supplier_item_id) if r.supplier_item_id else None,
            inputs=codec.dumps(item), result=_result_json(r),
        )
        for item, r in zip(gathered.items, results)
    )
    session.flush()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="replenishment.run_created",
                 object_type="replenishment_run", object_id=run.id,
                 after={"cutoff": cutoff.isoformat(), "policy_version": policy.version, "summary": run.summary})
    return run, True


def get_run(session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID) -> ReplenishmentRun:
    run = session.scalars(
        select(ReplenishmentRun).where(ReplenishmentRun.tenant_id == tenant_id, ReplenishmentRun.id == run_id)
    ).one_or_none()
    if run is None:
        raise NotFound(f"Replenishment run not found: {run_id}")
    return run


def run_lines(session: Session, run: ReplenishmentRun) -> list[ReplenishmentLine]:
    return list(session.scalars(
        select(ReplenishmentLine).where(ReplenishmentLine.tenant_id == run.tenant_id, ReplenishmentLine.run_id == run.id)
    ))


def current_run(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID) -> ReplenishmentRun | None:
    return session.scalars(
        select(ReplenishmentRun).where(ReplenishmentRun.tenant_id == tenant_id,
                                       ReplenishmentRun.location_id == location_id, ReplenishmentRun.status == "current")
    ).one_or_none()


def newer_data_since(session: Session, run: ReplenishmentRun) -> list[str]:
    """
    Which inputs changed after the plan's cutoff (the plan may be stale).

    Limitation: row timestamps are transaction start times, so a write whose
    transaction began before the cutoff but committed after it is not flagged.
    Commit-ordered change tracking is CP11.
    """
    from clawbot.persistence.models import (
        ReplenishmentPolicy as Pol, SalesCoverage, Supplier, SupplierClosure, SupplierItem, SupplierItemPrice, Variant,
    )

    t, tenant, loc = run.cutoff, run.tenant_id, run.location_id
    checks = {
        "sales": select(func.max(SalesLine.created_at)).where(SalesLine.tenant_id == tenant, SalesLine.location_id == loc),
        "sales_coverage": select(func.max(SalesCoverage.created_at)).where(
            SalesCoverage.tenant_id == tenant, SalesCoverage.location_id == loc),
        "stock": select(func.max(InventoryMovement.recorded_at)).where(
            InventoryMovement.tenant_id == tenant, InventoryMovement.location_id == loc),
        "stock_snapshots": select(func.max(InventorySnapshot.created_at)).where(
            InventorySnapshot.tenant_id == tenant, InventorySnapshot.location_id == loc),
        "open_orders": select(func.max(ExternalOpenOrderLine.updated_at)).where(
            ExternalOpenOrderLine.tenant_id == tenant, ExternalOpenOrderLine.location_id == loc),
        "prices": select(func.max(SupplierItemPrice.created_at)).where(SupplierItemPrice.tenant_id == tenant),
        "supplier_items": select(func.max(SupplierItem.updated_at)).where(SupplierItem.tenant_id == tenant),
        "suppliers": select(func.max(Supplier.updated_at)).where(Supplier.tenant_id == tenant),
        "supplier_closures": select(func.max(SupplierClosure.created_at)).where(SupplierClosure.tenant_id == tenant),
        "items": select(func.max(Variant.updated_at)).where(Variant.tenant_id == tenant),
        "item_settings": select(func.max(ReplenishmentItemSetting.updated_at)).where(
            ReplenishmentItemSetting.tenant_id == tenant, ReplenishmentItemSetting.location_id == loc),
        "policy": select(func.max(Pol.created_at)).where(Pol.tenant_id == tenant),
    }
    return [name for name, stmt in checks.items() if (latest := session.scalar(stmt)) is not None and latest > t]


def replay(line: ReplenishmentLine, run: ReplenishmentRun) -> ItemResult:
    """Recompute a stored line from its stored inputs and the run's policy."""
    return recommend(codec.load_item(line.inputs), codec.load_policy(run.policy))
