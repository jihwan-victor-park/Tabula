"""
Deterministic replenishment math (spec 7.2–7.3). Pure: no database, no clock,
no LLM. Everything the calculation depends on is in `ItemInputs` + `Policy`, so
the same inputs and policy version always produce the same `ItemResult`.

Days are local calendar days at the store. Day 1 is the planning day (the
cutoff's local date). Stock is projected at the start of each day; a day is a
stockout day when demand that day exceeds the stock available. Deliveries are
usable from the start of the day after they arrive.

  target       = forecast(days 1..arrival_day + review_period) + safety_stock
  position     = on_hand + confirmed inbound arriving within that window
                 + inbound that is ordered but not reliably arriving (unconfirmed, overdue,
                   no ETA) — counted so nothing is ordered twice
  need         = max(0, target − position)
  order        = need rounded up to case pack, order multiple and MOQ
  projection   uses only confirmed inbound with a future ETA (spec 6.4)

When several suppliers can deliver, the one with the fewest projected stockout
days wins, then the lowest cost per unit (spec 7.4: cost alone is not enough).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from clawbot.domain.units import QTY_SCALE, order_quantity_for

ENGINE_VERSION = "repl-2"
ZERO = Decimal(0)


def _q(value: Decimal) -> Decimal:
    return value.quantize(QTY_SCALE, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class Policy:
    """Merchant-level settings (versioned in replenishment_policies)."""

    version: int = 1
    review_period_days: int = 7
    demand_window_days: int = 28
    long_window_days: int = 90
    min_history_days: int = 14
    min_sale_days: int = 4  # fewer selling days in the window → intermittent demand
    safety_days: Decimal = Decimal(2)  # default safety stock = safety_days × daily demand
    weekday_pattern: bool = True
    weekday_min_weeks: int = 4
    max_stock_age_hours: int = 48
    max_sales_age_hours: int = 72
    max_unconfirmed_age_days: int = 14
    weekly_budget: Decimal | None = None
    budget_currency: str | None = None


@dataclass(frozen=True)
class InboundLine:
    reference: str  # e.g. "PO-77 (Phillips Pet)"
    quantity: Decimal  # base units still to arrive
    confirmed: bool
    arrival_day: int | None  # end-of-day index it becomes usable after; None = no ETA; ≤ 0 = overdue
    age_days: int | None = None  # days since it was ordered / last reported


@dataclass(frozen=True)
class OfferInputs:
    supplier_item_id: str
    supplier_id: str
    supplier_name: str
    order_uom: str
    units_per_order_uom: Decimal
    order_multiple: Decimal
    min_order_qty: Decimal
    unit_price: Decimal  # per order unit
    currency: str
    price_as_of: str
    arrival_day: int  # end-of-day index after which an order placed now is usable
    calendar_notes: tuple[str, ...] = ()
    price_id: str | None = None
    price_type: str | None = None
    price_source: str | None = None
    order_date: str | None = None  # supplier-local date the order counts as placed
    delivery_date: str | None = None
    usable_date: str | None = None


@dataclass(frozen=True)
class ItemInputs:
    variant_id: str
    sku: str
    planning_date: date
    variant_active: bool
    # stock
    on_hand: Decimal | None  # estimated at the planning moment; None = no reading at all
    stock_source: str | None
    stock_as_of: str | None
    stock_age_hours: Decimal | None
    stock_counted: bool = True  # False: the ledger has adjustments but no physical count yet
    sales_since_reading: Decimal = ZERO
    moves_since_reading: Decimal = ZERO  # non-count ledger movements after the last count
    # demand: net quantity per local day, oldest first, ending the day before planning
    daily_sales: tuple[tuple[date, Decimal], ...] = ()
    stockout_dates: tuple[date, ...] = ()  # excluded from the demand average
    history_days: int = 0  # days of sales data available for this location
    coverage_inferred: bool = False  # no declared coverage; first..last sale assumed complete
    sales_through: str | None = None
    sales_age_hours: Decimal | None = None
    # supply
    inbound: tuple[InboundLine, ...] = ()
    offers: tuple[OfferInputs, ...] = ()  # eligible offers, one currency
    offer_blockers: tuple[str, ...] = ()
    # merchant overrides
    safety_stock: Decimal | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    excluded: bool = False


@dataclass
class ItemResult:
    variant_id: str
    sku: str
    status: str  # order | on_hold | no_order | no_supplier | insufficient_data | excluded
    order_qty: Decimal = ZERO  # order units
    order_uom: str | None = None
    base_qty: Decimal = ZERO
    line_cost: Decimal | None = None
    currency: str | None = None
    supplier_item_id: str | None = None
    supplier_id: str | None = None
    daily_demand: Decimal | None = None
    target: Decimal | None = None
    position: Decimal | None = None
    need: Decimal | None = None
    need_before_held: Decimal | None = None  # what would be ordered if held (unconfirmed/overdue) orders did not exist
    held_qty: Decimal = ZERO  # ordered but not counted as arriving
    stockout_days: list[int] = field(default_factory=list)  # with the recommended order
    stockout_days_without_order: list[int] = field(default_factory=list)
    days_of_cover: Decimal | None = None
    priority: Decimal = ZERO  # higher = more urgent (budget ordering)
    reasons: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    projection: list[dict[str, Any]] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.reasons)

    def reason(self, code: str, message: str, **data: Any) -> None:
        self.reasons.append({"code": code, "message": message, **{k: _json(v) for k, v in data.items()}})

    def step(self, label: str, value: Any, formula: str | None = None) -> None:
        entry: dict[str, Any] = {"label": label, "value": _json(value)}
        if formula:
            entry["formula"] = formula
        self.steps.append(entry)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        # Fixed-point, trailing zeros trimmed: 500 → "500", 2.5000 → "2.5" (never "5E+2").
        return f"{(value if value == value.to_integral_value() else _q(value)).normalize():f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Demand:
    base: Decimal
    weekday_factors: dict[int, Decimal]  # ISO weekday → factor
    window_days: int
    sale_days: int
    intermittent: bool

    def on(self, day: date) -> Decimal:
        return _q(self.base * self.weekday_factors.get(day.isoweekday(), Decimal(1)))


def estimate_demand(item: ItemInputs, policy: Policy) -> Demand | None:
    """Moving average over the last N days with sales data, excluding stockout days; weekday factors when there is enough history."""
    stockouts = set(item.stockout_dates)
    series = [(d, max(q, ZERO)) for d, q in item.daily_sales if d not in stockouts]
    if not series:
        return None

    def window(n: int) -> list[tuple[date, Decimal]]:
        return series[-n:]

    days = window(policy.demand_window_days)
    sale_days = sum(1 for _, q in days if q > 0)
    intermittent = sale_days < policy.min_sale_days
    if intermittent and len(series) > len(days):
        days = window(policy.long_window_days)  # sparse sellers: a longer window
        sale_days = sum(1 for _, q in days if q > 0)
    base = _q(sum((q for _, q in days), ZERO) / Decimal(len(days)))

    factors: dict[int, Decimal] = {}
    if policy.weekday_pattern and base > 0 and len(days) >= 7 * policy.weekday_min_weeks:
        by_weekday: dict[int, list[Decimal]] = {}
        for d, q in days:
            by_weekday.setdefault(d.isoweekday(), []).append(q)
        if all(len(v) >= policy.weekday_min_weeks for v in by_weekday.values()) and len(by_weekday) == 7:
            for wd, qs in by_weekday.items():
                factors[wd] = _q((sum(qs, ZERO) / Decimal(len(qs))) / base)
    return Demand(base, factors, len(days), sale_days, intermittent)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def project(
    start: Decimal, demand: Demand, planning_date: date, horizon: int, arrivals: dict[int, Decimal]
) -> tuple[list[dict[str, Any]], list[int]]:
    """Day-by-day stock. Returns (rows, stockout day indexes)."""
    from datetime import timedelta

    # Anything usable at or before the start of day 1 is part of the opening stock.
    stock = start + sum((q for d, q in arrivals.items() if d <= 0), ZERO)
    rows, stockouts = [], []
    for t in range(1, horizon + 1):
        day = planning_date + timedelta(days=t - 1)
        need = demand.on(day)
        short = need - stock if need > stock else ZERO
        if short > 0:
            stockouts.append(t)
        end = max(stock - need, ZERO)
        arriving = arrivals.get(t, ZERO)
        rows.append({"day": t, "date": day.isoformat(), "start": _json(stock), "demand": _json(need),
                     "short": _json(short), "arriving": _json(arriving)})
        stock = end + arriving
    return rows, stockouts


# ---------------------------------------------------------------------------
# Item recommendation
# ---------------------------------------------------------------------------


def recommend(item: ItemInputs, policy: Policy) -> ItemResult:
    r = ItemResult(item.variant_id, item.sku, status="no_order")
    if item.excluded:
        r.status = "excluded"
        r.reason("excluded", "Excluded from automatic replenishment by the merchant")
        return r
    if not item.variant_active:
        r.status = "no_order"
        r.reason("discontinued", "Item is discontinued; nothing is ordered")
        return r

    # --- data freshness and coverage
    if item.on_hand is None:
        r.status = "insufficient_data"
        r.reason("no_stock_reading", "No stock count or POS reading for this item at this location")
        return r
    r.step("Stock on hand (estimated now)", item.on_hand,
           f"{item.stock_source} at {item.stock_as_of}"
           + (f" {'+' if item.moves_since_reading > 0 else '−'} {_json(abs(item.moves_since_reading))} other stock changes since"
              if item.moves_since_reading else "")
           + (f" − {_json(item.sales_since_reading)} sold since" if item.sales_since_reading else ""))
    if not item.stock_counted:
        r.reason("stock_not_counted", "This item has never been counted here; the level comes from adjustments only")
    if item.stock_age_hours is not None and item.stock_age_hours > policy.max_stock_age_hours:
        r.reason("stale_stock", f"Stock reading is {_json(_q(item.stock_age_hours / 24))} days old",
                 as_of=item.stock_as_of)
    if item.on_hand < 0:
        r.reason("negative_estimated_stock",
                 "More was sold since the last count than the count showed; recount this item")
    on_hand = max(item.on_hand, ZERO)

    if item.sales_age_hours is None or item.sales_age_hours > policy.max_sales_age_hours:
        r.reason("stale_sales", "Sales data is missing or out of date, so low sales may only mean missing data",
                 sales_through=item.sales_through)
    if item.coverage_inferred:
        r.reason("coverage_inferred", "Which days the sales data covers is unknown; gaps may look like zero sales")
    if item.history_days < policy.min_history_days:
        r.reason("short_history", f"Only {item.history_days} days of sales history", days=item.history_days)

    demand = estimate_demand(item, policy)
    if demand is None and item.max_qty is None:
        r.status = "insufficient_data"
        r.reason("no_demand_signal", "No sales history; set a min/max for this item to replenish it")
        return r
    if demand is not None:
        r.daily_demand = demand.base
        r.step("Daily demand", demand.base,
               f"average of {demand.window_days} days ({demand.sale_days} with sales)"
               + (", weekday pattern applied" if demand.weekday_factors else ""))
        if demand.intermittent:
            r.reason("intermittent_demand", f"Sold on only {demand.sale_days} of the last {demand.window_days} days")
        if item.stockout_dates:
            r.step("Stockout days excluded from demand", len(item.stockout_dates))

    # --- inbound: what will arrive vs what only prevents a duplicate order
    arriving: list[InboundLine] = []  # confirmed, future ETA
    held: list[InboundLine] = []  # counted against need, not projected as arriving
    for line in item.inbound:
        if not line.confirmed:
            r.reason("unconfirmed_open_order",
                     f"{line.reference}: {_json(line.quantity)} ordered but not confirmed by the supplier — "
                     "counted to avoid ordering twice, not counted as arriving",
                     reference=line.reference, quantity=line.quantity)
            if line.age_days is not None and line.age_days > policy.max_unconfirmed_age_days:
                r.reason("stale_unconfirmed_order",
                         f"{line.reference} has been unconfirmed for {line.age_days} days; check it is still on order",
                         reference=line.reference)
            held.append(line)
        elif line.arrival_day is None:
            r.reason("confirmed_order_without_eta", f"{line.reference}: confirmed but no delivery date",
                     reference=line.reference)
            held.append(line)
        elif line.arrival_day <= 0:
            r.reason("overdue_delivery",
                     f"{line.reference} is past its delivery date — if it arrived, count it in; "
                     "it is not assumed to arrive", reference=line.reference)
            held.append(line)
        else:
            arriving.append(line)
    held_qty = sum((i.quantity for i in held), ZERO)

    # --- supply: evaluate each eligible offer, keep the best
    if not item.offers:
        r.status = "no_supplier"
        r.reason("no_orderable_supplier", "No supplier item can be ordered for this item",
                 blockers=list(item.offer_blockers))
    if not item.offers and item.max_qty is None and demand is None:
        return r
    options = [_evaluate(item, policy, demand, on_hand, arriving, held_qty, o) for o in item.offers] or [
        _evaluate(item, policy, demand, on_hand, arriving, held_qty, None)]
    best = min(options, key=lambda o: (len(o["stockouts"]), o["unit_cost"], o["supplier"]))
    offer = best["offer"]
    if offer is not None:
        usable_day = max(offer.arrival_day, 0) + 1
        r.step("Order arrives (usable from)", f"day {usable_day}" + (f" ({offer.usable_date})" if offer.usable_date else ""),
               (f"ordered {offer.order_date}, delivered {offer.delivery_date}, on the shelf from the start of "
                f"{offer.usable_date}; " if offer.order_date else "")
               + "; ".join(offer.calendar_notes)
               + f". Day 1 = {item.planning_date.isoformat()}; stock is projected at the start of each day")
        if len(options) > 1:
            r.step("Supplier choice", offer.supplier_name,
                   "fewest projected stockout days, then lowest cost per unit, among "
                   + ", ".join(f"{o['supplier']} ({len(o['stockouts'])} stockout days, "
                               f"{_json(o['unit_cost'])} {o['offer'].currency}/unit)" for o in options))
    if item.inbound:
        r.step("Confirmed inbound arriving in the plan window", best["relevant_qty"])
        r.step("Ordered, not counted as arriving", held_qty)
    for line in best["beyond"]:
        r.reason("confirmed_inbound_after_window",
                 f"{line.reference} arrives after this plan's window (day {line.arrival_day}); "
                 "not counted against today's need", reference=line.reference)

    for label, value, formula in best["steps"]:
        r.step(label, value, formula)
    r.target, r.position, r.need = best["target"], best["position"], best["need"]
    r.need_before_held, r.held_qty = best["need_before_held"], held_qty
    q = best["quantity"]
    if offer is not None:
        r.supplier_item_id, r.supplier_id = offer.supplier_item_id, offer.supplier_id
    if q is not None and q.order_qty > 0:
        r.order_qty, r.order_uom, r.base_qty = q.order_qty, q.order_uom, q.base_qty
        r.line_cost = _q(q.order_qty * offer.unit_price)
        r.currency = offer.currency
        r.status = "order"
        r.step("Order", f"{_json(q.order_qty)} {q.order_uom} = {_json(q.base_qty)} units",
               f"{_json(best['need'])} rounded up to {offer.order_uom} of {_json(offer.units_per_order_uom)}"
               + (f", applied {', '.join(q.constraints_applied)}" if q.constraints_applied else ""))
        r.step("Line cost", f"{_json(r.line_cost)} {offer.currency}",
               f"{_json(q.order_qty)} {offer.order_uom} × {_json(offer.unit_price)} {offer.currency} per "
               f"{offer.order_uom} of {_json(offer.units_per_order_uom)} "
               f"({offer.price_type or 'price'}{', ' + offer.price_source if offer.price_source else ''}, "
               f"valid from {offer.price_as_of})")
    elif held_qty > 0 and best["need_before_held"] > 0 and best["need"] == 0:
        r.status = "on_hold"
        r.reason("reorder_on_hold",
                 f"Needs {_json(best['need_before_held'])} more, but {_json(held_qty)} already ordered is not confirmed "
                 "or not arriving on schedule — confirm those orders with the supplier before reordering",
                 need_before_held=best["need_before_held"], held=held_qty)

    # --- projection and stockout reasons
    if demand is not None:
        r.projection, r.stockout_days, r.stockout_days_without_order = best["rows"], best["stockouts"], best["without"]
        stockouts = best["stockouts"]
        r.days_of_cover = _q(on_hand / demand.base) if demand.base > 0 else None
        days_text = ", ".join(map(str, stockouts))
        if stockouts and r.base_qty > 0:
            r.reason("stockout_before_delivery",
                     f"Expected out of stock on {len(stockouts)} day(s) even with this order (days {days_text}); "
                     "consider an expedited delivery or a transfer", days=stockouts)
        elif stockouts and held:
            r.reason("stockout_risk_unconfirmed",
                     f"Expected out of stock on {len(stockouts)} day(s) (days {days_text}) unless orders not yet "
                     "confirmed or overdue arrive; check them with the supplier before ordering more", days=stockouts)
        elif stockouts:
            r.reason("stockout_risk", f"Expected out of stock on {len(stockouts)} day(s) (days {days_text})",
                     days=stockouts)
        first_out = best["without"][0] if best["without"] else best["horizon"] + 1
        r.priority = _q(Decimal(1000) / Decimal(first_out) + demand.base)
    return r


def _evaluate(item: ItemInputs, policy: Policy, demand: Demand | None, on_hand: Decimal,
              arriving: list[InboundLine], held_qty: Decimal, offer: OfferInputs | None) -> dict[str, Any]:
    """Target, position, need, order and projection if `offer` (or no supplier) is used."""
    arrival_day = max(offer.arrival_day, 0) if offer else 0
    cover_days = arrival_day + policy.review_period_days
    steps: list[tuple[str, Any, str | None]] = []
    if item.max_qty is not None:
        target = item.max_qty
        steps.append(("Target stock", target, "merchant maximum"))
    else:
        assert demand is not None
        safety = item.safety_stock if item.safety_stock is not None else _q(policy.safety_days * demand.base)
        forecast = sum((demand.on(item.planning_date + _days(t)) for t in range(cover_days)), ZERO)
        target = _q(forecast + safety)
        steps.append(("Safety stock", safety, "merchant setting" if item.safety_stock is not None
                      else f"{_json(policy.safety_days)} days × daily demand"))
        steps.append(("Target stock", target, f"demand over {cover_days} days (arrival day {arrival_day} + "
                      f"review period {policy.review_period_days}) + safety stock"))
    # spec 7.2 "relevant confirmed inbound": only what arrives inside the window this order covers
    relevant = [i for i in arriving if i.arrival_day <= cover_days]
    beyond = [i for i in arriving if i.arrival_day > cover_days]
    relevant_qty = sum((i.quantity for i in relevant), ZERO)
    position = _q(on_hand + relevant_qty + held_qty)
    steps.append(("Inventory position", position,
                  "on hand + confirmed inbound in the window + ordered but not counted as arriving"))
    need_before_held = max(target - _q(on_hand + relevant_qty), ZERO)
    if item.min_qty is not None and position > item.min_qty:
        need = ZERO
        steps.append(("Need", need, f"position above merchant minimum {_json(item.min_qty)}"))
    else:
        need = max(target - position, ZERO)
        steps.append(("Need", need, "max(0, target − position)"))

    quantity = None
    if offer is not None and need > 0:
        quantity = order_quantity_for(need, units_per_order_uom=offer.units_per_order_uom, order_uom=offer.order_uom,
                                      order_multiple=offer.order_multiple, min_order_qty=offer.min_order_qty)
    arrivals: dict[int, Decimal] = {}
    for line in arriving:
        arrivals[line.arrival_day] = arrivals.get(line.arrival_day, ZERO) + line.quantity
    horizon = max(cover_days, arrival_day + 1, policy.review_period_days)
    rows, stockouts, without = [], [], []
    if demand is not None:
        _, without = project(on_hand, demand, item.planning_date, horizon, arrivals)
        with_order = dict(arrivals)
        if quantity is not None and quantity.base_qty > 0:
            with_order[arrival_day] = with_order.get(arrival_day, ZERO) + quantity.base_qty
        rows, stockouts = project(on_hand, demand, item.planning_date, horizon, with_order)
    unit_cost = (offer.unit_price / offer.units_per_order_uom) if offer else ZERO
    return {"offer": offer, "supplier": offer.supplier_name if offer else "", "unit_cost": _q(unit_cost),
            "target": target, "position": position, "need": need, "need_before_held": need_before_held,
            "quantity": quantity, "steps": steps,
            "relevant_qty": relevant_qty, "beyond": beyond, "rows": rows, "stockouts": stockouts,
            "without": without, "horizon": horizon}


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)


# ---------------------------------------------------------------------------
# Plan-level checks (across items)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierTerms:
    supplier_id: str
    name: str
    currency: str
    min_order_amount: Decimal | None
    free_shipping_threshold: Decimal | None


def plan_checks(results: list[ItemResult], suppliers: dict[str, SupplierTerms], policy: Policy) -> list[dict[str, Any]]:
    """Supplier minimums, free shipping and budget. Flags only — never inflates orders (spec 7.4)."""
    notes: list[dict[str, Any]] = []
    by_supplier: dict[str, list[ItemResult]] = {}
    for r in results:
        if r.status == "order":
            by_supplier.setdefault(r.supplier_id, []).append(r)
    for supplier_id, lines in sorted(by_supplier.items()):
        terms = suppliers[supplier_id]
        subtotal = _q(sum((l.line_cost for l in lines), ZERO))
        note = {"supplier_id": supplier_id, "supplier": terms.name, "subtotal": _json(subtotal),
                "currency": terms.currency, "lines": len(lines)}
        if terms.min_order_amount is not None and subtotal < terms.min_order_amount:
            note["below_minimum"] = _json(terms.min_order_amount)
            for l in lines:
                l.reason("below_supplier_minimum",
                         f"{terms.name} order total {_json(subtotal)} {terms.currency} is below its minimum "
                         f"{_json(terms.min_order_amount)}; not increased automatically")
        if terms.free_shipping_threshold is not None and subtotal < terms.free_shipping_threshold:
            note["short_of_free_shipping"] = _json(terms.free_shipping_threshold - subtotal)
        notes.append(note)

    if policy.weekly_budget is not None:
        spent = ZERO
        for r in sorted((r for r in results if r.status == "order"), key=lambda r: (-r.priority, r.sku)):
            if r.currency != policy.budget_currency:
                r.reason("budget_currency_mismatch", f"Budget is in {policy.budget_currency}; this order is in {r.currency}")
                continue
            spent += r.line_cost
            if spent > policy.weekly_budget:
                r.reason("over_budget", f"Exceeds the weekly budget of {_json(policy.weekly_budget)} {policy.budget_currency} "
                         "after more urgent items", budget=policy.weekly_budget)
        notes.append({"budget": _json(policy.weekly_budget), "planned": _json(_q(spent)), "currency": policy.budget_currency})
    return notes
