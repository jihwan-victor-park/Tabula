from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.api.v1.suppliers import offer_out
from clawbot.domain import catalog, matching, suppliers, tenancy
from clawbot.schemas.catalog import (
    CandidateOut,
    ExternalMappingCreate,
    ExternalMappingOut,
    MappingDecision,
    MatchRequest,
    MatchResultOut,
    ProductCreate,
    ProductOut,
    VariantCreate,
    VariantOut,
    VariantUpdate,
)
from clawbot.schemas.core import LocationCreate, LocationOut
from clawbot.schemas.suppliers import OfferOut

router = APIRouter(tags=["catalog"])

_can_edit_locations = require_permission("location.edit")
_can_edit_catalog = require_permission("catalog.edit")
_can_propose_mapping = require_permission("mapping.propose")
_can_decide_mapping = require_permission("mapping.decide")


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


@router.get("/locations", response_model=list[LocationOut])
def get_locations(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> list[LocationOut]:
    return [LocationOut.model_validate(l) for l in tenancy.list_locations(session, tenant_id=ctx.tenant_id)]


@router.post("/locations", response_model=LocationOut, status_code=201)
def post_location(
    body: LocationCreate, session: Session = DbSession, ctx: TenantContext = Depends(_can_edit_locations)
) -> LocationOut:
    location = tenancy.create_location(session, tenant_id=ctx.tenant_id, actor=ctx.actor, **body.model_dump())
    return LocationOut.model_validate(location)


# ---------------------------------------------------------------------------
# Products and variants
# ---------------------------------------------------------------------------


@router.get("/products", response_model=list[ProductOut])
def get_products(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> list[ProductOut]:
    return [ProductOut.model_validate(p) for p in catalog.list_products(session, tenant_id=ctx.tenant_id)]


@router.post("/products", response_model=ProductOut, status_code=201)
def post_product(
    body: ProductCreate, session: Session = DbSession, ctx: TenantContext = Depends(_can_edit_catalog)
) -> ProductOut:
    product = catalog.create_product(session, tenant_id=ctx.tenant_id, actor=ctx.actor, **body.model_dump())
    return ProductOut.model_validate(product)


@router.get("/variants", response_model=list[VariantOut])
def get_variants(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> list[VariantOut]:
    return [VariantOut.model_validate(v) for v in catalog.list_variants(session, tenant_id=ctx.tenant_id)]


@router.get("/variants/{variant_id}", response_model=VariantOut)
def get_variant(
    variant_id: uuid.UUID, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> VariantOut:
    return VariantOut.model_validate(catalog.get_variant(session, tenant_id=ctx.tenant_id, variant_id=variant_id))


@router.post("/variants", response_model=VariantOut, status_code=201)
def post_variant(
    body: VariantCreate, session: Session = DbSession, ctx: TenantContext = Depends(_can_edit_catalog)
) -> VariantOut:
    variant = catalog.create_variant(session, tenant_id=ctx.tenant_id, actor=ctx.actor, **body.model_dump())
    return VariantOut.model_validate(variant)


@router.patch("/variants/{variant_id}", response_model=VariantOut)
def patch_variant(
    variant_id: uuid.UUID,
    body: VariantUpdate,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_edit_catalog),
) -> VariantOut:
    """Only name, barcode and status are editable; a different size or pack is a new variant."""
    fields = body.model_dump(exclude_unset=True, exclude={"version"})
    variant = catalog.update_variant(
        session,
        tenant_id=ctx.tenant_id,
        actor=ctx.actor,
        variant_id=variant_id,
        expected_version=body.version,
        **fields,
    )
    return VariantOut.model_validate(variant)


@router.get("/variants/{variant_id}/offers", response_model=list[OfferOut])
def get_variant_offers(
    variant_id: uuid.UUID,
    location_id: uuid.UUID | None = None,
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[OfferOut]:
    """Supplier items for this variant and why each can or cannot be ordered."""
    offers = suppliers.offers_for_variant(session, tenant_id=ctx.tenant_id, variant_id=variant_id, location_id=location_id)
    return [offer_out(o) for o in offers]


# ---------------------------------------------------------------------------
# Identity matching and external mappings
# ---------------------------------------------------------------------------


@router.post("/item-matches", response_model=MatchResultOut)
def post_item_match(
    body: MatchRequest, session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)
) -> MatchResultOut:
    """Resolve identifiers to a variant. Read-only: never creates or confirms a mapping."""
    result = matching.resolve_item(session, tenant_id=ctx.tenant_id, **body.model_dump())
    return MatchResultOut(
        variant_id=result.variant_id,
        method=result.method,
        needs_review=result.needs_review,
        ambiguous=result.ambiguous,
        conflicts=result.conflicts,
        candidates=[
            CandidateOut(variant_id=c.variant_id, sku=c.sku, name=c.name, score=c.score, warnings=list(c.warnings))
            for c in result.candidates
        ],
    )


@router.get("/external-mappings", response_model=list[ExternalMappingOut])
def get_external_mappings(
    status: Literal["suggested", "confirmed", "rejected"] | None = None,
    session: Session = DbSession,
    ctx: TenantContext = Depends(get_tenant_context),
) -> list[ExternalMappingOut]:
    mappings = catalog.list_external_mappings(session, tenant_id=ctx.tenant_id, status=status)
    return [ExternalMappingOut.model_validate(m) for m in mappings]


@router.post("/external-mappings", response_model=ExternalMappingOut, status_code=201)
def post_external_mapping(
    body: ExternalMappingCreate, session: Session = DbSession, ctx: TenantContext = Depends(_can_propose_mapping)
) -> ExternalMappingOut:
    """Proposals are always `suggested`; a person confirms them via /decision."""
    mapping = catalog.propose_external_mapping(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, **body.model_dump()
    )
    return ExternalMappingOut.model_validate(mapping)


@router.post("/external-mappings/{mapping_id}/decision", response_model=ExternalMappingOut)
def post_external_mapping_decision(
    mapping_id: uuid.UUID,
    body: MappingDecision,
    session: Session = DbSession,
    ctx: TenantContext = Depends(_can_decide_mapping),
) -> ExternalMappingOut:
    mapping = catalog.decide_external_mapping(
        session,
        tenant_id=ctx.tenant_id,
        actor=ctx.actor,
        mapping_id=mapping_id,
        decision=body.decision,
        expected_variant_id=body.variant_id,
        reason=body.reason,
    )
    return ExternalMappingOut.model_validate(mapping)
