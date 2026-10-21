"""PLAN-01: the deterministic engine, without a database (spec 7.2–7.3)."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from clawbot.domain.replenishment import codec
from clawbot.domain.replenishment.calendar import SupplierCalendar, arrival_day_for_eta, arrival_for_order_now
from clawbot.domain.replenishment.engine import (
    InboundLine, ItemInputs, OfferInputs, Policy, SupplierTerms, plan_checks, recommend,
)

TODAY = date(2026, 10, 21)  # a Wednesday
D = Decimal


def offer(**kw) -> OfferInputs:
    base = dict(supplier_item_id="si-1", supplier_id="sup-1", supplier_name="Phillips Pet", order_uom="case",
                units_per_order_uom=D(12), order_multiple=D(1), min_order_qty=D(1), unit_price=D("30.00"),
                currency="USD", price_as_of="2026-10-01T00:00:00+00:00", arrival_day=4)
    return OfferInputs(**{**base, **kw})


def item(**kw) -> ItemInputs:
    """Spec 7.3: 18 on hand, 6/day, lead 4, review 7, safety 12, case of 12, nothing inbound."""
    sales = tuple((TODAY - timedelta(days=n), D(6)) for n in range(28, 0, -1))
    base = dict(variant_id="v-1", sku="LITTER-20", planning_date=TODAY, variant_active=True, on_hand=D(18),
                stock_source="Tabula ledger", stock_as_of="2026-10-21T08:00:00-04:00", stock_age_hours=D(1),
                daily_sales=sales, history_days=28, sales_through="2026-10-20T19:00:00-04:00", sales_age_hours=D(14),
                offers=(offer(),), safety_stock=D(12))
    return ItemInputs(**{**base, **kw})


POLICY = Policy(version=3, review_period_days=7)


def codes(r) -> list[str]:
    return [x["code"] for x in r.reasons]


def step(r, label):
    return next(s for s in r.steps if s["label"] == label)


def test_spec_example_five_cases_one_stockout_day():
    r = recommend(item(), POLICY)
    assert (r.status, r.order_qty, r.order_uom, r.base_qty) == ("order", D(5), "case", D(60))
    assert (r.daily_demand, r.target, r.position, r.need) == (D(6), D(78), D(18), D(60))
    assert r.stockout_days == [4]  # 18 lasts 3 days; the order is usable from day 5
    assert r.stockout_days_without_order == list(range(4, 12))
    assert r.line_cost == D(150) and r.currency == "USD"
    assert codes(r) == ["stockout_before_delivery"]  # flagged for an expedite/transfer decision
    assert step(r, "Target stock")["value"] == "78"
    assert "arrival day 4 + review period 7" in step(r, "Target stock")["formula"]


def test_same_inputs_and_policy_give_identical_results_and_replay():
    a, b = recommend(item(), POLICY), recommend(item(), POLICY)
    assert dataclasses.asdict(a) == dataclasses.asdict(b)
    replayed = recommend(codec.load_item(codec.dumps(item())), codec.load_policy(codec.dumps(POLICY)))
    assert dataclasses.asdict(replayed) == dataclasses.asdict(a)
    assert codec.digest(POLICY, [item()]) == codec.digest(POLICY, [item()])
    assert codec.digest(POLICY, [item()]) != codec.digest(dataclasses.replace(POLICY, version=4), [item()])


def test_confirmed_inbound_reduces_the_order_and_the_risk():
    r = recommend(item(inbound=(InboundLine("PO-77 (Phillips Pet)", D(24), True, 2),)), POLICY)
    assert (r.position, r.need, r.order_qty) == (D(42), D(36), D(3))
    assert r.stockout_days == [] and "stockout_before_delivery" not in codes(r)


def test_unconfirmed_order_prevents_a_duplicate_order_but_not_the_risk():
    r = recommend(item(inbound=(InboundLine("PO-80 (Phillips Pet)", D(60), False, 4),)), POLICY)
    assert (r.position, r.need, r.order_qty, r.status) == (D(78), D(0), D(0), "no_order")
    assert codes(r) == ["unconfirmed_open_order", "stockout_risk_unconfirmed"]
    assert r.stockout_days  # not counted as arriving


@pytest.mark.parametrize("moq, multiple, cases", [(D(6), D(1), D(6)), (D(1), D(2), D(6)), (D(1), D(1), D(5))])
def test_moq_and_order_multiple(moq, multiple, cases):
    r = recommend(item(offers=(offer(min_order_qty=moq, order_multiple=multiple),)), POLICY)
    assert r.order_qty == cases and r.base_qty == cases * 12


def test_missing_or_stale_data_is_flagged_not_hidden():
    assert recommend(item(on_hand=None, stock_source=None, stock_as_of=None, stock_age_hours=None), POLICY).status == "insufficient_data"
    stale = recommend(item(stock_age_hours=D(120)), POLICY)
    assert "stale_stock" in codes(stale) and stale.status == "order"
    assert "stale_sales" in codes(recommend(item(sales_age_hours=D(200)), POLICY))
    assert "stale_sales" in codes(recommend(item(sales_age_hours=None, sales_through=None), POLICY))
    short = recommend(item(daily_sales=item().daily_sales[-10:], history_days=10), POLICY)
    assert "short_history" in codes(short)
    neg = recommend(item(on_hand=D(-3), sales_since_reading=D(21)), POLICY)
    assert "negative_estimated_stock" in codes(neg) and neg.position == D(0)


def test_no_sales_history_needs_min_max():
    r = recommend(item(daily_sales=(), history_days=0), POLICY)
    assert r.status == "insufficient_data" and "no_demand_signal" in codes(r)
    with_max = recommend(item(daily_sales=(), history_days=0, max_qty=D(40)), POLICY)
    assert (with_max.status, with_max.need, with_max.order_qty) == ("order", D(22), D(2))


def test_merchant_min_max():
    r = recommend(item(min_qty=D(20), max_qty=D(50)), POLICY)
    assert (r.target, r.need, r.order_qty) == (D(50), D(32), D(3))
    above = recommend(item(on_hand=D(30), min_qty=D(20), max_qty=D(50)), POLICY)
    assert above.need == 0 and above.status == "no_order"


def test_no_orderable_supplier_still_explains_the_need():
    r = recommend(item(offers=(), offer_blockers=("mapping_suggested",)), POLICY)
    assert r.status == "no_supplier" and r.order_qty == 0
    assert r.reasons[0]["code"] == "no_orderable_supplier" and r.reasons[0]["blockers"] == ["mapping_suggested"]
    assert r.need == D(6 * 7 + 12 - 18)  # review period only, since no lead time is known


def test_discontinued_and_excluded_items_are_never_ordered():
    assert recommend(item(variant_active=False), POLICY).status == "no_order"
    assert recommend(item(excluded=True), POLICY).status == "excluded"


def test_inbound_without_eta_or_overdue():
    no_eta = recommend(item(inbound=(InboundLine("PO-1 (X)", D(24), True, None),)), POLICY)
    assert "confirmed_order_without_eta" in codes(no_eta)
    overdue = recommend(item(inbound=(InboundLine("PO-2 (X)", D(24), True, -2),)), POLICY)
    assert "overdue_delivery" in codes(overdue)
    # Counted so it is not re-ordered, but not assumed to arrive (it may already be on the shelf, or lost).
    assert overdue.position == D(42) and all(p["arriving"] == "0" for p in overdue.projection[:3])


def test_stockout_days_do_not_drag_demand_down():
    sales = list(item().daily_sales)
    stockout_days = tuple(d for d, _ in sales[-5:])
    sales[-5:] = [(d, D(0)) for d, _ in sales[-5:]]
    r = recommend(item(daily_sales=tuple(sales), stockout_dates=stockout_days), POLICY)
    assert r.daily_demand == D(6)


def test_intermittent_demand_uses_the_long_window_and_is_flagged():
    sales = tuple((TODAY - timedelta(days=n), D(6) if n in (5, 40, 75) else D(0)) for n in range(90, 0, -1))
    r = recommend(item(daily_sales=sales, history_days=90), POLICY)
    assert "intermittent_demand" in codes(r)
    assert step(r, "Daily demand")["formula"].startswith("average of 90 days")


def test_weekday_pattern():
    # weekends sell double: Sat/Sun 12, weekdays 6 → base 52*4/28 ≈ 7.7143
    sales = tuple((d, D(12) if d.isoweekday() >= 6 else D(6))
                  for d in (TODAY - timedelta(days=n) for n in range(28, 0, -1)))
    r = recommend(item(daily_sales=sales), POLICY)
    sat = next(p for p in r.projection if date.fromisoformat(p["date"]).isoweekday() == 6)
    wed = next(p for p in r.projection if date.fromisoformat(p["date"]).isoweekday() == 3)
    assert D(sat["demand"]) > D(wed["demand"])


def test_supplier_minimum_and_budget_are_flagged_not_inflated():
    a = recommend(item(), POLICY)  # 150 USD
    b = recommend(item(variant_id="v-2", sku="FOOD-5", on_hand=D(60)), POLICY)  # less urgent
    terms = {"sup-1": SupplierTerms("sup-1", "Phillips Pet", "USD", D(500), D(250))}
    budget = dataclasses.replace(POLICY, weekly_budget=D(200), budget_currency="USD")
    notes = plan_checks([a, b], terms, budget)
    assert a.order_qty == D(5)  # not raised to meet the minimum
    assert "below_supplier_minimum" in codes(a)
    assert notes[0]["below_minimum"] == "500" and notes[0]["short_of_free_shipping"] is not None
    over = [r.sku for r in (a, b) if "over_budget" in codes(r)]
    assert over == ["FOOD-5"]  # the more urgent item keeps the budget


# ---------------------------------------------------------------------------
# Supplier calendar
# ---------------------------------------------------------------------------

NY = "America/New_York"


def at(local: str) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(NY)).astimezone(timezone.utc)


def test_calendar_cutoff_weekdays_and_closures():
    plain = SupplierCalendar(NY, None, (), ())
    assert arrival_for_order_now(now=at("2026-10-21T10:00"), store_timezone=NY, cal=plain, lead_time_days=4).arrival_day == 4
    cutoff = SupplierCalendar(NY, time(14, 0), (), ())
    late = arrival_for_order_now(now=at("2026-10-21T15:00"), store_timezone=NY, cal=cutoff, lead_time_days=4)
    assert late.arrival_day == 5 and "cutoff" in late.notes[0]
    tue_thu = SupplierCalendar(NY, None, (2, 4), ())
    # Wed order, lead 4 → delivery Sat → next delivery day Tue 27 → usable Wed 28 (day 7)
    assert arrival_for_order_now(now=at("2026-10-21T10:00"), store_timezone=NY, cal=tue_thu, lead_time_days=4).arrival_day == 7
    closed = SupplierCalendar(NY, None, (), ((date(2026, 10, 24), date(2026, 10, 27)),))
    # delivery Sat 24 falls in the closure → delivered Wed 28 → usable Thu 29 (day 8)
    assert arrival_for_order_now(now=at("2026-10-21T10:00"), store_timezone=NY, cal=closed, lead_time_days=4).arrival_day == 8


def test_eta_is_usable_the_day_after_delivery():
    assert arrival_day_for_eta(eta=at("2026-10-22T09:00"), now=at("2026-10-21T10:00"), store_timezone=NY) == 2



# ---------------------------------------------------------------------------
# CP5 review regressions
# ---------------------------------------------------------------------------


def test_r_confirmed_inbound_beyond_the_window_does_not_cancel_todays_need():
    r = recommend(item(inbound=(InboundLine("PO-9 (X)", D(60), True, 30),)), POLICY)
    assert (r.position, r.order_qty) == (D(18), D(5))
    assert "confirmed_inbound_after_window" in codes(r)


def test_r_lead_time_zero_is_usable_today():
    r = recommend(item(offers=(offer(arrival_day=0),)), POLICY)
    assert r.order_qty > 0 and r.stockout_days == []
    assert D(r.projection[0]["start"]) == D(18) + r.base_qty


def test_r_same_convention_for_new_orders_and_etas():
    tue_only = SupplierCalendar(NY, None, (2,), ())
    monday = at("2026-10-26T09:00")
    new_order = arrival_for_order_now(now=monday, store_timezone=NY, cal=tue_only, lead_time_days=1)
    eta = arrival_day_for_eta(eta=at("2026-10-27T09:00"), now=monday, store_timezone=NY)  # delivered Tuesday
    assert new_order.arrival_day == eta == 2


def test_r_supplier_with_fewer_stockouts_beats_a_cheaper_slow_one():
    slow_cheap = offer(supplier_item_id="si-slow", supplier_name="Slow & Cheap", unit_price=D("24.00"), arrival_day=14)
    fast = offer(supplier_item_id="si-fast", supplier_name="Fast", unit_price=D("30.00"), arrival_day=2)
    r = recommend(item(offers=(slow_cheap, fast)), POLICY)
    assert r.supplier_item_id == "si-fast" and r.stockout_days == []
    assert "Slow & Cheap" in step(r, "Supplier choice")["formula"]


def test_r_old_unconfirmed_orders_are_flagged():
    r = recommend(item(inbound=(InboundLine("PO-3 (X)", D(60), False, None, 30),)), POLICY)
    assert "stale_unconfirmed_order" in codes(r) and r.order_qty == 0


def test_r_never_counted_and_inferred_coverage_are_flagged():
    r = recommend(item(stock_counted=False, coverage_inferred=True), POLICY)
    assert {"stock_not_counted", "coverage_inferred"} <= set(codes(r))
