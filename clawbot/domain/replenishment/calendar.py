"""
When an order placed now becomes usable, from the supplier's calendar (spec 7.2).

One convention for new orders and for open orders with an ETA: goods are
*delivered* on a date and *usable* from the next day. Lead time is order →
usable (spec 7.2), so delivery = order day + lead − 1. Delivery weekdays and
closures apply to the delivery date. A lead time of 0 means usable the same day.

The result is the store-local day index at whose end the goods arrive (usable
from the next day); 0 = usable at the start of today.

  order day      = today in the supplier's timezone, or tomorrow if past today's cutoff,
                   moved past supplier closures
  delivery date  = order day + lead − 1, moved to an allowed delivery weekday, past closures
  usable date    = delivery date + 1 (lead 0: the order day itself)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MAX_ROLL_DAYS = 60


@dataclass(frozen=True)
class SupplierCalendar:
    timezone: str
    order_cutoff_local: time | None
    delivery_weekdays: tuple[int, ...]  # ISO weekdays; empty = any day
    closures: tuple[tuple[date, date], ...]  # inclusive ranges


@dataclass(frozen=True)
class Arrival:
    order_date: date
    delivery_date: date
    usable_date: date
    arrival_day: int  # end-of-day index relative to the store planning date
    notes: tuple[str, ...]


def _closed(day: date, closures: tuple[tuple[date, date], ...]) -> tuple[date, date] | None:
    return next(((a, b) for a, b in closures if a <= day <= b), None)


def arrival_for_order_now(
    *, now: datetime, store_timezone: str, cal: SupplierCalendar, lead_time_days: int
) -> Arrival:
    notes: list[str] = []
    supplier_now = now.astimezone(ZoneInfo(cal.timezone))
    order_date = supplier_now.date()
    if cal.order_cutoff_local is not None and supplier_now.time() > cal.order_cutoff_local:
        order_date += timedelta(days=1)
        notes.append(f"after today's {cal.order_cutoff_local.strftime('%H:%M')} order cutoff, so ordered tomorrow")
    for _ in range(MAX_ROLL_DAYS):
        closed = _closed(order_date, cal.closures)
        if not closed:
            break
        order_date = closed[1] + timedelta(days=1)
        notes.append(f"supplier closed {closed[0]}–{closed[1]}")

    notes.append(f"{lead_time_days}-day lead time")
    if lead_time_days <= 0:
        usable = delivery = order_date  # same-day (e.g. cash-and-carry pickup)
    else:
        delivery = order_date + timedelta(days=lead_time_days - 1)
        for _ in range(MAX_ROLL_DAYS):
            closed = _closed(delivery, cal.closures)
            if closed:
                delivery = closed[1] + timedelta(days=1)
                notes.append(f"no delivery during closure {closed[0]}–{closed[1]}")
                continue
            if cal.delivery_weekdays and delivery.isoweekday() not in cal.delivery_weekdays:
                delivery += timedelta(days=1)
                continue
            break
        usable = delivery + timedelta(days=1)
    if cal.delivery_weekdays:
        notes.append("delivers " + ", ".join(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[d - 1]
                                              for d in sorted(cal.delivery_weekdays)))

    planning_date = now.astimezone(ZoneInfo(store_timezone)).date()
    return Arrival(order_date, delivery, usable, (usable - planning_date).days, tuple(notes))


def arrival_day_for_eta(*, eta: datetime, now: datetime, store_timezone: str) -> int:
    """A confirmed delivery expected during the ETA's local date is usable the day after (conservative)."""
    tz = ZoneInfo(store_timezone)
    return (eta.astimezone(tz).date() - now.astimezone(tz).date()).days + 1
