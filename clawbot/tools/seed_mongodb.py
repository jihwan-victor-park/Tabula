"""
Seed MongoDB with demo data for the YHack presentation.

Run:
    python -m clawbot.tools.seed_mongodb

Pass --clear to wipe existing data before seeding:
    python -m clawbot.tools.seed_mongodb --clear

Barcodes used:
    673419302616  LEGO Classic Creative Bricks
    630509575008  Monopoly Classic
    076930077054  UNO Card Game
    021853006166  Jenga Classic
    653569819431  Play-Doh 4-Pack
    027084002256  Hot Wheels 5-Car Set
    076670207388  Rubik's Cube 3x3
    071662080716  Crayola 64 Crayons
    887961831641  Barbie Fashion Doll
    653569566328  Nerf N-Strike Elite Disruptor
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from clawbot.tools.mongodb import get_col, get_db


def _utc(days_ago: int = 0, hours_ago: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _date(days_ago: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

INVENTORY_ITEMS = [
    {
        "_id": "673419302616",
        "name": "LEGO Classic Creative Bricks Box",
        "brand": "LEGO",
        "category": "Building Toys",
        "description": "900-piece classic creative building set for ages 4+",
        "image_url": "https://images.unsplash.com/photo-1587654780291-39c9404d746b?w=400",
        "quantity": 15,
        "reorder_point": 5,
        "cost_price": 29.99,
        "sell_price": 44.99,
        "currency": "USD",
        "last_updated": _utc(1),
    },
    {
        "_id": "630509575008",
        "name": "Monopoly Classic Board Game",
        "brand": "Hasbro",
        "category": "Board Games",
        "description": "The classic real-estate trading board game",
        "image_url": "https://images.unsplash.com/photo-1611532736597-de2d4265fba3?w=400",
        "quantity": 8,
        "reorder_point": 3,
        "cost_price": 14.99,
        "sell_price": 24.99,
        "currency": "USD",
        "last_updated": _utc(2),
    },
    {
        "_id": "076930077054",
        "name": "UNO Card Game",
        "brand": "Mattel",
        "category": "Card Games",
        "description": "Classic UNO card game for 2-10 players, ages 7+",
        "image_url": "https://images.unsplash.com/photo-1606503153255-59d8b8b82176?w=400",
        "quantity": 20,
        "reorder_point": 8,
        "cost_price": 4.99,
        "sell_price": 9.99,
        "currency": "USD",
        "last_updated": _utc(0),
    },
    {
        "_id": "021853006166",
        "name": "Jenga Classic Game",
        "brand": "Hasbro",
        "category": "Board Games",
        "description": "Classic wood block stacking and tumbling tower game",
        "image_url": "https://images.unsplash.com/photo-1606503153255-59d8b8b82176?w=400",
        "quantity": 4,          # LOW STOCK — below reorder_point of 6
        "reorder_point": 6,
        "cost_price": 8.99,
        "sell_price": 16.99,
        "currency": "USD",
        "last_updated": _utc(0),
    },
    {
        "_id": "653569819431",
        "name": "Play-Doh 4-Pack",
        "brand": "Hasbro",
        "category": "Arts & Crafts",
        "description": "4-pack of classic Play-Doh colors, non-toxic",
        "image_url": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
        "quantity": 12,
        "reorder_point": 5,
        "cost_price": 7.99,
        "sell_price": 14.99,
        "currency": "USD",
        "last_updated": _utc(3),
    },
    {
        "_id": "027084002256",
        "name": "Hot Wheels 5-Car Set",
        "brand": "Mattel",
        "category": "Die-Cast Vehicles",
        "description": "5 assorted Hot Wheels die-cast vehicles, ages 3+",
        "image_url": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
        "quantity": 25,
        "reorder_point": 10,
        "cost_price": 4.99,
        "sell_price": 8.99,
        "currency": "USD",
        "last_updated": _utc(1),
    },
    {
        "_id": "076670207388",
        "name": "Rubik's Cube 3x3 Original",
        "brand": "Rubik's",
        "category": "Puzzles",
        "description": "Original 3x3 Rubik's Cube puzzle, ages 8+",
        "image_url": "https://images.unsplash.com/photo-1518791841217-8f162f1912da?w=400",
        "quantity": 7,
        "reorder_point": 3,
        "cost_price": 7.99,
        "sell_price": 14.99,
        "currency": "USD",
        "last_updated": _utc(2),
    },
    {
        "_id": "071662080716",
        "name": "Crayola 64 Crayons",
        "brand": "Crayola",
        "category": "Arts & Crafts",
        "description": "64 assorted crayon colors in a flip-top box, ages 3+",
        "image_url": "https://images.unsplash.com/photo-1513364776144-60967b0f800f?w=400",
        "quantity": 18,
        "reorder_point": 8,
        "cost_price": 4.99,
        "sell_price": 8.99,
        "currency": "USD",
        "last_updated": _utc(1),
    },
    {
        "_id": "887961831641",
        "name": "Barbie Fashion Doll",
        "brand": "Mattel",
        "category": "Dolls & Accessories",
        "description": "Barbie doll with fashion outfit and accessories",
        "image_url": "https://images.unsplash.com/photo-1594736797933-d0501ba2fe65?w=400",
        "quantity": 3,          # LOW STOCK — below reorder_point of 5
        "reorder_point": 5,
        "cost_price": 9.99,
        "sell_price": 19.99,
        "currency": "USD",
        "last_updated": _utc(0),
    },
    {
        "_id": "653569566328",
        "name": "Nerf N-Strike Elite Disruptor",
        "brand": "Hasbro",
        "category": "Outdoor & Active",
        "description": "Nerf blaster with rotating drum holds 6 darts, ages 8+",
        "image_url": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400",
        "quantity": 2,          # LOW STOCK — below reorder_point of 5
        "reorder_point": 5,
        "cost_price": 14.99,
        "sell_price": 27.99,
        "currency": "USD",
        "last_updated": _utc(0),
    },
]

STOCK_TRANSACTIONS = [
    {"_id": "tx-lego-restock-1", "item_id": "673419302616", "quantity_change": 24, "reason": "restock", "notes": "Weekly restock from LEGO distributor", "recorded_at": _utc(7)},
    {"_id": "tx-monopoly-sale-1", "item_id": "630509575008", "quantity_change": -2, "reason": "sale", "notes": None, "recorded_at": _utc(3)},
    {"_id": "tx-jenga-sale-1", "item_id": "021853006166", "quantity_change": -3, "reason": "sale", "notes": None, "recorded_at": _utc(2)},
    {"_id": "tx-jenga-sale-2", "item_id": "021853006166", "quantity_change": -2, "reason": "sale", "notes": None, "recorded_at": _utc(1)},
    {"_id": "tx-barbie-sale-1", "item_id": "887961831641", "quantity_change": -4, "reason": "sale", "notes": "Weekend sales", "recorded_at": _utc(1)},
    {"_id": "tx-nerf-sale-1", "item_id": "653569566328", "quantity_change": -5, "reason": "sale", "notes": "Back-to-school rush", "recorded_at": _utc(3)},
    {"_id": "tx-uno-restock-1", "item_id": "076930077054", "quantity_change": 12, "reason": "restock", "notes": None, "recorded_at": _utc(10)},
    {"_id": "tx-hotw-sale-1", "item_id": "027084002256", "quantity_change": -6, "reason": "sale", "notes": None, "recorded_at": _utc(4)},
    {"_id": "tx-rubik-sale-1", "item_id": "076670207388", "quantity_change": -2, "reason": "sale", "notes": None, "recorded_at": _utc(5)},
    {"_id": "tx-playdoh-sale-1", "item_id": "653569819431", "quantity_change": -4, "reason": "sale", "notes": None, "recorded_at": _utc(2)},
]


# ---------------------------------------------------------------------------
# Price watchlist
# ---------------------------------------------------------------------------

PRICE_WATCHLIST = [
    {
        "_id": "watch-lego-vendor",
        "label": "LEGO Classic Creative Bricks",
        "mode": "vendor",
        "active": True,
        "region": "US",
        "query": "LEGO Classic Creative Bricks wholesale",
        "notes": "Monitor for bulk pricing below $25/unit",
        "baseline": {"supplier": "LEGO Direct", "price": 29.99, "currency": "USD", "unit": "each", "quantity": 1},
        "threshold_pct": 10.0,
        "last_scan_at": _utc(1),
        "last_alert_at": None,
    },
    {
        "_id": "watch-monopoly-competitor",
        "label": "Monopoly Classic",
        "mode": "competitor",
        "active": True,
        "region": "US",
        "query": "Monopoly Classic board game retail price",
        "notes": "Track competitor pricing vs our $24.99",
        "baseline": {"supplier": "Our Store", "price": 24.99, "currency": "USD", "unit": "each", "quantity": 1},
        "threshold_pct": 5.0,
        "last_scan_at": _utc(2),
        "last_alert_at": _utc(5),
    },
    {
        "_id": "watch-playdoh-vendor",
        "label": "Play-Doh 4-Pack",
        "mode": "vendor",
        "active": True,
        "region": "US",
        "query": "Play-Doh 4 pack wholesale supplier",
        "notes": None,
        "baseline": {"supplier": "Hasbro Wholesale", "price": 7.99, "currency": "USD", "unit": "each", "quantity": 1},
        "threshold_pct": 8.0,
        "last_scan_at": _utc(3),
        "last_alert_at": None,
    },
]

PRICE_FINDINGS = [
    {
        "_id": "finding-lego-1",
        "watch_id": "watch-lego-vendor",
        "product_name": "LEGO Classic Creative Bricks 900pcs",
        "label": "LEGO Classic Creative Bricks",
        "scanned_at": _utc(1),
        "scraped_price": 27.50,
        "baseline": {"supplier": "LEGO Direct", "price": 29.99},
        "best_option": {"supplier": "ToysWholesale.com", "price": 25.49, "currency": "USD", "unit": "each", "url": "https://example.com/lego"},
        "candidates": [{"supplier": "AliExpress", "price": 23.00}, {"supplier": "ToysWholesale.com", "price": 25.49}],
        "confidence": "high",
        "notes": "15% below baseline price",
        "delta_pct": -15.0,
    },
    {
        "_id": "finding-monopoly-1",
        "watch_id": "watch-monopoly-competitor",
        "product_name": "Monopoly Classic Board Game",
        "label": "Monopoly Classic",
        "scanned_at": _utc(2),
        "scraped_price": 22.99,
        "baseline": {"supplier": "Our Store", "price": 24.99},
        "best_option": {"supplier": "Target.com", "price": 22.99, "currency": "USD", "unit": "each", "url": "https://example.com/monopoly"},
        "candidates": [{"supplier": "Walmart", "price": 23.49}, {"supplier": "Target.com", "price": 22.99}],
        "confidence": "high",
        "notes": "Competitor undercutting by $2",
        "delta_pct": -8.0,
    },
]

PRICE_ALERTS = [
    {
        "_id": "alert-monopoly-1",
        "watch_id": "watch-monopoly-competitor",
        "status": "new",
        "created_at": _utc(2),
        "acknowledged_at": None,
        "summary": "Target is selling Monopoly Classic at $22.99, undercutting your price of $24.99 by 8%. Consider a price match.",
        "baseline": {"supplier": "Our Store", "price": 24.99},
        "best_option": {"supplier": "Target.com", "price": 22.99},
        "delta_pct": -8.0,
        "notes": None,
    },
]


# ---------------------------------------------------------------------------
# Procurement
# ---------------------------------------------------------------------------

PROCUREMENT_ITEMS = [
    {
        "_id": "proc-jenga",
        "name": "Jenga Classic Game",
        "quantity_needed": 12,
        "budget_per_unit": 10.00,
        "currency": "USD",
        "notes": "Low stock — need restock ASAP",
        "active": True,
        "last_sourced_at": None,
    },
    {
        "_id": "proc-barbie",
        "name": "Barbie Fashion Doll",
        "quantity_needed": 10,
        "budget_per_unit": 12.00,
        "currency": "USD",
        "notes": "Popular item, frequent sell-outs",
        "active": True,
        "last_sourced_at": None,
    },
    {
        "_id": "proc-nerf",
        "name": "Nerf N-Strike Elite Disruptor",
        "quantity_needed": 8,
        "budget_per_unit": 17.00,
        "currency": "USD",
        "notes": "Back-to-school high demand",
        "active": True,
        "last_sourced_at": None,
    },
]

KNOWN_SUPPLIERS = [
    {
        "_id": "sup-hasbro",
        "name": "Hasbro Direct Wholesale",
        "categories": ["Board Games", "Outdoor & Active", "Arts & Crafts"],
        "contact_email": "wholesale@hasbro.com",
        "contact_phone": "1-800-327-8264",
        "notes": "Minimum order $500. Net 30 terms. Free shipping over $1000.",
        "active": True,
    },
    {
        "_id": "sup-mattel",
        "name": "Mattel Wholesale",
        "categories": ["Dolls & Accessories", "Die-Cast Vehicles", "Card Games"],
        "contact_email": "wholesale@mattel.com",
        "contact_phone": "1-800-524-8697",
        "notes": "Minimum order 24 units per SKU. Net 30 terms.",
        "active": True,
    },
    {
        "_id": "sup-toysdist",
        "name": "National Toy Distributors",
        "categories": ["Board Games", "Puzzles", "Building Toys", "Card Games"],
        "contact_email": "orders@nationaltoy.com",
        "contact_phone": "1-888-555-0192",
        "notes": "Multi-brand distributor. Good for mixed orders under MOQ.",
        "active": True,
    },
]

SUPPLIER_CATALOG = [
    {
        "_id": "cat-hasbro-jenga",
        "supplier_id": "sup-hasbro",
        "product_keyword": "jenga",
        "cost_per_unit": 8.50,
        "currency": "USD",
        "moq": 12,
        "typical_sell_price": 16.99,
        "target_margin_pct": 35.0,
        "last_updated": _utc(30),
    },
    {
        "_id": "cat-hasbro-monopoly",
        "supplier_id": "sup-hasbro",
        "product_keyword": "monopoly",
        "cost_per_unit": 13.50,
        "currency": "USD",
        "moq": 6,
        "typical_sell_price": 24.99,
        "target_margin_pct": 30.0,
        "last_updated": _utc(30),
    },
    {
        "_id": "cat-mattel-barbie",
        "supplier_id": "sup-mattel",
        "product_keyword": "barbie",
        "cost_per_unit": 9.25,
        "currency": "USD",
        "moq": 24,
        "typical_sell_price": 19.99,
        "target_margin_pct": 32.0,
        "last_updated": _utc(30),
    },
    {
        "_id": "cat-mattel-hotwheels",
        "supplier_id": "sup-mattel",
        "product_keyword": "hot wheels",
        "cost_per_unit": 4.50,
        "currency": "USD",
        "moq": 36,
        "typical_sell_price": 8.99,
        "target_margin_pct": 30.0,
        "last_updated": _utc(30),
    },
    {
        "_id": "cat-toysdist-nerf",
        "supplier_id": "sup-toysdist",
        "product_keyword": "nerf",
        "cost_per_unit": 13.99,
        "currency": "USD",
        "moq": 6,
        "typical_sell_price": 27.99,
        "target_margin_pct": 35.0,
        "last_updated": _utc(30),
    },
]


# ---------------------------------------------------------------------------
# Sales (for trend analysis via aggregation pipeline)
# ---------------------------------------------------------------------------

def _build_sales():
    """Generate 12 months of realistic sales data for the toy store."""
    records = []
    categories = {
        "Board Games": [
            ("MONO-001", "Monopoly Classic", 24.99),
            ("JENGA-001", "Jenga Classic", 16.99),
        ],
        "Building Toys": [
            ("LEGO-001", "LEGO Classic Creative Bricks", 44.99),
        ],
        "Card Games": [
            ("UNO-001", "UNO Card Game", 9.99),
        ],
        "Arts & Crafts": [
            ("CRYL-001", "Crayola 64 Crayons", 8.99),
            ("PLAY-001", "Play-Doh 4-Pack", 14.99),
        ],
        "Die-Cast Vehicles": [
            ("HOTW-001", "Hot Wheels 5-Car Set", 8.99),
        ],
        "Dolls & Accessories": [
            ("BARB-001", "Barbie Fashion Doll", 19.99),
        ],
        "Outdoor & Active": [
            ("NERF-001", "Nerf N-Strike Elite Disruptor", 27.99),
        ],
        "Puzzles": [
            ("RUBK-001", "Rubik's Cube 3x3 Original", 14.99),
        ],
    }

    import random
    random.seed(42)
    today = datetime.now(timezone.utc)

    # Seasonal multipliers (month 1=Jan…12=Dec)
    # Toys peak in Nov-Dec (holiday), summer (Jun-Aug)
    seasonal = {1: 0.7, 2: 0.6, 3: 0.8, 4: 0.9, 5: 1.0, 6: 1.2,
                7: 1.3, 8: 1.2, 9: 0.9, 10: 0.9, 11: 1.5, 12: 1.8}

    for days_back in range(365):
        date = today - timedelta(days=days_back)
        month = date.month
        date_str = date.strftime("%Y-%m-%d")
        factor = seasonal[month]

        for cat, skus in categories.items():
            for sku, name, price in skus:
                if random.random() < 0.3 * factor:
                    qty = random.randint(1, int(3 * factor) + 1)
                    records.append({
                        "sku": sku,
                        "product_name": name,
                        "category": cat,
                        "sale_date": date_str,
                        "quantity_sold": qty,
                        "unit_price": price,
                    })

    return records


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------


def seed(clear: bool = False) -> None:
    db = get_db()

    collections = {
        "inventory": INVENTORY_ITEMS,
        "stock_transactions": STOCK_TRANSACTIONS,
        "price_watchlist": PRICE_WATCHLIST,
        "price_findings": PRICE_FINDINGS,
        "price_alerts": PRICE_ALERTS,
        "procurement_items": PROCUREMENT_ITEMS,
        "known_suppliers": KNOWN_SUPPLIERS,
        "supplier_catalog": SUPPLIER_CATALOG,
    }

    if clear:
        for name in list(collections.keys()) + ["sales"]:
            db[name].drop()
        print("Cleared all collections.")

    for name, docs in collections.items():
        col = db[name]
        inserted = 0
        for doc in docs:
            try:
                col.insert_one(doc)
                inserted += 1
            except Exception:
                pass  # already exists
        print(f"  {name}: +{inserted} documents")

    # Sales data
    sales_col = db["sales"]
    if sales_col.count_documents({}) == 0:
        sales_docs = _build_sales()
        if sales_docs:
            sales_col.insert_many(sales_docs)
            print(f"  sales: +{len(sales_docs)} documents")
        sales_col.create_index([("category", 1)])
        sales_col.create_index([("sale_date", 1)])
        sales_col.create_index([("sku", 1)])
    else:
        print("  sales: already seeded (skipped)")

    print("\nDone. MongoDB is ready for the demo.")
    print("Barcodes you can scan:")
    for item in INVENTORY_ITEMS:
        flag = " *** LOW STOCK" if item["quantity"] <= item["reorder_point"] else ""
        print(f"  {item['_id']}  {item['name']}  (qty={item['quantity']}){flag}")


if __name__ == "__main__":
    clear = "--clear" in sys.argv
    seed(clear=clear)
