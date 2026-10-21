"""
What each import kind expects (spec 3.4), how columns are guessed, which
meanings a person must state explicitly, and how one row is interpreted.

Interpretation never touches the database except through the preloaded
Resolver, so a 100k-row preview stays a pure, fast pass.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field as PField, ValidationError

from clawbot.domain.imports import values as v
from clawbot.domain.units import QTY_SCALE, normalize_uom, unit_cost_per_base


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    synonyms: tuple[str, ...]
    required: bool = False


@dataclass(frozen=True)
class KindSpec:
    kind: str
    label: str
    fields: tuple[FieldSpec, ...]
    one_of: tuple[tuple[str, ...], ...] = ()  # at least one field of each group must be mapped
    context_required: tuple[str, ...] = ()

    def field(self, name: str) -> FieldSpec:
        return next(f for f in self.fields if f.name == name)


_ID_FIELDS = (
    FieldSpec("sku", "Your SKU", ("sku", "item sku", "variant sku", "our sku", "store sku", "merchant sku")),
    FieldSpec("barcode", "Barcode (UPC/EAN)", ("barcode", "upc", "ean", "gtin", "upc code")),
)

SPECS: dict[str, KindSpec] = {
    "supplier_price_list": KindSpec(
        kind="supplier_price_list",
        label="Supplier price list",
        context_required=("supplier_id",),
        fields=(
            FieldSpec("supplier_sku", "Supplier item #", ("supplier sku", "item", "item #", "item number", "item no",
                                                         "vendor sku", "product code", "item code", "code"), True),
            FieldSpec("unit_price", "Price", ("price", "cost", "unit cost", "case price", "wholesale", "unit price",
                                             "net price", "case cost"), True),
            FieldSpec("units_per_order_uom", "Units per order unit", ("case pack", "pack", "pack size", "units per case",
                                                                     "case qty", "qty per case", "casepack", "inner pack")),
            FieldSpec("order_uom", "Order unit", ("uom", "unit", "order unit", "unit of measure")),
            FieldSpec("description", "Description", ("description", "item description", "product", "product name", "name")),
            FieldSpec("merchant_sku", "Your SKU", ("our sku", "store sku", "merchant sku", "retailer sku", "your sku")),
            FieldSpec("barcode", "Barcode (UPC/EAN)", ("barcode", "upc", "ean", "gtin", "upc code")),
            FieldSpec("min_order_qty", "Minimum order (order units)", ("moq", "min qty", "minimum", "min order")),
            FieldSpec("order_multiple", "Order multiple (order units)", ("order multiple", "multiple")),
            FieldSpec("lead_time_days", "Lead time (days)", ("lead time", "lead time days", "leadtime")),
            FieldSpec("currency", "Currency", ("currency", "ccy")),
            FieldSpec("valid_from", "Price effective from", ("effective date", "valid from", "start date", "effective")),
            FieldSpec("expires_at", "Price valid until", ("expires", "valid until", "expiration", "end date", "valid to")),
        ),
    ),
    "inventory": KindSpec(
        kind="inventory",
        label="Stock count",
        context_required=("location_id",),
        one_of=(("sku", "barcode"),),
        fields=_ID_FIELDS + (
            FieldSpec("quantity", "Quantity on hand", ("quantity", "qty", "on hand", "stock", "count", "in stock",
                                                     "current quantity", "quantity on hand"), True),
            FieldSpec("name", "Item name", ("name", "item name", "product name", "description", "item")),
            FieldSpec("as_of", "Counted at", ("as of", "count date", "counted at", "timestamp", "date")),
        ),
    ),
    "sales": KindSpec(
        kind="sales",
        label="Sales history",
        context_required=("location_id", "source_system"),
        one_of=(("sku", "barcode"),),
        fields=_ID_FIELDS + (
            FieldSpec("order_id", "Transaction / order ID", ("transaction id", "order id", "order", "receipt",
                                                            "receipt number", "order number", "payment id", "ticket"), True),
            FieldSpec("sold_at", "Sold at", ("date", "datetime", "created at", "sold at", "order date", "time"), True),
            FieldSpec("quantity", "Quantity", ("qty", "quantity", "units sold", "count", "units"), True),
            FieldSpec("line_id", "Line ID", ("line id", "line item id", "item id", "line")),
            FieldSpec("unit_price", "Unit price", ("unit price", "price", "item price")),
            FieldSpec("currency", "Currency", ("currency", "ccy")),
            FieldSpec("line_type", "Sale or refund", ("event type", "transaction type", "type", "line type")),
        ),
    ),
    "open_orders": KindSpec(
        kind="open_orders",
        label="Open (not yet received) orders",
        context_required=("location_id",),
        one_of=(("sku", "barcode", "supplier_sku"),),
        fields=_ID_FIELDS + (
            FieldSpec("supplier", "Supplier", ("supplier", "vendor", "distributor", "supplier name")),
            FieldSpec("po_number", "PO number", ("po", "po number", "po #", "purchase order", "order number", "po no"), True),
            FieldSpec("supplier_sku", "Supplier item #", ("supplier sku", "vendor sku", "item #", "item number")),
            FieldSpec("outstanding_qty", "Quantity still to arrive", ("outstanding", "remaining", "qty remaining",
                                                                     "open qty", "backorder", "quantity", "qty"), True),
            FieldSpec("ordered_at", "Ordered at", ("order date", "ordered", "ordered at", "date ordered")),
            FieldSpec("expected_at", "Expected at", ("eta", "expected", "due date", "expected date", "arrival")),
            FieldSpec("confirmed", "Supplier confirmed", ("confirmed", "acknowledged", "supplier confirmed")),
        ),
    ),
}


# ---------------------------------------------------------------------------
# Settings: meanings a column name alone cannot settle
# ---------------------------------------------------------------------------


class _Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_format: Literal["MM/DD/YYYY", "DD/MM/YYYY", "YYYY/MM/DD", "MM-DD-YYYY"] | None = None
    timezone: str | None = PField(default=None, description="For times without an offset; defaults to the location's")


class PriceListSettings(_Settings):
    # None = not yet declared by a person → blocks confirmation.
    price_basis: Literal["per_order_unit", "per_base_unit"] | None = None
    units_per_order_uom: Decimal | None = PField(default=None, gt=0, description="When the file has no pack column")
    order_uom: str | None = PField(default=None, min_length=1, max_length=20, description="When the file has no unit column")
    currency: str | None = None
    price_type: Literal["price_list", "contract", "quote", "invoice"] = "price_list"
    update_pack_on_change: bool = PField(
        default=False, description="Apply pack changes from this file (un-confirms the item's mapping, retires prices)"
    )


class InventorySettings(_Settings):
    as_of: datetime | None = PField(default=None, description="When the file has no 'counted at' column")
    create_missing_variants: bool = False


class SalesSettings(_Settings):
    pass


class OpenOrderSettings(_Settings):
    quantity_unit: Literal["base", "order_unit"] | None = None  # must be declared
    supplier_id: uuid.UUID | None = None  # when the file has no supplier column


SETTINGS: dict[str, type[_Settings]] = {
    "supplier_price_list": PriceListSettings,
    "inventory": InventorySettings,
    "sales": SalesSettings,
    "open_orders": OpenOrderSettings,
}


def parse_settings(kind: str, raw: dict[str, Any]) -> _Settings:
    try:
        return SETTINGS[kind].model_validate(raw)
    except ValidationError as exc:
        from clawbot.domain.errors import ValidationFailed

        raise ValidationFailed(
            "Invalid import settings",
            details={"errors": [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]},
        )


# ---------------------------------------------------------------------------
# Column mapping draft
# ---------------------------------------------------------------------------


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9#]+", " ", text.lower()).strip()


def draft_columns(kind: str, header: list[str]) -> dict[str, str]:
    """Guess field → column from header names. Only a draft: a person confirms it."""
    spec = SPECS[kind]
    by_norm = {_norm(h): h for h in header}
    used: set[str] = set()
    columns: dict[str, str] = {}
    for f in spec.fields:
        for synonym in f.synonyms:
            column = by_norm.get(_norm(synonym))
            if column and column not in used:
                columns[f.name] = column
                used.add(column)
                break
    return columns


# ---------------------------------------------------------------------------
# Row interpretation
# ---------------------------------------------------------------------------


@dataclass
class RowResult:
    row_number: int
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    interpretation: str = ""
    key: str | None = None  # identity within the file, for duplicate detection
    digest: str | None = None  # set by evaluation; pinned at confirmation

    def error(self, column: str | None, message: str) -> None:
        self.errors.append({"column": column or "", "message": message})

    def warn(self, column: str | None, message: str) -> None:
        self.warnings.append({"column": column or "", "message": message})


@dataclass
class Context:
    """Everything interpretation needs, preloaded once per evaluation."""

    kind: str
    columns: dict[str, str]
    settings: Any
    header_index: dict[str, int]
    timezone: str
    currency: str | None = None  # price lists: the supplier's currency
    resolver: Any = None
    supplier_items: dict[str, Any] = field(default_factory=dict)  # price lists: supplier_sku → SupplierItem
    suppliers_by_name: dict[str, Any] = field(default_factory=dict)  # open orders
    supplier_items_by_variant: dict[tuple[uuid.UUID, uuid.UUID], list[Any]] = field(default_factory=dict)


_SKU = v.bounded_text(120)
_NAME = v.bounded_text(300)
_SALE_TYPES = {"", "sale", "sales", "sold", "payment", "purchase", "order"}
_REFUND_TYPES = {"refund", "refunded", "return", "returned"}


def _cell(ctx: Context, cells: list[str], name: str) -> str | None:
    column = ctx.columns.get(name)
    if column is None:
        return None
    return cells[ctx.header_index[column]]


def _parse(row: RowResult, ctx: Context, cells: list[str], name: str, parser: Callable[[str], Any],
           *, required: bool = False) -> Any:
    raw = _cell(ctx, cells, name)
    if raw is None or not raw.strip():
        if required:
            row.error(ctx.columns.get(name), f"{SPECS[ctx.kind].field(name).label} is missing")
        return None
    try:
        return parser(raw)
    except v.CellError as exc:
        row.error(ctx.columns[name], f"{SPECS[ctx.kind].field(name).label} {exc}")
        return None


def _resolve_variant(row: RowResult, ctx: Context, cells: list[str], *, supplier_id: uuid.UUID | None = None,
                     required: bool = True) -> uuid.UUID | None:
    sku = _parse(row, ctx, cells, "sku", _SKU) if "sku" in ctx.columns else None
    if ctx.kind == "supplier_price_list":
        sku = _parse(row, ctx, cells, "merchant_sku", _SKU)
    barcode = _parse(row, ctx, cells, "barcode", v.barcode)
    supplier_sku = _parse(row, ctx, cells, "supplier_sku", _SKU) if ctx.kind == "open_orders" else None
    if not (sku or barcode or supplier_sku):
        row.values["_sku_input"], row.values["_barcode_input"] = sku, barcode
        if required:
            row.error(None, "No SKU or barcode to identify the item")
        return None
    row.values["_sku_input"], row.values["_barcode_input"] = sku, barcode
    match = ctx.resolver.resolve(sku=sku, barcode=barcode, supplier_id=supplier_id, supplier_sku=supplier_sku)
    row.values["_match"] = match
    if match.ambiguous:
        row.error(ctx.columns.get("barcode"), "Barcode belongs to more than one of your items")
        return None
    if match.conflicts:
        row.error(None, "SKU and barcode point to different items: " + ", ".join(c["method"] for c in match.conflicts))
        return None
    if match.variant_id is None and required:
        row.error(ctx.columns.get("sku") or ctx.columns.get("barcode"), f"Unknown item {sku or barcode or supplier_sku!r}")
    return match.variant_id


def interpret_price_list(ctx: Context, number: int, cells: list[str]) -> RowResult:
    row = RowResult(number)
    s: PriceListSettings = ctx.settings
    supplier_sku = _parse(row, ctx, cells, "supplier_sku", _SKU, required=True)
    currency = _parse(row, ctx, cells, "currency", v.currency_code) or s.currency or ctx.currency
    if currency and ctx.currency and currency != ctx.currency:
        row.error(ctx.columns.get("currency"), f"Price is in {currency}; this supplier is billed in {ctx.currency}")
    price = _parse(row, ctx, cells, "unit_price", lambda x: v.decimal(x, currency=currency), required=True)
    if price is not None and price < 0:
        row.error(ctx.columns["unit_price"], "Price is negative")
    units = _parse(row, ctx, cells, "units_per_order_uom", v.positive_decimal) or s.units_per_order_uom
    uom = _parse(row, ctx, cells, "order_uom", v.bounded_text(20)) or s.order_uom
    uom = normalize_uom(uom) if uom else None
    if units is None:
        row.error(ctx.columns.get("units_per_order_uom"), "Units per order unit is missing (map a pack column or set a value)")
    if not uom:
        row.error(ctx.columns.get("order_uom"), "Order unit is missing (map a unit column or set a value)")
    tz = s.timezone or ctx.timezone
    valid_from = _parse(row, ctx, cells, "valid_from", lambda x: v.moment(x, date_format=s.date_format, tz=tz))
    expires_at = _parse(row, ctx, cells, "expires_at", lambda x: v.moment(x, date_format=s.date_format, tz=tz))
    moq = _parse(row, ctx, cells, "min_order_qty", v.positive_decimal)
    multiple = _parse(row, ctx, cells, "order_multiple", v.positive_decimal)
    lead = _parse(row, ctx, cells, "lead_time_days", v.integer)
    if lead is not None and lead < 0:
        row.error(ctx.columns["lead_time_days"], "Lead time is negative")
    variant_id = _resolve_variant(row, ctx, cells, required=False)

    per_order_unit = None
    if price is not None and units is not None and s.price_basis is not None:
        per_order_unit = price if s.price_basis == "per_order_unit" else price * units
        if per_order_unit != per_order_unit.quantize(QTY_SCALE):
            per_order_unit = per_order_unit.quantize(QTY_SCALE)
            row.warn(ctx.columns.get("unit_price"), f"Price per {uom} rounded to {per_order_unit}")
        each = unit_cost_per_base(per_order_unit, units)
        row.interpretation = f"{supplier_sku}: {uom} of {units.normalize():f} at {per_order_unit:.2f} {currency} = {each:.4f} each"

    existing = ctx.supplier_items.get(supplier_sku) if supplier_sku else None
    row.values["existing_pack"] = (
        None if existing is None else f"{existing.order_uom}:{existing.units_per_order_uom.normalize():f}"
    )
    if existing is not None and units is not None and uom:
        if (uom, units) != (existing.order_uom, existing.units_per_order_uom):
            message = (f"Pack changed: we have {existing.order_uom} of {existing.units_per_order_uom.normalize():f}, "
                       f"file says {uom} of {units.normalize():f}")
            if s.update_pack_on_change:
                row.warn(ctx.columns.get("units_per_order_uom"), message + " — will update and require re-confirming the item")
            else:
                row.error(ctx.columns.get("units_per_order_uom"), message + " (turn on 'apply pack changes' to accept)")
    if existing is None and variant_id is None:
        row.warn(None, "Not linked to one of your items yet; it will be created unmapped")

    row.key = supplier_sku
    row.values.update(supplier_sku=supplier_sku, description=_parse(row, ctx, cells, "description", _NAME),
                      unit_price=per_order_unit, currency=currency, units_per_order_uom=units, order_uom=uom,
                      valid_from=valid_from, expires_at=expires_at, min_order_qty=moq, order_multiple=multiple,
                      lead_time_days=lead, variant_id=variant_id)
    return row


def interpret_inventory(ctx: Context, number: int, cells: list[str]) -> RowResult:
    row = RowResult(number)
    s: InventorySettings = ctx.settings
    tz = s.timezone or ctx.timezone
    quantity = _parse(row, ctx, cells, "quantity", v.decimal, required=True)
    if quantity is not None and quantity < 0:
        row.error(ctx.columns["quantity"], "Quantity on hand is negative; recount this item")
    as_of = _parse(row, ctx, cells, "as_of", lambda x: v.past_moment(x, date_format=s.date_format, tz=tz)) or s.as_of
    if as_of is None:
        row.error(ctx.columns.get("as_of"), "Count time is missing (map a column or set 'as of')")
    elif as_of.tzinfo is None:
        row.error(None, "'as of' must include a timezone")
    elif as_of > datetime.now(timezone.utc) + timedelta(seconds=v.FUTURE_TOLERANCE_SECONDS):
        row.error(ctx.columns.get("as_of"), "'as of' is in the future")
    name = _parse(row, ctx, cells, "name", _NAME)
    variant_id = _resolve_variant(row, ctx, cells, required=not s.create_missing_variants)
    sku = row.values.get("_sku_input")
    if variant_id is None and s.create_missing_variants and not row.errors:
        if not sku or not name:
            row.error(None, "To create a new item the row needs both SKU and name")
        else:
            row.warn(None, f"New item {sku!r} will be created")
    row.key = str(variant_id) if variant_id else f"sku:{sku}"
    row.interpretation = f"{sku or ''} {name or ''}: {quantity} on hand".strip()
    row.values.update(variant_id=variant_id, quantity=quantity, as_of=as_of, sku=sku, name=name,
                      barcode=row.values.get("_barcode_input"))
    return row


def interpret_sales(ctx: Context, number: int, cells: list[str]) -> RowResult:
    row = RowResult(number)
    s: SalesSettings = ctx.settings
    tz = s.timezone or ctx.timezone
    order_id = _parse(row, ctx, cells, "order_id", v.bounded_text(255), required=True)
    sold_at = _parse(row, ctx, cells, "sold_at", lambda x: v.past_moment(x, date_format=s.date_format, tz=tz), required=True)
    quantity = _parse(row, ctx, cells, "quantity", v.decimal, required=True)
    currency = _parse(row, ctx, cells, "currency", v.currency_code)
    unit_price = _parse(row, ctx, cells, "unit_price", lambda x: v.decimal(x, currency=currency))
    raw_type = (_parse(row, ctx, cells, "line_type", v.text) or "").lower()
    variant_id = _resolve_variant(row, ctx, cells)
    if raw_type in _REFUND_TYPES:
        line_type = "refund"
    elif raw_type in _SALE_TYPES:
        line_type = "sale"
    else:  # void, cancelled, exchange, … are not demand; never count them as sales
        line_type = "sale"
        row.error(ctx.columns.get("line_type"), f"Unknown type {raw_type!r}; only sales and refunds are imported")
    if quantity is not None:
        if quantity == 0:
            row.error(ctx.columns["quantity"], "Quantity is zero")
        elif quantity < 0:
            line_type = "refund"  # negative quantities are refunds
        elif line_type == "refund":
            quantity = -quantity
    line_id = _parse(row, ctx, cells, "line_id", v.bounded_text(200), required="line_id" in ctx.columns)
    # Keys use the file's own identifiers, never what Tabula resolved them to: if a
    # barcode is later re-linked to another item, a re-import still matches.
    sku_in, barcode_in = row.values.get("_sku_input"), row.values.get("_barcode_input")
    source_item = f"sku:{sku_in}" if sku_in else f"barcode:{barcode_in}"
    row.key = f"{order_id}|{line_id}" if line_id else f"{order_id}|{source_item}|{line_type}"
    row.values["source_item"] = source_item
    row.interpretation = f"{order_id}: {line_type} of {abs(quantity) if quantity is not None else '?'}"
    row.values.update(order_id=order_id, line_id=line_id, sold_at=sold_at, quantity=quantity, line_type=line_type,
                      unit_price=unit_price, currency=currency, variant_id=variant_id)
    return row


def interpret_open_orders(ctx: Context, number: int, cells: list[str]) -> RowResult:
    row = RowResult(number)
    s: OpenOrderSettings = ctx.settings
    tz = s.timezone or ctx.timezone
    supplier = None
    supplier_name = _parse(row, ctx, cells, "supplier", v.bounded_text(200))
    if supplier_name:
        supplier = ctx.suppliers_by_name.get(supplier_name.lower())
        if supplier is None:
            row.error(ctx.columns["supplier"], f"Unknown supplier {supplier_name!r}; add it first")
    elif s.supplier_id is not None:
        supplier = ctx.suppliers_by_name.get(f"id:{s.supplier_id}")
    else:
        row.error(None, "No supplier (map a supplier column or choose one supplier for the whole file)")
    po = _parse(row, ctx, cells, "po_number", v.bounded_text(120), required=True)
    qty = _parse(row, ctx, cells, "outstanding_qty", v.decimal, required=True)
    if qty is not None and qty < 0:
        row.error(ctx.columns["outstanding_qty"], "Outstanding quantity is negative")
    ordered_at = _parse(row, ctx, cells, "ordered_at", lambda x: v.past_moment(x, date_format=s.date_format, tz=tz))
    expected_at = _parse(row, ctx, cells, "expected_at", lambda x: v.moment(x, date_format=s.date_format, tz=tz))
    confirmed = _parse(row, ctx, cells, "confirmed", v.boolean) or False
    variant_id = _resolve_variant(row, ctx, cells, supplier_id=supplier.id if supplier else None)

    base_qty = None
    if qty is not None and variant_id is not None and supplier is not None and s.quantity_unit is not None:
        if s.quantity_unit == "base":
            base_qty = qty
        else:
            items = ctx.supplier_items_by_variant.get((supplier.id, variant_id), [])
            supplier_sku = _parse(row, ctx, cells, "supplier_sku", _SKU)
            if supplier_sku:
                items = [i for i in items if i.supplier_sku == supplier_sku]
            packs = {(i.order_uom, i.units_per_order_uom) for i in items}
            if len(packs) != 1:
                row.error(ctx.columns.get("outstanding_qty"),
                          "Cannot convert order units: this supplier has " +
                          ("no pack for this item" if not packs else "several packs for this item"))
            else:
                uom, per = packs.pop()
                base_qty = qty * per
                row.interpretation = f"{po}: {qty} {uom} × {per.normalize():f} = {base_qty.normalize():f} each outstanding"
    if base_qty is not None and not row.interpretation:
        row.interpretation = f"{po}: {base_qty.normalize():f} each outstanding"
    row.key = f"{supplier.id if supplier else supplier_name}|{po}|{variant_id}"
    row.values.update(supplier_id=supplier.id if supplier else None, po_number=po, outstanding_qty=base_qty,
                      ordered_at=ordered_at, expected_at=expected_at, confirmed=confirmed, variant_id=variant_id)
    return row


INTERPRETERS: dict[str, Callable[[Context, int, list[str]], RowResult]] = {
    "supplier_price_list": interpret_price_list,
    "inventory": interpret_inventory,
    "sales": interpret_sales,
    "open_orders": interpret_open_orders,
}


def blocking_issues(kind: str, columns: dict[str, str], settings: Any) -> list[str]:
    """File-level problems that stop confirmation regardless of row content."""
    spec = SPECS[kind]
    issues = [f"map_required_field:{f.name}" for f in spec.fields if f.required and f.name not in columns]
    for group in spec.one_of:
        if not any(name in columns for name in group):
            issues.append("map_one_of:" + "|".join(group))
    if kind == "supplier_price_list":
        if settings.price_basis is None:
            issues.append("declare_price_basis")  # is "Price" per case or per each? never guessed
        if "units_per_order_uom" not in columns and settings.units_per_order_uom is None:
            issues.append("declare_units_per_order_uom")
        if "order_uom" not in columns and settings.order_uom is None:
            issues.append("declare_order_uom")
    if kind == "inventory" and "as_of" not in columns and settings.as_of is None:
        issues.append("declare_as_of")
    if kind == "open_orders":
        if settings.quantity_unit is None:
            issues.append("declare_quantity_unit")
        if "supplier" not in columns and settings.supplier_id is None:
            issues.append("declare_supplier")
    return issues


# Settings that carry meaning the file cannot (spec 3.4: "Case/Qty/Cost — boxes
# or eaches?"). The person confirming must state them back, so the audit shows a
# person — not an agent that drafted the mapping — declared what they mean.
_COMMON_DECLARED = ("date_format", "timezone")
DECLARED_SETTINGS: dict[str, tuple[str, ...]] = {
    "supplier_price_list": ("price_basis", "units_per_order_uom", "order_uom", "currency", "price_type",
                            "update_pack_on_change", *_COMMON_DECLARED),
    "inventory": ("as_of", "create_missing_variants", *_COMMON_DECLARED),
    "sales": _COMMON_DECLARED,
    "open_orders": ("quantity_unit", "supplier_id", *_COMMON_DECLARED),
}


def declared_view(kind: str, settings: Any) -> dict[str, Any]:
    """The declared settings as JSON values (what preview shows and confirm restates)."""
    dumped = settings.model_dump(mode="json")
    return {name: dumped[name] for name in DECLARED_SETTINGS[kind]}


def declared_matches(kind: str, settings: Any, stated: dict[str, Any]) -> bool:
    """
    Compare by meaning, not by string: "2026-10-20T09:00:00+00:00" and the same
    instant written differently are equal; an omitted key equals its default.
    """
    from pydantic import TypeAdapter

    model = SETTINGS[kind]
    for name in DECLARED_SETTINGS[kind]:
        expected = getattr(settings, name)
        field_info = model.model_fields[name]
        if name not in stated:
            if expected != field_info.default:
                return False
            continue
        try:
            value = TypeAdapter(field_info.annotation).validate_python(stated[name])
        except ValidationError:
            return False
        if value != expected:
            return False
    return True
