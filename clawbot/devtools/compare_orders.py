"""
Compare a store's real past orders with what Tabula would have recommended on those days.

    .venv/bin/python -m clawbot.devtools.compare_orders --tenant <id> --location <id> past_orders.csv \\
        [--out data/pilot/reports]

past_orders.csv (one row per ordered item; extra columns are ignored):
    date, supplier, sku | supplier_sku, qty, unit        unit = the unit qty is in: "case"/"each"/…
    date may include the time it was ordered (2026-10-14T15:30); otherwise 06:00 store time is used.

The store's sales, stock counts and supplier price lists must already be imported (Data imports).
For every order date the plan is recomputed as of that morning (a historical run — the store's
current plan is not touched) and each ordered item is compared:

  - quantity difference in base units (ordered vs recommended), and the recommendation's status
  - unit mapping problems: the order's unit does not match the supplier item's order unit, the
    pack size is unknown, or the SKU / supplier SKU is not mapped to an item
  - missing data that day: no stock reading before the date, sales history too short, no price

Writes <out>/compare-<date>.csv and .md. Real customer files and reports stay under data/pilot/
(git-ignored). Limits: open orders recorded outside Tabula are as known today, not as of each date.
"""

from __future__ import annotations

import argparse
import csv
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from clawbot.domain import tenancy
from clawbot.domain.replenishment import service
from clawbot.persistence.db import transaction
from clawbot.persistence.models import Supplier, SupplierItem, Variant
from clawbot.policies.permissions import system

ROOT = Path(__file__).resolve().parents[2]
EACH = {"each", "ea", "unit", "units", "pc", "pcs", "piece", "pieces", "bottle", "can", "bag"}


@dataclass
class Row:
    line: int
    day: date
    supplier: str
    sku: str
    qty: Decimal
    unit: str
    at: datetime | None = None  # when it was ordered, if the file says; else 06:00 store time that day
    issues: list[str] = field(default_factory=list)


def _read(path: Path) -> tuple[list[Row], list[str]]:
    rows, problems = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        cols = {c.strip().lower(): c for c in reader.fieldnames or []}
        need = {"date", "qty"}
        if not need <= set(cols) or not ({"sku", "supplier_sku"} & set(cols)):
            raise SystemExit("past_orders.csv needs date, qty and sku or supplier_sku columns")
        for n, r in enumerate(reader, start=2):
            get = lambda k: (r.get(cols.get(k, ""), "") or "").strip()  # noqa: E731
            try:
                raw = get("date")
                at = datetime.fromisoformat(raw) if "T" in raw or " " in raw.strip() else None
                day = date.fromisoformat(raw[:10])
                qty = Decimal(get("qty"))
            except (ValueError, InvalidOperation):
                problems.append(f"row {n}: unreadable date or qty ({get('date')!r}, {get('qty')!r})")
                continue
            rows.append(Row(n, day, get("supplier"), get("supplier_sku") or get("sku"), qty, get("unit").lower(), at))
    return rows, problems


def compare(tenant_id: uuid.UUID, location_id: uuid.UUID, rows: list[Row]) -> list[dict]:
    out = []
    with transaction() as s:
        location = tenancy.get_location(s, tenant_id=tenant_id, location_id=location_id)
        tz = ZoneInfo(location.timezone)
        variants = {v.sku.upper(): v for v in s.scalars(select(Variant).where(Variant.tenant_id == tenant_id))}
        suppliers = {sp.name.lower(): sp for sp in s.scalars(select(Supplier).where(Supplier.tenant_id == tenant_id))}
        items = list(s.scalars(select(SupplierItem).where(SupplierItem.tenant_id == tenant_id)))
        by_day: dict[datetime, list[Row]] = defaultdict(list)
        for r in rows:
            at = r.at.replace(tzinfo=r.at.tzinfo or tz) if r.at else datetime.combine(r.day, time(6), tz)
            by_day[min(at.astimezone(timezone.utc), datetime.now(timezone.utc))].append(r)  # never in the future
        for as_of in sorted(by_day):
            day = as_of.astimezone(tz).date()
            run, _ = service.create_run(s, tenant_id=tenant_id, actor=system("pilot-compare"), location_id=location_id,
                                        as_of=as_of)
            lines = {l.variant_id: l for l in service.run_lines(s, run)}
            for r in by_day[as_of]:
                supplier = suppliers.get(r.supplier.lower()) if r.supplier else None
                item = next((i for i in items if i.supplier_sku.upper() == r.sku.upper()
                             and (supplier is None or i.supplier_id == supplier.id)), None)
                variant = (s.get(Variant, item.variant_id) if item and item.variant_id else variants.get(r.sku.upper()))
                if r.supplier and supplier is None:
                    r.issues.append(f"supplier {r.supplier!r} not in Tabula")
                if variant is None:
                    r.issues.append(f"{r.sku!r} is not mapped to an item (add the item or confirm the supplier SKU)")
                if item is None and variant is not None:
                    item = next((i for i in items if i.variant_id == variant.id
                                 and (supplier is None or i.supplier_id == supplier.id)), None)
                base = None
                if r.unit in EACH or (not r.unit and item is None):
                    base = r.qty
                elif item is not None and r.unit in (item.order_uom.lower(), item.order_uom.lower() + "s"):
                    base = r.qty * item.units_per_order_uom
                elif item is not None:
                    r.issues.append(f"ordered in {r.unit!r} but the supplier item is ordered by {item.order_uom!r} "
                                    f"of {item.units_per_order_uom.normalize():f}: unit mapping needs checking")
                else:
                    r.issues.append(f"unit {r.unit!r} cannot be converted: no supplier item / pack size known")
                line = lines.get(variant.id) if variant else None
                rec_base = line.base_qty if line is not None and line.status == "order" else Decimal(0)
                if line is not None:
                    inputs = line.inputs
                    if inputs.get("on_hand") is None:
                        r.issues.append("no stock reading before this date")
                    if (inputs.get("history_days") or 0) < 14:
                        r.issues.append(f"only {inputs.get('history_days') or 0} day(s) of sales history before this date")
                    if line.status == "no_supplier":
                        r.issues.append("no orderable supplier item / price on this date")
                out.append({
                    "date": day.isoformat(), "row": r.line, "supplier": r.supplier, "sku": r.sku,
                    "item": variant.sku if variant else "", "ordered": f"{r.qty.normalize():f} {r.unit}".strip(),
                    "ordered_units": f"{base.normalize():f}" if base is not None else "",
                    "recommended_units": f"{rec_base.normalize():f}",
                    "plan_status": line.status if line is not None else "",
                    "difference_units": f"{(base - rec_base).normalize():f}" if base is not None else "",
                    "issues": "; ".join(r.issues), "run_id": str(run.id),
                })
        s.rollback()  # the historical runs were only needed for this report
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare real past orders with Tabula's recommendations")
    parser.add_argument("orders")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--location", required=True)
    parser.add_argument("--out", default=str(ROOT / "data" / "pilot" / "reports"))
    args = parser.parse_args(argv)
    rows, problems = _read(Path(args.orders))
    result = compare(uuid.UUID(args.tenant), uuid.UUID(args.location), rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    with open(out / f"compare-{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(result[0]) if result else ["date"])
        w.writeheader()
        w.writerows(result)
    md = [f"# Past orders vs Tabula — {stamp}", "", f"{len(result)} ordered item(s) on {len({r['date'] for r in result})} day(s).", ""]
    with_issues = [r for r in result if r["issues"]]
    comparable = [r for r in result if r["ordered_units"] and not r["issues"]]
    md += [f"- Comparable without data problems: {len(comparable)}",
           f"- With unit mapping or missing-data problems: {len(with_issues)}",
           *(f"- Unreadable rows: {p}" for p in problems), "", "| date | item | ordered | ordered units | recommended | difference | issues |",
           "|---|---|---|---|---|---|---|"]
    md += [f"| {r['date']} | {r['item'] or r['sku']} | {r['ordered']} | {r['ordered_units']} | {r['recommended_units']} "
           f"| {r['difference_units']} | {r['issues']} |" for r in result]
    (out / f"compare-{stamp}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:6]))
    print(f"\nreport: {out}/compare-{stamp}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
