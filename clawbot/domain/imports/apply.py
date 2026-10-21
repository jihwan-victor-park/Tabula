"""
Applying a confirmed import.

Runs as the person who confirmed it (role re-read from their membership now,
so a revoked user's import stops). Rows are re-evaluated against current data,
each row runs in its own savepoint, and every write is idempotent — a crashed
or retried job never applies a row twice.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from clawbot.domain import audit, catalog, inventory, open_orders, sales, suppliers, tenancy
from clawbot.domain.errors import DomainError
from clawbot.domain.imports import kinds
from clawbot.domain.imports.service import _rows, evaluate, get_import, mark_rows
from clawbot.persistence.models import Import, InventoryMovement
from clawbot.policies.permissions import Actor


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _source_ref(imp: Import) -> str:
    return f"import:{imp.id} ({imp.file_name})"


def _apply_price_row(session: Session, imp: Import, ctx: kinds.Context, actor: Actor, r: kinds.RowResult) -> tuple[str, str]:
    v = r.values
    s: kinds.PriceListSettings = ctx.settings
    tenant_id, supplier_id = imp.tenant_id, uuid.UUID(imp.context["supplier_id"])
    item = ctx.supplier_items.get(v["supplier_sku"])
    changed = False
    if item is None:
        item = suppliers.create_supplier_item(
            session, tenant_id=tenant_id, actor=actor, supplier_id=supplier_id, supplier_sku=v["supplier_sku"],
            order_uom=v["order_uom"], units_per_order_uom=v["units_per_order_uom"], description=v["description"],
            order_multiple=v["order_multiple"] or Decimal(1), min_order_qty=v["min_order_qty"] or Decimal(1),
            lead_time_days=v["lead_time_days"], suggested_variant_id=v["variant_id"], source_ref=_source_ref(imp),
        )
        changed = True
    else:
        updates: dict[str, Any] = {}
        if (v["order_uom"], v["units_per_order_uom"]) != (item.order_uom, item.units_per_order_uom):
            if not s.update_pack_on_change:  # evaluation already flags this; defensive
                raise DomainError("Pack changed; not applied")
            updates.update(order_uom=v["order_uom"], units_per_order_uom=v["units_per_order_uom"])
        for name in ("min_order_qty", "order_multiple", "lead_time_days", "description"):
            if v[name] is not None and getattr(item, name) != v[name]:
                updates[name] = v[name]
        if updates:
            item = suppliers.update_supplier_item(
                session, tenant_id=tenant_id, actor=actor, item_id=item.id, expected_version=item.version,
                changes={**updates, "source_ref": _source_ref(imp)}, reason=f"Supplier price list {imp.file_name}",
            )
            changed = True

    current = suppliers.current_price(session, tenant_id=tenant_id, item_id=item.id)
    same_price = (
        current is not None
        and v["valid_from"] is None
        and (current.unit_price, current.currency, current.price_type, current.units_per_order_uom, current.expires_at)
        == (v["unit_price"], v["currency"], s.price_type, item.units_per_order_uom, v["expires_at"])
    )
    if not same_price:
        suppliers.record_price(
            session, tenant_id=tenant_id, actor=actor, item_id=item.id, unit_price=v["unit_price"],
            currency=v["currency"], price_type=s.price_type, order_uom=item.order_uom,
            units_per_order_uom=item.units_per_order_uom, source_ref=_source_ref(imp),
            valid_from=v["valid_from"], expires_at=v["expires_at"],
        )
        changed = True
    # Cache only once every write for this row succeeded (a failed row rolls back its savepoint).
    ctx.supplier_items[item.supplier_sku] = item
    return ("applied" if changed else "unchanged"), f"supplier_item:{item.id}"


def _apply_inventory_row(session: Session, imp: Import, ctx: kinds.Context, actor: Actor, r: kinds.RowResult) -> tuple[str, str]:
    v = r.values
    tenant_id, location_id = imp.tenant_id, uuid.UUID(imp.context["location_id"])
    variant_id = v["variant_id"]
    created = None
    if variant_id is None:  # create_missing_variants (checked at evaluation and confirm)
        created = catalog.create_variant(
            session, tenant_id=tenant_id, actor=actor, sku=v["sku"], name=v["name"], barcode=v["barcode"]
        )
        variant_id = created.id
    _, is_new = inventory.record_snapshot(
        session, tenant_id=tenant_id, actor=actor, variant_id=variant_id, location_id=location_id,
        quantity=v["quantity"], as_of=v["as_of"], source_system="import", source_ref=str(imp.id),
    )
    if created is not None:
        ctx.resolver.add_variant(created)
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    if location.inventory_write_owner != "tabula":
        return ("applied" if is_new else "unchanged"), f"variant:{variant_id}"  # POS owns the count

    position = inventory.get_position(session, tenant_id=tenant_id, variant_id=variant_id, location_id=location_id)
    # Order by when stock changes *happened*, not when they were entered: a newer
    # count still applies after an older one was entered later.
    last_change = session.scalar(
        select(func.max(InventoryMovement.occurred_at)).where(
            InventoryMovement.tenant_id == tenant_id,
            InventoryMovement.variant_id == variant_id,
            InventoryMovement.location_id == location_id,
        )
    )
    if last_change is not None and last_change > v["as_of"]:
        r.warn(None, "Stock changed after this count was taken; count saved, quantity not overwritten")
        return "skipped", f"variant:{variant_id}"
    delta = v["quantity"] - (position.on_hand if position else Decimal(0))
    if delta == 0:
        return "unchanged", f"variant:{variant_id}"
    inventory.record_movement(
        session, tenant_id=tenant_id, actor=actor, variant_id=variant_id, location_id=location_id, delta=delta,
        reason="count", source=f"import:{imp.id}", source_event_id=f"row:{r.row_number}",
        notes=f"Stock count from {imp.file_name}", occurred_at=v["as_of"],
    )
    return "applied", f"variant:{variant_id}"


def _apply_sales_row(session: Session, imp: Import, ctx: kinds.Context, actor: Actor, r: kinds.RowResult) -> tuple[str, str]:
    v = r.values
    recorded = sales.record_sales_line(
        session, tenant_id=imp.tenant_id, actor=actor, variant_id=v["variant_id"],
        location_id=uuid.UUID(imp.context["location_id"]), source_system=imp.context["source_system"],
        external_order_id=v["order_id"], external_line_key=v["line_key"], key_scheme=v["key_scheme"],
        sold_at=v["sold_at"], quantity=v["quantity"], line_type=v["line_type"], unit_price=v["unit_price"],
        currency=v["currency"], import_id=imp.id, restock=v.get("restock"),
    )
    if recorded.outcome == "conflict":
        raise DomainError(
            f"Order {v['order_id']} was already recorded with quantity {recorded.line.quantity}; this file says {v['quantity']}"
        )
    if recorded.outcome == "other_path":
        raise DomainError(
            f"Order {v['order_id']} is already recorded from {imp.context['source_system']} through another path "
            f"({recorded.line.key_scheme}); not counted twice — review it"
        )
    return ("applied" if recorded.outcome == "created" else "unchanged"), f"sales_line:{recorded.line.id}"


def _apply_open_order_row(session: Session, imp: Import, ctx: kinds.Context, actor: Actor, r: kinds.RowResult) -> tuple[str, str]:
    v = r.values
    result = open_orders.upsert_open_order_line(
        session, tenant_id=imp.tenant_id, actor=actor, supplier_id=v["supplier_id"], variant_id=v["variant_id"],
        location_id=uuid.UUID(imp.context["location_id"]), external_po_number=v["po_number"],
        outstanding_qty=v["outstanding_qty"], supplier_confirmed=v["confirmed"], ordered_at=v["ordered_at"],
        expected_at=v["expected_at"], import_id=imp.id, reported_at=ctx.settings.as_of,
    )
    if result.outcome == "older_report":
        r.warn(None, "A newer report already updated this order line; not changed")
        return "skipped", f"open_order_line:{result.line.id}"
    return ("unchanged" if result.outcome == "unchanged" else "applied"), f"open_order_line:{result.line.id}"


_ROW_APPLIERS = {
    "supplier_price_list": _apply_price_row,
    "inventory": _apply_inventory_row,
    "sales": _apply_sales_row,
    "open_orders": _apply_open_order_row,
}


def apply_import(session: Session, *, tenant_id: uuid.UUID, import_id: uuid.UUID) -> Import:
    imp = get_import(session, tenant_id=tenant_id, import_id=import_id, for_update=True)
    if imp.status in ("applied", "rejected", "failed"):
        return imp  # already done: a retried job is a no-op
    if imp.status not in ("confirmed", "applying"):
        raise DomainError(f"Import {imp.id} is {imp.status}, not confirmed")
    try:
        actor = tenancy.actor_for(session, tenant_id=tenant_id, user_id=imp.confirmed_by_user_id)
    except DomainError as exc:
        imp.status, imp.failure = "failed", f"The person who confirmed this import can no longer apply it: {exc}"
        session.flush()
        return imp
    imp.status = "applying"
    session.flush()

    ev = evaluate(session, imp)
    if ev.blocking:
        imp.status, imp.failure = "failed", "Mapping no longer valid: " + ", ".join(ev.blocking)
        session.flush()
        return imp
    ctx = ev.context
    pinned = {row.row_number: (row.status, row.confirmed_digest, row.errors) for row in _rows(session, imp)}
    statuses: dict[int, tuple[str, list, str | None]] = {}
    valid: list[kinds.RowResult] = []
    drifted = 0
    for r in ev.rows:
        status, digest, confirmed_errors = pinned[r.row_number]
        if status == "error":
            # Left out at confirmation; never applied even if it would pass now.
            statuses[r.row_number] = ("error", confirmed_errors, None)
            continue
        if r.errors:
            statuses[r.row_number] = ("error", r.errors, None)
        elif r.digest != digest:
            # Data changed between confirmation and apply (e.g. a pack size was edited,
            # a barcode re-linked). Apply only what the person actually saw.
            drifted += 1
            statuses[r.row_number] = ("error", [{"column": "", "message":
                "This row would now be applied differently than when it was confirmed; upload the file again to review"}], None)
        else:
            valid.append(r)

    newly_bad = [n for n, (status, _, _) in statuses.items() if status == "error" and pinned[n][0] != "error"]
    if newly_bad and not imp.accept_row_errors:
        # The person agreed to all-or-nothing; something changed, so apply nothing.
        imp.status = "failed"
        imp.failure = (f"{len(newly_bad)} rows changed or now fail since confirmation; nothing was applied. "
                       "Upload the file again to review.")
        imp.summary = {**imp.summary, "changed_since_confirmation": drifted}
        mark_rows(session, imp, statuses)
        session.flush()
        return imp

    applier = _ROW_APPLIERS[imp.kind]
    # Outer savepoint: without consent to partial imports, one failing row undoes all rows.
    everything = session.begin_nested()
    apply_errors = 0
    for r in valid:
        savepoint = session.begin_nested()
        try:
            outcome, ref = applier(session, imp, ctx, actor, r)
            savepoint.commit()
            statuses[r.row_number] = (outcome, r.warnings if outcome == "skipped" else [], ref)
        except (DomainError, SQLAlchemyError) as exc:
            # One bad row (a rule, or a value the database refuses) is isolated in its savepoint.
            savepoint.rollback()
            apply_errors += 1
            message = str(exc) if isinstance(exc, DomainError) else f"Could not be saved ({type(exc).__name__})"
            statuses[r.row_number] = ("error", [{"column": "", "message": message}], None)
    if apply_errors and not imp.accept_row_errors:
        everything.rollback()
        session.expire_all()
        imp = get_import(session, tenant_id=tenant_id, import_id=import_id, for_update=True)
        imp.status = "failed"
        imp.failure = f"{apply_errors} rows could not be applied; nothing was applied. Fix them and upload again."
        failed = {n: st for n, st in statuses.items() if st[0] == "error"}
        mark_rows(session, imp, failed)
        session.flush()
        return imp
    everything.commit()

    if imp.kind == "open_orders" and ctx.settings.complete_scope in ("suppliers_in_file", "all_suppliers"):
        # A complete report closes older open lines it no longer shows for every supplier in its
        # declared scope — except suppliers with rows that failed ("missing" may mean "unreadable").
        by_supplier: dict[uuid.UUID, set[tuple[str, uuid.UUID]]] = defaultdict(set)
        if ctx.settings.complete_scope == "all_suppliers":
            for supplier in ctx.suppliers_by_name.values():
                by_supplier[supplier.id]  # every supplier is in scope, even with no rows
        failed_suppliers = {r.values.get("supplier_id") for r in ev.rows if statuses.get(r.row_number, ("",))[0] == "error"}
        for r in valid:
            by_supplier[r.values["supplier_id"]].add((r.values["po_number"], r.values["variant_id"]))
        closed = 0
        for supplier_id, listed in by_supplier.items():
            if supplier_id in failed_suppliers or None in failed_suppliers:
                continue
            closed += open_orders.close_missing_from_report(
                session, tenant_id=tenant_id, actor=actor, supplier_id=supplier_id,
                location_id=uuid.UUID(imp.context["location_id"]), listed=listed,
                reported_at=ctx.settings.as_of, source_ref=f"import:{imp.id}",
            )
        imp.summary = {**imp.summary, "closed_missing_lines": closed}

    if imp.kind == "sales" and not any(st[0] == "error" for st in statuses.values()):
        # The person declared the export period; with every row recorded, days in it
        # without a row are zero-sales days. (With row errors the period stays uncovered.)
        sales.record_coverage(
            session, tenant_id=tenant_id, actor=actor, location_id=uuid.UUID(imp.context["location_id"]),
            source_system=imp.context["source_system"], source_ref=f"import:{imp.id}",
            starts_on=ctx.settings.period_start, ends_on=ctx.settings.period_end,
        )

    mark_rows(session, imp, statuses)
    counts: dict[str, int] = defaultdict(int)
    for status, _, _ in statuses.values():
        counts[status] += 1
    imp.status = "applied"
    imp.applied_at = _now()
    imp.summary = {**imp.summary, "applied_counts": dict(counts), "changed_since_confirmation": drifted}
    imp.updated_at = _now()
    session.flush()
    audit.record(
        session, tenant_id=tenant_id, actor=actor, action="import.applied", object_type="import",
        object_id=imp.id, after={"counts": dict(counts)},
    )
    return imp
