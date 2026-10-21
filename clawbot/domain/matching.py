"""
Item identity resolution (spec 6.1).

Deterministic identifiers are tried in priority order:
  1. confirmed external mapping (provider item ID)
  2. merchant SKU (exact)
  3. GTIN (check-digit valid, compared as GTIN-14) / exact raw barcode if unique
  4. confirmed supplier SKU mapping
The first hit resolves the item. Hits from lower-priority identifiers that point
at a *different* variant are reported as conflicts so the caller can route the
row to review instead of trusting it.

Text similarity never resolves anything; it only produces candidates, flagged
when size or pack count in the names disagree (50 ml vs 100 ml, 1 vs 12-pack).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clawbot.domain.catalog import SIZE_UNITS
from clawbot.domain.gtin import normalize_gtin
from clawbot.persistence.models import ExternalItemMapping, SupplierItem, Variant

CANDIDATE_LIMIT = 5
CANDIDATE_MIN_SCORE = 0.55
TRGM_SHORTLIST = 25
TRGM_MIN_SIMILARITY = 0.2

# "1,000ml" is a thousands separator; "1,5 l" is a decimal comma.
_SIZE_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)\s*(fl\.?\s*oz|ml|l|kg|g|oz|lbs?)\b", re.IGNORECASE
)
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_COUNT_RE = re.compile(
    r"(?:(\d+)\s*(?:-?\s*)(?:ct|count|pk|pack|pcs|piece|pieces|입|개입)\b)|(?:\b(\d+)\s*x\b)|(?:\bx\s*(\d+)\b)",
    re.IGNORECASE,
)
_UNIT_ALIASES = {"lbs": "lb", "fl oz": "fl_oz", "fl.oz": "fl_oz", "floz": "fl_oz", "fl. oz": "fl_oz"}


@dataclass(frozen=True)
class Candidate:
    variant_id: uuid.UUID
    sku: str
    name: str
    score: float
    warnings: tuple[str, ...]


@dataclass
class MatchResult:
    variant_id: uuid.UUID | None = None
    method: str | None = None
    conflicts: list[dict[str, str]] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    ambiguous: bool = False  # an identifier matched more than one variant

    @property
    def needs_review(self) -> bool:
        return self.variant_id is None or bool(self.conflicts) or self.ambiguous


def _sizes(text: str) -> set[tuple[str, Decimal]]:
    out = set()
    for value, unit in _SIZE_RE.findall(text):
        unit = re.sub(r"\s+", " ", unit.lower())
        unit = _UNIT_ALIASES.get(unit, unit)
        if unit not in SIZE_UNITS:
            continue
        dim, factor = SIZE_UNITS[unit]
        number = value.replace(",", "") if _THOUSANDS.fullmatch(value) else value.replace(",", ".")
        out.add((dim, (Decimal(number) * factor).quantize(Decimal("1"))))
    return out


def _counts(text: str) -> set[int]:
    return {int(n) for groups in _COUNT_RE.findall(text) for n in groups if n}


def _variant_sizes(v: Variant) -> set[tuple[str, Decimal]]:
    if v.size_value is not None and v.size_unit in SIZE_UNITS:
        dim, factor = SIZE_UNITS[v.size_unit]
        return {(dim, (v.size_value * factor).quantize(Decimal("1")))}
    return _sizes(v.name)


def _variant_counts(v: Variant) -> set[int]:
    return {v.pack_count} if v.pack_count > 1 else (_counts(v.name) or {1})


def _normalize_name(text: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", text.lower()).strip()


def text_candidates(session: Session, *, tenant_id: uuid.UUID, name: str) -> list[Candidate]:
    """Rank active variants by name similarity. Candidates are suggestions only."""
    target = _normalize_name(name)
    if not target:
        return []
    their_sizes, their_counts = _sizes(name), _counts(name) or {1}
    scored: list[Candidate] = []
    # pg_trgm narrows the field with an index; SequenceMatcher then scores the shortlist.
    similarity = func.similarity(func.lower(Variant.name), target)
    shortlist = session.scalars(
        select(Variant)
        .where(Variant.tenant_id == tenant_id, Variant.status == "active", similarity > TRGM_MIN_SIMILARITY)
        .order_by(similarity.desc())
        .limit(TRGM_SHORTLIST)
    )
    for v in shortlist:
        score = SequenceMatcher(None, target, _normalize_name(v.name)).ratio()
        if score < CANDIDATE_MIN_SCORE:
            continue
        warnings = []
        ours = _variant_sizes(v)
        if their_sizes and ours and their_sizes != ours:
            warnings.append("size_conflict")
        if their_counts != _variant_counts(v):
            warnings.append("pack_count_conflict")
        scored.append(Candidate(v.id, v.sku, v.name, round(score, 3), tuple(warnings)))
    scored.sort(key=lambda c: (bool(c.warnings), -c.score))
    return scored[:CANDIDATE_LIMIT]


def resolve_item(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source_system: str | None = None,
    source_account: str = "",
    external_id: str | None = None,
    sku: str | None = None,
    barcode: str | None = None,
    supplier_id: uuid.UUID | None = None,
    supplier_sku: str | None = None,
    name: str | None = None,
) -> MatchResult:
    hits: list[tuple[str, uuid.UUID]] = []
    result = MatchResult()

    if source_system and external_id:
        variant_id = session.scalars(
            select(ExternalItemMapping.variant_id).where(
                ExternalItemMapping.tenant_id == tenant_id,
                ExternalItemMapping.source_system == source_system,
                ExternalItemMapping.source_account == source_account,
                ExternalItemMapping.external_id == external_id,
                ExternalItemMapping.status == "confirmed",
            )
        ).one_or_none()
        if variant_id:
            hits.append(("provider_id", variant_id))

    if sku and sku.strip():
        variant_id = session.scalars(
            select(Variant.id).where(Variant.tenant_id == tenant_id, Variant.sku == sku.strip())
        ).one_or_none()
        if variant_id:
            hits.append(("merchant_sku", variant_id))

    if barcode and barcode.strip():
        gtin = normalize_gtin(barcode)
        if gtin:
            variant_id = session.scalars(
                select(Variant.id).where(Variant.tenant_id == tenant_id, Variant.gtin == gtin)
            ).one_or_none()
            if variant_id:
                hits.append(("gtin", variant_id))
        else:
            ids = list(
                session.scalars(
                    select(Variant.id).where(Variant.tenant_id == tenant_id, Variant.barcode == barcode.strip())
                )
            )
            if len(ids) == 1:
                hits.append(("barcode", ids[0]))
            elif len(ids) > 1:
                result.ambiguous = True

    if supplier_id and supplier_sku:
        variant_id = session.scalars(
            select(SupplierItem.variant_id).where(
                SupplierItem.tenant_id == tenant_id,
                SupplierItem.supplier_id == supplier_id,
                SupplierItem.supplier_sku == supplier_sku.strip(),
                SupplierItem.mapping_status == "confirmed",
            )
        ).one_or_none()
        if variant_id:
            hits.append(("supplier_sku", variant_id))

    if hits:
        result.method, result.variant_id = hits[0]
        result.conflicts = [
            {"method": method, "variant_id": str(vid)} for method, vid in hits[1:] if vid != result.variant_id
        ]
    elif name:
        result.candidates = text_candidates(session, tenant_id=tenant_id, name=name)
    return result


class BulkResolver:
    """
    resolve_item() for many rows: the tenant's identifiers are loaded once, then
    each row resolves in memory with the same priority and conflict rules
    (merchant SKU → GTIN / unique raw barcode → confirmed supplier SKU).
    Provider-ID mappings are not used here; imports carry no provider IDs.
    """

    def __init__(self, session: Session, *, tenant_id: uuid.UUID):
        self.by_sku: dict[str, uuid.UUID] = {}
        self.by_gtin: dict[str, uuid.UUID] = {}
        self.by_barcode: dict[str, list[uuid.UUID]] = {}
        for vid, sku, gtin, barcode in session.execute(
            select(Variant.id, Variant.sku, Variant.gtin, Variant.barcode).where(Variant.tenant_id == tenant_id)
        ):
            self.by_sku[sku] = vid
            if gtin:
                self.by_gtin[gtin] = vid
            if barcode:
                self.by_barcode.setdefault(barcode, []).append(vid)
        self.by_supplier_sku: dict[tuple[uuid.UUID, str], uuid.UUID] = {
            (sid, ssku): vid
            for sid, ssku, vid in session.execute(
                select(SupplierItem.supplier_id, SupplierItem.supplier_sku, SupplierItem.variant_id).where(
                    SupplierItem.tenant_id == tenant_id, SupplierItem.mapping_status == "confirmed"
                )
            )
        }

    def add_variant(self, variant: Variant) -> None:
        self.by_sku[variant.sku] = variant.id
        if variant.gtin:
            self.by_gtin[variant.gtin] = variant.id

    def resolve(
        self,
        *,
        sku: str | None = None,
        barcode: str | None = None,
        supplier_id: uuid.UUID | None = None,
        supplier_sku: str | None = None,
    ) -> MatchResult:
        hits: list[tuple[str, uuid.UUID]] = []
        result = MatchResult()
        if sku and sku.strip() and sku.strip() in self.by_sku:
            hits.append(("merchant_sku", self.by_sku[sku.strip()]))
        if barcode and barcode.strip():
            gtin = normalize_gtin(barcode)
            if gtin:
                if gtin in self.by_gtin:
                    hits.append(("gtin", self.by_gtin[gtin]))
            else:
                ids = self.by_barcode.get(barcode.strip(), [])
                if len(ids) == 1:
                    hits.append(("barcode", ids[0]))
                elif len(ids) > 1:
                    result.ambiguous = True
        if supplier_id and supplier_sku and (supplier_id, supplier_sku.strip()) in self.by_supplier_sku:
            hits.append(("supplier_sku", self.by_supplier_sku[(supplier_id, supplier_sku.strip())]))
        if hits:
            result.method, result.variant_id = hits[0]
            result.conflicts = [
                {"method": method, "variant_id": str(vid)} for method, vid in hits[1:] if vid != result.variant_id
            ]
        return result
