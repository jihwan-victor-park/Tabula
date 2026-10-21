"""
Unit-of-measure and money arithmetic. Decimal only: float inputs are rejected
so binary rounding can never leak into order quantities or totals.

Vocabulary
  base unit   — what the store sells and counts (variant.base_uom, usually "each")
  order unit  — what the supplier sells (case, pack, ...)
  units_per_order_uom — base units in one order unit (case of 12 → 12)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal

from clawbot.domain.errors import ValidationFailed

# ISO 4217 minor units for currencies we accept. Extend deliberately; an unknown
# code is rejected rather than guessed.
CURRENCY_MINOR_UNITS: dict[str, int] = {
    "USD": 2, "CAD": 2, "EUR": 2, "GBP": 2, "AUD": 2, "MXN": 2,
    "CNY": 2, "HKD": 2, "SGD": 2, "TWD": 2, "INR": 2,
    "KRW": 0, "JPY": 0, "VND": 0,
}


# Matches the Numeric(18, 4) quantity columns, so computed and stored values print alike.
QTY_SCALE = Decimal("0.0001")


# Common order-unit spellings on price lists and invoices. Unknown labels are kept
# (lower-cased), never guessed.
_UOM_ALIASES = {
    "case": "case", "cases": "case", "cs": "case", "cse": "case", "ca": "case",
    "each": "each", "ea": "each", "eaches": "each", "unit": "each", "units": "each", "pc": "each", "pcs": "each",
    "pack": "pack", "pk": "pack", "pkg": "pack", "packs": "pack",
    "box": "box", "bx": "box", "boxes": "box",
    "bag": "bag", "bg": "bag", "bags": "bag",
    "carton": "carton", "ctn": "carton", "ct": "carton",
    "pallet": "pallet", "plt": "pallet",
    "dozen": "dozen", "dz": "dozen", "doz": "dozen",
}


def normalize_uom(label: str) -> str:
    key = label.strip().lower().rstrip(".")
    return _UOM_ALIASES.get(key, key)


class CurrencyMismatch(ValidationFailed):
    """Amounts in different currencies were combined or compared."""


def _dec(value: Decimal | int | str, field: str) -> Decimal:
    if isinstance(value, float):
        raise TypeError(f"{field} must be Decimal, int or str, not float")
    try:
        result = Decimal(value)
    except ArithmeticError:
        raise ValidationFailed(f"{field} is not a number: {value!r}")
    if not result.is_finite():
        raise ValidationFailed(f"{field} must be finite")
    return result


def validate_currency(code: str) -> str:
    code = code.upper()
    if code not in CURRENCY_MINOR_UNITS:
        raise ValidationFailed(f"Unsupported currency: {code}")
    return code


def require_same_currency(*codes: str) -> str:
    distinct = {c.upper() for c in codes}
    if len(distinct) != 1:
        raise CurrencyMismatch(f"Cannot combine amounts in different currencies: {sorted(distinct)}")
    return distinct.pop()


def round_money(amount: Decimal, currency: str) -> Decimal:
    """Round to the currency's minor unit (banker's rounding) for display or billing."""
    exponent = Decimal(1).scaleb(-CURRENCY_MINOR_UNITS[validate_currency(currency)])
    return amount.quantize(exponent, rounding=ROUND_HALF_EVEN)


def unit_cost_per_base(unit_price: Decimal, units_per_order_uom: Decimal) -> Decimal:
    """Price of one base unit, unrounded beyond 6 places (e.g. $30.00/case of 12 → 2.500000)."""
    per = _dec(units_per_order_uom, "units_per_order_uom")
    if per <= 0:
        raise ValidationFailed("units_per_order_uom must be positive")
    return (_dec(unit_price, "unit_price") / per).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class OrderQuantity:
    requested_base_qty: Decimal
    order_qty: Decimal  # in order units
    order_uom: str
    base_qty: Decimal  # what actually arrives, in base units
    extra_base_qty: Decimal  # arrives beyond the request because of pack/multiple/MOQ rounding
    constraints_applied: tuple[str, ...]


def to_base_qty(order_qty: Decimal, units_per_order_uom: Decimal) -> Decimal:
    return _dec(order_qty, "order_qty") * _dec(units_per_order_uom, "units_per_order_uom")


def order_quantity_for(
    base_qty: Decimal | int | str,
    *,
    units_per_order_uom: Decimal | int | str,
    order_uom: str,
    order_multiple: Decimal | int | str = 1,
    min_order_qty: Decimal | int | str = 1,
) -> OrderQuantity:
    """
    Smallest orderable quantity covering `base_qty`.

    48 each, case of 12            → 4 cases
    49 each, case of 12            → 5 cases (11 extra)
    49 each, case of 12, multiple 2 → 6 cases
    12 each, case of 12, MOQ 3      → 3 cases
    Order quantities are whole multiples of `order_multiple`; the MOQ is rounded
    up to that multiple too.
    """
    requested = _dec(base_qty, "base_qty")
    per = _dec(units_per_order_uom, "units_per_order_uom")
    multiple = _dec(order_multiple, "order_multiple")
    moq = _dec(min_order_qty, "min_order_qty")
    if per <= 0 or multiple <= 0 or moq <= 0:
        raise ValidationFailed("units_per_order_uom, order_multiple and min_order_qty must be positive")

    zero = Decimal(0).quantize(QTY_SCALE)
    if requested <= 0:
        return OrderQuantity(requested.quantize(QTY_SCALE), zero, order_uom, zero, zero, ())

    applied: list[str] = []
    exact = requested / per
    steps = (exact / multiple).to_integral_value(rounding=ROUND_CEILING)
    qty = steps * multiple
    if qty != exact:
        applied.append("order_multiple" if multiple != 1 else "pack_rounding")
    if qty < moq:
        qty = (moq / multiple).to_integral_value(rounding=ROUND_CEILING) * multiple
        applied.append("min_order_qty")

    arrives = qty * per
    return OrderQuantity(
        requested_base_qty=requested.quantize(QTY_SCALE),
        order_qty=qty.quantize(QTY_SCALE),
        order_uom=order_uom,
        base_qty=arrives.quantize(QTY_SCALE),
        extra_base_qty=(arrives - requested).quantize(QTY_SCALE),
        constraints_applied=tuple(applied),
    )
