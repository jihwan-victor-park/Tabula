"""Data models for store recommendations."""

from __future__ import annotations
from dataclasses import dataclass, field
import json


@dataclass
class Recommendation:
    category: str
    action: str             # "increase_stock" | "reduce_stock" | "promote" | "hold" | "discontinue"
    reasoning: str
    confidence: float       # 0.0 - 1.0
    priority: str           # "high" | "medium" | "low"

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "action": self.action,
            "reasoning": self.reasoning,
            "confidence": round(self.confidence, 3),
            "priority": self.priority,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class StoreRecommendationBundle:
    store_id: str
    store_name: str
    generated_at: str
    recommendations: list[Recommendation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "store_id": self.store_id,
            "store_name": self.store_name,
            "generated_at": self.generated_at,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
