"""Store profiles, product categories, scenarios, and model settings."""

from __future__ import annotations
from models.store_profile import StoreProfile, InventoryItem, ConversationMemoryEntry

# ── Model settings (now Hermes via Nous Research) ──────────────────────────
MODEL_NAME = "nousresearch/hermes-4-70b"
SIGNAL_TEMPERATURE = 0.3
RECOMMENDATION_TEMPERATURE = 0.7
COORDINATOR_TEMPERATURE = 0.3
MAX_RETRIES = 1
DEBATE_ROUNDS = 3
DEBATE_TEMPERATURE = 0.8

# ── Product categories ─────────────────────────────────────────────────────
PRODUCT_CATEGORIES = [
    "snacks_beverages", "fresh_prepared", "clothing_accessories",
    "gifts_arrangements", "handmade_crafts", "health_beauty",
    "electronics_accessories", "seasonal_items", "local_artisan", "home_decor",
]

NOISE_SIGMA = 0.05

# ── Scenarios ──────────────────────────────────────────────────────────────
SCENARIOS: dict[str, dict[str, float]] = {
    "default": {cat: 1.0 for cat in PRODUCT_CATEGORIES},
    "holiday_rush": {
        "snacks_beverages": 2.2, "fresh_prepared": 1.8, "clothing_accessories": 2.5,
        "gifts_arrangements": 3.0, "handmade_crafts": 2.0, "health_beauty": 1.4,
        "electronics_accessories": 2.8, "seasonal_items": 3.5, "local_artisan": 1.6,
        "home_decor": 2.0,
    },
    "new_trend": {
        "snacks_beverages": 1.2, "fresh_prepared": 1.1, "clothing_accessories": 2.8,
        "gifts_arrangements": 1.5, "handmade_crafts": 2.5, "health_beauty": 1.3,
        "electronics_accessories": 1.0, "seasonal_items": 0.9, "local_artisan": 2.2,
        "home_decor": 1.8,
    },
}

SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "default": "Normal market conditions — steady demand across all categories.",
    "holiday_rush": "Holiday & finals season surge — gifts, seasonal items, and snacks spike. Electronics hold strong.",
    "new_trend": "Viral social media trend — streetwear and handmade crafts explode. Seasonal items soften.",
}


def build_store_profiles() -> list[StoreProfile]:
    """Build the demo store profiles with hardcoded inventory data."""
    stores = [
        StoreProfile(
            store_id="store_a",
            store_name="College Convenience & Deli",
            specialty="Convenience store + deli near campus",
            location="College Street",
            constraints="Limited storage, high rent near campus",
            goals="Maximize grab-and-go sales, keep deli fresh and stocked",
            inventory=[
                InventoryItem("snacks_beverages", 200, 300, 40.0),
                InventoryItem("fresh_prepared", 80, 120, 25.0),
                InventoryItem("clothing_accessories", 10, 20, 0.5),
                InventoryItem("gifts_arrangements", 5, 15, 0.3),
                InventoryItem("handmade_crafts", 0, 5, 0.0),
                InventoryItem("health_beauty", 60, 100, 8.0),
                InventoryItem("electronics_accessories", 45, 80, 5.0),
                InventoryItem("seasonal_items", 30, 60, 3.0),
                InventoryItem("local_artisan", 10, 20, 0.5),
                InventoryItem("home_decor", 5, 10, 0.2),
            ],
            conversation_memory=[
                ConversationMemoryEntry("2026-03-15", "Energy drinks and cold brew flying off shelves during midterms"),
                ConversationMemoryEntry("2026-03-20", "Deli sandwich sales up 30% since adding new menu items"),
            ],
        ),
        StoreProfile(
            store_id="store_b",
            store_name="Grails",
            specialty="Sneakers, streetwear, and vintage clothing",
            location="Chapel Street",
            constraints="High rent on Chapel St, limited floor space for displays",
            goals="Dominate local sneaker resale market, grow streetwear brand partnerships",
            inventory=[
                InventoryItem("snacks_beverages", 5, 10, 0.3),
                InventoryItem("fresh_prepared", 0, 0, 0.0),
                InventoryItem("clothing_accessories", 180, 250, 12.0),
                InventoryItem("gifts_arrangements", 10, 20, 0.5),
                InventoryItem("handmade_crafts", 15, 30, 1.0),
                InventoryItem("health_beauty", 20, 40, 1.5),
                InventoryItem("electronics_accessories", 25, 50, 2.0),
                InventoryItem("seasonal_items", 40, 70, 3.0),
                InventoryItem("local_artisan", 15, 30, 1.0),
                InventoryItem("home_decor", 10, 25, 0.5),
            ],
            conversation_memory=[
                ConversationMemoryEntry("2026-03-18", "New Jordan drop brought huge foot traffic last weekend"),
                ConversationMemoryEntry("2026-03-22", "Vintage Yale gear selling well to visiting parents"),
            ],
        ),
        StoreProfile(
            store_id="store_c",
            store_name="Edible Arrangements",
            specialty="Fresh fruit arrangements and gift baskets",
            location="Whalley Avenue",
            constraints="Perishable inventory, tight delivery windows",
            goals="Grow corporate gifting accounts, expand holiday pre-orders",
            inventory=[
                InventoryItem("snacks_beverages", 30, 60, 4.0),
                InventoryItem("fresh_prepared", 100, 160, 18.0),
                InventoryItem("clothing_accessories", 0, 0, 0.0),
                InventoryItem("gifts_arrangements", 150, 200, 20.0),
                InventoryItem("handmade_crafts", 10, 25, 1.0),
                InventoryItem("health_beauty", 5, 15, 0.3),
                InventoryItem("electronics_accessories", 0, 0, 0.0),
                InventoryItem("seasonal_items", 80, 120, 10.0),
                InventoryItem("local_artisan", 20, 40, 2.0),
                InventoryItem("home_decor", 15, 30, 1.0),
            ],
            conversation_memory=[
                ConversationMemoryEntry("2026-03-20", "Corporate orders picking up for spring events"),
                ConversationMemoryEntry("2026-03-25", "Fruit sourcing costs up 15% — need to revisit pricing"),
            ],
        ),
        StoreProfile(
            store_id="store_d",
            store_name="Tinaliah Designs",
            specialty="Custom jewelry and handmade accessories",
            location="Audubon Street",
            constraints="Small studio space, handmade production limits volume",
            goals="Grow online orders, expand custom commission pipeline",
            inventory=[
                InventoryItem("snacks_beverages", 0, 0, 0.0),
                InventoryItem("fresh_prepared", 0, 0, 0.0),
                InventoryItem("clothing_accessories", 60, 90, 4.0),
                InventoryItem("gifts_arrangements", 35, 60, 3.0),
                InventoryItem("handmade_crafts", 120, 180, 8.0),
                InventoryItem("health_beauty", 25, 45, 2.0),
                InventoryItem("electronics_accessories", 5, 10, 0.3),
                InventoryItem("seasonal_items", 40, 70, 3.5),
                InventoryItem("local_artisan", 80, 120, 5.0),
                InventoryItem("home_decor", 45, 70, 3.0),
            ],
            conversation_memory=[
                ConversationMemoryEntry("2026-03-19", "Custom engagement ring orders booked out 3 weeks"),
                ConversationMemoryEntry("2026-03-24", "Yale graduation season coming — expect spike in gift jewelry"),
            ],
        ),
        StoreProfile(
            store_id="store_e",
            store_name="The Marketa",
            specialty="Local artisan market and handmade goods",
            location="State Street",
            constraints="Multi-vendor consignment model, thin margins per item",
            goals="Grow vendor base, become the go-to New Haven artisan destination",
            inventory=[
                InventoryItem("snacks_beverages", 25, 50, 3.0),
                InventoryItem("fresh_prepared", 20, 40, 2.5),
                InventoryItem("clothing_accessories", 50, 80, 3.5),
                InventoryItem("gifts_arrangements", 40, 65, 3.0),
                InventoryItem("handmade_crafts", 90, 140, 6.0),
                InventoryItem("health_beauty", 35, 60, 2.5),
                InventoryItem("electronics_accessories", 10, 20, 0.5),
                InventoryItem("seasonal_items", 55, 90, 4.0),
                InventoryItem("local_artisan", 110, 160, 7.0),
                InventoryItem("home_decor", 70, 100, 4.5),
            ],
            conversation_memory=[
                ConversationMemoryEntry("2026-03-17", "Three new vendors onboarded this month — candles, pottery, and soaps"),
                ConversationMemoryEntry("2026-03-23", "Weekend pop-up events doubling foot traffic on State Street"),
            ],
        ),
    ]
    return stores
