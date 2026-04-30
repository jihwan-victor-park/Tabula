"""Data models for store profiles, inventory, and conversation memory."""

from __future__ import annotations
from dataclasses import dataclass, field
import json


@dataclass
class InventoryItem:
    category: str
    stock: int
    capacity: int
    avg_daily_sales: float

    @property
    def days_of_supply(self) -> float:
        if self.avg_daily_sales <= 0:
            return 999.0
        return round(self.stock / self.avg_daily_sales, 1)

    @property
    def utilization(self) -> float:
        if self.capacity <= 0:
            return 0.0
        return round(self.stock / self.capacity, 2)

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "stock": self.stock,
            "capacity": self.capacity,
            "avg_daily_sales": self.avg_daily_sales,
            "days_of_supply": self.days_of_supply,
            "utilization": self.utilization,
        }


@dataclass
class ConversationMemoryEntry:
    timestamp: str
    note: str

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "note": self.note}


@dataclass
class StoreProfile:
    store_id: str
    store_name: str
    specialty: str
    location: str
    constraints: str
    goals: str
    inventory: list[InventoryItem] = field(default_factory=list)
    conversation_memory: list[ConversationMemoryEntry] = field(default_factory=list)
    spreadsheet_summary: str = ""

    def get_inventory_by_category(self, category: str) -> InventoryItem | None:
        for item in self.inventory:
            if item.category == category:
                return item
        return None

    def context_summary(self) -> str:
        lines = [
            f"Store: {self.store_name}",
            f"Specialty: {self.specialty}",
            f"Location: {self.location}",
            f"Constraints: {self.constraints}",
            f"Goals: {self.goals}",
        ]
        if self.conversation_memory:
            lines.append("Owner notes:")
            for m in self.conversation_memory:
                lines.append(f"  [{m.timestamp}] {m.note}")
        if self.spreadsheet_summary:
            lines.append(f"Spreadsheet data:\n{self.spreadsheet_summary}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "store_id": self.store_id,
            "store_name": self.store_name,
            "specialty": self.specialty,
            "location": self.location,
            "constraints": self.constraints,
            "goals": self.goals,
            "inventory": [i.to_dict() for i in self.inventory],
            "conversation_memory": [m.to_dict() for m in self.conversation_memory],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
