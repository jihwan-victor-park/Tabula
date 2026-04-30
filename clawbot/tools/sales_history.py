"""
Sales history tool — queries the MongoDB sales collection.

Collection: "sales" in the clawbot database.
Each document: { sku, product_name, category, sale_date (ISO str), quantity_sold, unit_price }

Uses the MongoDB aggregation pipeline for seasonality and top-SKU analysis.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from clawbot.schemas.trend import SalesHistoryResult, SalesRecord, SeasonalityResult
from clawbot.tools.mongodb import get_col


def _peak_trough_months(category: str) -> SeasonalityResult:
    """Aggregate monthly sales across all years using MongoDB aggregation pipeline."""
    pipeline = [
        {"$match": {"category": {"$regex": f"^{category}$", "$options": "i"}}},
        {
            "$group": {
                "_id": {
                    "$month": {"$dateFromString": {"dateString": "$sale_date", "onError": None}}
                },
                "total_qty": {"$sum": "$quantity_sold"},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    rows = list(get_col("sales").aggregate(pipeline))

    if not rows:
        return SeasonalityResult(
            category=category,
            peak_months=[],
            trough_months=[],
            notes="Insufficient data for seasonality analysis",
        )

    monthly = {r["_id"]: r["total_qty"] for r in rows if r["_id"] is not None}
    if not monthly:
        return SeasonalityResult(
            category=category, peak_months=[], trough_months=[],
            notes="Insufficient data for seasonality analysis",
        )

    avg = sum(monthly.values()) / len(monthly)
    peaks = sorted([m for m, qty in monthly.items() if qty >= avg * 1.2])
    troughs = sorted([m for m, qty in monthly.items() if qty <= avg * 0.8])

    return SeasonalityResult(
        category=category,
        peak_months=peaks,
        trough_months=troughs,
        notes=f"Based on {len(rows)} months of data; avg monthly units = {avg:.0f}",
    )


def get_sales_history(
    category: str,
    lookback_days: int = 90,
    top_n: int = 5,
) -> SalesHistoryResult:
    """
    Query the MongoDB sales collection for a given product category.

    Uses the aggregation pipeline to compute totals and top SKUs.
    """
    today = datetime.utcnow()
    start = today - timedelta(days=lookback_days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = today.strftime("%Y-%m-%d")

    col = get_col("sales")

    # Check if collection is empty — return stub so the agent can still run
    if col.count_documents({}) == 0:
        return SalesHistoryResult(
            category=category,
            period_start=start_str,
            period_end=end_str,
            total_units=0,
            total_revenue=0.0,
            top_skus=[],
            seasonality=None,
        )

    date_filter = {
        "category": {"$regex": f"^{category}$", "$options": "i"},
        "sale_date": {"$gte": start_str, "$lte": end_str},
    }

    # Aggregate totals
    totals_pipeline = [
        {"$match": date_filter},
        {
            "$group": {
                "_id": None,
                "total_units": {"$sum": "$quantity_sold"},
                "total_revenue": {"$sum": {"$multiply": ["$quantity_sold", "$unit_price"]}},
            }
        },
    ]
    totals_rows = list(col.aggregate(totals_pipeline))
    total_units = totals_rows[0]["total_units"] if totals_rows else 0
    total_revenue = round(totals_rows[0]["total_revenue"], 2) if totals_rows else 0.0

    # Top SKUs via aggregation
    sku_pipeline = [
        {"$match": date_filter},
        {
            "$group": {
                "_id": {"sku": "$sku", "product_name": "$product_name", "category": "$category"},
                "quantity_sold": {"$sum": "$quantity_sold"},
                "revenue": {"$sum": {"$multiply": ["$quantity_sold", "$unit_price"]}},
            }
        },
        {"$sort": {"quantity_sold": -1}},
        {"$limit": top_n},
    ]
    sku_rows = list(col.aggregate(sku_pipeline))
    top_skus = [
        SalesRecord(
            sku=r["_id"]["sku"],
            product_name=r["_id"]["product_name"],
            category=r["_id"]["category"],
            quantity_sold=r["quantity_sold"],
            revenue=round(r["revenue"], 2),
            period_start=start_str,
            period_end=end_str,
        )
        for r in sku_rows
    ]

    seasonality = _peak_trough_months(category)

    return SalesHistoryResult(
        category=category,
        period_start=start_str,
        period_end=end_str,
        total_units=total_units,
        total_revenue=total_revenue,
        top_skus=top_skus,
        seasonality=seasonality,
    )
