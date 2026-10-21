"""Pure calculation tests: order-unit conversion, money, GTIN."""

from __future__ import annotations

from decimal import Decimal

import pytest

from clawbot.domain.errors import ValidationFailed
from clawbot.domain.gtin import normalize_gtin
from clawbot.domain.units import (
    CurrencyMismatch,
    order_quantity_for,
    require_same_currency,
    round_money,
    to_base_qty,
    unit_cost_per_base,
)


@pytest.mark.parametrize(
    "need, per, multiple, moq, cases, extra, applied",
    [
        ("48", "12", "1", "1", "4", "0", ()),  # spec 6.2 example
        ("60", "12", "1", "1", "5", "0", ()),  # spec 7.3 example
        ("49", "12", "1", "1", "5", "11", ("pack_rounding",)),
        ("1", "12", "1", "1", "1", "11", ("pack_rounding",)),
        ("49", "12", "2", "1", "6", "23", ("order_multiple",)),
        ("12", "12", "1", "3", "3", "24", ("min_order_qty",)),
        ("12", "12", "2", "3", "4", "36", ("order_multiple", "min_order_qty")),  # MOQ rounded up to the multiple
        ("0", "12", "1", "1", "0", "0", ()),
        ("-5", "12", "1", "1", "0", "0", ()),
        ("7.5", "2.5", "1", "1", "3", "0", ()),  # fractional base units (e.g. kg)
    ],
)
def test_order_quantity(need, per, multiple, moq, cases, extra, applied):
    q = order_quantity_for(need, units_per_order_uom=per, order_uom="case", order_multiple=multiple, min_order_qty=moq)
    assert q.order_qty == Decimal(cases)
    assert q.extra_base_qty == Decimal(extra)
    assert q.constraints_applied == applied
    if q.order_qty:
        assert q.base_qty == q.order_qty * Decimal(per) >= Decimal(need)


def test_order_quantity_rejects_float_and_nonpositive_pack():
    with pytest.raises(TypeError):
        order_quantity_for(48.0, units_per_order_uom="12", order_uom="case")
    with pytest.raises(ValidationFailed):
        order_quantity_for("48", units_per_order_uom="0", order_uom="case")


def test_base_qty_and_unit_cost():
    assert to_base_qty(Decimal(4), Decimal(12)) == Decimal(48)
    assert unit_cost_per_base(Decimal("30.00"), Decimal(12)) == Decimal("2.500000")
    assert unit_cost_per_base(Decimal("5.00"), Decimal(12)) == Decimal("0.416667")


def test_money_rounding_respects_minor_units():
    assert round_money(Decimal("2.345"), "USD") == Decimal("2.34")  # banker's rounding
    assert round_money(Decimal("1234.6"), "KRW") == Decimal("1235")
    with pytest.raises(ValidationFailed):
        round_money(Decimal(1), "XYZ")


def test_currencies_never_mix():
    assert require_same_currency("USD", "usd") == "USD"
    with pytest.raises(CurrencyMismatch):
        require_same_currency("USD", "KRW")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("036000291452", "00036000291452"),  # UPC-A
        ("0036000291452", "00036000291452"),  # same item as EAN-13
        ("0 36000 29145 2", "00036000291452"),  # spaces from a printed label
        ("4006381333931", "04006381333931"),  # EAN-13
        ("96385074", "00000096385074"),  # EAN-8
        ("036000291453", None),  # wrong check digit
        ("SKU-123", None),  # store-internal code
        ("12345", None),  # wrong length
        (None, None),
    ],
)
def test_gtin_normalisation(raw, expected):
    assert normalize_gtin(raw) == expected
