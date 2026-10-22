"""
Import lifecycle: upload → (draft/edit mapping) → preview → confirm → apply job.

Nothing reaches inventory, sales, suppliers or prices until a person confirms
the mapping at the exact revision they previewed. The same file uploaded again
returns the existing import instead of a second copy.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.domain import audit, outbox, suppliers, tenancy
from clawbot.domain.errors import NotFound, StaleVersion, StateConflict, ValidationFailed
from clawbot.domain.imports import kinds
from clawbot.domain.imports.files import parse_file
from clawbot.domain.matching import BulkResolver, text_candidates
from clawbot.persistence.models import IMPORT_KINDS, SALES_SOURCES, Import, ImportRow, Supplier, SupplierItem
from clawbot.policies.permissions import Actor, authorize

APPLY_TOPIC = "import.apply"

# What the confirming person must be allowed to do for each kind.
CONFIRM_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "supplier_price_list": ("supplier_item.edit", "price.record"),
    "inventory": ("inventory.snapshot", "inventory.move"),
    "sales": ("sales.record",),
    "open_orders": ("orders.record_external",),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _snapshot(imp: Import) -> dict[str, Any]:
    return {"status": imp.status, "mapping": imp.mapping, "mapping_revision": imp.mapping_revision}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def _uuid(value: Any, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise ValidationFailed(f"{name} must be a UUID")


def _validate_context(session: Session, tenant_id: uuid.UUID, kind: str, context: dict[str, Any]) -> dict[str, Any]:
    spec = kinds.SPECS[kind]
    missing = [k for k in spec.context_required if not context.get(k)]
    if missing:
        raise ValidationFailed(f"{spec.label} imports need: {', '.join(missing)}")
    out: dict[str, Any] = {}
    if "supplier_id" in spec.context_required:
        supplier = suppliers.get_supplier(session, tenant_id=tenant_id, supplier_id=_uuid(context["supplier_id"], "supplier_id"))
        out["supplier_id"] = str(supplier.id)
    if "location_id" in spec.context_required:
        location = tenancy.get_location(session, tenant_id=tenant_id, location_id=_uuid(context["location_id"], "location_id"))
        out["location_id"] = str(location.id)
    if "source_system" in spec.context_required:
        source = str(context["source_system"]).strip().lower()
        if source not in SALES_SOURCES:
            raise ValidationFailed(f"source_system must be one of {', '.join(SALES_SOURCES)}")
        out["source_system"] = source
    return out


def _context_key(context: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def _live_import(session: Session, tenant_id: uuid.UUID, kind: str, sha: str, context_key: str) -> Import | None:
    return session.scalars(
        select(Import).where(
            Import.tenant_id == tenant_id, Import.kind == kind, Import.file_sha256 == sha,
            Import.context_key == context_key, Import.status.not_in(("rejected", "failed")),
        )
    ).one_or_none()


@dataclass(frozen=True)
class Uploaded:
    imp: Import
    created: bool


def create_import(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    kind: str,
    file_name: str,
    content: bytes,
    context: dict[str, Any],
) -> Uploaded:
    authorize(actor, "import.upload")
    if kind not in IMPORT_KINDS:
        raise ValidationFailed(f"Unknown import kind: {kind}")
    context = _validate_context(session, tenant_id, kind, context)
    context_key = _context_key(context)
    parsed = parse_file(file_name, content)

    # Same file, same supplier/location/origin, still live → the same import. A
    # different location, or a previously rejected/failed upload, starts fresh;
    # row-level keys still stop anything being applied twice.
    existing = _live_import(session, tenant_id, kind, parsed.sha256, context_key)
    if existing is not None:
        return Uploaded(existing, False)

    import_id = uuid.uuid4()
    inserted = session.execute(
        insert(Import)
        .values(
            id=import_id, tenant_id=tenant_id, kind=kind, status="uploaded", file_name=file_name[:255],
            file_sha256=parsed.sha256, file_size=len(content), file_format=parsed.file_format,
            header=parsed.header, row_count=len(parsed.rows), context=context, context_key=context_key,
            mapping={"columns": kinds.draft_columns(kind, parsed.header), "settings": {}},
            mapping_revision=1, accept_row_errors=False, summary={}, created_by_user_id=actor.user_id,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "kind", "file_sha256", "context_key"],
            # Literal SQL, not bound parameters: once psycopg prepares the statement,
            # a parameterised predicate no longer matches the partial index.
            index_where=text("status NOT IN ('rejected', 'failed')"),
        )
        .returning(Import.id)
    ).scalar_one_or_none()
    if inserted is None:  # the same file was uploaded concurrently
        imp = _live_import(session, tenant_id, kind, parsed.sha256, context_key)
        assert imp is not None
        return Uploaded(imp, False)

    session.execute(
        insert(ImportRow),
        [
            {"id": uuid.uuid4(), "tenant_id": tenant_id, "import_id": import_id, "row_number": n, "cells": cells,
             "status": "pending", "errors": []}
            for n, cells in parsed.rows
        ],
    )
    imp = session.get(Import, import_id)
    assert imp is not None
    audit.record(
        session, tenant_id=tenant_id, actor=actor, action="import.uploaded", object_type="import",
        object_id=import_id, after={"kind": kind, "file_name": file_name, "rows": len(parsed.rows),
                                    "sha256": parsed.sha256, "context": context},
    )
    return Uploaded(imp, True)


def get_import(session: Session, *, tenant_id: uuid.UUID, import_id: uuid.UUID, for_update: bool = False) -> Import:
    stmt = select(Import).where(Import.tenant_id == tenant_id, Import.id == import_id)
    if for_update:
        stmt = stmt.with_for_update()
    imp = session.scalars(stmt).one_or_none()
    if imp is None:
        raise NotFound(f"Import not found: {import_id}")
    return imp


def list_imports(session: Session, *, tenant_id: uuid.UUID, limit: int = 50) -> list[Import]:
    return list(
        session.scalars(
            select(Import).where(Import.tenant_id == tenant_id).order_by(Import.created_at.desc()).limit(limit)
        )
    )


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def update_mapping(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    import_id: uuid.UUID,
    expected_revision: int,
    columns: dict[str, str],
    settings: dict[str, Any],
) -> Import:
    """Replace the mapping. Agents may draft; every change bumps the revision a person must confirm."""
    authorize(actor, "import.draft_mapping")
    imp = get_import(session, tenant_id=tenant_id, import_id=import_id, for_update=True)
    if imp.status != "uploaded":
        raise StateConflict(f"Mapping can only change before confirmation (import is {imp.status})")
    if imp.mapping_revision != expected_revision:
        raise StaleVersion(f"Mapping is at revision {imp.mapping_revision}, not {expected_revision}")
    spec = kinds.SPECS[imp.kind]
    known = {f.name for f in spec.fields}
    unknown_fields = sorted(set(columns) - known)
    unknown_columns = sorted(set(columns.values()) - set(imp.header))
    if unknown_fields or unknown_columns:
        raise ValidationFailed(
            "Mapping refers to unknown fields or columns",
            details={"unknown_fields": unknown_fields, "unknown_columns": unknown_columns},
        )
    if len(set(columns.values())) != len(columns):
        raise ValidationFailed("Each column can be used for one field only")
    kinds.parse_settings(imp.kind, settings)  # validate
    if imp.kind == "open_orders" and settings.get("supplier_id"):
        suppliers.get_supplier(session, tenant_id=tenant_id, supplier_id=_uuid(settings["supplier_id"], "supplier_id"))

    before = _snapshot(imp)
    imp.mapping = {"columns": dict(columns), "settings": settings}
    imp.mapping_revision += 1
    imp.updated_at = _now()
    session.flush()
    audit.record(
        session, tenant_id=tenant_id, actor=actor, action="import.mapping_updated", object_type="import",
        object_id=imp.id, before=before, after=_snapshot(imp),
    )
    return imp


# ---------------------------------------------------------------------------
# Evaluation (shared by preview, confirm and apply)
# ---------------------------------------------------------------------------


@dataclass
class Evaluation:
    blocking: list[str]
    rows: list[kinds.RowResult] = field(default_factory=list)
    context: kinds.Context | None = None

    @property
    def error_rows(self) -> list[kinds.RowResult]:
        return [r for r in self.rows if r.errors]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "rows": len(self.rows),
            "valid": sum(1 for r in self.rows if not r.errors),
            "with_errors": len(self.error_rows),
            "with_warnings": sum(1 for r in self.rows if r.warnings and not r.errors),
        }


def build_context(session: Session, imp: Import) -> tuple[kinds.Context, list[str]]:
    settings = kinds.parse_settings(imp.kind, imp.mapping.get("settings", {}))
    columns = imp.mapping.get("columns", {})
    ctx = kinds.Context(
        kind=imp.kind, columns=columns, settings=settings,
        header_index={h: i for i, h in enumerate(imp.header)}, timezone="UTC",
        resolver=BulkResolver(session, tenant_id=imp.tenant_id),
    )
    if "location_id" in imp.context:
        location = tenancy.get_location(session, tenant_id=imp.tenant_id, location_id=uuid.UUID(imp.context["location_id"]))
        ctx.timezone, ctx.location = location.timezone, location
    if imp.kind == "supplier_price_list":
        supplier = suppliers.get_supplier(session, tenant_id=imp.tenant_id, supplier_id=uuid.UUID(imp.context["supplier_id"]))
        ctx.currency, ctx.timezone = supplier.currency, supplier.timezone
        ctx.supplier_items = {
            i.supplier_sku: i for i in suppliers.list_supplier_items(session, tenant_id=imp.tenant_id, supplier_id=supplier.id)
        }
    if imp.kind == "open_orders":
        for s in session.scalars(select(Supplier).where(Supplier.tenant_id == imp.tenant_id)):
            ctx.suppliers_by_name[s.name.lower()] = s
            ctx.suppliers_by_name[f"id:{s.id}"] = s
        for item in session.scalars(
            select(SupplierItem).where(SupplierItem.tenant_id == imp.tenant_id, SupplierItem.mapping_status == "confirmed")
        ):
            ctx.supplier_items_by_variant.setdefault((item.supplier_id, item.variant_id), []).append(item)
    return ctx, kinds.blocking_issues(imp.kind, columns, settings)


def _rows(session: Session, imp: Import) -> Iterable[ImportRow]:
    return session.scalars(
        select(ImportRow).where(ImportRow.tenant_id == imp.tenant_id, ImportRow.import_id == imp.id).order_by(ImportRow.row_number)
    )


def evaluate(session: Session, imp: Import) -> Evaluation:
    ctx, blocking = build_context(session, imp)
    result = Evaluation(blocking=blocking, context=ctx)
    if blocking:
        return result
    interpret = kinds.INTERPRETERS[imp.kind]
    first_seen: dict[str, int] = {}
    # Sales exports without line IDs can list the same item twice in one order
    # (two separate sales, or two partial refunds). Each occurrence becomes its
    # own line, numbered in file order, so a later export lines up again.
    ordinal_lines = imp.kind == "sales" and "line_id" not in ctx.columns
    occurrences: dict[str, int] = {}
    for row in _rows(session, imp):
        r = interpret(ctx, row.row_number, row.cells)
        if ordinal_lines and r.values.get("order_id"):
            # Ordinals count every row of the file, valid or not, so a row that
            # becomes valid later cannot shift its neighbours' keys.
            occurrences[r.key] = occurrences.get(r.key, 0) + 1
            n = occurrences[r.key]
            r.values["line_key"] = f"{r.values['source_item']}:{r.values['line_type']}:{n}"
            r.values["key_scheme"] = "csv_item_ordinal"
            r.key = f"{r.key}#{n}"
        elif r.key is not None and not r.errors and not ordinal_lines:
            if r.key in first_seen:
                r.error(None, f"Duplicate of row {first_seen[r.key]}")
            else:
                first_seen[r.key] = row.row_number
                if imp.kind == "sales":
                    r.values["line_key"], r.values["key_scheme"] = r.values["line_id"], "csv_line_id"
        r.digest = row_digest(r)
        result.rows.append(r)
    return result


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value.normalize() if isinstance(value, Decimal) else value)
    return value


def row_digest(r: kinds.RowResult) -> str:
    """What a person approves for one row: its interpreted values and warnings, not the raw cells."""
    payload = {
        "values": {k: _canonical(val) for k, val in sorted(r.values.items()) if not k.startswith("_")},
        "warnings": [w["message"] for w in r.warnings],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def row_view(r: kinds.RowResult) -> dict[str, Any]:
    return {"row_number": r.row_number, "interpretation": r.interpretation, "errors": r.errors, "warnings": r.warnings}


def _with_candidates(session: Session, tenant_id: uuid.UUID, r: kinds.RowResult) -> dict[str, Any]:
    """Unidentified rows that carry a name get look-alike items to choose from (suggestions only)."""
    view = row_view(r)
    name = r.values.get("name") or r.values.get("description")
    if r.values.get("variant_id") is None and name:
        view["candidates"] = [
            {"variant_id": str(c.variant_id), "sku": c.sku, "name": c.name, "score": c.score, "warnings": list(c.warnings)}
            for c in text_candidates(session, tenant_id=tenant_id, name=name)[:3]
        ]
    return view


def preview(session: Session, *, tenant_id: uuid.UUID, import_id: uuid.UUID, limit: int = 20) -> dict[str, Any]:
    imp = get_import(session, tenant_id=tenant_id, import_id=import_id)
    ev = evaluate(session, imp)
    sample = ev.rows[:limit]
    shown = {r.row_number for r in sample}
    errors = [r for r in ev.error_rows if r.row_number not in shown][:limit]
    return {
        "import_id": str(imp.id),
        "mapping_revision": imp.mapping_revision,
        "mapping": imp.mapping,
        "fields": [{"name": f.name, "label": f.label, "required": f.required} for f in kinds.SPECS[imp.kind].fields],
        "blocking_issues": ev.blocking,
        "declared_settings": kinds.declared_view(imp.kind, ev.context.settings),
        "counts": ev.counts if not ev.blocking else None,
        "rows": [_with_candidates(session, tenant_id, r) for r in sample],
        "more_errors": [_with_candidates(session, tenant_id, r) for r in errors],
        "suggested_settings": _suggestions(session, imp, ev),
        "unused_columns": _unused(imp),
    }


_KNOWN_UNUSED = (
    (("cost", "unit cost", "case cost", "wholesale"), "Cost is read from supplier price lists — upload one per supplier to use it"),
    (("supplier", "vendor", "distributor"), "Suppliers are set up per supplier (with their price list), not from this file"),
    (("price", "retail", "msrp", "sell price"), "Selling prices are not needed for stock or order suggestions"),
    (("category", "brand", "department", "type"), "Not used yet"),
)


def _unused(imp: Import) -> list[dict[str, str]]:
    """Columns this import will not read, with why — so nothing is silently ignored."""
    mapped = set(imp.mapping.get("columns", {}).values())
    out = []
    for header in imp.header:
        if header in mapped or not header.strip():
            continue
        low = header.strip().lower()
        if imp.kind == "sales" and any(w in low for w in ("item", "name", "product", "description", "title")):
            why = "Item names come from your stock file; sales are matched by SKU or barcode"
        else:
            why = next((reason for words, reason in _KNOWN_UNUSED if any(w in low for w in words)), "Not used by this kind of file")
        out.append({"column": header, "why": why})
    return out


def _suggestions(session: Session, imp: Import, ev: Evaluation) -> dict[str, Any]:
    """
    Values the file itself suggests for settings the person must confirm (never applied by
    themselves). Sales: the first and last day that has a sale in the file — the export's real
    range can be wider (days with no sales at either end do not show up in the rows).
    """
    if ev.context.kind != "sales":
        return {}
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(getattr(ev.context.settings, "timezone", None) or ev.context.timezone)
    rows = ev.rows
    if not rows and "sold_at" in ev.context.columns:
        # Rows are not evaluated while settings are undeclared; read just the dates to suggest the period.
        rows = [kinds.INTERPRETERS["sales"](ev.context, r.row_number, r.cells) for r in _rows(session, imp)]
    days = sorted({r.values["sold_at"].astimezone(tz).date() for r in rows if r.values.get("sold_at")})
    if not days:
        return {}
    return {"period_start": days[0].isoformat(), "period_end": days[-1].isoformat(),
            "note": "First and last day with a sale in this file. If the export covers more days (with no sales), "
                    "widen the period to match the export."}


# ---------------------------------------------------------------------------
# Confirm / reject
# ---------------------------------------------------------------------------


def confirm(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    import_id: uuid.UUID,
    expected_revision: int,
    accept_row_errors: bool,
    declared: dict[str, Any] | None = None,
) -> Import:
    """
    A person accepts the mapping they previewed; applying happens in a job.
    `declared` must restate the settings that carry meaning (kinds.DECLARED_SETTINGS),
    and each row's interpretation is pinned by digest so apply cannot drift.
    """
    authorize(actor, "import.confirm")
    imp = get_import(session, tenant_id=tenant_id, import_id=import_id, for_update=True)
    for permission in CONFIRM_PERMISSIONS[imp.kind]:
        authorize(actor, permission)
    settings = kinds.parse_settings(imp.kind, imp.mapping.get("settings", {}))
    if imp.kind == "inventory" and getattr(settings, "create_missing_variants", False):
        authorize(actor, "catalog.edit")
    if imp.status != "uploaded":
        raise StateConflict(f"Import is already {imp.status}")
    if imp.mapping_revision != expected_revision:
        raise StaleVersion(
            f"Mapping changed since you reviewed it (now revision {imp.mapping_revision})",
            details={"current_revision": imp.mapping_revision},
        )
    expected = kinds.declared_view(imp.kind, settings)
    stated = dict(declared or {})
    unknown = sorted(set(stated) - set(expected))
    if unknown or not kinds.declared_matches(imp.kind, settings, stated):
        raise ValidationFailed(
            "Confirm by restating what the file means",
            details={"declared_settings_required": expected, "you_stated": stated, "unknown": unknown},
        )
    ev = evaluate(session, imp)
    if ev.blocking:
        raise ValidationFailed("Mapping is incomplete", details={"blocking_issues": ev.blocking})
    counts = ev.counts
    if counts["valid"] == 0:
        raise ValidationFailed("No row can be applied", details={"counts": counts})
    if ev.error_rows and not accept_row_errors:
        raise ValidationFailed(
            f"{counts['with_errors']} rows have errors; fix the file or accept applying only valid rows",
            details={"counts": counts, "errors": [row_view(r) for r in ev.error_rows[:20]]},
        )

    by_row = {r.row_number: r for r in ev.rows}
    for row in _rows(session, imp):
        r = by_row[row.row_number]
        row.status = "error" if r.errors else "pending"
        row.errors = r.errors
        row.confirmed_digest = None if r.errors else r.digest
    before = _snapshot(imp)
    imp.status = "confirmed"
    imp.accept_row_errors = accept_row_errors
    imp.confirmed_by_user_id = actor.user_id
    imp.confirmed_role = actor.role
    imp.confirmed_at = _now()
    imp.summary = {"confirmed_counts": counts}
    imp.updated_at = _now()
    session.flush()
    outbox.enqueue(
        session, tenant_id=tenant_id, topic=APPLY_TOPIC, operation_key=f"import:{imp.id}:apply",
        payload={"import_id": str(imp.id)}, retry_safe=True,  # applying is idempotent per row
    )
    audit.record(
        session, tenant_id=tenant_id, actor=actor, action="import.confirmed", object_type="import",
        object_id=imp.id, before=before,
        after={**_snapshot(imp), "counts": counts, "accept_row_errors": accept_row_errors, "declared": expected},
    )
    return imp


def reject(session: Session, *, tenant_id: uuid.UUID, actor: Actor, import_id: uuid.UUID, reason: str | None) -> Import:
    authorize(actor, "import.upload")
    imp = get_import(session, tenant_id=tenant_id, import_id=import_id, for_update=True)
    if imp.status != "uploaded":
        raise StateConflict(f"Only unconfirmed imports can be discarded (this one is {imp.status})")
    before = _snapshot(imp)
    imp.status = "rejected"
    imp.updated_at = _now()
    session.flush()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="import.rejected", object_type="import",
                 object_id=imp.id, before=before, after=_snapshot(imp), reason=reason)
    return imp


def error_rows(session: Session, *, tenant_id: uuid.UUID, import_id: uuid.UUID) -> tuple[Import, list[tuple[ImportRow, list]]]:
    """Rows with errors: stored ones after confirm/apply, freshly evaluated before."""
    imp = get_import(session, tenant_id=tenant_id, import_id=import_id)
    rows = list(_rows(session, imp))
    if imp.status == "uploaded":
        ev = evaluate(session, imp)
        by_number = {r.row_number: r.errors for r in ev.error_rows}
        return imp, [(row, by_number[row.row_number]) for row in rows if row.row_number in by_number]
    return imp, [(row, row.errors) for row in rows if row.status == "error"]


def mark_rows(session: Session, imp: Import, statuses: dict[int, tuple[str, list, str | None]]) -> None:
    for number, (status, errors, ref) in statuses.items():
        session.execute(
            update(ImportRow)
            .where(ImportRow.tenant_id == imp.tenant_id, ImportRow.import_id == imp.id, ImportRow.row_number == number)
            .values(status=status, errors=errors, result_ref=ref)
        )
