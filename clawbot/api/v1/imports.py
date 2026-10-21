from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.domain import inventory, open_orders, sales
from clawbot.domain.errors import ValidationFailed
from clawbot.domain.imports import service
from clawbot.domain.imports.export import to_csv
from clawbot.domain.imports.files import MAX_FILE_BYTES
from clawbot.schemas.imports import (
    ConfirmImport,
    SalesSource,
    ImportKind,
    ImportOut,
    MappingUpdate,
    OpenOrderLineOut,
    RejectImport,
    SalesLineOut,
    SnapshotOut,
)

router = APIRouter(tags=["imports"])


@router.post("/imports", response_model=ImportOut, status_code=201)
def post_import(
    response: Response,
    file: UploadFile = File(...),
    kind: ImportKind = Form(...),
    supplier_id: uuid.UUID | None = Form(None),
    location_id: uuid.UUID | None = Form(None),
    source_system: SalesSource | None = Form(None, description="Origin of sales rows; the same origin dedupes with the POS later"),
    session: Session = DbSession,
    ctx: TenantContext = Depends(require_permission("import.upload")),
) -> ImportOut:
    """Upload a CSV/XLSX. Nothing is applied until the mapping is confirmed. Same file again → 200 with the existing import."""
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValidationFailed(f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
    context = {k: v for k, v in {"supplier_id": supplier_id, "location_id": location_id,
                                 "source_system": source_system}.items() if v is not None}
    uploaded = service.create_import(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, kind=kind, file_name=file.filename or "upload",
        content=content, context=context,
    )
    if not uploaded.created:
        response.status_code = 200
    return ImportOut.model_validate(uploaded.imp)


@router.get("/imports", response_model=list[ImportOut])
def get_imports(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> list[ImportOut]:
    return [ImportOut.model_validate(i) for i in service.list_imports(session, tenant_id=ctx.tenant_id)]


@router.get("/imports/{import_id}", response_model=ImportOut)
def get_import(import_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> ImportOut:
    return ImportOut.model_validate(service.get_import(session, tenant_id=ctx.tenant_id, import_id=import_id))


@router.get("/imports/{import_id}/preview")
def get_preview(
    import_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=200),
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """How each row will be read under the current mapping, plus anything blocking confirmation."""
    return service.preview(session, tenant_id=ctx.tenant_id, import_id=import_id, limit=limit)


@router.put("/imports/{import_id}/mapping", response_model=ImportOut)
def put_mapping(
    import_id: uuid.UUID,
    body: MappingUpdate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(require_permission("import.draft_mapping")),
) -> ImportOut:
    imp = service.update_mapping(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, import_id=import_id, expected_revision=body.revision,
        columns=body.columns, settings=body.settings,
    )
    return ImportOut.model_validate(imp)


@router.post("/imports/{import_id}/confirm-mapping", response_model=ImportOut, status_code=202)
def post_confirm(
    import_id: uuid.UUID,
    body: ConfirmImport,
    session: Session = DbSession,
    ctx: TenantContext = Depends(require_permission("import.confirm")),
) -> ImportOut:
    """Accept the previewed mapping. Applying runs as a job; poll GET /imports/{id} for `applied`."""
    imp = service.confirm(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, import_id=import_id, expected_revision=body.revision,
        accept_row_errors=body.accept_row_errors, declared=body.declared,
    )
    return ImportOut.model_validate(imp)


@router.post("/imports/{import_id}/reject", response_model=ImportOut)
def post_reject(
    import_id: uuid.UUID,
    body: RejectImport,
    session: Session = DbSession,
    ctx: TenantContext = Depends(require_permission("import.upload")),
) -> ImportOut:
    imp = service.reject(session, tenant_id=ctx.tenant_id, actor=ctx.actor, import_id=import_id, reason=body.reason)
    return ImportOut.model_validate(imp)


@router.get("/imports/{import_id}/errors.csv")
def get_errors_csv(import_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> Response:
    """Rows with errors, ready to fix in a spreadsheet. Cells are escaped against formula injection."""
    imp, rows = service.error_rows(session, tenant_id=ctx.tenant_id, import_id=import_id)
    body = to_csv(
        ["row", "column", "problem", *imp.header],
        ([row.row_number, e.get("column", ""), e.get("message", ""), *row.cells] for row, errors in rows for e in errors),
    )
    return Response(
        content=body, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="import-{imp.id}-errors.csv"'},
    )


@router.get("/sales-lines", response_model=list[SalesLineOut])
def get_sales_lines(
    variant_id: uuid.UUID | None = None,
    limit: int = Query(500, ge=1, le=5000),
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[SalesLineOut]:
    lines = sales.list_sales_lines(session, tenant_id=ctx.tenant_id, variant_id=variant_id, limit=limit)
    return [SalesLineOut.model_validate(l) for l in lines]


@router.get("/inventory-snapshots", response_model=list[SnapshotOut])
def get_snapshots(
    location_id: uuid.UUID | None = None, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> list[SnapshotOut]:
    """Latest reported count per item and location."""
    return [SnapshotOut.model_validate(s) for s in inventory.latest_snapshots(session, tenant_id=ctx.tenant_id, location_id=location_id)]


@router.get("/open-orders", response_model=list[OpenOrderLineOut])
def get_open_orders(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> list[OpenOrderLineOut]:
    return [OpenOrderLineOut.model_validate(l) for l in open_orders.list_open_order_lines(session, tenant_id=ctx.tenant_id)]
